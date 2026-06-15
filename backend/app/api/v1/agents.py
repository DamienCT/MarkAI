import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.models.agent_run import AgentRun

router = APIRouter()

# Image fields the content workflow stored as base64 in output_payload. The
# images live in MinIO; legacy rows still carry the base64 copy, which bloats a
# 50-row response to >100MB and OOM-kills the API. We strip it on read. Targets
# image keys + data: URIs only — long text (strategy/research docs) is kept.
_IMAGE_KEYS = {"generated_image", "branded_image", "composed_image", "product_image"}


def _slim_payload(obj):
    """Recursively replace base64 image blobs with a small placeholder."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _IMAGE_KEYS and isinstance(v, str) and len(v) > 200:
                out[k] = f"[image stripped: {len(v) // 1024} kB]"
            else:
                out[k] = _slim_payload(v)
        return out
    if isinstance(obj, list):
        return [_slim_payload(x) for x in obj]
    if isinstance(obj, str) and obj.startswith("data:") and len(obj) > 200:
        return f"[image stripped: {len(obj) // 1024} kB]"
    return obj


@router.get("/runs/latest-by-type")
async def latest_runs_by_type(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the single most recent run per agent_type for a brand,
    plus content generation stats (calendar items in 7-day window).

    Used by the pipeline display so context generation stages are never
    hidden by a large number of content runs.
    """
    result = await db.execute(
        text(
            "SELECT DISTINCT ON (agent_type) "
            "id, agent_type, trigger, brand_id, status, "
            "started_at, completed_at, error_message, "
            "output_payload, input_payload, tokens_used, "
            "cost_usd, duration_ms, created_at "
            "FROM agent_runs "
            "WHERE brand_id = :bid "
            "ORDER BY agent_type, created_at DESC"
        ),
        {"bid": str(brand_id)},
    )
    rows = result.fetchall()

    # Count calendar items in 7-day window by status bucket
    stats_result = await db.execute(
        text(
            "SELECT "
            "  COUNT(*) FILTER (WHERE status NOT IN ('planned', 'queued', 'failed', 'working')) AS generated, "
            "  COUNT(*) FILTER (WHERE status = 'failed') AS failed, "
            "  COUNT(*) FILTER (WHERE status IN ('queued', 'working')) AS in_progress, "
            "  COUNT(*) FILTER (WHERE status = 'working') AS working, "
            "  COUNT(*) AS total "
            "FROM calendar_items "
            "WHERE brand_id = :bid "
            "  AND scheduled_at BETWEEN NOW() AND NOW() + INTERVAL '7 days'"
        ),
        {"bid": str(brand_id)},
    )
    stats_row = stats_result.fetchone()

    runs = [
        {
            "id": str(r.id),
            "agent_type": r.agent_type,
            "trigger": r.trigger,
            "brand_id": str(r.brand_id),
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "error_message": r.error_message,
            "output_payload": _slim_payload(r.output_payload),
            "input_payload": _slim_payload(r.input_payload),
            "tokens_used": r.tokens_used,
            "cost_usd": float(r.cost_usd) if r.cost_usd else None,
            "duration_ms": r.duration_ms,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]

    return {
        "runs": runs,
        "content_stats": {
            "generated": stats_row.generated if stats_row else 0,
            "failed": stats_row.failed if stats_row else 0,
            "in_progress": stats_row.in_progress if stats_row else 0,
            "working": stats_row.working if stats_row else 0,
            "total": stats_row.total if stats_row else 0,
        },
    }


@router.get("/runs/active")
async def list_active_agent_runs(
    agent_type: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return currently running agent runs with step progress info.

    Used by the frontend workflow tracker to show real-time pipeline progress.
    Includes the calendar_item_id from input_payload and current_step from output_payload.
    """
    stmt = (
        select(AgentRun)
        .where(AgentRun.status == "running")
        .order_by(AgentRun.started_at.desc())
        .limit(50)
    )
    if agent_type:
        stmt = stmt.where(AgentRun.agent_type == agent_type)

    result = await db.execute(stmt)
    runs = result.scalars().all()

    return [
        {
            "id": str(run.id),
            "agent_type": run.agent_type,
            "trigger": run.trigger,
            "brand_id": str(run.brand_id) if run.brand_id else None,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "input_payload": _slim_payload(run.input_payload),
            "output_payload": _slim_payload(run.output_payload),
            "calendar_item_id": (run.input_payload or {}).get("calendar_item_id"),
            "current_step": (run.output_payload or {}).get("current_step"),
            "step_index": (run.output_payload or {}).get("step_index"),
            "total_steps": (run.output_payload or {}).get("total_steps", 10),
            "created_at": run.created_at.isoformat(),
        }
        for run in runs
    ]


@router.get("/runs")
async def list_agent_runs(
    skip: int = 0,
    limit: int = 10,
    brand_id: uuid.UUID | None = None,
    trigger: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent agent runs ordered by created_at descending."""
    limit = min(limit, 200)
    stmt = (
        select(AgentRun).order_by(AgentRun.created_at.desc()).offset(skip).limit(limit)
    )
    if brand_id:
        stmt = stmt.where(AgentRun.brand_id == brand_id)
    if trigger:
        stmt = stmt.where(AgentRun.trigger == trigger)

    result = await db.execute(stmt)
    runs = result.scalars().all()

    return [
        {
            "id": str(run.id),
            "agent_type": run.agent_type,
            "trigger": run.trigger,
            "brand_id": str(run.brand_id) if run.brand_id else None,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_message": run.error_message,
            "output_payload": _slim_payload(run.output_payload),
            "input_payload": _slim_payload(run.input_payload),
            "tokens_used": run.tokens_used,
            "cost_usd": float(run.cost_usd) if run.cost_usd else None,
            "duration_ms": run.duration_ms,
            "created_at": run.created_at.isoformat(),
        }
        for run in runs
    ]
