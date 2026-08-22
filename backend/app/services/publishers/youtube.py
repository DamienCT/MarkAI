"""YouTube publisher — direct video uploads via the YouTube Data API v3.

The backend refreshes the brand's OAuth access token, opens a resumable
upload session and PUTs the video bytes directly. Credentials come from the brand's per-channel config
(``client_id`` / ``client_secret`` / ``refresh_token`` / ``channel_id``) with
the global ``settings.YOUTUBE_*`` values as fallback.
"""

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.publishers.base import (
    ChannelPublisher,
    MediaBundle,
    PublishError,
    PublishOutcome,
    format_caption,
    resolve_caption_and_hashtags,
    resolve_title,
)

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"

# YouTube allows 100 chars for titles; stay under it with a safety margin.
MAX_TITLE_LENGTH = 95

# Videos are master-encoded H.264+AAC ≤90s, so a single-shot PUT is fine
# (Google recommends chunking only for unreliable connections / >300MB).
UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=30.0)


class YouTubePublishError(Exception):
    """Raised when a YouTube upload fails or credentials are missing."""

    pass


class YouTubePublisher:
    """Uploads videos to a brand's YouTube channel via resumable upload."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.client_id = config.get("client_id") or settings.YOUTUBE_CLIENT_ID
        self.client_secret = (
            config.get("client_secret") or settings.YOUTUBE_CLIENT_SECRET
        )
        self.refresh_token = (
            config.get("refresh_token") or settings.YOUTUBE_REFRESH_TOKEN
        )
        self.channel_id = config.get("channel_id") or settings.YOUTUBE_CHANNEL_ID

    def _check_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("client_id", self.client_id),
                ("client_secret", self.client_secret),
                ("refresh_token", self.refresh_token),
            )
            if not value
        ]
        if missing:
            raise YouTubePublishError(
                f"YouTube credentials missing ({', '.join(missing)}). "
                "Set them in Brand > Channels > YouTube or via YOUTUBE_* env vars."
            )

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> str:
        """Exchange the stored refresh token for a short-lived access token."""
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        resp.raise_for_status()
        access_token = resp.json().get("access_token")
        if not access_token:
            raise YouTubePublishError(
                "Google token endpoint returned no access_token — the refresh "
                "token may have been revoked."
            )
        return access_token

    async def publish_video(
        self,
        video_bytes: bytes,
        *,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        """Upload a video and return its platform_post_id (the video id).

        NOTE: unaudited Google API projects force YouTube uploads to private
        regardless of the requested privacyStatus — the response may come back
        ``private`` until the project passes the API audit. The video id is
        recorded as platform_post_id either way.
        """
        self._check_credentials()

        metadata = {
            "snippet": {
                "title": (title or "New video")[:MAX_TITLE_LENGTH],
                "description": description or "",
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,  # AI-generated content disclosure
            },
        }

        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as client:
            access_token = await self._refresh_access_token(client)

            # 1. Open the resumable upload session
            init_resp = await client.post(
                YOUTUBE_UPLOAD_URL,
                params={"uploadType": "resumable", "part": "snippet,status"},
                json=metadata,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "X-Upload-Content-Length": str(len(video_bytes)),
                    "X-Upload-Content-Type": "video/mp4",
                },
            )
            init_resp.raise_for_status()
            upload_url = init_resp.headers.get("Location")
            if not upload_url:
                raise YouTubePublishError(
                    "YouTube resumable upload init returned no Location header"
                )

            # 2. Upload the bytes in one shot (fine for our ≤90s masters)
            upload_resp = await client.put(
                upload_url,
                content=video_bytes,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(video_bytes)),
                },
            )
            upload_resp.raise_for_status()
            body = upload_resp.json()

        video_id = body.get("id")
        if not video_id:
            raise YouTubePublishError(
                f"YouTube upload response contained no video id: {body}"
            )

        privacy_status = (body.get("status") or {}).get("privacyStatus", "")
        if privacy_status and privacy_status != "public":
            logger.warning(
                "YouTube video %s uploaded but privacyStatus is '%s' — "
                "unaudited API projects force uploads private.",
                video_id,
                privacy_status,
            )

        logger.info("Published YouTube video %s (privacy=%s)", video_id, privacy_status)
        return {
            "status": "published",
            "channel": "youtube",
            "platform_post_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "privacy_status": privacy_status,
        }


class YouTubeChannelPublisher(ChannelPublisher):
    """``ChannelPublisher`` seam over ``YouTubePublisher`` for the registry.

    Builds the upload publisher from the brand's resolved channel credentials
    (``YouTubePublisher`` falls back to the global ``settings.YOUTUBE_*``
    values for any empty key), loads the video bytes from MinIO and maps
    ``YouTubePublishError`` onto the uniform ``PublishError`` contract.
    """

    channel = "youtube"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        if media.kind != "video":
            raise PublishError("YouTube direct publishing supports video only")

        caption, hashtags = resolve_caption_and_hashtags(content, self.channel)
        description = format_caption(caption, hashtags)
        title = resolve_title(content, caption, default="New video")
        video_bytes = await media.get_bytes()

        publisher = YouTubePublisher(creds)
        try:
            result = await publisher.publish_video(
                video_bytes, title=title, description=description
            )
        except YouTubePublishError as exc:
            raise PublishError(str(exc)) from exc

        return PublishOutcome(
            platform_post_id=str(result["platform_post_id"]),
            status="published",
            extra={
                "url": result.get("url"),
                "privacy_status": result.get("privacy_status"),
            },
        )
