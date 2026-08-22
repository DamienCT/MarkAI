"""TikTok publisher — direct video posts via the Content Posting API v2.

FILE_UPLOAD direct post: ``/v2/post/publish/video/init/`` opens the publish
(``source_info`` FILE_UPLOAD with chunk_size / total_chunk_count per
TikTok's chunking rules), the video bytes are PUT to the returned
``upload_url``, then ``/v2/post/publish/status/fetch/`` is polled until
PUBLISH_COMPLETE / FAILED.

``privacy_level`` comes from the brand's TikTok channel config and defaults
to SELF_ONLY: apps that have not passed TikTok's content-posting audit can
only post privately (self-visible) — TikTok rejects public posts from
unaudited apps, so SELF_ONLY is the safe default until the app is audited.

TikTok access tokens expire after 24 hours. When a request comes back
unauthorized and the brand config carries ``client_key`` /
``client_secret`` / ``refresh_token``, the token is refreshed via
``/v2/oauth/token/`` and the new token pair is written back into the
brand's channel config (``flag_modified`` — the caller's session commit
persists it).
"""

import logging
from collections.abc import Iterator
from typing import Any

import httpx
from sqlalchemy.orm.attributes import flag_modified

from app.services.publishers.base import (
    ChannelPublisher,
    MediaBundle,
    PublishError,
    PublishOutcome,
    format_caption,
    poll_until,
    resolve_caption_and_hashtags,
)

logger = logging.getLogger(__name__)

TIKTOK_API_BASE = "https://open.tiktokapis.com"
INIT_URL = f"{TIKTOK_API_BASE}/v2/post/publish/video/init/"
STATUS_URL = f"{TIKTOK_API_BASE}/v2/post/publish/status/fetch/"
TOKEN_URL = f"{TIKTOK_API_BASE}/v2/oauth/token/"

DEFAULT_PRIVACY_LEVEL = "SELF_ONLY"

# TikTok caps video titles at 2200 UTF-16 characters.
MAX_TITLE_CHARS = 2200

# Chunking rules: chunks must be 5–64MB (videos under 5MB upload whole as a
# single chunk); the final chunk absorbs the trailing remainder and may reach
# 128MB. Anything ≤64MB goes up in one chunk; larger videos use 10MB chunks.
MIN_CHUNK_SIZE = 5 * 1024 * 1024
MAX_SINGLE_CHUNK_SIZE = 64 * 1024 * 1024
CHUNK_SIZE = 10 * 1024 * 1024

STATUS_POLL_INTERVAL_SECONDS = 10
STATUS_POLL_TIMEOUT_SECONDS = 600

# error.code values that mean the access token is no longer usable.
_AUTH_ERROR_CODES = ("access_token_invalid", "token_expired")

_TOKEN_EXPIRED_HINT = (
    "TikTok access token expired — TikTok tokens live 24h. Add client_key/"
    "client_secret/refresh_token in Brand > Channels > TikTok so the backend "
    "can refresh it automatically, or reconnect TikTok to get fresh tokens."
)


def _plan_chunks(size: int) -> tuple[int, int]:
    """Return (chunk_size, total_chunk_count) per TikTok's FILE_UPLOAD rules."""
    if size <= MAX_SINGLE_CHUNK_SIZE:
        return size, 1
    return CHUNK_SIZE, size // CHUNK_SIZE


def _chunk_ranges(size: int, chunk_size: int, total: int) -> Iterator[tuple[int, int, int]]:
    """Yield (index, start, end_exclusive); the final chunk takes the remainder."""
    for index in range(total):
        start = index * chunk_size
        end = size if index == total - 1 else start + chunk_size
        yield index, start, end


def _tiktok_error(resp: httpx.Response) -> tuple[str, str]:
    """(code, message) from a TikTok envelope body ({data, error:{code,message}})."""
    try:
        err = resp.json().get("error") or {}
    except Exception:
        err = {}
    return str(err.get("code") or ""), str(err.get("message") or "")


def _is_auth_error(resp: httpx.Response) -> bool:
    if resp.status_code == 401:
        return True
    code, _ = _tiktok_error(resp)
    return code in _AUTH_ERROR_CODES


def _json_data(resp: httpx.Response, what: str) -> dict[str, Any]:
    """The ``data`` object of a TikTok envelope, failing actionably on non-JSON."""
    try:
        body = resp.json()
    except Exception:
        raise PublishError(
            f"{what} returned a non-JSON response (HTTP {resp.status_code})"
        )
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else {}


class TikTokPublisher(ChannelPublisher):
    """Publishes videos to a brand's TikTok account via FILE_UPLOAD direct post."""

    channel = "tiktok"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        if media.kind != "video":
            raise PublishError(
                "TikTok requires video content — images cannot be published "
                "to TikTok"
            )
        access_token = creds.get("access_token") or ""
        if not access_token:
            raise PublishError(
                "TikTok channel not configured for this brand (missing "
                "access_token) — connect TikTok in Brand > Channels > TikTok."
            )

        caption, hashtags = resolve_caption_and_hashtags(content, self.channel)
        title = format_caption(caption, hashtags)[:MAX_TITLE_CHARS]
        privacy_level = self._privacy_level(brand, creds)
        data = await media.get_bytes()
        chunk_size, total_chunks = _plan_chunks(len(data))

        init_payload = {
            "post_info": {
                "title": title,
                "privacy_level": privacy_level,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": len(data),
                "chunk_size": chunk_size,
                "total_chunk_count": total_chunks,
            },
        }

        async with self._http() as client:
            resp = await self._post_init(client, access_token, init_payload)
            if _is_auth_error(resp):
                # 24h token lifetime: refresh once and retry, or fail with
                # the actionable expiry message.
                access_token = await self._refresh_access_token(client, brand, creds)
                resp = await self._post_init(client, access_token, init_payload)
            self._check(resp, "TikTok publish init")
            init_data = _json_data(resp, "TikTok publish init")
            publish_id = init_data.get("publish_id")
            upload_url = init_data.get("upload_url")
            if not publish_id or not upload_url:
                raise PublishError(
                    "TikTok publish init returned no publish_id/upload_url"
                )

            await self._upload_chunks(
                client, upload_url, data, chunk_size, total_chunks, media.mime
            )
            status_data = await self._wait_until_published(
                client, access_token, publish_id
            )

        post_ids = status_data.get("publicaly_available_post_id") or []  # sic (TikTok's field name)
        platform_post_id = str(post_ids[0]) if post_ids else str(publish_id)
        return PublishOutcome(
            platform_post_id=platform_post_id,
            status="published",
            extra={"publish_id": publish_id, "privacy_level": privacy_level},
        )

    # ── Config ──────────────────────────────────────────────────────────

    @staticmethod
    def _channel_cfg(brand: Any) -> dict[str, Any]:
        guidelines = getattr(brand, "brand_guidelines", None) or {}
        channels = guidelines.get("channels") or {}
        cfg = channels.get("tiktok")
        return cfg if isinstance(cfg, dict) else {}

    def _privacy_level(self, brand: Any, creds: dict[str, Any]) -> str:
        return (
            creds.get("privacy_level")
            or self._channel_cfg(brand).get("privacy_level")
            or DEFAULT_PRIVACY_LEVEL
        )

    # ── HTTP steps ──────────────────────────────────────────────────────

    @staticmethod
    def _auth_headers(access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

    async def _post_init(
        self, client: httpx.AsyncClient, access_token: str, payload: dict[str, Any]
    ) -> httpx.Response:
        return await client.post(
            INIT_URL, json=payload, headers=self._auth_headers(access_token)
        )

    @staticmethod
    def _check(resp: httpx.Response, what: str) -> None:
        code, message = _tiktok_error(resp)
        if resp.status_code == 401 or code in _AUTH_ERROR_CODES:
            raise PublishError(f"{what} failed: {_TOKEN_EXPIRED_HINT}")
        if resp.status_code >= 400 or (code and code != "ok"):
            detail = message or f"HTTP {resp.status_code}"
            if code and code != "ok":
                detail = f"{detail} (code {code})"
            raise PublishError(f"{what} failed: {detail}")

    async def _refresh_access_token(
        self, client: httpx.AsyncClient, brand: Any, creds: dict[str, Any]
    ) -> str:
        client_key = creds.get("client_key") or ""
        client_secret = creds.get("client_secret") or ""
        refresh_token = creds.get("refresh_token") or ""
        if not (client_key and client_secret and refresh_token):
            raise PublishError(_TOKEN_EXPIRED_HINT)

        resp = await client.post(
            TOKEN_URL,
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            body = resp.json()
        except Exception:
            body = {}
        new_access = body.get("access_token")
        if resp.status_code >= 400 or not new_access:
            # error/error_description are OAuth error CODES, never token values.
            detail = (
                body.get("error_description")
                or body.get("error")
                or f"HTTP {resp.status_code}"
            )
            raise PublishError(
                f"TikTok token refresh failed ({detail}) — reconnect TikTok "
                "in Brand > Channels > TikTok. (TikTok access tokens live 24h.)"
            )
        new_refresh = body.get("refresh_token") or refresh_token
        creds["access_token"] = new_access
        creds["refresh_token"] = new_refresh
        self._write_back_tokens(brand, new_access, new_refresh)
        return new_access

    @staticmethod
    def _write_back_tokens(brand: Any, access_token: str, refresh_token: str) -> None:
        """Persist refreshed tokens into the brand's TikTok channel config.

        Mutates the JSONB in place and marks it dirty with ``flag_modified``
        so the dispatcher's ``record_publish_result`` commit persists it.
        """
        guidelines = brand.brand_guidelines or {}
        channels = guidelines.setdefault("channels", {})
        cfg = channels.setdefault("tiktok", {})
        cfg["access_token"] = access_token
        cfg["refresh_token"] = refresh_token
        brand.brand_guidelines = guidelines
        flag_modified(brand, "brand_guidelines")
        logger.info(
            "TikTok access token refreshed for brand %s — new tokens written "
            "back to the channel config",
            getattr(brand, "id", "?"),
        )

    async def _upload_chunks(
        self,
        client: httpx.AsyncClient,
        upload_url: str,
        data: bytes,
        chunk_size: int,
        total_chunks: int,
        mime: str,
    ) -> None:
        # NOTE: upload_url is a pre-signed TikTok storage URL — treat it as a
        # credential (never log it, never put it in an error message; httpx
        # errors are reduced to their type so no URL-bearing text escapes).
        for index, start, end in _chunk_ranges(len(data), chunk_size, total_chunks):
            try:
                resp = await client.put(
                    upload_url,
                    content=data[start:end],
                    headers={
                        "Content-Type": mime or "video/mp4",
                        "Content-Range": f"bytes {start}-{end - 1}/{len(data)}",
                    },
                )
            except httpx.HTTPError as exc:
                raise PublishError(
                    f"TikTok video chunk upload failed: {type(exc).__name__} "
                    f"(chunk {index + 1}/{total_chunks})"
                ) from None
            if resp.status_code >= 400:
                raise PublishError(
                    f"TikTok video chunk upload failed (HTTP {resp.status_code}, "
                    f"chunk {index + 1}/{total_chunks})"
                )

    async def _wait_until_published(
        self, client: httpx.AsyncClient, access_token: str, publish_id: str
    ) -> dict[str, Any]:
        async def _fetch_status() -> dict[str, Any] | None:
            resp = await client.post(
                STATUS_URL,
                json={"publish_id": publish_id},
                headers=self._auth_headers(access_token),
            )
            self._check(resp, "TikTok publish status fetch")
            data = _json_data(resp, "TikTok publish status fetch")
            status = data.get("status")
            if status == "PUBLISH_COMPLETE":
                return data
            if status in ("FAILED", "PUBLISH_FAILED"):
                reason = data.get("fail_reason") or "unknown reason"
                raise PublishError(f"TikTok publish failed: {reason}")
            return None  # PROCESSING_UPLOAD / SEND_TO_USER_INBOX — keep polling

        return await poll_until(
            _fetch_status,
            interval_s=STATUS_POLL_INTERVAL_SECONDS,
            max_wait_s=STATUS_POLL_TIMEOUT_SECONDS,
            description=f"TikTok publish {publish_id}",
        )
