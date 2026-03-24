import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.models.engagement import EngagementMetric
from app.schemas.engagement import EngagementAggregation


async def get_engagement_by_content(
    db: AsyncSession,
    content_id: uuid.UUID,
) -> Sequence[EngagementMetric]:
    result = await db.execute(
        select(EngagementMetric)
        .where(EngagementMetric.content_id == content_id)
        .order_by(EngagementMetric.fetched_at.desc())
    )
    return result.scalars().all()


async def get_aggregated_engagement(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    channel: str | None = None,
) -> EngagementAggregation:
    stmt = select(
        func.sum(EngagementMetric.impressions).label("total_impressions"),
        func.sum(EngagementMetric.reach).label("total_reach"),
        func.sum(EngagementMetric.likes).label("total_likes"),
        func.sum(EngagementMetric.comments).label("total_comments"),
        func.sum(EngagementMetric.shares).label("total_shares"),
        func.sum(EngagementMetric.saves).label("total_saves"),
        func.sum(EngagementMetric.clicks).label("total_clicks"),
        func.sum(EngagementMetric.video_views).label("total_video_views"),
        func.avg(EngagementMetric.engagement_rate).label("avg_engagement_rate"),
        func.count(func.distinct(EngagementMetric.content_id)).label("content_count"),
    )

    if brand_id is not None:
        stmt = stmt.where(EngagementMetric.brand_id == brand_id)
    if start_date is not None:
        stmt = stmt.where(EngagementMetric.fetched_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(EngagementMetric.fetched_at <= end_date)
    if channel is not None:
        stmt = stmt.where(EngagementMetric.channel == channel)

    result = await db.execute(stmt)
    row = result.one()

    return EngagementAggregation(
        total_impressions=row.total_impressions or 0,
        total_reach=row.total_reach or 0,
        total_likes=row.total_likes or 0,
        total_comments=row.total_comments or 0,
        total_shares=row.total_shares or 0,
        total_saves=row.total_saves or 0,
        total_clicks=row.total_clicks or 0,
        total_video_views=row.total_video_views or 0,
        avg_engagement_rate=float(row.avg_engagement_rate) if row.avg_engagement_rate else None,
        content_count=row.content_count or 0,
    )


async def get_engagement_timeseries(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    channel: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[dict]:
    """Return daily engagement aggregations for charting."""
    date_col = func.date(EngagementMetric.fetched_at).label("date")
    stmt = select(
        date_col,
        func.sum(EngagementMetric.impressions).label("impressions"),
        func.sum(EngagementMetric.likes).label("likes"),
        func.sum(EngagementMetric.comments).label("comments"),
        func.sum(EngagementMetric.shares).label("shares"),
    ).group_by(date_col).order_by(date_col)

    if brand_id is not None:
        stmt = stmt.where(EngagementMetric.brand_id == brand_id)
    if channel is not None:
        stmt = stmt.where(EngagementMetric.channel == channel)
    if start_date is not None:
        stmt = stmt.where(EngagementMetric.fetched_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(EngagementMetric.fetched_at <= end_date)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "date": str(row.date),
            "impressions": row.impressions or 0,
            "likes": row.likes or 0,
            "comments": row.comments or 0,
            "shares": row.shares or 0,
        }
        for row in rows
    ]
