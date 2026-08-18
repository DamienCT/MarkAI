"""Calendar planning workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class PlanningState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Configuration
    scope_weeks: int  # Planning horizon in weeks (default 4, activation uses 2)
    enabled_channels: list[str]  # Channels enabled in brand config
    content_format: str  # "posts_only" | "mixed" — Edit Documents override
    campaign_overrides: list[dict[str, Any]]  # user-curated campaigns (Edit Documents)
    removed_campaigns: list[str]  # campaign names the user removed (Edit Documents)
    target_months: list[str]  # ["YYYY-MM"] — targeted re-plan; empty = full horizon

    # Loaded data
    brand_context: str  # Brand identity + guardrails prompt block (shared.brand_context)
    brand_timezone: str  # IANA timezone the brand's posting times are expressed in
    strategy: dict[str, Any]
    events: list[dict[str, Any]]  # Significant dates (holidays, awareness weeks, etc.) over next 12 months
    existing_items: list[dict[str, Any]]  # Recent calendar items for deduplication

    # Generated
    campaigns: list[dict[str, Any]]
    strategy_document: str  # Year-long content calendar strategy document (markdown)
    calendar_items: list[dict[str, Any]]
    calendar_item_ids: list[str]

    # Plain-English summary for non-marketing readers (planning report)
    executive_summary_plain: str
