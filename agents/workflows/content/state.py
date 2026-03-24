"""Content generation workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class ContentState(TypedDict, total=False):
    brand_id: str
    run_id: str
    calendar_item_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Context loaded from DB
    calendar_item: dict[str, Any]
    brand: dict[str, Any]
    strategy: dict[str, Any]

    # Generated content
    hook: str
    caption: str
    hashtags: list[str]
    cta: str

    # Images
    product_image: str | None
    product_image_source: str | None
    needs_manual_image: bool
    generated_image: str | None

    # Platform adaptations
    platform_adaptations: dict[str, dict[str, Any]]
