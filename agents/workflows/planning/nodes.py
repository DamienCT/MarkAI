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

    # Calendar items are scoped to the next `scope_weeks` weeks (default 2)
    # so a planning run finishes in ~2 min rather than ~36 min. The strategy
    # document the LLM still references can describe a full year — we just
    # don't materialise calendar_items beyond the configured horizon.
    now = datetime.now(timezone.utc)
    scope_weeks = max(1, int(state.get("scope_weeks", 2) or 2))
    start_date_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_dt = start_date_dt + timedelta(weeks=scope_weeks)

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

    # Load real products for product-aware content planning
    products = await get_products(brand_id)
    product_summary = [
        {"name": p.get("name"), "sku": p.get("sku"), "vendor": p.get("vendor")}
        for p in products[:50]
    ]

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

    # ── Generate per-channel per-week ──────────────────────────────
    all_items: list[dict[str, Any]] = []
    batch_size_days = 7
    current_dt = start_date_dt
    batch_num = 0
    # Track expected vs actual for summary
    expected_total = 0
    channel_counts: dict[str, int] = {ch: 0 for ch in enabled_channels}

    def _build_dedup_context(channel: str) -> str:
        """Build dedup context filtered to this channel from existing + generated items."""
        combined = list(existing_items) + all_items
        channel_items = [i for i in combined if (i.get("platform") or i.get("channel", "")) == channel]
        if not channel_items:
            return ""
        lines = []
        for i in channel_items[-30:]:
            date_val = i.get("scheduled_at") or i.get("scheduled_date", "")
            date_str = str(date_val)[:10] if date_val else ""
            theme = i.get("theme") or i.get("title", "")
            sub = i.get("weekly_sub_theme", "")
            pillar = i.get("pillar", "")
            lines.append(f"{date_str} | {pillar} | {theme} | {sub}")
        summary = "\n".join(lines)
        return (
            f"ALREADY SCHEDULED {channel.upper()} CONTENT (do NOT repeat these):\n"
            f"{summary}\n\n"
        )

    while current_dt < end_date_dt:
        batch_end = min(current_dt + timedelta(days=batch_size_days), end_date_dt)
        batch_start_str = current_dt.strftime("%Y-%m-%d")
        batch_last_day = (batch_end - timedelta(days=1))
        batch_end_str = batch_last_day.strftime("%Y-%m-%d")
        batch_month_name = current_dt.strftime("%B")
        month_strategy = _extract_month_strategy(batch_month_name)

        # Filter events that overlap this week-batch so the LLM schedules
        # on the exact event date rather than scattering across the month.
        week_events: list[dict[str, Any]] = []
        for ev in events:
            ev_start = ev.get("start")
            if not ev_start:
                continue
            ev_end = ev.get("end") or ev_start
            if ev_end >= batch_start_str and ev_start <= batch_end_str:
                week_events.append(ev)
        week_events_block = (
            _format_events_for_prompt(week_events)
            if week_events
            else "(no significant events this week — schedule regular content only)"
        )

        # Generate for EACH channel separately
        for channel in enabled_channels:
            batch_num += 1
            posts_needed = channel_cadence.get(channel, 3)
            expected_total += posts_needed
            best_days = channel_best_days.get(channel, "")
            best_times = channel_best_times.get(channel, "")
            dedup = _build_dedup_context(channel)

            prompt = [
                {
                    "role": "system",
                    "content": (
                        "You are a content calendar planner. Write all content in English.\n\n"
                        f"Generate EXACTLY {posts_needed} posts for {channel.upper()} "
                        f"for the week of {batch_start_str} through {batch_end_str}.\n\n"
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
                        "- Vary content types (mix post, reel, carousel, story)\n"
                        "- Each content_brief must describe a DISTINCT topic\n\n"
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
                        "content_type (post/reel/story/carousel), "
                        "pillar, theme, weekly_sub_theme, target_audience, "
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
                        f"STRATEGY FOR {batch_month_name.upper()} ({channel.upper()}):\n"
                        f"{sanitize_for_prompt(month_strategy, max_length=5000)}\n\n"
                        f"Available products:\n{sanitize_json_for_prompt(product_summary, max_length=1500)}"
                    ),
                },
            ]

            # Debug log: what context is the LLM getting?
            logger.info(
                "PROMPT_DEBUG batch=%d channel=%s week=%s→%s posts_needed=%d best_days=%s best_times=%s strategy_chars=%d",
                batch_num, channel, batch_start_str, batch_end_str,
                posts_needed, best_days[:50] if best_days else "none",
                best_times[:50] if best_times else "none", len(month_strategy),
            )

            try:
                result = await chat_completion(
                    prompt,
                    temperature=0.5,
                    max_tokens=4096,
                )

                # Debug log: what did the LLM return?
                logger.info(
                    "RESPONSE_DEBUG batch=%d channel=%s response_chars=%d preview=%s",
                    batch_num, channel, len(result), result[:300],
                )

                batch_items = parse_llm_json(result, fallback=[])
                if isinstance(batch_items, dict):
                    if "scheduled_date" in batch_items or "platform" in batch_items:
                        batch_items = [batch_items]
                    else:
                        batch_items = next(
                            (v for v in batch_items.values() if isinstance(v, list)), []
                        )

                # Force correct platform on all items
                for item in batch_items:
                    item["platform"] = channel

                items_got = len(batch_items)

                # ── Retry if under-producing ──────────────────────
                if items_got < posts_needed and items_got > 0:
                    missing = posts_needed - items_got
                    logger.warning(
                        "RETRY batch=%d channel=%s: got %d/%d, retrying for %d more",
                        batch_num, channel, items_got, posts_needed, missing,
                    )
                    # Build list of dates already used
                    used_dates = [i.get("scheduled_date", "") for i in batch_items]
                    retry_prompt = [
                        {
                            "role": "system",
                            "content": (
                                f"Generate EXACTLY {missing} more {channel.upper()} posts "
                                f"for {batch_start_str} through {batch_end_str}. "
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
                        batch_num, channel, result[:500],
                    )
                else:
                    channel_counts[channel] = channel_counts.get(channel, 0) + len(batch_items)
                    logger.info(
                        "BATCH_OK batch=%d channel=%s produced %d items",
                        batch_num, channel, len(batch_items),
                    )

                all_items.extend(batch_items)

            except Exception as batch_exc:
                logger.error("BATCH_FAIL batch=%d channel=%s: %s", batch_num, channel, batch_exc)

        current_dt = batch_end

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
    scope_weeks = max(1, int(state.get("scope_weeks", 2) or 2))
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

    # Purge stale 'planned' items from prior planning runs within the same
    # window so reruns don't stack duplicates on top. Non-'planned' rows are
    # preserved — once an item moves into generation or publishing the user
    # has effectively taken ownership.
    planning_start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    try:
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

    # Persist year-long strategy document as an agent_run artifact
    if strategy_document:
        try:
            await store_strategy(
                brand_id,
                {
                    "type": "content_calendar_strategy",
                    "strategy_document": strategy_document,
                    "enabled_channels": enabled_channels,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                agent_type="content_calendar",
            )
            logger.info("Stored year-long strategy document for brand %s", brand_id)
        except Exception:
            logger.exception("Failed to store strategy document for brand %s", brand_id)

    return {"status": "completed", "calendar_item_ids": ids}
