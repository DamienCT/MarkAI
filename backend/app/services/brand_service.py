import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models.brand import Brand
from app.schemas.brand import BrandCreate, BrandUpdate

# JSONB columns that need flag_modified to persist changes
_JSONB_FIELDS = {"brand_guidelines", "target_audience", "color_palette", "bc_locations"}


async def list_brands(
    db: AsyncSession,
    *,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[Brand]:
    stmt = select(Brand).offset(skip).limit(limit)
    if is_active is not None:
        stmt = stmt.where(Brand.is_active == is_active)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_brand(db: AsyncSession, brand_id: uuid.UUID) -> Brand | None:
    result = await db.execute(select(Brand).where(Brand.id == brand_id))
    return result.scalar_one_or_none()


async def get_brand_by_slug(db: AsyncSession, slug: str) -> Brand | None:
    result = await db.execute(select(Brand).where(Brand.slug == slug))
    return result.scalar_one_or_none()


async def create_brand(db: AsyncSession, data: BrandCreate) -> Brand:
    brand = Brand(**data.model_dump())
    db.add(brand)
    await db.commit()
    await db.refresh(brand)
    return brand


async def update_brand(
    db: AsyncSession, brand_id: uuid.UUID, data: BrandUpdate
) -> Brand | None:
    brand = await get_brand(db, brand_id)
    if brand is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(brand, key, value)
        # Force SQLAlchemy to detect JSONB mutations
        if key in _JSONB_FIELDS:
            flag_modified(brand, key)
    await db.commit()
    await db.refresh(brand)
    return brand


async def delete_brand(db: AsyncSession, brand_id: uuid.UUID) -> bool:
    brand = await get_brand(db, brand_id)
    if brand is None:
        return False
    await db.delete(brand)
    await db.commit()
    return True
