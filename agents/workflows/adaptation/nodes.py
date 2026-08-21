"""Adaptation workflow nodes — surface evaluation recommendations for human
review via LangGraph interrupt(). Nothing is auto-applied: a recommendation
only becomes 'applied' or 'rejected' through an explicit human decision."""

from __future__ import annotations

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
    """Load pending recommendations from the database."""
    adaptations = await get_pending_adaptations(state["brand_id"])
    if not adaptations:
        return {"adaptations": [], "status": "no_pending"}
    logger.info(
        "Loaded %d pending recommendations for brand %s",
        len(adaptations),
        state["brand_id"],
    )
    return {"adaptations": adaptations}


async def apply_tier1(state: AdaptationState) -> dict[str, Any]:
    """Tier 1 (low-risk) recommendations are NOT auto-applied.

    No executor exists that could turn a recommendation into a real
    behaviour change, so the old auto-apply only flipped a status flag while
    changing nothing — fake learning (P0-06). Tier-1 rows stay 'proposed'
    and are reviewed together with tier 2 in propose_tier2; applied/rejected
    is written only on an explicit human decision.
    """
    adaptations = state.get("adaptations", [])
    tier1 = [a for a in adaptations if a.get("tier") == 1]
    if tier1:
        logger.info(
            "%d tier-1 recommendations await human review for brand %s "
            "(nothing is auto-applied)",
            len(tier1),
            state["brand_id"],
        )
    return {"applied_changes": []}


async def propose_tier2(state: AdaptationState) -> dict[str, Any]:
    """Present tier 1-2 recommendations for human review via interrupt().

    Covers low-risk tier 1 (posting times, hashtags, minor caption tweaks)
    and medium-risk tier 2 (tone shifts, audience targeting, format
    adjustments) — every tier waits for an explicit human decision.
    """
    adaptations = state.get("adaptations", [])
    tier2 = [a for a in adaptations if a.get("tier") in (1, 2)]

    if not tier2:
        return {"tier2_proposals": []}

    review = interrupt(
        {
            "type": "tier2_review",
            "brand_id": state["brand_id"],
            "adaptations": [
                {
                    "id": str(a.get("id")),
                    "description": a.get("description", ""),
                    "tier": a.get("tier", 2),
                    "confidence": a.get("confidence", 0),
                    "data": a.get("data"),
                }
                for a in tier2
            ],
            "message": (
                "Review these tier 1-2 recommendations. For each id, provide "
                "approved (true/false); ids you leave out stay proposed."
            ),
        }
    )

    # Only explicit decisions count — an id the reviewer did not decide on
    # stays 'proposed'; absence is not a rejection.
    decisions = review.get("decisions", {}) if isinstance(review, dict) else {}
    applied = state.get("applied_changes", [])

    for adaptation in tier2:
        aid = str(adaptation.get("id"))
        if aid not in decisions:
            continue
        approved = bool(decisions.get(aid))
        await update_adaptation_status(aid, "applied" if approved else "rejected")
        if approved:
            applied.append(
                {
                    "id": aid,
                    "description": adaptation.get("description", ""),
                    "tier": adaptation.get("tier", 2),
                    "action": "human_approved",
                }
            )

    return {"applied_changes": applied, "tier2_proposals": tier2}


async def propose_tier3(state: AdaptationState) -> dict[str, Any]:
    """Present tier 3 (major strategic) recommendations for review via interrupt().

    Tier 3 includes: pillar restructuring, platform strategy changes,
    brand voice modifications.
    """
    adaptations = state.get("adaptations", [])
    tier3 = [a for a in adaptations if a.get("tier") == 3]

    if not tier3:
        return {"tier3_proposals": [], "status": "completed"}

    review = interrupt(
        {
            "type": "tier3_review",
            "brand_id": state["brand_id"],
            "adaptations": [
                {
                    "id": str(a.get("id")),
                    "description": a.get("description", ""),
                    "tier": 3,
                    "confidence": a.get("confidence", 0),
                    "data": a.get("data"),
                }
                for a in tier3
            ],
            "message": (
                "Review these tier 3 MAJOR strategic recommendations carefully. "
                "These will significantly change the brand's content strategy. "
                "For each id, provide approved (true/false) and optional "
                "feedback; ids you leave out stay proposed."
            ),
        }
    )

    decisions = review.get("decisions", {}) if isinstance(review, dict) else {}
    applied = state.get("applied_changes", [])

    for adaptation in tier3:
        aid = str(adaptation.get("id"))
        if aid not in decisions:
            continue
        approved = bool(decisions.get(aid))
        await update_adaptation_status(aid, "applied" if approved else "rejected")
        if approved:
            applied.append(
                {
                    "id": aid,
                    "description": adaptation.get("description", ""),
                    "tier": 3,
                    "action": "human_approved",
                }
            )

    return {"applied_changes": applied, "tier3_proposals": tier3, "status": "completed"}
