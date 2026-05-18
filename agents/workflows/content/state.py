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
    positioning: dict[str, Any]
    relevant_pillar: dict[str, Any]
    relevant_audience: dict[str, Any]
    month_context: str
    recent_posts: list[dict[str, Any]]
    top_performing: list[dict[str, Any]]
    product: dict[str, Any]

    # Generated content
    hook: str
    caption: str
    hashtags: list[str]
    cta: str

    # Images
    product_image: str | None
    product_image_source: str | None
    product_id: str | None
    needs_manual_image: bool
    is_lifestyle_only: bool
    enhanced_image_prompt: str | None
    generated_image: str | None

    # Branded image (with logo + text overlay)
    branded_image: str | None
    logo_png_data: bytes | None

    # Social mockup previews (for approval UI)
    mockup_urls: dict[str, str]

    # Platform adaptations
    platform_adaptations: dict[str, dict[str, Any]]
