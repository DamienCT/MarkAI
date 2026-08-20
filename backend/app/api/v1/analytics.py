import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.services.ai_model_service import (
    _cache_delete_pattern,
    _cache_get,
    _cache_set,
)

router = APIRouter()

_ANALYTICS_CACHE_TTL = 300  # 5 minutes


@router.post("/refresh")
async def refresh_engagement(
    current_user: User = Depends(get_current_user),
):
    """Manually trigger an engagement pull from the social platforms — the same
    job that otherwise runs every 6h. Runs synchronously so the caller can
    refetch the dashboards as soon as it returns."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    from app.scheduler.engagement_puller import pull_all_engagement

    try:
        await pull_all_engagement()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"Engagement pull failed: {exc}"
        ) from exc
    # Invalidate cached summaries so the dashboard reflects the fresh pull
    # immediately instead of serving the pre-pull (often zero) cache.
    await _cache_delete_pattern("markai:analytics:*")
    return {"status": "ok"}


@router.get("/summary")
async def get_analytics_summary(
    brand_id: uuid.UUID | None = None,
    channel: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """High-level analytics summary, optionally scoped to a brand and/or channel."""
    cache_key = f"markai:analytics:summary:{brand_id or 'all'}:{channel or 'all'}"
    cached = await _cache_get(cache_key)
    if cached:
        return json.loads(cached)

    where = []
    params: dict = {}
    if brand_id is not None:
        where.append("brand_id = :brand_id")
        params["brand_id"] = brand_id
    if channel is not None:
        where.append("channel = :channel")
        params["channel"] = channel
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    # Published-post count honors the same brand/channel scope.
    pub_where = ["status = 'published'"]
    if brand_id is not None:
        pub_where.append("brand_id = :brand_id")
    if channel is not None:
        pub_where.append("channel = :channel")
    pub_sql = " AND ".join(pub_where)

    # engagement_metrics rows are cumulative lifetime snapshots pulled every
    # ~6h — summing them all counts each post once per snapshot (~4x/day).
    # Aggregate only the latest snapshot per content_id.
    row = (
        await db.execute(
            text(f"""
            WITH latest AS (
                SELECT DISTINCT ON (content_id) *
                FROM engagement_metrics{where_sql}
                ORDER BY content_id, fetched_at DESC
            )
            SELECT
                COALESCE(SUM(impressions), 0) AS total_impressions,
                COALESCE(SUM(likes), 0) AS total_likes,
                COALESCE(SUM(comments), 0) AS total_comments,
                COALESCE(SUM(shares), 0) AS total_shares,
                COALESCE(SUM(reach), 0) AS total_reach,
                COALESCE(SUM(clicks), 0) AS total_clicks,
                COALESCE(AVG(engagement_rate), 0) AS avg_engagement_rate,
                (SELECT count(*) FROM calendar_items WHERE {pub_sql}) AS total_published
            FROM latest
        """),
            params,
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
    await _cache_set(cache_key, json.dumps(result), ttl=_ANALYTICS_CACHE_TTL)
    return result


@router.get("/engagement/timeseries")
async def get_engagement_timeseries(
    days: int = 30,
    brand_id: uuid.UUID | None = None,
    channel: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Daily engagement metrics over time."""
    days = min(max(days, 1), 365)
    # Snapshots are cumulative and land ~4x/day — keep only the latest
    # snapshot per content per day, so each day shows totals-to-date once.
    query = """
        WITH latest AS (
            SELECT DISTINCT ON (content_id, DATE(fetched_at)) *
            FROM engagement_metrics
            WHERE fetched_at >= NOW() - MAKE_INTERVAL(days => :days)
    """
    params: dict = {"days": days}
    if brand_id:
        query += " AND brand_id = :brand_id"
        params["brand_id"] = brand_id
    if channel:
        query += " AND channel = :channel"
        params["channel"] = channel
    query += """
            ORDER BY content_id, DATE(fetched_at), fetched_at DESC
        )
        SELECT
            DATE(fetched_at) as date,
            COALESCE(SUM(likes), 0) as likes,
            COALESCE(SUM(comments), 0) as comments,
            COALESCE(SUM(shares), 0) as shares,
            COALESCE(SUM(impressions), 0) as impressions,
            COALESCE(AVG(engagement_rate), 0) as engagement_rate
        FROM latest
        GROUP BY DATE(fetched_at) ORDER BY date
    """
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
    brand_id: uuid.UUID | None = None,
    channel: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Posting frequency by day-of-week and hour."""
    query = """
        SELECT
            EXTRACT(DOW FROM scheduled_at) as day,
            EXTRACT(HOUR FROM scheduled_at) as hour,
            COUNT(*) as count
        FROM calendar_items
        WHERE scheduled_at IS NOT NULL AND status IN ('published', 'scheduled')
    """
    params: dict = {}
    if brand_id:
        query += " AND brand_id = :brand_id"
        params["brand_id"] = brand_id
    if channel:
        query += " AND channel = :channel"
        params["channel"] = channel
    query += " GROUP BY EXTRACT(DOW FROM scheduled_at), EXTRACT(HOUR FROM scheduled_at) ORDER BY day, hour"
    rows = await db.execute(text(query), params)
    return [
        {"day": int(row[0]), "hour": int(row[1]), "count": int(row[2])}
        for row in rows.fetchall()
    ]


@router.get("/content/top")
async def get_top_content(
    limit: int = 20,
    brand_id: uuid.UUID | None = None,
    channel: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Top performing content by engagement."""
    limit = min(limit, 200)
    # Join only the latest cumulative snapshot per content_id — summing every
    # ~6h snapshot inflated each item's numbers ~4x/day.
    query = """
            WITH latest_em AS (
                SELECT DISTINCT ON (content_id) *
                FROM engagement_metrics
                ORDER BY content_id, fetched_at DESC
            )
            SELECT
                ci.id, ci.title, ci.channel, ci.status,
                ci.scheduled_at, ci.published_at,
                COALESCE(SUM(em.likes), 0) as total_likes,
                COALESCE(SUM(em.comments), 0) as total_comments,
                COALESCE(SUM(em.shares), 0) as total_shares,
                COALESCE(SUM(em.impressions), 0) as total_impressions,
                COALESCE(AVG(em.engagement_rate), 0) as avg_engagement_rate
            FROM calendar_items ci
            LEFT JOIN latest_em em ON ci.id = em.calendar_item_id
            WHERE ci.status = 'published'
    """
    params: dict = {"lim": limit}
    if brand_id:
        query += " AND ci.brand_id = :brand_id"
        params["brand_id"] = brand_id
    if channel:
        query += " AND ci.channel = :channel"
        params["channel"] = channel
    query += """
            GROUP BY ci.id, ci.title, ci.channel, ci.status, ci.scheduled_at, ci.published_at
            ORDER BY COALESCE(SUM(em.likes), 0) + COALESCE(SUM(em.comments), 0) + COALESCE(SUM(em.shares), 0) DESC
            LIMIT :lim
    """
    rows = await db.execute(text(query), params)
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


@router.get("/by-channel")
async def get_engagement_by_channel(
    days: int = 30,
    brand_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Engagement aggregated per channel — powers the per-channel breakdown
    (donut + comparative cards). Engagement only exists for IG/FB/LinkedIn."""
    days = min(max(days, 1), 365)
    # Aggregate the latest cumulative snapshot per content_id only — raw rows
    # repeat every ~6h and would inflate each channel ~4x/day.
    query = """
        WITH latest AS (
            SELECT DISTINCT ON (content_id) *
            FROM engagement_metrics
            WHERE fetched_at >= NOW() - MAKE_INTERVAL(days => :days)
    """
    params: dict = {"days": days}
    if brand_id:
        query += " AND brand_id = :brand_id"
        params["brand_id"] = brand_id
    query += """
            ORDER BY content_id, fetched_at DESC
        )
        SELECT
            channel,
            COALESCE(SUM(impressions), 0) as impressions,
            COALESCE(SUM(reach), 0) as reach,
            COALESCE(SUM(likes), 0) as likes,
            COALESCE(SUM(comments), 0) as comments,
            COALESCE(SUM(shares), 0) as shares,
            COALESCE(SUM(clicks), 0) as clicks,
            COALESCE(AVG(engagement_rate), 0) as engagement_rate,
            COUNT(DISTINCT content_id) as posts
        FROM latest
        GROUP BY channel ORDER BY impressions DESC
    """
    rows = await db.execute(text(query), params)
    return [
        {
            "channel": row[0],
            "impressions": int(row[1]),
            "reach": int(row[2]),
            "likes": int(row[3]),
            "comments": int(row[4]),
            "shares": int(row[5]),
            "clicks": int(row[6]),
            "engagement_rate": round(float(row[7]), 4),
            "posts": int(row[8]),
            "engagements": int(row[3]) + int(row[4]) + int(row[5]),
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
    # Latest cumulative snapshot per content_id only — see get_analytics_summary.
    rows = await db.execute(
        text("""
            WITH latest AS (
                SELECT DISTINCT ON (content_id) *
                FROM engagement_metrics
                WHERE brand_id = :brand_id
                ORDER BY content_id, fetched_at DESC
            )
            SELECT
                COALESCE(SUM(em.likes), 0),
                COALESCE(SUM(em.comments), 0),
                COALESCE(SUM(em.shares), 0),
                COALESCE(SUM(em.impressions), 0),
                COALESCE(SUM(em.reach), 0),
                COALESCE(AVG(em.engagement_rate), 0),
                COUNT(DISTINCT ci.id)
            FROM latest em
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
