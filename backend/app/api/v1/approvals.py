import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.schemas.approval import ApprovalCreate, ApprovalDecision, ApprovalResponse
from app.services import approval_service

router = APIRouter()


@router.get("/")
async def list_approvals(
    status: str | None = None,
    status_filter: str | None = None,
    content_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List approvals, optionally filtered by status or content_id."""
    limit = min(limit, 200)
    from sqlalchemy import select, func
    from app.models.approval import Approval
    from app.models.content import Content

    # Accept both "status" and "status_filter" query params
    effective_status = status or status_filter

    count_stmt = select(func.count(Approval.id))
    if effective_status:
        count_stmt = count_stmt.where(Approval.status == effective_status)
    if content_id:
        count_stmt = count_stmt.where(Approval.content_id == content_id)
    total = (await db.execute(count_stmt)).scalar() or 0

    from sqlalchemy.orm import selectinload

    stmt = (
        select(Approval)
        .options(
            selectinload(Approval.content).selectinload(Content.brand),
            selectinload(Approval.calendar_item),
        )
        .order_by(Approval.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if effective_status:
        stmt = stmt.where(Approval.status == effective_status)
    if content_id:
        stmt = stmt.where(Approval.content_id == content_id)
    result = await db.execute(stmt)
    items = result.scalars().all()

    # Serialize with content data for frontend
    serialized = []
    for item in items:
        d = {
            "id": str(item.id),
            "content_id": str(item.content_id),
            "calendar_item_id": str(item.calendar_item_id),
            "reviewer_id": str(item.reviewer_id) if item.reviewer_id else None,
            "status": item.status,
            "feedback": item.feedback,
            "decided_at": item.decided_at.isoformat() if item.decided_at else None,
            "created_at": item.created_at.isoformat(),
            "updated_at": item.updated_at.isoformat(),
        }
        if item.content:
            hashtags = item.content.hashtags
            if hashtags and not isinstance(hashtags, list):
                hashtags = []
            d["content"] = {
                "id": str(item.content.id),
                "brand_id": str(item.content.brand_id),
                "brand_name": item.content.brand.name if item.content.brand else None,
                "headline": item.content.headline,
                "caption": item.content.caption,
                "hashtags": hashtags or [],
                "cta_text": item.content.cta_text,
            }
        if item.calendar_item:
            d["calendar_item"] = {
                "title": item.calendar_item.title,
                "channel": item.calendar_item.channel,
                "scheduled_at": item.calendar_item.scheduled_at.isoformat()
                if item.calendar_item.scheduled_at
                else None,
            }
        serialized.append(d)

    return {"items": serialized, "total": total, "skip": skip, "limit": limit}


@router.get("/pending", response_model=list[ApprovalResponse])
async def list_pending_approvals(
    reviewer_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 200)
    return await approval_service.list_pending_approvals(
        db, reviewer_id=reviewer_id, skip=skip, limit=limit
    )


@router.get("/content/{content_id}", response_model=list[ApprovalResponse])
async def list_content_approvals(
    content_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = min(limit, 200)
    return await approval_service.list_approvals_for_content(
        db, content_id, skip=skip, limit=limit
    )


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = await approval_service.get_approval(db, approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    data: ApprovalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await approval_service.create_approval(db, data)


@router.put("/{approval_id}", response_model=ApprovalResponse)
async def update_approval(
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update/decide on an approval (PUT alias for decide)."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if decision.status not in ("approved", "rejected", "revision_requested"):
        raise HTTPException(
            status_code=422,
            detail="Decision must be 'approved', 'rejected', or 'revision_requested'",
        )
    try:
        approval = await approval_service.resolve_approval(db, approval_id, decision)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if decision.status not in ("approved", "rejected", "revision_requested"):
        raise HTTPException(
            status_code=422,
            detail="Decision must be 'approved', 'rejected', or 'revision_requested'",
        )
    try:
        approval = await approval_service.resolve_approval(db, approval_id, decision)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval
