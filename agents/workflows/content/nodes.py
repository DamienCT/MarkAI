"""Content generation workflow nodes — real LLM, DB, and image sourcing calls."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from shared.llm import chat_completion, generate_image, parse_llm_json
from shared.prompt_enhancer import enhance_image_prompt as enhance_image_prompt_fn
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.database import (
    build_brand_intelligence,
    execute_update,
    get_calendar_item,
    store_content,
    update_agent_run_step,
)
from shared.tools.storage import (
    async_upload_file,
    async_ensure_bucket,
    async_download_file,
)
from shared.image_processing import (
    render_logo_png,
    overlay_logo_and_text,
    scale_for_logo_variant,
    generate_mockup,
    analyze_logo_region_brightness,
    select_logo_variant,
    resize_preserve_aspect,
    aspect_hint_for_size,
)

from pydantic import BaseModel, field_validator

from workflows.content.state import ContentState

logger = logging.getLogger(__name__)

# Step tracking: maps node key to (index, key) for progress reporting
CONTENT_PIPELINE_STEPS = [
    "load_context",
    "generate_hook",
    "generate_caption",
    "generate_hashtags",
    "source_product_image",
    "enhance_image_prompt",
    "generate_background",
    "apply_branding",
    "adapt_platforms",
    "generate_mockups",
    "store_content",
]
_STEP_INDEX = {key: idx for idx, key in enumerate(CONTENT_PIPELINE_STEPS)}


class ContentRecordValidator(BaseModel):
    """Validates generated content fields before DB insert."""

    brand_id: str
    calendar_item_id: str
    hook: str = ""
    caption: str = ""
    hashtags: str = "[]"
    cta: str = ""
    product_image_url: str | None = None
    generated_image_url: str | None = None
    platform_adaptations: str = "{}"
    metadata: dict = {}

    @field_validator("caption")
    @classmethod
    def caption_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("caption must not be empty")
        return v

    model_config = {"extra": "allow"}


def _extract_month_section(strategy_doc: str, month_name: str) -> str:
    """Extract the section for a specific month from the strategy document."""
    if not strategy_doc or not month_name:
        return ""
    # Try to find a section header containing the month name
    pattern = re.compile(
        rf"(#{{1,3}}\s*.*{re.escape(month_name)}.*?)(?=#{{1,3}}\s|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(strategy_doc)
    if match:
        return match.group(1).strip()[:5000]
    # Fallback: search for the month name and grab surrounding context
    idx = strategy_doc.lower().find(month_name.lower())
    if idx >= 0:
        start = max(0, idx - 200)
        end = min(len(strategy_doc), idx + 4800)
        return strategy_doc[start:end].strip()
    return ""


def _find_product(products: list[dict], calendar_item: dict) -> dict:
    """Match a product from the brand's product list to the calendar item."""
    product_name = calendar_item.get("product_name") or calendar_item.get("title", "")
    product_ids = calendar_item.get("product_ids") or []

    if not product_name and not product_ids:
        return {}

    # Match by product_ids first
    if product_ids:
        pid = product_ids[0] if isinstance(product_ids, list) else product_ids
        for p in products:
            if str(p.get("id", "")) == str(pid):
                return p

    # Fallback: fuzzy match by name
    if product_name:
        name_lower = product_name.lower()
        for p in products:
            if name_lower in (p.get("name") or "").lower():
                return p

    return {}


def _resolve_sub_brand(product: dict, brand: dict) -> str:
    """Resolve the speaking sub-brand for a post.

    For distributor brands (one parent brand selling products under multiple
    sub-brands), the product's vendor_name is the sub-brand that should hold
    the consumer voice. For single-identity brands the vendor_name typically
    matches the brand itself, in which case we just return brand.name.

    Returns brand.name as a safe default whenever no usable vendor_name exists.
    """
    brand_name = (brand.get("name") or "").strip()
    if not product:
        return brand_name
    vendor = (product.get("vendor_name") or "").strip()
    if vendor and vendor.lower() not in brand_name.lower():
        return vendor
    return brand_name


# Channels that take the B2B voice. Everything else is consumer-facing.
_B2B_CHANNELS = frozenset({"linkedin"})


def _voice_mode_for_channel(channel: str) -> str:
    return "b2b" if (channel or "").lower() in _B2B_CHANNELS else "b2c"


def _build_voice_block(voice_mode: str, sub_brand: str, brand_name: str) -> str:
    """Per-channel voice directive injected at the top of caption/hook prompts.

    B2C posts speak AS the featured sub-brand (the product's vendor); any
    distributor language is banned. B2B posts speak AS the parent brand
    itself, with the sub-brand cited as proof of catalogue quality, not as
    the narrator.
    """
    speaker = sub_brand or brand_name
    if voice_mode == "b2c":
        return (
            f"VOICE — write in first person AS '{speaker}'. The narrator IS "
            f"this brand speaking directly to the home consumer. Warm, "
            f"sensory, gourmand, accessible. NEVER mention the distributor, "
            f"supply chain, stock levels, margins, or any B2B language. "
            f"Forbidden phrases: 'good supplier', 'in stock', 'great margins', "
            f"'we distribute', 'reliable partner', 'wholesale', 'available "
            f"through'. Sell a moment, not a SKU."
        )
    return (
        f"VOICE — write in first person AS '{brand_name}' (the B2B "
        f"distributor / supply partner). Professional, factual, focused on "
        f"supply reliability, traceability, and quality consistency. The "
        f"featured sub-brand ('{sub_brand}') is referenced as proof of "
        f"catalogue quality, not as the narrating voice. B2B vocabulary "
        f"('reliable supply', 'HORECA', 'cold chain', 'catalogue', 'SKU') is "
        f"welcome here."
    )


# Default per-channel caption settings used when neither the channel
# override nor the brand-level guidelines specify a value. Tuned for
# scroll-stopping length per platform; brands can override any field via
# brand_guidelines.channels.<channel>.caption.<field>.
_DEFAULT_CHANNEL_CAPTION: dict[str, dict[str, Any]] = {
    "instagram":    {"max_words": 60,  "hashtags_min": 5, "hashtags_max": 10, "emoji": "moderate"},
    "facebook":     {"max_words": 90,  "hashtags_min": 3, "hashtags_max": 5,  "emoji": "minimal"},
    "linkedin":     {"max_words": 120, "hashtags_min": 3, "hashtags_max": 3,  "emoji": "none"},
    "tiktok":       {"max_words": 30,  "hashtags_min": 3, "hashtags_max": 5,  "emoji": "heavy"},
    "x":            {"max_words": 35,  "hashtags_min": 2, "hashtags_max": 3,  "emoji": "minimal"},
    "website_blog": {"max_words": 800, "hashtags_min": 0, "hashtags_max": 0,  "emoji": "none"},
    "teams":        {"max_words": 80,  "hashtags_min": 0, "hashtags_max": 0,  "emoji": "none"},
}


def _coerce_guidelines(brand: dict) -> dict:
    """brand_guidelines may arrive as JSON string; normalize to dict."""
    guidelines = brand.get("brand_guidelines") or {}
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except (json.JSONDecodeError, TypeError):
            guidelines = {}
    return guidelines if isinstance(guidelines, dict) else {}


def _effective_caption_settings(brand: dict, channel: str) -> dict[str, Any]:
    """Resolve effective caption settings via layered read.

    Layering order, per field:
      1. brand_guidelines.channels.<channel>.caption.<field>   (per-channel override)
      2. brand_guidelines.<field> / brand.<field>              (brand global)
      3. _DEFAULT_CHANNEL_CAPTION[<channel>].<field>           (system default)
    """
    channel = (channel or "").lower()
    guidelines = _coerce_guidelines(brand)
    channels_cfg = guidelines.get("channels") or {}
    channel_cfg = channels_cfg.get(channel) if isinstance(channels_cfg, dict) else {}
    channel_caption = (channel_cfg or {}).get("caption") or {}
    defaults = _DEFAULT_CHANNEL_CAPTION.get(channel) or _DEFAULT_CHANNEL_CAPTION["instagram"]

    hashtags_count = channel_caption.get("hashtags_count")
    if isinstance(hashtags_count, list) and len(hashtags_count) == 2:
        ht_min, ht_max = hashtags_count
    else:
        ht_min, ht_max = defaults["hashtags_min"], defaults["hashtags_max"]

    return {
        "max_words":          channel_caption.get("max_words") or defaults["max_words"],
        "hook_format":        channel_caption.get("hook_format") or "",
        "tone":               channel_caption.get("tone_override") or brand.get("tone_of_voice") or "",
        "style":              channel_caption.get("style_override") or guidelines.get("voice_style") or "",
        "emoji":              channel_caption.get("emoji_override") or guidelines.get("emoji_usage") or defaults["emoji"],
        "hashtags_min":       ht_min,
        "hashtags_max":       ht_max,
        "hashtag_strategy":   guidelines.get("hashtag_strategy") or "",
        "must_name_product":  bool(channel_caption.get("must_name_product", False)),
        "structure_template": channel_caption.get("structure_template") or "",
        "caption_brief":      channel_caption.get("caption_brief") or "",
        "dos":                guidelines.get("dos") or [],
        "donts":              guidelines.get("donts") or [],
    }


def _build_brand_bible_block(brand: dict, settings: dict) -> str:
    """Render brand description + voice rules as a verbatim prompt block.

    Lifted from brand fields the user fills via the UI; emitted only if
    populated, so brands with empty profiles fall back to existing prompt
    behavior.
    """
    parts = []
    description = (brand.get("description") or "").strip()
    if description:
        parts.append(
            "BRAND BIBLE (verbatim, non-negotiable):\n"
            f"{sanitize_for_prompt(description, max_length=4000)}"
        )
    if settings.get("tone"):
        parts.append(f"TONE: {sanitize_for_prompt(settings['tone'])}")
    if settings.get("style"):
        parts.append(f"STYLE: {sanitize_for_prompt(settings['style'])}")
    if settings.get("emoji"):
        parts.append(f"EMOJI USAGE: {sanitize_for_prompt(settings['emoji'])}")
    if settings.get("hashtag_strategy"):
        parts.append(
            f"HASHTAG STRATEGY: {sanitize_for_prompt(settings['hashtag_strategy'])}"
        )
    dos = [d for d in (settings.get("dos") or []) if d]
    if dos:
        dos_lines = "\n".join(f"  - {sanitize_for_prompt(str(d))}" for d in dos)
        parts.append(f"MUST FOLLOW:\n{dos_lines}")
    donts = [d for d in (settings.get("donts") or []) if d]
    if donts:
        donts_lines = "\n".join(f"  - {sanitize_for_prompt(str(d))}" for d in donts)
        parts.append(f"MUST NEVER DO:\n{donts_lines}")
    if settings.get("caption_brief"):
        parts.append(
            "CHANNEL OVERRIDE BRIEF (this channel only, overrides global tone):\n"
            f"{sanitize_for_prompt(settings['caption_brief'], max_length=2000)}"
        )
    return "\n\n".join(parts)


def _build_channel_constraints_block(settings: dict, channel: str) -> str:
    """Channel-specific hard constraints for the LLM."""
    lines = [
        f"CHANNEL: {channel or 'instagram'}",
        f"MAX WORDS: {settings['max_words']} (HARD LIMIT — never exceed)",
        f"HASHTAGS: between {settings['hashtags_min']} and {settings['hashtags_max']}",
    ]
    if settings.get("hook_format"):
        lines.append(f"HOOK FORMAT: {sanitize_for_prompt(settings['hook_format'])}")
    if settings.get("structure_template"):
        lines.append(
            f"STRUCTURE TEMPLATE: {sanitize_for_prompt(settings['structure_template'])}"
        )
    if settings.get("must_name_product"):
        lines.append("MUST mention the product name explicitly in the caption.")
    return "\n".join(lines)


async def load_context(state: ContentState) -> dict[str, Any]:
    """Load full brand intelligence, calendar item, and all enriched context."""
    await update_agent_run_step(state.get("run_id", ""), "load_context", _STEP_INDEX["load_context"])
    brand_id = state["brand_id"]
    item_id = state["calendar_item_id"]

    # Load the full intelligence package
    intel = await build_brand_intelligence(brand_id)
    calendar_item = await get_calendar_item(item_id)

    if not intel.get("brand"):
        return {
            "errors": [*(state.get("errors") or []), "Brand not found"],
            "status": "failed",
        }
    if not calendar_item:
        return {
            "errors": [*(state.get("errors") or []), "Calendar item not found"],
            "status": "failed",
        }

    brief = (
        calendar_item.get("content_brief")
        or calendar_item.get("description")
        or ""
    ).strip()
    if not brief:
        return {
            "errors": [
                *(state.get("errors") or []),
                "Empty brief — refusing to hallucinate content",
            ],
            "status": "failed",
        }

    # Transition calendar item status to 'working'
    await execute_update(
        "UPDATE calendar_items SET status = 'working' WHERE id = :id AND status = 'queued'",
        {"id": item_id},
    )

    # Find the relevant pillar, audience, and monthly theme for THIS post
    pillar_name = calendar_item.get("pillar", "")
    audience_name = calendar_item.get("target_audience", "")

    # Strategy stores pillars as dicts ({"name": "..."}) or plain strings
    strategy_pillars = intel.get("strategy", {}).get(
        "content_pillars", []
    ) or intel.get("strategy", {}).get("pillars", [])
    if not isinstance(strategy_pillars, list):
        strategy_pillars = []

    def _pillar_name(p: Any) -> str:
        if isinstance(p, dict):
            return str(p.get("name", ""))
        return str(p)

    relevant_pillar = next(
        (
            p
            for p in strategy_pillars
            if _pillar_name(p).lower() == (pillar_name or "").lower()
        ),
        {},
    )
    # Normalize: if pillar is a string, wrap it so downstream code can use .get()
    if isinstance(relevant_pillar, str):
        relevant_pillar = {"name": relevant_pillar}

    # Same for audiences — may be dicts or strings
    research_personas = intel.get("research", {}).get("personas", [])
    if not isinstance(research_personas, list):
        research_personas = []

    def _persona_name(a: Any) -> str:
        if isinstance(a, dict):
            return str(a.get("name", ""))
        return str(a)

    relevant_audience = next(
        (
            a
            for a in research_personas
            if (audience_name or "").lower() in _persona_name(a).lower()
        ),
        {},
    )
    if isinstance(relevant_audience, str):
        relevant_audience = {"name": relevant_audience}

    # Extract current month's strategy document section
    strategy_doc = intel.get("planning", {}).get("strategy_document", "")
    current_month = datetime.now().strftime("%B")
    month_section = _extract_month_section(strategy_doc, current_month)

    # Match product for this calendar item
    product = _find_product(
        intel.get("brand", {}).get("products", []),
        calendar_item,
    )

    # Resolve the speaking sub-brand from product.vendor_name; falls back
    # to brand.name for single-identity brands.
    sub_brand = _resolve_sub_brand(product, intel.get("brand", {}))

    return {
        "brand": intel["brand"],
        "calendar_item": calendar_item,
        "strategy": intel.get("strategy", {}),
        "positioning": intel.get("strategy", {}).get("positioning", {}),
        "relevant_pillar": relevant_pillar,
        "relevant_audience": relevant_audience,
        "month_context": month_section,
        "recent_posts": intel.get("recent_posts", []),
        "top_performing": intel.get("top_performing", []),
        "product": product,
        "sub_brand": sub_brand,
    }


async def generate_hook(state: ContentState) -> dict[str, Any]:
    """Generate an attention-grabbing hook via LLM."""
    await update_agent_run_step(state.get("run_id", ""), "generate_hook", _STEP_INDEX["generate_hook"])
    try:
        brand = state.get("brand", {})
        item = state.get("calendar_item", {})
        positioning = state.get("positioning", {})
        relevant_pillar = state.get("relevant_pillar", {})
        relevant_audience = state.get("relevant_audience", {})
        product = state.get("product", {})
        recent_posts = state.get("recent_posts", [])
        top_performing = state.get("top_performing", [])

        channel = (item.get("channel", "") or "").lower()
        voice_mode = _voice_mode_for_channel(channel)
        sub_brand = state.get("sub_brand") or brand.get("name", "")
        voice_block = _build_voice_block(voice_mode, sub_brand, brand.get("name", ""))

        # Layered caption settings + verbatim brand bible from the brand record
        settings = _effective_caption_settings(brand, channel)
        brand_bible_block = _build_brand_bible_block(brand, settings)
        hook_format_directive = (
            f"HOOK FORMAT: {sanitize_for_prompt(settings['hook_format'])}\n\n"
            if settings.get("hook_format")
            else ""
        )

        # Build recent hooks to avoid
        recent_hooks = (
            "\n".join(
                f"- {sanitize_for_prompt(str(p.get('title', ''))[:60])}"
                for p in recent_posts[:10]
                if p.get("title")
            )
            or "None available"
        )

        # Build top performing hooks to learn from
        top_hooks = (
            "\n".join(
                f"- {sanitize_for_prompt(str(p.get('caption_snippet', ''))[:60])} "
                f"(engagement: {p.get('engagement_rate', 0):.1%})"
                for p in top_performing[:5]
                if p.get("caption_snippet")
            )
            or "None available"
        )

        # Audience pain points
        pain_points = ", ".join(relevant_audience.get("pain_points", [])) or "N/A"
        content_prefs = relevant_audience.get("content_preferences", {})
        tone_pref = (
            content_prefs.get("tone", "") if isinstance(content_prefs, dict) else ""
        )

        brief_text = sanitize_for_prompt(
            item.get("content_brief") or item.get("description") or ""
        )

        bible_section = f"{brand_bible_block}\n\n" if brand_bible_block else ""
        prompt = [
            {
                "role": "system",
                "content": (
                    f"{voice_block}\n\n"
                    f"{bible_section}"
                    f"{hook_format_directive}"
                    "You write short, scroll-stopping hooks for social posts. "
                    "Output a single line under 8 words and 50 characters.\n\n"
                    "PRIMARY RULE: The user BRIEF tells you what this post is "
                    "ABOUT. Stay on that topic. The brand voice tells you HOW "
                    "to sound, not WHAT to talk about. If the brief and brand "
                    "positioning disagree on topic, the brief wins.\n\n"
                    "Sound like a real person wrote it. Specifically:\n"
                    "- No em dashes between clauses\n"
                    "- No 'it's not just X, it's Y' framing\n"
                    "- No tricolons (three parallel adjectives)\n"
                    "- No hashtags (#anything). Hashtags belong to a separate "
                    "field handled by the publisher.\n"
                    "- Avoid these words: elevate, unlock, discover, harness, "
                    "leverage, transform, navigate, delve, dive, embark, "
                    "journey, curated, bespoke, seamless, holistic, "
                    "game-changer, in today's world\n"
                    "- Concrete and specific, not vague-aspirational\n"
                    "Return ONLY the hook text. No quotes, no labels."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"WHAT TO WRITE ABOUT (primary intent — never override):\n"
                    f"{brief_text or '(no brief provided — use theme as fallback)'}\n\n"
                    f"THIS POST:\n"
                    f"  Platform: {sanitize_for_prompt(item.get('channel', ''))}\n"
                    f"  Theme: {sanitize_for_prompt(item.get('theme', ''))}\n"
                    f"  Sub-theme: {sanitize_for_prompt(item.get('weekly_sub_theme', ''))}\n"
                    f"  Pillar: {sanitize_for_prompt(relevant_pillar.get('name', ''))}\n\n"
                    f"BRAND TONE REFERENCE (voice only, NOT topic):\n"
                    f"  Brand: {sanitize_for_prompt(brand.get('name', ''))}\n"
                    f"  Voice: {sanitize_for_prompt(str(positioning.get('brand_voice', '')))}\n"
                    f"  Audience: {sanitize_for_prompt(relevant_audience.get('name', ''))} — "
                    f"{sanitize_for_prompt(tone_pref)}\n"
                    f"  Audience cares about: {sanitize_for_prompt(pain_points)}\n\n"
                    f"PRODUCT (mention only if the brief is product-related): "
                    f"{sanitize_for_prompt(product.get('name', 'N/A'))}\n\n"
                    f"DO NOT REUSE these recent openings:\n{recent_hooks}\n\n"
                    f"For style cues, hooks that performed well historically:\n{top_hooks}"
                ),
            },
        ]
        hook = await chat_completion(prompt, temperature=0.8, max_tokens=256)
        return {"hook": hook.strip().strip('"')}
    except Exception as exc:
        logger.error("generate_hook failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"generate_hook failed: {exc}"],
        }


async def generate_caption(state: ContentState) -> dict[str, Any]:
    """Generate the full caption body via LLM."""
    await update_agent_run_step(state.get("run_id", ""), "generate_caption", _STEP_INDEX["generate_caption"])
    try:
        brand = state.get("brand", {})
        item = state.get("calendar_item", {})
        positioning = state.get("positioning", {})
        relevant_pillar = state.get("relevant_pillar", {})
        relevant_audience = state.get("relevant_audience", {})
        product = state.get("product", {})
        month_context = state.get("month_context", "")
        recent_posts = state.get("recent_posts", [])
        top_performing = state.get("top_performing", [])

        channel = (item.get("channel", "") or "").lower()
        voice_mode = _voice_mode_for_channel(channel)
        sub_brand = state.get("sub_brand") or brand.get("name", "")
        voice_block = _build_voice_block(voice_mode, sub_brand, brand.get("name", ""))

        # Layered caption settings: per-channel override > brand global > defaults
        settings = _effective_caption_settings(brand, channel)
        brand_bible_block = _build_brand_bible_block(brand, settings)
        channel_constraints_block = _build_channel_constraints_block(settings, channel)
        max_words = settings["max_words"]

        # Full positioning context (no truncation)
        positioning_text = sanitize_json_for_prompt(positioning)

        # Pillar description
        pillar_desc = relevant_pillar.get("description", "")

        # Audience details
        pain_points = ", ".join(relevant_audience.get("pain_points", [])) or "N/A"
        content_prefs = relevant_audience.get("content_preferences", {})
        if isinstance(content_prefs, dict):
            audience_prefs = (
                f"Tone: {content_prefs.get('tone', 'N/A')}, "
                f"Topics: {', '.join(content_prefs.get('topics', []))}"
            )
        else:
            audience_prefs = str(content_prefs)

        # Product benefits
        product_section = ""
        if product.get("name"):
            product_section = (
                f"PRODUCT DETAILS:\n"
                f"  Name: {sanitize_for_prompt(product.get('name', ''))}\n"
                f"  Description: {sanitize_for_prompt(product.get('description', ''))}\n"
                f"  Category: {sanitize_for_prompt(product.get('category', ''))}\n\n"
            )

        # Recent captions to avoid
        recent_captions = (
            "\n".join(
                f"- {sanitize_for_prompt(str(p.get('title', ''))[:80])}"
                for p in recent_posts[:15]
                if p.get("title")
            )
            or "None available"
        )

        # Top performing captions to learn from
        top_captions = (
            "\n".join(
                f"- {sanitize_for_prompt(str(p.get('caption_snippet', ''))[:120])} "
                f"(engagement: {p.get('engagement_rate', 0):.1%})"
                for p in top_performing[:5]
                if p.get("caption_snippet")
            )
            or "None available"
        )

        # Brand URL for CTA
        brand_url = brand.get("website_url", "")

        brief_text = sanitize_for_prompt(
            item.get("content_brief") or item.get("description") or ""
        )

        bible_section = f"{brand_bible_block}\n\n" if brand_bible_block else ""
        prompt = [
            {
                "role": "system",
                "content": (
                    f"{voice_block}\n\n"
                    f"{bible_section}"
                    f"{channel_constraints_block}\n\n"
                    "You write social captions that sound like a real person "
                    "wrote them, not an AI optimizing for engagement.\n\n"
                    "PRIMARY RULE: The user BRIEF is the topic of this post. "
                    "Write about that topic. Use the brand voice only for TONE "
                    "(formality, warmth, register). Never let brand positioning "
                    "override what the user asked for. If the brief says "
                    "'educational post about eating healthy', write about "
                    "healthy eating, even if the brand is positioned for "
                    "something else commercially.\n\n"
                    f"LENGTH: Stay strictly under {max_words} words (HARD LIMIT). "
                    "Start with the provided hook. End with a CTA followed by "
                    "the brand URL on its own line. If your draft exceeds "
                    f"{max_words} words, rewrite tighter before returning. "
                    "Do not submit an over-length caption.\n\n"
                    "LAYOUT — give the caption visual breathing room:\n"
                    "- Open with the hook on its own line.\n"
                    "- Separate distinct sections with a blank line (\\n\\n).\n"
                    "- Pick the format that fits the brief: a flowing paragraph "
                    "  for storytelling, a short list for features or steps, "
                    "  a Q&A for educational posts. Don't force a list when the "
                    "  brief doesn't call for one. If you do use a list, the "
                    "  marker (✓, →, •, or numbered) should fit "
                    "  the brand voice.\n"
                    "- End with a short CTA line, then a label line ending with "
                    "  ':' (e.g. 'Shop now:', 'Try it today:', 'Read more:'), "
                    "  then the URL on its own line. Never embed a URL inside "
                    "  a sentence.\n\n"
                    "ABSOLUTE RULES:\n"
                    "- NEVER include hashtags (#anything) anywhere inside the "
                    "  caption body. Hashtags are appended automatically by the "
                    "  publishing pipeline from a separate field. Writing them "
                    "  in the caption will produce duplicates in the final post.\n"
                    "- The URL belongs on its own line, preceded by a short "
                    "  label line ending with ':'.\n\n"
                    "WRITE LIKE A HUMAN, NOT AN AI:\n"
                    "- Vary sentence length. Short. Then medium. Occasionally a "
                    "  longer one if the thought needs it.\n"
                    "- No em dashes between clauses. Use periods, commas, or "
                    "  restructure the sentence.\n"
                    "- No 'It's not just X, it's Y' or 'Whether you're...' templates.\n"
                    "- No tricolons (three parallel adjectives in a row).\n"
                    "- Avoid these words entirely: elevate, unlock, discover, "
                    "  harness, leverage, transform, navigate, delve, dive, "
                    "  embark, journey, curated, bespoke, seamless, holistic, "
                    "  unprecedented, game-changer, paradigm, ecosystem, "
                    "  in today's world.\n"
                    "- Don't open with 'Welcome to...' or 'In a world where...'.\n"
                    "- Specifics beat abstractions. Name actual things, places, "
                    "  numbers, behaviours. Avoid vague 'experience' / 'journey' talk.\n"
                    "- Read it back: would a friend write this in a message, or "
                    "  does it sound like a brand template? If the second, rewrite.\n\n"
                    "Return ONLY the caption text. No section labels, no quotes."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"WHAT TO WRITE ABOUT (primary intent — never override):\n"
                    f"{brief_text or '(no brief — fall back to theme below)'}\n\n"
                    f"HOOK (start the caption with this line):\n"
                    f"{sanitize_for_prompt(state.get('hook', ''))}\n\n"
                    f"PLATFORM: {sanitize_for_prompt(item.get('channel', ''))}\n"
                    f"THEME: {sanitize_for_prompt(item.get('theme', ''))}\n"
                    f"SUB-THEME: {sanitize_for_prompt(item.get('weekly_sub_theme', ''))}\n\n"
                    f"BRAND TONE REFERENCE (voice/style only, NOT topic):\n"
                    f"  Name: {sanitize_for_prompt(brand.get('name', ''))}\n"
                    f"  URL (for CTA): {sanitize_for_prompt(brand_url)}\n"
                    f"  Positioning summary: {positioning_text}\n\n"
                    f"AUDIENCE: {sanitize_for_prompt(relevant_audience.get('name', ''))}\n"
                    f"  Cares about: {sanitize_for_prompt(pain_points)}\n"
                    f"  Prefers: {sanitize_for_prompt(audience_prefs)}\n\n"
                    f"PILLAR (optional context): "
                    f"{sanitize_for_prompt(relevant_pillar.get('name', ''))} — "
                    f"{sanitize_for_prompt(pillar_desc)}\n\n"
                    f"{product_section}"
                    f"MONTHLY STRATEGY (background only — do not let it "
                    f"override the brief):\n"
                    f"{sanitize_for_prompt(month_context[:3000])}\n\n"
                    f"DO NOT REUSE angles from these recent captions:\n"
                    f"{recent_captions}\n\n"
                    f"For style cues only, posts that performed well:\n"
                    f"{top_captions}\n\n"
                    f"CTA: end with a natural-sounding call-to-action that "
                    f"includes the URL {sanitize_for_prompt(brand_url)}. "
                    f"Make it match the brief's topic, not a generic brand pitch."
                ),
            },
        ]
        caption = await chat_completion(prompt, temperature=0.8, max_tokens=2048)
        return {"caption": caption.strip()}
    except Exception as exc:
        logger.error("generate_caption failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"generate_caption failed: {exc}"],
        }


async def generate_hashtags(state: ContentState) -> dict[str, Any]:
    """Generate relevant hashtags via LLM."""
    await update_agent_run_step(state.get("run_id", ""), "generate_hashtags", _STEP_INDEX["generate_hashtags"])
    try:
        brand = state.get("brand", {})
        item = state.get("calendar_item", {})
        top_performing = state.get("top_performing", [])

        channel = (item.get("channel", "") or "").lower()

        # Platform-specific hashtag limits
        if channel == "instagram":
            platform_limit = "Up to 30 hashtags (use 20-25 for optimal reach)"
        elif channel == "linkedin":
            platform_limit = "3-5 hashtags only (LinkedIn penalizes excessive hashtags)"
        elif channel == "x":
            platform_limit = "2-3 hashtags maximum"
        else:
            platform_limit = "5-10 hashtags"

        # Brand name slug for branded hashtag
        brand_name = brand.get("name", "")
        brand_slug = re.sub(r"[^a-zA-Z0-9]", "", brand_name)

        # Top hashtags from engagement data (extract from top performing captions)
        top_hashtags_info = ""
        if top_performing:
            top_hashtags_info = "Top performing content hashtag context:\n" + "\n".join(
                f"- {sanitize_for_prompt(str(p.get('title', ''))[:50])} (engagement: {p.get('engagement_rate', 0):.1%})"
                for p in top_performing[:5]
                if p.get("title")
            )

        brief_text = sanitize_for_prompt(
            item.get("content_brief") or item.get("description") or ""
        )

        prompt = [
            {
                "role": "system",
                "content": (
                    "You generate hashtags for social posts.\n\n"
                    "PRIMARY RULE: Match the user BRIEF first. The brief tells "
                    "you the actual topic of this post. Pick hashtags that fit "
                    "that topic — not generic brand-positioning tags. If the "
                    "brief is about healthy eating, use food/wellness tags. If "
                    "it's a promo, use deals/savings tags. If it's a product "
                    "story, use category tags for that product.\n\n"
                    "Mix broad, niche, and branded hashtags.\n"
                    'Return JSON: {"hashtags": ["tag1", "tag2", ...]}. '
                    "Each tag is a single word, alphanumeric only, no '#' "
                    "prefix, no spaces, no punctuation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"BRIEF (drive hashtag topic from this):\n"
                    f"{brief_text or '(no brief — fall back to caption + theme)'}\n\n"
                    f"BRAND: {sanitize_for_prompt(brand_name)}\n"
                    f"PLATFORM: {sanitize_for_prompt(channel)}\n"
                    f"PLATFORM HASHTAG LIMIT: {platform_limit}\n\n"
                    f"FULL CAPTION (for context):\n"
                    f"{sanitize_for_prompt(state.get('caption', ''))}\n\n"
                    f"THEME: {sanitize_for_prompt(item.get('theme', ''))}\n\n"
                    f"{top_hashtags_info}\n\n"
                    f"ALWAYS INCLUDE the branded hashtag: {brand_slug}"
                ),
            },
        ]
        result = await chat_completion(
            prompt,
            temperature=0.6,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        parsed = parse_llm_json(result, fallback=None)
        hashtags: list[str] | None = None
        if isinstance(parsed, dict):
            # Skip 'error' / 'message' keys; pick the first list-of-strings value.
            for key, value in parsed.items():
                if key.lower() in {"error", "message", "detail"}:
                    continue
                if isinstance(value, list):
                    hashtags = value
                    break
        elif isinstance(parsed, list):
            hashtags = parsed

        # Sanitize: must be a non-empty alphanumeric token (a-z, 0-9, underscore).
        # Drops JSON syntax fragments, quoted strings, error messages, etc.
        def _clean_tag(tag: object) -> str | None:
            if not isinstance(tag, str):
                return None
            cleaned = tag.strip().lstrip("#").strip()
            cleaned = re.sub(r"[^A-Za-z0-9_]", "", cleaned)
            if not cleaned or len(cleaned) > 50:
                return None
            return cleaned

        cleaned_tags: list[str] = []
        seen: set[str] = set()
        for tag in hashtags or []:
            c = _clean_tag(tag)
            if c and c.lower() not in seen:
                cleaned_tags.append(c)
                seen.add(c.lower())

        # Always ensure the branded hashtag is present.
        if brand_slug and brand_slug.lower() not in seen:
            cleaned_tags.insert(0, brand_slug)

        return {"hashtags": cleaned_tags}
    except Exception as exc:
        logger.error("generate_hashtags failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_hashtags failed: {exc}",
            ],
        }


async def source_product_image_node(state: ContentState) -> dict[str, Any]:
    """Source a real product image from the product image gallery.

    Rules:
    - NEVER AI-generate product photos
    - Only use images from the product's image_urls gallery (real web photos)
    - If no gallery images exist, mark as lifestyle-only (no product in image)
    """
    await update_agent_run_step(state.get("run_id", ""), "source_product_image", _STEP_INDEX["source_product_image"])
    item = state.get("calendar_item", {})
    state.get("brand", {})
    brand_id = state["brand_id"]

    # Calendar items store product_ids (UUID array), not product_sku/product_name
    product_ids = item.get("product_ids") or []
    product_sku = item.get("product_sku")
    product_name = item.get("product_name") or item.get("title", "")

    if not product_sku and not product_name and not product_ids:
        return {
            "product_image": None,
            "needs_manual_image": False,
            "is_lifestyle_only": True,
        }

    # Try to find the product in the database and check its image gallery
    from shared.tools.database import execute_query

    # First try by product_ids (from calendar item), then fallback to sku/name
    if product_ids:
        pid = product_ids[0] if isinstance(product_ids, list) else product_ids
        products = await execute_query(
            "SELECT id, name, image_urls, primary_image_url FROM products "
            "WHERE id = :pid AND is_active = true LIMIT 1",
            {"pid": str(pid)},
        )
    else:
        products = await execute_query(
            "SELECT id, name, image_urls, primary_image_url FROM products "
            "WHERE brand_id = :brand_id AND is_active = true AND ("
            "  bc_item_no = :sku OR LOWER(name) LIKE LOWER(:name_pattern)"
            ") LIMIT 1",
            {
                "brand_id": brand_id,
                "sku": product_sku or "",
                "name_pattern": f"%{product_name[:30]}%" if product_name else "%",
            },
        )

    if not products:
        logger.info("No matching product found for '%s' — lifestyle only", product_name)
        return {
            "product_image": None,
            "needs_manual_image": False,
            "is_lifestyle_only": True,
        }

    product = products[0]
    gallery = product.get("image_urls")

    # Check if product has images in its gallery
    if isinstance(gallery, list) and gallery:
        # Use primary image or first gallery image
        primary = product.get("primary_image_url")
        if not primary and isinstance(gallery[0], dict):
            primary = gallery[0].get("url")
        elif not primary and isinstance(gallery[0], str):
            primary = gallery[0]

        if primary:
            logger.info("Using gallery image for product '%s'", product_name)
            return {
                "product_image": primary,
                "product_image_source": "gallery",
                "needs_manual_image": False,
                "is_lifestyle_only": False,
                "product_id": str(product.get("id", "")),
            }

    # No gallery images — restrict to lifestyle shots
    logger.info(
        "Product '%s' has no gallery images — lifestyle only, no product placement",
        product_name,
    )
    return {
        "product_image": None,
        "needs_manual_image": True,
        "is_lifestyle_only": True,
        "product_id": str(product.get("id", "")),
    }


async def enhance_image_prompt(state: ContentState) -> dict[str, Any]:
    """Expand a short user brief into an expert photographic prompt.

    Runs the brief from ``calendar_item.content_brief`` (fallback: ``description``)
    through an LLM art-director step. Long/expert briefs are passed through
    untouched. On failure we return no enhanced prompt and ``generate_background``
    falls back to its existing template.
    """
    await update_agent_run_step(
        state.get("run_id", ""), "enhance_image_prompt", _STEP_INDEX["enhance_image_prompt"]
    )

    item = state.get("calendar_item", {})
    brief = item.get("content_brief") or item.get("description") or ""
    if not brief or not brief.strip():
        return {"enhanced_image_prompt": None}

    brand = state.get("brand", {})
    product = state.get("product", {})
    relevant_audience = state.get("relevant_audience", {})
    is_lifestyle_only = state.get("is_lifestyle_only", True)
    has_product_image = state.get("product_image") is not None

    # Parse brand colors and visual style (same pattern as generate_background)
    color_palette = brand.get("color_palette") or {}
    if isinstance(color_palette, str):
        try:
            color_palette = json.loads(color_palette)
        except (json.JSONDecodeError, TypeError):
            color_palette = {}

    brand_guidelines = brand.get("brand_guidelines", {})
    if isinstance(brand_guidelines, str):
        try:
            brand_guidelines = json.loads(brand_guidelines)
        except (json.JSONDecodeError, TypeError):
            brand_guidelines = {}

    legacy_colors = brand_guidelines.get("colors", {})
    colors = {**legacy_colors, **color_palette} if color_palette else legacy_colors
    visual_style = brand_guidelines.get(
        "visual_style", "modern, clean, tropical warmth"
    )

    audience_content_prefs = relevant_audience.get("content_preferences", {})
    audience_tone = (
        audience_content_prefs.get("tone", "aspirational")
        if isinstance(audience_content_prefs, dict)
        else "aspirational"
    )

    enhanced = await enhance_image_prompt_fn(
        brief=brief,
        brand_name=brand.get("name", ""),
        product_name=product.get("name", ""),
        product_description=product.get("description", ""),
        channel=item.get("channel", ""),
        theme=item.get("theme", ""),
        audience=relevant_audience.get("name", ""),
        audience_tone=str(audience_tone),
        brand_colors=colors,
        visual_style=str(visual_style),
        has_product_image=has_product_image,
        is_lifestyle_only=is_lifestyle_only,
    )

    return {"enhanced_image_prompt": enhanced}


async def generate_background(state: ContentState) -> dict[str, Any]:
    """Generate a background/lifestyle image via AI.

    If ``enhanced_image_prompt`` is present in state (produced by the upstream
    enhancer node), use it as the creative core of the prompt and wrap it with
    the standard composition / realism / negative directives. Otherwise fall
    back to the previous template-only behaviour.

    If is_lifestyle_only (no product gallery images), generate a pure lifestyle shot.
    If product image is available, generate a scene with a generic product placeholder
    that will later be replaced by Gemini with the real product photo.
    """
    await update_agent_run_step(state.get("run_id", ""), "generate_background", _STEP_INDEX["generate_background"])
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})
    is_lifestyle_only = state.get("is_lifestyle_only", True)
    has_product_image = state.get("product_image") is not None
    relevant_audience = state.get("relevant_audience", {})
    month_context = state.get("month_context", "")
    enhanced_prompt = state.get("enhanced_image_prompt")

    # Extract brand colors from the dedicated color_palette field (preferred)
    # with fallback to brand_guidelines.colors for backwards compat
    color_palette = brand.get("color_palette") or {}
    if isinstance(color_palette, str):
        try:
            color_palette = json.loads(color_palette)
        except (json.JSONDecodeError, TypeError):
            color_palette = {}

    brand_guidelines = brand.get("brand_guidelines", {})
    if isinstance(brand_guidelines, str):
        try:
            brand_guidelines = json.loads(brand_guidelines)
        except (json.JSONDecodeError, TypeError):
            brand_guidelines = {}

    # Merge: color_palette takes priority, then brand_guidelines.colors
    legacy_colors = brand_guidelines.get("colors", {})
    colors = {**legacy_colors, **color_palette} if color_palette else legacy_colors

    visual_style = brand_guidelines.get(
        "visual_style", "modern, clean, tropical warmth"
    )

    # Build color palette directive
    color_directive = (
        f"Brand color palette: Primary {colors.get('primary', '#3b82f6')}, "
        f"Secondary {colors.get('secondary', '#22c55e')}, "
        f"Accent {colors.get('accent', '#f59e0b')}. "
        f"Subtly incorporate these brand colors into the scene (backgrounds, props, lighting tones). "
    )

    # Visual style directive
    style_directive = f"Visual style: {sanitize_for_prompt(str(visual_style))}. "

    # Audience aesthetic
    audience_content_prefs = relevant_audience.get("content_preferences", {})
    audience_tone = (
        audience_content_prefs.get("tone", "aspirational")
        if isinstance(audience_content_prefs, dict)
        else "aspirational"
    )
    audience_directive = (
        f"Target audience aesthetic: {sanitize_for_prompt(str(audience_tone))}. "
    )

    # Seasonal direction from month context
    seasonal_directive = (
        f"Seasonal direction: {sanitize_for_prompt(month_context[:200])}. "
        if month_context
        else "Seasonal direction: current season. "
    )

    # Common composition requirements for logo/text overlay
    composition_rules = (
        "IMPORTANT COMPOSITION: The top-right area of the image must be open sky, "
        "soft blurred background, or a monotone surface (low-contrast, uniform color) — "
        "this area is reserved for a brand logo overlay. "
        "The bottom-left area should have some darker or open space for text overlay. "
        "Do NOT place busy details or high-contrast elements in these corners. "
    )

    # Realism directives — anchor the model to real commercial photography
    # rather than the default "AI stock photo / illustration" aesthetic.
    realism_directive = (
        "Photorealistic raw photograph captured on a physical camera. "
        "Natural skin texture with visible pores and fine lines. "
        "Realistic imperfections — slight asymmetry, natural blemishes, weathered details. "
        "Authentic lighting with real shadows and accurate color temperature. "
        "Real-world materials — visible fabric weave, wood grain, surface wear. "
        "Natural reflections, true-to-life depth of field. "
        "This is a real photograph, indistinguishable from National Geographic, "
        "Magnum Photos, or documentary photojournalism. "
    )

    # Camera metadata anchors the model to real DSLR photography. EXIF data
    # acts as a hint to the model that this is photographic, not illustrative.
    camera_directive = (
        "Shot on Sony A7R IV with 85mm f/1.8 prime lens. "
        "ISO 200, 1/250s, manual focus, RAW format, 50 megapixels. "
        "Kodak Portra 400 film grain emulation with subtle chromatic aberration "
        "on high-contrast edges. "
        "Photographic style references: Annie Leibovitz portrait lighting, "
        "Steve McCurry documentary realism, Joel Meyerowitz street photography. "
    )

    # Aggressive negative prompting — explicitly block stylized/cartoon/illustration
    # aesthetics that gpt-image and similar models tend toward by default.
    negative_directive = (
        "STRICT STYLE EXCLUSIONS — the image must NOT be: "
        "anime, manga, Japanese animation, cartoon, comic book, graphic novel. "
        "NOT Disney style, NOT Pixar style, NOT DreamWorks, NOT Studio Ghibli, "
        "NOT animated film aesthetic. "
        "NOT 3D rendering, NOT Unreal Engine, NOT Blender render, NOT CGI. "
        "NOT vector illustration, NOT flat design, NOT material design. "
        "NOT digital painting, NOT concept art, NOT matte painting. "
        "NOT children's book illustration, NOT storybook style. "
        "NOT cel-shaded, NOT video game render, NOT character render. "
        "NOT AI-generated illustration aesthetic, NOT stylized rendering. "
        "STRICT CONTENT EXCLUSIONS: "
        "NO text, NO words, NO letters, NO numbers, NO typography. "
        "NO logos, NO watermarks, NO labels, NO signs, NO captions. "
        "NO floating icons, NO UI elements, NO app interface overlays. "
        "NO HUD chrome, NO health indicators, NO status badges, NO info bubbles. "
        "NO graphic shapes or symbols overlaid on the scene. "
        "STRICT VISUAL EXCLUSIONS: "
        "NO distorted anatomy, NO extra fingers, NO blurry faces. "
        "NO plastic skin, NO airbrushed skin, NO uniform skin. "
        "NO oversaturated colors, NO HDR look, NO heavy lens flare. "
        "NO dreamy soft filter, NO bloom effect, NO over-stylized lighting. "
    )

    if enhanced_prompt:
        # The art-director LLM has produced a self-contained scene description.
        # We still append the realism/camera/negative guards so the image model
        # stays on commercial-photography rails regardless of how the LLM phrased
        # the scene.
        logger.info(
            "Using enhanced image prompt (%d words) as creative core",
            len(enhanced_prompt.split()),
        )
        prompt_text = (
            f"REAL PHOTOGRAPH — Ultra realistic documentary commercial photography "
            f"for a {sanitize_for_prompt(item.get('channel', 'instagram'))} post.\n\n"
            f"SCENE:\n{sanitize_for_prompt(enhanced_prompt, max_length=4000)}\n\n"
            f"{camera_directive}"
            f"{realism_directive}"
            f"Real shadows. Authentic textures. Natural depth of field. "
            f"{composition_rules}"
            f"{negative_directive}"
            f"The image MUST look like a documentary photograph captured with a "
            f"real DSLR camera, NOT an artwork, NOT a rendering, NOT an illustration."
        )
    elif is_lifestyle_only or not has_product_image:
        # Pure lifestyle — no product in the image
        prompt_text = (
            f"REAL PHOTOGRAPH — Ultra realistic documentary commercial photography "
            f"for a {sanitize_for_prompt(item.get('channel', 'instagram'))} post. "
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}. "
            f"Theme: {sanitize_for_prompt(item.get('theme', ''))}. "
            f"Natural human environment, ordinary real-world setting. "
            f"{color_directive}"
            f"{style_directive}"
            f"{audience_directive}"
            f"{seasonal_directive}"
            f"{camera_directive}"
            f"{realism_directive}"
            f"Real shadows. Authentic textures. Natural depth of field. "
            f"{composition_rules}"
            f"{negative_directive}"
            f"The image MUST look like a documentary photograph captured with a "
            f"real DSLR camera, NOT an artwork, NOT a rendering, NOT an illustration. "
            f"Do NOT include any products. Focus on the lifestyle and mood."
        )
    else:
        # Scene with generic product placeholder — will be replaced by Gemini later
        prompt_text = (
            f"REAL PHOTOGRAPH — Ultra realistic documentary commercial photography "
            f"for a {sanitize_for_prompt(item.get('channel', 'instagram'))} post. "
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}. "
            f"Theme: {sanitize_for_prompt(item.get('theme', ''))}. "
            f"Natural human environment, ordinary real-world setting. "
            f"Include a realistic unlabeled neutral product container with authentic "
            f"material textures (matte plastic or paperboard, slight wear, natural "
            f"shadows, NO writing on it) placed naturally in the scene. "
            f"{color_directive}"
            f"{style_directive}"
            f"{audience_directive}"
            f"{seasonal_directive}"
            f"{camera_directive}"
            f"{realism_directive}"
            f"Real shadows. Authentic textures. Natural depth of field. "
            f"{composition_rules}"
            f"{negative_directive}"
            f"The image MUST look like a documentary photograph captured with a "
            f"real DSLR camera, NOT an artwork, NOT a rendering, NOT an illustration. "
            f"The product container must be completely blank — it will be digitally replaced later."
        )

    # Choose aspect ratio per platform so the preview/post doesn't crop.
    channel_lower = (item.get("channel", "") or "").lower()
    if channel_lower in {"facebook", "linkedin", "youtube"}:
        image_size = "1792x1024"  # landscape
    elif channel_lower in {"tiktok"}:
        image_size = "1024x1792"  # portrait
    else:
        image_size = "1024x1024"  # square (instagram, x, default)

    try:
        image_url = await generate_image(prompt_text, size=image_size)
        return {"generated_image": image_url}
    except Exception:
        logger.exception("Background image generation failed")
        return {"generated_image": None}


ALL_CHANNELS = [
    "instagram",
    "facebook",
    "linkedin",
    "youtube",
    "tiktok",
    "x",
    "website_blog",
    "teams",
]

# Base platform-format hints. The numeric constraints (max_words,
# hashtag counts) are appended dynamically per-brand by
# _platform_spec_for(), pulling from brand_guidelines first and falling
# back to _DEFAULT_CHANNEL_CAPTION.
_PLATFORM_FORMAT_HINTS = {
    "instagram":    "Square/portrait image, up to 30 hashtags supported.",
    "facebook":     "Landscape image, longer text supported.",
    "linkedin":     "Professional tone, article-style.",
    "youtube":      "Title (100 chars max), description (5000 chars max), tags list, thumbnail prompt.",
    "tiktok":       "Short punchy caption, trending hashtags, vertical video brief.",
    "x":            "280 chars max per tweet, thread format for longer content.",
    "website_blog": "Full markdown article with H1/H2/H3 headings, meta description, SEO keywords. NOT auto-published.",
    "teams":        "Internal announcement format, plain text, concise.",
}


def _count_words(text: str) -> int:
    return sum(1 for w in (text or "").split() if w.strip())


_URL_LIKE_RE = re.compile(r"https?://\S+")


def _split_url_block(text: str) -> tuple[str, str]:
    """Split caption into (body, url_block).

    url_block is the trailing label+URL pair if the caption ends with one
    (a short label line ending with ':' followed by a URL line). Otherwise
    url_block is empty. Used by _trim_to_word_limit so the CTA's URL block
    survives a hard trim instead of being chopped off mid-link.
    """
    if not text:
        return text or "", ""
    lines = text.rstrip().split("\n")
    # Walk back over trailing blank lines
    while lines and not lines[-1].strip():
        lines.pop()
    if len(lines) < 2:
        return text, ""
    last = lines[-1].strip()
    label = lines[-2].strip()
    if _URL_LIKE_RE.fullmatch(last) and label.endswith(":") and len(label) <= 40:
        body_lines = lines[:-2]
        # Drop trailing blank lines from body so the rebuild keeps spacing tight
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        return "\n".join(body_lines), f"{label}\n{last}"
    return text, ""


def _trim_to_word_limit(text: str, max_words: int) -> str:
    """Trim text to fit max_words, preserving the trailing URL block when present.

    Trimming strategy:
      1. Split off the trailing 'label:\\nURL' block if there is one; preserve
         it verbatim and budget the remaining words for the body.
      2. Prefer cutting on a `\\n\\n` block boundary inside the budget so we
         don't slice through a list or a half-sentence.
      3. Fall back to a sentence boundary in the back half of the cut.
      4. Last resort: word-boundary cut with ellipsis.
      5. Re-append the URL block separated by a blank line.
    """
    if not text:
        return text or ""
    body, url_block = _split_url_block(text)
    total_words = _count_words(text)
    if total_words <= max_words:
        return text

    url_words = _count_words(url_block) if url_block else 0
    # Reserve 1 word of slack so re-attachment doesn't push us over the limit
    body_budget = max(1, max_words - url_words - (1 if url_block else 0))

    body_words = body.split()
    if len(body_words) > body_budget:
        truncated = " ".join(body_words[:body_budget])
        # Prefer a block boundary (\n\n) in the back 40% of the truncation
        cut_floor = int(len(truncated) * 0.6)
        last_block = truncated.rfind("\n\n")
        if last_block >= cut_floor:
            body = truncated[:last_block].rstrip()
        else:
            last_stop = max(
                truncated.rfind("."),
                truncated.rfind("!"),
                truncated.rfind("?"),
            )
            if last_stop >= cut_floor:
                body = truncated[: last_stop + 1]
            else:
                body = truncated.rstrip(",;: ") + "..."
    # Body fit within budget — keep as-is

    return f"{body}\n\n{url_block}" if url_block else body


async def _shorten_caption_with_llm(
    caption: str, max_words: int, brand: dict, channel: str
) -> str:
    """Ask the LLM to compress a caption to <= max_words. One-shot retry."""
    settings = _effective_caption_settings(brand, channel)
    bible = _build_brand_bible_block(brand, settings)
    bible_section = f"{bible}\n\n" if bible else ""
    messages = [
        {
            "role": "system",
            "content": (
                f"{bible_section}"
                "You compress social captions while preserving meaning, voice, "
                "the call to action, AND the visual layout. Output ONLY the "
                "rewritten caption text.\n\n"
                "PRESERVE THE STRUCTURE:\n"
                "- Keep blank lines (\\n\\n) between distinct sections so the "
                "  caption keeps its visual breathing room.\n"
                "- Keep the URL on its own line, preceded by its short label "
                "  line ending with ':'. Never embed a URL inside a sentence.\n"
                "- If the original uses a list, keep the list (you may drop or "
                "  shorten individual items). Do not collapse a structured "
                "  caption into a single paragraph.\n"
                "- NEVER insert hashtags (#anything) in the rewrite. Hashtags "
                "  are handled separately by the publishing pipeline."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Rewrite this {channel or 'social'} caption to be under "
                f"{max_words} words while keeping the same topic, voice, hook, "
                f"CTA, URL line, and overall multi-block layout. Trim filler, "
                f"merge sentences, drop adjectives, shorten list items. "
                f"NEVER exceed {max_words} words.\n\n"
                f"Original:\n{sanitize_for_prompt(caption, max_length=4000)}"
            ),
        },
    ]
    try:
        result = await chat_completion(messages, temperature=0.4, max_tokens=1024)
        return str(result or "").strip().strip('"').strip("`")
    except Exception as exc:
        logger.warning(
            "shorten-caption retry failed for %s (%s) — falling back to trim",
            channel, exc,
        )
        return caption


async def _enforce_caption_word_limits(
    adaptations: dict, brand: dict
) -> dict:
    """Per-channel: count words, retry-once via LLM if over, trim as fallback.

    Implements the spec: keep <= max, LLM-retry if > max, hard-trim if still
    over after retry. Logs at each step so over-length issues are visible.
    """
    if not isinstance(adaptations, dict):
        return adaptations
    for channel, payload in list(adaptations.items()):
        if not isinstance(payload, dict):
            continue
        caption = payload.get("caption")
        if not isinstance(caption, str) or not caption.strip():
            continue
        settings = _effective_caption_settings(brand, channel)
        max_words = settings["max_words"]
        word_count = _count_words(caption)
        if word_count <= max_words:
            continue
        logger.info(
            "adapt_platforms: %s caption is %d words (limit %d), retrying via LLM",
            channel, word_count, max_words,
        )
        shortened = await _shorten_caption_with_llm(
            caption, max_words, brand, channel
        )
        new_count = _count_words(shortened)
        if shortened and new_count <= max_words:
            payload["caption"] = shortened
            continue
        # LLM still over budget (or returned junk) — hard trim
        trimmed = _trim_to_word_limit(
            shortened if shortened else caption, max_words
        )
        logger.warning(
            "adapt_platforms: %s caption still over after retry (%d), trimmed to %d",
            channel, new_count, _count_words(trimmed),
        )
        payload["caption"] = trimmed
    return adaptations


def _platform_spec_for(channel: str, brand: dict) -> str:
    """Per-channel spec line: format hint + per-brand max_words and hashtag count."""
    channel = (channel or "").lower()
    settings = _effective_caption_settings(brand, channel)
    base = _PLATFORM_FORMAT_HINTS.get(channel, "Standard caption with hashtags.")
    pieces = [
        base,
        f"MAX {settings['max_words']} WORDS (hard limit, never exceed).",
        f"Hashtags: {settings['hashtags_min']}-{settings['hashtags_max']}.",
    ]
    if settings.get("emoji"):
        pieces.append(f"Emoji usage: {settings['emoji']}.")
    if settings.get("hook_format"):
        pieces.append(f"Hook format: {settings['hook_format']}.")
    if settings.get("must_name_product"):
        pieces.append("MUST mention product name.")
    return " ".join(pieces)


async def adapt_platforms(state: ContentState) -> dict[str, Any]:
    """Create platform-specific adaptations of the content via LLM for enabled channels."""
    await update_agent_run_step(state.get("run_id", ""), "adapt_platforms", _STEP_INDEX["adapt_platforms"])
    source_platform = state.get("calendar_item", {}).get("channel", "instagram")

    # Determine which channels to adapt for based on brand config
    brand = state.get("brand", {})
    channels_cfg = brand.get("brand_guidelines") or {}
    if isinstance(channels_cfg, str):
        try:
            channels_cfg = json.loads(channels_cfg)
        except (json.JSONDecodeError, TypeError):
            channels_cfg = {}
    channels_cfg = channels_cfg.get("channels", {})
    enabled = [
        ch
        for ch, cfg in channels_cfg.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    channels_to_adapt = enabled if enabled else ["instagram"]

    # Build per-platform spec block only for enabled channels.
    # Specs now include the per-brand max_words / hashtag count from the
    # brand's Voice Profile (channel override or global), so the LLM gets
    # explicit numeric limits per platform instead of vague guidance.
    spec_lines = "\n".join(
        f"- {ch}: {_platform_spec_for(ch, brand)}" for ch in channels_to_adapt
    )

    # Also assemble a brand bible section so the adaptation respects the
    # same dos/donts as the original draft.
    primary_settings = _effective_caption_settings(brand, source_platform or "")
    bible_block_for_adapt = _build_brand_bible_block(brand, primary_settings)

    # Enriched context for platform adaptation
    positioning = state.get("positioning", {})
    relevant_audience = state.get("relevant_audience", {})
    audience_content_prefs = relevant_audience.get("content_preferences", {})
    audience_tone = (
        audience_content_prefs.get("tone", "")
        if isinstance(audience_content_prefs, dict)
        else ""
    )
    key_messages = positioning.get("key_messages", [])
    key_messages_str = (
        ", ".join(key_messages) if isinstance(key_messages, list) else str(key_messages)
    )

    bible_section_for_adapt = (
        f"{bible_block_for_adapt}\n\n" if bible_block_for_adapt else ""
    )
    prompt = [
        {
            "role": "system",
            "content": (
                "You are a social media and content marketing expert. "
                "Adapt the following content for each platform below, "
                "respecting each platform's constraints AND the brand voice rules.\n\n"
                f"{bible_section_for_adapt}"
                "Platform specifications (HARD LIMITS, never exceed):\n"
                f"{spec_lines}\n\n"
                "WORD COUNT IS A HARD LIMIT. For each platform, count words "
                "in your draft caption. If it exceeds the MAX, rewrite tighter "
                "until it fits. Do not return an over-length caption.\n\n"
                "CAPTION LAYOUT — apply to every platform caption:\n"
                "- Open with the hook on its own line.\n"
                "- Separate distinct sections with a blank line (\\n\\n) so "
                "  the caption keeps visual breathing room.\n"
                "- Pick the format that fits the brief: flowing paragraph, "
                "  short list, Q&A. Don't force a list when the brief doesn't "
                "  call for one. List markers (✓, →, •, numbered) "
                "  should fit the brand voice.\n"
                "- End each caption with a short CTA line, then a label line "
                "  ending with ':' (e.g. 'Shop now:'), then the URL on its "
                "  own line. Never embed a URL inside a sentence.\n"
                "- NEVER include hashtags (#anything) inside the caption "
                "  string. Hashtags go in the separate 'hashtags' array.\n\n"
                "Return JSON with platform names as keys. Each platform object must contain:\n"
                "  caption (string with the layout above), hashtags (array of strings without # prefix), cta (string), "
                "  optimal_time (string), format_notes (string).\n"
                "For youtube also include: title, description, tags, thumbnail_prompt.\n"
                "For website_blog also include: markdown_body, meta_description, seo_keywords (array).\n"
                "For teams also include: announcement_text (plain text)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"BRAND POSITIONING: {sanitize_for_prompt(str(positioning.get('value_proposition', '')))}\n"
                f"BRAND VOICE: {sanitize_for_prompt(str(positioning.get('brand_voice', '')))}\n"
                f"KEY MESSAGES: {sanitize_for_prompt(key_messages_str)}\n"
                f"TARGET AUDIENCE: {sanitize_for_prompt(relevant_audience.get('name', ''))} — "
                f"{sanitize_for_prompt(audience_tone)}\n"
                f"BRAND URL: {sanitize_for_prompt(brand.get('website_url', ''))}\n\n"
                f"Original platform: {sanitize_for_prompt(source_platform)}\n"
                f"Hook: {sanitize_for_prompt(state.get('hook', ''))}\n"
                f"Caption: {sanitize_for_prompt(state.get('caption', ''))}\n"
                f"Hashtags: {sanitize_json_for_prompt(state.get('hashtags', []))}\n"
                f"Adapt for these platforms: {', '.join(channels_to_adapt)}"
            ),
        },
    ]
    try:
        result = await chat_completion(
            prompt, temperature=0.5, response_format={"type": "json_object"}
        )
        adaptations = parse_llm_json(
            result,
            fallback={
                source_platform: {
                    "caption": state.get("caption", ""),
                    "hashtags": state.get("hashtags", []),
                }
            },
        )
        # Unwrap dict-wrapping-dict: LLM may return {"platforms": {"instagram": {...}, ...}}
        if isinstance(adaptations, dict) and len(adaptations) == 1:
            only_val = next(iter(adaptations.values()))
            if isinstance(only_val, dict):
                adaptations = only_val

        # Enforce per-channel max_words: LLM retry first, hard-trim fallback.
        adaptations = await _enforce_caption_word_limits(adaptations, brand)

        # Extract CTA from the primary platform adaptation
        primary = adaptations.get(source_platform, {})
        cta = primary.get("cta", "")

        return {"platform_adaptations": adaptations, "cta": cta}
    except Exception as exc:
        logger.error("adapt_platforms failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"adapt_platforms failed: {exc}"],
        }


async def _replace_product_in_generated_image(
    state: ContentState, image_data: bytes
) -> bytes:
    """If we have a real product image, use Gemini to replace the generic product."""
    product_image_url = state.get("product_image")
    is_lifestyle_only = state.get("is_lifestyle_only", True)

    if is_lifestyle_only or not product_image_url:
        return image_data  # No replacement needed

    try:
        import httpx as _httpx

        # Download the product image from gallery
        # Product image URLs may be: full http(s) URLs, MinIO bucket paths, or backend API paths
        if product_image_url.startswith("http://") or product_image_url.startswith("https://"):
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(product_image_url)
                resp.raise_for_status()
                product_image_data = resp.content
        elif product_image_url.startswith("/"):
            # Relative API path — resolve via backend
            from shared.config import settings as _cfg
            full_url = f"{_cfg.BACKEND_URL}{product_image_url}"
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(full_url)
                resp.raise_for_status()
                product_image_data = resp.content
        else:
            # MinIO object path (e.g., "products/brand_id/image.png")
            # These are stored in the default bucket, not in a bucket named "products"
            from shared.config import settings as _storage_cfg
            default_bucket = _storage_cfg.MINIO_BUCKET if hasattr(_storage_cfg, "MINIO_BUCKET") else "markai-assets"
            try:
                product_image_data = await async_download_file(default_bucket, product_image_url)
            except Exception:
                # Fallback: try via backend file proxy
                from shared.config import settings as _cfg
                full_url = f"{_cfg.BACKEND_URL}/api/v1/files/{product_image_url}"
                async with _httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(full_url)
                    resp.raise_for_status()
                    product_image_data = resp.content

        # Use Gemini to replace the generic product
        from shared.config import settings

        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY not set — skipping product replacement")
            return image_data

        from google import genai
        from google.genai import types as gtypes
        from PIL import Image as PILImage
        from io import BytesIO

        gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        marketing_img = PILImage.open(BytesIO(image_data))
        product_img = PILImage.open(BytesIO(product_image_data))

        product_name = state.get("calendar_item", {}).get("product_name", "product")

        input_size = marketing_img.size  # preserve original dimensions (e.g. 1024x1024)
        aspect_hint = aspect_hint_for_size(input_size)

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[
                f"Replace the generic product in Image 1 with the real product from Image 2 ('{product_name}'). "
                f"Keep everything else exactly the same. Match lighting and perspective. "
                f"{aspect_hint}",
                marketing_img,
                product_img,
            ],
            config=gtypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                result_data = part.inline_data.data
                # Gemini ignores aspect hints fairly often. When it returns a
                # mismatched size we center-crop to the target aspect instead
                # of stretching, which would otherwise distort the product.
                result_img = PILImage.open(BytesIO(result_data))
                if result_img.size != input_size:
                    logger.info(
                        "Gemini returned %s, aspect-preserving resize to %s",
                        result_img.size, input_size,
                    )
                    result_img = resize_preserve_aspect(result_img, input_size)
                    buf = BytesIO()
                    result_img.save(buf, format="PNG", quality=95)
                    result_data = buf.getvalue()
                logger.info(
                    "Gemini product replacement successful for %s", product_name
                )
                return result_data

    except Exception as exc:
        logger.warning(
            "Gemini product replacement failed: %s — using original image", exc
        )

    return image_data


async def _download_logo_bytes(url: str) -> bytes | None:
    """Download logo bytes from a MinIO path or HTTP URL."""
    import httpx

    try:
        if url.startswith("content-images/") or url.startswith("brand-assets/"):
            bucket, _, obj = url.partition("/")
            return await async_download_file(bucket, obj)
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content
    except Exception:
        logger.warning("Failed to download logo from %s", url)
        return None


def _bytes_to_logo_png(raw: bytes) -> bytes | None:
    """Convert raw logo bytes (SVG or raster) to PNG."""
    is_svg = (
        raw[:5] == b"<?xml"
        or raw[:4] == b"<svg"
        or b"<svg" in raw[:500]
    )
    if is_svg:
        return render_logo_png(raw)
    return raw


async def apply_branding(state: ContentState) -> dict[str, Any]:
    """Apply logo overlay and text to the generated image.

    Analyzes the image brightness at the logo placement region and selects
    the most appropriate logo variant (primary, dark_variant, secondary,
    watermark) for optimal contrast and visibility.
    """
    await update_agent_run_step(state.get("run_id", ""), "apply_branding", _STEP_INDEX["apply_branding"])
    generated_image_url = state.get("generated_image")
    if not generated_image_url:
        return {}

    brand = state.get("brand", {})
    item = state.get("calendar_item", {})

    # Collect all available logo variants from brand_guidelines
    brand_guidelines = brand.get("brand_guidelines", {})
    logos_cfg = brand_guidelines.get("logos", {})

    # Resolve each logo variant URL (same logic as build_brand_intelligence for primary)
    from shared.config import settings
    api_base = getattr(settings, "BACKEND_URL", "") or "http://backend:8000"

    available_logos: dict[str, str] = {}
    for label, info in logos_cfg.items():
        if isinstance(info, dict):
            url = info.get("url", "")
            if url and url.startswith("/"):
                url = f"{api_base}{url}"
            if url:
                available_logos[label] = url

    # Fallback: if no logos in guidelines, use brand.logo_url as primary
    if not available_logos:
        fallback_url = brand.get("logo_url", "")
        if fallback_url:
            if fallback_url.startswith("/"):
                fallback_url = f"{api_base}{fallback_url}"
            available_logos["primary"] = fallback_url

    if not available_logos:
        logger.info("No logo available — skipping branding overlay")
        return {}

    # Get the generated image bytes
    import base64 as _b64
    import httpx

    try:
        if generated_image_url.startswith("data:"):
            _, b64_part = generated_image_url.split(",", 1)
            image_data = _b64.b64decode(b64_part)
        elif generated_image_url.startswith("content-images/"):
            image_data = await async_download_file(
                "content-images", generated_image_url.replace("content-images/", "")
            )
        else:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(generated_image_url)
                resp.raise_for_status()
                image_data = resp.content

        # If we have a real product image, replace the generic product via Gemini first
        image_data = await _replace_product_in_generated_image(state, image_data)

        # Analyze image brightness at the logo placement region to pick the best variant
        # Use approximate logo dimensions for the analysis (18% of image width)
        from PIL import Image as _PILImage
        from io import BytesIO as _BytesIO
        _tmp_img = _PILImage.open(_BytesIO(image_data))
        approx_logo_w = int(_tmp_img.width * 0.18)
        approx_logo_h = int(approx_logo_w * 0.5)  # typical logo aspect ratio
        _tmp_img.close()

        brightness, variance = analyze_logo_region_brightness(
            image_data, approx_logo_w, approx_logo_h
        )

        chosen_label = select_logo_variant(
            brightness, variance, list(available_logos.keys())
        )
        chosen_url = available_logos[chosen_label]
        logger.info(
            "Logo variant selected: %s (brightness=%.0f, variance=%.0f, available=%s)",
            chosen_label, brightness, variance, list(available_logos.keys()),
        )

        # Download and convert the chosen logo
        logo_png = None
        logo_raw = await _download_logo_bytes(chosen_url)
        if logo_raw:
            logo_png = _bytes_to_logo_png(logo_raw)

        # Fallback: try other variants if chosen one failed
        if not logo_png:
            for fallback_label, fallback_url in available_logos.items():
                if fallback_label == chosen_label:
                    continue
                logo_raw = await _download_logo_bytes(fallback_url)
                if logo_raw:
                    logo_png = _bytes_to_logo_png(logo_raw)
                    if logo_png:
                        logger.info("Fell back to %s logo variant", fallback_label)
                        chosen_label = fallback_label
                        break

        if not logo_png:
            logger.info("No logo could be loaded — skipping branding overlay")
            return {}

        # Build text overlay lines
        brand_name = brand.get("name", "")
        theme = item.get("theme", "")
        website = brand.get("website_url", "")
        text_line1 = state.get("hook", theme)
        text_line2 = f"{brand_name}" + (f" — {website}" if website else "")

        # Apply overlay — scale depends on the chosen variant (icon-only logos
        # need a smaller scale than wordmarks).
        branded_bytes = overlay_logo_and_text(
            image_data,
            logo_png,
            text_line1=text_line1,
            text_line2=text_line2,
            logo_scale=scale_for_logo_variant(chosen_label),
        )

        # Upload branded image to MinIO
        brand_id = state["brand_id"]
        await async_ensure_bucket("content-images")
        branded_obj = f"{brand_id}/{state['calendar_item_id']}/branded.png"
        await async_upload_file(
            "content-images", branded_obj, branded_bytes, "image/png"
        )

        return {
            "branded_image": f"content-images/{branded_obj}",
            "logo_png_data": logo_png,
            "logo_variant_used": chosen_label,
        }

    except Exception as exc:
        logger.exception("Branding overlay failed: %s", exc)
        # Don't fail the whole pipeline — continue without branding
        return {"errors": [*(state.get("errors") or []), f"Branding overlay failed: {exc}"]}


async def generate_mockups_node(state: ContentState) -> dict[str, Any]:
    """Generate social platform mobile mockup previews for the approval UI.

    Creates mockups for Instagram, Facebook, LinkedIn, and X showing how
    the post would appear in each platform's feed on a mobile device.
    """
    await update_agent_run_step(state.get("run_id", ""), "generate_mockups", _STEP_INDEX["generate_mockups"])
    branded_url = state.get("branded_image")
    generated_url = state.get("generated_image")
    image_source = branded_url or generated_url

    if not image_source:
        return {"mockup_urls": {}}

    try:
        # Get image bytes
        if image_source.startswith("content-images/"):
            obj_name = image_source.replace("content-images/", "")
            image_data = await async_download_file("content-images", obj_name)
        else:
            import base64 as _b64

            if image_source.startswith("data:"):
                _, b64_part = image_source.split(",", 1)
                image_data = _b64.b64decode(b64_part)
            else:
                import httpx

                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(image_source)
                    resp.raise_for_status()
                    image_data = resp.content

        caption = state.get("caption", "")
        brand = state.get("brand", {})
        brand_name = brand.get("name", "Brand")
        logger.info(
            "Mockup brand state: name=%r, slug=%r, has_guidelines=%s, keys=%s",
            brand_name,
            brand.get("slug"),
            bool(brand.get("brand_guidelines")),
            list(brand.keys())[:10],
        )
        # Derive a username/handle from brand guidelines or slug
        brand_guidelines = brand.get("brand_guidelines") or {}
        if isinstance(brand_guidelines, str):
            try:
                brand_guidelines_parsed = json.loads(brand_guidelines)
            except (json.JSONDecodeError, TypeError):
                brand_guidelines_parsed = {}
        else:
            brand_guidelines_parsed = brand_guidelines
        social_links = brand_guidelines_parsed.get("social_links", {})
        channels_cfg_bg = brand_guidelines_parsed.get("channels", {})
        # Try to extract a handle from Instagram link, channels config, or brand slug
        brand_handle = ""
        ig_link = social_links.get("instagram", "")
        if ig_link:
            brand_handle = ig_link.rstrip("/").rsplit("/", 1)[-1]
        if not brand_handle:
            # Check channels.instagram.handle (e.g. "@healthspan.mu")
            ig_channel = channels_cfg_bg.get("instagram", {})
            if isinstance(ig_channel, dict):
                ig_handle = ig_channel.get("handle", "")
                if ig_handle:
                    brand_handle = ig_handle.lstrip("@")
        if not brand_handle:
            brand_handle = brand.get("slug", brand_name.lower().replace(" ", ""))
        logger.info("Mockup brand_handle resolved to %r", brand_handle)
        brand_id = state["brand_id"]
        item_id = state["calendar_item_id"]

        mockup_urls = {}
        await async_ensure_bucket("content-images")
        brand_initial = brand_name[0].upper() if brand_name else "H"

        # Load watermark logo for mockup avatars
        avatar_logo_data = None
        logos_cfg = brand_guidelines_parsed.get("logos", {})
        from shared.config import settings as _settings
        _api_base = getattr(_settings, "BACKEND_URL", "") or "http://backend:8000"
        # Prefer watermark for avatar, fall back to icon/secondary/primary
        for avatar_label in ["watermark", "icon", "secondary", "primary"]:
            logo_info = logos_cfg.get(avatar_label)
            if isinstance(logo_info, dict) and logo_info.get("url"):
                try:
                    _logo_url = logo_info["url"]
                    if _logo_url.startswith("/"):
                        _logo_url = f"{_api_base}{_logo_url}"
                    avatar_logo_data = await _download_logo_bytes(_logo_url)
                    if avatar_logo_data:
                        # Convert SVG to PNG if needed
                        avatar_logo_data = _bytes_to_logo_png(avatar_logo_data) or avatar_logo_data
                        logger.info("Using %s logo as mockup avatar", avatar_label)
                        break
                except Exception:
                    logger.warning("Failed to load %s logo for avatar", avatar_label)
            avatar_logo_data = None

        # Only generate mockups for enabled channels
        brand_guidelines = brand.get("brand_guidelines") or {}
        if isinstance(brand_guidelines, str):
            try:
                brand_guidelines = json.loads(brand_guidelines)
            except (json.JSONDecodeError, TypeError):
                brand_guidelines = {}
        channels_cfg = brand_guidelines.get("channels", {})
        enabled_channels = [
            ch
            for ch, cfg in channels_cfg.items()
            if isinstance(cfg, dict) and cfg.get("enabled")
        ]
        # Filter to platforms that support mockups; fall back to all mockup platforms if none enabled
        mockup_platforms = ["instagram", "facebook", "linkedin", "x"]
        platforms_to_mock = [p for p in enabled_channels if p in mockup_platforms]
        if not platforms_to_mock:
            platforms_to_mock = mockup_platforms

        for platform in platforms_to_mock:
            try:
                mockup_bytes = generate_mockup(
                    image_data,
                    caption,
                    platform,
                    username=brand_handle,
                    display_name=brand_name,
                    avatar_initial=brand_initial,
                    avatar_logo_data=avatar_logo_data,
                )
                obj_name = f"{brand_id}/{item_id}/mockup_{platform}.png"
                await async_upload_file(
                    "content-images", obj_name, mockup_bytes, "image/png"
                )
                mockup_urls[platform] = f"content-images/{obj_name}"
                logger.info("Generated %s mockup for %s", platform, item_id)
            except Exception:
                logger.warning("Failed to generate %s mockup", platform, exc_info=True)

        return {"mockup_urls": mockup_urls}

    except Exception:
        logger.exception("Mockup generation failed")
        return {"mockup_urls": {}}


async def store_content_node(state: ContentState) -> dict[str, Any]:
    """Persist generated content to the database and upload images to MinIO."""
    await update_agent_run_step(state.get("run_id", ""), "store_content", _STEP_INDEX["store_content"])
    brand_id = state["brand_id"]

    # Upload raw generated image to MinIO if not already there
    generated_image_url = state.get("generated_image")
    if generated_image_url and not generated_image_url.startswith("content-images/"):
        import base64 as _b64
        import httpx

        try:
            if generated_image_url.startswith("data:"):
                _, b64_part = generated_image_url.split(",", 1)
                image_data = _b64.b64decode(b64_part)
            else:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(generated_image_url)
                    resp.raise_for_status()
                    image_data = resp.content

            await async_ensure_bucket("content-images")
            object_name = f"{brand_id}/{state['calendar_item_id']}/background.png"
            await async_upload_file(
                "content-images", object_name, image_data, "image/png"
            )
            generated_image_url = f"content-images/{object_name}"
        except Exception:
            logger.exception("Failed to upload generated image to MinIO")

    # Use branded image as primary if available, fall back to raw generated
    primary_image = state.get("branded_image") or generated_image_url

    content_record = {
        "brand_id": brand_id,
        "calendar_item_id": state["calendar_item_id"],
        "hook": state.get("hook", ""),
        "caption": state.get("caption", ""),
        "hashtags": json.dumps(state.get("hashtags", [])),
        "cta": state.get("cta", ""),
        "product_image_url": state.get("product_image"),
        "generated_image_url": primary_image,
        "platform_adaptations": json.dumps(state.get("platform_adaptations", {})),
        # Extra metadata merged into generation_metadata by store_content()
        "metadata": {
            "raw_image": generated_image_url,
            "branded_image": state.get("branded_image"),
            "mockup_urls": state.get("mockup_urls", {}),
        },
        "status": "in_review",
    }

    # Validate content record before DB insert
    try:
        ContentRecordValidator(**content_record)
    except Exception as ve:
        logger.error(
            "Content validation failed for calendar item %s: %s",
            state["calendar_item_id"],
            ve,
        )
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"Content validation failed: {ve}",
            ],
        }

    content_id = await store_content(content_record)
    logger.info(
        "Stored content %s for calendar item %s", content_id, state["calendar_item_id"]
    )

    # Transition calendar item status to 'in_review'
    if state.get("calendar_item_id"):
        await execute_update(
            "UPDATE calendar_items SET status = 'in_review' WHERE id = :id",
            {"id": state["calendar_item_id"]},
        )

    # Auto-create approval record so it appears in the Approvals page
    try:
        from shared.tools.database import execute_query
        from uuid import uuid4

        # Find a manager/admin user to assign as reviewer
        reviewers = await execute_query(
            "SELECT id FROM users WHERE role IN ('admin', 'manager') AND is_active = true LIMIT 1"
        )
        if reviewers:
            approval_id = str(uuid4())
            await execute_update(
                "INSERT INTO approvals (id, content_id, calendar_item_id, reviewer_id, status) "
                "VALUES (:id, :content_id, :calendar_item_id, :reviewer_id, 'pending')",
                {
                    "id": approval_id,
                    "content_id": content_id,
                    "calendar_item_id": state["calendar_item_id"],
                    "reviewer_id": str(reviewers[0]["id"]),
                },
            )
            logger.info("Created approval %s for content %s", approval_id, content_id)
        else:
            logger.warning("No manager/admin user found — skipping approval creation")
    except Exception as appr_exc:
        logger.warning("Failed to create approval record: %s", appr_exc)

    return {
        "status": "in_review",
        "needs_manual_image": state.get("needs_manual_image", False),
    }
