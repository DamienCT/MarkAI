import uuid
from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content import Content
from app.schemas.content import ContentCreate, ContentUpdate


class InvalidStatusTransition(ValueError):
    # A ValueError so route handlers that guard resolve_approval with
    # `except ValueError` return 422 instead of letting it escape as a 500.
    pass


async def list_content(
    db: AsyncSession,
    *,
    brand_id: uuid.UUID | None = None,
    # Content is versioned; superseded rows keep is_current=False. Default to
    # current rows so listings don't show every historical version of each
    # item — pass False for history only, or None explicitly for everything.
    is_current: bool | None = True,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[Content]:
    stmt = (
        select(Content)
        .options(selectinload(Content.calendar_item), selectinload(Content.brand))
        .offset(skip)
        .limit(limit)
        .order_by(Content.created_at.desc())
    )
    if brand_id is not None:
        stmt = stmt.where(Content.brand_id == brand_id)
    if is_current is not None:
        stmt = stmt.where(Content.is_current == is_current)
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_content(db: AsyncSession, content_id: uuid.UUID) -> Content | None:
    result = await db.execute(select(Content).where(Content.id == content_id))
    return result.scalar_one_or_none()


async def get_content_by_calendar_item(
    db: AsyncSession, calendar_item_id: uuid.UUID
) -> Content | None:
    """Get the most recent current content for a calendar item."""
    result = await db.execute(
        select(Content)
        .where(Content.calendar_item_id == calendar_item_id, Content.is_current)
        .order_by(Content.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create_content(db: AsyncSession, data: ContentCreate) -> Content:
    # Demote any existing current rows for this calendar item first, in the
    # same transaction — a partial unique index (idx_content_current) allows
    # exactly one is_current row per calendar item, so inserting without
    # demoting is an IntegrityError (a 500 at the API). Mirrors the agents'
    # store_content, which maintains the same invariant on its side.
    if data.is_current:
        await db.execute(
            update(Content)
            .where(
                Content.calendar_item_id == data.calendar_item_id,
                Content.is_current,
            )
            .values(is_current=False)
        )
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

    # is_current is owned by the versioning flow (demote-then-insert on
    # create): a PUT that flipped it could strand a calendar item with zero
    # current rows, silently blocking publish. Ignored rather than 422'd so
    # old clients that still send it keep working.
    update_data.pop("is_current", None)

    for key, value in update_data.items():
        setattr(content, key, value)

    await db.commit()
    await db.refresh(content)
    return content


VALID_TRANSITIONS: dict[str, list[str]] = {
    "planned": ["queued"],
    "queued": ["working"],
    "working": ["in_review", "failed"],
    "in_review": ["scheduled", "reworking"],  # Approve → auto-schedule (no "approved" step)
    "reworking": ["in_review"],
    "scheduled": ["published", "failed"],  # Publish checker posts via the native publishers
    "published": [],
    "failed": ["scheduled"],
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
