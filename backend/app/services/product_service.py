import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate

logger = logging.getLogger(__name__)


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
    db: AsyncSession, bc_item_no: str, brand_id: uuid.UUID
) -> Product | None:
    """Look up a product by its BC item number, scoped to one brand.

    BC item numbers are only unique within a BC company, so the lookup MUST
    filter on brand_id — without it, two brands whose companies share item
    numbers steal each other's rows on every sync.

    Defensive against pre-existing duplicates: fetches up to two rows and
    returns the first with a warning instead of raising MultipleResultsFound.
    TODO(schema workstream): (brand_id, bc_item_no) uniqueness is declared in
    db/init.sql (partial unique index idx_products_brand_bc_item); deployed
    databases created before that index must have it applied via migration —
    until then this SELECT-then-insert path is not race-safe under
    concurrent syncs.
    """
    result = await db.execute(
        select(Product)
        .where(Product.brand_id == brand_id, Product.bc_item_no == bc_item_no)
        .limit(2)
    )
    products = result.scalars().all()
    if len(products) > 1:
        logger.warning(
            "Duplicate products for brand %s with bc_item_no %s — returning the "
            "first; deduplicate so the (brand_id, bc_item_no) unique index can apply",
            brand_id,
            bc_item_no,
        )
    return products[0] if products else None


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


# Fields controlled by the user in the UI. BC sync must NOT overwrite these
# on update, or manual "Include" toggles would flip back to "Exclude" on every
# re-sync. They are still honored on initial create (as defaults).
_USER_CONTROLLED_FIELDS = frozenset({"is_active"})


async def upsert_from_bc(
    db: AsyncSession,
    bc_item_no: str,
    data: dict,
    *,
    brand_id: uuid.UUID,
    _batch_mode: bool = False,
) -> Product:
    """
    Upsert a product from Business Central sync data.
    Creates if not existing, updates if it does.

    Lookup and write are scoped to *brand_id* — the upsert targets
    (brand_id, bc_item_no) uniqueness so one brand's sync can never adopt or
    re-parent another brand's product row (see get_product_by_bc_item_no).

    User-controlled fields (see ``_USER_CONTROLLED_FIELDS``) are preserved on
    update — sync only sets them on initial creation. Manual overrides via the
    UI survive re-syncs.

    When ``_batch_mode`` is True, the caller is responsible for committing.
    """
    product = await get_product_by_bc_item_no(db, bc_item_no, brand_id)
    if product is None:
        product = Product(bc_item_no=bc_item_no, **{**data, "brand_id": brand_id})
        db.add(product)
    else:
        for key, value in data.items():
            # Never re-parent an existing row to another brand on update.
            if key in _USER_CONTROLLED_FIELDS or key == "brand_id":
                continue
            if hasattr(product, key):
                setattr(product, key, value)
    product.bc_last_synced_at = datetime.now(timezone.utc)
    if not _batch_mode:
        await db.commit()
        await db.refresh(product)
    return product


async def prune_brand_products_not_in(
    db: AsyncSession,
    brand_id: uuid.UUID,
    keep_bc_item_nos: set[str],
) -> int:
    """Delete products for a brand whose bc_item_no is not in *keep_bc_item_nos*.

    Used after a filtered BC sync so the table reflects only the selected
    vendors/categories — without this, previous unfiltered syncs leave
    orphaned products behind. Returns the number of rows deleted.
    """
    stmt = delete(Product).where(Product.brand_id == brand_id)
    if keep_bc_item_nos:
        stmt = stmt.where(Product.bc_item_no.notin_(keep_bc_item_nos))
    # Also restrict deletion to BC-sourced products (have a bc_item_no)
    stmt = stmt.where(Product.bc_item_no.is_not(None))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount or 0


async def batch_upsert_from_bc(
    db: AsyncSession,
    items: list[tuple[str, dict]],
    *,
    brand_id: uuid.UUID,
    batch_size: int = 50,
) -> list[Product]:
    """Upsert multiple products from Business Central, committing every *batch_size* items."""
    products: list[Product] = []
    for i, (bc_item_no, data) in enumerate(items, 1):
        product = await upsert_from_bc(
            db, bc_item_no, data, brand_id=brand_id, _batch_mode=True
        )
        products.append(product)
        if i % batch_size == 0:
            await db.commit()
    # Final commit for remaining items
    await db.commit()
    return products
