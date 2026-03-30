import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.config import settings
from app.deps import get_current_user, get_db
from app.models.adaptation import Adaptation
from app.models.agent_run import AgentRun
from app.models.competitor import Competitor
from app.services import brand_service, nats_service
from sqlalchemy import func

logger = logging.getLogger(__name__)


async def _call_llm(messages: list[dict], temperature: float = 0.7, json_mode: bool = False) -> str:
    """Call LLM via LiteLLM proxy, falling back to OpenAI directly if LiteLLM fails."""
    body: dict = {
        "model": "gpt-5.4-mini",
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
                body_litellm = {**body, "model": "openai/gpt-5.4-mini"}
                resp = await client.post(
                    settings.LITELLM_BASE_URL.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json=body_litellm,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as litellm_exc:
                logger.warning("LiteLLM call failed, falling back to direct OpenAI: %s", litellm_exc)

        # Direct OpenAI fallback
        if not settings.OPENAI_API_KEY:
            raise ValueError("No LLM available: LiteLLM failed and OPENAI_API_KEY not set")

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List recent agent run reports (research, strategy, planning, content_calendar_strategy, product_intel).

    Pass ?type=research to filter by a single agent_type.
    """
    allowed_types = ["research", "strategy", "planning", "content_calendar_strategy", "product_intel"]

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
    result = await db.execute(stmt)
    runs = result.scalars().all()

    # Map agent_runs to the report format the frontend expects
    reports = []
    for r in runs:
        output = r.output_payload or {}
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
                summary_parts.append(f"{len(output['competitor_analysis'])} competitor(s) analyzed")
        elif r.agent_type == "strategy":
            if output.get("content_pillars"):
                summary_parts.append(f"{len(output['content_pillars'])} content pillar(s)")
            if output.get("target_audiences"):
                summary_parts.append(f"{len(output['target_audiences'])} target audience(s)")
            if output.get("positioning"):
                summary_parts.append("Positioning defined")
            if output.get("posting_cadence"):
                summary_parts.append("Posting cadence set")
        elif r.agent_type == "planning":
            if output.get("campaigns"):
                summary_parts.append(f"{len(output['campaigns'])} campaign(s)")
            if output.get("calendar_summary") or output.get("calendar"):
                summary_parts.append("Calendar summary available")
        elif r.agent_type == "content_calendar_strategy":
            # Markdown document — just note its presence
            if output.get("strategy_document") or output.get("markdown"):
                summary_parts.append("Year-long strategy document")
            if output.get("monthly_themes"):
                summary_parts.append(f"{len(output['monthly_themes'])} monthly theme(s)")

        if not summary_parts:
            # Fallback: generic summary from gaps (legacy)
            gaps = output.get("gaps", [])
            personas = output.get("personas", [])
            if gaps:
                summary_parts.append(f"{len(gaps)} gap(s) identified")
            if personas:
                summary_parts.append(f"{len(personas)} persona(s) built")
            if output.get("competitor_analysis"):
                summary_parts.append(f"{len(output['competitor_analysis'])} competitor(s) analyzed")

        summary = ". ".join(summary_parts) if summary_parts else f"Status: {r.status}"

        # Extract insights from gaps
        gaps = output.get("gaps", [])
        insights = [g.get("description", "") for g in gaps[:5]] if gaps else []

        reports.append({
            "id": str(r.id),
            "brand_id": str(r.brand_id) if r.brand_id else None,
            "report_type": r.agent_type,
            "status": r.status,
            "title": title,
            "summary": summary,
            "insights": insights,
            "output_payload": output,
            "created_at": r.created_at.isoformat(),
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })
    return reports


@router.get("/report/{run_id}")
async def get_report(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single agent run report by ID, including brand info."""
    from app.models.brand import Brand

    result = await db.execute(
        select(AgentRun).where(AgentRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Report not found")

    brand_name = None
    brand_description = None
    brand_website = None
    brand_industry = None
    if run.brand_id:
        brand_result = await db.execute(
            select(Brand).where(Brand.id == run.brand_id)
        )
        brand = brand_result.scalar_one_or_none()
        if brand:
            brand_name = brand.name
            brand_description = brand.description
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


@router.get("/trends")
async def get_trending_topics(
    brand_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get trending topics from the latest strategy output."""
    stmt = (
        select(AgentRun)
        .where(
            AgentRun.agent_type == "strategy",
            AgentRun.status == "completed",
        )
        .order_by(AgentRun.completed_at.desc())
        .limit(1)
    )

    if brand_id:
        stmt = stmt.where(AgentRun.brand_id == brand_id)

    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if not run or not run.output_payload:
        return []

    # Extract themes from strategy output
    payload = run.output_payload if isinstance(run.output_payload, dict) else {}
    themes = payload.get("themes", [])

    trends = []
    for i, theme in enumerate(themes):
        if isinstance(theme, dict):
            trends.append({
                "topic": theme.get("name", theme.get("theme", f"Theme {i+1}")),
                "platform": theme.get("platform", "all"),
                "relevance_score": theme.get("relevance", theme.get("score", 0.8)),
                "description": theme.get("description", ""),
                "discovered_at": run.completed_at.isoformat() if run.completed_at else None,
            })
        elif isinstance(theme, str):
            trends.append({
                "topic": theme,
                "platform": "all",
                "relevance_score": 0.8,
                "description": "",
                "discovered_at": run.completed_at.isoformat() if run.completed_at else None,
            })

    return trends


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
async def generate_brand_fields(
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
            text("SELECT value FROM app_settings WHERE key = 'scheduler_timezone' LIMIT 1")
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

    # Build brand context for the LLM
    guidelines = brand.brand_guidelines or {}
    brand_context = (
        f"Brand Name: {brand.name}\n"
        f"Description: {brand.description or 'Not set'}\n"
        f"BC Company: {brand.bc_company or 'Not set'}\n"
        f"Tone of Voice: {brand.tone_of_voice or 'Not set'}\n"
        f"Target Audience: {(brand.target_audience or {}).get('description', 'Not set') if isinstance(brand.target_audience, dict) else 'Not set'}\n"
        f"Voice Style: {guidelines.get('voice_style', 'Not set')}\n"
        f"Hashtag Strategy: {guidelines.get('hashtag_strategy', 'Not set')}\n"
        f"Dos: {', '.join(guidelines.get('dos', [])) or 'Not set'}\n"
        f"Donts: {', '.join(guidelines.get('donts', [])) or 'Not set'}\n"
        f"Location/Timezone: {timezone_value} (Mauritius, Indian Ocean region)\n"
    )

    if req.context:
        for key, val in req.context.items():
            brand_context += f"{key}: {val}\n"

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
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(exc)}")


class AIRewriteFieldRequest(BaseModel):
    brand_id: uuid.UUID
    field: str
    current_value: str


class AIRewriteFieldResponse(BaseModel):
    value: str


@router.post("/rewrite-field", response_model=AIRewriteFieldResponse)
async def rewrite_brand_field(
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

    guidelines = brand.brand_guidelines or {}
    brand_context = (
        f"Brand Name: {brand.name}\n"
        f"Description: {brand.description or 'Not set'}\n"
        f"Tone of Voice: {brand.tone_of_voice or 'Not set'}\n"
        f"Target Audience: {(brand.target_audience or {}).get('description', 'Not set') if isinstance(brand.target_audience, dict) else 'Not set'}\n"
        f"Location: Mauritius, Indian Ocean region\n"
    )

    field_label = req.field.replace("_", " ").title()

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
        f"Current text to rewrite:\n{req.current_value}\n\n"
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
        if (content.startswith('"') and content.endswith('"')) or (content.startswith("'") and content.endswith("'")):
            content = content[1:-1]
        return AIRewriteFieldResponse(value=content)

    except Exception as exc:
        logger.error("AI rewrite failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI rewrite failed: {str(exc)}")
