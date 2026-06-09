import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.services.ai_model_service import _cache_get, _cache_set

router = APIRouter()

_DASHBOARD_CACHE_TTL = 300  # 5 minutes


@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate dashboard statistics."""
    cached = await _cache_get("markai:dashboard:stats")
    if cached:
        return json.loads(cached)

    row = (
        await db.execute(
            text("""
            SELECT
                (SELECT count(*) FROM brands WHERE status = 'active') AS active_brands,
                (SELECT count(*) FROM calendar_items
                   WHERE status IN ('queued', 'working', 'in_review', 'reworking')) AS content_in_pipeline,
                (SELECT count(*) FROM approvals WHERE status = 'pending') AS pending_approvals,
                (SELECT count(*) FROM calendar_items WHERE status = 'scheduled') AS scheduled_posts,
                (SELECT count(*) FROM calendar_items WHERE status = 'published' AND published_at >= now() - interval '7 days') AS published_this_week,
                (SELECT count(*) FROM agent_runs WHERE status = 'running') AS active_workflows
        """)
        )
    ).fetchone()

    result = {
        # Field names MUST match the frontend DashboardStats interface.
        "active_brands": int(row[0]),
        "content_in_pipeline": int(row[1]),
        "pending_approvals": int(row[2]),
        "scheduled_posts": int(row[3]),
        "published_this_week": int(row[4]),
        "active_workflows": int(row[5]),
    }
    await _cache_set(
        "markai:dashboard:stats", json.dumps(result), ttl=_DASHBOARD_CACHE_TTL
    )
    return result


_ALLOWED_CHART_DAYS = (30, 60, 90, 120)


@router.get("/charts")
async def dashboard_charts(
    days: int = Query(30, description="Window for the published-per-day series"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chart data for the dashboard.

    - published_per_day: zero-filled daily publish count over the last `days`
      days (so gaps show as 0 in the chart).
    - published_by_channel: posts published in the CURRENT calendar month,
      grouped by channel (donut).
    """
    if days not in _ALLOWED_CHART_DAYS:
        days = 30

    cache_key = f"markai:dashboard:charts:{days}"
    cached = await _cache_get(cache_key)
    if cached:
        return json.loads(cached)

    # Zero-filled daily series via generate_series LEFT JOINed to actual counts.
    per_day_rows = (
        await db.execute(
            text("""
            SELECT to_char(d.day, 'YYYY-MM-DD') AS day,
                   COALESCE(c.cnt, 0) AS count
            FROM generate_series(
                   now()::date - (CAST(:days AS int) - 1) * interval '1 day',
                   now()::date,
                   interval '1 day'
                 ) AS d(day)
            LEFT JOIN (
                   SELECT published_at::date AS day, count(*) AS cnt
                   FROM calendar_items
                   WHERE status = 'published'
                     AND published_at >= now()::date - (CAST(:days AS int) - 1) * interval '1 day'
                   GROUP BY published_at::date
                 ) c ON c.day = d.day
            ORDER BY d.day
        """),
            {"days": days},
        )
    ).fetchall()

    by_channel_rows = (
        await db.execute(
            text("""
            SELECT channel, count(*) AS cnt
            FROM calendar_items
            WHERE status = 'published'
              AND published_at >= date_trunc('month', now())
            GROUP BY channel
            ORDER BY cnt DESC
        """)
        )
    ).fetchall()

    result = {
        "days": days,
        "published_per_day": [
            {"day": r[0], "count": int(r[1])} for r in per_day_rows
        ],
        "published_by_channel": [
            {"channel": r[0], "count": int(r[1])} for r in by_channel_rows
        ],
    }
    await _cache_set(cache_key, json.dumps(result), ttl=_DASHBOARD_CACHE_TTL)
    return result
