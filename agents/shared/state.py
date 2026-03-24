"""Base state TypedDict shared by all workflows."""

from __future__ import annotations

from typing import TypedDict


class BaseState(TypedDict, total=False):
    """Common fields present in every workflow state."""

    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]
