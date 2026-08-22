import logging
from typing import Any

import httpx

from app.models.content import Content
from app.services.publishers.x import oauth1_auth_header
from app.utils.redact import redact

logger = logging.getLogger(__name__)

# Graph API version. `impressions` was deprecated for Instagram media (replaced
# by `views`) — older versions + that metric made the whole insights request
# fail, which is why analytics came back empty.
_GRAPH_VERSION = "v25.0"

# Tweet lookup endpoint (public_metrics ride on the tweet object).
_X_TWEETS_URL = "https://api.x.com/2/tweets"

# videos.list endpoint (part=statistics with an API key).
_YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


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
            # Token goes in the Authorization header, never the URL — query
            # strings end up in logs and exception messages (N-01).
            resp = await client.get(
                f"https://graph.facebook.com/{_GRAPH_VERSION}/{post_id}",
                params={"fields": "like_count,comments_count"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            d = resp.json()
            result["likes"] = d.get("like_count", 0) or 0
            result["comments"] = d.get("comments_count", 0) or 0
        except Exception as exc:
            logger.warning("IG media fields failed for %s: %s", post_id, redact(exc))

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
                    params={"metric": metric},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
            except Exception as exc:
                logger.warning(
                    "IG insights metric=%s failed for %s: %s",
                    metric,
                    post_id,
                    redact(exc),
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
                },
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            d = resp.json()
            result["likes"] = ((d.get("likes") or {}).get("summary") or {}).get("total_count", 0) or 0
            result["comments"] = ((d.get("comments") or {}).get("summary") or {}).get("total_count", 0) or 0
            result["shares"] = (d.get("shares") or {}).get("count", 0) or 0
        except Exception as exc:
            logger.warning("FB fields failed for %s: %s", post_id, redact(exc))

        # Reach / impressions / clicks via insights. Meta's "new Pages
        # experience" deprecated several post metrics (e.g. post_impressions),
        # and the valid names vary, so try candidates individually and keep
        # whatever validates — invalid ones (#100) are skipped, not fatal.
        fb_candidates = [
            ("impressions", "post_impressions"),
            ("impressions", "post_impressions_organic"),
            ("impressions", "post_impressions_unique"),
            ("reach", "post_impressions_unique"),
            ("reach", "post_impressions_organic_unique"),
            ("clicks", "post_clicks"),
            ("clicks", "post_clicks_unique"),
        ]
        for key, metric in fb_candidates:
            if result.get(key):
                continue  # already filled this metric from an earlier candidate
            try:
                resp = await client.get(
                    f"https://graph.facebook.com/{_GRAPH_VERSION}/{post_id}/insights",
                    params={"metric": metric},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
            except Exception:
                continue  # metric not valid on this version — try the next
            for m in data:
                val = (m.get("values") or [{}])[0].get("value", 0) or 0
                if isinstance(val, dict):
                    val = sum(val.values())
                if val:
                    result[key] = val
                    logger.info(
                        "FB insights %s via metric=%s = %s", key, metric, val
                    )

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


async def pull_x_public_metrics(
    content: Content, creds: dict[str, Any]
) -> dict[str, Any]:
    """
    Direct call to the X API for tweet public_metrics:
    ``GET /2/tweets?ids=…&tweet.fields=public_metrics``.

    Signed with the same OAuth 1.0a user-context helper the X publisher uses
    (query params participate in the RFC 5849 signature); ``creds`` carries
    the brand's four user-context keys. Retweets + quote tweets both count
    as "shares"; ``impression_count`` maps to impressions and
    ``bookmark_count`` to saves.
    """
    tweet_id = content.platform_post_id
    result: dict[str, Any] = {
        "impressions": 0, "likes": 0, "comments": 0, "shares": 0, "saves": 0,
    }
    if not tweet_id:
        return result

    params = {"ids": tweet_id, "tweet.fields": "public_metrics"}
    auth_header = oauth1_auth_header(
        "GET",
        _X_TWEETS_URL,
        consumer_key=creds["consumer_key"],
        consumer_secret=creds["consumer_secret"],
        access_token=creds["access_token"],
        access_token_secret=creds["access_token_secret"],
        request_params=params,
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _X_TWEETS_URL,
            params=params,
            headers={"Authorization": auth_header},
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []

    metrics = (data[0].get("public_metrics") or {}) if data else {}
    result["likes"] = metrics.get("like_count", 0) or 0
    result["comments"] = metrics.get("reply_count", 0) or 0
    result["shares"] = (metrics.get("retweet_count", 0) or 0) + (
        metrics.get("quote_count", 0) or 0
    )
    result["saves"] = metrics.get("bookmark_count", 0) or 0
    result["impressions"] = metrics.get("impression_count", 0) or 0
    return result


async def pull_youtube_statistics(
    content: Content, api_key: str
) -> dict[str, Any]:
    """
    Direct call to the YouTube Data API: ``videos.list part=statistics``.

    The API key rides in the ``X-Goog-Api-Key`` header, never the URL —
    query strings end up in logs and exception messages (N-01). The API
    returns counts as strings, so they are coerced defensively.
    ``viewCount`` maps to both ``video_views`` and ``impressions`` (views
    are YouTube's impression analogue, mirroring the IG `views` mapping) so
    the shared engagement-rate computation gets a denominator.
    """
    video_id = content.platform_post_id
    result: dict[str, Any] = {
        "impressions": 0, "likes": 0, "comments": 0, "video_views": 0,
    }
    if not video_id:
        return result

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            _YOUTUBE_VIDEOS_URL,
            params={"part": "statistics", "id": video_id},
            headers={"X-Goog-Api-Key": api_key},
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []

    stats = (items[0].get("statistics") or {}) if items else {}

    def _count(name: str) -> int:
        try:
            return int(stats.get(name) or 0)
        except (TypeError, ValueError):
            return 0

    result["likes"] = _count("likeCount")
    result["comments"] = _count("commentCount")
    result["video_views"] = _count("viewCount")
    result["impressions"] = result["video_views"]
    return result
