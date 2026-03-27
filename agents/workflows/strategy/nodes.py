"""Strategy workflow nodes — all use real LLM calls and database operations."""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.types import interrupt

from shared.llm import chat_completion
from shared.sanitize import sanitize_json_for_prompt
from shared.tools.database import get_latest_research, store_strategy

from workflows.strategy.state import StrategyState

logger = logging.getLogger(__name__)


async def load_research(state: StrategyState) -> dict[str, Any]:
    """Load the latest research results for this brand from the database."""
    research = await get_latest_research(state["brand_id"])
    if not research:
        return {"errors": [*(state.get("errors") or []), "No research data found"], "status": "failed"}
    return {"research_data": research.get("output_payload", research)}


async def generate_positioning(state: StrategyState) -> dict[str, Any]:
    """Generate brand positioning via LLM based on research data."""
    research = state.get("research_data", {})
    prompt = [
        {"role": "system", "content": "You are a brand strategist. The brand operates in Mauritius. Consider the local market, Indian Ocean region, bilingual (English/French) content needs, local holidays and events, and regional consumer preferences. Based on the research data, define a clear brand positioning. Return JSON with: value_proposition, differentiators, brand_voice, tone_attributes, key_messages."},
        {"role": "user", "content": f"Research data:\n{sanitize_json_for_prompt(research, max_length=8000)}"},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    try:
        positioning = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        positioning = {"raw": result}
    return {"positioning": positioning}


async def define_pillars(state: StrategyState) -> dict[str, Any]:
    """Define content pillars based on positioning and research."""
    prompt = [
        {"role": "system", "content": "You are a content strategist. The brand operates in Mauritius. Consider the local market, Indian Ocean region, bilingual (English/French) content needs, local holidays and events, and regional consumer preferences. Define 4-6 content pillars for this brand. Each pillar should have: name, description, content_types, percentage_of_content, example_topics. Return a JSON array."},
        {"role": "user", "content": (
            f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}))}\n\n"
            f"Research:\n{sanitize_json_for_prompt(state.get('research_data', {}), max_length=5000)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    try:
        pillars = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        pillars = [{"name": "General", "description": result}]
    return {"pillars": pillars}


async def define_audiences(state: StrategyState) -> dict[str, Any]:
    """Define target audiences with platform-specific strategies."""
    prompt = [
        {"role": "system", "content": "You are a marketing strategist. The brand operates in Mauritius. Consider the local market, Indian Ocean region, bilingual (English/French) content needs, local holidays and events, and regional consumer preferences. Define 3-5 target audience segments. Each should have: segment_name, description, demographics, platforms, content_preferences, engagement_strategy, best_times. Return a JSON array."},
        {"role": "user", "content": (
            f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}))}\n\n"
            f"Pillars:\n{sanitize_json_for_prompt(state.get('pillars', []))}\n\n"
            f"Research:\n{sanitize_json_for_prompt(state.get('research_data', {}), max_length=4000)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    try:
        audiences = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        audiences = [{"segment_name": "Primary", "description": result}]
    return {"audiences": audiences}


async def plan_cadence(state: StrategyState) -> dict[str, Any]:
    """Plan posting cadence per platform."""
    prompt = [
        {"role": "system", "content": "You are a social media strategist. The brand operates in Mauritius. Consider the local market, Indian Ocean region, bilingual (English/French) content needs, local holidays and events, and regional consumer preferences. Create a posting cadence plan. Return JSON with platforms as keys, each having: posts_per_week, best_days, best_times, content_mix (mapping pillar to percentage)."},
        {"role": "user", "content": (
            f"Audiences:\n{sanitize_json_for_prompt(state.get('audiences', []))}\n\n"
            f"Pillars:\n{sanitize_json_for_prompt(state.get('pillars', []))}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.4)
    try:
        cadence = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        cadence = {"raw": result}
    return {"cadence": cadence}


async def generate_themes(state: StrategyState) -> dict[str, Any]:
    """Generate monthly content themes for the next quarter."""
    prompt = [
        {"role": "system", "content": "You are a content strategist. The brand operates in Mauritius. Consider the local market, Indian Ocean region, bilingual (English/French) content needs, local holidays and events (e.g. Mauritian Independence Day, Diwali, Eid, Chinese Spring Festival, Thaipoosam Cavadee, Christmas), and regional consumer preferences. Generate monthly themes for the next 3 months. Each month should have: month, theme_name, description, sub_themes, key_campaigns, pillar_focus. Return a JSON array."},
        {"role": "user", "content": (
            f"Positioning:\n{sanitize_json_for_prompt(state.get('positioning', {}))}\n\n"
            f"Pillars:\n{sanitize_json_for_prompt(state.get('pillars', []))}\n\n"
            f"Cadence:\n{sanitize_json_for_prompt(state.get('cadence', {}))}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.6)
    try:
        themes = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        themes = [{"month": "current", "theme_name": "General", "description": result}]
    return {"themes": themes}


async def human_review(state: StrategyState) -> dict[str, Any]:
    """Pause execution for human review of the complete strategy.

    Uses LangGraph interrupt() to halt the graph until a human approves or
    provides feedback.

    When auto_approve=True or trigger="event" (automated pipeline), skip
    the interrupt and auto-approve the strategy to allow unattended e2e runs.
    """
    strategy_summary = {
        "positioning": state.get("positioning"),
        "pillars": state.get("pillars"),
        "audiences": state.get("audiences"),
        "cadence": state.get("cadence"),
        "themes": state.get("themes"),
    }

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
        logger.info("Auto-approving strategy for brand %s (trigger=%s)", state["brand_id"], state.get("trigger"))
        await store_strategy(state["brand_id"], strategy_summary)
        return {"human_approved": True, "status": "approved"}

    review = interrupt({
        "type": "strategy_review",
        "brand_id": state["brand_id"],
        "strategy": strategy_summary,
        "message": "Please review and approve the generated strategy, or provide feedback for revision.",
    })

    approved = review.get("approved", False)
    feedback = review.get("feedback", "")

    if approved:
        # Store the approved strategy
        await store_strategy(state["brand_id"], strategy_summary)
        return {"human_approved": True, "status": "approved"}
    else:
        return {"human_approved": False, "human_feedback": feedback, "status": "needs_revision"}
