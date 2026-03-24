import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.adaptation import Adaptation
from app.models.agent_run import AgentRun
from app.models.competitor import Competitor
from app.services import nats_service
from sqlalchemy import func

router = APIRouter()


@router.get("/reports")
async def list_intelligence_reports(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent agent run reports (research, strategy, product intel)."""
    stmt = (
        select(AgentRun)
        .where(AgentRun.agent_type.in_(["research", "strategy", "product_intel"]))
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "agent_type": r.agent_type,
            "brand_id": str(r.brand_id) if r.brand_id else None,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "duration_ms": r.duration_ms,
        }
        for r in runs
    ]


@router.get("/trends")
async def list_intelligence_trends(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent competitor analysis and market trends."""
    stmt = (
        select(Competitor)
        .where(Competitor.is_active == True)
        .order_by(Competitor.updated_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    competitors = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "brand_id": str(c.brand_id),
            "name": c.name,
            "website_url": c.website_url,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in competitors
    ]


class WorkflowTrigger(BaseModel):
    brand_id: uuid.UUID
    params: dict = {}


@router.get("/research/{brand_id}")
async def get_research_results(
    brand_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get latest research agent runs and competitor analyses for a brand."""
    # Fetch recent research agent runs
    runs_result = await db.execute(
        select(AgentRun)
        .where(AgentRun.brand_id == brand_id)
        .where(AgentRun.agent_type == "research")
        .order_by(AgentRun.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    runs = runs_result.scalars().all()

    # Fetch competitors
    competitors_result = await db.execute(
        select(Competitor)
        .where(Competitor.brand_id == brand_id)
        .order_by(Competitor.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    competitors = competitors_result.scalars().all()

    return {
        "agent_runs": [
            {
                "id": str(run.id),
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "output_payload": run.output_payload,
            }
            for run in runs
        ],
        "competitors": [
            {
                "id": str(c.id),
                "name": c.name,
                "website_url": c.website_url,
                "social_handles": c.social_handles,
                "description": c.description,
                "monitoring_config": c.monitoring_config,
                "is_active": c.is_active,
            }
            for c in competitors
        ],
    }


@router.get("/adaptations/{content_id}")
async def get_adaptations(
    content_id: uuid.UUID,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get adaptations for a content item."""
    stmt = (
        select(Adaptation)
        .where(Adaptation.source_content_id == content_id)
        .order_by(Adaptation.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(Adaptation.status == status_filter)

    result = await db.execute(stmt)
    adaptations = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "source_content_id": str(a.source_content_id),
            "target_channel": a.target_channel,
            "adapted_text": a.adapted_text,
            "adapted_headline": a.adapted_headline,
            "adapted_hashtags": a.adapted_hashtags,
            "adapted_media": a.adapted_media,
            "adaptation_notes": a.adaptation_notes,
            "ai_model": a.ai_model,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
        }
        for a in adaptations
    ]


@router.post("/trigger/research")
async def trigger_research(
    trigger: WorkflowTrigger,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger a research workflow for a brand via NATS."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await nats_service.publish(
        "research.trigger",
        {
            "brand_id": str(trigger.brand_id),
            "triggered_by": str(current_user.id),
            "params": trigger.params,
            "timestamp": datetime.now().isoformat(),
        },
    )

    return {"message": "Research workflow triggered", "brand_id": str(trigger.brand_id)}


@router.post("/trigger/strategy")
async def trigger_strategy(
    trigger: WorkflowTrigger,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger a strategy workflow for a brand via NATS."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await nats_service.publish(
        "strategy.trigger",
        {
            "brand_id": str(trigger.brand_id),
            "triggered_by": str(current_user.id),
            "params": trigger.params,
            "timestamp": datetime.now().isoformat(),
        },
    )

    return {"message": "Strategy workflow triggered", "brand_id": str(trigger.brand_id)}


@router.post("/trigger/content")
async def trigger_content_generation(
    trigger: WorkflowTrigger,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger content generation workflow for a brand via NATS."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await nats_service.publish(
        "content.generate",
        {
            "brand_id": str(trigger.brand_id),
            "triggered_by": str(current_user.id),
            "params": trigger.params,
            "timestamp": datetime.now().isoformat(),
        },
    )

    return {
        "message": "Content generation workflow triggered",
        "brand_id": str(trigger.brand_id),
    }
