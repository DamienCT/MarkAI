"""Real product image sourcing pipeline.

Priority order:
  1. Business Central item card (via the BC API v2.0 — shared/tools/bc_api.py)
  2. Supplier website (via browser-worker scraping)
  3. Web search (DuckDuckGo + browser-worker)

If no real image is found, sets needs_manual=True.
NEVER AI-generates product images.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from shared.tools.fabric import get_product_image_from_bc
from shared.tools.image_search import find_product_image
from shared.tools.browser import scrape_product_images

logger = logging.getLogger(__name__)


@dataclass
class ImageSourcingResult:
    image_url: str | None
    source: str | None  # "bc", "supplier", "web"
    needs_manual: bool
    confidence: float


async def source_product_image(
    product_sku: str | None = None,
    product_name: str | None = None,
    supplier_url: str | None = None,
    brand_name: str = "",
) -> ImageSourcingResult:
    """Run the full image sourcing pipeline for a product.

    Returns the best real product image found, or flags that manual
    sourcing is required.  Never generates AI images for products.
    """
    # ── 1. Business Central item card (authoritative) ──────────────────
    # The client's own ERP picture outranks anything scraped or searched, so
    # it short-circuits the rest of the chain at confidence 1.0.
    if product_sku:
        try:
            bc_url = await get_product_image_from_bc(product_sku)
            if bc_url:
                logger.info("Found BC image for %s: %s", product_sku, bc_url)
                return ImageSourcingResult(
                    image_url=bc_url, source="bc", needs_manual=False, confidence=1.0
                )
        except Exception:
            logger.exception("BC image lookup failed for %s", product_sku)

    # ── 2. Supplier website ────────────────────────────────────────────
    if supplier_url and product_name:
        try:
            images = await scrape_product_images(supplier_url)
            if images:
                logger.info("Found supplier image for %s", product_name)
                return ImageSourcingResult(
                    image_url=images[0],
                    source="supplier",
                    needs_manual=False,
                    confidence=0.85,
                )
        except Exception:
            logger.exception("Supplier image scrape failed for %s", supplier_url)

    # ── 3. Web search ──────────────────────────────────────────────────
    if product_name:
        try:
            result = await find_product_image(
                product_name=product_name,
                supplier_url=supplier_url,
                brand=brand_name,
            )
            if result:
                logger.info(
                    "Found web image for %s from %s", product_name, result.source
                )
                return ImageSourcingResult(
                    image_url=result.url,
                    source=result.source,
                    needs_manual=False,
                    confidence=result.confidence,
                )
        except Exception:
            logger.exception("Web image search failed for %s", product_name)

    # ── No image found ─────────────────────────────────────────────────
    logger.warning(
        "No real product image found for sku=%s name=%s — flagging needs_manual",
        product_sku,
        product_name,
    )
    return ImageSourcingResult(
        image_url=None, source=None, needs_manual=True, confidence=0.0
    )
