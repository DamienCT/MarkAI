import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.schemas.content import ContentCreate, ContentResponse, ContentUpdate
from app.services import content_service
from app.services.content_service import InvalidStatusTransition

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
        raise HTTPException(status_code=404, detail="Content not found for this calendar item")
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
