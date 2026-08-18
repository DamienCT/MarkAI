"""Instagram + Facebook publishers (Meta Graph API v25.0).

Implements the direct publish flows:
- Instagram images: media container -> media_publish.
- Instagram Reels: REELS container -> status polling -> media_publish.
- Facebook images: /{page_id}/photos (proper photo posts, not link posts).
- Facebook Reels: 3-phase video_reels flow (start -> rupload binary -> finish)
  with best-effort status polling.
"""

import logging
from typing import Any

import httpx

# Page-token derivation lives in publish_service (no import cycle: it only
# imports config/models/httpx). Module-level name so tests can monkeypatch it.
from app.services.publish_service import _derive_facebook_page_token
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

GRAPH_BASE = "https://graph.facebook.com/v25.0"
RUPLOAD_BASE = "https://rupload.facebook.com/video-upload/v25.0"


class _StatusPollUnavailable(Exception):
    """Status polling broke (HTTP/transport) — not a publish failure per se."""


def _graph_error_detail(resp: httpx.Response) -> str:
    """Readable detail from a Graph API error body ({error: {message, code, error_subcode}})."""
    try:
        err = resp.json().get("error") or {}
    except Exception:
        err = {}
    if err:
        detail = err.get("message") or "Unknown Graph API error"
        if err.get("error_user_msg"):
            detail = f"{detail} — {err['error_user_msg']}"
        code = err.get("code")
        subcode = err.get("error_subcode")
        suffix = ", ".join(
            part
            for part in (
                f"code {code}" if code is not None else None,
                f"subcode {subcode}" if subcode is not None else None,
            )
            if part
        )
        return f"{detail} ({suffix})" if suffix else detail
    return f"HTTP {resp.status_code}: {resp.text[:300]}"


async def _graph_post(
    client: httpx.AsyncClient, url: str, data: dict[str, Any], *, what: str
) -> dict[str, Any]:
    resp = await client.post(url, data=data)
    if resp.status_code >= 400:
        raise PublishError(f"{what} failed: {_graph_error_detail(resp)}")
    try:
        return resp.json()
    except Exception:
        raise PublishError(f"{what} returned a non-JSON response (HTTP {resp.status_code})")


async def _graph_get(
    client: httpx.AsyncClient, url: str, params: dict[str, Any], *, what: str
) -> dict[str, Any]:
    resp = await client.get(url, params=params)
    if resp.status_code >= 400:
        raise PublishError(f"{what} failed: {_graph_error_detail(resp)}")
    try:
        return resp.json()
    except Exception:
        raise PublishError(f"{what} returned a non-JSON response (HTTP {resp.status_code})")


class InstagramPublisher(ChannelPublisher):
    """Publishes images and Reels via the IG Content Publishing API."""

    channel = "instagram"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        token = creds.get("meta_access_token") or ""
        ig_user_id = creds.get("instagram_account_id") or ""
        if not token or not ig_user_id:
            raise PublishError(
                "Instagram credentials missing (meta_access_token / instagram_account_id). "
                "Set them in Brand > Channels > Instagram."
            )
        if not media.public_url:
            raise PublishError("Instagram needs a public media URL to pull from")

        caption_text, hashtags = resolve_caption_and_hashtags(content, self.channel)
        caption = format_caption(caption_text, hashtags)

        async with self._http() as client:
            if media.kind == "video":
                return await self._publish_reel(client, ig_user_id, token, caption, media)
            return await self._publish_image(client, ig_user_id, token, caption, media)

    async def _publish_image(
        self,
        client: httpx.AsyncClient,
        ig_user_id: str,
        token: str,
        caption: str,
        media: MediaBundle,
    ) -> PublishOutcome:
        container = await _graph_post(
            client,
            f"{GRAPH_BASE}/{ig_user_id}/media",
            {"image_url": media.public_url, "caption": caption, "access_token": token},
            what="Instagram image container creation",
        )
        container_id = container.get("id")
        if not container_id:
            raise PublishError("Instagram container creation returned no id")
        published = await _graph_post(
            client,
            f"{GRAPH_BASE}/{ig_user_id}/media_publish",
            {"creation_id": container_id, "access_token": token},
            what="Instagram media publish",
        )
        post_id = published.get("id")
        if not post_id:
            raise PublishError("Instagram media_publish returned no id")
        return PublishOutcome(
            platform_post_id=str(post_id),
            status="published",
            extra={"creation_id": container_id},
        )

    async def _publish_reel(
        self,
        client: httpx.AsyncClient,
        ig_user_id: str,
        token: str,
        caption: str,
        media: MediaBundle,
    ) -> PublishOutcome:
        await self._warn_if_quota_low(client, ig_user_id, token)

        container = await _graph_post(
            client,
            f"{GRAPH_BASE}/{ig_user_id}/media",
            {
                "media_type": "REELS",
                "video_url": media.public_url,
                "caption": caption,
                "share_to_feed": "true",
                "access_token": token,
            },
            what="Instagram Reels container creation",
        )
        container_id = container.get("id")
        if not container_id:
            raise PublishError("Instagram Reels container creation returned no id")

        async def _check_container() -> dict[str, Any] | None:
            data = await _graph_get(
                client,
                f"{GRAPH_BASE}/{container_id}",
                {"fields": "status_code,status", "access_token": token},
                what="Instagram container status check",
            )
            status_code = data.get("status_code")
            if status_code == "FINISHED":
                return data
            if status_code in ("ERROR", "EXPIRED"):
                detail = data.get("status") or status_code
                raise PublishError(f"Instagram Reels container {status_code}: {detail}")
            return None  # IN_PROGRESS / PUBLISHED-pending — keep polling

        await poll_until(
            _check_container,
            interval_s=10,
            max_wait_s=300,
            description=f"Instagram Reels container {container_id} processing",
        )

        published = await _graph_post(
            client,
            f"{GRAPH_BASE}/{ig_user_id}/media_publish",
            {"creation_id": container_id, "access_token": token},
            what="Instagram Reels publish",
        )
        post_id = published.get("id")
        if not post_id:
            raise PublishError("Instagram media_publish returned no id")
        return PublishOutcome(
            platform_post_id=str(post_id),
            status="published",
            extra={"creation_id": container_id},
        )

    async def _warn_if_quota_low(
        self, client: httpx.AsyncClient, ig_user_id: str, token: str
    ) -> None:
        """Best-effort content_publishing_limit check — never blocks publishing."""
        try:
            resp = await client.get(
                f"{GRAPH_BASE}/{ig_user_id}/content_publishing_limit",
                params={"fields": "quota_usage,config", "access_token": token},
            )
            entries = resp.json().get("data") or []
            usage = entries[0].get("quota_usage") if entries else None
            if isinstance(usage, (int, float)) and usage >= 90:
                logger.warning(
                    "Instagram publishing quota nearly exhausted for account %s: "
                    "quota_usage=%s",
                    ig_user_id,
                    usage,
                )
        except Exception as exc:
            logger.debug("Instagram quota check skipped: %s", exc)


class FacebookPublisher(ChannelPublisher):
    """Publishes Page photos and Reels via the Graph API."""

    channel = "facebook"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        token = creds.get("meta_access_token") or ""
        page_id = creds.get("page_id") or ""
        if not token or not page_id:
            raise PublishError(
                "Facebook credentials missing (meta_access_token / page_id). "
                "Set them in Brand > Channels > Facebook."
            )

        # Page publishing needs the Page's OWN token; fall back to the stored
        # token if derivation fails (same behavior as the n8n dispatch path).
        page_token = await _derive_facebook_page_token(token, page_id) or token

        caption_text, hashtags = resolve_caption_and_hashtags(content, self.channel)
        message = format_caption(caption_text, hashtags)

        async with self._http() as client:
            if media.kind == "video":
                return await self._publish_reel(client, page_id, page_token, message, media)
            return await self._publish_photo(client, page_id, page_token, message, media)

    async def _publish_photo(
        self,
        client: httpx.AsyncClient,
        page_id: str,
        page_token: str,
        message: str,
        media: MediaBundle,
    ) -> PublishOutcome:
        if not media.public_url:
            raise PublishError("Facebook photo publishing needs a public image URL")
        result = await _graph_post(
            client,
            f"{GRAPH_BASE}/{page_id}/photos",
            {"url": media.public_url, "message": message, "access_token": page_token},
            what="Facebook photo post",
        )
        post_id = result.get("post_id") or result.get("id")
        if not post_id:
            raise PublishError("Facebook photo post returned no id")
        return PublishOutcome(
            platform_post_id=str(post_id),
            status="published",
            extra={"photo_id": result.get("id")},
        )

    async def _publish_reel(
        self,
        client: httpx.AsyncClient,
        page_id: str,
        page_token: str,
        message: str,
        media: MediaBundle,
    ) -> PublishOutcome:
        # Load the raw bytes from MinIO — the rupload endpoint wants the binary
        # pushed to it, not a URL to pull (and our proxy URL may not be
        # reachable from Meta's fetchers in all deployments).
        data = await media.get_bytes()

        # Phase 1: start
        start = await _graph_post(
            client,
            f"{GRAPH_BASE}/{page_id}/video_reels",
            {"upload_phase": "start", "access_token": page_token},
            what="Facebook Reels upload start",
        )
        video_id = start.get("video_id")
        if not video_id:
            raise PublishError("Facebook Reels start phase returned no video_id")
        upload_url = start.get("upload_url") or f"{RUPLOAD_BASE}/{video_id}"

        # Phase 2: binary upload to rupload.facebook.com
        upload_resp = await client.post(
            upload_url,
            headers={
                "Authorization": f"OAuth {page_token}",
                "offset": "0",
                "file_size": str(len(data)),
            },
            content=data,
        )
        if upload_resp.status_code >= 400:
            raise PublishError(
                f"Facebook Reels binary upload failed: {_graph_error_detail(upload_resp)}"
            )
        try:
            upload_ok = upload_resp.json().get("success", True)
        except Exception:
            upload_ok = True
        if not upload_ok:
            raise PublishError(
                f"Facebook Reels binary upload not accepted: {upload_resp.text[:300]}"
            )

        # Phase 3: finish + publish
        await _graph_post(
            client,
            f"{GRAPH_BASE}/{page_id}/video_reels",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": message,
                "access_token": page_token,
            },
            what="Facebook Reels upload finish",
        )

        # Best-effort processing status. The finish call succeeded, so polling
        # breakage or a timeout is tolerated (treated as published); only an
        # explicit video_status == "error" fails the publish.
        async def _check_status() -> dict[str, Any] | None:
            try:
                resp = await client.get(
                    f"{GRAPH_BASE}/{video_id}",
                    params={"fields": "status", "access_token": page_token},
                )
            except httpx.HTTPError as exc:
                raise _StatusPollUnavailable(str(exc))
            if resp.status_code >= 400:
                raise _StatusPollUnavailable(_graph_error_detail(resp))
            try:
                status = resp.json().get("status") or {}
            except Exception:
                raise _StatusPollUnavailable(
                    f"non-JSON status response (HTTP {resp.status_code})"
                )
            if status.get("video_status") in ("ready", "error"):
                return status
            return None  # still processing

        extra: dict[str, Any] = {}
        status_info: dict[str, Any] | None = None
        try:
            status_info = await poll_until(
                _check_status,
                interval_s=10,
                max_wait_s=300,
                description=f"Facebook Reel {video_id} processing",
            )
        except (PublishError, _StatusPollUnavailable) as exc:
            detail = exc.detail if isinstance(exc, PublishError) else str(exc)
            logger.warning(
                "Facebook Reel %s: finish succeeded but status polling did not "
                "confirm ready (%s) — treating as published",
                video_id,
                detail,
            )
            extra["status_poll"] = detail

        if status_info is not None:
            if status_info.get("video_status") == "error":
                raise PublishError(
                    f"Facebook Reel processing failed: {str(status_info)[:300]}"
                )
            extra["video_status"] = status_info.get("video_status")

        return PublishOutcome(
            platform_post_id=str(video_id), status="published", extra=extra
        )
