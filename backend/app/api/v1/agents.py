import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.agent_run import AgentRun
from app.services import audit_service, nats_service

logger = logging.getLogger(__name__)

router = APIRouter()

# The status the worker records when a graph interrupt()s for human review.
_PAUSED_STATUS = "paused_for_review"

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


def _interrupt_summary(output_payload) -> dict:
    """Human-facing summary of a paused run's interrupt payload.

    The worker stores ONLY {"paused_for_review": True, "interrupts": [...]}
    on pause — each interrupt being {"value": <payload>, "interrupt_id": ...}
    with value keys like type/message (see agents/worker._record_paused_run).
    Odd or legacy shapes degrade to empty fields, never a 500.
    """
    interrupts = (output_payload or {}).get("interrupts")
    if not isinstance(interrupts, list):
        interrupts = []
    first = interrupts[0] if interrupts else None
    value = first.get("value") if isinstance(first, dict) else None
    if not isinstance(value, dict):
        value = {"message": str(value)} if value is not None else {}
    return {
        "type": value.get("type"),
        "message": value.get("message"),
        "interrupt_id": first.get("interrupt_id") if isinstance(first, dict) else None,
        "count": len(interrupts),
    }


@router.get("/runs/paused")
async def list_paused_agent_runs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Runs waiting on a human decision (status paused_for_review).

    Any authenticated role may view; the decision itself goes through
    POST /runs/{run_id}/review (manager/admin only).
    """
    stmt = (
        select(AgentRun)
        .options(selectinload(AgentRun.brand))
        .where(AgentRun.status == _PAUSED_STATUS)
        .order_by(AgentRun.created_at.desc())
        .limit(100)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()

    return [
        {
            "id": str(run.id),
            "workflow_type": run.agent_type,
            "brand_id": str(run.brand_id) if run.brand_id else None,
            "brand_name": run.brand.name if run.brand else None,
            "trigger": run.trigger,
            "created_at": run.created_at.isoformat(),
            "paused_at": run.completed_at.isoformat() if run.completed_at else None,
            "interrupt": _interrupt_summary(run.output_payload),
        }
        for run in runs
    ]


class AgentRunReview(BaseModel):
    action: Literal["approve", "reject"]
    # Bounded: this string rides the NATS resume payload, the audit record
    # and a revision LLM prompt verbatim — no reason to allow megabytes.
    feedback: str | None = Field(default=None, max_length=4000)


@router.post("/runs/{run_id}/review", status_code=status.HTTP_202_ACCEPTED)
async def review_agent_run(
    run_id: uuid.UUID,
    payload: AgentRunReview,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Approve/reject a paused run and ask the worker to resume it.

    Manager/admin only. The backend NEVER touches agent_runs.status — the
    worker owns the paused_for_review→running CAS transition (single writer).
    This endpoint only validates, audits, and publishes the resume request;
    a lost message leaves the run paused and the operator simply clicks again.
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    if run.status != _PAUSED_STATUS:
        raise HTTPException(
            status_code=409,
            detail=f"Run is not awaiting review (status '{run.status}')",
        )

    decision = "approved" if payload.action == "approve" else "rejected"
    # Pinned resume contract — the worker's agent.resume.run handler
    # depends on these exact keys.
    resume_payload = {
        "run_id": str(run.id),
        "workflow_type": run.agent_type,
        "decision": decision,
        "feedback": payload.feedback,
        "actor": current_user.email,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await nats_service.publish("agent.resume.run", resume_payload)
    except Exception as exc:
        # Fail closed: no 202 without a dispatched resume. The run stays
        # paused_for_review, so a retry is always safe.
        logger.error("Resume dispatch failed for run %s: %s", run_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Could not dispatch the resume request; the run stays paused — try again",
        )

    await audit_service.record_audit(
        action=payload.action,
        entity_type="agent_run",
        user_id=current_user.id,
        entity_id=run_id,
        old_values={"status": _PAUSED_STATUS},
        new_values={"decision": decision, "feedback": payload.feedback},
        request=request,
    )
    logger.info(
        "Agent run %s %s by %s — resume requested",
        run_id,
        decision,
        current_user.email,
    )
    return {"status": "resume_requested"}


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
