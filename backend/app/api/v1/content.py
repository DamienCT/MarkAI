import os as _os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.calendar_item import CalendarItem
from app.schemas.content import ContentCreate, ContentResponse, ContentUpdate
from app.services import content_service, minio_service
from app.services.content_service import InvalidStatusTransition

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


@router.get("/", response_model=list[ContentResponse])
async def list_content(
    brand_id: uuid.UUID | None = None,
    is_current: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 200)
    return await content_service.list_content(
        db, brand_id=brand_id, is_current=is_current, skip=skip, limit=limit
    )


@router.get("/by-calendar-item/{calendar_item_id}", response_model=ContentResponse)
async def get_content_by_calendar_item(
    calendar_item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current content record for a calendar item."""
    item = await content_service.get_content_by_calendar_item(db, calendar_item_id)
    if item is None:
        raise HTTPException(
            status_code=404, detail="Content not found for this calendar item"
        )
    return item


@router.get("/{content_id}", response_model=ContentResponse)
async def get_content(
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await content_service.get_content(db, content_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return item


@router.post("/", response_model=ContentResponse, status_code=status.HTTP_201_CREATED)
async def create_content(
    data: ContentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await content_service.create_content(db, data)


@router.put("/{content_id}", response_model=ContentResponse)
async def update_content(
    content_id: uuid.UUID,
    data: ContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        item = await content_service.update_content(db, content_id, data)
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=422, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return item


class ImageRegenerateRequest(BaseModel):
    prompt: str | None = None


@router.post("/{content_id}/regenerate-image")
async def regenerate_image(
    content_id: uuid.UUID,
    body: ImageRegenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Regenerate the image for an existing content piece without recreating the text."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    content = await content_service.get_content(db, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Publish a NATS message to trigger image regeneration
    from app.services import nats_service

    await nats_service.publish(
        "content.regenerate-image",
        {
            "content_id": str(content_id),
            "brand_id": str(content.brand_id),
            "calendar_item_id": str(content.calendar_item_id),
            "custom_prompt": (body.prompt if body else None),
        },
    )

    return {"status": "queued", "message": "Image regeneration started"}


# Statuses where the image is effectively locked — the content either went out
# the door or errored out terminally. Uploading over it would rewrite history.
_IMAGE_LOCKED_STATUSES = frozenset({"published", "failed"})


@router.post("/{content_id}/upload-image", response_model=ContentResponse)
@_limiter.limit("20/minute")
async def upload_content_image(
    request: Request,
    content_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace the AI-generated image with a user-uploaded one.

    Blocked once the linked calendar item is published or failed — those are
    terminal states where the image is treated as the canonical delivered asset.
    """
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    content = await content_service.get_content(db, content_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Content not found")

    # Status lives on CalendarItem; block edits on terminal statuses.
    cal_result = await db.execute(
        select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
    )
    cal_item = cal_result.scalar_one_or_none()
    if cal_item is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    if cal_item.status in _IMAGE_LOCKED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot edit image for content in '{cal_item.status}' state",
        )

    # Validate content type — images only (SVG excluded to prevent stored XSS)
    _allowed_types = {"image/png", "image/jpeg", "image/webp"}
    if not file.content_type or file.content_type not in _allowed_types:
        raise HTTPException(
            status_code=400, detail="Only PNG, JPEG, and WebP images are allowed"
        )

    file_data = await file.read()

    # Validate file size — max 5 MB
    if len(file_data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size must be under 5MB")

    # Validate magic bytes match declared content type
    _magic_ok = False
    if file_data[:4] == b"\x89PNG" and file.content_type == "image/png":
        _magic_ok = True
    elif file_data[:3] == b"\xff\xd8\xff" and file.content_type == "image/jpeg":
        _magic_ok = True
    elif (
        file_data[:4] == b"RIFF"
        and file_data[8:12] == b"WEBP"
        and file.content_type == "image/webp"
    ):
        _magic_ok = True
    if not _magic_ok:
        raise HTTPException(
            status_code=400,
            detail="File content does not match declared content type",
        )

    safe_filename = f"{uuid.uuid4().hex}{_os.path.splitext(file.filename or '.jpg')[1]}"
    object_name = f"contents/{content_id}/{safe_filename}"
    content_type = file.content_type or "image/jpeg"

    await minio_service.upload_file(object_name, file_data, content_type)

    # Render priority is branded_image → raw_image → generated_image_url, so
    # writing to branded_image guarantees the upload wins regardless of what
    # prior AI runs left in the other slots.
    metadata = dict(content.generation_metadata) if content.generation_metadata else {}
    metadata["branded_image"] = object_name
    metadata["user_uploaded_image"] = object_name
    content.generation_metadata = metadata
    flag_modified(content, "generation_metadata")
    await db.commit()
    await db.refresh(content)
    return content


@router.post("/{content_id}/transition", response_model=ContentResponse)
async def transition_content_status(
    content_id: uuid.UUID,
    new_status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    try:
        item = await content_service.transition_status(db, content_id, new_status)
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=422, detail=str(e))
    if item is None:
        raise HTTPException(status_code=404, detail="Content not found")
    return item
