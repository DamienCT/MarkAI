"""Strategy workflow nodes — all use real LLM calls and database operations."""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.types import interrupt

from shared.brand_context import build_brand_context_block, get_enabled_channels
from shared.llm import (
    chat_completion,
    generate_executive_summary_plain,
    parse_llm_json,
)
from shared.sanitize import sanitize_json_for_prompt
from shared.tools.database import (
    get_brand_config,
    get_events_for_research,
    get_latest_research,
    store_strategy,
)

from workflows.strategy.state import StrategyState

logger = logging.getLogger(__name__)


def _brand_ctx(state: StrategyState) -> str:
    """Render the shared brand grounding block from the loaded brand config."""
    return build_brand_context_block(state.get("brand_config"))


def _format_events_for_prompt(events: list[dict[str, Any]]) -> str:
    """Render the events list as a compact markdown bullet list for LLM prompts.

    Mirrors workflows/planning/nodes.py so strategy and planning documents
    show identical renderings for non-empty lists; the empty-case instruction
    is agent-specific (key_dates is a schema field here vs prose in planning).
    """
    if not events:
        return (
            "(no significant events registered — every month's key_dates must "
            "be an empty array)"
        )
    lines = []
    for ev in events:
        start = ev.get("start", "")
        end = ev.get("end")
        title = ev.get("title", "")
        category = ev.get("category") or "event"
        scope = ev.get("scope", "global")
        date_str = f"{start} → {end}" if end else start
        lines.append(f"- {date_str}: {title} ({category}, {scope})")
    return "\n".join(lines)


async def load_research(state: StrategyState) -> dict[str, Any]:
    """Load the latest research results and brand config for this brand."""
    brand_config = await get_brand_config(state["brand_id"]) or {}
    research = await get_latest_research(state["brand_id"])
    if not research:
        return {
            "brand_config": brand_config,
            "errors": [*(state.get("errors") or []), "No research data found"],
            "status": "failed",
        }
    research_data = research.get("output_payload", research)
    # output_payload may come back as a JSON string from the database
    if isinstance(research_data, str):
        try:
            research_data = json.loads(research_data)
        except (json.JSONDecodeError, TypeError):
            research_data = {"raw": research_data}
    return {"research_data": research_data, "brand_config": brand_config}


async def generate_positioning(state: StrategyState) -> dict[str, Any]:
    """Generate brand positioning via LLM based on research data."""
    try:
        research = state.get("research_data", {})
        prompt = [
            {
                "role": "system",
                "content": "You are a brand strategist. Based on the brand's target market and the research data, define a clear brand positioning. Return JSON with: value_proposition, differentiators, brand_voice, tone_attributes, key_messages, brand_archetype (the brand's Jungian archetype, e.g. Caregiver, Sage, Creator), emotional_territory (the emotional space the brand owns), competitive_differentiation (array of objects comparing this brand vs top 3 competitors across 5 dimensions, each object having: dimension, brand_score (1-5), competitor_scores (object with competitor name as key and score 1-5 as value)).",
            },
            {
                "role": "user",
                "content": (
                    f"{_brand_ctx(state)}\n\n"
                    f"Research data:\n{sanitize_json_for_prompt(research, max_length=8000)}"
                ),
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.5, response_format={"type": "json_object"}
        )
        positioning = parse_llm_json(result, fallback={"raw": result})
        return {"positioning": positioning}
    except Exception as exc:
        logger.error("generate_positioning failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_positioning failed: {exc}",
            ],
        }


async def define_pillars(state: StrategyState) -> dict[str, Any]:
    """Define content pillars based on positioning and research."""
    try:
        prompt = [
            {
                "role": "system",
                "content": "You are a content strategist. Based on the brand's target market, define 4-6 content pillars for this brand. Each pillar should have: name, description, content_types, percentage_of_content, example_topics, audience_alignment (array of persona names this pillar primarily serves), seasonal_emphasis (which months/quarters this pillar gets more weight), platform_fit (which platforms are best for this pillar's content), visual_style (visual direction for this pillar — colors, mood, photography style), pillar_rationale (why this pillar matters for this brand's strategic goals). Every pillar must comply with the brand NEVER-guardrails in the brand block, and platform_fit may only reference the enabled platforms listed there. Return a JSON array.",
            },
            {
                "role": "user",
                "content": (
                    f"{_brand_ctx(state)}\n\n"
                    f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}))}\n\n"
                    f"Research:\n{sanitize_json_for_prompt(state.get('research_data', {}), max_length=5000)}"
                ),
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.5, response_format={"type": "json_object"}
        )
        pillars = parse_llm_json(
            result, fallback=[{"name": "General", "description": result}]
        )
        if isinstance(pillars, dict):
            pillars = next((v for v in pillars.values() if isinstance(v, list)), [])
        return {"pillars": pillars}
    except Exception as exc:
        logger.error("define_pillars failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"define_pillars failed: {exc}"],
        }


async def define_audiences(state: StrategyState) -> dict[str, Any]:
    """Define target audiences with platform-specific strategies."""
    try:
        # Cross-reference research personas if available
        research_data = state.get("research_data", {})
        if not isinstance(research_data, dict):
            research_data = {}
        personas_context = sanitize_json_for_prompt(
            research_data.get("personas", []), max_length=6000
        )

        prompt = [
            {
                "role": "system",
                "content": "You are a marketing strategist. Based on the brand's target market, define 3-5 target audience segments. IMPORTANT: Cross-reference the research personas below. Each segment must include a 'persona_ref' field naming which research persona it aligns with. Do NOT invent new audiences that contradict the research personas. Each should have: segment_name, persona_ref, description, demographics, platforms, content_preferences, engagement_strategy, best_times. Return a JSON object with a single key \"audiences\" whose value is an array of the segment objects.",
            },
            {
                "role": "user",
                "content": (
                    f"{_brand_ctx(state)}\n\n"
                    f"Research Personas (source of truth):\n{personas_context}\n\n"
                    f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}))}\n\n"
                    f"Pillars:\n{sanitize_json_for_prompt(state.get('pillars', []))}\n\n"
                    f"Research:\n{sanitize_json_for_prompt(research_data, max_length=4000)}"
                ),
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.5, response_format={"type": "json_object"}
        )
        audiences = parse_llm_json(
            result, fallback=[{"segment_name": "Primary", "description": result}]
        )
        if isinstance(audiences, dict):
            # json_object mode can't return a top-level array, so the model wraps
            # it. Prefer a list-valued key (e.g. {"audiences": [...]}); if it
            # instead returned one object per segment ({"segment_1": {...}, ...}),
            # collect the dict values so we don't silently drop everything.
            audiences = (
                next((v for v in audiences.values() if isinstance(v, list)), None)
                or [v for v in audiences.values() if isinstance(v, dict)]
            )
        return {"audiences": audiences}
    except Exception as exc:
        logger.error("define_audiences failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"define_audiences failed: {exc}"],
        }


async def plan_cadence(state: StrategyState) -> dict[str, Any]:
    """Plan posting cadence per platform."""
    try:
        # Enabled channels come from the shared brand-context helper so every
        # workflow computes them identically.
        brand_config = state.get("brand_config")
        if brand_config is None:
            brand_config = await get_brand_config(state["brand_id"]) or {}
        enabled_channels = get_enabled_channels(brand_config)
        channels_str = ", ".join(enabled_channels)

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a social media strategist. Create a posting cadence plan "
                    f"for EXACTLY these platforms: {channels_str}.\n\n"
                    "Return a JSON object with each platform as a key. Each platform MUST have:\n"
                    "- posts_per_week (integer, e.g., 5)\n"
                    "- best_days (array of day names, e.g., [\"Monday\", \"Wednesday\", \"Friday\"])\n"
                    "- best_times (array of times in HH:MM format, e.g., [\"07:00\", \"13:00\", \"20:00\"])\n"
                    "- content_mix (object mapping pillar name to percentage)\n"
                    "- content_format_mix (object mapping format to percentage, e.g., {\"reel\": 30, \"carousel\": 25})\n\n"
                    "Consider the brand's target market in Mauritius. Instagram and Facebook "
                    "typically need 4-5 posts/week, LinkedIn 2-3, YouTube 1-2."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{build_brand_context_block(brand_config)}\n\n"
                    f"Enabled channels: {channels_str}\n\n"
                    f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}), max_length=1000)}\n\n"
                    f"Audiences:\n{sanitize_json_for_prompt(state.get('audiences', []))}\n\n"
                    f"Pillars:\n{sanitize_json_for_prompt(state.get('pillars', []))}"
                ),
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.4, response_format={"type": "json_object"}
        )
        cadence = parse_llm_json(result, fallback={})
        # Validate: ensure every enabled channel has a cadence entry
        for ch in enabled_channels:
            if ch not in cadence:
                cadence[ch] = {"posts_per_week": 3, "best_days": ["Monday", "Wednesday", "Friday"], "best_times": ["07:00", "13:00", "20:00"]}
        logger.info("plan_cadence result: %s", {ch: cadence[ch].get("posts_per_week") for ch in enabled_channels if ch in cadence})
        return {"cadence": cadence}
    except Exception as exc:
        logger.error("plan_cadence failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"plan_cadence failed: {exc}"],
        }


async def generate_themes(state: StrategyState) -> dict[str, Any]:
    """Generate monthly content themes for the next 12 months."""
    try:
        # Ground key_dates in the real events calendar — never LLM memory.
        try:
            events = await get_events_for_research(state["brand_id"], months_ahead=12)
        except Exception as exc:
            logger.warning(
                "Failed to load events for brand %s: %s", state["brand_id"], exc
            )
            events = []
        events_block = _format_events_for_prompt(events)

        prompt = [
            {
                "role": "system",
                "content": "You are a content strategist. Based on the brand's target market, generate monthly themes for ALL 12 months starting from the current date. Each month should have: month (month name and year), theme_name (overarching theme), description, sub_themes (array of 4 weekly sub-themes, each with: week as 'W1'/'W2'/'W3'/'W4', focus as sub-theme name, pillar as which content pillar this week emphasizes, primary_audience as which persona to prioritize this week), key_dates (array of notable dates in this month taken ONLY from the significant-events list in the user message — copy the exact date strings from that list; if the list has no events in a month, key_dates MUST be an empty array; NEVER add holidays, festivals, or awareness days from memory. Each key_date has: date as the exact date string from the events list, event as the event title from the list, content_angle as specific angle for this date, format as recommended content format, audience as target persona), pillar_rotation (how pillars rotate across the 4 weeks), key_campaigns, pillar_focus. Themes, sub-themes and campaigns must comply with the brand NEVER-guardrails in the brand block and reference only the enabled platforms listed there. Return a JSON object with a single key \"themes\" whose value is the array of 12 month objects.",
            },
            {
                "role": "user",
                "content": (
                    f"{_brand_ctx(state)}\n\n"
                    f"Significant events (next 12 months — the ONLY dates allowed in key_dates):\n{events_block}\n\n"
                    f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}))}\n\n"
                    f"Pillars:\n{sanitize_json_for_prompt(state.get('pillars', []))}\n\n"
                    f"Audiences:\n{sanitize_json_for_prompt(state.get('audiences', []))}\n\n"
                    f"Cadence:\n{sanitize_json_for_prompt(state.get('cadence', {}))}"
                ),
            },
        ]
        result = await chat_completion(
            prompt,
            temperature=0.65,
            max_tokens=16384,
            response_format={"type": "json_object"},
        )
        themes = parse_llm_json(
            result,
            fallback=[
                {
                    "month": "current",
                    "theme_name": "General",
                    "description": result,
                    "sub_themes": [],
                    "key_dates": [],
                    "pillar_rotation": "",
                }
            ],
        )
        if isinstance(themes, dict):
            # json_object mode can't return a top-level array, so the model
            # wraps it ({"themes": [...]}); if it instead returned one object
            # per month, collect the dict values so nothing is dropped.
            themes = (
                next((v for v in themes.values() if isinstance(v, list)), None)
                or [v for v in themes.values() if isinstance(v, dict)]
            )
        if not themes:
            logger.warning(
                "generate_themes produced no themes for brand %s", state["brand_id"]
            )
        return {"themes": themes}
    except Exception as exc:
        logger.error("generate_themes failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"generate_themes failed: {exc}"],
        }


async def human_review(state: StrategyState) -> dict[str, Any]:
    """Pause execution for human review of the complete strategy.

    Uses LangGraph interrupt() to halt the graph until a human approves or
    provides feedback.

    When auto_approve=True or trigger="event" (automated pipeline), skip
    the interrupt and auto-approve the strategy to allow unattended e2e runs.
    """
    strategy_summary = {
        "positioning": state.get("positioning"),
        "content_pillars": state.get("pillars"),
        "target_audiences": state.get("audiences"),
        "posting_cadence": state.get("cadence"),
        "monthly_themes": state.get("themes"),
    }

    # Plain-English summary for non-marketing readers (IT/finance). Stored
    # inside the strategy payload so it persists via store_strategy.
    summary_plain = await generate_executive_summary_plain("strategy", strategy_summary)
    strategy_summary["executive_summary_plain"] = summary_plain

    # Auto-approve for automated pipeline triggers (no human in the loop)
    # Can also be controlled per-brand via brand_guidelines.pipeline_auto_approve
    auto_approve = state.get("auto_approve") or state.get("trigger") == "event"
    if not auto_approve:
        # Check brand-level setting
        from shared.tools.database import get_brand

        brand_data = await get_brand(state["brand_id"])
        if brand_data:
            guidelines = brand_data.get("brand_guidelines") or {}
            auto_approve = guidelines.get("pipeline_auto_approve", False)

    if auto_approve:
        logger.info(
            "Auto-approving strategy for brand %s (trigger=%s)",
            state["brand_id"],
            state.get("trigger"),
        )
        await store_strategy(state["brand_id"], strategy_summary)
        return {
            "human_approved": True,
            "status": "approved",
            "executive_summary_plain": summary_plain,
        }

    review = interrupt(
        {
            "type": "strategy_review",
            "brand_id": state["brand_id"],
            "strategy": strategy_summary,
            "message": "Please review and approve the generated strategy, or provide feedback for revision.",
        }
    )

    approved = review.get("approved", False)
    feedback = review.get("feedback", "")

    if approved:
        # Store the approved strategy
        await store_strategy(state["brand_id"], strategy_summary)
        return {
            "human_approved": True,
            "status": "approved",
            "executive_summary_plain": summary_plain,
        }
    else:
        return {
            "human_approved": False,
            "human_feedback": feedback,
            "status": "needs_revision",
        }
