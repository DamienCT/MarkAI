"""Calendar planning workflow nodes — real DB and LLM calls."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion
from shared.sanitize import sanitize_json_for_prompt
from shared.tools.database import (
    get_latest_strategy,
    get_products,
    store_calendar_items,
)

from workflows.planning.state import PlanningState

logger = logging.getLogger(__name__)


async def load_strategy(state: PlanningState) -> dict[str, Any]:
    """Load the latest approved strategy from the database."""
    strategy = await get_latest_strategy(state["brand_id"])
    if not strategy:
        return {"errors": [*(state.get("errors") or []), "No strategy found"], "status": "failed"}
    return {"strategy": strategy.get("output_payload", strategy)}


async def generate_campaigns(state: PlanningState) -> dict[str, Any]:
    """Generate campaign plans from the strategy using LLM."""
    strategy = state.get("strategy", {})
    prompt = [
        {"role": "system", "content": (
            "You are a campaign planner. The brand operates in Mauritius. Consider the local market, "
            "Indian Ocean region, bilingual (English/French) content needs, local holidays and events, "
            "and regional consumer preferences. Based on the strategy, generate specific campaigns "
            "for the next month. Each campaign should have: name, description, start_date, "
            "end_date, pillar, platforms, goal, kpis. Return a JSON array."
        )},
        {"role": "user", "content": f"Strategy:\n{sanitize_json_for_prompt(strategy, max_length=8000)}"},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    try:
        campaigns = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        campaigns = [{"name": "General Campaign", "description": result}]
    return {"campaigns": campaigns}


async def generate_calendar(state: PlanningState) -> dict[str, Any]:
    """Generate individual calendar items from campaigns, incorporating product awareness."""
    brand_id = state["brand_id"]
    campaigns = state.get("campaigns", [])
    strategy = state.get("strategy", {})

    # Load real products for product-aware content planning
    products = await get_products(brand_id)
    product_summary = [
        {"name": p.get("name"), "sku": p.get("sku"), "vendor": p.get("vendor")}
        for p in products[:50]
    ]

    prompt = [
        {"role": "system", "content": (
            "You are a content calendar planner. The brand operates in Mauritius. Consider the local market, "
            "Indian Ocean region, bilingual (English/French) content needs, local holidays and events, "
            "and regional consumer preferences. Generate specific calendar items for each campaign. "
            "Each item should have: campaign_name, scheduled_date (YYYY-MM-DD), platform "
            "(instagram/facebook/linkedin), content_type (post/reel/story/carousel), "
            "theme, product_name (from available products if relevant, else null), brief. "
            "Return a JSON array."
        )},
        {"role": "user", "content": (
            f"Campaigns:\n{sanitize_json_for_prompt(campaigns, max_length=5000)}\n\n"
            f"Strategy cadence:\n{sanitize_json_for_prompt(strategy.get('cadence', {}), max_length=2000)}\n\n"
            f"Available products:\n{sanitize_json_for_prompt(product_summary, max_length=3000)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5, max_tokens=8192)
    try:
        items = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        items = []
    return {"calendar_items": items}


async def assign_products(state: PlanningState) -> dict[str, Any]:
    """Match calendar items to real products from the database."""
    brand_id = state["brand_id"]
    items = state.get("calendar_items", [])
    products = await get_products(brand_id)

    product_map = {p["name"].lower(): p for p in products if p.get("name")}

    updated_items = []
    for item in items:
        product_name = (item.get("product_name") or "").lower()
        if product_name and product_name in product_map:
            item["product_id"] = product_map[product_name].get("id")
            item["product_sku"] = product_map[product_name].get("sku")
        updated_items.append(item)

    return {"calendar_items": updated_items}


async def store_calendar(state: PlanningState) -> dict[str, Any]:
    """Persist calendar items to the database."""
    brand_id = state["brand_id"]
    items = state.get("calendar_items", [])

    db_items = []
    for item in items:
        db_items.append({
            "brand_id": brand_id,
            "campaign_id": None,
            "title": item.get("theme") or item.get("campaign_name", ""),
            "description": item.get("brief", ""),
            "channel": item.get("platform", "instagram"),
            "scheduled_at": item.get("scheduled_date"),
            "content_type": item.get("content_type"),
            "product_id": item.get("product_id"),
            "theme": item.get("theme"),
            "status": "planned",
        })

    ids = await store_calendar_items(db_items)
    logger.info("Stored %d calendar items for brand %s", len(ids), brand_id)

    return {"status": "completed", "calendar_item_ids": ids}
