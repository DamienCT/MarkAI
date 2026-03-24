"""Real async SQLAlchemy database operations for brands, content, products, etc."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

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
    """Return a new async session."""
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
            text(
                "SELECT id, brand_guidelines FROM brands WHERE id = :id"
            ),
            {"id": brand_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


# ── Content operations ───────────────────────────────────────────────────

async def get_calendar_item(item_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM calendar_items WHERE id = :id"), {"id": item_id}
        )
        row = result.mappings().first()
        return dict(row) if row else None


async def store_content(content: dict[str, Any]) -> str:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO content_items "
                "(brand_id, calendar_item_id, hook, caption, hashtags, cta, "
                " product_image_url, generated_image_url, platform_adaptations, status) "
                "VALUES (:brand_id, :calendar_item_id, :hook, :caption, :hashtags, :cta, "
                " :product_image_url, :generated_image_url, :platform_adaptations::jsonb, :status) "
                "RETURNING id"
            ),
            content,
        )
        await session.commit()
        row = result.first()
        return str(row[0]) if row else ""


async def get_content_items(brand_id: str, limit: int = 50) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM content_items WHERE brand_id = :brand_id "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"brand_id": brand_id, "limit": limit},
        )
        return [dict(r) for r in result.mappings().all()]


# ── Product operations ───────────────────────────────────────────────────

async def get_products(brand_id: str) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT * FROM products WHERE brand_id = :brand_id"),
            {"brand_id": brand_id},
        )
        return [dict(r) for r in result.mappings().all()]


async def upsert_product(product: dict[str, Any]) -> str:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO products (id, brand_id, name, sku, vendor, image_url, metadata) "
                "VALUES (:id, :brand_id, :name, :sku, :vendor, :image_url, :metadata::jsonb) "
                "ON CONFLICT (id) DO UPDATE SET "
                "  name = EXCLUDED.name, sku = EXCLUDED.sku, vendor = EXCLUDED.vendor, "
                "  image_url = EXCLUDED.image_url, metadata = EXCLUDED.metadata, "
                "  updated_at = NOW() "
                "RETURNING id"
            ),
            product,
        )
        await session.commit()
        row = result.first()
        return str(row[0]) if row else ""


# ── Strategy / Research operations ───────────────────────────────────────

async def store_research(brand_id: str, research_data: dict[str, Any]) -> str:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO research_results (brand_id, data) "
                "VALUES (:brand_id, :data::jsonb) RETURNING id"
            ),
            {"brand_id": brand_id, "data": str(research_data)},
        )
        await session.commit()
        row = result.first()
        return str(row[0]) if row else ""


async def get_latest_research(brand_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM research_results WHERE brand_id = :brand_id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"brand_id": brand_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


async def store_strategy(brand_id: str, strategy_data: dict[str, Any]) -> str:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "INSERT INTO strategies (brand_id, data) "
                "VALUES (:brand_id, :data::jsonb) RETURNING id"
            ),
            {"brand_id": brand_id, "data": str(strategy_data)},
        )
        await session.commit()
        row = result.first()
        return str(row[0]) if row else ""


async def get_latest_strategy(brand_id: str) -> dict[str, Any] | None:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM strategies WHERE brand_id = :brand_id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"brand_id": brand_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None


# ── Calendar operations ──────────────────────────────────────────────────

async def store_calendar_items(items: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    async with async_session_factory() as session:
        for item in items:
            result = await session.execute(
                text(
                    "INSERT INTO calendar_items "
                    "(brand_id, campaign_id, scheduled_date, platform, content_type, "
                    " product_id, theme, status) "
                    "VALUES (:brand_id, :campaign_id, :scheduled_date, :platform, "
                    " :content_type, :product_id, :theme, :status) "
                    "RETURNING id"
                ),
                item,
            )
            row = result.first()
            if row:
                ids.append(str(row[0]))
        await session.commit()
    return ids


# ── Performance / Evaluation operations ──────────────────────────────────

async def get_performance_data(
    brand_id: str, days: int = 30
) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM content_performance "
                "WHERE brand_id = :brand_id "
                "  AND measured_at >= NOW() - make_interval(days => :days) "
                "ORDER BY measured_at DESC"
            ),
            {"brand_id": brand_id, "days": days},
        )
        return [dict(r) for r in result.mappings().all()]


async def store_adaptations(adaptations: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    async with async_session_factory() as session:
        for a in adaptations:
            result = await session.execute(
                text(
                    "INSERT INTO adaptations "
                    "(brand_id, tier, description, confidence, data, status) "
                    "VALUES (:brand_id, :tier, :description, :confidence, :data::jsonb, :status) "
                    "RETURNING id"
                ),
                a,
            )
            row = result.first()
            if row:
                ids.append(str(row[0]))
        await session.commit()
    return ids


async def get_pending_adaptations(brand_id: str) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM adaptations "
                "WHERE brand_id = :brand_id AND status = 'pending' "
                "ORDER BY tier, created_at"
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

async def execute_query(
    query: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(text(query), params or {})
        return [dict(r) for r in result.mappings().all()]
