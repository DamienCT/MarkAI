import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models.base import async_session_factory
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services import minio_service
from app.services.publishers.base import MediaBundle, PublishOutcome
from app.services.publishers.registry import get_publisher
from app.utils.media_sign import sign_media_path
from app.utils.redact import redact

logger = logging.getLogger(__name__)

# TTL for signed media URLs handed to platforms that fetch media by URL
# (Meta / LinkedIn). Long enough to cover slow container polls + retries.
MEDIA_URL_SIGN_TTL = 2 * 60 * 60

# system_flags key for the global publishing kill switch. Scoped variants
# (see ``kill_switch_key``) suffix it with ``:brand:<uuid>`` / ``:channel:<name>``.
PUBLISHING_KILL_SWITCH_KEY = "publishing_enabled"


class PublishingDisabledError(Exception):
    """Raised when a publishing kill switch (any scope) is engaged."""

    pass


def kill_switch_key(
    brand_id: uuid.UUID | str | None = None, channel: str | None = None
) -> str:
    """The ``system_flags`` key for ONE kill-switch scope.

    ``brand_id`` → ``publishing_enabled:brand:<uuid>``; ``channel`` →
    ``publishing_enabled:channel:<channel>``; neither → the global key.
    """
    if brand_id is not None:
        return f"{PUBLISHING_KILL_SWITCH_KEY}:brand:{brand_id}"
    if channel:
        return f"{PUBLISHING_KILL_SWITCH_KEY}:channel:{channel}"
    return PUBLISHING_KILL_SWITCH_KEY


def kill_switch_scope_keys(
    brand_id: uuid.UUID | str | None = None, channel: str | None = None
) -> list[str]:
    """Every flag key that gates a dispatch for (brand, channel).

    Global first, then the brand and channel scopes when given — ALL of them
    must be enabled (absent = enabled) for the dispatch to proceed.
    """
    keys = [PUBLISHING_KILL_SWITCH_KEY]
    if brand_id is not None:
        keys.append(kill_switch_key(brand_id=brand_id))
    if channel:
        keys.append(kill_switch_key(channel=channel))
    return keys


def known_channels() -> set[str]:
    """Channel names with a registered publisher — the valid scope values
    for per-channel kill-switch flags."""
    from app.services.publishers.registry import _PUBLISHERS

    return {channel for channel, _kind in _PUBLISHERS}


def _flag_value_enabled(value: Any) -> bool:
    """Decode one ``system_flags`` JSONB value into the enabled bool.

    Absent (None) = enabled. A malformed string raises so the caller fails
    CLOSED — mirrored by the display decode in ``api.v1.system._flag_enabled``.
    """
    if value is None:
        return True  # flag absent = publishing enabled
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        return bool(value.get("enabled", True))
    return True


async def _read_publishing_flags(db: AsyncSession, keys: list[str]) -> bool:
    for key in keys:
        result = await db.execute(
            text("SELECT value FROM system_flags WHERE key = :key"),
            {"key": key},
        )
        if not _flag_value_enabled(result.scalar_one_or_none()):
            return False
    return True


async def is_publishing_enabled(
    db: AsyncSession | None = None,
    *,
    brand_id: uuid.UUID | str | None = None,
    channel: str | None = None,
) -> bool:
    """Publishing kill switch across every applicable scope.

    Checks the global ``publishing_enabled`` flag plus, when given, the
    per-brand (``publishing_enabled:brand:<uuid>``) and per-channel
    (``publishing_enabled:channel:<channel>``) flags — ALL must be enabled.
    Absent flags = enabled. Any read/decode error fails CLOSED (returns
    False) so a broken flags table or malformed flag can never allow an
    external post.
    """
    keys = kill_switch_scope_keys(brand_id=brand_id, channel=channel)
    try:
        if db is not None:
            return await _read_publishing_flags(db, keys)
        async with async_session_factory() as session:
            return await _read_publishing_flags(session, keys)
    except Exception:
        logger.exception(
            "Could not read publishing kill switch — failing closed (no dispatch)"
        )
        return False


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
            "client_key": ch_cfg.get("client_key", ""),
            "client_secret": ch_cfg.get("client_secret", ""),
            "access_token": ch_cfg.get("access_token", ""),
            "refresh_token": ch_cfg.get("refresh_token", ""),
            "handle": ch_cfg.get("handle", ""),
        }
    elif channel == "x":
        # OAuth 1.0a user context — all four keys required to sign requests.
        return {
            "consumer_key": ch_cfg.get("consumer_key", ""),
            "consumer_secret": ch_cfg.get("consumer_secret", ""),
            "access_token": ch_cfg.get("access_token", ""),
            "access_token_secret": ch_cfg.get("access_token_secret", ""),
            "handle": ch_cfg.get("handle", ""),
        }
    elif channel == "website_blog":
        return {
            "platform": ch_cfg.get("platform") or "wordpress",
            "base_url": ch_cfg.get("base_url", ""),
            "username": ch_cfg.get("username", ""),
            "app_password": ch_cfg.get("app_password", ""),
        }
    elif channel == "teams":
        return {
            "webhook_url": ch_cfg.get("webhook_url", ""),
        }
    else:
        # Unknown channels — no credentials to resolve.
        return {}


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
            # Token goes in the Authorization header, NEVER the URL: httpx
            # logs request URLs and str(HTTPStatusError) embeds them, so a
            # query-string token leaks into backend logs on every 4xx (N-01).
            resp = await client.get(
                f"https://graph.facebook.com/v25.0/{page_id}",
                params={"fields": "access_token"},
                headers={"Authorization": f"Bearer {token}"},
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
        logger.warning(
            "Could not derive FB Page token for page %s: %s", page_id, redact(str(exc))
        )
        return None


def _signed_file_url(path: str, *, as_jpg: bool = False) -> str | None:
    """Externally reachable ``/files`` URL for a MinIO path, carrying a signed
    access token (``mt=<hmac>&exp=<unix>``) so third-party fetchers (Meta,
    LinkedIn, Teams cards) can read it now that the media endpoints require
    auth."""
    api_base = settings.PUBLIC_API_URL or settings.FRONTEND_URL
    if not api_base or not path:
        return None
    url = f"{api_base}/api/v1/files/{path}"
    try:
        # Sign the bare object path — media_sign verification accepts either
        # the full URL path or the object path, and transform params
        # (fmt=jpg) stay outside the signature.
        url = f"{url}?{sign_media_path(path, MEDIA_URL_SIGN_TTL)}"
    except RuntimeError:
        # MEDIA_PROXY_TOKEN unset. Outside production the media endpoints
        # fall back to open access, so an unsigned URL still works;
        # production enforces the token at startup (_REQUIRED_PROD), so
        # fail loudly rather than emit a URL a platform cannot fetch.
        if settings.MARKAI_ENV == "production":
            raise
        logger.warning(
            "MEDIA_PROXY_TOKEN unset — media URL for %s left unsigned "
            "(non-production fallback)",
            path,
        )
    if as_jpg:
        url += ("&" if "?" in url else "?") + "fmt=jpg"
    return url


def resolve_media(content: Content, calendar_item: CalendarItem) -> MediaBundle:
    """Pick the media asset to publish for a calendar item.

    Video items (item_type ``reel``/``video`` with a rendered master at
    ``content.video_url``) publish the video; everything else publishes the
    branded image from ``generation_metadata`` (branded → raw → legacy key).
    ``public_url`` is the externally reachable file-proxy URL; ``bytes_loader``
    streams the raw object out of MinIO for platforms we push bytes to.
    """
    if content.video_url and calendar_item.item_type in ("reel", "video"):
        video_path = content.video_url
        return MediaBundle(
            kind="video",
            public_url=_signed_file_url(video_path),
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
    if image_path:
        # Instagram's Content Publishing API only accepts JPEG; our pipeline
        # renders PNG. Serve a JPEG-converted variant for Meta channels.
        public_url = _signed_file_url(
            image_path,
            as_jpg=calendar_item.channel in ("instagram", "facebook"),
        )
    return MediaBundle(
        kind="image",
        public_url=public_url,
        bytes_loader=(
            (lambda: minio_service.download_file(image_path)) if image_path else None
        ),
        mime="image/png",
    )


async def record_publish_result(
    db: AsyncSession,
    content: Content,
    calendar_item: CalendarItem,
    channel: str,
    outcome: PublishOutcome,
) -> None:
    """Write a publish result back to the calendar item and content row.

    published → calendar item ``published`` + ``published_at`` and the
    platform post id on the content; failed → calendar item ``failed`` with
    the error stored in ``generation_metadata.publish_error``. Also records
    ``platform_metadata[channel]`` (merge, not replace) so multi-channel
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
    """Publish a calendar item straight to its platform — the ONLY dispatch path.

    Picks the publisher from the registry (media-kind aware), resolves the
    brand's channel credentials, runs the platform flow and writes the result
    back to the calendar item / content row. When ``get_publisher`` returns
    None the channel/media combination is unsupported (no fallback exists)
    and the item is failed with an actionable error.
    """
    # Kill switch (global + this item's brand/channel scopes) — checked
    # immediately before any external effect. Raises (instead of recording a
    # failed outcome) so callers can release the 'publishing' claim without
    # marking the item failed.
    if not await is_publishing_enabled(
        db, brand_id=calendar_item.brand_id, channel=calendar_item.channel
    ):
        raise PublishingDisabledError(
            "Publishing kill switch is engaged for this scope — "
            "direct publish blocked"
        )

    channel = calendar_item.channel
    media = resolve_media(content, calendar_item)
    publisher = get_publisher(channel, media.kind)

    if publisher is None:
        if channel == "youtube" and media.kind == "image":
            error = (
                "YouTube requires video content — this item resolved to an "
                "image; schedule it as a reel/video with a rendered master "
                "or pick another channel"
            )
        else:
            error = (
                f"no publisher supports channel '{channel}' with media kind "
                f"'{media.kind}'"
            )
        outcome = PublishOutcome(
            platform_post_id=None,
            status="failed",
            error=error,
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
                platform_post_id=None, status="failed", error=redact(str(exc))
            )

    await record_publish_result(db, content, calendar_item, channel, outcome)
    return outcome
