"""Adaptation workflow nodes — surface evaluation recommendations for human
review via LangGraph interrupt(). Nothing is auto-applied: a recommendation
only becomes 'applied' or 'rejected' through an explicit human decision.

Resume contract (agent.resume.run, pinned): the interrupt resolves to
{"decision": "approved"|"rejected", "feedback": str|None}. Approved applies
every recommendation the pause presented; rejected routes through a revision
node that carries the feedback into the next review round (max MAX_REVISIONS
loops per review stage, then the run fails). Anything that is not an explicit
approval is treated as a rejection — fail closed."""

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

# Rejected reviews loop back through their revision node at most this many
# times per review stage; the next rejection fails the run.
MAX_REVISIONS = 2


def _decision(review: Any) -> tuple[str | None, str]:
    """(decision, feedback) from an interrupt resume payload, fail closed."""
    review = review if isinstance(review, dict) else {}
    return review.get("decision"), str(review.get("feedback") or "")


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
    adjustments). Approved applies every recommendation listed in this pause;
    rejected loops through revise_tier2 (feedback re-presented, max
    MAX_REVISIONS rounds, then the run fails). Ids never presented stay
    'proposed'.
    """
    adaptations = state.get("adaptations", [])
    tier2 = [a for a in adaptations if a.get("tier") in (1, 2)]

    if not tier2:
        return {"tier2_proposals": []}

    revisions = int(state.get("tier2_revisions") or 0)
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
            "revision_count": revisions,
            "operator_feedback": state.get("revision_feedback") or None,
            "message": (
                "Review these tier 1-2 recommendations. Approve to apply ALL "
                "of them, or reject with feedback to send them back for "
                "another look."
            ),
        }
    )

    decision, feedback = _decision(review)
    applied = state.get("applied_changes", [])

    if decision == "approved":
        for adaptation in tier2:
            aid = str(adaptation.get("id"))
            await update_adaptation_status(aid, "applied")
            applied.append(
                {
                    "id": aid,
                    "description": adaptation.get("description", ""),
                    "tier": adaptation.get("tier", 2),
                    "action": "human_approved",
                }
            )
        # Clear the loop's feedback so tier 3's first review round never
        # shows tier 2's stale rejection note as operator_feedback.
        return {
            "applied_changes": applied,
            "tier2_proposals": tier2,
            "revision_feedback": "",
        }

    if revisions >= MAX_REVISIONS:
        # Rows stay 'proposed' — a failed run must not write decisions the
        # reviewer never confirmed on the final round.
        return {
            "tier2_proposals": tier2,
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"tier 1-2 recommendations rejected after {revisions} revisions",
            ],
        }
    return {
        "tier2_proposals": tier2,
        "revision_feedback": feedback,
        "status": "needs_revision",
    }


async def revise_tier2(state: AdaptationState) -> dict[str, Any]:
    """Carry the reviewer's rejection feedback into another tier 1-2 round.

    Adaptation proposals come from the evaluation workflow's stored rows —
    there is nothing to regenerate here, so a revision round re-presents the
    same recommendations WITH the operator's feedback attached, and counts
    toward the MAX_REVISIONS cap enforced in propose_tier2.
    """
    revisions = int(state.get("tier2_revisions") or 0) + 1
    logger.info(
        "Tier 1-2 recommendations sent back for review round %d/%d for brand "
        "%s (feedback: %.120s)",
        revisions,
        MAX_REVISIONS,
        state["brand_id"],
        state.get("revision_feedback") or "",
    )
    return {"tier2_revisions": revisions, "status": "running"}


async def propose_tier3(state: AdaptationState) -> dict[str, Any]:
    """Present tier 3 (major strategic) recommendations for review via interrupt().

    Tier 3 includes: pillar restructuring, platform strategy changes,
    brand voice modifications. Same decision contract and revision loop as
    propose_tier2, with its own counter.
    """
    adaptations = state.get("adaptations", [])
    tier3 = [a for a in adaptations if a.get("tier") == 3]

    if not tier3:
        return {"tier3_proposals": [], "status": "completed"}

    revisions = int(state.get("tier3_revisions") or 0)
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
            "revision_count": revisions,
            "operator_feedback": state.get("revision_feedback") or None,
            "message": (
                "Review these tier 3 MAJOR strategic recommendations carefully. "
                "These will significantly change the brand's content strategy. "
                "Approve to apply ALL of them, or reject with feedback to send "
                "them back for another look."
            ),
        }
    )

    decision, feedback = _decision(review)
    applied = state.get("applied_changes", [])

    if decision == "approved":
        for adaptation in tier3:
            aid = str(adaptation.get("id"))
            await update_adaptation_status(aid, "applied")
            applied.append(
                {
                    "id": aid,
                    "description": adaptation.get("description", ""),
                    "tier": 3,
                    "action": "human_approved",
                }
            )
        return {
            "applied_changes": applied,
            "tier3_proposals": tier3,
            "status": "completed",
        }

    if revisions >= MAX_REVISIONS:
        return {
            "tier3_proposals": tier3,
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"tier 3 recommendations rejected after {revisions} revisions",
            ],
        }
    return {
        "tier3_proposals": tier3,
        "revision_feedback": feedback,
        "status": "needs_revision",
    }


async def revise_tier3(state: AdaptationState) -> dict[str, Any]:
    """Carry the reviewer's rejection feedback into another tier 3 round."""
    revisions = int(state.get("tier3_revisions") or 0) + 1
    logger.info(
        "Tier 3 recommendations sent back for review round %d/%d for brand "
        "%s (feedback: %.120s)",
        revisions,
        MAX_REVISIONS,
        state["brand_id"],
        state.get("revision_feedback") or "",
    )
    return {"tier3_revisions": revisions, "status": "running"}
