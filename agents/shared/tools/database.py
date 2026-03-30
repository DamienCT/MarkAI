"""Real async SQLAlchemy database operations using the actual MARKAI schema."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from shared.config import settings

logger = logging.getLogger(__name__)

_engine = create_async_engine(
    settings.postgres_dsn,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)
async_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    return async_session_factory()


# ── Brand operations ─────────────────────────────────────────────────────

async def get_brand(brand_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM brands WHERE id = :id"), {"id": brand_id}
        )
        row = result.mappings().first()
        return dict(row) if row else None


async def get_brand_config(brand_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT id, brand_guidelines, tone_of_voice, target_audience, website_url FROM brands WHERE id = :id"),
            {"id": brand_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


# ── Agent Run operations (store all workflow results here) ────────────────

async def create_agent_run(
    brand_id: str,
    agent_type: str,
    trigger: str = "manual",  # valid: manual, scheduled, event, webhook
    input_payload: dict | None = None,
) -> str:
    """Create a new agent_run record and return its ID."""
    run_id = str(uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO agent_runs (id, brand_id, agent_type, trigger, status, input_payload, started_at) "
                "VALUES (:id, :brand_id, :agent_type, :trigger, 'running', :input_payload, :started_at)"
            ),
            {
                "id": run_id,
                "brand_id": brand_id,
                "agent_type": agent_type,
                "trigger": trigger,
                "input_payload": json.dumps(input_payload or {}, default=str),
                "started_at": datetime.now(timezone.utc),
            },
        )
        await session.commit()
    return run_id


async def complete_agent_run(
    run_id: str,
    output_payload: dict | None = None,
    status: str = "completed",
    error_message: str | None = None,
    tokens_used: int | None = None,
) -> None:
    """Mark an agent_run as completed or failed."""
    async with async_session_factory() as session:
        await session.execute(
            text(
                "UPDATE agent_runs SET status = :status, output_payload = :output, "
                "error_message = :error, completed_at = :completed_at, "
                "tokens_used = COALESCE(:tokens_used, tokens_used) "
                "WHERE id = :id"
            ),
            {
                "id": run_id,
                "status": status,
                "output": json.dumps(output_payload or {}, default=str),
                "error": error_message,
                "completed_at": datetime.now(timezone.utc),
                "tokens_used": tokens_used,
            },
        )
        await session.commit()


# ── Research operations (stored in agent_runs) ────────────────────────────

async def store_research(brand_id: str, research_data: dict[str, Any]) -> str:
    """Store research results as a completed agent_run with output_payload."""
    run_id = str(uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO agent_runs (id, brand_id, agent_type, trigger, status, output_payload, started_at, completed_at) "
                "VALUES (:id, :brand_id, 'research', 'manual', 'completed', :output_payload, :now, :now)"
            ),
            {
                "id": run_id,
                "brand_id": brand_id,
                "output_payload": json.dumps(research_data, default=str),
                "now": datetime.now(timezone.utc),
            },
        )
        await session.commit()
    return run_id


async def get_latest_research(brand_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM agent_runs WHERE brand_id = :brand_id "
                "AND agent_type = 'research' AND status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            ),
            {"brand_id": brand_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


# ── Strategy operations (stored in agent_runs) ────────────────────────────

async def store_strategy(brand_id: str, strategy_data: dict[str, Any], agent_type: str = "strategy") -> str:
    """Store strategy results as a completed agent_run with output_payload."""
    run_id = str(uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO agent_runs (id, brand_id, agent_type, trigger, status, output_payload, started_at, completed_at) "
                "VALUES (:id, :brand_id, :agent_type, 'manual', 'completed', :output_payload, :now, :now)"
            ),
            {
                "id": run_id,
                "brand_id": brand_id,
                "agent_type": agent_type,
                "output_payload": json.dumps(strategy_data, default=str),
                "now": datetime.now(timezone.utc),
            },
        )
        await session.commit()
    return run_id


async def get_latest_strategy(brand_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM agent_runs WHERE brand_id = :brand_id "
                "AND agent_type = 'strategy' AND status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            ),
            {"brand_id": brand_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


# ── Competitor operations ─────────────────────────────────────────────────

async def store_competitors(brand_id: str, competitors: list[dict[str, Any]]) -> int:
    """Upsert discovered competitors for a brand. Returns count inserted."""
    count = 0
    async with async_session_factory() as session:
        for comp in competitors:
            name = comp.get("name", "").strip()
            if not name:
                continue
            # Check if exists
            existing = await session.execute(
                text("SELECT id FROM competitors WHERE brand_id = :brand_id AND LOWER(name) = LOWER(:name)"),
                {"brand_id": brand_id, "name": name},
            )
            if existing.first():
                continue
            await session.execute(
                text(
                    "INSERT INTO competitors (brand_id, name, website_url, social_handles, description, is_active) "
                    "VALUES (:brand_id, :name, :website_url, :social_handles, :description, true)"
                ),
                {
                    "brand_id": brand_id,
                    "name": name,
                    "website_url": comp.get("website_url", ""),
                    "social_handles": json.dumps(comp.get("social_handles", {})),
                    "description": comp.get("description", ""),
                },
            )
            count += 1
        await session.commit()
    return count


# ── Content operations ────────────────────────────────────────────────────

async def get_calendar_item(item_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM calendar_items WHERE id = :id"), {"id": item_id}
        )
        row = result.mappings().first()
        return dict(row) if row else None


async def store_content(content_data: dict[str, Any]) -> str:
    """Store generated content in the content table. Marks previous versions as not current."""
    content_id = str(uuid4())
    async with async_session_factory() as session:
        # Mark any existing content for this calendar item as not current
        cal_item_id = content_data.get("calendar_item_id")
        if cal_item_id:
            await session.execute(
                text("UPDATE content SET is_current = false WHERE calendar_item_id = :cid AND is_current = true"),
                {"cid": cal_item_id},
            )
        # Parse hashtags: may be a JSON string or a list
        raw_hashtags = content_data.get("hashtags", [])
        if isinstance(raw_hashtags, str):
            try:
                raw_hashtags = json.loads(raw_hashtags)
            except (json.JSONDecodeError, TypeError):
                raw_hashtags = [h.strip() for h in raw_hashtags.split(",") if h.strip()]
        if not isinstance(raw_hashtags, list):
            raw_hashtags = []

        # Build generation_metadata with all the extra content info
        gen_metadata = content_data.get("metadata", {})
        if content_data.get("platform_adaptations"):
            gen_metadata["platform_adaptations"] = (
                json.loads(content_data["platform_adaptations"])
                if isinstance(content_data["platform_adaptations"], str)
                else content_data["platform_adaptations"]
            )
        if content_data.get("product_image_url"):
            gen_metadata["product_image_url"] = content_data["product_image_url"]
        if content_data.get("generated_image_url"):
            gen_metadata["generated_image_url"] = content_data["generated_image_url"]
        if content_data.get("hook"):
            gen_metadata["hook"] = content_data["hook"]

        await session.execute(
            text(
                "INSERT INTO content (id, brand_id, calendar_item_id, headline, caption, "
                "hashtags, cta_text, generation_metadata, ai_generated, is_current) "
                "VALUES (:id, :brand_id, :calendar_item_id, :headline, :caption, "
                ":hashtags, :cta_text, :metadata, true, true)"
            ),
            {
                "id": content_id,
                "brand_id": content_data.get("brand_id"),
                "calendar_item_id": cal_item_id,
                "headline": (content_data.get("headline") or content_data.get("hook", ""))[:500],
                "caption": content_data.get("caption") or content_data.get("body_text", ""),
                "hashtags": raw_hashtags,
                "cta_text": (content_data.get("cta") or content_data.get("cta_text", ""))[:255],
                "metadata": json.dumps(gen_metadata, default=str),
            },
        )
        await session.commit()
    return content_id


async def get_content_items(brand_id: str, limit: int = 50) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM content WHERE brand_id = :brand_id "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"brand_id": brand_id, "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]


# ── Product operations ────────────────────────────────────────────────────

async def get_products(brand_id: str) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM products WHERE brand_id = :brand_id AND is_active = true"),
            {"brand_id": brand_id},
        )
        return [dict(r) for r in result.mappings().all()]


async def upsert_product(product: dict[str, Any]) -> str:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO products (brand_id, bc_item_no, name, description, category, "
                "vendor_no, unit_price, bc_company, bc_location, remaining_qty, is_active) "
                "VALUES (:brand_id, :bc_item_no, :name, :description, :category, "
                ":vendor_no, :unit_price, :bc_company, :bc_location, :remaining_qty, true) "
                "ON CONFLICT (brand_id, bc_item_no) DO UPDATE SET "
                "name = EXCLUDED.name, description = EXCLUDED.description, "
                "remaining_qty = EXCLUDED.remaining_qty, updated_at = NOW() "
                "RETURNING id"
            ),
            product,
        )
        await session.commit()
        row = result.first()
        return str(row[0]) if row else ""


# ── Calendar operations ──────────────────────────────────────────────────

async def store_calendar_items(
    items: list[dict[str, Any]],
    max_date: datetime | None = None,
    enabled_channels: list[str] | None = None,
) -> list[str]:
    ids: list[str] = []
    async with async_session_factory() as session:
        for item in items:
            # Validate channel early so we can filter before doing more work
            VALID_CHANNELS = {"instagram", "facebook", "linkedin", "youtube", "tiktok", "x", "website_blog", "teams"}
            raw_channel = (item.get("channel") or "instagram").lower().strip()
            channel_map = {"twitter": "x", "blog": "website_blog", "web": "website_blog"}
            channel = channel_map.get(raw_channel, raw_channel)
            if channel not in VALID_CHANNELS:
                channel = "instagram"

            # Skip items for channels that are not enabled
            if enabled_channels and channel not in enabled_channels:
                logger.info("Skipping calendar item for disabled channel: %s", channel)
                continue

            item_id = str(uuid4())
            # Parse scheduled_at — LLM may return a string like "2026-04-01"
            scheduled_at_raw = item.get("scheduled_at")
            if isinstance(scheduled_at_raw, str) and scheduled_at_raw:
                try:
                    scheduled_at_val = datetime.fromisoformat(scheduled_at_raw)
                except ValueError:
                    # Handle date-only strings like "2026-04-01" on older Pythons
                    try:
                        from datetime import date as _date
                        d = _date.fromisoformat(scheduled_at_raw[:10])
                        scheduled_at_val = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
                    except Exception:
                        scheduled_at_val = datetime.now(timezone.utc)
            elif isinstance(scheduled_at_raw, datetime):
                scheduled_at_val = scheduled_at_raw
            else:
                scheduled_at_val = datetime.now(timezone.utc)

            # Hard enforcement: skip items scheduled beyond the max_date boundary
            if max_date is not None:
                # Ensure both are comparable (tz-aware)
                max_dt = max_date if max_date.tzinfo else max_date.replace(tzinfo=timezone.utc)
                sched_dt = scheduled_at_val if scheduled_at_val.tzinfo else scheduled_at_val.replace(tzinfo=timezone.utc)
                if sched_dt > max_dt:
                    logger.info("Skipping calendar item '%s' — scheduled_at %s exceeds max_date %s",
                                item.get("title", ""), scheduled_at_val.isoformat(), max_date.isoformat())
                    continue

            # Validate and map item_type (content_type from LLM)
            VALID_ITEM_TYPES = {"post", "story", "reel", "carousel", "article", "newsletter", "ad", "event", "other"}
            raw_type = (item.get("content_type") or item.get("item_type") or "post").lower().strip()
            item_type = raw_type if raw_type in VALID_ITEM_TYPES else "post"

            await session.execute(
                text(
                    "INSERT INTO calendar_items (id, brand_id, campaign_id, title, description, "
                    "item_type, channel, scheduled_at, status, product_ids, "
                    "pillar, theme, target_audience, weekly_sub_theme, content_brief, visual_direction, cta_type) "
                    "VALUES (:id, :brand_id, :campaign_id, :title, :description, "
                    ":item_type, :channel, :scheduled_at, 'queued', :product_ids, "
                    ":pillar, :theme, :target_audience, :weekly_sub_theme, :content_brief, :visual_direction, :cta_type)"
                ),
                {
                    "id": item_id,
                    "brand_id": item.get("brand_id"),
                    "campaign_id": item.get("campaign_id"),
                    "title": item.get("title", "")[:500],
                    "description": item.get("description", ""),
                    "item_type": item_type,
                    "channel": channel,
                    "scheduled_at": scheduled_at_val,
                    "product_ids": [item["product_id"]] if item.get("product_id") else None,
                    "pillar": item.get("pillar"),
                    "theme": item.get("theme"),
                    "target_audience": item.get("target_audience"),
                    "weekly_sub_theme": item.get("weekly_sub_theme"),
                    "content_brief": item.get("content_brief"),
                    "visual_direction": item.get("visual_direction"),
                    "cta_type": item.get("cta_type"),
                },
            )
            ids.append((item_id, scheduled_at_val))
        await session.commit()
    # Sort by scheduled_at ASC and return only IDs (ensure tz-aware for comparison)
    def _tz_aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    ids.sort(key=lambda x: _tz_aware(x[1]))
    return [item_id for item_id, _ in ids]


# ── Performance / Evaluation operations ──────────────────────────────────

async def get_performance_data(brand_id: str, days: int = 30) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT em.*, ci.channel, ci.title FROM engagement_metrics em "
                "JOIN calendar_items ci ON em.calendar_item_id = ci.id "
                "WHERE em.brand_id = :brand_id "
                "AND em.fetched_at >= NOW() - make_interval(days => :days) "
                "ORDER BY em.fetched_at DESC"
            ),
            {"brand_id": brand_id, "days": days},
        )
        return [dict(r) for r in result.mappings().all()]


async def store_adaptations(adaptations: list[dict[str, Any]]) -> list[str]:
    """Store adaptations from the evaluation workflow.

    Accepts records with either the evaluation-node schema
    (brand_id, tier, description, confidence, data, status) or the
    legacy content-adaptation schema (source_content_id, target_channel, ...).
    """
    ids: list[str] = []
    async with async_session_factory() as session:
        for a in adaptations:
            adapt_id = str(uuid4())

            # Detect which schema the caller is using
            if "brand_id" in a and "tier" in a:
                # Evaluation-node schema — store tier/confidence/data in adaptation_notes as JSON
                eval_meta = json.dumps({
                    "tier": a.get("tier", 2),
                    "confidence": a.get("confidence", 0.5),
                    "data": a.get("data", {}),
                }, default=str)
                await session.execute(
                    text(
                        "INSERT INTO adaptations (id, source_content_id, target_channel, "
                        "adapted_text, adaptation_notes, status) "
                        "VALUES (:id, :source_content_id, :target_channel, "
                        ":adapted_text, :notes, :status)"
                    ),
                    {
                        "id": adapt_id,
                        "source_content_id": a.get("source_content_id"),
                        "target_channel": a.get("target_channel", "instagram"),
                        "adapted_text": a.get("description", ""),
                        "notes": eval_meta,
                        "status": a.get("status", "queued"),
                    },
                )
            else:
                # Legacy content-adaptation schema
                await session.execute(
                    text(
                        "INSERT INTO adaptations (id, source_content_id, target_channel, "
                        "adapted_text, adapted_headline, adaptation_notes, status) "
                        "VALUES (:id, :source_content_id, :target_channel, "
                        ":adapted_text, :adapted_headline, :notes, 'proposed')"
                    ),
                    {
                        "id": adapt_id,
                        "source_content_id": a.get("source_content_id"),
                        "target_channel": a.get("target_channel", "instagram"),
                        "adapted_text": a.get("adapted_text", ""),
                        "adapted_headline": a.get("adapted_headline", ""),
                        "notes": a.get("notes", ""),
                    },
                )
            ids.append(adapt_id)
        await session.commit()
    return ids


async def get_pending_adaptations(brand_id: str) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT a.* FROM adaptations a "
                "JOIN content c ON a.source_content_id = c.id "
                "WHERE c.brand_id = :brand_id "
                "AND a.status IN ('proposed', 'auto_applied', 'queued') "
                "ORDER BY a.created_at"
            ),
            {"brand_id": brand_id},
        )
        return [dict(r) for r in result.mappings().all()]


async def update_adaptation_status(adaptation_id: str, status: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE adaptations SET status = :status WHERE id = :id"),
            {"id": adaptation_id, "status": status},
        )
        await session.commit()


# ── Generic query helper ─────────────────────────────────────────────────

async def execute_query(query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(text(query), params or {})
        return [dict(r) for r in result.mappings().all()]


async def execute_update(query: str, params: dict[str, Any] | None = None) -> int:
    """Execute a non-SELECT statement (UPDATE, INSERT, DELETE) and commit.

    Returns the number of rows affected.
    """
    async with async_session_factory() as session:
        result = await session.execute(text(query), params or {})
        await session.commit()
        return result.rowcount


# ── Recent calendar items helper ─────────────────────────────────────────

async def get_recent_calendar_items(brand_id: str, days: int = 90, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent calendar items for a brand within the last N days."""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, title, theme, pillar, target_audience, channel, scheduled_at, status "
                "FROM calendar_items WHERE brand_id = :brand_id "
                "AND scheduled_at > NOW() - make_interval(days => :days) "
                "ORDER BY scheduled_at DESC LIMIT :limit"
            ),
            {"brand_id": brand_id, "days": days, "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]


# ── Brand Intelligence ───────────────────────────────────────────────────

def _parse_payload(raw: Any) -> dict[str, Any]:
    """Parse an output_payload that may be a JSON string or already a dict."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


async def build_brand_intelligence(brand_id: str) -> dict[str, Any]:
    """Build consolidated context package for all AI workflows.

    Loads brand config, products, latest research/strategy/planning outputs,
    recent calendar items, and top-performing content into a single dict.
    """
    # 1. Brand config
    brand = await get_brand(brand_id)
    if not brand:
        return {}

    brand_guidelines = brand.get("brand_guidelines", {})
    if isinstance(brand_guidelines, str):
        try:
            brand_guidelines = json.loads(brand_guidelines)
        except (json.JSONDecodeError, TypeError):
            brand_guidelines = {}

    # Derive enabled channels from brand_guidelines
    channels_cfg = brand_guidelines.get("channels", {})
    enabled_channels = [
        ch for ch, cfg in channels_cfg.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    if not enabled_channels:
        enabled_channels = ["instagram"]

    brand_info = {
        "name": brand.get("name", ""),
        "description": brand.get("description", ""),
        "website_url": brand.get("website_url", ""),
        "industry": brand.get("industry", ""),
        "tone_of_voice": brand.get("tone_of_voice", ""),
        "brand_guidelines": brand_guidelines,
        "enabled_channels": enabled_channels,
    }

    # 2. Active products
    products = await get_products(brand_id)

    # 3. Latest completed research
    research_run = await get_latest_research(brand_id)
    research_data = _parse_payload((research_run or {}).get("output_payload"))

    # 4. Latest completed strategy
    strategy_run = await get_latest_strategy(brand_id)
    strategy_data = _parse_payload((strategy_run or {}).get("output_payload"))

    # 5. Latest completed planning
    async with async_session_factory() as session:
        planning_result = await session.execute(
            text(
                "SELECT output_payload FROM agent_runs WHERE brand_id = :brand_id "
                "AND agent_type = 'planning' AND status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            ),
            {"brand_id": brand_id},
        )
        planning_row = planning_result.mappings().first()
    planning_data = _parse_payload((planning_row or {}).get("output_payload") if planning_row else None)

    # 6. Latest content_calendar_strategy
    async with async_session_factory() as session:
        strategy_doc_result = await session.execute(
            text(
                "SELECT output_payload FROM agent_runs WHERE brand_id = :brand_id "
                "AND agent_type IN ('content_calendar', 'content_calendar_strategy') AND status = 'completed' "
                "ORDER BY completed_at DESC LIMIT 1"
            ),
            {"brand_id": brand_id},
        )
        strategy_doc_row = strategy_doc_result.mappings().first()
    strategy_doc_data = _parse_payload((strategy_doc_row or {}).get("output_payload") if strategy_doc_row else None)

    # 7. Recent calendar items (last 90 days)
    recent_posts = await get_recent_calendar_items(brand_id, days=90, limit=50)

    # 8. Top performing content (last 90 days)
    async with async_session_factory() as session:
        top_result = await session.execute(
            text(
                "SELECT ci.title, ci.channel, em.engagement_rate, em.likes, em.comments, "
                "LEFT(c.caption, 200) AS caption_snippet "
                "FROM calendar_items ci "
                "JOIN engagement_metrics em ON em.calendar_item_id = ci.id "
                "LEFT JOIN content c ON c.calendar_item_id = ci.id AND c.is_current = true "
                "WHERE ci.brand_id = :brand_id "
                "AND ci.scheduled_at > NOW() - INTERVAL '90 days' "
                "ORDER BY em.engagement_rate DESC LIMIT 10"
            ),
            {"brand_id": brand_id},
        )
        top_performing = [dict(r) for r in top_result.mappings().all()]

    return {
        "brand": {**brand_info, "products": products},
        "research": research_data,
        "strategy": strategy_data,
        "planning": {
            "strategy_document": strategy_doc_data.get("document", ""),
            "campaigns": planning_data.get("campaigns", []),
        },
        "recent_posts": recent_posts,
        "top_performing": top_performing,
    }
