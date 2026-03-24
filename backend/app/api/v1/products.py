import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.services import fabric_service, minio_service, product_service
from app.services.brand_service import get_brand
from app.services.product_service import upsert_from_bc

router = APIRouter()


@router.post("/sync/{brand_id}", status_code=status.HTTP_202_ACCEPTED)
async def sync_brand_products(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sync products for a specific brand using its BC company + locations."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    if not brand.bc_company:
        raise HTTPException(
            status_code=400,
            detail="Brand is not linked to a BC company",
        )

    locations = brand.bc_locations or []
    if not locations:
        raise HTTPException(
            status_code=400,
            detail="Brand has no BC stock locations configured",
        )

    stock_rows = await fabric_service.get_active_stock(brand.bc_company, locations)

    synced = 0
    for row in stock_rows:
        item_no = row.get("itemNo")
        if not item_no:
            continue

        product_data = {
            "brand_id": brand.id,
            "name": row.get("description", ""),
            "description": row.get("description2", ""),
            "category": row.get("itemCategoryCode", ""),
            "vendor_no": row.get("vendorNo", ""),
            "unit_price": row.get("unitPrice"),
            "bc_company": brand.bc_company,
            "bc_location": row.get("locationCode", ""),
            "remaining_qty": row.get("totalRemaining"),
            "is_active": True,
            "attributes": {
                "unitCost": row.get("unitCost"),
                "baseUnitOfMeasure": row.get("baseUnitOfMeasure"),
                "type": row.get("type"),
                "description2": row.get("description2", ""),
            },
        }

        await upsert_from_bc(db, item_no, product_data)
        synced += 1

    return {"message": f"Synced {synced} products for brand {brand.name}"}


@router.get("/", response_model=list[ProductResponse])
async def list_products(
    brand_id: uuid.UUID | None = None,
    is_new: bool | None = None,
    is_expiring: bool | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await product_service.list_products(
        db,
        brand_id=brand_id,
        is_new=is_new,
        is_expiring=is_expiring,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await product_service.create_product(db, data)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: uuid.UUID,
    data: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    product = await product_service.update_product(db, product_id, data)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/{product_id}/upload-image", response_model=ProductResponse)
async def upload_product_image(
    product_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a manual product image to MinIO and link it to the product."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    file_data = await file.read()
    object_name = f"products/{product_id}/{file.filename}"
    content_type = file.content_type or "image/jpeg"

    minio_service.upload_file(object_name, file_data, content_type)
    presigned_url = minio_service.get_presigned_url(object_name)

    product_update = ProductUpdate(
        primary_image_url=presigned_url,
    )
    return await product_service.update_product(db, product_id, product_update)


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def trigger_bc_sync(
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a Business Central product sync."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    from app.scheduler.bc_sync import sync_bc_products

    # Run asynchronously — fire and forget via the scheduler
    from app.scheduler import scheduler

    scheduler.add_job(
        sync_bc_products,
        id="bc_sync_manual",
        name="Manual BC sync",
        replace_existing=True,
    )
    return {"message": "BC sync triggered"}
