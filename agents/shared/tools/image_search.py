"""Product image finder.  Searches supplier websites and the web for real
product images.  NEVER generates AI images for products — only sources real
photographs."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from shared.tools.browser import scrape_product_images
from shared.tools.web_search import web_search

logger = logging.getLogger(__name__)


@dataclass
class ProductImage:
    url: str
    source: str  # "supplier", "web", "bc"
    product_name: str
    confidence: float  # 0-1


async def search_supplier_images(
    supplier_url: str,
    product_name: str,
) -> list[ProductImage]:
    """Scrape product images from a known supplier website."""
    try:
        images = await scrape_product_images(supplier_url)
        return [
            ProductImage(
                url=img,
                source="supplier",
                product_name=product_name,
                confidence=0.9,
            )
            for img in images
        ]
    except Exception:
        logger.exception("Failed to scrape supplier images from %s", supplier_url)
        return []


async def search_web_images(product_name: str, brand: str = "") -> list[ProductImage]:
    """Search the web for product images using DuckDuckGo."""
    query = f"{brand} {product_name} product photo".strip()
    results = await web_search(query, max_results=5)

    found: list[ProductImage] = []
    for result in results:
        try:
            images = await scrape_product_images(result.url)
            for img in images[:3]:
                found.append(
                    ProductImage(
                        url=img,
                        source="web",
                        product_name=product_name,
                        confidence=0.5,
                    )
                )
        except Exception:
            logger.debug("Failed to scrape images from %s", result.url)
            continue

    return found


async def find_product_image(
    product_name: str,
    supplier_url: str | None = None,
    brand: str = "",
    bc_image_url: str | None = None,
) -> ProductImage | None:
    """Unified image search.  Priority: BC -> supplier -> web search.

    Returns the best image found, or None if nothing is available.  Never
    generates AI images.
    """
    # 1. Business Central image (highest priority)
    if bc_image_url:
        logger.info("Using BC image for %s", product_name)
        return ProductImage(
            url=bc_image_url,
            source="bc",
            product_name=product_name,
            confidence=1.0,
        )

    # 2. Supplier website
    if supplier_url:
        supplier_images = await search_supplier_images(supplier_url, product_name)
        if supplier_images:
            logger.info("Found supplier image for %s", product_name)
            return supplier_images[0]

    # 3. Web search
    web_images = await search_web_images(product_name, brand)
    if web_images:
        logger.info("Found web image for %s", product_name)
        return web_images[0]

    logger.warning("No real product image found for %s", product_name)
    return None
