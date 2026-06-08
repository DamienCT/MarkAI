import json

from fastapi import APIRouter, Depends
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
