import asyncio
import logging
from datetime import datetime

from sqlalchemy import select

from app.models.base import async_session_factory
from app.models.brand import Brand
from app.services import fabric_service
from app.services.notification_service import notify_failure
from app.services.product_service import upsert_from_bc

logger = logging.getLogger(__name__)

_sync_lock = asyncio.Lock()


async def sync_bc_products() -> None:
    """
    Sync products from Business Central via Fabric Lakehouse.
    For each BC-linked brand, pull items filtered by company + locations,
    then upsert into the products table.
    """
    if _sync_lock.locked():
        logger.info("BC sync already in progress, skipping")
        return

    async with _sync_lock:
        await _sync_bc_products_impl()


async def _sync_bc_products_impl() -> None:
    logger.info("Starting Business Central product sync")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Brand).where(Brand.is_bc_linked == True)  # noqa: E712
        )
        brands = result.scalars().all()

        if not brands:
            logger.info("No BC-linked brands found, skipping sync")
            return

        for brand in brands:
            if not brand.bc_company:
                logger.info(
                    "Brand %s has no BC company set, skipping", brand.name
                )
                continue

            locations = brand.bc_locations or []
            if not locations:
                logger.info(
                    "Brand %s has no BC locations set, skipping", brand.name
                )
                continue

            # ── Fetch active stock (company + locations, blocked=0, qty>0) ──
            try:
                stock_items = await fabric_service.get_active_stock(
                    brand.bc_company, locations
                )
            except Exception as e:
                logger.error(
                    "Failed to fetch active stock for brand %s: %s",
                    brand.name, e,
                )
                await notify_failure("bc_sync", brand.id, e)
                continue

            logger.info(
                "Syncing %d stock items for brand %s",
                len(stock_items), brand.name,
            )

            # ── Fetch expiring items to flag products ──
            expiring_item_nos: set[str] = set()
            try:
                expiring = await fabric_service.get_expiring_items(
                    brand.bc_company, locations
                )
                expiring_item_nos = {
                    r.get("itemNo", "") for r in expiring if r.get("itemNo")
                }
            except Exception as e:
                logger.warning(
                    "Failed to fetch expiring items for brand %s: %s",
                    brand.name, e,
                )

            # ── Fetch new items to flag products ──
            new_item_nos: set[str] = set()
            try:
                new_items = await fabric_service.get_new_items(brand.bc_company)
                new_item_nos = {
                    r.get("no", "") for r in new_items if r.get("no")
                }
            except Exception as e:
                logger.warning(
                    "Failed to fetch new items for brand %s: %s",
                    brand.name, e,
                )

            # ── Build expiry date map from expiring items ──
            expiry_date_map: dict[str, str] = {}
            lot_no_map: dict[str, str] = {}
            for exp_row in expiring if expiring_item_nos else []:
                ino = exp_row.get("itemNo", "")
                if ino:
                    expiry_date_map.setdefault(ino, exp_row.get("expirationDate"))
                    lot_no_map.setdefault(ino, exp_row.get("lotNo", ""))

            # ── Upsert each stock item ──
            for item in stock_items:
                item_no = item.get("itemNo")
                if not item_no:
                    continue

                product_data = {
                    "brand_id": brand.id,
                    "name": item.get("description", ""),
                    "description": item.get("description2", ""),
                    "category": item.get("itemCategoryCode", ""),
                    "vendor_no": item.get("vendorNo", ""),
                    "unit_price": item.get("unitPrice"),
                    "bc_company": brand.bc_company,
                    "bc_location": item.get("locationCode", ""),
                    "remaining_qty": item.get("totalRemaining"),
                    "lot_no": lot_no_map.get(item_no, ""),
                    "is_active": False,
                    "is_new": item_no in new_item_nos,
                    "is_expiring_soon": item_no in expiring_item_nos,
                    "expiry_date": expiry_date_map.get(item_no),
                    "attributes": {
                        "unitCost": item.get("unitCost"),
                        "baseUnitOfMeasure": item.get("baseUnitOfMeasure"),
                        "type": item.get("type"),
                        "description2": item.get("description2", ""),
                    },
                }

                try:
                    await upsert_from_bc(db, item_no, product_data)
                except Exception as e:
                    logger.warning(
                        "Failed to upsert product %s: %s", item_no, e
                    )

        logger.info("Business Central product sync completed")
