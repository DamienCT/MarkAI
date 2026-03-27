import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate


async def list_products(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    is_new: bool | None = None,
    is_expiring: bool | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[Product]:
    stmt = select(Product).offset(skip).limit(limit).order_by(Product.name.asc())
    if brand_id is not None:
        stmt = stmt.where(Product.brand_id == brand_id)
    if is_new is not None:
        stmt = stmt.where(Product.is_new == is_new)
    if is_expiring is not None:
        stmt = stmt.where(Product.is_expiring_soon == is_expiring)
    if is_active is not None:
        stmt = stmt.where(Product.is_active == is_active)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> Product | None:
    result = await db.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one_or_none()


async def get_product_by_bc_item_no(
    db: AsyncSession, bc_item_no: str
) -> Product | None:
    result = await db.execute(
        select(Product).where(Product.bc_item_no == bc_item_no)
    )
    return result.scalar_one_or_none()


async def create_product(db: AsyncSession, data: ProductCreate) -> Product:
    product = Product(**data.model_dump())
    db.add(product)
    await db.commit()
    await db.refresh(product)
    return product


async def update_product(
    db: AsyncSession, product_id: uuid.UUID, data: ProductUpdate
) -> Product | None:
    product = await get_product(db, product_id)
    if product is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)
    await db.commit()
    await db.refresh(product)
    return product


async def upsert_from_bc(
    db: AsyncSession,
    bc_item_no: str,
    data: dict,
) -> Product:
    """
    Upsert a product from Business Central sync data.
    Creates if not existing, updates if it does.
    """
    product = await get_product_by_bc_item_no(db, bc_item_no)
    if product is None:
        product = Product(bc_item_no=bc_item_no, **data)
        db.add(product)
    else:
        for key, value in data.items():
            if hasattr(product, key):
                setattr(product, key, value)
    product.bc_last_synced_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(product)
    return product
