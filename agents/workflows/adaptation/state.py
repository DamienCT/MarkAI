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
