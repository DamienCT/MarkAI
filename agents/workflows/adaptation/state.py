"""Adaptation workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class AdaptationState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Loaded
    adaptations: list[dict[str, Any]]

    # Results
    applied_changes: list[dict[str, Any]]
    tier2_proposals: list[dict[str, Any]]
    tier3_proposals: list[dict[str, Any]]

    # Human review loop (agent.resume.run contract). Each review stage keeps
    # its own revision counter, capped by nodes.MAX_REVISIONS; the reviewer's
    # rejection feedback is carried into the next review round's payload.
    tier2_revisions: int
    tier3_revisions: int
    revision_feedback: str
