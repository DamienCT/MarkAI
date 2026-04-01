"""Social platform data tools.  Fetches real profile info, posts, and engagement
metrics from Instagram, Facebook, and LinkedIn APIs using tokens from env vars."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

# ── Rate limiting ───────────────────────────────────────────────────────
_RATE_LIMIT_DELAY = 0.5  # seconds between API calls
_MAX_RETRIES = 3
_BACKOFF_BASE = 2  # exponential backoff base for 429 retries

# ── Shared httpx client (lazy singleton) ────────────────────────────────
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_connections=20),
        )
    return _http_client


async def _rate_limited_request(
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Execute an HTTP request with rate limiting and retry on 429."""
    client = _get_http_client()
    await asyncio.sleep(_RATE_LIMIT_DELAY)

    for attempt in range(_MAX_RETRIES):
        resp = await getattr(client, method)(url, **kwargs)
        if resp.status_code == 429:
            wait = _BACKOFF_BASE**attempt
            logger.warning(
                "Rate limited (429) on %s %s — retrying in %ds (attempt %d/%d)",
                method.upper(),
                url,
                wait,
                attempt + 1,
                _MAX_RETRIES,
            )
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        return resp

    # Final attempt — let the exception propagate
    resp = await getattr(client, method)(url, **kwargs)
    resp.raise_for_status()
    return resp


_IG_BASE = "https://graph.instagram.com/v20.0"
_FB_BASE = "https://graph.facebook.com/v20.0"
_LI_BASE = "https://api.linkedin.com/v2"


# ── Instagram ────────────────────────────────────────────────────────────


async def ig_get_profile(ig_user_id: str) -> dict[str, Any]:
    """Fetch Instagram business profile info."""
    resp = await _rate_limited_request(
        "get",
        f"{_IG_BASE}/{ig_user_id}",
        params={
            "fields": "id,username,name,biography,followers_count,follows_count,media_count,profile_picture_url,website",
            "access_token": settings.META_ACCESS_TOKEN,
        },
    )
    return resp.json()


async def ig_get_recent_posts(ig_user_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Fetch recent Instagram posts with engagement data."""
    resp = await _rate_limited_request(
        "get",
        f"{_IG_BASE}/{ig_user_id}/media",
        params={
            "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
            "limit": limit,
            "access_token": settings.META_ACCESS_TOKEN,
        },
    )
    data = resp.json()
    return data.get("data", [])


async def ig_get_post_insights(media_id: str) -> dict[str, Any]:
    """Fetch insights (reach, impressions, engagement) for a single post."""
    resp = await _rate_limited_request(
        "get",
        f"{_IG_BASE}/{media_id}/insights",
        params={
            "metric": "impressions,reach,engagement,saved",
            "access_token": settings.META_ACCESS_TOKEN,
        },
    )
    data = resp.json()
    return {item["name"]: item["values"][0]["value"] for item in data.get("data", [])}


# ── Facebook ─────────────────────────────────────────────────────────────


async def fb_get_page(page_id: str) -> dict[str, Any]:
    """Fetch Facebook Page profile info."""
    resp = await _rate_limited_request(
        "get",
        f"{_FB_BASE}/{page_id}",
        params={
            "fields": "id,name,about,fan_count,followers_count,category,website,link",
            "access_token": settings.META_ACCESS_TOKEN,
        },
    )
    return resp.json()


async def fb_get_recent_posts(page_id: str, limit: int = 25) -> list[dict[str, Any]]:
    """Fetch recent Facebook Page posts with engagement."""
    resp = await _rate_limited_request(
        "get",
        f"{_FB_BASE}/{page_id}/posts",
        params={
            "fields": "id,message,created_time,permalink_url,shares,full_picture,"
            "reactions.summary(true),comments.summary(true)",
            "limit": limit,
            "access_token": settings.META_ACCESS_TOKEN,
        },
    )
    data = resp.json()
    return data.get("data", [])


# ── LinkedIn ─────────────────────────────────────────────────────────────


async def li_get_organization(org_id: str) -> dict[str, Any]:
    """Fetch LinkedIn organization profile."""
    resp = await _rate_limited_request(
        "get",
        f"{_LI_BASE}/organizations/{org_id}",
        headers={"Authorization": f"Bearer {settings.LINKEDIN_ACCESS_TOKEN}"},
    )
    return resp.json()


async def li_get_follower_count(org_id: str) -> int:
    """Fetch LinkedIn organization follower count."""
    resp = await _rate_limited_request(
        "get",
        f"{_LI_BASE}/organizationalEntityFollowerStatistics",
        params={
            "q": "organizationalEntity",
            "organizationalEntity": f"urn:li:organization:{org_id}",
        },
        headers={"Authorization": f"Bearer {settings.LINKEDIN_ACCESS_TOKEN}"},
    )
    data = resp.json()
    elements = data.get("elements", [])
    if elements:
        follower_counts = elements[0].get("followerCounts", {})
        return follower_counts.get("organicFollowerCount", 0) + follower_counts.get(
            "paidFollowerCount", 0
        )
    return 0


async def li_get_recent_posts(org_id: str, count: int = 25) -> list[dict[str, Any]]:
    """Fetch recent LinkedIn organization posts."""
    resp = await _rate_limited_request(
        "get",
        f"{_LI_BASE}/ugcPosts",
        params={
            "q": "authors",
            "authors": f"urn:li:organization:{org_id}",
            "count": count,
        },
        headers={"Authorization": f"Bearer {settings.LINKEDIN_ACCESS_TOKEN}"},
    )
    data = resp.json()
    return data.get("elements", [])


# ── Aggregated helpers ───────────────────────────────────────────────────


async def get_social_profiles(
    ig_user_id: str | None = None,
    fb_page_id: str | None = None,
    li_org_id: str | None = None,
) -> dict[str, Any]:
    """Fetch all available social profiles for a brand."""
    profiles: dict[str, Any] = {}

    if ig_user_id and settings.META_ACCESS_TOKEN:
        try:
            profiles["instagram"] = await ig_get_profile(ig_user_id)
        except Exception:
            logger.exception("Failed to fetch Instagram profile")

    if fb_page_id and settings.META_ACCESS_TOKEN:
        try:
            profiles["facebook"] = await fb_get_page(fb_page_id)
        except Exception:
            logger.exception("Failed to fetch Facebook page")

    if li_org_id and settings.LINKEDIN_ACCESS_TOKEN:
        try:
            profiles["linkedin"] = await li_get_organization(li_org_id)
        except Exception:
            logger.exception("Failed to fetch LinkedIn organization")

    return profiles


async def get_engagement_data(
    ig_user_id: str | None = None,
    fb_page_id: str | None = None,
    li_org_id: str | None = None,
    post_limit: int = 25,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch recent posts and engagement across all platforms."""
    engagement: dict[str, list[dict[str, Any]]] = {}

    if ig_user_id and settings.META_ACCESS_TOKEN:
        try:
            engagement["instagram"] = await ig_get_recent_posts(ig_user_id, post_limit)
        except Exception:
            logger.exception("Failed to fetch Instagram posts")

    if fb_page_id and settings.META_ACCESS_TOKEN:
        try:
            engagement["facebook"] = await fb_get_recent_posts(fb_page_id, post_limit)
        except Exception:
            logger.exception("Failed to fetch Facebook posts")

    if li_org_id and settings.LINKEDIN_ACCESS_TOKEN:
        try:
            engagement["linkedin"] = await li_get_recent_posts(li_org_id, post_limit)
        except Exception:
            logger.exception("Failed to fetch LinkedIn posts")

    return engagement
