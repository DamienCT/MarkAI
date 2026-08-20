"""Evaluation workflow nodes — real performance data and LLM analysis."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, parse_llm_json
from shared.sanitize import sanitize_json_for_prompt
from shared.tools.database import (
    get_performance_data,
    resolve_current_content_id,
    store_adaptations,
)

from workflows.evaluation.state import EvaluationState

logger = logging.getLogger(__name__)


async def load_performance(state: EvaluationState) -> dict[str, Any]:
    """Load engagement metrics from the database."""
    data = await get_performance_data(state["brand_id"], days=30)
    if not data:
        return {
            "errors": [*(state.get("errors") or []), "No performance data found"],
            "status": "failed",
        }
    logger.info(
        "Loaded %d performance records for brand %s", len(data), state["brand_id"]
    )
    return {"performance_data": data}


async def analyze_patterns(state: EvaluationState) -> dict[str, Any]:
    """Analyse performance patterns using LLM."""
    try:
        perf_data = state.get("performance_data", [])

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a social media analytics expert. Analyze the performance data and identify patterns. "
                    "Look for: best performing content types, optimal posting times, engagement trends, "
                    "audience response patterns, content themes that resonate. "
                    "Return JSON with: top_performers (array), worst_performers (array), "
                    "engagement_trends, time_patterns, content_type_performance, theme_performance."
                ),
            },
            {
                "role": "user",
                "content": f"Performance data (last 30 days):\n{sanitize_json_for_prompt(perf_data)}",
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.3, response_format={"type": "json_object"}
        )
        patterns = parse_llm_json(result, fallback={"raw_analysis": result})

        return {"patterns": patterns}
    except Exception as exc:
        logger.error("analyze_patterns failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"analyze_patterns failed: {exc}"],
        }


async def generate_recommendations(state: EvaluationState) -> dict[str, Any]:
    """Generate actionable recommendations with confidence scores."""
    try:
        patterns = state.get("patterns", {})

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a marketing optimization expert. Based on the performance patterns, "
                    "generate specific, actionable recommendations. Each recommendation should have: "
                    "title, description, expected_impact (high/medium/low), confidence (0.0-1.0), "
                    "category (timing/content/audience/format), specific_action. "
                    "Return a JSON array sorted by confidence descending."
                ),
            },
            {
                "role": "user",
                "content": f"Performance patterns:\n{sanitize_json_for_prompt(patterns, max_length=8000)}",
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.4, response_format={"type": "json_object"}
        )
        recommendations = parse_llm_json(
            result,
            fallback=[
                {"title": "Analysis complete", "description": result, "confidence": 0.5}
            ],
        )
        if isinstance(recommendations, dict):
            recommendations = next(
                (v for v in recommendations.values() if isinstance(v, list)), []
            )

        return {"recommendations": recommendations}
    except Exception as exc:
        logger.error("generate_recommendations failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_recommendations failed: {exc}",
            ],
        }


async def classify_adaptations(state: EvaluationState) -> dict[str, Any]:
    """Classify recommendations into adaptation tiers.

    - tier1: Safe to auto-apply (timing adjustments, hashtag changes)
    - tier2: Needs human review (content tone changes, audience targeting)
    - tier3: Major strategic changes (pillar restructuring, platform changes)
    """
    try:
        recommendations = state.get("recommendations", [])

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a marketing operations manager. Classify each recommendation into a tier:\n"
                    "- tier1: Safe to auto-apply. Examples: posting time changes, hashtag optimization, minor caption tweaks.\n"
                    "- tier2: Needs human review. Examples: content tone shifts, new audience targeting, format changes.\n"
                    "- tier3: Major strategic change. Examples: pillar restructuring, platform strategy changes, brand voice shifts.\n"
                    "Return a JSON array where each object has the original recommendation fields plus a 'tier' field (1, 2, or 3)."
                ),
            },
            {
                "role": "user",
                "content": f"Recommendations:\n{sanitize_json_for_prompt(recommendations, max_length=8000)}",
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.2, response_format={"type": "json_object"}
        )
        classified = parse_llm_json(
            result, fallback=[{**r, "tier": 2} for r in recommendations]
        )
        if isinstance(classified, dict):
            classified = next(
                (v for v in classified.values() if isinstance(v, list)), []
            )

        return {"adaptations": classified}
    except Exception as exc:
        logger.error("classify_adaptations failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"classify_adaptations failed: {exc}",
            ],
        }


async def store_adaptations_node(state: EvaluationState) -> dict[str, Any]:
    """Persist classified adaptations to the database."""
    try:
        brand_id = state["brand_id"]
        adaptations = state.get("adaptations", [])
        if not adaptations:
            logger.info("No adaptations to store for brand %s", brand_id)
            return {"status": "completed"}

        # adaptations.source_content_id is NOT NULL, so these brand-level
        # recommendations need a real content anchor. Use the current content
        # row of the best-engaging item the evaluation actually analysed,
        # falling back to the analysed row's own (possibly superseded) content.
        ranked = sorted(
            state.get("performance_data") or [],
            key=lambda r: float(r.get("engagement_rate") or 0),
            reverse=True,
        )
        item_ids: list[str] = []
        for r in ranked:
            item_id = str(r.get("calendar_item_id") or "")
            if item_id and item_id not in item_ids:
                item_ids.append(item_id)
        source_content_id = await resolve_current_content_id(item_ids)
        if not source_content_id and ranked:
            source_content_id = str(ranked[0].get("content_id") or "") or None
        if not source_content_id:
            return {
                "status": "failed",
                "errors": [
                    *(state.get("errors") or []),
                    "store_adaptations failed: no content row to anchor adaptations",
                ],
            }

        db_records = []
        for a in adaptations:
            db_records.append(
                {
                    "brand_id": brand_id,
                    "source_content_id": source_content_id,
                    "tier": a.get("tier", 2),
                    "description": a.get("description", a.get("title", "")),
                    "confidence": a.get("confidence", 0.5),
                    "data": json.dumps(a),
                    # 'pending' is not in the adaptations status CHECK —
                    # tier 2/3 recommendations wait for review as 'proposed'.
                    "status": "auto_applied" if a.get("tier") == 1 else "proposed",
                }
            )

        ids = await store_adaptations(db_records)
        logger.info("Stored %d adaptations for brand %s", len(ids), brand_id)

        return {"status": "completed"}
    except Exception as exc:
        logger.error("store_adaptations_node failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"store_adaptations failed: {exc}",
            ],
        }
