import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db
from app.models.agent_run import AgentRun

router = APIRouter()


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
            "output_payload": run.output_payload,
            "input_payload": run.input_payload,
            "tokens_used": run.tokens_used,
            "cost_usd": float(run.cost_usd) if run.cost_usd else None,
            "duration_ms": run.duration_ms,
            "created_at": run.created_at.isoformat(),
        }
        for run in runs
    ]
