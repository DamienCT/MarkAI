"""Calendar planning workflow nodes — real DB and LLM calls."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from shared.llm import chat_completion, parse_llm_json
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.database import (
    get_brand,
    get_brand_config,
    get_latest_strategy,
    get_products,
    get_recent_calendar_items,
    store_calendar_items,
    store_strategy,
)

from workflows.planning.state import PlanningState

logger = logging.getLogger(__name__)

VALID_CHANNELS = {
    "instagram",
    "facebook",
    "linkedin",
    "youtube",
    "tiktok",
    "x",
    "website_blog",
    "teams",
}
VALID_CONTENT_TYPES = {
    "post",
    "story",
    "reel",
    "carousel",
    "article",
    "newsletter",
    "ad",
    "event",
    "other",
}


class CalendarItemValidator(BaseModel):
    """Validates LLM-generated calendar items before DB insert."""

    scheduled_date: str
    platform: str = "instagram"
    content_type: str = "post"
    campaign_name: Optional[str] = None
    theme: Optional[str] = None
    pillar: Optional[str] = None
    target_audience: Optional[str] = None
    weekly_sub_theme: Optional[str] = None
    content_brief: Optional[str] = None
    visual_direction: Optional[str] = None
    cta_type: Optional[str] = None
    product_name: Optional[str] = None
    product_id: Optional[str] = None
    product_sku: Optional[str] = None

    @field_validator("product_id", mode="before")
    @classmethod
    def coerce_product_id(cls, v: Any) -> Optional[str]:
        """Coerce UUID objects to strings."""
        if v is None:
            return None
        return str(v)

    @field_validator("scheduled_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except (ValueError, TypeError):
            # Try date-only format
            from datetime import date as _date

            _date.fromisoformat(v[:10])
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        v = v.lower().strip()
        channel_map = {"twitter": "x", "blog": "website_blog", "web": "website_blog"}
        v = channel_map.get(v, v)
        if v not in VALID_CHANNELS:
            v = "instagram"
        return v

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        v = v.lower().strip()
        return v if v in VALID_CONTENT_TYPES else "post"

    model_config = {"extra": "allow"}


async def load_strategy(state: PlanningState) -> dict[str, Any]:
    """Load the latest approved strategy and enabled channels from the database."""
    brand_id = state["brand_id"]
    strategy = await get_latest_strategy(brand_id)
    if not strategy:
        return {
            "errors": [*(state.get("errors") or []), "No strategy found"],
            "status": "failed",
        }

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
        ch
        for ch, cfg in channels_cfg.items()
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

    # Load existing calendar items for deduplication context
    try:
        existing_items = await get_recent_calendar_items(brand_id, days=90)
    except Exception as exc:
        logger.warning(
            "Failed to load existing calendar items for brand %s: %s", brand_id, exc
        )
        existing_items = []

    return {
        "strategy": strategy_data,
        "enabled_channels": enabled_channels,
        "existing_items": existing_items,
    }


async def generate_campaigns(state: PlanningState) -> dict[str, Any]:
    """Generate campaign plans from the strategy using LLM, plus a year-long strategy document."""
    try:
        return await _generate_campaigns_inner(state)
    except Exception as exc:
        logger.error("generate_campaigns failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_campaigns failed: {exc}",
            ],
        }


async def _generate_campaigns_inner(state: PlanningState) -> dict[str, Any]:
    brand_id = state["brand_id"]
    strategy = state.get("strategy", {})
    scope_weeks = state.get("scope_weeks", 4)
    enabled_channels = state.get("enabled_channels", ["instagram"])
    start_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end_date = (datetime.now(timezone.utc) + timedelta(weeks=scope_weeks)).strftime(
        "%Y-%m-%d"
    )

    # Load brand info for strategy document (get_brand returns name, etc.)
    brand = await get_brand(brand_id) or {}

    # Load products for product-aware campaign planning
    try:
        products = await get_products(brand_id)
    except Exception as exc:
        logger.warning("Failed to load products for brand %s: %s", brand_id, exc)
        products = []
    product_summary = sanitize_json_for_prompt(
        [
            {
                "name": p.get("name"),
                "category": p.get("category"),
                "vendor": p.get("vendor"),
                "description": (p.get("description") or "")[:200],
            }
            for p in products[:50]
        ],
        max_length=3000,
    )

    channels_str = ", ".join(enabled_channels)
    prompt = [
        {
            "role": "system",
            "content": (
                "You are a campaign planner. Based on the brand's target market and strategy, generate specific campaigns "
                f"for the period {start_date} to {end_date} ({scope_weeks} weeks). "
                f"Generate content ONLY for these platforms: {channels_str}. "
                "Do NOT generate content for any other platforms. "
                "Each campaign should have: name, description, start_date, "
                "end_date, pillar, platforms, goal, kpis, "
                "target_metrics (object with reach, engagement_rate targets), "
                "creative_direction (2-3 sentences describing the visual/tonal approach), "
                "content_format_mix (object with content_type percentages e.g. {reel: 40, carousel: 30, static: 20, story: 10}), "
                "target_audience (primary persona name from strategy). "
                "Return a JSON array."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Strategy:\n{sanitize_json_for_prompt(strategy, max_length=8000)}\n\n"
                f"Available Products:\n{product_summary}"
            ),
        },
    ]
    result = await chat_completion(
        prompt, temperature=0.5, response_format={"type": "json_object"}
    )
    campaigns = parse_llm_json(
        result, fallback=[{"name": "General Campaign", "description": result}]
    )
    if isinstance(campaigns, dict):
        campaigns = next((v for v in campaigns.values() if isinstance(v, list)), [])

    # ── Generate year-long content calendar strategy document ──────────────
    strategy_doc_prompt = [
        {
            "role": "system",
            "content": (
                "You are a senior content strategist. Create a comprehensive Content Calendar Strategy Document "
                "that covers the full year. This document will be the reference guide for daily content generation. "
                "Write everything in English.\n\n"
                "FORMATTING REQUIREMENTS (strict):\n"
                "- Use '## ' for major section headers (e.g., '## Monthly Overview', '## Q1 Strategy')\n"
                "- Use '### ' for month names (e.g., '### January', '### February')\n"
                "- Use bullet lists (- ) for key points\n"
                "- Use **bold** for emphasis on key terms\n"
                "- Use '---' horizontal rules between quarters\n"
                "- Include a markdown table for the yearly overview with columns: Month | Theme | Key Dates | Content Focus | Pillar Rotation\n"
                "- Include a markdown table for content mix ratios by platform\n"
                "- Start with an executive summary paragraph\n\n"
                "CONTENT TO INCLUDE:\n"
                "- Monthly themes with strategic rationale\n"
                "- Seasonal hooks and key dates/holidays relevant to the brand's market\n"
                "- Content pillar rotation schedule\n"
                "- Content mix ratios per platform\n"
                "- Strategic rationale for content sequencing"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Brand: {sanitize_for_prompt(brand.get('name', '') or '')}\n"
                f"Positioning: {sanitize_json_for_prompt(strategy.get('positioning', {}), max_length=3000)}\n"
                f"Pillars: {sanitize_json_for_prompt(strategy.get('pillars', []), max_length=3000)}\n"
                f"Audiences: {sanitize_json_for_prompt(strategy.get('audiences', []), max_length=3000)}\n"
                f"Cadence: {sanitize_json_for_prompt(strategy.get('cadence', {}), max_length=3000)}\n"
                f"Themes: {sanitize_json_for_prompt(strategy.get('themes', []), max_length=3000)}\n"
                f"Enabled Channels: {channels_str}\n"
                f"Generate a full 12-month content calendar strategy document."
            ),
        },
    ]
    strategy_document = await chat_completion(
        strategy_doc_prompt, temperature=0.6, max_tokens=16384
    )
    logger.info(
        "Generated year-long strategy document for brand %s (%d chars)",
        brand_id,
        len(strategy_document),
    )

    return {"campaigns": campaigns, "strategy_document": strategy_document}


async def generate_calendar(state: PlanningState) -> dict[str, Any]:
    """Generate individual calendar items from campaigns, incorporating product awareness."""
    try:
        return await _generate_calendar_inner(state)
    except Exception as exc:
        logger.error("generate_calendar failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_calendar failed: {exc}",
            ],
        }


async def _generate_calendar_inner(state: PlanningState) -> dict[str, Any]:
    brand_id = state["brand_id"]
    campaigns = state.get("campaigns", [])
    strategy = state.get("strategy", {})
    strategy_document = state.get("strategy_document", "")
    enabled_channels = state.get("enabled_channels", ["instagram"])
    existing_items = state.get("existing_items", [])

    # Always start from January 1 of current year — the Content Strategy
    # covers the full year with events tied to specific dates.
    now = datetime.now(timezone.utc)
    start_date_dt = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    end_date_dt = datetime(now.year, 12, 31, tzinfo=timezone.utc)

    # Build cadence string from strategy so the LLM respects weekly post counts
    cadence = strategy.get("cadence", {})
    cadence_lines = []
    for ch in enabled_channels:
        ch_cadence = cadence.get(ch, {}) if isinstance(cadence, dict) else {}
        if isinstance(ch_cadence, dict):
            posts_per_week = ch_cadence.get("posts_per_week", ch_cadence.get("frequency", ""))
        elif isinstance(ch_cadence, (int, float)):
            posts_per_week = ch_cadence
        else:
            posts_per_week = str(ch_cadence)
        if posts_per_week:
            cadence_lines.append(f"- {ch}: {posts_per_week} posts per week")
        else:
            cadence_lines.append(f"- {ch}: follow strategy guidance")
    cadence_instruction = "\n".join(cadence_lines) if cadence_lines else "Follow the strategy document for posting frequency per channel."

    # Load real products for product-aware content planning
    products = await get_products(brand_id)
    product_summary = [
        {"name": p.get("name"), "sku": p.get("sku"), "vendor": p.get("vendor")}
        for p in products[:50]
    ]

    channels_str = ", ".join(enabled_channels)

    # Generate in weekly batches to avoid LLM truncation on large calendars
    all_items: list[dict[str, Any]] = []
    batch_size_days = 7
    current_dt = start_date_dt
    batch_num = 0

    def _build_dedup_context() -> str:
        """Build dedup context from BOTH existing DB items AND items generated so far in this run."""
        combined = list(existing_items) + all_items
        if not combined:
            return ""
        lines = []
        for i in combined[-60:]:  # Last 60 items (DB + current run)
            date_val = i.get("scheduled_at") or i.get("scheduled_date", "")
            date_str = str(date_val)[:10] if date_val else ""
            theme = i.get("theme") or i.get("title", "")
            sub = i.get("weekly_sub_theme", "")
            pillar = i.get("pillar", "")
            lines.append(f"{date_str} | {pillar} | {theme} | {sub}")
        summary = "\n".join(lines)
        return (
            "ALREADY SCHEDULED CONTENT (you MUST NOT repeat any of these themes, sub-themes, or content angles):\n"
            f"{summary}\n\n"
        )

    while current_dt < end_date_dt:
        batch_num += 1
        batch_end = min(current_dt + timedelta(days=batch_size_days), end_date_dt)
        batch_start_str = current_dt.strftime("%Y-%m-%d")
        batch_end_str = batch_end.strftime("%Y-%m-%d")
        batch_days = (batch_end - current_dt).days

        # Rebuild dedup context EVERY batch to include items generated so far
        dedup_context = _build_dedup_context()

        logger.info(
            "generate_calendar batch %d: %s to %s (%d days, %d existing for dedup)",
            batch_num,
            batch_start_str,
            batch_end_str,
            batch_days,
            len(existing_items) + len(all_items),
        )

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a content calendar planner. Write all content in English. "
                    f"Generate content for the period {batch_start_str} to {batch_end_str} ({batch_days} days). "
                    f"Generate content ONLY for these platforms: {channels_str}. "
                    "Do NOT generate content for any other platforms.\n\n"
                    "POSTING FREQUENCY (from the approved strategy — you MUST follow this exactly):\n"
                    f"{cadence_instruction}\n"
                    "Spread posts evenly across the week. Do NOT post on every day for channels with fewer posts per week. "
                    "For example, if LinkedIn is 3 posts/week, pick 3 non-consecutive days (e.g., Mon, Wed, Fri).\n\n"
                    "CRITICAL DEDUPLICATION RULES:\n"
                    "- Each item MUST have a UNIQUE theme + weekly_sub_theme combination\n"
                    "- Do NOT repeat any theme or angle from the ALREADY SCHEDULED list below\n"
                    "- Rotate through ALL content pillars — do not use the same pillar two weeks in a row\n"
                    "- Vary content types (mix post, reel, carousel, story) across the week\n"
                    "- Each content_brief must describe a DISTINCT topic, not a rephrased version of another\n\n"
                    "Each item MUST include ALL of these fields: "
                    "campaign_name, scheduled_date (YYYY-MM-DD), platform "
                    f"(one of: {channels_str}), content_type (post/reel/story/carousel), "
                    "pillar (which content pillar from strategy), "
                    "theme (monthly theme name — MUST be unique per week), "
                    "weekly_sub_theme (specific sub-theme — MUST be unique across all items), "
                    "target_audience (primary persona for this post), "
                    "content_brief (2-3 sentences describing EXACTLY what this post should communicate), "
                    "product_name (from available products if relevant, else null), "
                    "visual_direction (1 sentence on visual style for the image), "
                    "cta_type (what action to drive: shop, learn, engage, or share). "
                    "Return a JSON array."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{dedup_context}"
                    f"Campaigns:\n{sanitize_json_for_prompt(campaigns, max_length=3000)}\n\n"
                    f"Strategy document (THIS IS THE PRIMARY REFERENCE — follow its monthly themes, "
                    f"seasonal hooks, pillar rotation, and cadence guidance strictly):\n"
                    f"{sanitize_for_prompt(strategy_document, max_length=4000)}\n\n"
                    f"Available products:\n{sanitize_json_for_prompt(product_summary, max_length=2000)}"
                ),
            },
        ]
        try:
            result = await chat_completion(
                prompt,
                temperature=0.5,
                max_tokens=8192,
                response_format={"type": "json_object"},
            )
            logger.info(
                "generate_calendar batch %d LLM response: %d chars",
                batch_num,
                len(result),
            )
            batch_items = parse_llm_json(result, fallback=[])
            if isinstance(batch_items, dict):
                # Check if this is a single calendar item (has scheduled_date) vs a wrapper
                if "scheduled_date" in batch_items or "platform" in batch_items:
                    # LLM returned a single item instead of an array — wrap it
                    batch_items = [batch_items]
                else:
                    # Try to extract the list value from wrapper dict
                    batch_items = next(
                        (v for v in batch_items.values() if isinstance(v, list)), []
                    )
            if not batch_items:
                logger.warning(
                    "generate_calendar batch %d produced 0 items — raw response preview: %s",
                    batch_num,
                    result[:300],
                )
            else:
                logger.info(
                    "generate_calendar batch %d produced %d items",
                    batch_num,
                    len(batch_items),
                )
            all_items.extend(batch_items)
        except Exception as batch_exc:
            logger.error("generate_calendar batch %d failed: %s", batch_num, batch_exc)

        current_dt = batch_end

    logger.info(
        "generate_calendar total: %d items across %d batches", len(all_items), batch_num
    )
    return {"calendar_items": all_items}


async def assign_products(state: PlanningState) -> dict[str, Any]:
    """Match calendar items to real products from the database."""
    try:
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
    except Exception as exc:
        logger.error("assign_products failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"assign_products failed: {exc}"],
        }


async def store_calendar(state: PlanningState) -> dict[str, Any]:
    """Persist calendar items and strategy document to the database."""
    brand_id = state["brand_id"]
    items = state.get("calendar_items", [])
    strategy_document = state.get("strategy_document", "")
    enabled_channels = state.get("enabled_channels", [])
    # Store all calendar items through end of year (strategy covers full year)
    now = datetime.now(timezone.utc)
    max_date = datetime(now.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    db_items = []
    skipped = 0
    for item in items:
        # Validate with Pydantic before DB insert
        try:
            validated = CalendarItemValidator(**item)
        except Exception as ve:
            logger.warning(
                "Skipping invalid calendar item: %s — %s", item.get("theme", ""), ve
            )
            skipped += 1
            continue
        db_items.append(
            {
                "brand_id": brand_id,
                "campaign_id": None,
                "title": validated.theme or validated.campaign_name or "",
                "description": validated.content_brief or item.get("brief", ""),
                "channel": validated.platform,
                "scheduled_at": validated.scheduled_date,
                "content_type": validated.content_type,
                "product_id": validated.product_id,
                "theme": validated.theme,
                "pillar": validated.pillar,
                "target_audience": validated.target_audience,
                "weekly_sub_theme": validated.weekly_sub_theme,
                "content_brief": validated.content_brief,
                "visual_direction": validated.visual_direction,
                "cta_type": validated.cta_type,
                "status": "planned",
            }
        )
    if skipped:
        logger.warning(
            "Skipped %d invalid calendar items for brand %s", skipped, brand_id
        )

    ids = await store_calendar_items(
        db_items, max_date=max_date, enabled_channels=enabled_channels
    )
    logger.info("Stored %d calendar items for brand %s", len(ids), brand_id)

    # Persist year-long strategy document as an agent_run artifact
    if strategy_document:
        try:
            await store_strategy(
                brand_id,
                {
                    "type": "content_calendar_strategy",
                    "strategy_document": strategy_document,
                    "scope_weeks": scope_weeks,
                    "enabled_channels": enabled_channels,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                agent_type="content_calendar",
            )
            logger.info("Stored year-long strategy document for brand %s", brand_id)
        except Exception:
            logger.exception("Failed to store strategy document for brand %s", brand_id)

    return {"status": "completed", "calendar_item_ids": ids}
