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
    sub_brand: str

    # Full intelligence reports — exposed so enrich_user_brief and the
    # generation nodes can mine them when the brief is sparse.
    research: dict[str, Any]
    planning: dict[str, Any]
    events: list[dict[str, Any]]

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
    composed_image: str | None
    logo_png_data: bytes | None
    logo_variant_used: str | None
    logo_xy: tuple[float, float] | None
    text_anchor_used: str | None
    text_xy: tuple[float, float] | None
    text_scale: float | None
    text_style: str | None

    # Vision-critic review after branding (decides whether to re-render)
    branding_review: dict[str, Any] | None

    # Social mockup previews (for approval UI)
    mockup_urls: dict[str, str]

    # Platform adaptations
    platform_adaptations: dict[str, dict[str, Any]]
