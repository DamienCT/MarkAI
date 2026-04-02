import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate
from app.services import fabric_service, minio_service, product_service
from app.services.brand_service import get_brand
from app.services.product_service import upsert_from_bc
from slowapi import Limiter
from slowapi.util import get_remote_address

_limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)

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
            "is_active": False,
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


@router.get("/")
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
    limit = min(limit, 200)
    products = await product_service.list_products(
        db,
        brand_id=brand_id,
        is_new=is_new,
        is_expiring=is_expiring,
        is_active=is_active,
        skip=skip,
        limit=limit,
    )
    # Manual serialization to handle Decimal → float conversion
    return [ProductResponse.model_validate(p).model_dump(mode="json") for p in products]


@router.get("/{product_id}")
async def get_product(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return ProductResponse.model_validate(product).model_dump(mode="json")


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
@_limiter.limit("20/minute")
async def upload_product_image(
    request: Request,
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

    # Validate content type — images only
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")

    file_data = await file.read()

    # Validate file size — max 5 MB
    if len(file_data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    import os as _os

    safe_filename = f"{uuid.uuid4().hex}{_os.path.splitext(file.filename or '.jpg')[1]}"
    object_name = f"products/{product_id}/{safe_filename}"
    content_type = file.content_type or "image/jpeg"

    await minio_service.upload_file(object_name, file_data, content_type)

    # Add to image gallery and set as primary
    gallery = list(product.image_urls) if isinstance(product.image_urls, list) else []
    gallery.append(
        {
            "url": object_name,
            "object_name": object_name,
            "source": "upload",
            "original_filename": file.filename,
        }
    )
    product.image_urls = gallery
    product.primary_image_url = object_name
    flag_modified(product, "image_urls")
    await db.commit()
    await db.refresh(product)
    return product


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


# ── Product Image Gallery ────────────────────────────────────────────────


class FetchImagesRequest(BaseModel):
    product_ids: list[uuid.UUID]


class FetchImagesResponse(BaseModel):
    product_id: str
    images_found: int
    images: list[dict]


@router.post("/{product_id}/fetch-images")
async def fetch_product_images(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search the web for real product images and save them to the product's image gallery."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    from app.services.gemini_service import search_product_images

    results = await search_product_images(
        product_name=product.name,
        product_description=product.description or "",
        max_results=3,
    )

    if not results:
        return {"product_id": str(product_id), "images_found": 0, "images": []}

    # Save images to MinIO and build gallery entries
    gallery = list(product.image_urls) if isinstance(product.image_urls, list) else []
    if isinstance(product.image_urls, dict):
        gallery = list(product.image_urls.values()) if product.image_urls else []

    new_images = []
    for i, img in enumerate(results):
        ext = (
            "jpg"
            if "jpeg" in img["content_type"]
            else img["content_type"].split("/")[-1]
        )
        object_name = f"products/{product_id}/gallery/web_{len(gallery) + i + 1}.{ext}"

        await minio_service.ensure_bucket()
        await minio_service.upload_file(
            object_name, img["image_data"], img["content_type"]
        )

        entry = {
            "url": object_name,
            "object_name": object_name,
            "source": "web_search",
            "source_url": img["url"],
            "size_bytes": img["size_bytes"],
        }
        gallery.append(entry)
        new_images.append(entry)

    # Update product
    product.image_urls = gallery
    flag_modified(product, "image_urls")
    if not product.primary_image_url and gallery:
        product.primary_image_url = gallery[0]["object_name"]
    await db.commit()
    await db.refresh(product)

    logger.info(
        "Fetched %d web images for product %s (%s)",
        len(new_images),
        product_id,
        product.name,
    )
    return {
        "product_id": str(product_id),
        "images_found": len(new_images),
        "images": new_images,
    }


@router.post("/batch-fetch-images")
async def batch_fetch_product_images(
    req: FetchImagesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch images for multiple products at once."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    from app.services.gemini_service import search_product_images

    results = []
    for pid in req.product_ids:
        product = await product_service.get_product(db, pid)
        if not product:
            results.append(
                {
                    "product_id": str(pid),
                    "images_found": 0,
                    "error": "Product not found",
                }
            )
            continue

        images = await search_product_images(
            product_name=product.name,
            product_description=product.description or "",
            max_results=3,
        )

        gallery = (
            list(product.image_urls) if isinstance(product.image_urls, list) else []
        )

        saved = 0
        for i, img in enumerate(images):
            ext = (
                "jpg"
                if "jpeg" in img["content_type"]
                else img["content_type"].split("/")[-1]
            )
            object_name = f"products/{pid}/gallery/web_{len(gallery) + i + 1}.{ext}"
            await minio_service.ensure_bucket()
            await minio_service.upload_file(
                object_name, img["image_data"], img["content_type"]
            )
            gallery.append(
                {
                    "url": object_name,
                    "object_name": object_name,
                    "source": "web_search",
                    "source_url": img["url"],
                    "size_bytes": img["size_bytes"],
                }
            )
            saved += 1

        product.image_urls = gallery
        flag_modified(product, "image_urls")
        if not product.primary_image_url and gallery:
            product.primary_image_url = gallery[0]["url"]
        await db.commit()

        results.append({"product_id": str(pid), "images_found": saved})

    return {"results": results, "total_processed": len(results)}


@router.get("/{product_id}/images")
async def get_product_image_gallery(
    product_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the product's image gallery."""
    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    gallery = []
    if isinstance(product.image_urls, list):
        gallery = product.image_urls
    elif isinstance(product.image_urls, dict):
        gallery = list(product.image_urls.values())

    return {
        "product_id": str(product_id),
        "primary_image_url": product.primary_image_url,
        "images": gallery,
    }


@router.delete("/{product_id}/images/{image_index}")
async def delete_product_image(
    product_id: uuid.UUID,
    image_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove an image from the product's gallery by index."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    gallery = list(product.image_urls) if isinstance(product.image_urls, list) else []
    if image_index < 0 or image_index >= len(gallery):
        raise HTTPException(status_code=404, detail="Image index out of range")

    removed = gallery.pop(image_index)

    # Try to delete from MinIO
    obj_name = removed.get("object_name") if isinstance(removed, dict) else None
    if obj_name:
        try:
            await minio_service.delete_file(obj_name)
        except Exception:
            pass

    product.image_urls = gallery
    flag_modified(product, "image_urls")

    # Update primary if it was the deleted one
    if (
        product.primary_image_url
        and isinstance(removed, dict)
        and removed.get("url") == product.primary_image_url
    ):
        product.primary_image_url = gallery[0]["url"] if gallery else None

    await db.commit()
    return {"status": "ok", "remaining": len(gallery)}


@router.put("/{product_id}/images/{image_index}/set-primary")
async def set_primary_product_image(
    product_id: uuid.UUID,
    image_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set a gallery image as the primary product image."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    product = await product_service.get_product(db, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    gallery = list(product.image_urls) if isinstance(product.image_urls, list) else []
    if image_index < 0 or image_index >= len(gallery):
        raise HTTPException(status_code=404, detail="Image index out of range")

    img = gallery[image_index]
    url = img["url"] if isinstance(img, dict) else img
    product.primary_image_url = url
    await db.commit()
    return {"status": "ok", "primary_image_url": url}
