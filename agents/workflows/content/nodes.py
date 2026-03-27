"""Content generation workflow nodes — real LLM, DB, and image sourcing calls."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, generate_image
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
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
        "strategy": strategy.get("output_payload", strategy) if strategy else {},
    }


async def generate_hook(state: ContentState) -> dict[str, Any]:
    """Generate an attention-grabbing hook via LLM."""
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})
    strategy = state.get("strategy", {})

    prompt = [
        {"role": "system", "content": (
            "You are a social media copywriter. Create content appropriate for the Mauritian market. "
            "Consider bilingual audience (English/French/Creole), local culture, tropical lifestyle, and Indian Ocean region context. "
            "Write a compelling hook (opening line) for a social media post. The hook should stop the scroll and be under 15 words. "
            "Naturally weave in French or Kreol Morisien phrases where appropriate for local resonance. "
            "Return ONLY the hook text, nothing else."
        )},
        {"role": "user", "content": (
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}\n"
            f"Platform: {sanitize_for_prompt(item.get('platform', ''))}\n"
            f"Content type: {sanitize_for_prompt(item.get('content_type', ''))}\n"
            f"Theme: {sanitize_for_prompt(item.get('theme', ''))}\n"
            f"Brand voice: {sanitize_json_for_prompt(strategy.get('positioning', {}).get('brand_voice', ''))}"
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
            "You are a social media copywriter. Create content appropriate for the Mauritian market. "
            "Consider bilingual audience (English/French/Creole), local culture, tropical lifestyle, and Indian Ocean region context. "
            "Write a compelling caption for a social media post. "
            "Start with the provided hook. Keep it engaging, on-brand, and appropriate for the platform. "
            "Naturally integrate French or Kreol Morisien phrases where they add warmth and local flavour "
            "(e.g. greetings, food terms, common expressions). Primary language should be English. "
            "Return ONLY the caption text."
        )},
        {"role": "user", "content": (
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}\n"
            f"Hook: {sanitize_for_prompt(state.get('hook', ''))}\n"
            f"Platform: {sanitize_for_prompt(item.get('platform', ''))}\n"
            f"Theme: {sanitize_for_prompt(item.get('theme', ''))}\n"
            f"Brand voice: {sanitize_json_for_prompt(strategy.get('positioning', {}), max_length=2000)}"
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
            "You are a social media strategist. Create content appropriate for the Mauritian market. "
            "Consider bilingual audience (English/French/Creole), local culture, tropical lifestyle, and Indian Ocean region context. "
            "Generate 15-25 relevant hashtags for this post. "
            "Mix broad, niche, and branded hashtags. Include relevant local hashtags (e.g. Mauritius, MauritiusIsland, IndianOcean). "
            "Include a few French/Kreol hashtags where appropriate (e.g. IleMaurice, LaVieMorisien, BienEtre). "
            "Return ONLY a JSON array of strings (no # prefix)."
        )},
        {"role": "user", "content": (
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}\n"
            f"Caption: {sanitize_for_prompt(state.get('caption', '')[:500])}\n"
            f"Platform: {sanitize_for_prompt(item.get('platform', ''))}\n"
            f"Theme: {sanitize_for_prompt(item.get('theme', ''))}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.6)
    try:
        hashtags = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        hashtags = [tag.strip().strip("#") for tag in result.split() if tag.strip()]
    return {"hashtags": hashtags}


async def source_product_image_node(state: ContentState) -> dict[str, Any]:
    """Source a real product image from the product image gallery.

    Rules:
    - NEVER AI-generate product photos
    - Only use images from the product's image_urls gallery (real web photos)
    - If no gallery images exist, mark as lifestyle-only (no product in image)
    """
    item = state.get("calendar_item", {})
    brand = state.get("brand", {})
    brand_id = state["brand_id"]

    product_sku = item.get("product_sku")
    product_name = item.get("product_name") or item.get("theme", "")

    if not product_sku and not product_name:
        return {"product_image": None, "needs_manual_image": False, "is_lifestyle_only": True}

    # Try to find the product in the database and check its image gallery
    from shared.tools.database import execute_query

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
        return {"product_image": None, "needs_manual_image": False, "is_lifestyle_only": True}

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
    logger.info("Product '%s' has no gallery images — lifestyle only, no product placement", product_name)
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
    brand = state.get("brand", {})
    item = state.get("calendar_item", {})
    is_lifestyle_only = state.get("is_lifestyle_only", True)
    has_product_image = state.get("product_image") is not None

    if is_lifestyle_only or not has_product_image:
        # Pure lifestyle — no product in the image
        prompt_text = (
            f"Create a clean, professional social media lifestyle image for a {sanitize_for_prompt(item.get('platform', 'instagram'))} post. "
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}. Theme: {sanitize_for_prompt(item.get('theme', ''))}. "
            f"Style: modern, aspirational wellness lifestyle in a tropical Mauritius setting. "
            f"Do NOT include any products, text, logos, or watermarks. "
            f"Focus on the lifestyle and mood, not products."
        )
    else:
        # Scene with generic product placeholder — will be replaced by Gemini later
        prompt_text = (
            f"Create a professional social media product lifestyle photo for a {sanitize_for_prompt(item.get('platform', 'instagram'))} post. "
            f"Brand: {sanitize_for_prompt(brand.get('name', ''))}. Theme: {sanitize_for_prompt(item.get('theme', ''))}. "
            f"Include a generic health/wellness product (a simple pouch or box) placed naturally in the scene. "
            f"Style: modern, aspirational wellness lifestyle in a tropical setting. "
            f"The product should be clearly visible and will be replaced with the real product later. "
            f"Do NOT include any text, logos, or watermarks on the product."
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
            "You are a social media and content marketing expert. Create content appropriate for the Mauritian market. "
            "Consider bilingual audience (English/French/Creole), local culture, tropical lifestyle, and Indian Ocean region context. "
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
        )},
        {"role": "user", "content": (
            f"Original platform: {sanitize_for_prompt(source_platform)}\n"
            f"Hook: {sanitize_for_prompt(state.get('hook', ''))}\n"
            f"Caption: {sanitize_for_prompt(state.get('caption', ''))}\n"
            f"Hashtags: {sanitize_json_for_prompt(state.get('hashtags', []))}\n"
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


async def _replace_product_in_generated_image(state: ContentState, image_data: bytes) -> bytes:
    """If we have a real product image, use Gemini to replace the generic product."""
    product_image_url = state.get("product_image")
    is_lifestyle_only = state.get("is_lifestyle_only", True)

    if is_lifestyle_only or not product_image_url:
        return image_data  # No replacement needed

    try:
        import httpx as _httpx

        # Download the product image from gallery
        async with _httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(product_image_url)
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
                logger.info("Gemini product replacement successful for %s", product_name)
                return part.inline_data.data

    except Exception as exc:
        logger.warning("Gemini product replacement failed: %s — using original image", exc)

    return image_data


async def store_content_node(state: ContentState) -> dict[str, Any]:
    """Persist generated content to the database and upload images to MinIO."""
    brand_id = state["brand_id"]

    # Upload generated image to MinIO if available
    generated_image_url = state.get("generated_image")
    if generated_image_url:
        import base64 as _b64
        import httpx
        try:
            # Handle both data URIs (gpt-image-1.5) and regular URLs (older models)
            if generated_image_url.startswith("data:"):
                # Extract base64 data from data URI
                _, b64_part = generated_image_url.split(",", 1)
                image_data = _b64.b64decode(b64_part)
            else:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.get(generated_image_url)
                    resp.raise_for_status()
                    image_data = resp.content

            # If we have a real product image, replace the generic product via Gemini
            image_data = await _replace_product_in_generated_image(state, image_data)

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
