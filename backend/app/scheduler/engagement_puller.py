import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.base import async_session_factory
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.models.engagement import EngagementMetric
from app.services.engagement_service import (
    pull_facebook_insights,
    pull_instagram_insights,
    pull_linkedin_insights,
)

logger = logging.getLogger(__name__)


async def upsert_engagement(
    db, content_id, calendar_item_id, brand_id, channel: str, metrics: dict
) -> None:
    """Create a new engagement metric record for the given content."""
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
        engagement_rate=metrics.get("engagement_rate"),
        sentiment_score=metrics.get("sentiment_score"),
        raw_metrics=metrics,
        fetched_at=datetime.now(timezone.utc),
    )
    db.add(em)
    await db.commit()


async def pull_all_engagement() -> None:
    """
    Pull engagement metrics directly from social platform APIs.
    No n8n needed -- just HTTP calls using brand credentials.
    """
    logger.info("Starting engagement pull for all published content")

    async with async_session_factory() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        # Find calendar items that are published within the last 30 days
        result = await db.execute(
            select(CalendarItem)
            .where(CalendarItem.status == "published")
            .where(CalendarItem.published_at >= cutoff)
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
                    metrics = await pull_instagram_insights(content, token)
                elif channel == "facebook":
                    token = ch_cfg.get("access_token") or creds.get(
                        "meta_access_token", ""
                    )
                    metrics = await pull_facebook_insights(content, token)
                elif channel == "linkedin":
                    token = ch_cfg.get("access_token") or creds.get(
                        "linkedin_access_token", ""
                    )
                    org_id = ch_cfg.get("org_id") or creds.get("linkedin_org_id", "")
                    metrics = await pull_linkedin_insights(content, token, org_id)
                else:
                    logger.info(
                        "Skipping engagement pull for content %s — channel '%s' "
                        "not yet supported (no API integration for youtube/tiktok/x/website_blog/teams)",
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
