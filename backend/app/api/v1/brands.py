import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.brand import ALL_CHANNELS, CHANNEL_DISPLAY_NAMES
from app.schemas.brand import BrandCreate, BrandResponse, BrandUpdate, ChannelConfigUpdate
from app.services import brand_service, fabric_service

router = APIRouter()


@router.get("/bc-companies")
async def list_bc_companies(
    current_user: User = Depends(get_current_user),
):
    """Return distinct BC company names from the items table."""
    companies = await fabric_service.list_companies()
    return companies


@router.get("/bc-locations")
async def list_bc_locations(
    company: str,
    current_user: User = Depends(get_current_user),
):
    """Return distinct stock location codes for a given BC company."""
    locations = await fabric_service.list_locations_for_company(company)
    return locations


@router.get("/", response_model=list[BrandResponse])
async def list_brands(
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await brand_service.list_brands(
        db, is_active=is_active, skip=skip, limit=limit
    )


@router.get("/{brand_id}", response_model=BrandResponse)
async def get_brand(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand


@router.post("/", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
async def create_brand(
    data: BrandCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    existing = await brand_service.get_brand_by_slug(db, data.slug)
    if existing:
        raise HTTPException(status_code=409, detail="Brand slug already exists")
    return await brand_service.create_brand(db, data)


@router.put("/{brand_id}", response_model=BrandResponse)
async def update_brand(
    brand_id: uuid.UUID,
    data: BrandUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    brand = await brand_service.update_brand(db, brand_id, data)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return brand


@router.get("/{brand_id}/channels")
async def get_brand_channels(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return channel config for a brand with setup status."""
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = brand.brand_guidelines or {}
    channels = guidelines.get("channels", {})

    result = []
    for ch in ALL_CHANNELS:
        cfg = channels.get(ch, {})
        result.append({
            "channel": ch,
            "enabled": cfg.get("enabled", False),
            "configured": cfg.get("configured", False),
            "display_name": CHANNEL_DISPLAY_NAMES[ch],
            "requires_setup": ch not in ["website_blog", "teams"],
        })
    return result


@router.put("/{brand_id}/channels")
async def update_brand_channels(
    brand_id: uuid.UUID,
    data: ChannelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update channel configuration for a brand."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = dict(brand.brand_guidelines or {})
    guidelines["channels"] = data.channels
    updated = await brand_service.update_brand(
        db, brand_id, BrandUpdate(brand_guidelines=guidelines)
    )
    return {"status": "ok", "channels": updated.brand_guidelines.get("channels", {})}


@router.delete("/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    deleted = await brand_service.delete_brand(db, brand_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Brand not found")
