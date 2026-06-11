"""Calendar planning workflow nodes — real DB and LLM calls."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from shared.llm import (
    chat_completion,
    generate_executive_summary_plain,
    parse_llm_json,
)
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.database import (
    delete_planned_calendar_items,
    get_brand,
    get_brand_config,
    get_events_for_research,
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


def _format_events_for_prompt(events: list[dict[str, Any]]) -> str:
    """Render the events list as a compact markdown bullet list for LLM prompts."""
    if not events:
        return "(no significant events registered — use only universally-known dates)"
    lines = []
    for ev in events:
        start = ev.get("start", "")
        end = ev.get("end")
        title = ev.get("title", "")
        category = ev.get("category") or "event"
        scope = ev.get("scope", "global")
        date_str = f"{start} → {end}" if end else start
        lines.append(f"- {date_str}: {title} ({category}, {scope})")
    return "\n".join(lines)


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
    guidelines = (brand_config or {}).get("brand_guidelines", {})
    # brand_guidelines may be stored as a JSON string
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except (json.JSONDecodeError, TypeError):
            guidelines = {}
    if not isinstance(guidelines, dict):
        guidelines = {}
    overrides = guidelines.get("overrides") or {}
    channels_cfg = guidelines.get("channels", {})
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

    # ── Apply "Edit Documents" overrides with PRIORITY over the auto strategy ──
    # Cadence override: per-channel posts_per_week / best_days set by the user
    # win over what the strategy generated. Stored in brand_guidelines.overrides.
    if isinstance(strategy_data, dict) and isinstance(overrides, dict) and overrides.get("cadence"):
        merged_cadence = dict(strategy_data.get("cadence") or {})
        for ch, cfg in overrides["cadence"].items():
            base = dict(merged_cadence.get(ch)) if isinstance(merged_cadence.get(ch), dict) else {}
            if isinstance(cfg, dict):
                base.update(cfg)
                merged_cadence[ch] = base
        strategy_data["cadence"] = merged_cadence
        logger.info(
            "Applied cadence override for brand %s: %s",
            brand_id, list(overrides["cadence"].keys()),
        )
    # Content pillars / target audiences overrides (used downstream for rotation).
    if isinstance(strategy_data, dict) and isinstance(overrides, dict):
        if overrides.get("content_pillars"):
            strategy_data["content_pillars"] = [
                {"name": p} if isinstance(p, str) else p
                for p in overrides["content_pillars"]
            ]
        if overrides.get("target_audiences"):
            strategy_data["target_audiences"] = overrides["target_audiences"]
        # Positioning / monthly themes overrides flow to the campaign LLM via
        # the strategy blob (see _generate_campaigns_inner prompt). Positioning
        # is merged into value_proposition so the other sub-fields survive.
        if overrides.get("positioning"):
            pos = strategy_data.get("positioning")
            if isinstance(pos, dict):
                pos = dict(pos)
                pos["value_proposition"] = overrides["positioning"]
                strategy_data["positioning"] = pos
            else:
                strategy_data["positioning"] = overrides["positioning"]
        if overrides.get("monthly_themes"):
            strategy_data["monthly_themes"] = overrides["monthly_themes"]

    # Load existing calendar items for deduplication context
    try:
        existing_items = await get_recent_calendar_items(brand_id, days=90)
    except Exception as exc:
        logger.warning(
            "Failed to load existing calendar items for brand %s: %s", brand_id, exc
        )
        existing_items = []

    # Load significant events (global + brand-scoped) so downstream nodes can
    # anchor the strategy document and calendar items to real dates.
    try:
        events = await get_events_for_research(brand_id, months_ahead=12)
    except Exception as exc:
        logger.warning("Failed to load events for brand %s: %s", brand_id, exc)
        events = []
    logger.info("Loaded %d events for planning brand %s", len(events), brand_id)

    return {
        "strategy": strategy_data,
        "enabled_channels": enabled_channels,
        "existing_items": existing_items,
        "events": events,
        # Edit Documents override; defaults to posts-only.
        "content_format": (overrides.get("content_format") if isinstance(overrides, dict) else None) or "posts_only",
        "campaign_overrides": (overrides.get("campaigns") if isinstance(overrides, dict) else None) or [],
        "removed_campaigns": (overrides.get("removed_campaigns") if isinstance(overrides, dict) else None) or [],
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
    scope_weeks = state.get("scope_weeks", 52)
    enabled_channels = state.get("enabled_channels", ["instagram"])
    events = state.get("events", [])
    events_block = _format_events_for_prompt(events)
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

    # ── Edit Documents campaign overrides ─────────────────────────────────
    # User-curated campaigns MUST be included (enriched with full structure);
    # removed campaign names MUST NOT reappear.
    campaign_overrides = state.get("campaign_overrides") or []
    removed_campaigns = state.get("removed_campaigns") or []
    constraints = ""
    if campaign_overrides:
        must_include = "; ".join(
            f"{c.get('name', '')}" + (f" — {c.get('description', '')}" if c.get("description") else "")
            for c in campaign_overrides if isinstance(c, dict) and c.get("name")
        )
        if must_include:
            constraints += (
                " You MUST include these user-defined campaigns, enriching each with the full "
                f"structure (use the given name/description verbatim as the basis): {must_include}."
            )
    if removed_campaigns:
        constraints += (
            " You MUST NOT generate any campaign matching these removed names: "
            f"{', '.join(removed_campaigns)}."
        )

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
                + constraints
            ),
        },
        {
            "role": "user",
            "content": (
                f"Strategy:\n{sanitize_json_for_prompt(strategy, max_length=8000)}\n\n"
                f"Significant Events Calendar (anchor campaigns to these dates where relevant):\n"
                f"{events_block}\n\n"
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

    # Safety net: drop any campaign whose name the user removed (LLM may ignore).
    if removed_campaigns and isinstance(campaigns, list):
        _removed_lc = {n.strip().lower() for n in removed_campaigns if isinstance(n, str)}
        campaigns = [
            c for c in campaigns
            if not (isinstance(c, dict) and (c.get("name") or "").strip().lower() in _removed_lc)
        ]

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
                "- Strategic rationale for content sequencing\n\n"
                "EVENTS CALENDAR INTEGRATION (CRITICAL):\n"
                "- The user message includes a 'Significant Events Calendar' — these are the ONLY event dates you may cite.\n"
                "- You MUST reference EVERY event from that list by name and date in the appropriate monthly section.\n"
                "- Each event must appear in the 'Key Dates' column of the yearly overview table.\n"
                "- Date-range events (e.g. 2026-05-11 → 2026-05-27) are multi-day campaigns; plan a sustained content arc across the range.\n"
                "- Do NOT invent or cite events that are not in that list.\n"
                "- If the list is empty, say so in the executive summary rather than inventing dates.\n\n"
                "CHANNEL CADENCE SECTION (REQUIRED — include a section titled '## Channel Posting Cadence' with this exact format):\n"
                "For EACH enabled channel, include:\n"
                "### [Channel Name]\n"
                "- Weekly cadence: [N] posts per week\n"
                "- Best days: [day1], [day2], [day3]\n"
                "- Best times: [HH:MM], [HH:MM], [HH:MM]\n"
                "- Primary role: [one sentence]\n"
                "- Best formats: [format1], [format2]\n"
                "This section is critical — the content calendar generator reads these exact numbers."
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
                f"Enabled Channels: {channels_str}\n\n"
                f"Significant Events Calendar (the ONLY dates you may cite — include EVERY one):\n"
                f"{events_block}\n\n"
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
    events = state.get("events", [])

    # Content format (Edit Documents override). "posts_only" = single-image
    # posts everywhere (default); "mixed" = let the planner vary formats.
    content_format = state.get("content_format", "posts_only")
    if content_format == "mixed":
        _ctype_rule = "- Vary content types (mix post, reel, carousel, story)\n"
        _ctype_field = 'content_type (post/reel/story/carousel), '
    else:
        _ctype_rule = (
            '- content_type MUST be "post" for EVERY item — single-image posts only '
            "(NO reels, carousels, stories, videos, or articles)\n"
        )
        _ctype_field = 'content_type (always "post"), '

    # Calendar items cover the full year (Jan 1 → Dec 31). The batch loop
    # runs all week×channel combinations in parallel (semaphore=8) so the
    # full-year run completes in ~5 min instead of the old ~36 min sequential.
    now = datetime.now(timezone.utc)
    scope_weeks = max(1, int(state.get("scope_weeks", 52) or 52))
    start_date_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_dt = start_date_dt + timedelta(weeks=scope_weeks)

    # Targeted re-plan (Edit Documents "Apply"): regenerate ONLY the calendar
    # months the user changed. "YYYY-MM" strings → {(year, month)}. Empty set =
    # full horizon (legacy behavior). Only target/purge these months.
    target_months: set[tuple[int, int]] = set()
    for m in state.get("target_months") or []:
        try:
            y, mo = str(m).split("-")[:2]
            target_months.add((int(y), int(mo)))
        except (ValueError, TypeError):
            continue
    if target_months:
        logger.info("Targeted re-plan for brand %s — months=%s", brand_id, sorted(target_months))

    # Build cadence string from strategy so the LLM respects weekly post counts.
    # Try structured cadence data first, then fall back to extracting from strategy document.
    cadence = strategy.get("cadence", {})
    cadence_lines = []
    for ch in enabled_channels:
        ch_cadence = cadence.get(ch, {}) if isinstance(cadence, dict) else {}
        if isinstance(ch_cadence, dict):
            posts_per_week = ch_cadence.get("posts_per_week", ch_cadence.get("frequency", ""))
        elif isinstance(ch_cadence, (int, float)):
            posts_per_week = ch_cadence
        else:
            posts_per_week = str(ch_cadence) if ch_cadence else ""
        if posts_per_week:
            cadence_lines.append(f"- {ch}: {posts_per_week} posts per week")

    # If structured cadence is incomplete, extract from strategy document text
    if len(cadence_lines) < len(enabled_channels) and strategy_document:
        import re as _re
        for ch in enabled_channels:
            if any(ch in line for line in cadence_lines):
                continue  # Already have this channel
            # Search for patterns like "Instagram\n5 posts per week" or "instagram: 3 posts/week"
            pattern = _re.compile(
                rf"{ch}[:\s\n]*(\d+)\s*posts?\s*(?:per|/)\s*week",
                _re.IGNORECASE,
            )
            match = pattern.search(strategy_document)
            if match:
                cadence_lines.append(f"- {ch}: {match.group(1)} posts per week")
            else:
                cadence_lines.append(f"- {ch}: 3 posts per week")  # Safe default

    cadence_instruction = "\n".join(cadence_lines) if cadence_lines else "3 posts per week per channel."

    # Load real products for product-aware content planning. Keep the FULL
    # active catalog (no [:50] truncation) — each batch is shown a rotating
    # window of it (see _run_batch) so coverage sweeps the whole catalog over
    # the horizon instead of repeating only the first few products.
    products = await get_products(brand_id)
    all_product_summary = [
        {"name": p.get("name"), "sku": p.get("sku"), "vendor": p.get("vendor")}
        for p in products
        if p.get("name")
    ]
    _PRODUCT_WINDOW = 15  # products shown to the LLM per batch (fits the prompt budget)

    channels_str = ", ".join(enabled_channels)

    def _extract_month_strategy(month_name: str) -> str:
        """Extract the relevant month/quarter section from the strategy document.

        Searches for the month name in any header format (##, ###, **, bold, etc.)
        and captures everything until the next month header. Also captures the
        quarter section and channel strategy guidance.
        """
        if not strategy_document:
            return ""

        all_months = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]
        month_idx = next((i for i, m in enumerate(all_months) if m.lower() == month_name.lower()), -1)
        quarter = f"Q{(month_idx // 3) + 1}" if month_idx >= 0 else ""

        lines = strategy_document.split("\n")
        result_lines: list[str] = []
        capturing = False

        for line in lines:
            stripped = line.strip().lower()

            # Start capturing if line contains this month's name or quarter
            if not capturing:
                if month_name.lower() in stripped or (quarter and quarter.lower() in stripped and "strategy" in stripped):
                    capturing = True
                    result_lines.append(line)
                    continue
            else:
                # Stop when we hit a DIFFERENT month's header
                is_next_month = False
                for m in all_months:
                    if m.lower() == month_name.lower():
                        continue
                    if m.lower() in stripped and any(
                        stripped.startswith(p) for p in ("#", "**", "###")
                    ):
                        is_next_month = True
                        break
                # Also stop at next quarter header (unless it's our quarter)
                if not is_next_month and "q" in stripped and "strategy" in stripped:
                    for q in ["q1", "q2", "q3", "q4"]:
                        if q in stripped and q != quarter.lower():
                            is_next_month = True
                            break
                if is_next_month:
                    capturing = False
                    continue
                result_lines.append(line)

        extracted = "\n".join(result_lines).strip()

        # Also extract channel strategy section (posting frequency, best times)
        channel_section: list[str] = []
        capturing_channels = False
        for line in lines:
            stripped = line.strip().lower()
            if "channel strategy" in stripped or "publishing structure" in stripped or "posting frequency" in stripped:
                capturing_channels = True
                channel_section.append(line)
                continue
            if capturing_channels:
                if stripped.startswith("#") and "channel" not in stripped and "publishing" not in stripped:
                    break
                channel_section.append(line)

        channel_text = "\n".join(channel_section).strip()

        # Combine month section + channel guidance
        parts = []
        if extracted:
            parts.append(extracted)
        if channel_text:
            parts.append(f"\nCHANNEL STRATEGY & POSTING SCHEDULE:\n{channel_text}")

        if parts:
            return "\n\n".join(parts)

        # Fallback: return first 4000 chars (executive summary + overview)
        return strategy_document[:4000]

    # ── Build per-channel cadence lookup ──────────────────────────────
    # Primary source: structured cadence from strategy state (populated by plan_cadence node)
    # Fallback: regex extraction from strategy document text
    import re as _re

    channel_cadence: dict[str, int] = {}
    channel_best_days: dict[str, str] = {}
    channel_best_times: dict[str, str] = {}

    for ch in enabled_channels:
        posts = 3  # safe default
        best_days = ""
        best_times = ""

        # Try structured cadence first (from strategy state)
        ch_cad = cadence.get(ch, {}) if isinstance(cadence, dict) else {}
        if isinstance(ch_cad, dict):
            if ch_cad.get("posts_per_week"):
                posts = int(ch_cad["posts_per_week"])
            if ch_cad.get("best_days"):
                days = ch_cad["best_days"]
                best_days = ", ".join(days) if isinstance(days, list) else str(days)
            if ch_cad.get("best_times"):
                times = ch_cad["best_times"]
                best_times = ", ".join(times) if isinstance(times, list) else str(times)

        # Fallback: extract from strategy document text
        if posts == 3 and strategy_document:
            # Match "### Instagram\n- Weekly cadence: 5 posts per week" or "Instagram\n5 posts per week"
            patterns = [
                rf"###?\s*{ch}[\s\S]*?(?:weekly\s*cadence|cadence)[:\s]*(\d+)\s*posts",
                rf"###?\s*{ch}[\s\S]*?(\d+)\s*posts?\s*(?:per|/)\s*week",
                rf"{ch}\s*\n[^#]*?(\d+)\s*posts?\s*(?:per|/)\s*week",
            ]
            for pattern in patterns:
                m = _re.search(pattern, strategy_document, _re.IGNORECASE)
                if m:
                    posts = int(m.group(1))
                    break

        if not best_days and strategy_document:
            days_m = _re.search(rf"###?\s*{ch}[\s\S]*?best\s*days?[:\s]*([^\n]+)", strategy_document, _re.IGNORECASE)
            if days_m:
                best_days = days_m.group(1).strip()

        if not best_times and strategy_document:
            times_m = _re.search(rf"###?\s*{ch}[\s\S]*?best\s*times?[:\s]*([^\n]+)", strategy_document, _re.IGNORECASE)
            if times_m:
                best_times = times_m.group(1).strip()

        channel_cadence[ch] = posts
        if best_days:
            channel_best_days[ch] = best_days
        if best_times:
            channel_best_times[ch] = best_times

    logger.info("PROMPT_DEBUG channel_cadence: %s", channel_cadence)
    logger.info("PROMPT_DEBUG channel_best_days: %s", channel_best_days)
    logger.info("PROMPT_DEBUG channel_best_times: %s", channel_best_times)

    # ── Extract weekly pillar rotation from strategy ────────────────
    pillar_rotation = ""
    if strategy_document:
        rot_match = _re.search(
            r"(?:weekly\s*pillar\s*rotation|recommended\s*weekly.*rotation)[:\s]*\n((?:.*\n)*?)(?:\n\n|\Z)",
            strategy_document,
            _re.IGNORECASE,
        )
        if rot_match:
            pillar_rotation = rot_match.group(1).strip()

    # ── Generate per-channel per-week (parallel) ───────────────
    all_items: list[dict[str, Any]] = []
    batch_size_days = 7
    expected_total = 0
    channel_counts: dict[str, int] = {ch: 0 for ch in enabled_channels}

    # Pre-build all (batch_start, batch_end) windows for the full year
    batch_windows: list[tuple[datetime, datetime]] = []
    cur = start_date_dt
    while cur < end_date_dt:
        bend = min(cur + timedelta(days=batch_size_days), end_date_dt)
        batch_windows.append((cur, bend))
        cur = bend

    # Targeted re-plan: keep only windows overlapping a target month (a 7-day
    # window spans at most two months — check both ends).
    if target_months:
        batch_windows = [
            (s, e)
            for (s, e) in batch_windows
            if (s.year, s.month) in target_months
            or ((e - timedelta(days=1)).year, (e - timedelta(days=1)).month) in target_months
        ]

    for _ in batch_windows:
        for ch in enabled_channels:
            expected_total += channel_cadence.get(ch, 3)

    # Semaphore caps concurrent LLM calls — 8 at a time avoids rate-limit
    # spikes while keeping wall-clock time to ~5 min for a full year.
    _sem = asyncio.Semaphore(8)

    async def _run_batch(batch_idx: int, batch_start: datetime, batch_end: datetime, channel: str) -> list[dict]:
        async with _sem:
            b_start_str = batch_start.strftime("%Y-%m-%d")
            b_last_day = batch_end - timedelta(days=1)
            b_end_str = b_last_day.strftime("%Y-%m-%d")
            b_month = batch_start.strftime("%B")
            month_strategy = _extract_month_strategy(b_month)
            posts_needed = channel_cadence.get(channel, 3)
            best_days = channel_best_days.get(channel, "")
            best_times = channel_best_times.get(channel, "")

            # Rotating product window: each batch sees a different slice of the
            # catalog (advancing by batch_idx), wrapping around. Over all
            # week×channel batches this sweeps the full catalog, so the planner
            # isn't stuck recommending only the first products it ever saw.
            if all_product_summary:
                _n = len(all_product_summary)
                _start = (batch_idx * _PRODUCT_WINDOW) % _n
                batch_products = [
                    all_product_summary[(_start + k) % _n]
                    for k in range(min(_PRODUCT_WINDOW, _n))
                ]
            else:
                batch_products = []

            # Dedup from DB-existing items only (no cross-batch deps in parallel mode)
            ch_existing = [
                i for i in existing_items
                if (i.get("platform") or i.get("channel", "")) == channel
            ]
            dedup_lines = [
                f"{str(i.get('scheduled_at') or i.get('scheduled_date', ''))[:10]} | "
                f"{i.get('pillar', '')} | {i.get('theme') or i.get('title', '')} | "
                f"{i.get('weekly_sub_theme', '')}"
                for i in ch_existing[-30:]
            ]
            dedup = (
                f"ALREADY SCHEDULED {channel.upper()} CONTENT (do NOT repeat these):\n"
                + "\n".join(dedup_lines) + "\n\n"
            ) if dedup_lines else ""

            week_events = [
                ev for ev in events
                if ev.get("start") and (ev.get("end") or ev["start"]) >= b_start_str
                and ev["start"] <= b_end_str
            ]
            week_events_block = (
                _format_events_for_prompt(week_events)
                if week_events
                else "(no significant events this week — schedule regular content only)"
            )

            prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a content calendar planner. Write all content in English.\n\n"
                        f"Generate EXACTLY {posts_needed} posts for {channel.upper()} "
                        f"for the week of {b_start_str} through {b_end_str}.\n\n"
                        "IMPORTANT: You MUST return a JSON array with the items. "
                        "Do NOT return error messages, questions, or clarification requests. "
                        "Use the information provided and make reasonable assumptions for anything missing.\n\n"
                        f"POSTING SCHEDULE:\n"
                        f"- Posts this week: {posts_needed}\n"
                        f"- Best days: {best_days or 'spread evenly across the week'}\n"
                        f"- Best times: {best_times or '07:00, 13:00, 20:00'}\n"
                        f"- Assign each post a specific date and time from the best days/times\n\n"
                        + (f"WEEKLY PILLAR ROTATION:\n{pillar_rotation}\n\n" if pillar_rotation else "")
                        + "RULES:\n"
                        "- Each item MUST have a UNIQUE weekly_sub_theme\n"
                        "- Do NOT repeat any theme from the ALREADY SCHEDULED list\n"
                        + _ctype_rule
                        + "- Each content_brief must describe a DISTINCT topic\n\n"
                        "EVENT DATE RULES:\n"
                        "- If the strategy mentions a specific event with a date (e.g., 'World Cancer Day (Feb 4)'), "
                        "content referencing that event should ONLY be scheduled on the event date itself or the day before/after\n"
                        "- Do NOT spread event-specific content across the entire week or month\n"
                        "- Weeks that do not contain an event date should focus on the month's general theme, "
                        "pillar rotation, and educational content — NOT reference the event\n"
                        "- An event post replaces one of the week's regular posts on that specific day\n\n"
                        "Each item MUST include ALL fields: "
                        "campaign_name, scheduled_date (YYYY-MM-DD), "
                        "scheduled_time (HH:MM 24h format), "
                        f"platform (always \"{channel}\"), "
                        + _ctype_field
                        + "pillar, theme, weekly_sub_theme, target_audience, "
                        "content_brief (2-3 sentences), "
                        "product_name (from products list or null), "
                        "visual_direction (1 sentence), "
                        "cta_type (shop/learn/engage/share).\n"
                        "Return a JSON array."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{dedup}"
                        f"Campaigns:\n{sanitize_json_for_prompt(campaigns, max_length=2000)}\n\n"
                        f"SIGNIFICANT EVENTS THIS WEEK (schedule on the event date, do NOT invent others):\n"
                        f"{week_events_block}\n\n"
                        f"STRATEGY FOR {b_month.upper()} ({channel.upper()}):\n"
                        f"{sanitize_for_prompt(month_strategy, max_length=5000)}\n\n"
                        f"Available products:\n{sanitize_json_for_prompt(batch_products, max_length=1500)}"
                    ),
                },
            ]

            logger.info(
                "PROMPT_DEBUG batch=%d channel=%s week=%s→%s posts_needed=%d",
                batch_idx, channel, b_start_str, b_end_str, posts_needed,
            )

            try:
                result = await chat_completion(prompt, temperature=0.5, max_tokens=4096)
                logger.info(
                    "RESPONSE_DEBUG batch=%d channel=%s response_chars=%d preview=%s",
                    batch_idx, channel, len(result), result[:300],
                )

                batch_items = parse_llm_json(result, fallback=[])
                if isinstance(batch_items, dict):
                    if "scheduled_date" in batch_items or "platform" in batch_items:
                        batch_items = [batch_items]
                    else:
                        batch_items = next(
                            (v for v in batch_items.values() if isinstance(v, list)), []
                        )

                for item in batch_items:
                    item["platform"] = channel

                items_got = len(batch_items)

                if items_got < posts_needed and items_got > 0:
                    missing = posts_needed - items_got
                    logger.warning(
                        "RETRY batch=%d channel=%s: got %d/%d, retrying for %d more",
                        batch_idx, channel, items_got, posts_needed, missing,
                    )
                    used_dates = [i.get("scheduled_date", "") for i in batch_items]
                    retry_prompt = [
                        {
                            "role": "system",
                            "content": (
                                f"Generate EXACTLY {missing} more {channel.upper()} posts "
                                f"for {b_start_str} through {b_end_str}. "
                                f"Do NOT use these dates (already taken): {', '.join(used_dates)}. "
                                f"Best days: {best_days or 'any remaining day'}. "
                                f"Best times: {best_times or '07:00, 13:00, 20:00'}. "
                                "Return a JSON array. Same fields as before."
                            ),
                        },
                        {"role": "user", "content": prompt[1]["content"]},
                    ]
                    try:
                        retry_result = await chat_completion(retry_prompt, temperature=0.5, max_tokens=4096)
                        retry_items = parse_llm_json(retry_result, fallback=[])
                        if isinstance(retry_items, dict):
                            retry_items = next((v for v in retry_items.values() if isinstance(v, list)), [])
                        for item in retry_items:
                            item["platform"] = channel
                        batch_items.extend(retry_items)
                        logger.info("RETRY got %d more items for %s", len(retry_items), channel)
                    except Exception as retry_exc:
                        logger.warning("RETRY failed for %s: %s", channel, retry_exc)

                if not batch_items:
                    logger.warning(
                        "BATCH_ZERO batch=%d channel=%s produced 0 items — response: %s",
                        batch_idx, channel, result[:500],
                    )
                else:
                    logger.info("BATCH_OK batch=%d channel=%s produced %d items", batch_idx, channel, len(batch_items))

                return batch_items

            except Exception as batch_exc:
                logger.error("BATCH_FAIL batch=%d channel=%s: %s", batch_idx, channel, batch_exc)
                return []

    # Launch all batch×channel tasks concurrently
    tasks = [
        _run_batch(
            idx * len(enabled_channels) + ch_idx,
            bs, be, ch,
        )
        for idx, (bs, be) in enumerate(batch_windows)
        for ch_idx, ch in enumerate(enabled_channels)
    ]
    batch_results = await asyncio.gather(*tasks)
    for r in batch_results:
        all_items.extend(r)
        for item in r:
            ch = item.get("platform", "")
            if ch in channel_counts:
                channel_counts[ch] += 1

    # ── Batch summary ─────────────────────────────────────────────
    logger.info(
        "BATCH_SUMMARY total=%d expected=%d (%.0f%%). Per channel: %s",
        len(all_items),
        expected_total,
        (len(all_items) / expected_total * 100) if expected_total else 0,
        ", ".join(f"{ch}={cnt}" for ch, cnt in channel_counts.items()),
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
    # Store calendar items only up to the planning horizon (scope_weeks),
    # mirroring what generate_calendar_items emitted above. Items beyond the
    # horizon get skipped by store_calendar_items via max_date.
    now = datetime.now(timezone.utc)
    scope_weeks = max(1, int(state.get("scope_weeks", 52) or 52))
    max_date = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(weeks=scope_weeks, days=1)  # +1 day cushion for end-of-window items
        - timedelta(seconds=1)
    )

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
        # Combine scheduled_date + scheduled_time into a full datetime
        # validated.scheduled_date is a string like "2026-01-01"
        scheduled_time_str = item.get("scheduled_time", "")
        try:
            date_str = str(validated.scheduled_date)[:10]
            if scheduled_time_str:
                time_str = scheduled_time_str.strip()[:5]  # "18:00"
                scheduled_dt = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                ).replace(tzinfo=timezone.utc)
            else:
                scheduled_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            # Fallback: use the raw string (store_calendar_items handles parsing)
            scheduled_dt = validated.scheduled_date

        db_items.append(
            {
                "brand_id": brand_id,
                "campaign_id": None,
                "title": validated.theme or validated.campaign_name or "",
                "description": validated.content_brief or item.get("brief", ""),
                "channel": validated.platform,
                "scheduled_at": scheduled_dt,
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

    # Targeted re-plan: drop any stray item that landed outside the target
    # months (e.g. a 7-day batch window straddling a month boundary).
    if target_months:
        def _item_ym(it):
            sa = it.get("scheduled_at")
            if isinstance(sa, datetime):
                return (sa.year, sa.month)
            try:
                y, mo = str(sa)[:7].split("-")
                return (int(y), int(mo))
            except (ValueError, TypeError):
                return None
        db_items = [it for it in db_items if _item_ym(it) in target_months]

    # Purge stale 'planned' items so reruns don't stack duplicates. Non-'planned'
    # rows are preserved — once an item moves into generation or publishing the
    # user has effectively taken ownership. Targeted re-plan purges ONLY the
    # changed months; full re-plan purges the whole year-to-horizon window.
    try:
        if target_months:
            deleted = 0
            for (y, mo) in sorted(target_months):
                m_start = datetime(y, mo, 1, tzinfo=timezone.utc)
                if mo == 12:
                    m_end = datetime(y + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
                else:
                    m_end = datetime(y, mo + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
                deleted += await delete_planned_calendar_items(brand_id, m_start, m_end)
        else:
            planning_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
            deleted = await delete_planned_calendar_items(
                brand_id, planning_start, max_date
            )
        if deleted:
            logger.info(
                "Purged %d stale planned calendar items for brand %s before insert",
                deleted,
                brand_id,
            )
    except Exception as exc:
        logger.warning(
            "Failed to purge stale planned items for brand %s (continuing): %s",
            brand_id,
            exc,
        )

    ids = await store_calendar_items(
        db_items, max_date=max_date, enabled_channels=enabled_channels
    )
    logger.info("Stored %d calendar items for brand %s", len(ids), brand_id)

    # Plain-English summary of the marketing plan (planning report) for
    # non-marketing readers (IT/finance). Best-effort, empty on failure.
    planning_summary_plain = await generate_executive_summary_plain(
        "planning",
        {
            "campaigns": state.get("campaigns", []),
            "calendar_items_count": len(ids),
            "enabled_channels": enabled_channels,
        },
    )

    # Persist year-long strategy document as an agent_run artifact
    if strategy_document:
        try:
            # Separate plain-English summary for the content-calendar report.
            calendar_summary_plain = await generate_executive_summary_plain(
                "content_calendar",
                {
                    "strategy_document": strategy_document[:8000],
                    "enabled_channels": enabled_channels,
                },
            )
            cc_run_id = await store_strategy(
                brand_id,
                {
                    "type": "content_calendar_strategy",
                    "strategy_document": strategy_document,
                    "enabled_channels": enabled_channels,
                    "executive_summary_plain": calendar_summary_plain,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                agent_type="content_calendar",
            )
            logger.info("Stored year-long strategy document for brand %s", brand_id)

            # Notify brand owner that the Content Calendar Strategy is ready.
            # (The worker hook covers research/strategy/planning, but not
            # content_calendar — it's stored inline here, never traverses
            # complete_agent_run via the worker.)
            try:
                from shared.tools.database import create_notification, execute_query

                rows = await execute_query(
                    "SELECT name, created_by FROM brands WHERE id = :bid",
                    {"bid": brand_id},
                )
                if rows and rows[0].get("created_by"):
                    await create_notification(
                        user_id=str(rows[0]["created_by"]),
                        notification_type="context_ready",
                        title=(
                            f"Content Calendar Strategy ready — "
                            f"{rows[0].get('name') or 'your brand'}"
                        ),
                        body="Click to review and approve.",
                        reference_type="agent_run",
                        reference_id=str(cc_run_id) if cc_run_id else None,
                    )
            except Exception as notif_exc:
                logger.debug("content_calendar notification skipped: %s", notif_exc)
        except Exception:
            logger.exception("Failed to store strategy document for brand %s", brand_id)

    return {
        "status": "completed",
        "calendar_item_ids": ids,
        "executive_summary_plain": planning_summary_plain,
    }
