"""Adaptation workflow nodes — applies safe changes automatically and
requests human review for higher-tier changes via LangGraph interrupt()."""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.types import interrupt

from shared.tools.database import (
    get_pending_adaptations,
    update_adaptation_status,
)

from workflows.adaptation.state import AdaptationState

logger = logging.getLogger(__name__)


async def load_adaptations(state: AdaptationState) -> dict[str, Any]:
    """Load pending adaptations from the database."""
    adaptations = await get_pending_adaptations(state["brand_id"])
    if not adaptations:
        return {"adaptations": [], "status": "no_pending"}
    logger.info("Loaded %d pending adaptations for brand %s", len(adaptations), state["brand_id"])
    return {"adaptations": adaptations}


async def apply_tier1(state: AdaptationState) -> dict[str, Any]:
    """Auto-apply tier 1 (safe) changes without human review.

    Tier 1 includes: posting time adjustments, hashtag optimizations,
    minor caption style tweaks.
    """
    adaptations = state.get("adaptations", [])
    tier1 = [a for a in adaptations if a.get("tier") == 1]

    applied: list[dict[str, Any]] = []
    for adaptation in tier1:
        adaptation_id = adaptation.get("id")
        try:
            # Mark as applied in the database
            await update_adaptation_status(str(adaptation_id), "applied")
            applied.append({
                "id": str(adaptation_id),
                "description": adaptation.get("description", ""),
                "tier": 1,
                "action": "auto_applied",
            })
            logger.info("Auto-applied tier1 adaptation %s", adaptation_id)
        except Exception:
            logger.exception("Failed to apply tier1 adaptation %s", adaptation_id)

    return {"applied_changes": applied}


async def propose_tier2(state: AdaptationState) -> dict[str, Any]:
    """Present tier 2 adaptations for human review via interrupt().

    Tier 2 includes: content tone shifts, audience targeting changes,
    format adjustments.
    """
    adaptations = state.get("adaptations", [])
    tier2 = [a for a in adaptations if a.get("tier") == 2]

    if not tier2:
        return {"tier2_proposals": []}

    review = interrupt({
        "type": "tier2_review",
        "brand_id": state["brand_id"],
        "adaptations": [
            {
                "id": str(a.get("id")),
                "description": a.get("description", ""),
                "confidence": a.get("confidence", 0),
                "data": a.get("data"),
            }
            for a in tier2
        ],
        "message": "Review these tier 2 adaptations. For each, provide approved (true/false).",
    })

    # Process human decisions
    decisions = review.get("decisions", {})
    applied = state.get("applied_changes", [])

    for adaptation in tier2:
        aid = str(adaptation.get("id"))
        approved = decisions.get(aid, False)
        new_status = "applied" if approved else "rejected"
        await update_adaptation_status(aid, new_status)
        if approved:
            applied.append({
                "id": aid,
                "description": adaptation.get("description", ""),
                "tier": 2,
                "action": "human_approved",
            })

    return {"applied_changes": applied, "tier2_proposals": tier2}


async def propose_tier3(state: AdaptationState) -> dict[str, Any]:
    """Present tier 3 (major strategic) adaptations for human review via interrupt().

    Tier 3 includes: pillar restructuring, platform strategy changes,
    brand voice modifications.
    """
    adaptations = state.get("adaptations", [])
    tier3 = [a for a in adaptations if a.get("tier") == 3]

    if not tier3:
        return {"tier3_proposals": [], "status": "completed"}

    review = interrupt({
        "type": "tier3_review",
        "brand_id": state["brand_id"],
        "adaptations": [
            {
                "id": str(a.get("id")),
                "description": a.get("description", ""),
                "confidence": a.get("confidence", 0),
                "data": a.get("data"),
            }
            for a in tier3
        ],
        "message": (
            "Review these tier 3 MAJOR strategic adaptations carefully. "
            "These will significantly change the brand's content strategy. "
            "For each, provide approved (true/false) and optional feedback."
        ),
    })

    decisions = review.get("decisions", {})
    applied = state.get("applied_changes", [])

    for adaptation in tier3:
        aid = str(adaptation.get("id"))
        approved = decisions.get(aid, False)
        new_status = "applied" if approved else "rejected"
        await update_adaptation_status(aid, new_status)
        if approved:
            applied.append({
                "id": aid,
                "description": adaptation.get("description", ""),
                "tier": 3,
                "action": "human_approved",
            })

    return {"applied_changes": applied, "tier3_proposals": tier3, "status": "completed"}
