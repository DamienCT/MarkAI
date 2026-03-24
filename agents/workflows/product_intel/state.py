"""Product intelligence workflow state."""

from __future__ import annotations

from typing import Any, TypedDict


class ProductIntelState(TypedDict, total=False):
    brand_id: str
    run_id: str
    status: str
    errors: list[str]
    messages: list[dict[str, str]]

    # Data
    products: list[dict[str, Any]]
    brand_mappings: dict[str, list[dict[str, Any]]]
    images: dict[str, str]  # product_id -> image_url
    promotable_items: list[dict[str, Any]]
