"""Content generation workflow nodes — real LLM, DB, and image sourcing calls."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from shared.llm import chat_completion, generate_image, parse_llm_json
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

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are an expert social media copywriter. "
                    "Write a scroll-stopping hook (opening line) for a social media post. "
                    "The hook MUST be under 8 words and under 50 characters. "
                    "This text will be overlaid on an image, so brevity is critical. "
                    "Write a complete, punchy short sentence — never leave it unfinished or truncated. "
                    "Return ONLY the hook text, nothing else."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"BRAND: {sanitize_for_prompt(brand.get('name', ''))}\n"
                    f"BRAND VOICE: {sanitize_for_prompt(str(positioning.get('brand_voice', '')))}\n"
                    f"BRAND ARCHETYPE: {sanitize_for_prompt(str(positioning.get('brand_archetype', '')))}\n\n"
                    f"THIS POST:\n"
                    f"  Platform: {sanitize_for_prompt(item.get('channel', ''))}\n"
                    f"  Content type: {sanitize_for_prompt(item.get('content_type', item.get('item_type', '')))}\n"
                    f"  Theme: {sanitize_for_prompt(item.get('theme', ''))}\n"
                    f"  Sub-theme: {sanitize_for_prompt(item.get('weekly_sub_theme', ''))}\n"
                    f"  Brief: {sanitize_for_prompt(item.get('content_brief', item.get('description', '')))}\n"
                    f"  Pillar: {sanitize_for_prompt(relevant_pillar.get('name', ''))}\n\n"
                    f"TARGET AUDIENCE: {sanitize_for_prompt(relevant_audience.get('name', ''))}\n"
                    f"  Pain points: {sanitize_for_prompt(pain_points)}\n"
                    f"  Tone preference: {sanitize_for_prompt(tone_pref)}\n\n"
                    f"PRODUCT (if applicable): {sanitize_for_prompt(product.get('name', 'N/A'))} — "
                    f"{sanitize_for_prompt(product.get('description', ''))}\n\n"
                    f"RECENTLY POSTED HOOKS (do NOT repeat similar openings):\n{recent_hooks}\n\n"
                    f"TOP PERFORMING HOOKS (learn from these):\n{top_hooks}"
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

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are an expert social media copywriter. "
                    "Write a compelling caption for a social media post. "
                    "Start with the provided hook. Keep it engaging, on-brand, and appropriate for the platform. "
                    "AIM FOR MEDIUM LENGTH: 3-5 short paragraphs. Include a strong opening hook, "
                    "1-2 paragraphs of substance (product benefits, lifestyle value, or educational insight), "
                    "and a clear CTA with the brand URL. Do NOT be overly long or overly terse. "
                    "Return ONLY the caption text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"BRAND: {sanitize_for_prompt(brand.get('name', ''))}\n"
                    f"BRAND URL: {sanitize_for_prompt(brand_url)}\n\n"
                    f"FULL BRAND POSITIONING:\n{positioning_text}\n\n"
                    f"CONTENT PILLAR: {sanitize_for_prompt(relevant_pillar.get('name', ''))}\n"
                    f"  Description: {sanitize_for_prompt(pillar_desc)}\n\n"
                    f"TARGET AUDIENCE: {sanitize_for_prompt(relevant_audience.get('name', ''))}\n"
                    f"  Pain points: {sanitize_for_prompt(pain_points)}\n"
                    f"  Content preferences: {sanitize_for_prompt(audience_prefs)}\n\n"
                    f"{product_section}"
                    f"THIS POST:\n"
                    f"  Hook: {sanitize_for_prompt(state.get('hook', ''))}\n"
                    f"  Platform: {sanitize_for_prompt(item.get('channel', ''))}\n"
                    f"  Theme: {sanitize_for_prompt(item.get('theme', ''))}\n"
                    f"  Sub-theme: {sanitize_for_prompt(item.get('weekly_sub_theme', ''))}\n"
                    f"  Brief: {sanitize_for_prompt(item.get('content_brief', item.get('description', '')))}\n\n"
                    f"STRATEGY GUIDANCE FOR THIS MONTH:\n{sanitize_for_prompt(month_context[:5000])}\n\n"
                    f"RECENTLY POSTED CAPTIONS (do NOT repeat similar themes or angles):\n{recent_captions}\n\n"
                    f"TOP PERFORMING CAPTIONS (learn from these):\n{top_captions}\n\n"
                    f"CTA GUIDANCE: Include a call-to-action with brand URL: {sanitize_for_prompt(brand_url)}"
                ),
            },
        ]
        caption = await chat_completion(prompt, temperature=0.7, max_tokens=2048)
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

        prompt = [
            {
                "role": "system",
                "content": (
                    "You are a social media strategist. "
                    "Generate relevant hashtags for this post. "
                    "Mix broad, niche, and branded hashtags. "
                    'Return JSON: {"hashtags": ["tag1", "tag2", ...]}. '
                    "Each tag is a single word, alphanumeric only, no '#' prefix, "
                    "no spaces, no punctuation."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"BRAND: {sanitize_for_prompt(brand_name)}\n"
                    f"PLATFORM: {sanitize_for_prompt(channel)}\n"
                    f"PLATFORM HASHTAG LIMIT: {platform_limit}\n\n"
                    f"FULL CAPTION:\n{sanitize_for_prompt(state.get('caption', ''))}\n\n"
                    f"THEME: {sanitize_for_prompt(item.get('theme', ''))}\n\n"
                    f"{top_hashtags_info}\n\n"
                    f"ALWAYS INCLUDE branded hashtag: {brand_slug}"
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


async def generate_background(state: ContentState) -> dict[str, Any]:
    """Generate a background/lifestyle image via AI.

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

    if is_lifestyle_only or not has_product_image:
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

# Platform-specific constraints used in the adaptation prompt
PLATFORM_SPECS = {
    "instagram": "Square/portrait image, 2200 char caption max, up to 30 hashtags.",
    "facebook": "Landscape image, longer text allowed, 3-5 hashtags.",
    "linkedin": "Professional tone, article-style, up to 3 hashtags.",
    "youtube": "Title (100 chars max), description (5000 chars max), tags list, thumbnail prompt.",
    "tiktok": "Short punchy caption, trending hashtags, vertical video brief.",
    "x": "280 chars max per tweet, 2-3 hashtags, thread format for longer content.",
    "website_blog": "Full markdown article with H1/H2/H3 headings, meta description, SEO keywords. NOT auto-published.",
    "teams": "Internal announcement format, plain text, concise.",
}


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

    # Build per-platform spec block only for enabled channels
    spec_lines = "\n".join(
        f"- {name}: {spec}"
        for name, spec in PLATFORM_SPECS.items()
        if name in channels_to_adapt
    )

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

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a social media and content marketing expert. "
                "Adapt the following content "
                "for each platform below, respecting each platform's constraints and best practices.\n\n"
                "Platform specifications:\n"
                f"{spec_lines}\n\n"
                "Return JSON with platform names as keys. Each platform object must contain:\n"
                "  caption (string), hashtags (array of strings without # prefix), cta (string), "
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

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[
                f"Replace the generic product in Image 1 with the real product from Image 2 ('{product_name}'). "
                f"Keep everything else exactly the same. Match lighting and perspective.",
                marketing_img,
                product_img,
            ],
            config=gtypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                result_data = part.inline_data.data
                # Gemini may return a different size — normalize back to input dims
                result_img = PILImage.open(BytesIO(result_data))
                if result_img.size != input_size:
                    logger.info(
                        "Gemini returned %s, normalizing to %s",
                        result_img.size, input_size,
                    )
                    result_img = result_img.resize(input_size, PILImage.LANCZOS)
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
