"""Pull worldwide Google Trends, score each one for every active brand
via an LLM (creatively, not just keyword-matching), and upsert the keepers
into the `trending_topics` table.

Runs on a 6-hour cron. The LLM is permissive — it asks
"could this trend become a good ad angle for this brand, even if not
directly related?" so unrelated-but-creative ideas get through.
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import async_session_factory
from app.models.brand import Brand
from app.models.trending_topic import TrendingTopic

logger = logging.getLogger(__name__)

# ── Tunables ─────────────────────────────────────────────────────────────

# Score threshold below which a trend is dropped for the brand.
# 0..100 — 50 = "could plausibly fit"; lower = more permissive.
MIN_RELEVANCE_SCORE = 50

# How many top trends to keep per brand per run.
MAX_TRENDS_PER_BRAND = 20

# Time-to-live for rows after they're discovered.
TRENDS_TTL_DAYS = 14


# ─────────────────────────────────────────────────────────────────────────
# Google Trends pull (worldwide, via the public RSS "Trending now" feed)
# ─────────────────────────────────────────────────────────────────────────

# Public, no-auth Google Trends feed. Same data as the trends.google.com
# "Trending now" page. Each <item> carries title + approx_traffic + first
# related news article. Stable as of 2026 — replaced the deprecated
# pytrends.trending_searches endpoint which now returns 404.
_TRENDS_RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"
_TRENDS_GEOS = ("US", "GB", "FR", "IN", "JP", "ZA")
_TRENDS_NS = {"ht": "https://trends.google.com/trending/rss"}


async def pull_google_trends_worldwide() -> list[dict[str, Any]]:
    """Return raw worldwide trending searches as a flat list of dicts.

    Fetches the public Google Trends RSS feed for several geos in parallel,
    parses the XML, and dedupes by lower-cased topic. Best-effort — returns
    an empty list on any total failure.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
    }

    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        for geo in _TRENDS_GEOS:
            try:
                resp = await client.get(_TRENDS_RSS_URL.format(geo=geo))
                if resp.status_code != 200 or not resp.text:
                    logger.debug("Trends RSS %s: HTTP %s", geo, resp.status_code)
                    continue
                root = ET.fromstring(resp.text)
            except Exception as exc:
                logger.debug("Trends RSS %s: fetch/parse failed — %s", geo, exc)
                continue

            for item in root.iter("item"):
                title_el = item.find("title")
                topic = (title_el.text or "").strip() if title_el is not None else ""
                if not topic or topic.lower() in seen:
                    continue
                seen.add(topic.lower())

                approx_el = item.find("ht:approx_traffic", _TRENDS_NS)
                raw_metric = (approx_el.text or "").strip() if approx_el is not None else None

                news_url_el = item.find("ht:news_item/ht:news_item_url", _TRENDS_NS)
                news_url = (news_url_el.text or "").strip() if news_url_el is not None else None

                out.append({
                    "topic": topic,
                    "source": "google",
                    "source_url": news_url
                    or f"https://trends.google.com/trends/explore?q={quote_plus(topic)}",
                    "raw_metric": raw_metric,
                    "metadata": {"geo": geo},
                })

    if not out:
        logger.warning("Google Trends RSS returned 0 items across all geos")
    return out


# ─────────────────────────────────────────────────────────────────────────
# LLM scoring — creative / permissive, per brand
# ─────────────────────────────────────────────────────────────────────────


_SCORING_SYSTEM_PROMPT = (
    "You are a creative marketing strategist. Given a list of trending topics "
    "and a brand's pillars + audiences + positioning, you decide if each "
    "trend could be turned into a useful marketing post for this brand.\n\n"
    "Be PERMISSIVE and CREATIVE — even if a trend has no direct relation to "
    "the brand's category, ask yourself: 'could a skilled copywriter bridge "
    "this trend to one of the brand's products, audiences, or values to make "
    "a memorable post?' If yes, accept it with a clear pitch.\n\n"
    "Reject only when the trend is:\n"
    "- Politically divisive or sensitive\n"
    "- Tragedy / disaster / death\n"
    "- Adult / NSFW content\n"
    "- Truly unbridgeable (e.g. a niche software bug for a food brand)\n\n"
    "For each accepted trend, return:\n"
    "- score: 0..100 (50+ to keep, higher = stronger fit)\n"
    "- reason: 1 short sentence explaining the bridge\n"
    "- angle: a punchy 1-2 sentence pitch ready to use as a post brief "
    "(specific, actionable, voice already adapted to the brand)\n\n"
    "Return STRICT JSON of the form:\n"
    '{"results": [{"topic": "<exact original topic>", "score": <int>, '
    '"reason": "<sentence>", "angle": "<pitch>"}, ...]}'
)


async def _call_llm_json(messages: list[dict], temperature: float = 0.5) -> dict[str, Any]:
    """Minimal LLM JSON call. Mirrors the pattern in intelligence.py but
    stays local to this service so it has no cross-module dependency."""
    from app.services.ai_model_service import get_active_model

    model_id = await get_active_model("text-fast")

    body = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Try LiteLLM proxy first
        if settings.LITELLM_BASE_URL:
            try:
                headers = {"Content-Type": "application/json"}
                if settings.LITELLM_MASTER_KEY:
                    headers["Authorization"] = f"Bearer {settings.LITELLM_MASTER_KEY}"
                resp = await client.post(
                    settings.LITELLM_BASE_URL.rstrip("/") + "/v1/chat/completions",
                    headers=headers,
                    json={**body, "model": f"openai/{model_id}"},
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)
            except Exception as litellm_exc:
                logger.debug("LiteLLM failed, falling back to OpenAI: %s", litellm_exc)

        # Direct OpenAI fallback
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("LiteLLM unreachable and OPENAI_API_KEY not set")

        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            },
            json=body,
        )
        resp.raise_for_status()
        return json.loads(resp.json()["choices"][0]["message"]["content"])


def _build_brand_context(brand: Brand) -> str:
    """Compact brand description fed to the LLM scorer."""
    guidelines = brand.brand_guidelines or {}
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except Exception:
            guidelines = {}

    pillars = guidelines.get("content_pillars") or guidelines.get("pillars") or []
    pillar_names: list[str] = []
    for p in pillars[:8]:
        if isinstance(p, dict):
            name = p.get("name") or p.get("title")
            if name:
                pillar_names.append(str(name))
        elif isinstance(p, str):
            pillar_names.append(p)

    audiences = (
        brand.target_audience
        if isinstance(brand.target_audience, dict)
        else (brand.target_audience or {})
    )
    audience_names: list[str] = []
    audiences_raw = audiences.get("personas") or audiences.get("audiences") or []
    if not isinstance(audiences_raw, list):
        audiences_raw = []
    for a in audiences_raw[:8]:
        if isinstance(a, dict):
            name = a.get("name")
            if name:
                audience_names.append(str(name))
        elif isinstance(a, str):
            audience_names.append(a)

    positioning = guidelines.get("positioning") or guidelines.get("value_proposition") or ""
    if isinstance(positioning, dict):
        positioning = positioning.get("value_proposition") or json.dumps(positioning)[:400]
    positioning = str(positioning)[:600]

    voice = brand.tone_of_voice or guidelines.get("tone_of_voice") or ""
    voice = str(voice)[:300]

    parts = [f"BRAND: {brand.name}"]
    if brand.description:
        parts.append(f"DESCRIPTION: {str(brand.description)[:400]}")
    if pillar_names:
        parts.append(f"PILLARS: {', '.join(pillar_names)}")
    if audience_names:
        parts.append(f"AUDIENCES: {', '.join(audience_names)}")
    if positioning:
        parts.append(f"POSITIONING: {positioning}")
    if voice:
        parts.append(f"VOICE: {voice}")
    return "\n".join(parts)


async def score_trends_for_brand(
    brand: Brand, raw_trends: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """LLM-score every raw trend for a single brand. Returns the trends
    augmented with `score`, `reason`, and `angle`. Trends the LLM
    rejected (or below MIN_RELEVANCE_SCORE) are filtered out.
    """
    if not raw_trends:
        return []

    brand_context = _build_brand_context(brand)
    topics_block = "\n".join(f"- {t['topic']}" for t in raw_trends)

    user_msg = (
        f"{brand_context}\n\n"
        f"TRENDS TO EVALUATE:\n{topics_block}\n\n"
        "Return JSON as specified. Skip trends you reject — only include "
        "trends with a real angle for this brand."
    )

    try:
        result = await _call_llm_json(
            [
                {"role": "system", "content": _SCORING_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.6,
        )
    except Exception as exc:
        logger.warning("LLM scoring failed for brand %s: %s", brand.name, exc)
        return []

    results = result.get("results") if isinstance(result, dict) else None
    if not isinstance(results, list):
        return []

    # Index raw trends by lowered topic for quick lookup of source metadata.
    raw_by_topic = {str(t["topic"]).lower(): t for t in raw_trends}

    scored: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        topic = str(r.get("topic", "")).strip()
        score = r.get("score")
        if not topic or not isinstance(score, (int, float)):
            continue
        score = int(score)
        if score < MIN_RELEVANCE_SCORE:
            continue
        raw = raw_by_topic.get(topic.lower())
        if not raw:
            # LLM hallucinated a topic not in the list — skip.
            continue
        scored.append({
            **raw,
            "topic": raw["topic"],  # preserve original casing
            "relevance_score": score,
            "relevance_reason": str(r.get("reason", ""))[:600],
            "llm_angle": str(r.get("angle", ""))[:1200],
        })

    # Keep the top N by score
    scored.sort(key=lambda x: x["relevance_score"], reverse=True)
    return scored[:MAX_TRENDS_PER_BRAND]


# ─────────────────────────────────────────────────────────────────────────
# Velocity (rising / stable / falling) — derived from yesterday's state
# ─────────────────────────────────────────────────────────────────────────


async def _compute_velocity(
    db: AsyncSession, brand_id: str, topic: str
) -> str:
    """Compare against the previous row for this (brand, topic) if any.
    score > previous → rising; less → falling; same/absent → stable."""
    prev = await db.execute(
        select(TrendingTopic.relevance_score)
        .where(TrendingTopic.brand_id == brand_id)
        .where(TrendingTopic.topic == topic)
    )
    row = prev.first()
    if row is None:
        return "stable"
    return "stable"  # set by upsert below — fine to be lazy here, we compute it inline


# ─────────────────────────────────────────────────────────────────────────
# Upsert + cleanup
# ─────────────────────────────────────────────────────────────────────────


async def _upsert_trends(
    db: AsyncSession,
    brand_id: str,
    scored_trends: list[dict[str, Any]],
) -> int:
    """Upsert scored trends into trending_topics. Returns number of rows
    upserted. Velocity is computed inline by comparing to the existing
    row (if any)."""
    if not scored_trends:
        return 0

    # Fetch existing scores for these topics (one query)
    topics = [t["topic"] for t in scored_trends]
    existing = await db.execute(
        select(TrendingTopic.topic, TrendingTopic.relevance_score)
        .where(TrendingTopic.brand_id == brand_id)
        .where(TrendingTopic.topic.in_(topics))
    )
    prev_scores = {row[0]: row[1] for row in existing.all()}

    expires_at = datetime.now(timezone.utc) + timedelta(days=TRENDS_TTL_DAYS)
    count = 0
    for t in scored_trends:
        prev_score = prev_scores.get(t["topic"])
        new_score = t["relevance_score"]
        if prev_score is None or prev_score == new_score:
            velocity = "stable"
        elif new_score > prev_score:
            velocity = "rising"
        else:
            velocity = "falling"

        # pg_insert().values() and stmt.excluded both work at the table
        # level, so keys here are SQL column names, not ORM attribute names.
        # The TrendingTopic.extra_data attribute maps to the SQL column
        # named `metadata` — use that name throughout the UPSERT.
        stmt = pg_insert(TrendingTopic).values(
            brand_id=brand_id,
            topic=t["topic"],
            source=t.get("source", "google"),
            source_url=t.get("source_url"),
            raw_metric=t.get("raw_metric"),
            velocity=velocity,
            relevance_score=new_score,
            relevance_reason=t.get("relevance_reason"),
            llm_angle=t.get("llm_angle"),
            metadata=t.get("metadata") or {},
            expires_at=expires_at,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="trending_topics_brand_topic_uniq",
            set_={
                "source_url": stmt.excluded.source_url,
                "raw_metric": stmt.excluded.raw_metric,
                "velocity": stmt.excluded.velocity,
                "relevance_score": stmt.excluded.relevance_score,
                "relevance_reason": stmt.excluded.relevance_reason,
                "llm_angle": stmt.excluded.llm_angle,
                "metadata": stmt.excluded.metadata,
                "discovered_at": text("now()"),
                "expires_at": stmt.excluded.expires_at,
            },
        )
        await db.execute(stmt)
        count += 1

    await db.commit()
    return count


async def _cleanup_expired(db: AsyncSession) -> int:
    """Delete rows past their expires_at. Returns count removed."""
    result = await db.execute(
        text("DELETE FROM trending_topics WHERE expires_at < now() RETURNING id")
    )
    rows = result.fetchall()
    await db.commit()
    return len(rows)


# ─────────────────────────────────────────────────────────────────────────
# Orchestrator (called by the 6h cron)
# ─────────────────────────────────────────────────────────────────────────


async def pull_and_score_all_brands() -> None:
    """Entry point for the cron. Pulls Google Trends once, then scores
    them per active brand, upserts the keepers, and cleans up expired."""
    logger.info("Starting trending topics pull + score cycle")

    raw_trends = await pull_google_trends_worldwide()
    if not raw_trends:
        logger.warning("No raw trends pulled from Google — nothing to score")
        return
    logger.info("Pulled %d raw trends from Google Trends", len(raw_trends))

    async with async_session_factory() as db:
        brands_result = await db.execute(
            select(Brand).where(Brand.is_active.is_(True))
        )
        brands = list(brands_result.scalars().all())
        logger.info("Scoring trends for %d active brands", len(brands))

        total_upserted = 0
        for brand in brands:
            try:
                scored = await score_trends_for_brand(brand, raw_trends)
                if not scored:
                    logger.info("Brand %s: 0 trends kept after scoring", brand.name)
                    continue
                upserted = await _upsert_trends(db, str(brand.id), scored)
                total_upserted += upserted
                logger.info(
                    "Brand %s: %d trends upserted (top score=%d)",
                    brand.name, upserted, scored[0]["relevance_score"],
                )
            except Exception as exc:
                logger.exception(
                    "Trend scoring failed for brand %s: %s", brand.name, exc
                )

        # Cleanup expired rows globally (cheap, one DELETE)
        removed = await _cleanup_expired(db)
        logger.info(
            "Trends cycle complete: %d rows upserted, %d expired rows removed",
            total_upserted, removed,
        )
