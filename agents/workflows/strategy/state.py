"""Strategy workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class StrategyState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Loaded data
    research_data: dict[str, Any]

    # Generated strategy components
    positioning: dict[str, Any]
    pillars: list[dict[str, Any]]
    audiences: list[dict[str, Any]]
    cadence: dict[str, Any]
    themes: list[dict[str, Any]]

    # Pipeline control
    trigger: str  # "manual" or "event" — event-triggered skips human review
    auto_approve: bool  # When True, skip interrupt and auto-approve

    # Human review
    human_approved: bool
    human_feedback: str

    # Plain-English summary for non-marketing readers
    executive_summary_plain: str
