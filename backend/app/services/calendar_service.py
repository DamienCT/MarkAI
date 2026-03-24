import uuid
from datetime import datetime
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_item import CalendarItem
from app.schemas.calendar_item import CalendarItemCreate, CalendarItemUpdate


async def list_calendar_items(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 200,
) -> Sequence[CalendarItem]:
    stmt = (
        select(CalendarItem)
        .offset(skip)
        .limit(limit)
        .order_by(CalendarItem.scheduled_at.asc())
    )
    if brand_id is not None:
        stmt = stmt.where(CalendarItem.brand_id == brand_id)
    if start_date is not None:
        stmt = stmt.where(CalendarItem.scheduled_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(CalendarItem.scheduled_at <= end_date)
    if status is not None:
        stmt = stmt.where(CalendarItem.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_calendar_item(
    db: AsyncSession, item_id: uuid.UUID
) -> CalendarItem | None:
    result = await db.execute(
        select(CalendarItem).where(CalendarItem.id == item_id)
    )
    return result.scalar_one_or_none()


async def create_calendar_item(
    db: AsyncSession, data: CalendarItemCreate
) -> CalendarItem:
    item = CalendarItem(**data.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def update_calendar_item(
    db: AsyncSession, item_id: uuid.UUID, data: CalendarItemUpdate
) -> CalendarItem | None:
    item = await get_calendar_item(db, item_id)
    if item is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return item


async def delete_calendar_item(db: AsyncSession, item_id: uuid.UUID) -> bool:
    item = await get_calendar_item(db, item_id)
    if item is None:
        return False
    await db.delete(item)
    await db.commit()
    return True


async def reorder_calendar_items(
    db: AsyncSession,
    items: list[dict],
) -> list[CalendarItem]:
    """
    Reorder calendar items by updating their scheduled_at times.
    items format: [{"id": "...", "scheduled_at": "..."}, ...]
    """
    updated = []
    for entry in items:
        item_id = uuid.UUID(entry["id"])
        item = await get_calendar_item(db, item_id)
        if item is not None:
            item.scheduled_at = datetime.fromisoformat(entry["scheduled_at"])
            updated.append(item)

    await db.commit()
    for item in updated:
        await db.refresh(item)
    return updated
