"""Website/blog publisher — WordPress REST driver (application passwords).

When the brand's ``website_blog`` channel carries WordPress credentials
(``base_url`` / ``username`` / ``app_password``), the branded image is
uploaded to ``/wp-json/wp/v2/media`` (set as ``featured_media``) and the
post is created via ``/wp-json/wp/v2/posts`` with Basic auth. Without
credentials the item fails closed with an actionable error — the content
stays in Content Studio for manual publishing. ``platform`` selects the
driver; only ``wordpress`` is implemented.
"""

import html
import logging
import re
from typing import Any

import httpx

from app.services.publishers.base import (
    ChannelPublisher,
    MediaBundle,
    PublishError,
    PublishOutcome,
    resolve_caption_and_hashtags,
    resolve_title,
)

logger = logging.getLogger(__name__)

WP_API_PREFIX = "/wp-json/wp/v2"

SUPPORTED_PLATFORMS = ("wordpress",)

UNCONFIGURED_ERROR = (
    "website_blog not configured — add WordPress credentials in "
    "Brand → Channels, or publish manually from Content Studio "
    "(content stays available)"
)

_MIME_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "video/mp4": "mp4",
}


def _render_paragraphs(text: str) -> str:
    """Render plain text to simple HTML paragraphs (blank-line separated)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    return "\n".join(
        "<p>" + html.escape(block).replace("\n", "<br />") + "</p>"
        for block in blocks
    )


def _wp_error_detail(resp: httpx.Response) -> str:
    """Readable detail from a WP REST error body ({code, message})."""
    try:
        body = resp.json()
    except Exception:
        body = {}
    if isinstance(body, dict) and body.get("message"):
        code = body.get("code")
        return f"{body['message']} ({code})" if code else str(body["message"])
    return f"HTTP {resp.status_code}: {resp.text[:300]}"


def _check(resp: httpx.Response, what: str) -> None:
    if resp.status_code < 400:
        return
    detail = f"WordPress {what} failed: {_wp_error_detail(resp)}"
    if resp.status_code in (401, 403):
        detail += (
            " — check the WordPress username/application password in "
            "Brand > Channels > Website/Blog"
        )
    raise PublishError(detail)


def _json_body(resp: httpx.Response, what: str) -> dict[str, Any]:
    try:
        body = resp.json()
    except Exception:
        raise PublishError(
            f"WordPress {what} returned a non-JSON response "
            f"(HTTP {resp.status_code})"
        )
    return body if isinstance(body, dict) else {}


class BlogPublisher(ChannelPublisher):
    """Publishes posts (with featured media) to a brand's WordPress site."""

    channel = "website_blog"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        platform = (creds.get("platform") or "wordpress").strip().lower()
        if platform not in SUPPORTED_PLATFORMS:
            raise PublishError(
                f"website_blog platform '{platform}' is not supported — "
                f"supported drivers: {', '.join(SUPPORTED_PLATFORMS)}. Set the "
                "platform in Brand > Channels > Website/Blog."
            )

        base_url = (creds.get("base_url") or "").strip().rstrip("/")
        username = creds.get("username") or ""
        app_password = creds.get("app_password") or ""
        if not (base_url and username and app_password):
            raise PublishError(UNCONFIGURED_ERROR)
        if not base_url.startswith(("http://", "https://")):
            raise PublishError(
                "website_blog base_url must be a full URL (https://…) — "
                "fix it in Brand > Channels > Website/Blog"
            )

        caption, _hashtags = resolve_caption_and_hashtags(content, self.channel)
        title = resolve_title(content, caption, default="New post")
        body_html = _render_paragraphs(content.body_text or caption)

        auth = httpx.BasicAuth(username, app_password)
        async with self._http() as client:
            media_id: int | None = None
            media_source_url: str | None = None
            if media.bytes_loader is not None:
                media_id, media_source_url = await self._upload_media(
                    client, auth, base_url, media, title, calendar_item
                )

            post_payload: dict[str, Any] = {
                "title": title,
                "content": body_html,
                "status": "publish",
            }
            if media.kind == "image" and media_id is not None:
                post_payload["featured_media"] = media_id
            elif media.kind == "video" and media_source_url:
                # Videos don't work as featured media on most themes — embed
                # the uploaded file in the post body instead.
                post_payload["content"] += (
                    "\n<figure>"
                    f'<video controls src="{html.escape(media_source_url)}">'
                    "</video></figure>"
                )

            resp = await client.post(
                f"{base_url}{WP_API_PREFIX}/posts", json=post_payload, auth=auth
            )
            _check(resp, "post creation")
            body = _json_body(resp, "post creation")

        post_id = body.get("id")
        if not post_id:
            raise PublishError("WordPress post creation returned no post id")
        return PublishOutcome(
            platform_post_id=str(post_id),
            status="published",
            extra={"link": body.get("link"), "media_id": media_id},
        )

    async def _upload_media(
        self,
        client: httpx.AsyncClient,
        auth: httpx.BasicAuth,
        base_url: str,
        media: MediaBundle,
        title: str,
        calendar_item: Any,
    ) -> tuple[int, str | None]:
        """Upload the media bytes to the WP media library; return (id, source_url)."""
        data = await media.get_bytes()
        extension = _MIME_EXTENSIONS.get(media.mime, "bin")
        filename = f"markai-{getattr(calendar_item, 'id', 'media')}.{extension}"
        resp = await client.post(
            f"{base_url}{WP_API_PREFIX}/media",
            files={"file": (filename, data, media.mime)},
            data={"alt_text": title, "title": title},
            auth=auth,
        )
        _check(resp, "media upload")
        body = _json_body(resp, "media upload")
        media_id = body.get("id")
        if not media_id:
            raise PublishError("WordPress media upload returned no attachment id")
        return media_id, body.get("source_url")
