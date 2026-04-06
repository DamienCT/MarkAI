"""Research workflow nodes — each calls real external services."""

from __future__ import annotations

import json
import logging
from typing import Any

from shared.llm import chat_completion, get_embedding, parse_llm_json
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.browser import crawl_site
from shared.tools.social import get_social_profiles, get_engagement_data
from shared.tools.database import get_brand, get_brand_config, store_competitors
from shared.tools.vector import async_create_collection, async_upsert_vectors
from shared.tools.web_search import web_search

from workflows.research.state import ResearchState

logger = logging.getLogger(__name__)


async def crawl_website(state: ResearchState) -> dict[str, Any]:
    """Crawl the brand's website(s) via browser-worker and extract content.
    Uses primary website_url plus any additional websites from brand_guidelines.
    """
    brand = await get_brand(state["brand_id"])
    if not brand:
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), "Brand not found"],
        }

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
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                "No website URLs configured for this brand",
            ],
        }

    logger.info(
        "Crawling %d website(s) for brand %s: %s", len(urls), state["brand_id"], urls
    )

    all_pages: list[dict] = []
    for url in urls:
        try:
            pages = await crawl_site(url, max_pages=10)
            all_pages.extend(pages if isinstance(pages, list) else [])
        except Exception as exc:
            logger.warning("Failed to crawl %s: %s", url, exc)

    if not all_pages:
        return {
            "status": "failed",
            "website_url": urls[0],
            "website_data": [],
            "errors": [
                *(state.get("errors") or []),
                "All website crawls failed — no content gathered",
            ],
        }

    return {"website_url": urls[0], "website_data": all_pages}


async def analyze_social(state: ResearchState) -> dict[str, Any]:
    """Fetch and analyse social profiles and engagement data.
    Uses channel handles even if the channel is disabled — for research context.
    """
    config = await get_brand_config(state["brand_id"])
    if not config:
        return {
            "status": "failed",
            "social_analysis": {},
            "errors": [*(state.get("errors") or []), "No brand config found"],
        }

    # Extract handles from brand_guidelines.channels (regardless of enabled status)
    guidelines = config.get("brand_guidelines", {}) or {}
    channels = guidelines.get("channels", {}) if isinstance(guidelines, dict) else {}
    ig_handle = (channels.get("instagram", {}) or {}).get("handle", "")
    fb_id = (channels.get("facebook", {}) or {}).get("page_id", "")
    li_id = (channels.get("linkedin", {}) or {}).get("org_id", "")

    logger.info("Research social handles: IG=%s, FB=%s, LI=%s", ig_handle, fb_id, li_id)

    profiles = await get_social_profiles(ig_handle, fb_id, li_id)
    engagement = await get_engagement_data(ig_handle, fb_id, li_id)

    try:
        analysis_prompt = [
            {
                "role": "system",
                "content": "You are a social media analyst. Analyze the following social media data and provide insights on content performance, audience engagement patterns, posting frequency, and content themes. Include in your analysis: engagement_rate (current average engagement rate as a percentage), benchmark_comparison (how this compares to industry averages), top_content_types (ranked list of content types by engagement, e.g. Reel > Carousel > Static), peak_times (best posting times per platform with data-backed reasoning), content_gaps (what competitors post about that this brand doesn't), hashtag_analysis (top 10 hashtags by reach from recent posts), and 5 specific, actionable recommendations.",
            },
            {
                "role": "user",
                "content": f"Social profiles:\n{sanitize_json_for_prompt(profiles)}\n\nRecent engagement data:\n{sanitize_json_for_prompt(engagement)}",
            },
        ]
        analysis_text = await chat_completion(analysis_prompt)

        return {
            "social_profiles": profiles,
            "social_analysis": {
                "raw_profiles": profiles,
                "raw_engagement": engagement,
                "analysis": analysis_text,
            },
        }
    except Exception as exc:
        logger.error("analyze_social failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"analyze_social failed: {exc}"],
        }


async def analyze_competitors(state: ResearchState) -> dict[str, Any]:
    """Identify and analyse competitors using browser-worker and LLM."""
    from shared.tools.database import execute_query

    brand = await get_brand(state["brand_id"])
    brand_name = brand.get("name", "") if brand else ""
    website_data = state.get("website_data", [])

    # Extract brand context for more targeted search
    brand_industry = brand.get("description", "") or ""
    brand_guidelines = brand.get("brand_guidelines", {}) or {}
    brand_context = brand_guidelines.get("industry", "") or ""

    # Load existing competitors from DB
    existing = await execute_query(
        "SELECT name, website_url, description, social_handles FROM competitors "
        "WHERE brand_id = :brand_id AND is_active = true",
        {"brand_id": state["brand_id"]},
    )
    existing_competitors = [dict(r) for r in existing] if existing else []

    # Include existing competitors in the prompt context
    existing_info = ""
    if existing_competitors:
        names = [c.get("name", "") for c in existing_competitors]
        existing_info = f"\n\nAlready known competitors: {', '.join(names)}. Include these and discover additional ones."

    # Ask LLM to identify competitors from website data
    identify_prompt = [
        {
            "role": "system",
            "content": "You are a competitive intelligence analyst. Focus on direct competitors in the brand's market. Do NOT include comparison websites, blog sites, review aggregators, or unrelated international companies. Given the brand's website content, identify their top 5 competitors. For EACH competitor, provide a comprehensive profile. Return a JSON array where each object has: name (company name), website_url (their website), positioning (their brand positioning statement in 1 sentence), strengths (array of 3+ competitive strengths), weaknesses (array of 3+ competitive weaknesses), social_presence (object with platform names as keys and estimated follower counts as values), content_strategy (description of their social media content approach — frequency, content types, tone), threat_level ('high', 'medium', or 'low' based on market overlap and competitive strength).",
        },
        {
            "role": "user",
            "content": f"Brand: {sanitize_for_prompt(brand_name)}\nIndustry context: {sanitize_for_prompt(brand_industry)} {sanitize_for_prompt(brand_context)}{existing_info}\n\nWebsite content:\n{sanitize_json_for_prompt(website_data[:5], max_length=8000)}",
        },
    ]
    try:
        competitor_text = await chat_completion(
            identify_prompt, temperature=0.3, response_format={"type": "json_object"}
        )
    except Exception as exc:
        logger.error("analyze_competitors failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"analyze_competitors failed: {exc}",
            ],
        }

    # Parse competitor list
    competitors = parse_llm_json(
        competitor_text,
        fallback=[
            {
                "name": "Unknown",
                "website_url": "",
                "positioning": "",
                "strengths": [],
                "weaknesses": [],
                "social_presence": {},
                "content_strategy": "",
                "threat_level": "medium",
            }
        ],
    )
    # json_object mode may wrap arrays in a dict — extract the list
    if isinstance(competitors, dict):
        competitors = next((v for v in competitors.values() if isinstance(v, list)), [])

    # If LLM couldn't identify competitors (e.g. no website data), do targeted web searches
    if not competitors or len(competitors) < 3:
        # Multiple targeted searches for actual local businesses
        search_queries = [
            f"{brand_name} competitors",
            f"{brand_context or brand_industry} stores near {brand_name}",
            f"{brand_context or brand_industry} similar businesses",
            f"{brand_name} alternatives",
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
                {
                    "role": "system",
                    "content": (
                        "You are a market analyst. From the search results below, "
                        "identify ONLY actual businesses that are direct competitors to the brand. "
                        "EXCLUDE: review sites, comparison sites, "
                        "directory listings, blog posts, news articles, and unrelated companies. "
                        "Return a JSON array of objects with 'name' (business name) "
                        "and 'website' (their actual website URL) fields. Maximum 5 results."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Brand context: {sanitize_for_prompt(brand_name)} - {sanitize_for_prompt(brand_industry)}\n\nSearch results:\n"
                    + "\n".join(
                        [
                            f"- {r.title}: {r.url} — {getattr(r, 'snippet', '')}"
                            for r in all_results[:20]
                        ]
                    ),
                },
            ]
            try:
                filtered_text = await chat_completion(
                    filter_prompt,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                filtered = parse_llm_json(filtered_text, fallback=[])
                if isinstance(filtered, dict):
                    filtered = next(
                        (v for v in filtered.values() if isinstance(v, list)), []
                    )
                if isinstance(filtered, list) and filtered:
                    competitors = filtered
            except Exception:
                pass

    # Build structured competitor data for storage
    logger.info(
        "analyze_competitors: %d competitors (type=%s)",
        len(competitors) if isinstance(competitors, (list, dict)) else 0,
        type(competitors).__name__,
    )
    analyses: list[dict[str, Any]] = []
    for comp in competitors[:5]:
        # Handle LLM returning strings instead of dicts (e.g., ["Omron", "Withings"])
        if isinstance(comp, str):
            comp = {"name": comp, "website": "", "description": ""}
        if not isinstance(comp, dict):
            continue
        comp_name = comp.get("name", "Unknown")
        comp_website = comp.get("website", "")

        # Skip obvious non-business results
        skip_domains = [
            "craft.co",
            "owler.com",
            "tracxn.com",
            "growjo.com",
            "crunchbase.com",
            "linkedin.com",
            "facebook.com",
            "wikipedia.org",
            "bloomberg.com",
        ]
        if any(d in comp_website.lower() for d in skip_domains):
            continue

        description = comp.get("description", "")
        if not description:
            # Quick LLM description
            try:
                desc_text = await chat_completion(
                    [
                        {
                            "role": "system",
                            "content": "Write a one-sentence description of this business and what they sell. If you don't know, say 'Competitor'.",
                        },
                        {
                            "role": "user",
                            "content": f"Business: {sanitize_for_prompt(comp_name)}, Website: {sanitize_for_prompt(comp_website)}",
                        },
                    ],
                    temperature=0.3,
                )
                description = desc_text.strip()[:300]
            except Exception as exc:
                logger.warning(
                    "Failed to generate description for competitor %s: %s",
                    comp_name,
                    exc,
                )
                description = "Competitor"

        analyses.append(
            {
                "name": comp_name,
                "website": comp_website,
                "website_url": comp_website,
                "description": description,
                "social_handles": {},
            }
        )

    # Merge existing competitors with newly discovered ones (avoid duplicates)
    discovered_names = {a["name"].lower() for a in analyses}
    for ec in existing_competitors:
        ec_name = ec.get("name", "").strip()
        if ec_name and ec_name.lower() not in discovered_names:
            analyses.append(
                {
                    "name": ec_name,
                    "website": ec.get("website_url", ""),
                    "website_url": ec.get("website_url", ""),
                    "description": ec.get("description", ""),
                    "social_handles": ec.get("social_handles", {})
                    if isinstance(ec.get("social_handles"), dict)
                    else {},
                }
            )
            discovered_names.add(ec_name.lower())

    logger.info(
        "Found %d competitors for brand %s (%d existing, %d new)",
        len(analyses),
        brand_name,
        len(existing_competitors),
        len(analyses) - len(existing_competitors),
    )
    return {
        "competitor_analysis": analyses,
        "competitor_urls": [
            c.get("website", c.get("website_url", "")) for c in analyses
        ],
    }


async def identify_gaps(state: ResearchState) -> dict[str, Any]:
    """Use LLM to identify content and positioning gaps from all collected data."""
    try:
        prompt = [
            {
                "role": "system",
                "content": "You are a strategic marketing analyst. Based on the brand's website, social media analysis, and competitor analysis, identify gaps and opportunities. Return a JSON array where each gap has: title (short descriptive title), category (one of: content, positioning, digital, audience, product, channel), description (what the gap is), opportunity (how to exploit it), priority (high/medium/low), estimated_impact (expected business impact if addressed), implementation_effort (low/medium/high), recommended_timeline (when to implement, e.g. 'Q2 2026'), target_audience (which persona(s) this gap affects most), success_metrics (array of 2-3 measurable KPIs to track).",
            },
            {
                "role": "user",
                "content": (
                    f"Website data summary: {sanitize_json_for_prompt(state.get('website_data', [])[:3], max_length=3000)}\n\n"
                    f"Social analysis: {sanitize_json_for_prompt(state.get('social_analysis', {}), max_length=3000)}\n\n"
                    f"Competitor analysis: {sanitize_json_for_prompt(state.get('competitor_analysis', []), max_length=3000)}"
                ),
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.4, response_format={"type": "json_object"}
        )
        gaps = parse_llm_json(
            result,
            fallback=[
                {
                    "title": "General Gap",
                    "category": "content",
                    "description": result,
                    "opportunity": "",
                    "priority": "medium",
                    "estimated_impact": "",
                    "implementation_effort": "medium",
                    "recommended_timeline": "",
                    "target_audience": "",
                    "success_metrics": [],
                }
            ],
        )
        if isinstance(gaps, dict):
            gaps = next((v for v in gaps.values() if isinstance(v, list)), [])
        return {"gaps": gaps}
    except Exception as exc:
        logger.error("identify_gaps failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"identify_gaps failed: {exc}"],
        }


async def build_personas(state: ResearchState) -> dict[str, Any]:
    """Build audience personas from research data using LLM."""
    try:
        prompt = [
            {
                "role": "system",
                "content": "You are a marketing strategist. Build 3-5 detailed audience personas based on the research data. Create personas that reflect the brand's target market. Each persona should have: name (a memorable name and archetype, e.g. 'Sarah, the Wellness Enthusiast'), demographics (object with age range, gender, location, income level, education, occupation), psychographics (values, lifestyle, interests, media habits), pain_points (array of 3+ specific pain points related to the brand's industry), content_preferences (object with: formats — preferred content formats like Reels/Carousels/Stories/Static/Articles; topics — 5+ specific topic interests; tone — preferred communication tone), platforms (array of social platforms they use, ordered by preference), buying_triggers (array of 3+ triggers that drive purchase decisions), best_engagement_times (specific times when this persona is most active), content_avoidance (array of what turns this persona off, e.g. 'hard sells', 'medical jargon'). Return a JSON array.",
            },
            {
                "role": "user",
                "content": (
                    f"Social analysis: {sanitize_json_for_prompt(state.get('social_analysis', {}), max_length=3000)}\n\n"
                    f"Gaps identified: {sanitize_json_for_prompt(state.get('gaps', []), max_length=2000)}\n\n"
                    f"Competitor analysis: {sanitize_json_for_prompt(state.get('competitor_analysis', []), max_length=2000)}"
                ),
            },
        ]
        result = await chat_completion(
            prompt, temperature=0.5, response_format={"type": "json_object"}
        )
        personas = parse_llm_json(
            result,
            fallback=[
                {
                    "name": "Primary Audience",
                    "demographics": {
                        "age": "",
                        "gender": "",
                        "location": "",
                        "income": "",
                        "occupation": "",
                    },
                    "psychographics": result,
                    "pain_points": [],
                    "content_preferences": {
                        "formats": [],
                        "topics": [],
                        "tone": "",
                        "language_mix": "",
                    },
                    "platforms": [],
                    "buying_triggers": [],
                    "best_engagement_times": "",
                    "content_avoidance": [],
                }
            ],
        )
        if isinstance(personas, dict):
            personas = next((v for v in personas.values() if isinstance(v, list)), [])
        return {"personas": personas}
    except Exception as exc:
        logger.error("build_personas failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"build_personas failed: {exc}"],
        }


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
        try:
            await async_create_collection("brand_research", vector_size=1536)
        except Exception:
            pass  # Collection likely already exists
        texts_to_embed = []
        payloads_list = []
        for gap in state.get("gaps", []):
            t = f"{gap.get('category', '')}: {gap.get('description', '')} - {gap.get('opportunity', '')}"
            texts_to_embed.append(t)
            payloads_list.append({"brand_id": brand_id, "type": "gap", "data": gap})
        for persona in state.get("personas", []):
            t = json.dumps(persona, default=str)
            texts_to_embed.append(t)
            payloads_list.append(
                {"brand_id": brand_id, "type": "persona", "data": persona}
            )
        if texts_to_embed:
            vectors = [await get_embedding(t) for t in texts_to_embed]
            await async_upsert_vectors("brand_research", vectors, payloads_list)
    except Exception as exc:
        logger.warning("Qdrant vector store failed (non-fatal): %s", exc)

    return {"status": "completed", "research_data": research_data}
