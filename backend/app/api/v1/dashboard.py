import calendar
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.services.ai_model_service import _cache_get, _cache_set

router = APIRouter()

_DASHBOARD_CACHE_TTL = 300  # 5 minutes


def _weekly_cadence(cadence) -> int:
    """Sum posts_per_week across a strategy cadence object.

    The cadence is keyed by channel; each value is usually a dict carrying
    ``posts_per_week`` (sometimes ``frequency``), but may also be a bare number.
    Anything unparseable contributes 0.
    """
    if not isinstance(cadence, dict):
        return 0
    total = 0
    for cfg in cadence.values():
        if isinstance(cfg, dict):
            ppw = cfg.get("posts_per_week", cfg.get("frequency", 0))
        elif isinstance(cfg, (int, float)):
            ppw = cfg
        else:
            ppw = 0
        try:
            total += int(ppw)
        except (ValueError, TypeError):
            pass
    return total


@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate dashboard statistics.

    Workflow counters are computed LIVE on every call (cheap counts) so the
    dashboard's Active Workflows matches the System page in real time. The
    heavier/slower-changing stats are cached for ``_DASHBOARD_CACHE_TTL``.
    """
    # ── Live workflow counters (never cached) ─────────────────────────
    wf = (
        await db.execute(
            text("""
            SELECT
                (SELECT count(*) FROM agent_runs WHERE status = 'running') AS active_workflows,
                (SELECT count(*) FROM agent_runs WHERE status IN ('running', 'pending')) AS workflows_running_pending,
                (SELECT count(*) FROM agent_runs WHERE status = 'completed') AS workflows_completed,
                (SELECT count(*) FROM agent_runs WHERE status = 'failed') AS workflows_failed
        """)
        )
    ).fetchone()
    workflow_counts = {
        "active_workflows": int(wf[0]),
        "workflows_running_pending": int(wf[1]),
        "workflows_completed": int(wf[2]),
        "workflows_failed": int(wf[3]),
    }

    # ── Cached base stats ─────────────────────────────────────────────
    cached = await _cache_get("markai:dashboard:stats:v4")
    if cached:
        return {**json.loads(cached), **workflow_counts}

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
                (SELECT count(*) FROM calendar_items WHERE status = 'published' AND published_at >= date_trunc('month', now())) AS published_this_month
        """)
        )
    ).fetchone()

    # Monthly goal (option A): sum each active brand's latest strategy cadence
    # (posts_per_week per channel), scaled to the number of weeks in this month.
    cadence_rows = (
        await db.execute(
            text("""
            SELECT (
                SELECT ar.output_payload -> 'cadence'
                FROM agent_runs ar
                WHERE ar.brand_id = b.id
                  AND ar.agent_type = 'strategy'
                  AND ar.status = 'completed'
                ORDER BY ar.created_at DESC
                LIMIT 1
            ) AS cadence
            FROM brands b
            WHERE b.status = 'active'
        """)
        )
    ).fetchall()

    weekly_target = sum(_weekly_cadence(r[0]) for r in cadence_rows)
    now = datetime.utcnow()
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    monthly_target = round(weekly_target * days_in_month / 7)

    base = {
        # Field names MUST match the frontend DashboardStats interface.
        "active_brands": int(row[0]),
        "content_in_pipeline": int(row[1]),
        "pending_approvals": int(row[2]),
        "scheduled_posts": int(row[3]),
        "published_this_week": int(row[4]),
        # Monthly cadence goal for the dashboard ring.
        "monthly_goal": {
            "published": int(row[5]),
            "target": monthly_target,
        },
    }
    await _cache_set(
        "markai:dashboard:stats:v4", json.dumps(base), ttl=_DASHBOARD_CACHE_TTL
    )
    return {**base, **workflow_counts}


_ALLOWED_CHART_DAYS = (30, 60, 90, 120)


@router.get("/charts")
async def dashboard_charts(
    days: int = Query(30, description="Window for the published-per-day series"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chart data for the dashboard.

    - published_per_day: zero-filled daily series in WIDE format — one row per
      day with a count per channel: {"day": "2026-06-05", "instagram": 2, ...}.
      Drives one superimposed line per channel.
    - channels: distinct channels present in the window (line/legend/filter).
    - published_by_channel: posts published in the CURRENT calendar month,
      grouped by channel (donut).
    """
    if days not in _ALLOWED_CHART_DAYS:
        days = 30

    cache_key = f"markai:dashboard:charts:v2:{days}"
    cached = await _cache_get(cache_key)
    if cached:
        return json.loads(cached)

    # Ordered day list (zero-filled spine for the chart's x-axis).
    day_rows = (
        await db.execute(
            text("""
            SELECT to_char(d.day, 'YYYY-MM-DD') AS day
            FROM generate_series(
                   now()::date - (CAST(:days AS int) - 1) * interval '1 day',
                   now()::date,
                   interval '1 day'
                 ) AS d(day)
            ORDER BY d.day
        """),
            {"days": days},
        )
    ).fetchall()

    # Per-day, per-channel publish counts within the window.
    per_day_channel_rows = (
        await db.execute(
            text("""
            SELECT to_char(published_at::date, 'YYYY-MM-DD') AS day,
                   channel,
                   count(*) AS cnt
            FROM calendar_items
            WHERE status = 'published'
              AND published_at >= now()::date - (CAST(:days AS int) - 1) * interval '1 day'
            GROUP BY published_at::date, channel
        """),
            {"days": days},
        )
    ).fetchall()

    # Distinct channels in the window, ordered by total volume desc.
    channels: list[str] = []
    totals: dict[str, int] = {}
    for _day, channel, cnt in per_day_channel_rows:
        totals[channel] = totals.get(channel, 0) + int(cnt)
    channels = sorted(totals, key=lambda c: totals[c], reverse=True)

    # Pivot into wide rows: {day, <channel>: count, ...} zero-filled per channel.
    counts_by_day: dict[str, dict[str, int]] = {}
    for day, channel, cnt in per_day_channel_rows:
        counts_by_day.setdefault(day, {})[channel] = int(cnt)

    published_per_day = []
    for (day,) in day_rows:
        entry: dict = {"day": day}
        day_counts = counts_by_day.get(day, {})
        for ch in channels:
            entry[ch] = day_counts.get(ch, 0)
        published_per_day.append(entry)

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
        "channels": channels,
        "published_per_day": published_per_day,
        "published_by_channel": [
            {"channel": r[0], "count": int(r[1])} for r in by_channel_rows
        ],
    }
    await _cache_set(cache_key, json.dumps(result), ttl=_DASHBOARD_CACHE_TTL)
    return result
