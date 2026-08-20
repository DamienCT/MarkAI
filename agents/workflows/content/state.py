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
    # "lifestyle" (real-looking scene + glass card) | "ad" (studio commercial
    # + big headline). Chosen at generation time for a global ~50/50 mix.
    image_format: str | None
    text_width: float | None

    # Branded image (with logo + text overlay)
    branded_image: str | None
    composed_image: str | None
    # In-flight copies of the two images above, carried between nodes so the
    # vision review and the mockups don't re-download from MinIO what the
    # previous node just uploaded. Memory stays bounded because each key is
    # set to None by its LAST consumer: composed by review_branding, branded
    # by generate_mockups.
    branded_image_bytes: bytes | None
    composed_image_bytes: bytes | None
    logo_png_data: bytes | None
    logo_variant_used: str | None
    logo_xy: tuple[float, float] | None
    text_anchor_used: str | None
    text_xy: tuple[float, float] | None
    text_scale: float | None
    text_style: str | None
    headline_colors: dict | None
    font_family: str | None
    # Optional 2nd logo: the product's manufacturer logo (e.g. Citterio).
    product_logo_image: str | None  # MinIO object name of the logo (default/light)
    # Light/dark variants of the vendor logo, keyed "light"/"dark" → object name.
    product_logo_variants: dict[str, str] | None
    product_logo_xy: tuple[float, float] | None
    product_logo_scale: float | None
    product_logo_enabled: bool | None
    product_logo_variant: str | None  # manual override chosen in the editor

    # Vision-critic review after branding (decides whether to re-render)
    branding_review: dict[str, Any] | None

    # Social mockup previews (for approval UI)
    mockup_urls: dict[str, str]

    # Platform adaptations
    platform_adaptations: dict[str, dict[str, Any]]
