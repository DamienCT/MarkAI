import json
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.services.ai_model_service import _cache_get, _cache_set

router = APIRouter()

_ANALYTICS_CACHE_TTL = 300  # 5 minutes


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """High-level analytics summary for the dashboard."""
    cached = await _cache_get("markai:analytics:summary")
    if cached:
        return json.loads(cached)

    row = (
        await db.execute(
            text("""
            SELECT
                COALESCE(SUM(impressions), 0) AS total_impressions,
                COALESCE(SUM(likes), 0) AS total_likes,
                COALESCE(SUM(comments), 0) AS total_comments,
                COALESCE(SUM(shares), 0) AS total_shares,
                COALESCE(SUM(reach), 0) AS total_reach,
                COALESCE(SUM(clicks), 0) AS total_clicks,
                COALESCE(AVG(engagement_rate), 0) AS avg_engagement_rate,
                (SELECT count(*) FROM calendar_items WHERE status = 'published') AS total_published
            FROM engagement_metrics
        """)
        )
    ).fetchone()

    result = {
        "impressions": int(row[0]),
        "likes": int(row[1]),
        "comments": int(row[2]),
        "shares": int(row[3]),
        "reach": int(row[4]),
        "clicks": int(row[5]),
        "engagement_rate": round(float(row[6]), 4),
        "total_published_posts": int(row[7]),
    }
    await _cache_set(
        "markai:analytics:summary", json.dumps(result), ttl=_ANALYTICS_CACHE_TTL
    )
    return result


@router.get("/engagement/timeseries")
async def get_engagement_timeseries(
    days: int = 30,
    brand_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Daily engagement metrics over time."""
    days = min(max(days, 1), 365)
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
        params["brand_id"] = brand_id
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
    rows = await db.execute(
        text("""
        SELECT
            EXTRACT(DOW FROM scheduled_at) as day,
            EXTRACT(HOUR FROM scheduled_at) as hour,
            COUNT(*) as count
        FROM calendar_items
        WHERE scheduled_at IS NOT NULL AND status IN ('published', 'scheduled')
        GROUP BY EXTRACT(DOW FROM scheduled_at), EXTRACT(HOUR FROM scheduled_at)
        ORDER BY day, hour
    """)
    )
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
    limit = min(limit, 200)
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


@router.get("/brands/{brand_id}/metrics")
async def get_brand_metrics(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Engagement metrics for a specific brand."""
    rows = await db.execute(
        text("""
            SELECT
                COALESCE(SUM(em.likes), 0),
                COALESCE(SUM(em.comments), 0),
                COALESCE(SUM(em.shares), 0),
                COALESCE(SUM(em.impressions), 0),
                COALESCE(SUM(em.reach), 0),
                COALESCE(AVG(em.engagement_rate), 0),
                COUNT(DISTINCT ci.id)
            FROM engagement_metrics em
            JOIN calendar_items ci ON em.calendar_item_id = ci.id
            WHERE ci.brand_id = :brand_id
        """),
        {"brand_id": brand_id},
    )
    row = rows.fetchone()
    if not row:
        return {
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "impressions": 0,
            "reach": 0,
            "engagement_rate": 0,
            "total_posts": 0,
        }
    return {
        "likes": int(row[0]),
        "comments": int(row[1]),
        "shares": int(row[2]),
        "impressions": int(row[3]),
        "reach": int(row[4]),
        "engagement_rate": round(float(row[5]), 4),
        "total_posts": int(row[6]),
    }
