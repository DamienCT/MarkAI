import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.calendar_item import CalendarItem
from app.schemas.content import ContentCreate, ContentResponse, ContentUpdate
from app.services import content_service
from app.services.content_service import InvalidStatusTransition

router = APIRouter()


@router.get("/calendar")
async def content_calendar(
    brand_id: uuid.UUID | None = None,
    month: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all calendar items, optionally filtered by brand or month."""
    stmt = select(CalendarItem).order_by(CalendarItem.scheduled_at.desc()).limit(200)
    if brand_id:
        stmt = stmt.where(CalendarItem.brand_id == brand_id)
    result = await db.execute(stmt)
    items = result.scalars().all()
    return [
        {
            "id": str(item.id),
            "brand_id": str(item.brand_id),
            "title": item.title,
            "channel": item.channel,
            "status": item.status,
            "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
            "published_at": item.published_at.isoformat() if item.published_at else None,
        }
        for item in items
    ]


@router.get("/calendar/upcoming")
async def content_calendar_upcoming(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return upcoming calendar items with scheduled_at >= now(), ordered ascending."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(CalendarItem)
        .where(CalendarItem.scheduled_at >= now)
        .order_by(CalendarItem.scheduled_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    return [
        {
            "id": str(item.id),
            "brand_id": str(item.brand_id),
            "campaign_id": str(item.campaign_id) if item.campaign_id else None,
            "title": item.title,
            "description": item.description,
            "item_type": item.item_type,
            "channel": item.channel,
            "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
            "status": item.status,
            "priority": item.priority,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        for item in items
    ]


@router.get("/", response_model=list[ContentResponse])
async def list_content(
    brand_id: uuid.UUID | None = None,
    is_current: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await content_service.list_content(
        db, brand_id=brand_id, is_current=is_current, skip=skip, limit=limit
    )


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
