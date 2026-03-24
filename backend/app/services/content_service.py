import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import Content
from app.schemas.content import ContentCreate, ContentUpdate


class InvalidStatusTransition(Exception):
    pass


async def list_content(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    is_current: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    **kwargs,
) -> Sequence[Content]:
    stmt = select(Content).offset(skip).limit(limit).order_by(Content.created_at.desc())
    if brand_id is not None:
        stmt = stmt.where(Content.brand_id == brand_id)
    if is_current is not None:
        stmt = stmt.where(Content.is_current == is_current)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_content(db: AsyncSession, content_id: uuid.UUID) -> Content | None:
    result = await db.execute(select(Content).where(Content.id == content_id))
    return result.scalar_one_or_none()


async def create_content(db: AsyncSession, data: ContentCreate) -> Content:
    content = Content(**data.model_dump())
    db.add(content)
    await db.commit()
    await db.refresh(content)
    return content


async def update_content(
    db: AsyncSession, content_id: uuid.UUID, data: ContentUpdate
) -> Content | None:
    content = await get_content(db, content_id)
    if content is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(content, key, value)

    await db.commit()
    await db.refresh(content)
    return content


VALID_TRANSITIONS: dict[str, list[str]] = {
    "queued": ["working"],
    "working": ["in_review", "failed"],
    "in_review": ["approved", "reworking"],
    "reworking": ["in_review"],
    "approved": ["scheduled"],
    "scheduled": ["published", "failed"],
    "published": [],
    "failed": [],
}

# Any status can be reset back to queued
ALL_STATUSES = list(VALID_TRANSITIONS.keys())


def _validate_transition(current: str, new: str) -> None:
    """Raise if the status transition is not allowed."""
    if new == "queued":
        return  # reset is always allowed
    allowed = VALID_TRANSITIONS.get(current, [])
    if new not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition from '{current}' to '{new}'. "
            f"Allowed transitions: {allowed}"
        )


async def transition_status(
    db: AsyncSession,
    content_id: uuid.UUID,
    new_status: str,
    **extra_fields: object,
) -> Content | None:
    """
    Content no longer has a status column; status lives on CalendarItem.
    This is kept for backward compatibility but operates on the
    associated calendar item's status.
    """
    from app.models.calendar_item import CalendarItem

    content = await get_content(db, content_id)
    if content is None:
        return None

    # Update the associated calendar item's status
    if content.calendar_item_id:
        result = await db.execute(
            select(CalendarItem).where(CalendarItem.id == content.calendar_item_id)
        )
        cal_item = result.scalar_one_or_none()
        if cal_item is not None:
            _validate_transition(cal_item.status, new_status)
            cal_item.status = new_status

    for key, value in extra_fields.items():
        if hasattr(content, key):
            setattr(content, key, value)

    await db.commit()
    await db.refresh(content)
    return content
