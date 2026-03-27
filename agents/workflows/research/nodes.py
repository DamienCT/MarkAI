"""Research workflow nodes — each calls real external services."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, get_embedding, parse_llm_json
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.browser import crawl_site, extract_page
from shared.tools.social import get_social_profiles, get_engagement_data
from shared.tools.database import get_brand, get_brand_config, store_competitors
from shared.tools.vector import create_collection, upsert_vectors, async_create_collection, async_upsert_vectors
from shared.tools.web_search import web_search

from workflows.research.state import ResearchState

logger = logging.getLogger(__name__)


async def crawl_website(state: ResearchState) -> dict[str, Any]:
    """Crawl the brand's website(s) via browser-worker and extract content.
    Uses primary website_url plus any additional websites from brand_guidelines.
    """
    brand = await get_brand(state["brand_id"])
    if not brand:
        return {"errors": [*(state.get("errors") or []), "Brand not found"]}

    # Collect all brand URLs
    urls: list[str] = []
    if brand.get("website_url"):
        urls.append(brand["website_url"])
    guidelines = brand.get("brand_guidelines", {}) or {}
    if isinstance(guidelines, dict):
        extra_websites = guidelines.get("websites", [])
        if isinstance(extra_websites, list):
            urls.extend([u for u in extra_websites if u and isinstance(u, str)])

    if not urls:
        return {"errors": [*(state.get("errors") or []), "No website URLs configured for this brand"]}

    logger.info("Crawling %d website(s) for brand %s: %s", len(urls), state["brand_id"], urls)

    all_pages: list[dict] = []
    for url in urls:
        try:
            pages = await crawl_site(url, max_pages=10)
            all_pages.extend(pages if isinstance(pages, list) else [])
        except Exception as exc:
            logger.warning("Failed to crawl %s: %s", url, exc)

    return {"website_url": urls[0], "website_data": all_pages}


async def analyze_social(state: ResearchState) -> dict[str, Any]:
    """Fetch and analyse social profiles and engagement data.
    Uses channel handles even if the channel is disabled — for research context.
    """
    config = await get_brand_config(state["brand_id"])
    if not config:
        return {"social_analysis": {}, "errors": [*(state.get("errors") or []), "No brand config found"]}

    # Extract handles from brand_guidelines.channels (regardless of enabled status)
    guidelines = config.get("brand_guidelines", {}) or {}
    channels = guidelines.get("channels", {}) if isinstance(guidelines, dict) else {}
    ig_handle = (channels.get("instagram", {}) or {}).get("handle", "")
    fb_id = (channels.get("facebook", {}) or {}).get("page_id", "")
    li_id = (channels.get("linkedin", {}) or {}).get("org_id", "")

    logger.info("Research social handles: IG=%s, FB=%s, LI=%s", ig_handle, fb_id, li_id)

    profiles = await get_social_profiles(ig_handle, fb_id, li_id)
    engagement = await get_engagement_data(ig_handle, fb_id, li_id)

    analysis_prompt = [
        {"role": "system", "content": "You are a social media analyst. Analyze the following social media data and provide insights on content performance, audience engagement patterns, posting frequency, and content themes. The brand operates in Mauritius and the Indian Ocean region. Consider local social media landscape: Facebook and Instagram are dominant platforms in Mauritius, WhatsApp is widely used for business communication, and content often needs to work in English, French, and Creole. Factor in local peak usage times (GMT+4 timezone)."},
        {"role": "user", "content": f"Social profiles:\n{sanitize_json_for_prompt(profiles)}\n\nRecent engagement data:\n{sanitize_json_for_prompt(engagement)}"},
    ]
    analysis_text = await chat_completion(analysis_prompt)

    return {
        "social_profiles": profiles,
        "social_analysis": {"raw_profiles": profiles, "raw_engagement": engagement, "analysis": analysis_text},
    }


async def analyze_competitors(state: ResearchState) -> dict[str, Any]:
    """Identify and analyse competitors using browser-worker and LLM."""
    brand = await get_brand(state["brand_id"])
    brand_name = brand.get("name", "") if brand else ""
    website_data = state.get("website_data", [])

    # Extract brand context for more targeted search
    brand_industry = brand.get("description", "") or ""
    brand_guidelines = brand.get("brand_guidelines", {}) or {}
    brand_context = brand_guidelines.get("industry", "") or ""

    # Ask LLM to identify competitors from website data
    identify_prompt = [
        {"role": "system", "content": "You are a competitive intelligence analyst. The brand operates in Mauritius and the Indian Ocean region. Focus ONLY on direct competitors in Mauritius and the Indian Ocean region. Do NOT include comparison websites, blog sites, review aggregators, or international companies unless they operate locally in Mauritius. Given the brand's website content, identify their top 5 LOCAL competitors. Return a JSON array of objects with 'name' and 'website' fields."},
        {"role": "user", "content": f"Brand: {sanitize_for_prompt(brand_name)}\nIndustry context: {sanitize_for_prompt(brand_industry)} {sanitize_for_prompt(brand_context)}\n\nWebsite content:\n{sanitize_json_for_prompt(website_data[:5], max_length=8000)}"},
    ]
    competitor_text = await chat_completion(identify_prompt, temperature=0.3)

    # Parse competitor list
    competitors = parse_llm_json(competitor_text, fallback=[])

    # If LLM couldn't identify competitors (e.g. no website data), do targeted web searches
    if not competitors or len(competitors) < 3:
        # Multiple targeted searches for actual local businesses
        search_queries = [
            f"health fitness stores Mauritius",
            f"pharmacy wellness products Mauritius",
            f"sports nutrition supplements Mauritius shops",
            f"{brand_name} similar shops Mauritius",
        ]
        all_results = []
        for q in search_queries:
            try:
                results = await web_search(q)
                all_results.extend(results[:5])
            except Exception:
                pass

        # Use LLM to filter and identify actual local businesses from search results
        if all_results:
            filter_prompt = [
                {"role": "system", "content": (
                    "You are a local market analyst in Mauritius. From the search results below, "
                    "identify ONLY actual businesses/stores/pharmacies/retailers in Mauritius that sell "
                    "health, fitness, or wellness products. EXCLUDE: review sites, comparison sites, "
                    "directory listings, blog posts, news articles, and international companies without "
                    "a local presence in Mauritius. Return a JSON array of objects with 'name' (business name) "
                    "and 'website' (their actual website URL) fields. Maximum 5 results."
                )},
                {"role": "user", "content": f"Brand context: {sanitize_for_prompt(brand_name)} - {sanitize_for_prompt(brand_industry)}\n\nSearch results:\n" +
                    "\n".join([f"- {r.title}: {r.url} — {getattr(r, 'snippet', '')}" for r in all_results[:20]])},
            ]
            try:
                filtered_text = await chat_completion(filter_prompt, temperature=0.2)
                filtered = parse_llm_json(filtered_text, fallback=[])
                if isinstance(filtered, list) and filtered:
                    competitors = filtered
            except Exception:
                pass

    # Build structured competitor data for storage
    analyses: list[dict[str, Any]] = []
    for comp in competitors[:5]:
        comp_name = comp.get("name", "Unknown")
        comp_website = comp.get("website", "")

        # Skip obvious non-business results
        skip_domains = ["craft.co", "owler.com", "tracxn.com", "growjo.com", "crunchbase.com",
                       "linkedin.com", "facebook.com", "wikipedia.org", "bloomberg.com"]
        if any(d in comp_website.lower() for d in skip_domains):
            continue

        description = comp.get("description", "")
        if not description:
            # Quick LLM description
            try:
                desc_text = await chat_completion([
                    {"role": "system", "content": "Write a one-sentence description of this business and what they sell. If you don't know, say 'Local competitor in Mauritius'."},
                    {"role": "user", "content": f"Business: {sanitize_for_prompt(comp_name)}, Website: {sanitize_for_prompt(comp_website)}"},
                ], temperature=0.3)
                description = desc_text.strip()[:300]
            except Exception:
                description = "Local competitor in Mauritius"

        analyses.append({
            "name": comp_name,
            "website": comp_website,
            "website_url": comp_website,
            "description": description,
            "social_handles": {},
        })

    logger.info("Found %d competitors for brand %s", len(analyses), brand_name)
    return {"competitor_analysis": analyses, "competitor_urls": [c.get("website", "") for c in competitors[:5]]}


async def identify_gaps(state: ResearchState) -> dict[str, Any]:
    """Use LLM to identify content and positioning gaps from all collected data."""
    prompt = [
        {"role": "system", "content": "You are a strategic marketing analyst. Based on the brand's website, social media analysis, and competitor analysis, identify gaps and opportunities. Consider the Mauritian market, Indian Ocean region demographics, and local consumer behavior. Return a JSON array of gap objects with 'category', 'description', 'opportunity', and 'priority' (high/medium/low) fields."},
        {"role": "user", "content": (
            f"Website data summary: {sanitize_json_for_prompt(state.get('website_data', [])[:3], max_length=3000)}\n\n"
            f"Social analysis: {sanitize_json_for_prompt(state.get('social_analysis', {}), max_length=3000)}\n\n"
            f"Competitor analysis: {sanitize_json_for_prompt(state.get('competitor_analysis', []), max_length=3000)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.4)
    gaps = parse_llm_json(result, fallback=[{"category": "general", "description": result, "opportunity": "", "priority": "medium"}])

    return {"gaps": gaps}


async def build_personas(state: ResearchState) -> dict[str, Any]:
    """Build audience personas from research data using LLM."""
    prompt = [
        {"role": "system", "content": "You are a marketing strategist. Build 3-5 detailed audience personas based on the research data. Create personas that reflect the Mauritian market. Use local demographics (Mauritius population ~1.3M, diverse ethnic groups, multilingual - English/French/Creole). Consider Indian Ocean region consumer behavior, local income levels, popular local platforms, and cultural context. Do NOT create personas from US cities. Each persona should have: name, demographics, psychographics, pain_points, content_preferences, platforms, buying_triggers. Return a JSON array."},
        {"role": "user", "content": (
            f"Social analysis: {sanitize_json_for_prompt(state.get('social_analysis', {}), max_length=3000)}\n\n"
            f"Gaps identified: {sanitize_json_for_prompt(state.get('gaps', []), max_length=2000)}\n\n"
            f"Competitor analysis: {sanitize_json_for_prompt(state.get('competitor_analysis', []), max_length=2000)}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    personas = parse_llm_json(result, fallback=[{"name": "Primary Audience", "description": result}])

    return {"personas": personas}


async def store_results(state: ResearchState) -> dict[str, Any]:
    """Persist research results to the database and vector store."""
    brand_id = state["brand_id"]

    research_data = {
        "website_data": state.get("website_data", []),
        "social_analysis": state.get("social_analysis", {}),
        "competitor_analysis": state.get("competitor_analysis", []),
        "gaps": state.get("gaps", []),
        "personas": state.get("personas", []),
    }

    # Store competitors discovered during research
    competitors = state.get("competitor_analysis", [])
    if competitors:
        count = await store_competitors(brand_id, competitors)
        logger.info("Stored %d competitors for brand %s", count, brand_id)

    # Try vector store but don't fail if Qdrant is down
    try:
        await async_create_collection("brand_research", vector_size=1536)
        texts_to_embed = []
        payloads_list = []
        for gap in state.get("gaps", []):
            t = f"{gap.get('category', '')}: {gap.get('description', '')} - {gap.get('opportunity', '')}"
            texts_to_embed.append(t)
            payloads_list.append({"brand_id": brand_id, "type": "gap", "data": gap})
        for persona in state.get("personas", []):
            t = json.dumps(persona, default=str)
            texts_to_embed.append(t)
            payloads_list.append({"brand_id": brand_id, "type": "persona", "data": persona})
        if texts_to_embed:
            vectors = [await get_embedding(t) for t in texts_to_embed]
            await async_upsert_vectors("brand_research", vectors, payloads_list)
    except Exception as exc:
        logger.warning("Qdrant vector store failed (non-fatal): %s", exc)

    return {"status": "completed", "research_data": research_data}
