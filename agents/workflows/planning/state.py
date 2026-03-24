"""Calendar planning workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class PlanningState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Loaded data
    strategy: dict[str, Any]

    # Generated
    campaigns: list[dict[str, Any]]
    calendar_items: list[dict[str, Any]]
