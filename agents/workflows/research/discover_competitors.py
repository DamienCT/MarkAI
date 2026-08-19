"""Standalone competitor discovery — finds competitors via web search + LLM and
upserts them into the `competitors` table WITHOUT running the research workflow
or writing the research document.

Triggered by the worker on the `research.discover-competitors` subject (the
"Auto-discover" button), so the user can populate competitors without
regenerating any document.
"""

from __future__ import annotations

import logging
from typing import Any

from shared.brand_context import ENGLISH_ONLY_RULE as _ENGLISH_ONLY_RULE
from shared.llm import chat_completion, parse_llm_json
from shared.sanitize import sanitize_for_prompt
from shared.tools.database import execute_query, get_brand, store_competitors
from shared.tools.web_search import web_search

logger = logging.getLogger(__name__)


async def discover_competitors_standalone(brand_id: str) -> int:
    """Discover competitors for a brand and upsert them. Returns count inserted.

    Self-contained: does NOT touch agent_runs or any generated document. Only
    the `competitors` table is written (via store_competitors, upsert by name).
    """
    brand = await get_brand(brand_id)
    brand_name = brand.get("name", "") if brand else ""
    brand_industry = (brand.get("description", "") if brand else "") or ""
    guidelines = (brand.get("brand_guidelines", {}) if brand else {}) or {}
    brand_context = guidelines.get("industry", "") or ""

    # Existing competitors — so we don't re-suggest the same ones and the LLM
    # has context on what's already tracked.
    existing = await execute_query(
        "SELECT name FROM competitors WHERE brand_id = :brand_id AND is_active = true",
        {"brand_id": brand_id},
    )
    existing_names = {(dict(r).get("name") or "").lower() for r in (existing or [])}

    # Targeted web searches for real businesses (no website_data dependency).
    search_queries = [
        f"{brand_name} competitors",
        f"{brand_context or brand_industry} similar businesses",
        f"{brand_name} alternatives",
    ]
    all_results: list[Any] = []
    for q in search_queries:
        try:
            results = await web_search(q)
            all_results.extend(results[:5])
        except Exception as exc:
            logger.warning("competitor discovery search failed (%s): %s", q, exc)

    if not all_results:
        logger.info("Competitor discovery: no search results for brand %s", brand_id)
        return 0

    # LLM filters search results down to actual direct competitors.
    filter_prompt = [
        {
            "role": "system",
            "content": (
                f"{_ENGLISH_ONLY_RULE}\n\n"
                "You are a market analyst. From the search results below, identify "
                "ONLY actual businesses that are direct competitors to the brand. "
                "EXCLUDE: review sites, comparison sites, directory listings, blog "
                "posts, news articles, and unrelated companies. Return a JSON array "
                "of objects with 'name' (business name) and 'website' (their actual "
                "website URL). Maximum 5 results."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Brand: {sanitize_for_prompt(brand_name)} - "
                f"{sanitize_for_prompt(brand_industry)} {sanitize_for_prompt(brand_context)}\n\n"
                "Search results:\n"
                + "\n".join(
                    f"- {getattr(r, 'title', '')}: {getattr(r, 'url', '')} — "
                    f"{getattr(r, 'snippet', '')}"
                    for r in all_results[:20]
                )
            ),
        },
    ]
    try:
        filtered_text = await chat_completion(
            filter_prompt, temperature=0.2, response_format={"type": "json_object"}
        )
    except Exception as exc:
        logger.error("Competitor discovery LLM failed for brand %s: %s", brand_id, exc)
        return 0

    competitors = parse_llm_json(filtered_text, fallback=[])
    if isinstance(competitors, dict):
        competitors = next((v for v in competitors.values() if isinstance(v, list)), [])
    if not isinstance(competitors, list):
        return 0

    skip_domains = [
        "craft.co", "owler.com", "tracxn.com", "growjo.com", "crunchbase.com",
        "linkedin.com", "facebook.com", "wikipedia.org", "bloomberg.com",
    ]

    to_store: list[dict[str, Any]] = []
    for comp in competitors[:5]:
        if isinstance(comp, str):
            comp = {"name": comp, "website": ""}
        if not isinstance(comp, dict):
            continue
        name = (comp.get("name") or "").strip()
        if not name or name.lower() in existing_names:
            continue
        website = (comp.get("website") or comp.get("website_url") or "").strip()
        if any(d in website.lower() for d in skip_domains):
            continue
        to_store.append(
            {
                "name": name,
                "website_url": website,
                "description": (comp.get("description") or "").strip()[:300],
                "social_handles": {},
            }
        )

    if not to_store:
        logger.info("Competitor discovery: nothing new for brand %s", brand_id)
        return 0

    count = await store_competitors(brand_id, to_store)
    logger.info("Competitor discovery: stored %d new competitor(s) for brand %s",
                count, brand_id)
    return count
