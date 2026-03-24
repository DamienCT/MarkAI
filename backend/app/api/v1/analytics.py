import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db

router = APIRouter()


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """High-level analytics summary for the dashboard."""
    total_impressions = (
        await db.execute(text("SELECT COALESCE(SUM(impressions), 0) FROM engagement_metrics"))
    ).scalar() or 0
    total_likes = (
        await db.execute(text("SELECT COALESCE(SUM(likes), 0) FROM engagement_metrics"))
    ).scalar() or 0
    total_comments = (
        await db.execute(text("SELECT COALESCE(SUM(comments), 0) FROM engagement_metrics"))
    ).scalar() or 0
    total_shares = (
        await db.execute(text("SELECT COALESCE(SUM(shares), 0) FROM engagement_metrics"))
    ).scalar() or 0
    total_reach = (
        await db.execute(text("SELECT COALESCE(SUM(reach), 0) FROM engagement_metrics"))
    ).scalar() or 0
    total_clicks = (
        await db.execute(text("SELECT COALESCE(SUM(clicks), 0) FROM engagement_metrics"))
    ).scalar() or 0
    avg_engagement_rate = (
        await db.execute(text("SELECT COALESCE(AVG(engagement_rate), 0) FROM engagement_metrics"))
    ).scalar() or 0.0
    total_published = (
        await db.execute(text("SELECT count(*) FROM calendar_items WHERE status = 'published'"))
    ).scalar() or 0

    return {
        "impressions": int(total_impressions),
        "likes": int(total_likes),
        "comments": int(total_comments),
        "shares": int(total_shares),
        "reach": int(total_reach),
        "clicks": int(total_clicks),
        "engagement_rate": round(float(avg_engagement_rate), 4),
        "total_published_posts": total_published,
    }


@router.get("/engagement/timeseries")
async def get_engagement_timeseries(
    days: int = 30,
    brand_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Daily engagement metrics over time."""
    query = """
        SELECT
            DATE(fetched_at) as date,
            COALESCE(SUM(likes), 0) as likes,
            COALESCE(SUM(comments), 0) as comments,
            COALESCE(SUM(shares), 0) as shares,
            COALESCE(SUM(impressions), 0) as impressions,
            COALESCE(AVG(engagement_rate), 0) as engagement_rate
        FROM engagement_metrics
        WHERE fetched_at >= NOW() - MAKE_INTERVAL(days => :days)
    """
    params: dict = {"days": days}
    if brand_id:
        query += " AND brand_id = :brand_id"
        params["brand_id"] = str(brand_id)
    query += " GROUP BY DATE(fetched_at) ORDER BY date"
    rows = await db.execute(text(query), params)
    return [
        {
            "date": str(row[0]),
            "likes": int(row[1]),
            "comments": int(row[2]),
            "shares": int(row[3]),
            "impressions": int(row[4]),
            "engagement_rate": round(float(row[5]), 4),
        }
        for row in rows.fetchall()
    ]


@router.get("/posting/heatmap")
async def get_posting_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Posting frequency by day-of-week and hour."""
    rows = await db.execute(text("""
        SELECT
            EXTRACT(DOW FROM scheduled_at) as day,
            EXTRACT(HOUR FROM scheduled_at) as hour,
            COUNT(*) as count
        FROM calendar_items
        WHERE scheduled_at IS NOT NULL AND status IN ('published', 'scheduled')
        GROUP BY EXTRACT(DOW FROM scheduled_at), EXTRACT(HOUR FROM scheduled_at)
        ORDER BY day, hour
    """))
    return [
        {"day": int(row[0]), "hour": int(row[1]), "count": int(row[2])}
        for row in rows.fetchall()
    ]


@router.get("/content/top")
async def get_top_content(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top performing content by engagement."""
    rows = await db.execute(
        text("""
            SELECT
                ci.id, ci.title, ci.channel, ci.status,
                ci.scheduled_at, ci.published_at,
                COALESCE(SUM(em.likes), 0) as total_likes,
                COALESCE(SUM(em.comments), 0) as total_comments,
                COALESCE(SUM(em.shares), 0) as total_shares,
                COALESCE(SUM(em.impressions), 0) as total_impressions,
                COALESCE(AVG(em.engagement_rate), 0) as avg_engagement_rate
            FROM calendar_items ci
            LEFT JOIN engagement_metrics em ON ci.id = em.calendar_item_id
            WHERE ci.status = 'published'
            GROUP BY ci.id, ci.title, ci.channel, ci.status, ci.scheduled_at, ci.published_at
            ORDER BY COALESCE(SUM(em.likes), 0) + COALESCE(SUM(em.comments), 0) + COALESCE(SUM(em.shares), 0) DESC
            LIMIT :lim
        """),
        {"lim": limit},
    )
    return [
        {
            "id": str(row[0]),
            "title": row[1],
            "channel": row[2],
            "status": row[3],
            "scheduled_at": row[4].isoformat() if row[4] else None,
            "published_at": row[5].isoformat() if row[5] else None,
            "likes": int(row[6]),
            "comments": int(row[7]),
            "shares": int(row[8]),
            "impressions": int(row[9]),
            "engagement_rate": round(float(row[10]), 4),
        }
        for row in rows.fetchall()
    ]
