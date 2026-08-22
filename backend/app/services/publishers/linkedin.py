"""LinkedIn publisher — direct organization posts via the LinkedIn REST API.

Videos use the versioned Videos API (initializeUpload → chunked PUTs →
finalizeUpload → poll until AVAILABLE) and images the one-shot Images API,
then both are attached to a Posts API post. Credentials come from the brand's
per-channel config (``access_token`` / ``org_id``) with the global
``settings.LINKEDIN_*`` values as fallback.
"""

import asyncio
import logging
import time
from typing import Any
from urllib.parse import quote

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

LINKEDIN_API_BASE = "https://api.linkedin.com"

# LinkedIn versions its REST API monthly and sunsets each version after
# ~2 years: "202508" sunsets around August 2027 and MUST be bumped before
# then (check the migration notes when bumping — payload shapes can change).
LINKEDIN_VERSION = "202508"

VIDEO_POLL_INTERVAL_SECONDS = 10
VIDEO_POLL_TIMEOUT_SECONDS = 300

UPLOAD_TIMEOUT = httpx.Timeout(600.0, connect=30.0)


class LinkedInPublishError(Exception):
    """Raised when a LinkedIn publish fails or credentials are missing."""

    pass


class LinkedInPublisher:
    """Publishes text, image and video posts as a LinkedIn organization."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.access_token = config.get("access_token") or settings.LINKEDIN_ACCESS_TOKEN
        self.org_id = config.get("org_id") or settings.LINKEDIN_ORG_ID

    @property
    def _author_urn(self) -> str:
        return f"urn:li:organization:{self.org_id}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "LinkedIn-Version": LINKEDIN_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _check_credentials(self) -> None:
        missing = [
            name
            for name, value in (
                ("access_token", self.access_token),
                ("org_id", self.org_id),
            )
            if not value
        ]
        if missing:
            raise LinkedInPublishError(
                f"LinkedIn credentials missing ({', '.join(missing)}). "
                "Set them in Brand > Channels > LinkedIn or via LINKEDIN_* env vars."
            )

    # ── Posts ───────────────────────────────────────────────────────────

    async def _create_post(
        self,
        client: httpx.AsyncClient,
        *,
        commentary: str,
        media_urn: str | None = None,
        media_title: str | None = None,
    ) -> str:
        """Create the post and return its id from the x-restli-id header."""
        payload: dict[str, Any] = {
            "author": self._author_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "lifecycleState": "PUBLISHED",
        }
        if media_urn:
            media: dict[str, Any] = {"id": media_urn}
            if media_title:
                media["title"] = media_title
            payload["content"] = {"media": media}

        resp = await client.post(
            f"{LINKEDIN_API_BASE}/rest/posts",
            json=payload,
            headers=self._headers(),
        )
        resp.raise_for_status()
        post_id = resp.headers.get("x-restli-id", "")
        if not post_id:
            # Without the id we cannot record platform_post_id — surface the
            # failure instead of reporting "published" with an empty id.
            raise LinkedInPublishError(
                "LinkedIn post was created but the response carried no "
                "x-restli-id header, so no platform post id can be recorded"
            )
        return post_id

    async def publish_text(self, *, caption: str) -> dict[str, Any]:
        """Publish a text-only post."""
        self._check_credentials()
        async with httpx.AsyncClient(timeout=30) as client:
            post_id = await self._create_post(client, commentary=caption)
        logger.info("Published LinkedIn text post %s", post_id)
        return {
            "status": "published",
            "channel": "linkedin",
            "platform_post_id": post_id,
        }

    # ── Images (one-shot upload) ────────────────────────────────────────

    async def publish_image(
        self,
        image_bytes: bytes,
        *,
        caption: str,
    ) -> dict[str, Any]:
        """Publish an image post via the one-shot Images API upload."""
        self._check_credentials()

        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as client:
            init_resp = await client.post(
                f"{LINKEDIN_API_BASE}/rest/images",
                params={"action": "initializeUpload"},
                json={"initializeUploadRequest": {"owner": self._author_urn}},
                headers=self._headers(),
            )
            init_resp.raise_for_status()
            value = init_resp.json().get("value", {})
            upload_url = value.get("uploadUrl")
            image_urn = value.get("image")
            if not upload_url or not image_urn:
                raise LinkedInPublishError(
                    f"LinkedIn image initializeUpload returned no uploadUrl/image: {value}"
                )

            upload_resp = await client.put(
                upload_url,
                content=image_bytes,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/octet-stream",
                },
            )
            # The pre-signed uploadUrl is a short-lived credential — map the
            # error locally so raise_for_status's URL-bearing message never
            # reaches base.publish's generic httpx handler (outcome.error).
            if upload_resp.status_code >= 400:
                raise LinkedInPublishError(
                    f"LinkedIn image upload returned HTTP {upload_resp.status_code}"
                )

            post_id = await self._create_post(
                client, commentary=caption, media_urn=image_urn
            )

        logger.info("Published LinkedIn image post %s (%s)", post_id, image_urn)
        return {
            "status": "published",
            "channel": "linkedin",
            "platform_post_id": post_id,
            "media_urn": image_urn,
        }

    # ── Videos (chunked upload) ─────────────────────────────────────────

    @staticmethod
    def _chunk_for_instruction(data: bytes, instruction: dict[str, Any]) -> bytes:
        """Slice the exact byte range one uploadInstruction asks for."""
        return data[instruction["firstByte"] : instruction["lastByte"] + 1]

    async def _upload_video_parts(
        self,
        client: httpx.AsyncClient,
        video_bytes: bytes,
        instructions: list[dict[str, Any]],
    ) -> list[str]:
        """PUT each instructed byte range, returning the ETags in order."""
        etags: list[str] = []
        for instruction in instructions:
            chunk = self._chunk_for_instruction(video_bytes, instruction)
            resp = await client.put(
                instruction["uploadUrl"],
                content=chunk,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/octet-stream",
                },
            )
            # Pre-signed uploadUrl = credential; keep it out of error text.
            if resp.status_code >= 400:
                raise LinkedInPublishError(
                    f"LinkedIn video part upload returned HTTP {resp.status_code} "
                    f"(bytes {instruction['firstByte']}-{instruction['lastByte']})"
                )
            etag = resp.headers.get("ETag")
            if not etag:
                raise LinkedInPublishError(
                    f"LinkedIn video part upload returned no ETag "
                    f"(bytes {instruction['firstByte']}-{instruction['lastByte']})"
                )
            etags.append(etag)
        return etags

    async def _wait_until_available(
        self, client: httpx.AsyncClient, video_urn: str
    ) -> None:
        """Poll the video until LinkedIn finishes processing it."""
        encoded_urn = quote(video_urn, safe="")
        deadline = time.monotonic() + VIDEO_POLL_TIMEOUT_SECONDS
        while True:
            resp = await client.get(
                f"{LINKEDIN_API_BASE}/rest/videos/{encoded_urn}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            status = resp.json().get("status", "")
            if status == "AVAILABLE":
                return
            if status in ("PROCESSING_FAILED", "FAILED"):
                raise LinkedInPublishError(
                    f"LinkedIn video processing failed for {video_urn} "
                    f"(status={status})"
                )
            if time.monotonic() >= deadline:
                raise LinkedInPublishError(
                    f"LinkedIn video {video_urn} still '{status}' after "
                    f"{VIDEO_POLL_TIMEOUT_SECONDS}s — giving up"
                )
            await asyncio.sleep(VIDEO_POLL_INTERVAL_SECONDS)

    async def publish_video(
        self,
        video_bytes: bytes,
        *,
        caption: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Upload a video and publish it as an organization post."""
        self._check_credentials()

        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT) as client:
            # 1. Initialize the upload — LinkedIn dictates the chunk ranges
            init_resp = await client.post(
                f"{LINKEDIN_API_BASE}/rest/videos",
                params={"action": "initializeUpload"},
                json={
                    "initializeUploadRequest": {
                        "owner": self._author_urn,
                        "fileSizeBytes": len(video_bytes),
                    }
                },
                headers=self._headers(),
            )
            init_resp.raise_for_status()
            value = init_resp.json().get("value", {})
            video_urn = value.get("video")
            instructions = value.get("uploadInstructions", [])
            if not video_urn or not instructions:
                raise LinkedInPublishError(
                    f"LinkedIn video initializeUpload returned no video/"
                    f"uploadInstructions: {value}"
                )

            # 2. Upload every instructed byte range, collecting ETags in order
            etags = await self._upload_video_parts(client, video_bytes, instructions)

            # 3. Finalize with the ordered part ids
            finalize_resp = await client.post(
                f"{LINKEDIN_API_BASE}/rest/videos",
                params={"action": "finalizeUpload"},
                json={
                    "finalizeUploadRequest": {
                        "video": video_urn,
                        "uploadToken": "",
                        "uploadedPartIds": etags,
                    }
                },
                headers=self._headers(),
            )
            finalize_resp.raise_for_status()

            # 4. Wait for processing, then attach the video to a post
            await self._wait_until_available(client, video_urn)
            post_id = await self._create_post(
                client,
                commentary=caption,
                media_urn=video_urn,
                media_title=title or "Video",
            )

        logger.info("Published LinkedIn video post %s (%s)", post_id, video_urn)
        return {
            "status": "published",
            "channel": "linkedin",
            "platform_post_id": post_id,
            "media_urn": video_urn,
        }


class LinkedInChannelPublisher(ChannelPublisher):
    """``ChannelPublisher`` seam over ``LinkedInPublisher`` for the registry.

    Translates the dispatcher's credential keys (``linkedin_access_token`` /
    ``linkedin_org_id``, see ``get_platform_credentials``) into the
    publisher's config keys so brand-level credentials are honored (empty
    values fall back to the global ``settings.LINKEDIN_*``), loads the media
    bytes from MinIO and maps ``LinkedInPublishError`` onto the uniform
    ``PublishError`` contract. Videos use the chunked Videos API, images the
    one-shot Images API; an image item without rendered bytes publishes the
    caption as a text-only post.
    """

    channel = "linkedin"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        caption, hashtags = resolve_caption_and_hashtags(content, self.channel)
        commentary = format_caption(caption, hashtags)

        publisher = LinkedInPublisher(
            {
                "access_token": creds.get("linkedin_access_token") or "",
                "org_id": creds.get("linkedin_org_id") or "",
            }
        )
        try:
            if media.kind == "video":
                title = resolve_title(content, caption, default="Video")
                video_bytes = await media.get_bytes()
                result = await publisher.publish_video(
                    video_bytes, caption=commentary, title=title
                )
            elif media.bytes_loader is not None:
                image_bytes = await media.get_bytes()
                result = await publisher.publish_image(
                    image_bytes, caption=commentary
                )
            else:
                # No rendered image — publish the caption as a text-only post.
                result = await publisher.publish_text(caption=commentary)
        except LinkedInPublishError as exc:
            raise PublishError(str(exc)) from exc

        return PublishOutcome(
            platform_post_id=str(result["platform_post_id"]),
            status="published",
            extra={"media_urn": result.get("media_urn")},
        )
