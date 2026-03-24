#!/usr/bin/env python3
"""Development seed script — creates initial structural data via the FastAPI API.

Creates:
  - A test brand with real-looking but clearly labeled test data
  - Prompt versions for each workflow step

Does NOT create fake content or fake engagement data — only the structural
data needed to test workflows end-to-end.

Usage:
    python scripts/seed-dev.py [--base-url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import sys

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
API_V1 = "/api/v1"


def seed_brand(client: httpx.Client) -> str:
    """Create a test brand. Returns the brand ID."""
    payload = {
        "name": "[TEST] Island Fresh Mauritius",
        "slug": "test-island-fresh-mu",
        "website": "https://islandfresh.example.mu",
        "description": (
            "Test brand for development. Island Fresh is a fictional Mauritian "
            "food & beverage company specializing in locally-sourced tropical products."
        ),
        "tone_settings": {
            "voice": "warm, authentic, proud-of-origin",
            "formality": "casual-professional",
            "humor": "light",
        },
        "visual_identity": {
            "primary_color": "#2E7D32",
            "secondary_color": "#FFA726",
            "font_family": "Inter",
        },
        "target_audiences": [
            "Health-conscious consumers 25-45",
            "Tourists visiting Mauritius",
            "Export market B2B buyers",
        ],
        "content_pillars": [
            "Local sourcing & sustainability",
            "Tropical lifestyle & wellness",
            "Mauritian heritage & culture",
            "Product quality & freshness",
        ],
        "excluded_topics": [
            "Competitor bashing",
            "Political content",
            "Unverified health claims",
        ],
        "brand_safety_rules": [
            "No alcohol references in content targeting under-18",
            "All health claims must cite source",
            "No stock photos — real product imagery only",
        ],
        "social_links": {
            "instagram": "https://instagram.com/islandfresh_test",
            "facebook": "https://facebook.com/islandfreshtest",
            "linkedin": "https://linkedin.com/company/islandfresh-test",
        },
        "social_credentials": {},
        "posting_cadence": {
            "instagram": {"posts_per_week": 4, "best_times": ["09:00", "18:00"]},
            "facebook": {"posts_per_week": 3, "best_times": ["10:00", "19:00"]},
            "linkedin": {"posts_per_week": 2, "best_times": ["08:00", "12:00"]},
        },
        "approval_chain": {
            "levels": [
                {"role": "content_creator", "auto_approve": False},
                {"role": "brand_manager", "auto_approve": False},
            ]
        },
        "competitor_urls": [
            "https://instagram.com/competitor_a_example",
            "https://instagram.com/competitor_b_example",
        ],
        "is_active": True,
        "is_bc_linked": False,
        "bc_vendor_filter": [],
    }

    resp = client.post(f"{API_V1}/brands", json=payload)
    resp.raise_for_status()
    brand = resp.json()
    brand_id = brand["id"]
    print(f"  Brand created: {brand['name']} (id={brand_id})")
    return brand_id


def seed_prompt_versions(client: httpx.Client) -> None:
    """Create initial prompt versions for each workflow step."""
    prompts = [
        {
            "workflow": "content_generation",
            "step": "generate_draft",
            "version": 1,
            "content": (
                "You are a social media content creator for {{brand_name}}.\n\n"
                "Create a {{platform}} post about {{product_name}}.\n"
                "Tone: {{tone}}\n"
                "Pillars: {{pillars}}\n\n"
                "Output only the post text with hashtags if applicable."
            ),
            "variables": ["brand_name", "platform", "product_name", "tone", "pillars"],
            "is_active": True,
            "ab_test_weight": 1.0,
        },
        {
            "workflow": "content_generation",
            "step": "review_compliance",
            "version": 1,
            "content": (
                "Review the following social media post for brand safety.\n\n"
                "Brand: {{brand_name}}\n"
                "Safety rules:\n{{brand_safety_rules}}\n\n"
                "Post:\n{{draft_content}}\n\n"
                "Respond with JSON: {\"approved\": bool, \"issues\": [str], \"suggested_edits\": str|null}"
            ),
            "variables": ["brand_name", "brand_safety_rules", "draft_content"],
            "is_active": True,
            "ab_test_weight": 1.0,
        },
        {
            "workflow": "research_summary",
            "step": "summarize",
            "version": 1,
            "content": (
                "Summarize the following research for {{brand_name}} on {{research_topic}}.\n\n"
                "Data:\n{{research_data}}\n\n"
                "Provide 2-3 key findings with actionable recommendations. "
                "Do not invent data points not present in the research."
            ),
            "variables": ["brand_name", "research_topic", "research_data"],
            "is_active": True,
            "ab_test_weight": 1.0,
        },
        {
            "workflow": "strategy_recommendation",
            "step": "recommend",
            "version": 1,
            "content": (
                "Based on the following engagement data and brand context, "
                "recommend content strategy adjustments for {{brand_name}}.\n\n"
                "Current pillars: {{content_pillars}}\n"
                "Engagement summary: {{engagement_summary}}\n"
                "Competitor insights: {{competitor_insights}}\n\n"
                "Provide specific, actionable recommendations."
            ),
            "variables": [
                "brand_name",
                "content_pillars",
                "engagement_summary",
                "competitor_insights",
            ],
            "is_active": True,
            "ab_test_weight": 1.0,
        },
    ]

    for p in prompts:
        resp = client.post(f"{API_V1}/prompt-versions", json=p)
        resp.raise_for_status()
        pv = resp.json()
        print(f"  Prompt version created: {pv['workflow']}/{pv['step']} v{pv['version']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed MARKAI dev environment")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend API base URL (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    print(f"Seeding dev data against {base_url} ...")

    client = httpx.Client(base_url=base_url, timeout=30)

    # Health check
    try:
        resp = client.get("/health")
        resp.raise_for_status()
        print(f"  Backend healthy: {resp.json()}")
    except httpx.HTTPError as exc:
        print(f"ERROR: Backend not reachable at {base_url}: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n1. Creating test brand...")
    seed_brand(client)

    print("\n2. Creating prompt versions...")
    seed_prompt_versions(client)

    print("\nDev seed complete.")


if __name__ == "__main__":
    main()
