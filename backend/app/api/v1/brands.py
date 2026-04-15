import re
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.brand import ALL_CHANNELS, CHANNEL_DISPLAY_NAMES
from app.models.competitor import Competitor
from app.schemas.brand import (
    BrandCreate,
    BrandResponse,
    BrandUpdate,
    ChannelConfigUpdate,
)
from app.schemas.competitor import (
    CompetitorCreateBody,
    CompetitorResponse,
    CompetitorUpdate,
)
from app.services import brand_service, fabric_service, minio_service
from slowapi import Limiter
from slowapi.util import get_remote_address

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter()

# Sensitive keys that must never leak to the frontend via brand_guidelines JSONB
_SENSITIVE_GUIDELINE_KEYS = {
    "access_token",
    "api_key",
    "refresh_token",
    "webhook_url",
    "client_secret",
    "password",
    "private_key",
    "secret",
    "signing_key",
}

# Regex for safe logo labels — alphanumeric, hyphens, underscores, max 50 chars
_SAFE_LABEL_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


def _strip_sensitive_recursive(obj: object) -> object:
    """Recursively strip sensitive keys from nested dicts."""
    if isinstance(obj, dict):
        return {
            k: _strip_sensitive_recursive(v)
            for k, v in obj.items()
            if k not in _SENSITIVE_GUIDELINE_KEYS
        }
    if isinstance(obj, list):
        return [_strip_sensitive_recursive(item) for item in obj]
    return obj


def _strip_sensitive_guidelines(brand):
    """Return a brand object with sensitive fields removed from brand_guidelines.

    Works on a deep copy so the ORM instance is never mutated — prevents
    accidental persistence of stripped data via autoflush/commit.
    """
    from copy import deepcopy

    guidelines = brand.brand_guidelines
    if not guidelines or not isinstance(guidelines, dict):
        return brand
    cleaned = _strip_sensitive_recursive(deepcopy(guidelines))
    # Work on an expunged copy to prevent DB mutation
    brand_copy = deepcopy(brand)
    brand_copy.brand_guidelines = cleaned
    return brand_copy


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
    limit = min(limit, 200)
    brands = await brand_service.list_brands(
        db, is_active=is_active, skip=skip, limit=limit
    )
    return [_strip_sensitive_guidelines(b) for b in brands]


@router.get("/{brand_id}", response_model=BrandResponse)
async def get_brand(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")
    return _strip_sensitive_guidelines(brand)


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
    # Force new brands to onboarding status
    data.is_active = False
    data.status = "onboarding"
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
    # Sync is_active with status if status is provided
    if data.status is not None:
        data.is_active = data.status in ("active", "activating")
    elif data.is_active is not None:
        # Sync status with is_active if only is_active is provided
        if not data.is_active:
            data.status = "inactive"
    # Check if is_active is being set to false so we can cancel running agents
    deactivating = data.is_active is False

    try:
        brand = await brand_service.update_brand(db, brand_id, data)
        if brand is None:
            raise HTTPException(status_code=404, detail="Brand not found")

        # Cancel any running agent_runs when the brand is deactivated
        if deactivating:
            await db.execute(
                text(
                    "UPDATE agent_runs SET status = 'cancelled', completed_at = NOW() "
                    "WHERE brand_id = :brand_id AND status = 'running'"
                ),
                {"brand_id": brand_id},
            )
            await db.commit()

        return brand
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise


@router.post("/{brand_id}/complete-onboarding", response_model=BrandResponse)
async def complete_onboarding(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate and mark onboarding as complete."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Validate required onboarding steps
    missing = []
    if not brand.name or not brand.description:
        missing.append("Brand name and description")
    if not brand.tone_of_voice:
        missing.append("Voice profile")

    # Check at least one channel enabled
    channels = (brand.brand_guidelines or {}).get("channels", {})
    has_channel = any(
        ch.get("enabled") for ch in channels.values() if isinstance(ch, dict)
    )
    if not has_channel:
        missing.append("At least one enabled channel")

    # Check at least one logo
    logos = (brand.brand_guidelines or {}).get("logos", {})
    if not logos:
        missing.append("At least one logo")

    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"Onboarding incomplete. Missing: {', '.join(missing)}",
        )

    from datetime import datetime, timezone

    brand.onboarding_completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(brand)
    return brand


@router.post("/{brand_id}/activate")
@_limiter.limit("5/minute")
async def activate_content_factory(
    request: Request,
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Start Context Generation pipeline: research → strategy → plan → calendar."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    if not brand.onboarding_completed_at:
        raise HTTPException(status_code=422, detail="Complete onboarding first")

    if brand.status == "activating":
        # Allow re-activation if no agents are actually running (all failed/completed)
        running_check = await db.execute(
            text(
                "SELECT 1 FROM agent_runs WHERE brand_id = :bid AND status = 'running' LIMIT 1"
            ),
            {"bid": str(brand_id)},
        )
        if running_check.scalar_one_or_none():
            raise HTTPException(
                status_code=409, detail="Activation already in progress"
            )
        # All runs are done — allow re-activation by resetting status

    from datetime import datetime, timezone

    brand.status = "activating"
    brand.is_active = True
    brand.activation_started_at = datetime.now(timezone.utc)
    await db.commit()

    # Trigger the research pipeline (worker chains: research → strategy → planning → content)
    from app.services import nats_service

    await nats_service.publish(
        "research.trigger",
        {
            "brand_id": str(brand_id),
            "trigger": "activation",
            "scope_weeks": 12,
        },
    )

    return {
        "status": "activating",
        "brand_id": str(brand_id),
        "message": "Context Generation started. Research → Strategy → Plan → Calendar.",
    }


@router.post("/{brand_id}/generate-content")
@_limiter.limit("5/minute")
async def generate_content(
    request: Request,
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger content generation for queued calendar items."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Verify context generation completed
    ctx_check = await db.execute(
        text(
            "SELECT agent_type FROM agent_runs "
            "WHERE brand_id = :bid AND status = 'completed' "
            "AND agent_type IN ('research', 'strategy', 'planning') "
            "GROUP BY agent_type"
        ),
        {"bid": str(brand_id)},
    )
    completed_types = {row[0] for row in ctx_check.fetchall()}
    missing = {"research", "strategy", "planning"} - completed_types
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Run Context Generation first. Missing: {', '.join(sorted(missing))}",
        )

    # Query calendar items within TODAY + 7 days that need content generation
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=7)

    items_result = await db.execute(
        text(
            "SELECT id FROM calendar_items "
            "WHERE brand_id = :bid AND status IN ('queued', 'planned') "
            "  AND scheduled_at IS NOT NULL "
            "  AND scheduled_at BETWEEN :now AND :horizon "
            "ORDER BY scheduled_at ASC"
        ),
        {"bid": str(brand_id), "now": now, "horizon": horizon},
    )
    item_ids = [str(row[0]) for row in items_result.fetchall()]

    if not item_ids:
        return {
            "status": "no_items",
            "items_queued": 0,
            "brand_id": str(brand_id),
            "message": "No calendar items need content generation in the next 7 days.",
        }

    # Transition planned items to queued so they appear in Content Studio
    await db.execute(
        text(
            "UPDATE calendar_items SET status = 'queued' "
            "WHERE id = ANY(:ids) AND status = 'planned'"
        ),
        {"ids": item_ids},
    )
    await db.commit()

    # Publish first item with remaining_queue for sequential processing
    from app.services import nats_service

    first_id = item_ids[0]
    remaining = item_ids[1:]

    await nats_service.publish(
        "content.generate",
        {
            "brand_id": str(brand_id),
            "calendar_item_id": first_id,
            "trigger": "manual",
            "remaining_queue": remaining,
        },
    )

    return {
        "status": "generating",
        "items_queued": len(item_ids),
        "brand_id": str(brand_id),
        "message": f"Content generation started for {len(item_ids)} items ({now.strftime('%b %d')} – {horizon.strftime('%b %d')}).",
    }


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
        result.append(
            {
                "channel": ch,
                "enabled": cfg.get("enabled", False),
                "configured": cfg.get("configured", False),
                "display_name": CHANNEL_DISPLAY_NAMES[ch],
                "requires_setup": ch not in ["website_blog", "teams"],
            }
        )
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

    # Direct update with flag_modified to ensure JSONB persistence
    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = guidelines
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)

    return {"status": "ok", "channels": brand.brand_guidelines.get("channels", {})}


@router.post("/{brand_id}/logos")
async def upload_brand_logo(
    brand_id: uuid.UUID,
    file: UploadFile = File(...),
    label: str = "primary",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a brand logo. Supports multiple logos with labels (primary, icon, watermark, etc.)."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Validate label to prevent path traversal in MinIO object names
    if not _SAFE_LABEL_RE.match(label):
        raise HTTPException(
            status_code=400,
            detail="Invalid label — use only alphanumeric characters, hyphens, and underscores (max 50 chars)",
        )

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    # Validate file type (SVG excluded to prevent stored XSS)
    allowed = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400, detail="Only PNG, JPEG, and WebP images are allowed"
        )

    # Read file and upload to MinIO
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:  # 5MB limit
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    # Validate magic bytes match declared content type
    _magic_ok = False
    if data[:4] == b"\x89PNG" and file.content_type == "image/png":
        _magic_ok = True
    elif data[:3] == b"\xff\xd8\xff" and file.content_type == "image/jpeg":
        _magic_ok = True
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and file.content_type == "image/webp":
        _magic_ok = True
    if not _magic_ok:
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared content type",
        )

    ext = (
        file.filename.rsplit(".", 1)[-1].lower()
        if file.filename and "." in file.filename
        else "png"
    )
    object_name = f"brands/{brand_id}/logos/{label}.{ext}"

    await minio_service.ensure_bucket()
    await minio_service.upload_file(
        object_name, data, content_type=file.content_type or "image/png"
    )

    # Generate URL and update brand
    logo_url = f"/api/v1/brands/{brand_id}/logos/{label}"

    # Store logo info in brand_guidelines
    guidelines = dict(brand.brand_guidelines or {})
    logos = guidelines.get("logos", {})
    logos[label] = {
        "object_name": object_name,
        "url": logo_url,
        "content_type": file.content_type,
        "filename": file.filename,
    }
    guidelines["logos"] = logos

    # Direct update with flag_modified for JSONB persistence
    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = guidelines
    if label == "primary":
        brand.logo_url = logo_url
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return {"status": "ok", "label": label, "url": logo_url, "logos": logos}


@router.get("/{brand_id}/logos/{label}")
async def get_brand_logo(
    brand_id: uuid.UUID,
    label: str,
    db: AsyncSession = Depends(get_db),
):
    """Serve a brand logo by label (public — used by img tags)."""
    if not _SAFE_LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="Invalid label")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = brand.brand_guidelines or {}
    logos = guidelines.get("logos", {})
    logo_info = logos.get(label)
    if not logo_info:
        raise HTTPException(status_code=404, detail="Logo not found")

    try:
        data = await minio_service.download_file(logo_info["object_name"])
    except Exception:
        raise HTTPException(status_code=404, detail="Logo file not found in storage")

    from fastapi.responses import Response

    return Response(
        content=data,
        media_type=logo_info.get("content_type", "image/png"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.delete("/{brand_id}/logos/{label}")
async def delete_brand_logo(
    brand_id: uuid.UUID,
    label: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a brand logo."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not _SAFE_LABEL_RE.match(label):
        raise HTTPException(status_code=400, detail="Invalid label")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    guidelines = dict(brand.brand_guidelines or {})
    logos = guidelines.get("logos", {})
    logo_info = logos.pop(label, None)
    if not logo_info:
        raise HTTPException(status_code=404, detail="Logo not found")

    try:
        await minio_service.delete_file(logo_info["object_name"])
    except Exception:
        pass  # File may already be deleted

    guidelines["logos"] = logos

    # Force SQLAlchemy to detect the JSONB change by assigning a new dict
    from sqlalchemy.orm.attributes import flag_modified

    brand.brand_guidelines = dict(guidelines)
    if label == "primary":
        brand.logo_url = None
    flag_modified(brand, "brand_guidelines")
    await db.commit()
    await db.refresh(brand)
    return {"status": "ok"}


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


# ── Competitor CRUD ───────────────────────────────────────────────────


@router.get("/{brand_id}/competitors", response_model=list[CompetitorResponse])
async def list_brand_competitors(
    brand_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all competitors for a brand."""
    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    stmt = (
        select(Competitor)
        .where(Competitor.brand_id == brand_id)
        .order_by(Competitor.created_at.desc())
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post(
    "/{brand_id}/competitors",
    response_model=CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_competitor(
    brand_id: uuid.UUID,
    data: CompetitorCreateBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new competitor for a brand."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand = await brand_service.get_brand(db, brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="Brand not found")

    competitor = Competitor(
        brand_id=brand_id,
        name=data.name,
        website_url=data.website_url,
        social_handles=data.social_handles or {},
        description=data.notes or data.description,
        is_active=True,
        created_by=current_user.id,
    )
    db.add(competitor)
    await db.commit()
    await db.refresh(competitor)
    return competitor


@router.put(
    "/{brand_id}/competitors/{competitor_id}", response_model=CompetitorResponse
)
async def update_competitor(
    brand_id: uuid.UUID,
    competitor_id: uuid.UUID,
    data: CompetitorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a competitor."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = select(Competitor).where(
        Competitor.id == competitor_id, Competitor.brand_id == brand_id
    )
    result = await db.execute(stmt)
    competitor = result.scalar_one_or_none()
    if competitor is None:
        raise HTTPException(status_code=404, detail="Competitor not found")

    update_data = data.model_dump(exclude_unset=True)
    # Support "notes" field from frontend mapping to "description" in model
    if "notes" in update_data:
        update_data["description"] = update_data.pop("notes")
    for key, value in update_data.items():
        setattr(competitor, key, value)

    await db.commit()
    await db.refresh(competitor)
    return competitor


@router.delete(
    "/{brand_id}/competitors/{competitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_competitor(
    brand_id: uuid.UUID,
    competitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a competitor."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = select(Competitor).where(
        Competitor.id == competitor_id, Competitor.brand_id == brand_id
    )
    result = await db.execute(stmt)
    competitor = result.scalar_one_or_none()
    if competitor is None:
        raise HTTPException(status_code=404, detail="Competitor not found")

    await db.delete(competitor)
    await db.commit()
