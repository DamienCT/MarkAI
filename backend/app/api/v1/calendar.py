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
from app.services import calendar_service, nats_service


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
            "scheduled_at": item.scheduled_at.isoformat()
            if item.scheduled_at
            else None,
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
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 1000)
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
    item = await calendar_service.create_calendar_item(db, data)

    # If the user created the item already queued, kick off content generation
    # immediately instead of waiting for the next morning_jobs cycle.
    if item.status == "queued":
        await nats_service.publish(
            "content.generate",
            {
                "brand_id": str(item.brand_id),
                "calendar_item_id": str(item.id),
                "triggered_by": f"user:{current_user.id}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    return item


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


async def _recreate_pending_approval_on_return(
    db: AsyncSession, item_id: uuid.UUID
) -> None:
    """When a scheduled post is sent back to review, recreate a pending approval
    so the Approve/Reject actions reappear.

    Reuses the content_id + reviewer_id from the item's most recent approval
    (it was approved before, so one exists). No-op if a pending one already
    exists or there's no prior approval to base it on.
    """
    from app.models.approval import Approval

    result = await db.execute(
        select(Approval)
        .where(Approval.calendar_item_id == item_id)
        .order_by(Approval.created_at.desc())
    )
    prior = result.scalars().first()
    if prior is None or prior.status == "pending":
        return
    db.add(
        Approval(
            content_id=prior.content_id,
            calendar_item_id=item_id,
            reviewer_id=prior.reviewer_id,
            status="pending",
        )
    )
    await db.commit()


@router.patch("/{item_id}", response_model=CalendarItemResponse)
async def patch_calendar_item(
    item_id: uuid.UUID,
    data: CalendarItemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partial update of a calendar item (alias for PUT)."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    existing = await calendar_service.get_calendar_item(db, item_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    old_status = existing.status
    item = await calendar_service.update_calendar_item(db, item_id, data)
    if item is None:
        raise HTTPException(status_code=404, detail="Calendar item not found")
    # Returning a scheduled post to review → re-open it for Approve/Reject.
    if old_status == "scheduled" and item.status == "in_review":
        await _recreate_pending_approval_on_return(db, item_id)
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
