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
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List approvals, optionally filtered by status."""
    from sqlalchemy import select, func
    from app.models.approval import Approval

    # Count total
    count_stmt = select(func.count(Approval.id))
    if status_filter:
        count_stmt = count_stmt.where(Approval.status == status_filter)
    total = (await db.execute(count_stmt)).scalar() or 0

    stmt = select(Approval).order_by(Approval.created_at.desc()).offset(skip).limit(limit)
    if status_filter:
        stmt = stmt.where(Approval.status == status_filter)
    result = await db.execute(stmt)
    items = result.scalars().all()

    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get("/pending", response_model=list[ApprovalResponse])
async def list_pending_approvals(
    reviewer_id: uuid.UUID | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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


@router.post("/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if decision.status not in ("approved", "revision_requested"):
        raise HTTPException(
            status_code=422, detail="Decision must be 'approved' or 'revision_requested'"
        )
    try:
        approval = await approval_service.resolve_approval(db, approval_id, decision)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval
