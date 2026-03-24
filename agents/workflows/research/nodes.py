"""Research workflow nodes — each calls real external services."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, get_embedding
from shared.tools.browser import crawl_site, extract_page
from shared.tools.social import get_social_profiles, get_engagement_data
from shared.tools.database import get_brand, get_brand_config, store_research
from shared.tools.vector import create_collection, upsert_vectors
from shared.tools.web_search import web_search

from workflows.research.state import ResearchState

logger = logging.getLogger(__name__)


async def crawl_website(state: ResearchState) -> dict[str, Any]:
    """Crawl the brand's website via browser-worker and extract content."""
    brand = await get_brand(state["brand_id"])
    if not brand or not brand.get("website_url"):
        return {"errors": [*(state.get("errors") or []), "Brand or website URL not found"]}

    website_url = brand["website_url"]
    logger.info("Crawling website %s for brand %s", website_url, state["brand_id"])

    pages = await crawl_site(website_url, max_pages=20)
    return {"website_url": website_url, "website_data": pages}


async def analyze_social(state: ResearchState) -> dict[str, Any]:
    """Fetch and analyse social profiles and engagement data."""
    config = await get_brand_config(state["brand_id"])
    if not config:
        return {"social_analysis": {}, "errors": [*(state.get("errors") or []), "No brand config found"]}

    ig_id = config.get("instagram_user_id")
    fb_id = config.get("facebook_page_id")
    li_id = config.get("linkedin_org_id")

    profiles = await get_social_profiles(ig_id, fb_id, li_id)
    engagement = await get_engagement_data(ig_id, fb_id, li_id)

    analysis_prompt = [
        {"role": "system", "content": "You are a social media analyst. Analyze the following social media data and provide insights on content performance, audience engagement patterns, posting frequency, and content themes."},
        {"role": "user", "content": f"Social profiles:\n{json.dumps(profiles, default=str)}\n\nRecent engagement data:\n{json.dumps(engagement, default=str)}"},
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

    # Ask LLM to identify competitors from website data
    identify_prompt = [
        {"role": "system", "content": "You are a competitive intelligence analyst. Given the brand's website content, identify their top 5 competitors. Return a JSON array of objects with 'name' and 'website' fields."},
        {"role": "user", "content": f"Brand: {brand_name}\n\nWebsite content:\n{json.dumps(website_data[:5], default=str)[:8000]}"},
    ]
    competitor_text = await chat_completion(identify_prompt, temperature=0.3)

    # Parse competitor list
    try:
        competitors = json.loads(competitor_text.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        # Fallback: search the web
        results = await web_search(f"{brand_name} competitors")
        competitors = [{"name": r.title, "website": r.url} for r in results[:5]]

    # Analyse each competitor
    analyses: list[dict[str, Any]] = []
    for comp in competitors[:5]:
        try:
            comp_data = await extract_page(comp["website"])
            analysis_prompt = [
                {"role": "system", "content": "Analyze this competitor's online presence. Provide: positioning, target audience, content strategy, strengths, weaknesses. Return JSON."},
                {"role": "user", "content": f"Competitor: {comp['name']}\nWebsite data:\n{json.dumps(comp_data, default=str)[:6000]}"},
            ]
            analysis = await chat_completion(analysis_prompt, temperature=0.3)
            analyses.append({"name": comp["name"], "website": comp["website"], "analysis": analysis})
        except Exception:
            logger.exception("Failed to analyze competitor %s", comp.get("name"))

    return {"competitor_analysis": analyses, "competitor_urls": [c["website"] for c in competitors[:5]]}


async def identify_gaps(state: ResearchState) -> dict[str, Any]:
    """Use LLM to identify content and positioning gaps from all collected data."""
    prompt = [
        {"role": "system", "content": "You are a strategic marketing analyst. Based on the brand's website, social media analysis, and competitor analysis, identify gaps and opportunities. Return a JSON array of gap objects with 'category', 'description', 'opportunity', and 'priority' (high/medium/low) fields."},
        {"role": "user", "content": (
            f"Website data summary: {json.dumps(state.get('website_data', [])[:3], default=str)[:3000]}\n\n"
            f"Social analysis: {json.dumps(state.get('social_analysis', {}), default=str)[:3000]}\n\n"
            f"Competitor analysis: {json.dumps(state.get('competitor_analysis', []), default=str)[:3000]}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.4)
    try:
        gaps = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        gaps = [{"category": "general", "description": result, "opportunity": "", "priority": "medium"}]

    return {"gaps": gaps}


async def build_personas(state: ResearchState) -> dict[str, Any]:
    """Build audience personas from research data using LLM."""
    prompt = [
        {"role": "system", "content": "You are a marketing strategist. Build 3-5 detailed audience personas based on the research data. Each persona should have: name, demographics, psychographics, pain_points, content_preferences, platforms, buying_triggers. Return a JSON array."},
        {"role": "user", "content": (
            f"Social analysis: {json.dumps(state.get('social_analysis', {}), default=str)[:3000]}\n\n"
            f"Gaps identified: {json.dumps(state.get('gaps', []), default=str)[:2000]}\n\n"
            f"Competitor analysis: {json.dumps(state.get('competitor_analysis', []), default=str)[:2000]}"
        )},
    ]
    result = await chat_completion(prompt, temperature=0.5)
    try:
        personas = json.loads(result.strip().strip("```json").strip("```"))
    except json.JSONDecodeError:
        personas = [{"name": "Primary Audience", "description": result}]

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

    # Store in Postgres
    research_id = await store_research(brand_id, research_data)
    logger.info("Stored research %s for brand %s", research_id, brand_id)

    # Store in Qdrant for similarity search
    create_collection("brand_research", vector_size=1536)

    # Embed key research findings
    texts_to_embed = []
    payloads = []
    for gap in state.get("gaps", []):
        text = f"{gap.get('category', '')}: {gap.get('description', '')} - {gap.get('opportunity', '')}"
        texts_to_embed.append(text)
        payloads.append({"brand_id": brand_id, "type": "gap", "data": gap})

    for persona in state.get("personas", []):
        text = json.dumps(persona, default=str)
        texts_to_embed.append(text)
        payloads.append({"brand_id": brand_id, "type": "persona", "data": persona})

    if texts_to_embed:
        vectors = [await get_embedding(t) for t in texts_to_embed]
        upsert_vectors("brand_research", vectors, payloads)

    return {"status": "completed"}
