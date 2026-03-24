"""Evaluation workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class EvaluationState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Loaded data
    performance_data: list[dict[str, Any]]

    # Analysis results
    patterns: dict[str, Any]
    recommendations: list[dict[str, Any]]
    adaptations: list[dict[str, Any]]
