import logging
from typing import Any

import httpx

from app.models.content import Content

logger = logging.getLogger(__name__)

# Graph API version. `impressions` was deprecated for Instagram media (replaced
# by `views`) — older versions + that metric made the whole insights request
# fail, which is why analytics came back empty.
_GRAPH_VERSION = "v25.0"


async def pull_instagram_insights(
    content: Content, access_token: str
) -> dict[str, Any]:
    """
    Direct call to Instagram Graph API for post insights.
    Uses the brand's meta_access_token and the content's platform_post_id.

    Two separate calls, both fault-tolerant so one bad metric never zeroes the
    whole pull:
      1. Media object fields → like_count / comments_count (these are NOT
         insights metrics).
      2. /insights → reach, saved, shares, views (views replaces the now-removed
         `impressions`). Degrades to a smaller metric set if one isn't valid for
         this media type/account.
    """
    post_id = content.platform_post_id
    result: dict[str, Any] = {
        "impressions": 0, "reach": 0, "saves": 0,
        "likes": 0, "comments": 0, "shares": 0,
    }
    if not post_id:
        return result

    async with httpx.AsyncClient(timeout=30) as client:
        # 1) Engagement counts live on the media object, not on /insights.
        try:
            resp = await client.get(
                f"https://graph.facebook.com/{_GRAPH_VERSION}/{post_id}",
                params={"fields": "like_count,comments_count", "access_token": access_token},
            )
            resp.raise_for_status()
            d = resp.json()
            result["likes"] = d.get("like_count", 0) or 0
            result["comments"] = d.get("comments_count", 0) or 0
        except Exception as exc:
            logger.warning("IG media fields failed for %s: %s", post_id, exc)

        # 2) Insights. Try the richest valid set, then degrade so one
        #    unsupported metric doesn't fail the whole request.
        for metric in (
            "reach,saved,shares,views",
            "reach,saved,shares",
            "reach,saved",
            "reach",
        ):
            try:
                resp = await client.get(
                    f"https://graph.facebook.com/{_GRAPH_VERSION}/{post_id}/insights",
                    params={"metric": metric, "access_token": access_token},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
            except Exception as exc:
                logger.warning(
                    "IG insights metric=%s failed for %s: %s", metric, post_id, exc
                )
                continue
            m = {
                item["name"]: (item.get("values") or [{}])[0].get("value", 0) or 0
                for item in data
            }
            result["reach"] = m.get("reach", result["reach"])
            result["saves"] = m.get("saved", result["saves"])
            result["shares"] = m.get("shares", result["shares"])
            # `views` is the modern replacement for the removed `impressions`.
            if "views" in m:
                result["impressions"] = m["views"]
            break

    return result


async def pull_facebook_insights(content: Content, access_token: str) -> dict[str, Any]:
    """
    Direct call to Facebook Graph API for post insights. Fault-tolerant: counts
    come from field summaries (reliable), reach/impressions/clicks from insights.
    """
    post_id = content.platform_post_id
    result: dict[str, Any] = {
        "impressions": 0, "reach": 0, "clicks": 0,
        "likes": 0, "comments": 0, "shares": 0,
    }
    if not post_id:
        return result

    async with httpx.AsyncClient(timeout=30) as client:
        # Engagement counts via summaries (more reliable than reaction insights).
        try:
            resp = await client.get(
                f"https://graph.facebook.com/{_GRAPH_VERSION}/{post_id}",
                params={
                    "fields": "likes.summary(true).limit(0),comments.summary(true).limit(0),shares",
                    "access_token": access_token,
                },
            )
            resp.raise_for_status()
            d = resp.json()
            result["likes"] = ((d.get("likes") or {}).get("summary") or {}).get("total_count", 0) or 0
            result["comments"] = ((d.get("comments") or {}).get("summary") or {}).get("total_count", 0) or 0
            result["shares"] = (d.get("shares") or {}).get("count", 0) or 0
        except Exception as exc:
            logger.warning("FB fields failed for %s: %s", post_id, exc)

        # Reach / impressions / clicks via insights. Degrade the metric set so
        # one metric that's invalid on this API version doesn't 400 the whole
        # request (leaving impressions/reach at 0).
        for metric in (
            "post_impressions,post_impressions_unique,post_clicks",
            "post_impressions,post_impressions_unique",
            "post_impressions",
        ):
            try:
                resp = await client.get(
                    f"https://graph.facebook.com/{_GRAPH_VERSION}/{post_id}/insights",
                    params={"metric": metric, "access_token": access_token},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
            except Exception as exc:
                logger.warning(
                    "FB insights metric=%s failed for %s: %s", metric, post_id, exc
                )
                continue
            for m in data:
                val = (m.get("values") or [{}])[0].get("value", 0) or 0
                if isinstance(val, dict):
                    val = sum(val.values())
                if m["name"] == "post_impressions":
                    result["impressions"] = val
                elif m["name"] == "post_impressions_unique":
                    result["reach"] = val
                elif m["name"] == "post_clicks":
                    result["clicks"] = val
            break

    return result


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
