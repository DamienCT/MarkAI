import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.base import async_session_factory
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.models.engagement import EngagementMetric
from app.services.engagement_service import (
    pull_facebook_insights,
    pull_instagram_insights,
    pull_linkedin_insights,
    pull_x_public_metrics,
    pull_youtube_statistics,
)
from app.services.publish_service import (
    _derive_facebook_page_token,
    get_platform_credentials,
)

logger = logging.getLogger(__name__)

# Channels with NO metrics pull, and why (logged so operators know the gap
# is deliberate, not a bug): TikTok metrics need Display API scopes the
# stored publish credentials don't carry; Teams incoming webhooks are
# write-only; the blog platforms expose no metrics API.
UNSUPPORTED_ENGAGEMENT_CHANNELS = {
    "tiktok": (
        "TikTok metrics require Display API scopes the stored publish "
        "credentials don't include"
    ),
    "teams": "Teams incoming webhooks are write-only — no metrics API",
    "website_blog": "the blog platform exposes no metrics API",
}

# The four OAuth 1.0a user-context keys an X metrics pull needs.
_X_REQUIRED_CREDS = (
    "consumer_key",
    "consumer_secret",
    "access_token",
    "access_token_secret",
)


async def upsert_engagement(
    db, content_id, calendar_item_id, brand_id, channel: str, metrics: dict
) -> None:
    """Create a new engagement metric record for the given content."""
    # Engagement rate stored as a RATIO 0..1 (the UI multiplies by 100 for
    # display). interactions / impressions (fallback reach). Computed here so
    # every platform gets one consistently; the pull functions don't return it,
    # which left the column NULL (analytics showed 0).
    engagement_rate = metrics.get("engagement_rate")
    if engagement_rate is None:
        interactions = (
            (metrics.get("likes") or 0)
            + (metrics.get("comments") or 0)
            + (metrics.get("shares") or 0)
            + (metrics.get("saves") or 0)
        )
        denom = metrics.get("impressions") or metrics.get("reach") or 0
        if denom:
            engagement_rate = round(interactions / denom, 4)

    em = EngagementMetric(
        content_id=content_id,
        calendar_item_id=calendar_item_id,
        brand_id=brand_id,
        channel=channel,
        impressions=metrics.get("impressions"),
        reach=metrics.get("reach"),
        likes=metrics.get("likes"),
        comments=metrics.get("comments"),
        shares=metrics.get("shares"),
        saves=metrics.get("saves"),
        clicks=metrics.get("clicks"),
        video_views=metrics.get("video_views"),
        engagement_rate=engagement_rate,
        sentiment_score=metrics.get("sentiment_score"),
        raw_metrics=metrics,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(em)
    await db.commit()


async def pull_all_engagement() -> None:
    """
    Pull engagement metrics directly from social platform APIs.
    Plain HTTP calls using brand credentials.
    """
    logger.info("Starting engagement pull for all published content")

    async with async_session_factory() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        # Find calendar items that are published within the last 30 days
        result = await db.execute(
            select(CalendarItem)
            .where(CalendarItem.status == "published")
            .where(CalendarItem.published_at >= cutoff)
            .options(
                selectinload(CalendarItem.content_items),
                selectinload(CalendarItem.brand),
            )
        )

        calendar_items = result.scalars().all()
        logger.info(
            "Pulling engagement for %d published calendar items", len(calendar_items)
        )

        for cal_item in calendar_items:
            # Get the current content for this calendar item
            content_result = await db.execute(
                select(Content)
                .where(Content.calendar_item_id == cal_item.id)
                .where(Content.is_current == True)  # noqa: E712
                .where(Content.platform_post_id.isnot(None))
                .options(selectinload(Content.brand))
            )
            content = content_result.scalar_one_or_none()
            if content is None:
                continue

            channel = cal_item.channel
            brand = content.brand
            guidelines = brand.brand_guidelines or {}
            creds = guidelines.get("social_credentials", {})
            # Also check per-channel config (same pattern as publish_service)
            channels_cfg = guidelines.get("channels", {})
            ch_cfg = channels_cfg.get(channel, {})

            try:
                if channel == "instagram":
                    token = ch_cfg.get("access_token") or creds.get(
                        "meta_access_token", ""
                    )
                    # IG insights need the connected Page's access token (the
                    # "new Pages experience" rejects a user/system token). Fall
                    # back to the facebook channel's page_id if IG has none.
                    page_id = (
                        ch_cfg.get("page_id")
                        or creds.get("facebook_page_id", "")
                        or (channels_cfg.get("facebook", {}) or {}).get("page_id", "")
                    )
                    page_token = (
                        await _derive_facebook_page_token(token, page_id)
                        if page_id else None
                    )
                    metrics = await pull_instagram_insights(content, page_token or token)
                elif channel == "facebook":
                    token = ch_cfg.get("access_token") or creds.get(
                        "meta_access_token", ""
                    )
                    page_id = ch_cfg.get("page_id") or creds.get("facebook_page_id", "")
                    # FB post ids are "{page_id}_{post}" — derive page_id from it
                    # when not configured.
                    if not page_id and content.platform_post_id and "_" in content.platform_post_id:
                        page_id = content.platform_post_id.split("_", 1)[0]
                    page_token = (
                        await _derive_facebook_page_token(token, page_id)
                        if page_id else None
                    )
                    metrics = await pull_facebook_insights(content, page_token or token)
                elif channel == "linkedin":
                    token = ch_cfg.get("access_token") or creds.get(
                        "linkedin_access_token", ""
                    )
                    org_id = ch_cfg.get("org_id") or creds.get("linkedin_org_id", "")
                    metrics = await pull_linkedin_insights(content, token, org_id)
                elif channel == "x":
                    x_creds = get_platform_credentials(brand, "x")
                    if not all(x_creds.get(name) for name in _X_REQUIRED_CREDS):
                        logger.info(
                            "Skipping engagement pull for content %s — X "
                            "credentials not configured for brand %s",
                            content.id,
                            brand.id,
                        )
                        continue
                    metrics = await pull_x_public_metrics(content, x_creds)
                elif channel == "youtube":
                    yt_creds = get_platform_credentials(brand, "youtube")
                    api_key = yt_creds.get("api_key") or getattr(
                        settings, "YOUTUBE_API_KEY", ""
                    )
                    if not api_key:
                        logger.info(
                            "Skipping engagement pull for content %s — no "
                            "YouTube Data API key for brand %s",
                            content.id,
                            brand.id,
                        )
                        continue
                    metrics = await pull_youtube_statistics(content, api_key)
                elif channel in UNSUPPORTED_ENGAGEMENT_CHANNELS:
                    logger.info(
                        "Skipping engagement pull for content %s — channel "
                        "'%s' unsupported: %s",
                        content.id,
                        channel,
                        UNSUPPORTED_ENGAGEMENT_CHANNELS[channel],
                    )
                    continue
                else:
                    logger.info(
                        "Skipping engagement pull for content %s — channel "
                        "'%s' has no engagement integration",
                        content.id,
                        channel,
                    )
                    continue

                await upsert_engagement(
                    db, content.id, cal_item.id, cal_item.brand_id, channel, metrics
                )
                logger.debug(
                    "Pulled engagement for content %s on %s", content.id, channel
                )

            except Exception as e:
                logger.warning(
                    "Engagement pull failed for content %s on %s: %s",
                    content.id,
                    channel,
                    e,
                )
