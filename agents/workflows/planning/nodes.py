"""Calendar planning workflow nodes — real DB and LLM calls."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.llm import chat_completion, parse_llm_json
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.database import (
    get_brand,
    get_brand_config,
    get_latest_strategy,
    get_products,
    store_calendar_items,
    store_strategy,
)

from workflows.planning.state import PlanningState

logger = logging.getLogger(__name__)


async def load_strategy(state: PlanningState) -> dict[str, Any]:
    """Load the latest approved strategy and enabled channels from the database."""
    brand_id = state["brand_id"]
    strategy = await get_latest_strategy(brand_id)
    if not strategy:
        return {"errors": [*(state.get("errors") or []), "No strategy found"], "status": "failed"}

    # Load enabled channels from brand config
    brand_config = await get_brand_config(brand_id)
    channels_cfg = (brand_config or {}).get("brand_guidelines", {})
    # brand_guidelines may be stored as a JSON string
    if isinstance(channels_cfg, str):
        try:
            channels_cfg = json.loads(channels_cfg)
        except (json.JSONDecodeError, TypeError):
            channels_cfg = {}
    channels_cfg = channels_cfg.get("channels", {})
    enabled_channels = [
        ch for ch, cfg in channels_cfg.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    if not enabled_channels:
        enabled_channels = ["instagram"]  # fallback
    logger.info("Enabled channels for brand %s: %s", brand_id, enabled_channels)

    strategy_data = strategy.get("output_payload", strategy)
    if isinstance(strategy_data, str):
        try:
            strategy_data = json.loads(strategy_data)
        except (json.JSONDecodeError, TypeError):
            strategy_data = {}
    return {
        "strategy": strategy_data,
        "enabled_channels": enabled_channels,
    }


async def generate_campaigns(state: PlanningState) -> dict[str, Any]:
    """Generate campaign plans from the strategy using LLM, plus a year-long strategy document."""
    try:
        return await _generate_campaigns_inner(state)
    except Exception as exc:
        logger.error("generate_campaigns failed: %s", exc)
        return {"status": "failed", "errors": [*(state.get("errors") or []), f"generate_campaigns failed: {exc}"]}


async def _generate_campaigns_inner(state: PlanningState) -> dict[str, Any]:
    brand_id = state["brand_id"]
    strategy = state.get("strategy", {})
    scope_weeks = state.get("scope_weeks", 4)
    enabled_channels = state.get("enabled_channels", ["instagram"])
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(weeks=scope_weeks)).strftime("%Y-%m-%d")

    # Load brand info for strategy document (get_brand returns name, etc.)
    brand = await get_brand(brand_id) or {}

    channels_str = ", ".join(enabled_channels)
    prompt = [
        {"role": "system", "content": (
            "You are a campaign planner. The brand operates in Mauritius. Consider the local market, "
            "Indian Ocean region, bilingual (English/French) content needs, local holidays and events, "
            "and regional consumer preferences. Based on the strategy, generate specific campaigns "
            f"for the period {start_date} to {end_date} ({scope_weeks} weeks). "
            f"Generate content ONLY for these platforms: {channels_str}. "
            "Do NOT generate content for any other platforms. "
            "Each campaign should have: name, description, start_date, "
            "end_date, pillar, platforms, goal, kpis. Return a JSON array."
        )},
        {"role": "user", "content": f"Strategy:\n{sanitize_json_for_prompt(strategy, max_length=8000)}"},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    campaigns = parse_llm_json(result, fallback=[{"name": "General Campaign", "description": result}])

    # ── Generate year-long content calendar strategy document ──────────────
    strategy_doc_prompt = [
        {"role": "system", "content": (
            "You are a senior content strategist. Create a comprehensive Content Calendar Strategy Document "
            "that covers the full year. This document will be the reference guide for daily content generation. "
            "Include: monthly themes, seasonal hooks, content pillars rotation, key dates and holidays relevant to "
            "Mauritius and the Indian Ocean region (Independence Day March 12, Diwali, Eid, Chinese New Year, "
            "Christmas, Cavadee, Abolition of Slavery Feb 1, Thaipoosam Cavadee, Maha Shivaratri, Ugadi, "
            "Ganesh Chaturthi, Pere Laval Pilgrimage Sep 9, etc.), content mix ratios, and the strategic rationale "
            "for the content sequencing. Format as structured markdown."
        )},
        {"role": "user", "content": (
            f"Brand: {sanitize_for_prompt(brand.get('name', '') or '')}\n"
            f"Positioning: {sanitize_json_for_prompt(strategy.get('positioning', {}), max_length=1000)}\n"
            f"Pillars: {sanitize_json_for_prompt(strategy.get('pillars', []), max_length=1000)}\n"
            f"Audiences: {sanitize_json_for_prompt(strategy.get('audiences', []), max_length=1000)}\n"
            f"Cadence: {sanitize_json_for_prompt(strategy.get('cadence', {}), max_length=500)}\n"
            f"Themes: {sanitize_json_for_prompt(strategy.get('themes', []), max_length=1000)}\n"
            f"Enabled Channels: {channels_str}\n"
            f"Generate a full 12-month content calendar strategy document."
        )},
    ]
    strategy_document = await chat_completion(strategy_doc_prompt, temperature=0.6)
    logger.info("Generated year-long strategy document for brand %s (%d chars)", brand_id, len(strategy_document))

    return {"campaigns": campaigns, "strategy_document": strategy_document}


async def generate_calendar(state: PlanningState) -> dict[str, Any]:
    """Generate individual calendar items from campaigns, incorporating product awareness."""
    try:
        return await _generate_calendar_inner(state)
    except Exception as exc:
        logger.error("generate_calendar failed: %s", exc)
        return {"status": "failed", "errors": [*(state.get("errors") or []), f"generate_calendar failed: {exc}"]}


async def _generate_calendar_inner(state: PlanningState) -> dict[str, Any]:
    brand_id = state["brand_id"]
    campaigns = state.get("campaigns", [])
    strategy = state.get("strategy", {})
    strategy_document = state.get("strategy_document", "")
    scope_weeks = state.get("scope_weeks", 4)
    enabled_channels = state.get("enabled_channels", ["instagram"])
    start_date_dt = datetime.now(timezone.utc)
    end_date_dt = start_date_dt + timedelta(weeks=scope_weeks)
    start_date = start_date_dt.strftime("%Y-%m-%d")
    end_date = end_date_dt.strftime("%Y-%m-%d")
    total_days = (end_date_dt - start_date_dt).days
    total_items = len(enabled_channels) * total_days

    # Load real products for product-aware content planning
    products = await get_products(brand_id)
    product_summary = [
        {"name": p.get("name"), "sku": p.get("sku"), "vendor": p.get("vendor")}
        for p in products[:50]
    ]

    channels_str = ", ".join(enabled_channels)
    prompt = [
        {"role": "system", "content": (
            "You are a content calendar planner. The brand operates in Mauritius. Consider the local market, "
            "Indian Ocean region, bilingual (English/French) content needs, local holidays and events, "
            "and regional consumer preferences. Generate content for the period "
            f"{start_date} to {end_date} ({scope_weeks} weeks). "
            f"Generate content ONLY for these platforms: {channels_str}. "
            "Do NOT generate content for any other platforms. "
            "CRITICAL: Generate EXACTLY 1 post per enabled channel per day, for EVERY day in the date range. "
            f"No gaps — every single day from {start_date} to {end_date} must have content for each enabled channel. "
            f"There are {len(enabled_channels)} enabled channel(s) and {total_days} days, "
            f"so generate exactly {total_items} items total. "
            "Distribute content evenly — do NOT cluster posts on certain days or skip weekends. "
            "Generate specific calendar items for each campaign. "
            "Each item should have: campaign_name, scheduled_date (YYYY-MM-DD), platform "
            f"(one of: {channels_str}), content_type (post/reel/story/carousel), "
            "theme, product_name (from available products if relevant, else null), brief. "
            "Return a JSON array."
        )},
        {"role": "user", "content": (
            f"Campaigns:\n{sanitize_json_for_prompt(campaigns, max_length=5000)}\n\n"
            f"Strategy cadence:\n{sanitize_json_for_prompt(strategy.get('cadence', {}), max_length=2000)}\n\n"
            f"Strategy document (use as reference for themes and seasonal hooks):\n"
            f"{sanitize_for_prompt(strategy_document, max_length=3000)}\n\n"
            f"Available products:\n{sanitize_json_for_prompt(product_summary, max_length=3000)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5, max_tokens=8192)
    items = parse_llm_json(result, fallback=[])
    return {"calendar_items": items}


async def assign_products(state: PlanningState) -> dict[str, Any]:
    """Match calendar items to real products from the database."""
    brand_id = state["brand_id"]
    items = state.get("calendar_items", [])
    try:
        products = await get_products(brand_id)
    except Exception as exc:
        logger.warning("Failed to load products for brand %s: %s", brand_id, exc)
        products = []

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
    """Persist calendar items and strategy document to the database."""
    brand_id = state["brand_id"]
    items = state.get("calendar_items", [])
    strategy_document = state.get("strategy_document", "")
    enabled_channels = state.get("enabled_channels", [])
    scope_weeks = state.get("scope_weeks", 4)
    max_date = datetime.now(timezone.utc) + timedelta(weeks=scope_weeks)

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

    ids = await store_calendar_items(db_items, max_date=max_date, enabled_channels=enabled_channels)
    logger.info("Stored %d calendar items for brand %s", len(ids), brand_id)

    # Persist year-long strategy document as an agent_run artifact
    if strategy_document:
        try:
            await store_strategy(brand_id, {
                "type": "content_calendar_strategy",
                "document": strategy_document,
                "scope_weeks": scope_weeks,
                "enabled_channels": enabled_channels,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            })
            logger.info("Stored year-long strategy document for brand %s", brand_id)
        except Exception:
            logger.exception("Failed to store strategy document for brand %s", brand_id)

    return {"status": "completed", "calendar_item_ids": ids}
