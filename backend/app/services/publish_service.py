import logging
from typing import Any

import httpx

from app.config import settings
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content

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

    # Build caption from platform metadata or fallback to main caption
    platform_meta = content.platform_metadata or {}
    channel_data = platform_meta.get(channel, {})
    caption = channel_data.get("caption", content.caption or content.body_text or "")

    # Get image URL — stored in generation_metadata by the content pipeline.
    # Prefer branded (has logo + text overlay) → raw background → legacy key.
    gen_meta = content.generation_metadata or {}
    minio_path = (
        gen_meta.get("branded_image")
        or gen_meta.get("raw_image")
        or gen_meta.get("generated_image_url")
    )
    # Convert MinIO internal path to public API URL
    api_base = settings.PUBLIC_API_URL or settings.FRONTEND_URL
    if minio_path and api_base:
        image_url = f"{api_base}/api/v1/files/{minio_path}"
        # Instagram's Content Publishing API only accepts JPEG; our pipeline
        # renders PNG. Serve a JPEG-converted variant for Meta channels.
        if channel in ("instagram", "facebook"):
            image_url += "?fmt=jpg"
    else:
        image_url = content.video_url or None

    payload = {
        "content_id": str(content.id),
        "channel": channel,
        "caption": caption,
        "headline": content.headline,
        "image_url": image_url,
        "hashtags": content.hashtags or [],
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

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(n8n_webhook, json=payload)
        resp.raise_for_status()
        return resp.json()
