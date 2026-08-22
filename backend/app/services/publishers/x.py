"""X (Twitter) publisher — direct tweets via the v2 API with in-repo OAuth 1.0a.

Text tweets go to ``POST https://api.x.com/2/tweets``; media is uploaded
first through the v1.1 media endpoint (simple upload for images, chunked
INIT/APPEND/FINALIZE with a STATUS poll for video) and attached to the tweet
via ``media.media_ids``. Requests are signed with OAuth 1.0a user context
(HMAC-SHA1, RFC 5849) implemented in this module — no extra dependency; the
signer is unit-tested against the worked example in X's "Creating a
signature" documentation. Credentials come from the brand's per-channel
config (``consumer_key`` / ``consumer_secret`` / ``access_token`` /
``access_token_secret``).
"""

import base64
import hashlib
import hmac
import logging
import secrets
import time
from typing import Any
from urllib.parse import quote

import httpx

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

TWEETS_URL = "https://api.x.com/2/tweets"
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"

TWEET_MAX_CHARS = 280
TWEET_ELLIPSIS = "…"

# v1.1 chunked APPEND accepts at most 5MB per segment; stay under it.
UPLOAD_CHUNK_SIZE = 4 * 1024 * 1024

VIDEO_STATUS_POLL_INTERVAL_SECONDS = 5
VIDEO_STATUS_POLL_TIMEOUT_SECONDS = 300


# ── OAuth 1.0a signing (RFC 5849, HMAC-SHA1) ────────────────────────────


def _pct(value: Any) -> str:
    """RFC 3986 percent-encoding as required by RFC 5849 §3.6.

    Python's ``quote`` never encodes the unreserved set (letters, digits,
    ``_.-~``); ``safe=""`` encodes everything else, spaces included.
    """
    return quote(str(value), safe="")


def oauth1_signature(
    method: str,
    url: str,
    params: dict[str, Any],
    consumer_secret: str,
    token_secret: str,
) -> str:
    """HMAC-SHA1 signature over the RFC 5849 §3.4.1 signature base string.

    ``params`` are ALL request parameters that participate in the signature:
    the ``oauth_*`` protocol parameters plus any query-string and
    form-urlencoded body parameters (JSON and multipart bodies contribute
    nothing). ``url`` must be the base URL without a query string.
    """
    pairs = sorted((_pct(k), _pct(v)) for k, v in params.items())
    param_string = "&".join(f"{k}={v}" for k, v in pairs)
    base_string = "&".join([method.upper(), _pct(url), _pct(param_string)])
    signing_key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    digest = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1)
    return base64.b64encode(digest.digest()).decode()


def oauth1_auth_header(
    method: str,
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    request_params: dict[str, Any] | None = None,
    nonce: str | None = None,
    timestamp: int | None = None,
) -> str:
    """Build the ``Authorization: OAuth …`` header for one signed request.

    ``request_params`` are the non-oauth request parameters that must be
    covered by the signature (query params, and body params only when the
    body is ``application/x-www-form-urlencoded``). ``nonce``/``timestamp``
    are injectable for the documented-test-vector unit test.
    """
    oauth_params: dict[str, str] = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(timestamp or int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    signature = oauth1_signature(
        method,
        url,
        {**(request_params or {}), **oauth_params},
        consumer_secret,
        access_token_secret,
    )
    header_params = {**oauth_params, "oauth_signature": signature}
    return "OAuth " + ", ".join(
        f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(header_params.items())
    )


class _OAuth1Signer:
    """Bundles the four user-context credentials for per-request signing."""

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_token_secret: str,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret

    def header(
        self, method: str, url: str, request_params: dict[str, Any] | None = None
    ) -> str:
        return oauth1_auth_header(
            method,
            url,
            consumer_key=self.consumer_key,
            consumer_secret=self.consumer_secret,
            access_token=self.access_token,
            access_token_secret=self.access_token_secret,
            request_params=request_params,
        )


# ── Caption handling ────────────────────────────────────────────────────


def truncate_tweet(text: str, limit: int = TWEET_MAX_CHARS) -> str:
    """Truncate ``text`` to ``limit`` chars on a word boundary with ``…``.

    Cutting only at whitespace means no whitespace-delimited token is ever
    split — a URL near the cut is dropped whole rather than truncated
    mid-way. Only a single unbroken token longer than the limit (which a
    real caption never is) falls back to a hard cut.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - len(TWEET_ELLIPSIS)]
    boundary = max(cut.rfind(" "), cut.rfind("\n"), cut.rfind("\t"))
    if boundary > 0:
        cut = cut[:boundary]
    return cut.rstrip() + TWEET_ELLIPSIS


# ── Error mapping ───────────────────────────────────────────────────────


def _x_error_detail(resp: httpx.Response) -> str:
    """Readable detail from a v2 ({title, detail}) or v1.1 ({errors: […]}) body."""
    try:
        body = resp.json()
    except Exception:
        body = {}
    if isinstance(body, dict):
        # v1.1 media endpoint: {"errors": [{"code": …, "message": …}]}
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0] if isinstance(errors[0], dict) else {}
            message = first.get("message") or first.get("detail")
            if message:
                code = first.get("code")
                return f"{message} (code {code})" if code is not None else str(message)
        # v2: {"title": …, "detail": …, "status": …}
        detail = body.get("detail") or body.get("title")
        if detail:
            return str(detail)
        if body.get("error"):
            return str(body["error"])
    return f"HTTP {resp.status_code}: {resp.text[:300]}"


def _check(resp: httpx.Response, what: str) -> None:
    if resp.status_code < 400:
        return
    detail = f"{what} failed: {_x_error_detail(resp)}"
    if resp.status_code in (401, 403):
        detail += (
            " — check the X consumer/access keys in Brand > Channels > X "
            "(the app needs Read+Write access and a tier that allows posting)"
        )
    raise PublishError(detail)


def _json_body(resp: httpx.Response, what: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception:
        raise PublishError(
            f"{what} returned a non-JSON response (HTTP {resp.status_code})"
        )
    return body if isinstance(body, dict) else {}


# ── Publisher ───────────────────────────────────────────────────────────


class XPublisher(ChannelPublisher):
    """Publishes image, video and text-only tweets via the X APIs."""

    channel = "x"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        missing = [
            name
            for name in (
                "consumer_key",
                "consumer_secret",
                "access_token",
                "access_token_secret",
            )
            if not creds.get(name)
        ]
        if missing:
            raise PublishError(
                f"X channel not configured for this brand (missing "
                f"{', '.join(missing)}) — add the consumer/access keys in "
                "Brand > Channels > X."
            )
        signer = _OAuth1Signer(
            creds["consumer_key"],
            creds["consumer_secret"],
            creds["access_token"],
            creds["access_token_secret"],
        )

        caption, hashtags = resolve_caption_and_hashtags(content, self.channel)
        text = truncate_tweet(format_caption(caption, hashtags))

        async with self._http() as client:
            media_ids: list[str] = []
            # A bundle without bytes (e.g. no rendered image) → text-only tweet.
            if media.bytes_loader is not None:
                data = await media.get_bytes()
                if media.kind == "video":
                    media_ids.append(
                        await self._upload_video(client, signer, data, media.mime)
                    )
                else:
                    media_ids.append(
                        await self._upload_image(client, signer, data, media.mime)
                    )
            return await self._create_tweet(client, signer, text, media_ids)

    # ── Media upload (v1.1) ─────────────────────────────────────────────

    @staticmethod
    def _media_id(body: dict[str, Any], what: str) -> str:
        media_id = body.get("media_id_string") or body.get("media_id")
        if not media_id:
            raise PublishError(f"{what} returned no media id")
        return str(media_id)

    async def _upload_image(
        self,
        client: httpx.AsyncClient,
        signer: _OAuth1Signer,
        data: bytes,
        mime: str,
    ) -> str:
        """Simple (single-request) upload — multipart body, nothing to co-sign."""
        resp = await client.post(
            MEDIA_UPLOAD_URL,
            files={"media": ("media", data, mime or "application/octet-stream")},
            headers={"Authorization": signer.header("POST", MEDIA_UPLOAD_URL)},
        )
        _check(resp, "X image upload")
        return self._media_id(_json_body(resp, "X image upload"), "X image upload")

    async def _upload_video(
        self,
        client: httpx.AsyncClient,
        signer: _OAuth1Signer,
        data: bytes,
        mime: str,
    ) -> str:
        """Chunked INIT/APPEND/FINALIZE upload with a STATUS processing poll."""
        init_form = {
            "command": "INIT",
            "total_bytes": str(len(data)),
            "media_type": mime or "video/mp4",
            "media_category": "tweet_video",
        }
        resp = await client.post(
            MEDIA_UPLOAD_URL,
            data=init_form,
            headers={
                # Form-urlencoded body params participate in the signature.
                "Authorization": signer.header("POST", MEDIA_UPLOAD_URL, init_form)
            },
        )
        _check(resp, "X video upload INIT")
        media_id = self._media_id(
            _json_body(resp, "X video upload INIT"), "X video upload INIT"
        )

        for index in range(0, len(data), UPLOAD_CHUNK_SIZE):
            segment = index // UPLOAD_CHUNK_SIZE
            params = {
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": str(segment),
            }
            resp = await client.post(
                MEDIA_UPLOAD_URL,
                params=params,
                files={"media": data[index : index + UPLOAD_CHUNK_SIZE]},
                headers={
                    # Multipart body stays out of the signature; the query
                    # params carry the command and must be co-signed.
                    "Authorization": signer.header("POST", MEDIA_UPLOAD_URL, params)
                },
            )
            _check(resp, f"X video upload APPEND (segment {segment})")

        finalize_form = {"command": "FINALIZE", "media_id": media_id}
        resp = await client.post(
            MEDIA_UPLOAD_URL,
            data=finalize_form,
            headers={
                "Authorization": signer.header("POST", MEDIA_UPLOAD_URL, finalize_form)
            },
        )
        _check(resp, "X video upload FINALIZE")
        processing = _json_body(resp, "X video upload FINALIZE").get(
            "processing_info"
        ) or {}
        if processing and processing.get("state") != "succeeded":
            await self._wait_until_processed(client, signer, media_id)
        return media_id

    async def _wait_until_processed(
        self, client: httpx.AsyncClient, signer: _OAuth1Signer, media_id: str
    ) -> None:
        params = {"command": "STATUS", "media_id": media_id}

        async def _check_status() -> dict[str, Any] | None:
            resp = await client.get(
                MEDIA_UPLOAD_URL,
                params=params,
                headers={
                    "Authorization": signer.header("GET", MEDIA_UPLOAD_URL, params)
                },
            )
            _check(resp, "X video upload STATUS")
            info = _json_body(resp, "X video upload STATUS").get(
                "processing_info"
            ) or {}
            state = info.get("state")
            if state == "succeeded":
                return info
            if state == "failed":
                error = (info.get("error") or {}).get("message") or str(info)[:200]
                raise PublishError(f"X video processing failed: {error}")
            return None  # pending / in_progress — keep polling

        await poll_until(
            _check_status,
            interval_s=VIDEO_STATUS_POLL_INTERVAL_SECONDS,
            max_wait_s=VIDEO_STATUS_POLL_TIMEOUT_SECONDS,
            description=f"X media {media_id} processing",
        )

    # ── Tweet (v2) ──────────────────────────────────────────────────────

    async def _create_tweet(
        self,
        client: httpx.AsyncClient,
        signer: _OAuth1Signer,
        text: str,
        media_ids: list[str],
    ) -> PublishOutcome:
        payload: dict[str, Any] = {"text": text}
        if media_ids:
            payload["media"] = {"media_ids": media_ids}
        resp = await client.post(
            TWEETS_URL,
            json=payload,
            # JSON body → only the oauth_* params are signed (RFC 5849 §3.4.1.3).
            headers={"Authorization": signer.header("POST", TWEETS_URL)},
        )
        _check(resp, "X tweet creation")
        tweet_id = (_json_body(resp, "X tweet creation").get("data") or {}).get("id")
        if not tweet_id:
            raise PublishError("X tweet creation returned no tweet id")
        return PublishOutcome(
            platform_post_id=str(tweet_id),
            status="published",
            extra={
                "media_ids": media_ids,
                "url": f"https://x.com/i/web/status/{tweet_id}",
            },
        )
