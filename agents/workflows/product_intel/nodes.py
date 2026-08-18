"""Product intelligence workflow nodes — real data from Fabric, browser, LLM, DB."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, parse_llm_json
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.browser import extract_page
from shared.tools.database import get_brand, get_products, upsert_product
from shared.tools.fabric import execute_sql
from shared.tools.web_search import web_search
from workflows.content.image_sourcing import source_product_image

from workflows.product_intel.state import ProductIntelState

logger = logging.getLogger(__name__)


async def discover_brands(state: ProductIntelState) -> dict[str, Any]:
    """Group products by vendor and use LLM to identify distinct brands."""
    products = await get_products(state["brand_id"])
    if not products:
        # Try loading from Fabric / BC — scoped to the brand's BC company.
        # The lakehouse tables hold every BC company's rows, so an unfiltered
        # query would leak other brands' items (mirrors the Company = ?
        # filtering used by backend fabric_service).
        try:
            brand = await get_brand(state["brand_id"])
            bc_company = (brand or {}).get("bc_company")
            if not bc_company:
                logger.warning(
                    "Brand %s has no bc_company set — skipping Fabric fallback",
                    state["brand_id"],
                )
                return {
                    "errors": [*(state.get("errors") or []), "No products found"],
                    "status": "failed",
                }
            await execute_sql(
                "SELECT DISTINCT vendorNo FROM itemmodule_item "
                "WHERE Company = ? AND blocked = 0",
                (bc_company,),
            )
            # Also fetch products
            raw_products = await execute_sql(
                "SELECT TOP 500 no, description, vendorNo FROM itemmodule_item "
                "WHERE Company = ? AND blocked = 0 ORDER BY no",
                (bc_company,),
            )
            products = [
                {
                    "name": p.get("description", ""),
                    "sku": p.get("no", ""),
                    "vendor": p.get("vendorNo", ""),
                    "image_url": None,
                }
                for p in raw_products
            ]
        except Exception:
            logger.exception("Failed to load products from Fabric")
            return {
                "errors": [*(state.get("errors") or []), "No products found"],
                "status": "failed",
            }

    # Group by vendor
    vendor_groups: dict[str, list[dict[str, Any]]] = {}
    for p in products:
        vendor = p.get("vendor", "Unknown")
        vendor_groups.setdefault(vendor, []).append(p)

    # Use LLM to identify brands from vendor groups
    prompt = [
        {
            "role": "system",
            "content": (
                "You are a product intelligence analyst. Given product data grouped by vendor, "
                "identify distinct brands. Some vendors may represent multiple brands, some may be the same brand. "
                "Return JSON: {vendor_name: [{brand_name, brand_website (if known), product_count, category}]}"
            ),
        },
        {
            "role": "user",
            "content": f"Vendor groups:\n{sanitize_json_for_prompt({v: [{'name': p['name'], 'sku': p.get('sku')} for p in ps[:20]] for v, ps in vendor_groups.items()}, max_length=8000)}",
        },
    ]
    try:
        result = await chat_completion(
            prompt, temperature=0.3, response_format={"type": "json_object"}
        )
        brand_mappings = parse_llm_json(
            result,
            fallback={
                v: [{"brand_name": v, "product_count": len(ps)}]
                for v, ps in vendor_groups.items()
            },
        )
        return {"products": products, "brand_mappings": brand_mappings}
    except Exception as exc:
        logger.error("discover_brands LLM call failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"discover_brands failed: {exc}"],
        }


async def research_brand(state: ProductIntelState) -> dict[str, Any]:
    """Research each discovered brand via browser-worker and LLM."""
    try:
        brand_mappings = state.get("brand_mappings", {})
        enriched: dict[str, list[dict[str, Any]]] = {}

        for vendor, brands in brand_mappings.items():
            enriched_brands = []
            for brand_info in brands:
                brand_name = brand_info.get("brand_name", vendor)
                website = brand_info.get("brand_website")

                # Search for brand website if not known
                if not website:
                    results = await web_search(f"{brand_name} official website")
                    if results:
                        website = results[0].url

                # Extract brand info from website
                if website:
                    try:
                        page_data = await extract_page(website)
                        prompt = [
                            {
                                "role": "system",
                                "content": (
                                    "Extract brand information: description, target_market, price_range, "
                                    "brand_values, social_media_links. Return JSON."
                                ),
                            },
                            {
                                "role": "user",
                                "content": f"Brand: {sanitize_for_prompt(brand_name)}\nWebsite data:\n{sanitize_json_for_prompt(page_data, max_length=5000)}",
                            },
                        ]
                        analysis = await chat_completion(
                            prompt,
                            temperature=0.3,
                            response_format={"type": "json_object"},
                        )
                        brand_data = parse_llm_json(
                            analysis, fallback={"description": analysis}
                        )

                        brand_info.update(brand_data)
                        brand_info["brand_website"] = website
                    except Exception:
                        logger.exception("Failed to research brand %s", brand_name)

                enriched_brands.append(brand_info)
            enriched[vendor] = enriched_brands

        return {"brand_mappings": enriched}
    except Exception as exc:
        logger.error("research_brand failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"research_brand failed: {exc}"],
        }


async def match_products_to_brands(state: ProductIntelState) -> dict[str, Any]:
    """Match individual products to their brands using LLM and update DB."""
    products = state.get("products", [])
    brand_mappings = state.get("brand_mappings", {})

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a product cataloging expert. Match each product to its correct brand. "
                "Return a JSON array of objects with: sku, product_name, brand_name, category, "
                "is_promotable (boolean based on whether it's suitable for social media promotion)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Products:\n{sanitize_json_for_prompt([{'sku': p.get('sku'), 'name': p.get('name'), 'vendor': p.get('vendor')} for p in products[:100]], max_length=6000)}\n\n"
                f"Brand mappings:\n{sanitize_json_for_prompt(brand_mappings, max_length=4000)}"
            ),
        },
    ]
    try:
        result = await chat_completion(
            prompt,
            temperature=0.2,
            max_tokens=8192,
            response_format={"type": "json_object"},
        )
        matched = parse_llm_json(result, fallback=[])
        if isinstance(matched, dict):
            matched = next((v for v in matched.values() if isinstance(v, list)), [])
    except Exception as exc:
        logger.error("match_products_to_brands LLM call failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"match_products_to_brands failed: {exc}",
            ],
        }

    # Update products in DB
    for match in matched:
        sku = match.get("sku")
        matching_product = next((p for p in products if p.get("sku") == sku), None)
        if matching_product:
            matching_product["metadata"] = json.dumps(
                {
                    "brand_name": match.get("brand_name"),
                    "category": match.get("category"),
                    "is_promotable": match.get("is_promotable", False),
                }
            )
            try:
                await upsert_product(matching_product)
            except Exception:
                logger.exception("Failed to upsert product %s", sku)

    return {"products": products}


async def source_product_images_node(state: ProductIntelState) -> dict[str, Any]:
    """Source real images for all products using the image sourcing pipeline."""
    products = state.get("products", [])
    images: dict[str, str] = {}

    for product in products:
        pid = product.get("id") or product.get("sku", "")
        if product.get("image_url"):
            images[pid] = product["image_url"]
            continue

        result = await source_product_image(
            product_sku=product.get("sku"),
            product_name=product.get("name"),
            brand_name=product.get("vendor", ""),
        )
        if result.image_url:
            images[pid] = result.image_url
            # Update product in DB
            product["image_url"] = result.image_url
            try:
                await upsert_product(product)
            except Exception:
                logger.exception("Failed to update product image for %s", pid)

    logger.info("Sourced images for %d/%d products", len(images), len(products))
    return {"images": images}


async def flag_promotable(state: ProductIntelState) -> dict[str, Any]:
    """Flag products that are suitable for social media promotion using LLM + rules."""
    products = state.get("products", [])
    images = state.get("images", {})

    # Rule-based filtering: must have an image and name
    candidates = [
        p
        for p in products
        if p.get("name") and (images.get(p.get("id") or p.get("sku", "")))
    ]

    if not candidates:
        return {"promotable_items": [], "status": "completed"}

    prompt = [
        {
            "role": "system",
            "content": (
                "You are a social media marketing expert. From this list of products, "
                "select those most suitable for social media promotion. Consider: visual appeal, "
                "audience interest, seasonality, margin potential. "
                "Return a JSON array of objects with: sku, name, promotability_score (0-1), "
                "recommended_platforms, suggested_angle, priority (high/medium/low)."
            ),
        },
        {
            "role": "user",
            "content": f"Products:\n{sanitize_json_for_prompt([{'sku': p.get('sku'), 'name': p.get('name'), 'vendor': p.get('vendor')} for p in candidates[:50]], max_length=6000)}",
        },
    ]
    try:
        result = await chat_completion(
            prompt, temperature=0.4, response_format={"type": "json_object"}
        )
        promotable = parse_llm_json(result, fallback=[])
        if isinstance(promotable, dict):
            promotable = next(
                (v for v in promotable.values() if isinstance(v, list)), []
            )
        return {"promotable_items": promotable, "status": "completed"}
    except Exception as exc:
        logger.error("flag_promotable LLM call failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"flag_promotable failed: {exc}"],
        }
