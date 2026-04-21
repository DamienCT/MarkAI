"""Research workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class ResearchState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Populated by nodes
    website_url: str
    website_data: list[dict[str, Any]]
    social_profiles: dict[str, Any]
    social_analysis: dict[str, Any]
    competitor_urls: list[str]
    competitor_analysis: list[dict[str, Any]]
    personas: list[dict[str, Any]]
    gaps: list[dict[str, Any]]
    events: list[dict[str, Any]]
    research_data: dict
