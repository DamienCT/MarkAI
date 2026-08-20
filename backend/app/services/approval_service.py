import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.schemas.approval import ApprovalCreate, ApprovalDecision


async def list_pending_approvals(
    db: AsyncSession,
    *,
    reviewer_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[Approval]:
    stmt = (
        select(Approval)
        .where(Approval.status == "pending")
        .offset(skip)
        .limit(limit)
        .order_by(Approval.created_at.desc())
    )
    if reviewer_id is not None:
        stmt = stmt.where(Approval.reviewer_id == reviewer_id)
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_approvals_for_content(
    db: AsyncSession,
    content_id: uuid.UUID,
    *,
    skip: int = 0,
    limit: int = 50,
) -> Sequence[Approval]:
    result = await db.execute(
        select(Approval)
        .where(Approval.content_id == content_id)
        .offset(skip)
        .limit(limit)
        .order_by(Approval.created_at.desc())
    )
    return result.scalars().all()


async def get_approval(db: AsyncSession, approval_id: uuid.UUID) -> Approval | None:
    result = await db.execute(select(Approval).where(Approval.id == approval_id))
    return result.scalar_one_or_none()


async def create_approval(db: AsyncSession, data: ApprovalCreate) -> Approval:
    approval = Approval(**data.model_dump())
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


def _roll_schedule_forward(scheduled_at: datetime | None, now: datetime) -> datetime:
    """Next future slot for an item approved after its scheduled_at passed:
    keep the original time-of-day, moved to today — or tomorrow if that time
    is already gone. With no prior schedule, fall back to this time tomorrow."""
    if scheduled_at is None:
        return now + timedelta(days=1)
    candidate = now.replace(
        hour=scheduled_at.hour,
        minute=scheduled_at.minute,
        second=scheduled_at.second,
        microsecond=0,
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


async def resolve_approval(
    db: AsyncSession,
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
) -> Approval | None:
    from app.models.calendar_item import CalendarItem

    approval = await get_approval(db, approval_id)
    if approval is None:
        return None
    if approval.status != "pending":
        raise ValueError(f"Approval is already '{approval.status}', cannot resolve")

    approval.status = decision.status
    approval.feedback = decision.feedback
    approval.decided_at = datetime.now(timezone.utc)

    # Update the associated calendar item status based on the decision,
    # using the same state-machine validation as content_service.
    if approval.calendar_item_id:
        from app.services.content_service import _validate_transition

        result = await db.execute(
            select(CalendarItem).where(CalendarItem.id == approval.calendar_item_id)
        )
        cal_item = result.scalar_one_or_none()
        if cal_item is not None:
            if decision.status == "approved":
                # Auto-schedule: skip "approved" status, go directly to "scheduled"
                _validate_transition(cal_item.status, "scheduled")
                cal_item.status = "scheduled"
                # A missing or past scheduled_at would make the publish checker
                # fire instantly (or silently expire the item as >1-day stale)
                # — roll it forward to the next future slot and record the
                # change on the approval so the UI can surface it.
                now = datetime.now(timezone.utc)
                if cal_item.scheduled_at is None or cal_item.scheduled_at <= now:
                    new_slot = _roll_schedule_forward(cal_item.scheduled_at, now)
                    cal_item.scheduled_at = new_slot
                    note = (
                        "Note: scheduled time was missing or in the past — "
                        f"rescheduled to {new_slot.strftime('%Y-%m-%d %H:%M UTC')}."
                    )
                    approval.feedback = (
                        f"{approval.feedback}\n\n{note}" if approval.feedback else note
                    )
            elif decision.status in ("rejected", "revision_requested"):
                _validate_transition(cal_item.status, "reworking")
                cal_item.status = "reworking"

    await db.commit()
    await db.refresh(approval)
    return approval
