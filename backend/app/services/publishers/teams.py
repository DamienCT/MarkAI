"""Microsoft Teams publisher — MessageCard posts to a per-brand incoming webhook.

Ported from the legacy dispatch path's native teams branch: the card carries
the headline + caption; image items add the branded image and video items a
"View video" action. Teams re-fetches card media on every render, so the
media URL is re-signed with a 30-day TTL instead of the short-lived publish
signature.

The webhook URL is itself a credential (the secret is embedded in the URL
path) — it must never appear in logs or exception messages, so HTTP errors
are reduced to their status code / exception type before leaving this
module.
"""

import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.services.publishers.base import (
    ChannelPublisher,
    MediaBundle,
    PublishError,
    PublishOutcome,
)
from app.utils.media_sign import sign_media_path

logger = logging.getLogger(__name__)

# Teams renders cards long after publish and re-fetches the image every time
# the card is displayed — sign the media URL for 30 days, not the dispatch
# window.
TEAMS_MEDIA_URL_TTL = 30 * 24 * 3600

# Synthetic platform post id: an incoming webhook returns no post id, so the
# outcome records this marker in ``extra`` instead of a real id.
SYNTHETIC_POST_ID = "teams-webhook"


def _long_lived_media_url(media: MediaBundle) -> str | None:
    """Re-sign the bundle's public URL with the 30-day Teams TTL.

    ``media.public_url`` carries the short publish-window signature; strip
    its query string and sign the bare URL path again (``verify_media_sig``
    accepts a signature over the full URL path).
    """
    if not media.public_url:
        return None
    parts = urlsplit(media.public_url)
    base = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    try:
        return f"{base}?{sign_media_path(parts.path, TEAMS_MEDIA_URL_TTL)}"
    except RuntimeError:
        # MEDIA_PROXY_TOKEN unset — non-production serves media without
        # signatures, so the (possibly unsigned) URL we already have works.
        return media.public_url


class TeamsPublisher(ChannelPublisher):
    """Posts a MessageCard with the content + media link to a Teams webhook."""

    channel = "teams"

    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        webhook_url = creds.get("webhook_url") or ""
        if not webhook_url:
            raise PublishError(
                "Teams webhook URL not configured for this brand. "
                "Set it in Brand > Channels > Teams."
            )

        caption = content.caption or content.body_text or ""
        payload: dict[str, Any] = {
            "@type": "MessageCard",
            "summary": content.headline or "New content published",
            "sections": [
                {
                    "activityTitle": content.headline or "New Content",
                    "text": caption,
                }
            ],
        }
        media_url = _long_lived_media_url(media)
        if media_url and media.kind == "image":
            payload["sections"][0]["images"] = [{"image": media_url}]
        elif media_url and media.kind == "video":
            payload["potentialAction"] = [
                {
                    "@type": "OpenUri",
                    "name": "View video",
                    "targets": [{"os": "default", "uri": media_url}],
                }
            ]

        # Teams webhook URLs embed a credential in the PATH — never let the
        # URL-bearing httpx exception text escape into logs / job-log rows.
        try:
            async with self._http() as client:
                resp = await client.post(webhook_url, json=payload)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise PublishError(
                f"Teams webhook returned HTTP {exc.response.status_code}"
            ) from None
        except httpx.HTTPError as exc:
            raise PublishError(
                f"Teams webhook request failed: {type(exc).__name__}"
            ) from None

        # An incoming webhook returns "1" on success — there is no platform
        # post id to record; the synthetic marker goes in ``extra``.
        return PublishOutcome(
            platform_post_id=None,
            status="published",
            extra={"synthetic_post_id": SYNTHETIC_POST_ID},
        )
