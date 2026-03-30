import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.models.calendar_item import CalendarItem
from app.schemas.calendar_item import (
    CalendarItemCreate,
    CalendarItemResponse,
    CalendarItemUpdate,
)
from app.services import calendar_service


class CalendarReorderItem(BaseModel):
    """Pydantic model for a single item in a calendar reorder request."""
    id: uuid.UUID
    scheduled_at: datetime

router = APIRouter()


@router.get("/upcoming")
async def upcoming_calendar_items(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return upcoming calendar items with scheduled_at >= now(), ordered ascending."""
    limit = min(limit, 200)
    now = datetime.now(timezone.utc)
    stmt = (
        select(CalendarItem)
        .options(selectinload(CalendarItem.brand))
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
            "brand_name": item.brand.name if item.brand else None,
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


@router.get("/", response_model=list[CalendarItemResponse])
async def list_calendar_items(
    brand_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 200)
    return await calendar_service.list_calendar_items(
        db,
        brand_id=brand_id,
        start_date=start_date,
        end_date=end_date,
        status=status_filter,
        skip=skip,
        limit=limit,
    )


@router.get("/{item_id}", response_model=CalendarItemResponse)
async def get_calendar_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await calendar_service.get_calendar_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    return item


@router.post(
    "/", response_model=CalendarItemResponse, status_code=status.HTTP_201_CREATED
)
async def create_calendar_item(
    data: CalendarItemCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await calendar_service.create_calendar_item(db, data)


@router.put("/{item_id}", response_model=CalendarItemResponse)
async def update_calendar_item(
    item_id: uuid.UUID,
    data: CalendarItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    item = await calendar_service.update_calendar_item(db, item_id, data)
    if item is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_item(
    item_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    deleted = await calendar_service.delete_calendar_item(db, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Calendar item not found")


@router.post("/reorder", response_model=list[CalendarItemResponse])
async def reorder_calendar_items(
    items: list[CalendarReorderItem],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reorder calendar items via drag-and-drop (update scheduled_at)."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await calendar_service.reorder_calendar_items(
        db, [item.model_dump() for item in items]
    )
