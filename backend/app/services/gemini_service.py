"""Gemini API service for product image operations.

Uses Google's Nano Banana (Gemini native image generation) ONLY for:
- Replacing generic products in marketing images with real product photos

Product images themselves are sourced from the WEB (real photos, never AI-generated).
"""

import logging
import re
from io import BytesIO
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Model priority for image editing/replacement
IMAGE_MODELS = [
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
]


def _get_client():
    """Lazy import and create Gemini client."""
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _get_types():
    """Lazy import Gemini types."""
    from google.genai import types

    return types


# ── Web Image Search (real product photos only) ─────────────────────────


async def search_product_images(
    product_name: str,
    product_description: str = "",
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Search the web for real product images using DuckDuckGo.

    Returns list of dicts with: url, content_type, size_bytes, image_data (bytes).
    These are REAL photos from the web, never AI-generated.
    """
    query = f"{product_name} product official photo"
    if product_description:
        # Add key terms from description for better results
        query = f"{product_name} {product_description[:50]} product photo"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    }

    image_urls: list[str] = []

    # Strategy 1: DuckDuckGo image API
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(
                "https://duckduckgo.com/",
                params={"q": query, "iax": "images", "ia": "images"},
                headers=headers,
            )
            # Try multiple vqd patterns (DuckDuckGo changes these)
            vqd = None
            for pattern in [r'vqd=([^&"\']+)', r'vqd%3D([^&"\']+)', r'"vqd":"([^"]+)"']:
                m = re.search(pattern, resp.text)
                if m:
                    vqd = m.group(1)
                    break
            if vqd:
                img_resp = await client.get(
                    "https://duckduckgo.com/i.js",
                    params={
                        "l": "us-en",
                        "o": "json",
                        "q": query,
                        "vqd": vqd,
                        "f": ",size:Medium,",
                    },
                    headers=headers,
                )
                if img_resp.status_code == 200:
                    data = img_resp.json()
                    for result in data.get("results", [])[:20]:
                        img_url = result.get("image", "")
                        if img_url and img_url.startswith("http"):
                            image_urls.append(img_url)
            else:
                logger.info("DuckDuckGo vqd token not found for '%s'", product_name)
    except Exception as e:
        logger.warning("DuckDuckGo image search failed for '%s': %s", product_name, e)

    # Strategy 2: DuckDuckGo HTML fallback
    if not image_urls:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": f"{product_name} product image"},
                    headers=headers,
                )
                for url in re.findall(r'href="(https?://[^"]+)"', resp.text):
                    if any(
                        ext in url.lower() for ext in [".jpg", ".jpeg", ".png", ".webp"]
                    ):
                        if "duckduckgo" not in url:
                            image_urls.append(url)
        except Exception as e:
            logger.warning(
                "DuckDuckGo HTML fallback failed for '%s': %s", product_name, e
            )

    # Strategy 3: Direct manufacturer website guess
    if not image_urls:
        # Try common product image hosting patterns
        brand_slug = product_name.split()[0].lower() if product_name else ""
        if brand_slug:
            guess_urls = [
                f"https://www.{brand_slug}.com/images/{product_name.replace(' ', '-').lower()}.jpg",
            ]
            image_urls.extend(guess_urls)

    logger.info("Found %d candidate image URLs for '%s'", len(image_urls), product_name)

    # Download and validate images
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for url in image_urls:
            if len(results) >= max_results:
                break
            try:
                resp = await client.get(url, headers=headers)
                ct = resp.headers.get("content-type", "")
                if not any(t in ct for t in ["image/jpeg", "image/png", "image/webp"]):
                    continue
                if len(resp.content) < 10000:  # Skip tiny images (icons, thumbnails)
                    continue
                if len(resp.content) > 10_000_000:  # Skip huge files
                    continue

                results.append(
                    {
                        "url": url,
                        "content_type": ct.split(";")[0],
                        "size_bytes": len(resp.content),
                        "image_data": resp.content,
                    }
                )
                logger.info(
                    "Downloaded product image %d for '%s' from %s (%d KB)",
                    len(results),
                    product_name,
                    url[:60],
                    len(resp.content) // 1024,
                )
            except Exception as e:
                logger.debug("Image download failed for URL %s: %s", url, e)
                continue

    logger.info("Found %d product images for '%s'", len(results), product_name)
    return results


# ── Gemini Product Replacement (swap generic → real product) ─────────────


async def replace_product_in_image(
    marketing_image_bytes: bytes,
    product_image_bytes: bytes,
    product_name: str,
) -> bytes | None:
    """Replace a generic product in a marketing image with a real product photo.

    Uses Gemini Nano Banana's multi-image editing to swap the product while
    keeping the rest of the scene intact.

    Args:
        marketing_image_bytes: The AI-generated marketing/lifestyle image (with generic product)
        product_image_bytes: The real product photo from the product image gallery
        product_name: Name of the product for context

    Returns:
        PNG bytes of the edited image, or None on failure
    """
    from PIL import Image as PILImage

    client = _get_client()
    types = _get_types()

    marketing_img = PILImage.open(BytesIO(marketing_image_bytes))
    product_img = PILImage.open(BytesIO(product_image_bytes))

    prompt = (
        f"I have two images. Image 1 is a lifestyle marketing photo that contains a generic/placeholder "
        f"product. Image 2 is the real product photo of '{product_name}'. "
        f"Please edit Image 1 to replace the generic product with the product shown in Image 2. "
        f"Keep the exact branding, labels, and appearance from Image 2 on the product. "
        f"Keep everything else in Image 1 exactly the same — the background, setting, "
        f"lighting, props, and overall composition. "
        f"The product should look naturally integrated with correct lighting, shadows, "
        f"and perspective matching the original scene."
    )

    for model in IMAGE_MODELS:
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, marketing_img, product_img],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )

            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    logger.info(
                        "Product replacement successful for '%s' using %s",
                        product_name,
                        model,
                    )
                    return part.inline_data.data

            logger.warning(
                "No image in Gemini response for product replacement (model=%s)", model
            )

        except Exception as e:
            logger.warning(
                "Product replacement failed with %s for '%s': %s",
                model,
                product_name,
                e,
            )
            continue

    return None
