import logging
from typing import Any

import httpx

from app.models.content import Content

logger = logging.getLogger(__name__)


async def pull_instagram_insights(
    content: Content, access_token: str
) -> dict[str, Any]:
    """
    Direct call to Instagram Graph API for post insights.
    Uses the brand's meta_access_token and the content's platform_post_id.
    """
    post_id = content.platform_post_id

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://graph.facebook.com/v21.0/{post_id}/insights",
            params={
                "metric": "impressions,reach,saved,likes,comments,shares",
                "access_token": access_token,
            },
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])

    metrics: dict[str, int] = {}
    for m in data:
        metrics[m["name"]] = m.get("values", [{}])[0].get("value", 0)

    return {
        "impressions": metrics.get("impressions", 0),
        "reach": metrics.get("reach", 0),
        "saves": metrics.get("saved", 0),
        "likes": metrics.get("likes", 0),
        "comments": metrics.get("comments", 0),
        "shares": metrics.get("shares", 0),
    }


async def pull_facebook_insights(content: Content, access_token: str) -> dict[str, Any]:
    """
    Direct call to Facebook Graph API for post insights.
    """
    post_id = content.platform_post_id

    async with httpx.AsyncClient(timeout=30) as client:
        # Get basic metrics
        resp = await client.get(
            f"https://graph.facebook.com/v21.0/{post_id}",
            params={
                "fields": "insights.metric(post_impressions,post_impressions_unique,post_clicks,post_reactions_by_type_total)",
                "access_token": access_token,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    insights = data.get("insights", {}).get("data", [])
    metrics: dict[str, int] = {}
    for m in insights:
        val = m.get("values", [{}])[0].get("value", 0)
        if isinstance(val, dict):
            metrics[m["name"]] = sum(val.values())
        else:
            metrics[m["name"]] = val

    return {
        "impressions": metrics.get("post_impressions", 0),
        "reach": metrics.get("post_impressions_unique", 0),
        "clicks": metrics.get("post_clicks", 0),
        "likes": metrics.get("post_reactions_by_type_total", 0),
    }


async def pull_linkedin_insights(
    content: Content, access_token: str, org_id: str
) -> dict[str, Any]:
    """
    Direct call to LinkedIn API for post analytics.
    """
    post_urn = content.platform_post_id

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://api.linkedin.com/v2/socialActions/{}/statistics".format(post_urn),
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Restli-Protocol-Version": "2.0.0",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "likes": data.get("likeCount", 0),
        "comments": data.get("commentCount", 0),
        "shares": data.get("shareCount", 0),
        "impressions": data.get("impressionCount", 0),
        "clicks": data.get("clickCount", 0),
    }
