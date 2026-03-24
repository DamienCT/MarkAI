"""Content generation workflow nodes — real LLM, DB, and image sourcing calls."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, generate_image
from shared.tools.database import (
    get_brand,
    get_brand_config,
    get_calendar_item,
    get_latest_strategy,
    store_content,
)
from shared.tools.storage import upload_file, ensure_bucket

from workflows.content.state import ContentState
from workflows.content.image_sourcing import source_product_image

logger = logging.getLogger(__name__)


async def load_context(state: ContentState) -> dict[str, Any]:
    """Load brand, calendar item, and strategy from the database."""
    brand_id = state["brand_id"]
    item_id = state["calendar_item_id"]

    brand = await get_brand(brand_id)
    calendar_item = await get_calendar_item(item_id)
    strategy = await get_latest_strategy(brand_id)

    if not brand:
        return {"errors": [*(state.get("errors") or []), "Brand not found"], "status": "failed"}
    if not calendar_item:
        return {"errors": [*(state.get("errors") or []), "Calendar item not found"], "status": "failed"}

    return {
        "brand": brand,
        "calendar_item": calendar_item,
        "strategy": strategy.get("data", strategy) if strategy else {},
    }


async def generate_hook(state: ContentState) -> dict[str, Any]:
    """Generate an attention-grabbing hook via LLM."""
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})
    strategy = state.get("strategy", {})

    prompt = [
        {"role": "system", "content": (
            "You are a social media copywriter. Write a compelling hook (opening line) "
            "for a social media post. The hook should stop the scroll and be under 15 words. "
            "Return ONLY the hook text, nothing else."
        )},
        {"role": "user", "content": (
            f"Brand: {brand.get('name', '')}\n"
            f"Platform: {item.get('platform', '')}\n"
            f"Content type: {item.get('content_type', '')}\n"
            f"Theme: {item.get('theme', '')}\n"
            f"Brand voice: {json.dumps(strategy.get('positioning', {}).get('brand_voice', ''), default=str)}"
        )},
    ]
    hook = await chat_completion(prompt, temperature=0.8)
    return {"hook": hook.strip().strip('"')}


async def generate_caption(state: ContentState) -> dict[str, Any]:
    """Generate the full caption body via LLM."""
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})
    strategy = state.get("strategy", {})

    prompt = [
        {"role": "system", "content": (
            "You are a social media copywriter. Write a compelling caption for a social media post. "
            "Start with the provided hook. Keep it engaging, on-brand, and appropriate for the platform. "
            "Return ONLY the caption text."
        )},
        {"role": "user", "content": (
            f"Brand: {brand.get('name', '')}\n"
            f"Hook: {state.get('hook', '')}\n"
            f"Platform: {item.get('platform', '')}\n"
            f"Theme: {item.get('theme', '')}\n"
            f"Brand voice: {json.dumps(strategy.get('positioning', {}), default=str)[:2000]}"
        )},
    ]
    caption = await chat_completion(prompt, temperature=0.7)
    return {"caption": caption.strip()}


async def generate_hashtags(state: ContentState) -> dict[str, Any]:
    """Generate relevant hashtags via LLM."""
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})

    prompt = [
        {"role": "system", "content": (
            "You are a social media strategist. Generate 15-25 relevant hashtags for this post. "
            "Mix broad, niche, and branded hashtags. Return ONLY a JSON array of strings (no # prefix)."
        )},
        {"role": "user", "content": (
            f"Brand: {brand.get('name', '')}\n"
            f"Caption: {state.get('caption', '')[:500]}\n"
            f"Platform: {item.get('platform', '')}\n"
            f"Theme: {item.get('theme', '')}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.6)
    try:
        hashtags = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        hashtags = [tag.strip().strip("#") for tag in result.split() if tag.strip()]
    return {"hashtags": hashtags}


async def source_product_image_node(state: ContentState) -> dict[str, Any]:
    """Source a real product image — NEVER AI-generate product photos."""
    item = state.get("calendar_item", {})
    brand = state.get("brand", {})
    config = await get_brand_config(state["brand_id"])

    product_sku = item.get("product_sku")
    product_name = item.get("product_name") or item.get("theme", "")
    supplier_url = config.get("supplier_website") if config else None

    if not product_sku and not product_name:
        return {"product_image": None, "needs_manual_image": False}

    result = await source_product_image(
        product_sku=product_sku,
        product_name=product_name,
        supplier_url=supplier_url,
        brand_name=brand.get("name", ""),
    )

    return {
        "product_image": result.image_url,
        "product_image_source": result.source,
        "needs_manual_image": result.needs_manual,
    }


async def generate_background(state: ContentState) -> dict[str, Any]:
    """Generate a background/lifestyle image via AI.  This is for backgrounds
    and creative elements ONLY — never for product images."""
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})

    prompt_text = (
        f"Create a clean, professional social media background image for a {item.get('platform', 'instagram')} post. "
        f"Brand: {brand.get('name', '')}. Theme: {item.get('theme', '')}. "
        f"Style: modern, minimal, brand-appropriate lifestyle background. "
        f"Do NOT include any products, text, logos, or watermarks."
    )

    try:
        image_url = await generate_image(prompt_text)
        return {"generated_image": image_url}
    except Exception:
        logger.exception("Background image generation failed")
        return {"generated_image": None}


ALL_CHANNELS = [
    "instagram", "facebook", "linkedin", "youtube",
    "tiktok", "x", "website_blog", "teams",
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
    """Create platform-specific adaptations of the content via LLM for all 8 channels."""
    source_platform = state.get("calendar_item", {}).get("platform", "instagram")

    # Build per-platform spec block for the prompt
    spec_lines = "\n".join(
        f"- {name}: {spec}" for name, spec in PLATFORM_SPECS.items()
    )

    prompt = [
        {"role": "system", "content": (
            "You are a social media and content marketing expert. Adapt the following content "
            "for each platform below, respecting each platform's constraints and best practices.\n\n"
            "Platform specifications:\n"
            f"{spec_lines}\n\n"
            "Return JSON with platform names as keys. Each platform object must contain:\n"
            "  caption (string), hashtags (array of strings without # prefix), cta (string), "
            "  optimal_time (string), format_notes (string).\n"
            "For youtube also include: title, description, tags, thumbnail_prompt.\n"
            "For website_blog also include: markdown_body, meta_description, seo_keywords (array).\n"
            "For teams also include: announcement_text (plain text)."
        )},
        {"role": "user", "content": (
            f"Original platform: {source_platform}\n"
            f"Hook: {state.get('hook', '')}\n"
            f"Caption: {state.get('caption', '')}\n"
            f"Hashtags: {json.dumps(state.get('hashtags', []))}\n"
            f"Adapt for these platforms: {', '.join(ALL_CHANNELS)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    try:
        adaptations = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        adaptations = {source_platform: {"caption": state.get("caption", ""), "hashtags": state.get("hashtags", [])}}

    # Extract CTA from the primary platform adaptation
    primary = adaptations.get(source_platform, {})
    cta = primary.get("cta", "")

    return {"platform_adaptations": adaptations, "cta": cta}


async def store_content_node(state: ContentState) -> dict[str, Any]:
    """Persist generated content to the database and upload images to MinIO."""
    brand_id = state["brand_id"]

    # Upload generated image to MinIO if available
    generated_image_url = state.get("generated_image")
    if generated_image_url:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(generated_image_url)
                resp.raise_for_status()
                image_data = resp.content

            ensure_bucket("content-images")
            object_name = f"{brand_id}/{state['calendar_item_id']}/background.png"
            upload_file("content-images", object_name, image_data, "image/png")
            generated_image_url = f"content-images/{object_name}"
        except Exception:
            logger.exception("Failed to upload generated image to MinIO")

    content_record = {
        "brand_id": brand_id,
        "calendar_item_id": state["calendar_item_id"],
        "hook": state.get("hook", ""),
        "caption": state.get("caption", ""),
        "hashtags": json.dumps(state.get("hashtags", [])),
        "cta": state.get("cta", ""),
        "product_image_url": state.get("product_image"),
        "generated_image_url": generated_image_url,
        "platform_adaptations": json.dumps(state.get("platform_adaptations", {})),
        "status": "in_review",
    }

    content_id = await store_content(content_record)
    logger.info("Stored content %s for calendar item %s", content_id, state["calendar_item_id"])

    return {
        "status": "in_review",
        "needs_manual_image": state.get("needs_manual_image", False),
    }
