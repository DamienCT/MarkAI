"""Pull worldwide Google Trends, score each one for every active brand
via an LLM (creatively, not just keyword-matching), and upsert the keepers
into the `trending_topics` table.

Runs on a 6-hour cron. The LLM is permissive — it asks
"could this trend become a good ad angle for this brand, even if not
directly related?" so unrelated-but-creative ideas get through.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agent_run import AgentRun
from app.models.base import async_session_factory
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
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
# Google Trends pull (rising queries, via the public Explore API)
# ─────────────────────────────────────────────────────────────────────────

# trends.google.com's Explore page is served by two undocumented JSON APIs:
# 1) POST-like GET /api/explore  → returns widget tokens (one per data card)
# 2) GET /api/widgetdata/relatedsearches  → returns the actual ranked
#    keywords for the RELATED_QUERIES widget. rankedList[0] is "Top" and
#    rankedList[1] is "Rising". We use Rising only — momentum > volume.
#
# This endpoint supports Mauritius (geo=MU), unlike the /trending/rss feed
# which returns 400 for MU.
_TRENDS_EXPLORE_URL = "https://trends.google.com/trends/api/explore"
_TRENDS_WIDGETDATA_URL = "https://trends.google.com/trends/api/widgetdata/relatedsearches"
_TRENDS_WARMUP_URL = "https://trends.google.com/?geo=MU"
_TRENDS_GEOS = ("US", "GB", "FR", "IN", "JP", "ZA", "MU")
_TRENDS_TIME_RANGE = "today 1-m"

_TRENDS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _strip_xssi_prefix(text_body: str) -> str:
    """Google's internal JSON APIs prefix responses with )]}',\\n or similar
    anti-XSSI tokens. Strip everything before the first '{'."""
    idx = text_body.find("{")
    return text_body[idx:] if idx >= 0 else text_body


async def _pull_rising_for_geo(
    client: httpx.AsyncClient, geo: str
) -> list[dict[str, Any]]:
    """Two-step fetch of the 'Rising queries' widget for one geo. Returns
    [] on any failure (best-effort, per-geo isolated)."""
    explore_payload = {
        "comparisonItem": [
            {"keyword": "", "geo": geo, "time": _TRENDS_TIME_RANGE}
        ],
        "category": 0,
        "property": "",
    }
    try:
        resp = await client.get(
            _TRENDS_EXPLORE_URL,
            params={
                "hl": "en-US",
                "tz": "0",
                "req": json.dumps(explore_payload),
            },
        )
        if resp.status_code != 200:
            logger.debug("Trends explore %s: HTTP %s", geo, resp.status_code)
            return []
        explore_data = json.loads(_strip_xssi_prefix(resp.text))
        rq_widget = next(
            (
                w
                for w in explore_data.get("widgets", [])
                if w.get("id") == "RELATED_QUERIES"
            ),
            None,
        )
        if rq_widget is None:
            return []

        await asyncio.sleep(2)

        resp2 = await client.get(
            _TRENDS_WIDGETDATA_URL,
            params={
                "hl": "en-US",
                "tz": "0",
                "req": json.dumps(rq_widget["request"]),
                "token": rq_widget["token"],
            },
        )
        if resp2.status_code != 200:
            logger.debug("Trends widgetdata %s: HTTP %s", geo, resp2.status_code)
            return []
        widget_data = json.loads(_strip_xssi_prefix(resp2.text))

        ranked_lists = widget_data.get("default", {}).get("rankedList", [])
        # rankedList[0] = Top, rankedList[1] = Rising. We only want Rising.
        if len(ranked_lists) < 2:
            return []
        rising = ranked_lists[1].get("rankedKeyword", [])

        out: list[dict[str, Any]] = []
        for item in rising:
            topic = str(item.get("query", "")).strip()[:255]
            if not topic:
                continue
            formatted = str(
                item.get("formattedValue") or item.get("value") or ""
            ).strip()[:50]
            out.append({
                "topic": topic,
                "source": "google_trends_rising",
                "source_url": f"https://trends.google.com/trends/explore?q={quote_plus(topic)}&geo={geo}",
                "raw_metric": formatted or None,
                "metadata": {"geo": geo, "type": "rising"},
            })
        return out
    except Exception as exc:
        logger.debug("Trends pull failed for geo=%s: %s", geo, exc)
        return []


async def pull_google_trends_worldwide() -> list[dict[str, Any]]:
    """Pull RISING queries from Google Trends across our target geos
    (including Maurice), deduplicated by topic. Best-effort: returns
    whatever geos succeeded."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        timeout=20.0, follow_redirects=True, headers=_TRENDS_HEADERS
    ) as client:
        # Warm-up so Google sets the consent cookie. Without it the API
        # often 429s on the first real call from a fresh container IP.
        try:
            await client.get(_TRENDS_WARMUP_URL)
        except Exception:
            pass
        await asyncio.sleep(3)

        for geo in _TRENDS_GEOS:
            geo_trends = await _pull_rising_for_geo(client, geo)
            for t in geo_trends:
                key = t["topic"].lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(t)
            # Spread out the calls — Google rate-limits aggressively.
            await asyncio.sleep(5)

    if not out:
        logger.warning("Google Trends rising: 0 items across all geos")
    else:
        logger.info(
            "Google Trends rising: %d unique items from %d geos",
            len(out),
            len(_TRENDS_GEOS),
        )
    return out


# ─────────────────────────────────────────────────────────────────────────
# LLM scoring — creative / permissive, per brand
# ─────────────────────────────────────────────────────────────────────────


_SCORING_SYSTEM_PROMPT = (
    "You are a creative marketing strategist. You will receive a brand "
    "context (summary + four strategy documents + upcoming calendar) and a "
    "list of trending topics. Decide for each trend if it could be turned "
    "into a useful marketing post for this brand.\n\n"
    "Be PERMISSIVE and CREATIVE — even if a trend has no direct relation to "
    "the brand's category, ask yourself: 'could a skilled copywriter bridge "
    "this trend to one of the brand's products, audiences, or values to make "
    "a memorable post?' If yes, accept it with a clear pitch.\n\n"
    "Reject only when the trend is:\n"
    "- Politically divisive or sensitive\n"
    "- Tragedy / disaster / death / health crisis / outbreak\n"
    "- Adult / NSFW content\n"
    "- Truly unbridgeable (e.g. a niche software bug for a food brand)\n\n"
    "ALSO: for each accepted trend, check the UPCOMING CALENDAR section. If "
    "an existing calendar item ALREADY clearly covers this trend (same event, "
    "same theme — not a loose topical overlap), set already_planned=true. "
    "We will then skip it so the trends list only surfaces gaps. When in "
    "doubt, prefer already_planned=false.\n\n"
    "Return STRICT JSON:\n"
    '{"results": [{"topic": "<exact original topic>", "score": <int 0-100>, '
    '"reason": "<sentence>", "angle": "<pitch>", '
    '"product": "<exact product name from the BRAND PRODUCTS list, or empty string>", '
    '"already_planned": <bool>}, ...]}\n\n'
    "Per-field rules:\n"
    "- score 0..100 — 50+ to keep, higher = stronger fit\n"
    "- reason: 1 short sentence explaining the bridge to this brand\n"
    "- angle: a punchy 1-2 sentence pitch (specific, actionable, voice "
    "already adapted to the brand). MUST embed a CONCRETE VISUAL CUE "
    "matching the trend's context — e.g. 'with the football pitch on the "
    "TV behind' for a football match trend, 'on Roland Garros clay court' "
    "for a tennis trend, 'with a Christmas tree and red ribbons' for a "
    "December trend, 'fireworks at midnight' for New Year, 'red roses on "
    "the table' for Valentine's, 'a basketball court scene' for an NBA "
    "trend. Without this noun the downstream image model produces a "
    "generic scene. Also: name AT MOST ONE brand-product in the angle "
    "(the hero). Describe any companions in GENERIC terms ('charcuterie "
    "spread', 'sharing plates', 'cheese board') — never name a second "
    "brand-product, the image can only have one hero.\n"
    "- product: the hero product MUST be chosen from the BRAND PRODUCTS list "
    "below (copy its name EXACTLY) and should also be referenced in the angle. "
    "If no product in the list fits this trend, return an empty string — do "
    "NOT invent a product that isn't in the list.\n"
    "- already_planned: true ONLY if a calendar item clearly covers it"
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


# Max chars per document section in the LLM prompt (keep tokens reasonable).
_DOC_CHAR_CAP = 1000

# How far ahead we look when checking calendar matches.
_CALENDAR_WINDOW_DAYS = 30
_TREND_PRODUCT_WINDOW = 20  # products shown to the LLM per run (rotating window)

# The four strategy reports we squeeze into the LLM prompt for richer scoring.
_BRAND_DOC_TYPES = ("research", "strategy", "branding", "planning")


async def _load_brand_documents(
    db: AsyncSession, brand_id: Any
) -> dict[str, str]:
    """Return latest completed report per agent_type, as a short text blob
    suitable for direct injection into the LLM prompt."""
    docs: dict[str, str] = {}
    for agent_type in _BRAND_DOC_TYPES:
        result = await db.execute(
            select(AgentRun)
            .where(AgentRun.brand_id == brand_id)
            .where(AgentRun.agent_type == agent_type)
            .where(AgentRun.status == "completed")
            .order_by(AgentRun.completed_at.desc().nullslast())
            .limit(1)
        )
        run = result.scalar_one_or_none()
        if run is None or not isinstance(run.output_payload, dict):
            continue
        payload = run.output_payload
        # Prefer the plain-English summary; fall back to a compact JSON dump
        # of the signal-rich fields if the summary hasn't been generated.
        text_blob = payload.get("executive_summary_plain")
        if not text_blob:
            stripped = {
                k: v
                for k, v in payload.items()
                if k
                not in {
                    "raw_response",
                    "metadata",
                    "tokens_used",
                    "model_used",
                    "model",
                }
            }
            try:
                text_blob = json.dumps(stripped, ensure_ascii=False)
            except Exception:
                text_blob = str(stripped)
        docs[agent_type] = str(text_blob)[:_DOC_CHAR_CAP]
    return docs


async def _load_upcoming_calendar(
    db: AsyncSession, brand_id: Any
) -> list[dict[str, Any]]:
    """Calendar items scheduled in the next CALENDAR_WINDOW_DAYS for this
    brand. Used by the LLM to decide if a trend is already-planned."""
    cutoff = datetime.now(timezone.utc) + timedelta(days=_CALENDAR_WINDOW_DAYS)
    result = await db.execute(
        select(CalendarItem)
        .where(CalendarItem.brand_id == brand_id)
        .where(CalendarItem.scheduled_at.is_not(None))
        .where(CalendarItem.scheduled_at >= func.now())
        .where(CalendarItem.scheduled_at <= cutoff)
        .order_by(CalendarItem.scheduled_at.asc())
        .limit(40)
    )
    items: list[dict[str, Any]] = []
    for ci in result.scalars().all():
        items.append({
            "title": ci.title,
            "theme": ci.theme,
            "weekly_sub_theme": ci.weekly_sub_theme,
            "content_brief": (ci.content_brief or "")[:300],
            "scheduled_at": ci.scheduled_at.isoformat() if ci.scheduled_at else None,
        })
    return items


async def _load_active_products(
    db: AsyncSession, brand_id: Any
) -> list[dict[str, Any]]:
    """Active products for the brand — the catalog the trend scorer picks the
    hero product from. Only included (is_active) products, same as planning."""
    from app.models.product import Product

    result = await db.execute(
        select(
            Product.id, Product.name, Product.sku, Product.category, Product.vendor_name
        )
        .where(Product.brand_id == brand_id)
        .where(Product.is_active.is_(True))
        .order_by(Product.name.asc())
    )
    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "sku": row[2],
            "category": row[3],
            "vendor": row[4],
        }
        for row in result.all()
    ]


def _build_brand_context(
    brand: Brand,
    docs: dict[str, str] | None = None,
    calendar: list[dict[str, Any]] | None = None,
) -> str:
    """Compact brand description + 4 strategy documents + upcoming calendar,
    fed to the LLM scorer. Sections are appended only if data exists, so a
    brand with empty reports still gets a meaningful prompt from the summary."""
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

    parts: list[str] = [f"BRAND: {brand.name}"]
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

    if docs:
        parts.append("\n--- BRAND STRATEGY DOCUMENTS ---")
        for doc_type in _BRAND_DOC_TYPES:
            blob = docs.get(doc_type)
            if blob:
                parts.append(f"\n[{doc_type.upper()}]\n{blob}")

    if calendar:
        parts.append(
            f"\n--- UPCOMING CALENDAR (next {_CALENDAR_WINDOW_DAYS} days, "
            f"{len(calendar)} items) ---"
        )
        for ci in calendar:
            bits: list[str] = []
            if ci.get("scheduled_at"):
                bits.append(ci["scheduled_at"][:10])
            bits.append(ci.get("title", "(no title)"))
            if ci.get("theme"):
                bits.append(f"theme={ci['theme']}")
            if ci.get("weekly_sub_theme"):
                bits.append(f"sub={ci['weekly_sub_theme']}")
            if ci.get("content_brief"):
                bits.append(f"brief={ci['content_brief']}")
            parts.append("- " + " | ".join(bits))

    return "\n".join(parts)


async def score_trends_for_brand(
    db: AsyncSession, brand: Brand, raw_trends: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """LLM-score every raw trend for a single brand, using the brand's
    four strategy documents + upcoming calendar as extra context.

    Returns kept trends augmented with `score`, `reason`, `angle`. Filters
    out:
    - LLM rejections (no entry in results, or below MIN_RELEVANCE_SCORE)
    - LLM hallucinations (topic not in raw_trends)
    - Trends already covered by an upcoming calendar item (already_planned)
    """
    if not raw_trends:
        return []

    docs = await _load_brand_documents(db, brand.id)
    calendar = await _load_upcoming_calendar(db, brand.id)
    brand_context = _build_brand_context(brand, docs=docs, calendar=calendar)

    # Real product catalog → the LLM picks the hero product from THIS list
    # (so trend angles link to an actual SKU). A rotating window keeps the
    # whole catalog in play over successive daily runs instead of always the
    # first products.
    try:
        products = await _load_active_products(db, brand.id)
    except Exception as exc:
        logger.warning("Product load failed for brand %s (continuing): %s", brand.name, exc)
        products = []
    prod_by_name = {p["name"].strip().lower(): p for p in products if p.get("name")}
    if products and len(products) > _TREND_PRODUCT_WINDOW:
        _n = len(products)
        _offset = (datetime.now(timezone.utc).toordinal() * _TREND_PRODUCT_WINDOW) % _n
        window = [products[(_offset + k) % _n] for k in range(_TREND_PRODUCT_WINDOW)]
    else:
        window = products
    products_block = ""
    if window:
        products_block = (
            "\n--- BRAND PRODUCTS (pick the hero from THIS list, exact name) ---\n"
            + "\n".join(
                f"- {p['name']}" + (f" [{p['category']}]" if p.get("category") else "")
                for p in window
            )
            + "\n"
        )

    topics_block = "\n".join(f"- {t['topic']}" for t in raw_trends)
    user_msg = (
        f"{brand_context}\n"
        f"{products_block}\n"
        f"TRENDS TO EVALUATE:\n{topics_block}\n\n"
        "Return JSON as specified. Skip trends you reject — only include "
        "trends with a real angle for this brand. Mark already_planned=true "
        "only when a calendar item clearly covers the trend."
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

    raw_by_topic = {str(t["topic"]).lower(): t for t in raw_trends}

    scored: list[dict[str, Any]] = []
    skipped_planned = 0
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
        if r.get("already_planned") is True:
            skipped_planned += 1
            continue
        raw = raw_by_topic.get(topic.lower())
        if not raw:
            continue
        # Link the hero product (chosen from the catalog window) to a real row.
        meta = dict(raw.get("metadata") or {})
        prod_name = str(r.get("product", "")).strip()
        if prod_name:
            matched = prod_by_name.get(prod_name.lower())
            if matched:
                meta["product_id"] = matched["id"]
                meta["product_name"] = matched["name"]
                if matched.get("sku"):
                    meta["product_sku"] = matched["sku"]
        scored.append({
            **raw,
            "topic": raw["topic"],
            "relevance_score": score,
            "relevance_reason": str(r.get("reason", ""))[:600],
            "llm_angle": str(r.get("angle", ""))[:1200],
            "metadata": meta,
        })

    if skipped_planned:
        logger.info(
            "Brand %s: skipped %d trends already in calendar",
            brand.name,
            skipped_planned,
        )

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

        # TrendingTopic.extra_data is the ORM attribute mapped to the SQL
        # column named `metadata`. pg_insert(ORMClass).values() resolves
        # kwargs via ORM attribute names (and `metadata` collides with
        # Base.metadata), so use `extra_data` here. stmt.excluded and the
        # set_ dict keys below operate at the table level, so they use the
        # actual SQL column name `metadata`.
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
            extra_data=t.get("metadata") or {},
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
                scored = await score_trends_for_brand(db, brand, raw_trends)
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
                # The session may be in a "needs rollback" state if the
                # exception came from a partial UPSERT. Roll back so the
                # next brand (and the cleanup below) can run on a clean
                # session instead of cascading the failure.
                try:
                    await db.rollback()
                except Exception:
                    pass

        # Cleanup expired rows globally (cheap, one DELETE)
        removed = await _cleanup_expired(db)
        logger.info(
            "Trends cycle complete: %d rows upserted, %d expired rows removed",
            total_upserted, removed,
        )
