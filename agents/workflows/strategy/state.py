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
    brand_config: dict[str, Any]

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
    # Completed revision loops (rejected → revise → re-review). Capped by
    # nodes.MAX_REVISIONS, after which another rejection fails the run.
    revision_count: int

    # Plain-English summary for non-marketing readers
    executive_summary_plain: str
