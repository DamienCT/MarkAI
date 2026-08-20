import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services import minio_service
from app.services.publishers.base import (
    MediaBundle,
    PublishOutcome,
    resolve_caption_and_hashtags,
)
from app.services.publishers.registry import get_publisher

logger = logging.getLogger(__name__)


def get_platform_credentials(brand: Brand, channel: str) -> dict[str, Any]:
    """Extract platform-specific credentials from brand guidelines channel config."""
    guidelines = brand.brand_guidelines or {}

    # Try new per-channel config first, then fall back to legacy social_credentials
    channels_cfg = guidelines.get("channels", {})
    ch_cfg = channels_cfg.get(channel, {})
    creds = guidelines.get("social_credentials", {})

    if channel == "instagram":
        return {
            "meta_access_token": ch_cfg.get("access_token")
            or creds.get("meta_access_token", ""),
            "instagram_account_id": ch_cfg.get("account_id")
            or creds.get("instagram_account_id", ""),
        }
    elif channel == "facebook":
        return {
            "meta_access_token": ch_cfg.get("access_token")
            or creds.get("meta_access_token", ""),
            "page_id": ch_cfg.get("page_id") or creds.get("facebook_page_id", ""),
        }
    elif channel == "linkedin":
        return {
            "linkedin_access_token": ch_cfg.get("access_token")
            or creds.get("linkedin_access_token", ""),
            "linkedin_org_id": ch_cfg.get("org_id") or creds.get("linkedin_org_id", ""),
        }
    elif channel == "youtube":
        return {
            "channel_id": ch_cfg.get("channel_id", ""),
            "api_key": ch_cfg.get("api_key", ""),
            # Per-brand OAuth for direct uploads; the publisher falls back to
            # the global settings.YOUTUBE_* values when these are empty.
            "client_id": ch_cfg.get("client_id", ""),
            "client_secret": ch_cfg.get("client_secret", ""),
            "refresh_token": ch_cfg.get("refresh_token", ""),
        }
    elif channel == "tiktok":
        return {
            "access_token": ch_cfg.get("access_token", ""),
            "handle": ch_cfg.get("handle", ""),
        }
    elif channel == "x":
        return {
            "api_key": ch_cfg.get("api_key", ""),
            "handle": ch_cfg.get("handle", ""),
        }
    elif channel == "teams":
        return {
            "webhook_url": ch_cfg.get("webhook_url", ""),
        }
    else:
        # website_blog and any unknown channels — no credentials needed
        return {}


class PublishPreflightError(Exception):
    """Raised when pre-flight checks fail before dispatching to n8n."""

    pass


def _preflight_checks(
    content: Content,
    calendar_item: CalendarItem,
    brand: Brand,
) -> None:
    """Verify required data is present before dispatching to n8n."""
    channel = calendar_item.channel

    # Check n8n webhook URL is configured
    if not settings.N8N_WEBHOOK_BASE or "example.com" in settings.N8N_WEBHOOK_BASE:
        raise PublishPreflightError(
            "N8N_WEBHOOK_BASE not configured. Set it in .env to enable publishing."
        )

    # Check content has required fields
    caption = content.caption or content.body_text or ""
    if not caption:
        raise PublishPreflightError(
            f"Content '{content.id}' has no caption or body_text for channel '{channel}'"
        )


async def _derive_facebook_page_token(token: str, page_id: str) -> str | None:
    """Exchange a User/System-User token for the Page's OWN access token.

    Posting to ``/{page-id}/feed`` requires a Page access token; a user or
    system-user token (even with ``pages_manage_posts``) triggers Facebook's
    deprecated ``publish_actions`` error. The page token is obtained from
    ``GET /{page-id}?fields=access_token`` using the stored token (which must
    have the Page assigned + ``pages_manage_posts``). Returns None on failure
    so the caller falls back to the original token.
    """
    if not token or not page_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://graph.facebook.com/v25.0/{page_id}",
                params={"fields": "access_token", "access_token": token},
            )
            resp.raise_for_status()
            page_token = resp.json().get("access_token")
        if page_token:
            logger.info("Derived Facebook Page token for page %s", page_id)
            return page_token
        logger.warning(
            "No Page token returned for page %s — is the Page assigned to the "
            "system user with pages_manage_posts?", page_id,
        )
        return None
    except Exception as exc:
        logger.warning("Could not derive FB Page token for page %s: %s", page_id, exc)
        return None


def resolve_channel_copy(content: Content, channel: str) -> tuple[str, list[str]]:
    """Resolve the caption and hashtags to publish for one channel.

    Per-channel adaptations from ``generation_metadata.platform_adaptations``
    win, then legacy ``platform_metadata``, then the primary caption /
    body_text. Delegates to the publishers' shared helper so the direct and
    n8n paths can never drift apart.
    """
    return resolve_caption_and_hashtags(content, channel)


def resolve_media(
    content: Content, calendar_item: CalendarItem, *, image_only: bool = False
) -> MediaBundle:
    """Pick the media asset to publish for a calendar item.

    Video items (item_type ``reel``/``video`` with a rendered master at
    ``content.video_url``) publish the video; everything else publishes the
    branded image from ``generation_metadata`` (branded → raw → legacy key).
    ``public_url`` is the externally reachable file-proxy URL; ``bytes_loader``
    streams the raw object out of MinIO for platforms we push bytes to.

    ``image_only=True`` skips the video branch and always resolves the image
    — the n8n webhook payload is image-only, so its dispatch keeps sending
    the branded image even for video items.
    """
    api_base = settings.PUBLIC_API_URL or settings.FRONTEND_URL

    if not image_only and content.video_url and calendar_item.item_type in ("reel", "video"):
        video_path = content.video_url
        return MediaBundle(
            kind="video",
            public_url=f"{api_base}/api/v1/files/{video_path}" if api_base else None,
            bytes_loader=lambda: minio_service.download_file(video_path),
            mime="video/mp4",
        )

    gen_meta = content.generation_metadata or {}
    # Prefer branded (has logo + text overlay) → raw background → legacy key.
    image_path = (
        gen_meta.get("branded_image")
        or gen_meta.get("raw_image")
        or gen_meta.get("generated_image_url")
    )
    public_url = None
    if image_path and api_base:
        public_url = f"{api_base}/api/v1/files/{image_path}"
        # Instagram's Content Publishing API only accepts JPEG; our pipeline
        # renders PNG. Serve a JPEG-converted variant for Meta channels.
        if calendar_item.channel in ("instagram", "facebook"):
            public_url += "?fmt=jpg"
    return MediaBundle(
        kind="image",
        public_url=public_url,
        bytes_loader=(
            (lambda: minio_service.download_file(image_path)) if image_path else None
        ),
        mime="image/png",
    )


async def dispatch_to_n8n(
    content: Content,
    calendar_item: CalendarItem,
    brand: Brand,
) -> dict[str, Any]:
    """
    Channel-aware publishing dispatch.

    - instagram, facebook, linkedin: dispatch to n8n webhooks (existing)
    - youtube, tiktok, x: dispatch to n8n (new workflow endpoints)
    - website_blog: NO dispatch — mark as ready_to_publish with markdown stored in content
    - teams: dispatch directly via Teams incoming webhook (not n8n)
    """
    channel = calendar_item.channel

    # ── website_blog: no external dispatch ──────────────────────────
    if channel == "website_blog":
        logger.info(
            "website_blog channel — content %s marked ready_to_publish (manual copy/paste)",
            content.id,
        )
        return {
            "status": "ready_to_publish",
            "message": "Blog content is ready. Copy the markdown from Content Studio and publish manually.",
            "content_id": str(content.id),
        }

    # ── teams: dispatch via Teams incoming webhook directly ─────────
    if channel == "teams":
        creds = get_platform_credentials(brand, channel)
        webhook_url = creds.get("webhook_url", "")
        if not webhook_url:
            raise PublishPreflightError(
                "Teams webhook URL not configured for this brand. "
                "Set it in Brand > Channels > Teams."
            )
        caption = content.caption or content.body_text or ""
        teams_payload = {
            "@type": "MessageCard",
            "summary": content.headline or "New content published",
            "sections": [
                {
                    "activityTitle": content.headline or "New Content",
                    "text": caption,
                }
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=teams_payload)
            resp.raise_for_status()
            return {"status": "published", "channel": "teams"}

    # ── All other channels: dispatch to n8n ─────────────────────────
    _preflight_checks(content, calendar_item, brand)

    # Caption/hashtags from the pipeline's per-channel adaptations. Media:
    # the n8n webhook is image-only, so resolve the branded image even for
    # video items (the pre-direct-publish behavior), falling back to the raw
    # video_url only when no image/API base is available.
    caption, adapted_hashtags = resolve_channel_copy(content, channel)
    media = resolve_media(content, calendar_item, image_only=True)
    image_url = media.public_url or content.video_url or None

    payload = {
        "content_id": str(content.id),
        "channel": channel,
        "caption": caption,
        "headline": content.headline,
        "image_url": image_url,
        "hashtags": adapted_hashtags,
        "cta_text": content.cta_text,
        "cta_url": content.cta_url,
        "brand_name": brand.name,
        "calendar_item_id": str(calendar_item.id),
        **get_platform_credentials(brand, channel),
    }

    # Facebook Page publishing needs a PAGE token, not the stored user/system-
    # user token. Derive it on the fly so the brand can keep storing its
    # (non-expiring) system-user token; falls back to the stored token if the
    # exchange fails.
    if channel == "facebook" and payload.get("meta_access_token") and payload.get("page_id"):
        page_token = await _derive_facebook_page_token(
            payload["meta_access_token"], payload["page_id"]
        )
        if page_token:
            payload["meta_access_token"] = page_token

    # Single unified webhook — n8n routes internally by channel field
    n8n_webhook = f"{settings.N8N_WEBHOOK_BASE}/markai/publish"

    # Outbound auth: the n8n webhook is internet-reachable and this payload
    # carries live platform tokens, so n8n must be able to reject calls that
    # are not ours. Same shared secret as the inbound callback verification
    # (webhooks.py) — the n8n instance already holds it as
    # $env.N8N_WEBHOOK_SECRET for signing its callbacks, so no new
    # provisioning is needed. Header omitted while the secret is unset so
    # dispatch keeps working before the secret is provisioned.
    #
    # n8n side (runtime change, not in this repo): the FIRST node after the
    # Webhook trigger in docs/n8n-workflows/markai-publish.json must compare
    # $json.headers['x-webhook-secret'] to $env.N8N_WEBHOOK_SECRET and stop
    # the workflow on mismatch — until that node exists, this header is sent
    # but not enforced.
    #
    # The platform tokens stay IN the payload: the n8n workflow reads them
    # straight from $json.body (it has no vault/credential-store lookup), so
    # dropping them here would break every n8n-dispatched channel. Removing
    # them requires the n8n-side vault migration first; n8n execution logs
    # retain webhook payloads until then.
    headers: dict[str, str] = {}
    if settings.N8N_WEBHOOK_SECRET:
        headers["X-Webhook-Secret"] = settings.N8N_WEBHOOK_SECRET

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(n8n_webhook, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def record_publish_result(
    db: AsyncSession,
    content: Content,
    calendar_item: CalendarItem,
    channel: str,
    outcome: PublishOutcome,
) -> None:
    """Write a publish result back to the calendar item and content row.

    Mirrors what the n8n callback (``/api/v1/webhooks/publish-result``) does:
    published → calendar item ``published`` + ``published_at`` and the
    platform post id on the content; failed → calendar item ``failed`` with
    the error stored in ``generation_metadata.publish_error``. The direct
    path additionally records ``platform_metadata[channel]`` so multi-channel
    post ids don't overwrite each other.
    """
    now = datetime.now(timezone.utc)

    if outcome.status == "published":
        if not outcome.platform_post_id:
            logger.warning(
                "Publish outcome for content %s missing platform_post_id", content.id
            )
        content.platform_post_id = outcome.platform_post_id
        calendar_item.status = "published"
        calendar_item.published_at = now

        # Merge (not replace) so legacy per-channel adaptation data stored in
        # platform_metadata[channel] survives the publish write-back.
        platform_meta = dict(content.platform_metadata or {})
        channel_meta = platform_meta.get(channel)
        channel_meta = dict(channel_meta) if isinstance(channel_meta, dict) else {}
        channel_meta.update(
            {"post_id": outcome.platform_post_id, "published_at": now.isoformat()}
        )
        platform_meta[channel] = channel_meta
        content.platform_metadata = platform_meta
        flag_modified(content, "platform_metadata")

        logger.info(
            "Content %s published to %s, platform_post_id=%s",
            content.id,
            channel,
            outcome.platform_post_id,
        )
    else:
        calendar_item.status = "failed"
        gen_meta = dict(content.generation_metadata or {})
        gen_meta["publish_error"] = outcome.error
        content.generation_metadata = gen_meta
        flag_modified(content, "generation_metadata")

        logger.warning(
            "Content %s publish to %s failed: %s", content.id, channel, outcome.error
        )

    await db.commit()


async def publish_direct(
    db: AsyncSession,
    content: Content,
    calendar_item: CalendarItem,
    brand: Brand,
) -> PublishOutcome:
    """Publish a calendar item straight to its platform (no n8n hop).

    Picks the publisher from the registry (media-kind aware), resolves the
    brand's channel credentials, runs the platform flow and writes the result
    back to the calendar item / content row. Callers route to
    ``dispatch_to_n8n`` instead when ``get_publisher`` returns None for the
    channel/media combination.
    """
    channel = calendar_item.channel
    media = resolve_media(content, calendar_item)
    publisher = get_publisher(channel, media.kind)

    if publisher is None:
        outcome = PublishOutcome(
            platform_post_id=None,
            status="failed",
            error=(
                f"No direct publisher for channel '{channel}' "
                f"with media kind '{media.kind}'"
            ),
        )
    else:
        creds = get_platform_credentials(brand, channel)
        # Facebook Page publishing needs the Page's OWN token, not the stored
        # user/system-user token — ``FacebookPublisher`` derives it itself
        # (exactly once), so the raw credentials are passed through here.
        try:
            outcome = await publisher.publish(
                content, calendar_item, brand, creds, media
            )
        except Exception as exc:
            # Publishers map their known errors to failed outcomes; this is
            # the safety net for anything unexpected (bugs, MinIO errors, …).
            logger.exception(
                "Direct publish of content %s to %s crashed", content.id, channel
            )
            outcome = PublishOutcome(
                platform_post_id=None, status="failed", error=str(exc)
            )

    await record_publish_result(db, content, calendar_item, channel, outcome)
    return outcome
