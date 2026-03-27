"""Evaluation workflow nodes — real performance data and LLM analysis."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, parse_llm_json
from shared.sanitize import sanitize_json_for_prompt
from shared.tools.database import get_performance_data, store_adaptations

from workflows.evaluation.state import EvaluationState

logger = logging.getLogger(__name__)


async def load_performance(state: EvaluationState) -> dict[str, Any]:
    """Load engagement metrics from the database."""
    data = await get_performance_data(state["brand_id"], days=30)
    if not data:
        return {"errors": [*(state.get("errors") or []), "No performance data found"], "status": "failed"}
    logger.info("Loaded %d performance records for brand %s", len(data), state["brand_id"])
    return {"performance_data": data}


async def analyze_patterns(state: EvaluationState) -> dict[str, Any]:
    """Analyse performance patterns using LLM."""
    perf_data = state.get("performance_data", [])

    prompt = [
        {"role": "system", "content": (
            "You are a social media analytics expert. Analyze the performance data and identify patterns. "
            "Look for: best performing content types, optimal posting times, engagement trends, "
            "audience response patterns, content themes that resonate. "
            "Return JSON with: top_performers (array), worst_performers (array), "
            "engagement_trends, time_patterns, content_type_performance, theme_performance."
        )},
        {"role": "user", "content": f"Performance data (last 30 days):\n{sanitize_json_for_prompt(perf_data)}"},
    ]
    result = await chat_completion(prompt, temperature=0.3)
    patterns = parse_llm_json(result, fallback={"raw_analysis": result})

    return {"patterns": patterns}


async def generate_recommendations(state: EvaluationState) -> dict[str, Any]:
    """Generate actionable recommendations with confidence scores."""
    patterns = state.get("patterns", {})

    prompt = [
        {"role": "system", "content": (
            "You are a marketing optimization expert. Based on the performance patterns, "
            "generate specific, actionable recommendations. Each recommendation should have: "
            "title, description, expected_impact (high/medium/low), confidence (0.0-1.0), "
            "category (timing/content/audience/format), specific_action. "
            "Return a JSON array sorted by confidence descending."
        )},
        {"role": "user", "content": f"Performance patterns:\n{sanitize_json_for_prompt(patterns, max_length=8000)}"},
    ]
    result = await chat_completion(prompt, temperature=0.4)
    recommendations = parse_llm_json(result, fallback=[{"title": "Analysis complete", "description": result, "confidence": 0.5}])

    return {"recommendations": recommendations}


async def classify_adaptations(state: EvaluationState) -> dict[str, Any]:
    """Classify recommendations into adaptation tiers.

    - tier1: Safe to auto-apply (timing adjustments, hashtag changes)
    - tier2: Needs human review (content tone changes, audience targeting)
    - tier3: Major strategic changes (pillar restructuring, platform changes)
    """
    recommendations = state.get("recommendations", [])

    prompt = [
        {"role": "system", "content": (
            "You are a marketing operations manager. Classify each recommendation into a tier:\n"
            "- tier1: Safe to auto-apply. Examples: posting time changes, hashtag optimization, minor caption tweaks.\n"
            "- tier2: Needs human review. Examples: content tone shifts, new audience targeting, format changes.\n"
            "- tier3: Major strategic change. Examples: pillar restructuring, platform strategy changes, brand voice shifts.\n"
            "Return a JSON array where each object has the original recommendation fields plus a 'tier' field (1, 2, or 3)."
        )},
        {"role": "user", "content": f"Recommendations:\n{sanitize_json_for_prompt(recommendations, max_length=8000)}"},
    ]
    result = await chat_completion(prompt, temperature=0.2)
    classified = parse_llm_json(result, fallback=[{**r, "tier": 2} for r in recommendations])

    return {"adaptations": classified}


async def store_adaptations_node(state: EvaluationState) -> dict[str, Any]:
    """Persist classified adaptations to the database."""
    brand_id = state["brand_id"]
    adaptations = state.get("adaptations", [])

    db_records = []
    for a in adaptations:
        db_records.append({
            "brand_id": brand_id,
            "tier": a.get("tier", 2),
            "description": a.get("description", a.get("title", "")),
            "confidence": a.get("confidence", 0.5),
            "data": json.dumps(a),
            "status": "auto_applied" if a.get("tier") == 1 else "pending",
        })

    ids = await store_adaptations(db_records)
    logger.info("Stored %d adaptations for brand %s", len(ids), brand_id)

    return {"status": "completed"}
