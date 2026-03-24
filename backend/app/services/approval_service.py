import uuid
from datetime import datetime
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
    result = await db.execute(
        select(Approval).where(Approval.id == approval_id)
    )
    return result.scalar_one_or_none()


async def create_approval(db: AsyncSession, data: ApprovalCreate) -> Approval:
    approval = Approval(**data.model_dump())
    db.add(approval)
    await db.commit()
    await db.refresh(approval)
    return approval


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
    approval.decided_at = datetime.now()

    # Update the associated calendar item status based on the decision
    if approval.calendar_item_id:
        result = await db.execute(
            select(CalendarItem).where(CalendarItem.id == approval.calendar_item_id)
        )
        cal_item = result.scalar_one_or_none()
        if cal_item is not None:
            if decision.status == "approved":
                cal_item.status = "approved"
            elif decision.status in ("rejected", "revision_requested"):
                cal_item.status = "reworking"

    await db.commit()
    await db.refresh(approval)
    return approval
