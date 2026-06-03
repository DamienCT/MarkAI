import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.config import settings
from app.deps import get_current_user, get_db
from slowapi import Limiter
from slowapi.util import get_remote_address

_limiter = Limiter(key_func=get_remote_address)
from app.models.adaptation import Adaptation  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.competitor import Competitor  # noqa: E402
from app.services import brand_service, nats_service  # noqa: E402

logger = logging.getLogger(__name__)

# ── Prompt sanitization (shared implementation) ──────────────────────────
from app.utils.sanitize import sanitize_for_prompt as _sanitize  # noqa: E402


def _is_retryable_llm(exc: BaseException) -> bool:
    """Return True for transient LLM errors worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 502, 503)
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception(_is_retryable_llm),
    reraise=True,
)
async def _call_llm(
    messages: list[dict], temperature: float = 0.7, json_mode: bool = False
) -> str:
    """Call LLM via LiteLLM proxy, falling back to OpenAI directly if LiteLLM fails."""
    from app.services.ai_model_service import get_active_model

    model_id = await get_active_model("text-fast")

    body: dict = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try LiteLLM first
        if settings.LITELLM_BASE_URL:
            try:
                headers = {"Content-Type": "application/json"}
                if settings.LITELLM_MASTER_KEY:
                    headers["Authorization"] = f"Bearer {settings.LITELLM_MASTER_KEY}"
                body_litellm = {**body, "model": f"openai/{model_id}"}
                resp = await client.post(
                    settings.LITELLM_BASE_URL.rstrip("/") + "/v1/chat/completions",
                    headers=headers,
                    json=body_litellm,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as litellm_exc:
                logger.warning(
                    "LiteLLM call failed, falling back to direct OpenAI: %s",
                    litellm_exc,
                )

        # Direct OpenAI fallback
        if not settings.OPENAI_API_KEY:
            raise ValueError(
                "No LLM available: LiteLLM failed and OPENAI_API_KEY not set"
            )

        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            },
            json=body,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


router = APIRouter()


@router.get("/reports")
async def list_intelligence_reports(
    limit: int = 20,
    type: str | None = None,
    brand_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent agent run reports (research, strategy, planning, content_calendar, product_intel).

    Pass ?type=research to filter by a single agent_type.
    Pass ?brand_id=uuid to filter by brand.
    """
    limit = min(limit, 200)
    allowed_types = [
        "research",
        "strategy",
        "planning",
        "content_calendar",
        "content_calendar_strategy",
        "product_intel",
    ]

    if type:
        filter_types = [type] if type in allowed_types else allowed_types
    else:
        filter_types = allowed_types

    stmt = (
        select(AgentRun)
        .where(AgentRun.agent_type.in_(filter_types))
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    if brand_id is not None:
        stmt = stmt.where(AgentRun.brand_id == brand_id)
    result = await db.execute(stmt)
    runs = result.scalars().all()

    # Map agent_runs to the report format the frontend expects
    reports = []
    for r in runs:
        output = r.output_payload if isinstance(r.output_payload, dict) else {}
        # Build a title from agent type
        title = f"{r.agent_type.replace('_', ' ').title()} Report"
        # Extract summary depending on report type
        summary_parts = []

        if r.agent_type == "research":
            gaps = output.get("gaps", [])
            personas = output.get("personas", [])
            if gaps:
                summary_parts.append(f"{len(gaps)} gap(s) identified")
            if personas:
                summary_parts.append(f"{len(personas)} persona(s) built")
            if output.get("competitor_analysis"):
                summary_parts.append(
                    f"{len(output['competitor_analysis'])} competitor(s) analyzed"
                )
        elif r.agent_type == "strategy":
            if output.get("content_pillars"):
                summary_parts.append(
                    f"{len(output['content_pillars'])} content pillar(s)"
                )
            if output.get("target_audiences"):
                summary_parts.append(
                    f"{len(output['target_audiences'])} target audience(s)"
                )
            if output.get("positioning"):
                summary_parts.append("Positioning defined")
            if output.get("posting_cadence"):
                summary_parts.append("Posting cadence set")
        elif r.agent_type == "planning":
            if output.get("campaigns"):
                summary_parts.append(f"{len(output['campaigns'])} campaign(s)")
            if output.get("calendar_summary") or output.get("calendar"):
                summary_parts.append("Calendar summary available")
        elif r.agent_type in ("content_calendar", "content_calendar_strategy"):
            # Markdown document — just note its presence
            if output.get("strategy_document") or output.get("markdown"):
                summary_parts.append("Year-long strategy document")
            if output.get("monthly_themes"):
                summary_parts.append(
                    f"{len(output['monthly_themes'])} monthly theme(s)"
                )

        if not summary_parts:
            # Fallback: generic summary from gaps (legacy)
            gaps = output.get("gaps", [])
            personas = output.get("personas", [])
            if gaps:
                summary_parts.append(f"{len(gaps)} gap(s) identified")
            if personas:
                summary_parts.append(f"{len(personas)} persona(s) built")
            if output.get("competitor_analysis"):
                summary_parts.append(
                    f"{len(output['competitor_analysis'])} competitor(s) analyzed"
                )

        summary = ". ".join(summary_parts) if summary_parts else f"Status: {r.status}"

        # Extract insights from gaps
        gaps = output.get("gaps", [])
        insights = (
            [g.get("description", "") for g in gaps[:5] if isinstance(g, dict)]
            if isinstance(gaps, list)
            else []
        )

        reports.append(
            {
                "id": str(r.id),
                "brand_id": str(r.brand_id) if r.brand_id else None,
                "report_type": r.agent_type,
                "status": r.status,
                "title": title,
                "summary": summary,
                "insights": insights,
                "output_payload": {},  # Excluded from list for performance; use detail endpoint
                "created_at": r.created_at.isoformat(),
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
        )
    return reports


@router.get("/report/{run_id}")
async def get_report(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single agent run report by ID, including brand info."""
    from app.models.brand import Brand

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Report not found")

    brand_name = None
    brand_description = None
    brand_website = None
    brand_industry = None
    brand_logo_url = None
    if run.brand_id:
        brand_result = await db.execute(select(Brand).where(Brand.id == run.brand_id))
        brand = brand_result.scalar_one_or_none()
        if brand:
            brand_name = brand.name
            brand_description = brand.description
            brand_logo_url = brand.logo_url
            guidelines = brand.brand_guidelines or {}
            brand_website = guidelines.get("website_url")
            brand_industry = guidelines.get("industry")

    return {
        "id": str(run.id),
        "agent_type": run.agent_type,
        "brand_id": str(run.brand_id) if run.brand_id else None,
        "brand_name": brand_name,
        "brand_description": brand_description,
        "brand_website": brand_website,
        "brand_industry": brand_industry,
        "brand_logo_url": brand_logo_url,
        "status": run.status,
        "trigger": run.trigger,
        "input_payload": run.input_payload,
        "output_payload": run.output_payload,
        "error_message": run.error_message,
        "tokens_used": run.tokens_used,
        "cost_usd": float(run.cost_usd) if run.cost_usd else None,
        "duration_ms": run.duration_ms,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat(),
    }


# Content keys the editor may overwrite. The plain-English summary is NOT in
# this set — it is regenerated server-side from the edited content on every
# save, so it always reflects the document (it is read-only in the UI).
_EDITABLE_CONTENT_KEYS = {
    "gaps",
    "personas",
    "competitor_analysis",
    "recommendations",
    "notes",
    "positioning",
    "content_pillars",
    "target_audiences",
    "posting_cadence",
    "monthly_themes",
    "campaigns",
    "calendar_items",
    "calendar_summary",
    "strategy_document",
}

# Keys passed to the summary regenerator, by agent type — the meat of each doc.
_SUMMARY_INPUT_KEYS: dict[str, list[str]] = {
    "research": ["gaps", "personas", "competitor_analysis", "recommendations"],
    "strategy": ["positioning", "content_pillars", "target_audiences", "monthly_themes"],
    "planning": ["campaigns", "calendar_summary", "calendar_items"],
    "content_calendar": ["strategy_document", "monthly_themes"],
    "content_calendar_strategy": ["strategy_document", "monthly_themes"],
}

_SUMMARY_TYPE_LABELS = {
    "research": "market research report",
    "strategy": "marketing strategy",
    "planning": "marketing plan",
    "content_calendar": "content calendar strategy",
    "content_calendar_strategy": "content calendar strategy",
}


async def _regenerate_plain_summary(agent_type: str, payload: dict) -> str:
    """Rewrite executive_summary_plain from the (edited) report content.

    Plain English, 3-4 sentences, no jargon — same spirit as the agent-side
    helper. Returns "" on failure so the caller can fall back to the old value.
    """
    import json as _json

    label = _SUMMARY_TYPE_LABELS.get(agent_type, "report")
    keys = _SUMMARY_INPUT_KEYS.get(agent_type, list(payload.keys()))
    subset = {k: payload.get(k) for k in keys if payload.get(k) is not None}
    try:
        payload_json = _json.dumps(subset, default=str)[:12000]
    except (TypeError, ValueError):
        payload_json = str(subset)[:12000]

    system_prompt = (
        "You write plain-English executive summaries for business documents. "
        "Your reader is NOT a marketer — assume IT, finance, or operations. "
        "Rules: 3 to 4 sentences; state what the document covers, the single "
        "most important point, and the main recommended action; plain words "
        "only (define any specialized term inline in parentheses); no bullet "
        "points, no markdown. Return ONLY the summary text."
    )
    user_prompt = (
        f"This is a {label}. Summarize it for a non-marketing reader.\n\n"
        f"Report content (JSON):\n{payload_json}"
    )
    try:
        text = await _call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return str(text or "").strip().strip('"')
    except Exception as exc:  # noqa: BLE001 — summary is best-effort
        logger.warning("Summary regeneration failed for %s: %s", agent_type, exc)
        return ""


class ReportEditBody(BaseModel):
    """Edited report content. `content` carries any of the editable content
    keys (gaps, personas, pillars, calendar items, strategy_document, …).

    The plain-English summary is intentionally NOT accepted here — it is
    regenerated from the edited content on save so it can never drift.
    Edits overwrite in place (Q4: no version history).
    """

    content: dict[str, Any] = {}


@router.patch("/report/{run_id}")
async def edit_report(
    run_id: uuid.UUID,
    body: ReportEditBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Overwrite the editable content of a report and auto-refresh its summary.

    Access is limited to manager+ (same bar as brand creation).
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Report not found")

    payload = dict(run.output_payload) if isinstance(run.output_payload, dict) else {}

    # Overwrite only whitelisted content keys — ignore anything else the client
    # might send (technical/internal keys stay untouched).
    for key, value in (body.content or {}).items():
        if key in _EDITABLE_CONTENT_KEYS:
            payload[key] = value

    # Regenerate the plain-English summary from the edited content (Q3). Keep
    # the previous summary if regeneration fails so we never blank it.
    new_summary = await _regenerate_plain_summary(run.agent_type, payload)
    if new_summary:
        payload["executive_summary_plain"] = new_summary

    run.output_payload = payload
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(run, "output_payload")
    await db.commit()
    await db.refresh(run)

    return {
        "id": str(run.id),
        "agent_type": run.agent_type,
        "output_payload": run.output_payload,
    }


@router.get("/trends")
async def get_trending_topics(
    brand_id: uuid.UUID | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List trending topics discovered + LLM-scored by the 6h cron.

    Returns the highest-scoring topics first. When ``brand_id`` is set,
    scoped to that brand; otherwise returns the global top across all
    brands (with the brand_name on each row so the UI can badge it).
    """
    from app.models.trending_topic import TrendingTopic
    from app.models.brand import Brand

    limit = max(1, min(limit, 100))

    stmt = (
        select(TrendingTopic, Brand.name)
        .join(Brand, Brand.id == TrendingTopic.brand_id)
        .where(TrendingTopic.expires_at > func.now())
        .order_by(
            TrendingTopic.relevance_score.desc(),
            TrendingTopic.discovered_at.desc(),
        )
        .limit(limit)
    )
    if brand_id is not None:
        stmt = stmt.where(TrendingTopic.brand_id == brand_id)

    result = await db.execute(stmt)
    rows = result.all()

    return [
        {
            "id": str(t.id),
            "topic": t.topic,
            "platform": t.source,
            "source_url": t.source_url,
            "relevance_score": t.relevance_score,
            "relevance_reason": t.relevance_reason,
            "llm_angle": t.llm_angle,
            "velocity": t.velocity,
            "raw_metric": t.raw_metric,
            "geo": (
                t.extra_data.get("geo")
                if isinstance(t.extra_data, dict)
                else None
            ),
            "discovered_at": t.discovered_at.isoformat() if t.discovered_at else None,
            "brand_id": str(t.brand_id),
            "brand_name": brand_name,
        }
        for t, brand_name in rows
    ]


# Module-level lock prevents concurrent runs of the trends pull, which is
# expensive (one pytrends call + one LLM call per active brand). The lock
# is reset when the background task finishes — see _run_trends_refresh.
_trends_refresh_in_progress = False


async def _run_trends_refresh() -> None:
    """Background task wrapper that resets the lock when done."""
    global _trends_refresh_in_progress
    try:
        from app.services.trends_service import pull_and_score_all_brands

        await pull_and_score_all_brands()
    except Exception as exc:
        logger.exception("Manual trends refresh failed: %s", exc)
    finally:
        _trends_refresh_in_progress = False


@router.delete("/trends/{trend_id}", status_code=200)
async def delete_trend(
    trend_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a single trending topic by id. Manager+ only.

    UI usage: bulk delete uses Promise.allSettled to call this in parallel
    for each selected trend, mirroring the content stage delete pattern.
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    from app.models.trending_topic import TrendingTopic

    result = await db.execute(
        sa_delete(TrendingTopic).where(TrendingTopic.id == trend_id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Trend not found")
    return {"deleted": result.rowcount}


@router.post("/trends/refresh", status_code=202)
@_limiter.limit("3/hour")
async def trigger_trends_refresh(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """Manually trigger the trends pull + LLM scoring without waiting for
    the 6h cron. Returns immediately; the work runs in the background.

    Capped at 3 calls/hour per IP (slowapi) + a global in-flight lock so
    overlapping clicks don't spawn parallel runs.
    """
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    global _trends_refresh_in_progress
    if _trends_refresh_in_progress:
        raise HTTPException(
            status_code=409,
            detail="A trends refresh is already in progress — wait for it to finish.",
        )

    _trends_refresh_in_progress = True
    background_tasks.add_task(_run_trends_refresh)
    return {"status": "started", "message": "Trends refresh kicked off in the background."}


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
    limit = min(limit, 200)
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
                "completed_at": run.completed_at.isoformat()
                if run.completed_at
                else None,
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
    limit = min(limit, 200)
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {"message": "Strategy workflow triggered", "brand_id": str(trigger.brand_id)}


@router.post("/trigger/planning")
async def trigger_planning(
    trigger: WorkflowTrigger,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger the planning workflow (marketing plan + content calendar) via NATS."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await nats_service.publish(
        "planning.trigger",
        {
            "brand_id": str(trigger.brand_id),
            "triggered_by": str(current_user.id),
            "params": trigger.params,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {"message": "Planning workflow triggered", "brand_id": str(trigger.brand_id)}


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
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {
        "message": "Content generation workflow triggered",
        "brand_id": str(trigger.brand_id),
    }


# ── AI Field Generation ─────────────────────────────────────────────


class AIGenerateFieldRequest(BaseModel):
    brand_id: uuid.UUID
    field: str | None = None  # None = generate all empty fields
    context: dict | None = None  # Extra context (e.g. website URLs)


class AIGenerateFieldResponse(BaseModel):
    fields: dict[str, str]


FIELD_PROMPTS: dict[str, str] = {
    "description": "Write a concise brand description (2-3 sentences) for marketing purposes.",
    "target_audience": "Describe the ideal target audience for this brand (demographics, interests, pain points).",
    "tone_of_voice": "Define the brand's tone of voice as comma-separated adjectives (e.g. 'friendly, professional, witty').",
    "voice_style": "Define the writing style for this brand's content (e.g. 'conversational', 'formal', 'storytelling').",
    "hashtag_strategy": "Define a hashtag strategy for social media (branded hashtags, community hashtags, trending approach).",
    "dos": "List 5 content do's for this brand, one per line. These are things the brand should always do in content.",
    "donts": "List 5 content don'ts for this brand, one per line. These are things the brand should never do in content.",
}


@router.post("/generate-fields", response_model=AIGenerateFieldResponse)
@_limiter.limit("10/minute")
async def generate_brand_fields(
    request: Request,
    req: AIGenerateFieldRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Use AI to generate one or all empty brand fields based on brand context."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, req.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Fetch timezone setting for geographic context
    try:
        tz_result = await db.execute(
            text(
                "SELECT value FROM app_settings WHERE key = 'scheduler_timezone' LIMIT 1"
            )
        )
        raw_tz = tz_result.scalar()
        if raw_tz:
            import json as _json

            try:
                timezone_value = _json.loads(raw_tz)
            except Exception:
                timezone_value = raw_tz
        else:
            timezone_value = "Indian/Mauritius"
    except Exception:
        timezone_value = "Indian/Mauritius"

    # Build brand context for the LLM (sanitize all user-provided fields)
    guidelines = brand.brand_guidelines or {}
    ta_desc = (
        (brand.target_audience or {}).get("description", "Not set")
        if isinstance(brand.target_audience, dict)
        else "Not set"
    )
    brand_context = (
        f"Brand Name: {_sanitize(brand.name or '')}\n"
        f"Description: {_sanitize(brand.description or 'Not set')}\n"
        f"BC Company: {_sanitize(brand.bc_company or 'Not set')}\n"
        f"Tone of Voice: {_sanitize(brand.tone_of_voice or 'Not set')}\n"
        f"Target Audience: {_sanitize(ta_desc)}\n"
        f"Voice Style: {_sanitize(guidelines.get('voice_style', 'Not set'))}\n"
        f"Hashtag Strategy: {_sanitize(guidelines.get('hashtag_strategy', 'Not set'))}\n"
        f"Dos: {_sanitize(', '.join(guidelines.get('dos', [])) or 'Not set')}\n"
        f"Donts: {_sanitize(', '.join(guidelines.get('donts', [])) or 'Not set')}\n"
        f"Location/Timezone: {_sanitize(str(timezone_value))} (Mauritius, Indian Ocean region)\n"
    )

    if req.context:
        for key, val in req.context.items():
            brand_context += f"{_sanitize(str(key))}: {_sanitize(str(val))}\n"

    # Determine which fields to generate
    if req.field:
        fields_to_gen = [req.field] if req.field in FIELD_PROMPTS else []
    else:
        # Generate all empty fields
        fields_to_gen = []
        if not brand.description:
            fields_to_gen.append("description")
        if not brand.tone_of_voice:
            fields_to_gen.append("tone_of_voice")
        ta = brand.target_audience
        if not ta or (isinstance(ta, dict) and not ta.get("description")):
            fields_to_gen.append("target_audience")
        if not guidelines.get("voice_style"):
            fields_to_gen.append("voice_style")
        if not guidelines.get("hashtag_strategy"):
            fields_to_gen.append("hashtag_strategy")
        if not guidelines.get("dos"):
            fields_to_gen.append("dos")
        if not guidelines.get("donts"):
            fields_to_gen.append("donts")

    if not fields_to_gen:
        return AIGenerateFieldResponse(fields={})

    # Build LLM prompt
    fields_instructions = "\n".join(
        f"- {field}: {FIELD_PROMPTS[field]}" for field in fields_to_gen
    )

    system_prompt = (
        "You are a brand strategist AI. The brand operates in Mauritius and the Indian Ocean region. "
        "Consider the local market, bilingual audience (English/French/Creole), local culture, and regional context. "
        "Given the brand context below, generate the requested field values. "
        "Return ONLY a JSON object with the field names as keys and generated text as values. "
        "Do not include any markdown formatting, code blocks, or explanations. Just the raw JSON object."
    )

    user_prompt = (
        f"Brand Context:\n{brand_context}\n\n"
        f"Generate these fields:\n{fields_instructions}\n\n"
        "Return a JSON object with these exact field names as keys."
    )

    try:
        import json

        content = await _call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
        )
        try:
            generated = json.loads(content)
        except json.JSONDecodeError:
            # Try stripping markdown code fences
            cleaned = content.strip().strip("```json").strip("```").strip()
            generated = json.loads(cleaned)
        result = {k: str(v) for k, v in generated.items() if k in fields_to_gen}
        return AIGenerateFieldResponse(fields=result)

    except json.JSONDecodeError as jde:
        logger.error("AI field generation returned invalid JSON: %s", jde)
        raise HTTPException(status_code=502, detail="AI returned invalid JSON response")
    except Exception as exc:
        logger.error("AI field generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI generation failed")


class AIRewriteFieldRequest(BaseModel):
    brand_id: uuid.UUID
    field: str
    current_value: str


class AIRewriteFieldResponse(BaseModel):
    value: str


@router.post("/rewrite-field", response_model=AIRewriteFieldResponse)
@_limiter.limit("10/minute")
async def rewrite_brand_field(
    request: Request,
    req: AIRewriteFieldRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rewrite/rephrase an existing brand field value using AI."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, req.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    ta_desc = (
        (brand.target_audience or {}).get("description", "Not set")
        if isinstance(brand.target_audience, dict)
        else "Not set"
    )
    brand_context = (
        f"Brand Name: {_sanitize(brand.name or '')}\n"
        f"Description: {_sanitize(brand.description or 'Not set')}\n"
        f"Tone of Voice: {_sanitize(brand.tone_of_voice or 'Not set')}\n"
        f"Target Audience: {_sanitize(ta_desc)}\n"
        f"Location: Mauritius, Indian Ocean region\n"
    )

    field_label = _sanitize(req.field.replace("_", " ").title())

    system_prompt = (
        "You are a brand copywriter. The brand operates in Mauritius and the Indian Ocean region. "
        "Consider the local market, bilingual audience (English/French/Creole), and regional context. "
        "Rewrite the given text to be more compelling, clear, and professional "
        "while keeping the same meaning and intent. Match the brand's tone of voice. "
        "Return ONLY the rewritten text, nothing else — no quotes, no explanation."
    )

    user_prompt = (
        f"Brand Context:\n{brand_context}\n\n"
        f"Field: {field_label}\n"
        f"Current text to rewrite:\n{_sanitize(req.current_value)}\n\n"
        "Rewrite this to be better while keeping the same meaning."
    )

    try:
        content = await _call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = content.strip()
        if (content.startswith('"') and content.endswith('"')) or (
            content.startswith("'") and content.endswith("'")
        ):
            content = content[1:-1]
        return AIRewriteFieldResponse(value=content)

    except Exception as exc:
        logger.error("AI rewrite failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI rewrite failed")


# ── Per-channel caption rules (AI auto-fill) ─────────────────────────


class ChannelCaptionGenRequest(BaseModel):
    brand_id: uuid.UUID
    channel: str


# LinkedIn is the B2B channel; everything else is consumer-facing. Used to
# steer the generated rules toward the right audience per channel.
_B2B_CHANNELS = {"linkedin"}


@router.post("/generate-channel-caption")
@_limiter.limit("15/minute")
async def generate_channel_caption(
    request: Request,
    req: ChannelCaptionGenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AI-generate the caption rules for a single channel from brand context.

    Returns a ChannelCaptionSettings-shaped object the form merges into that
    channel's rules. B2C channels (Instagram, Facebook, etc.) speak as the
    product to the consumer; LinkedIn speaks as the B2B distributor.
    """
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    channel = (req.channel or "").strip().lower()
    if not channel:
        raise HTTPException(status_code=400, detail="channel is required")

    brand = await brand_service.get_brand(db, req.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = brand.brand_guidelines or {}
    ta_desc = (
        (brand.target_audience or {}).get("description", "Not set")
        if isinstance(brand.target_audience, dict)
        else "Not set"
    )
    brand_context = (
        f"Brand Name: {_sanitize(brand.name or '')}\n"
        f"Description: {_sanitize(brand.description or 'Not set')}\n"
        f"Tone of Voice: {_sanitize(brand.tone_of_voice or 'Not set')}\n"
        f"Voice Style: {_sanitize(guidelines.get('voice_style', 'Not set'))}\n"
        f"Target Audience: {_sanitize(ta_desc)}\n"
        f"Location: Mauritius, Indian Ocean region (bilingual EN/FR/Creole)\n"
    )

    is_b2b = channel in _B2B_CHANNELS
    audience_line = (
        "This is LinkedIn — a B2B channel. The brand speaks as the distributor/"
        "supply partner to hotels, restaurants and retailers. Professional, "
        "factual, no emojis."
        if is_b2b
        else "This is a consumer (B2C) channel. The brand speaks in first person "
        "AS the featured product to a home consumer — warm, sensory, benefit-led."
    )

    system_prompt = (
        "You configure per-channel social caption rules for a brand. "
        f"{audience_line}\n\n"
        "Return ONLY a JSON object with EXACTLY these keys:\n"
        '  "tone_override" (string: a few adjectives for this channel),\n'
        '  "hook_format" (string: how the opening line should look),\n'
        '  "structure_template" (string: the post shape — describe a flexible '
        "layout with blank lines between sections; lists optional, URL on its "
        "own line; never force a rigid template),\n"
        '  "caption_brief" (string: 1-2 sentences of extra guidance for this channel),\n'
        '  "emoji_override" (one of: "none", "minimal", "moderate", "heavy"),\n'
        '  "max_words" (integer),\n'
        '  "hashtags_min" (integer), "hashtags_max" (integer),\n'
        '  "must_name_product" (boolean).\n\n'
        "Never put hashtags inside the caption body. No markdown, no code "
        "fences — just the raw JSON object."
    )
    user_prompt = (
        f"Channel: {_sanitize(channel)}\n\n"
        f"Brand context:\n{brand_context}\n\n"
        "Generate sensible caption rules for THIS channel, consistent with the "
        "brand voice and tuned to how this platform is actually used."
    )

    try:
        import json

        raw = await _call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            cleaned = raw.strip().strip("```json").strip("```").strip()
            data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned invalid JSON response")
    except Exception as exc:
        logger.error("Channel caption generation failed: %s", exc)
        raise HTTPException(status_code=502, detail="AI generation failed")

    # Coerce into the ChannelCaptionSettings shape the frontend expects.
    def _as_int(v: object) -> int | None:
        try:
            return int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    result: dict = {}
    if isinstance(data.get("tone_override"), str) and data["tone_override"].strip():
        result["tone_override"] = data["tone_override"].strip()
    if isinstance(data.get("hook_format"), str) and data["hook_format"].strip():
        result["hook_format"] = data["hook_format"].strip()
    if isinstance(data.get("structure_template"), str) and data["structure_template"].strip():
        result["structure_template"] = data["structure_template"].strip()
    if isinstance(data.get("caption_brief"), str) and data["caption_brief"].strip():
        result["caption_brief"] = data["caption_brief"].strip()
    emoji = str(data.get("emoji_override", "")).strip().lower()
    if emoji in {"none", "minimal", "moderate", "heavy"}:
        result["emoji_override"] = emoji
    mw = _as_int(data.get("max_words"))
    if mw and mw > 0:
        result["max_words"] = mw
    hmin = _as_int(data.get("hashtags_min"))
    hmax = _as_int(data.get("hashtags_max"))
    if hmin is not None and hmax is not None:
        result["hashtags_count"] = [max(0, hmin), max(0, hmax)]
    if isinstance(data.get("must_name_product"), bool):
        result["must_name_product"] = data["must_name_product"]

    return {"channel": channel, "caption": result}
