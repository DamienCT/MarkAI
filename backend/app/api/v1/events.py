import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.schemas.event import (
    DetectEventsRequest,
    EventCreate,
    EventResponse,
    EventUpdate,
)
from app.services import brand_service, event_service

_limiter = Limiter(key_func=get_remote_address)

logger = logging.getLogger(__name__)

router = APIRouter()


def _scope_filter(scope: str | None) -> tuple[uuid.UUID | None, bool]:
    """Translate the frontend ``scope`` query param into service kwargs.

    - "global" → brand_id=None, include_global=True (global-only handled below)
    - None / "all" → every event (brand_id=None, include_global=True, no extra
      filter — list_events returns all rows when brand_id is None + include_global)

    A UUID string is parsed as a brand_id.
    """
    if not scope or scope == "all":
        return (None, True)
    if scope == "global":
        # brand_id=None + include_global=False → only global rows
        return (None, False)
    try:
        return (uuid.UUID(scope), True)
    except ValueError:
        return (None, True)


@router.get("/", response_model=list[EventResponse])
async def list_events(
    scope: str | None = Query(None, description="'all' | 'global' | <brand_uuid>"),
    category: str | None = None,
    upcoming_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand_id, include_global = _scope_filter(scope)
    return await event_service.list_events(
        db,
        brand_id=brand_id,
        include_global=include_global,
        category=category,
        upcoming_only=upcoming_only,
    )


@router.get("/updated-at")
async def events_updated_at(
    brand_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return max(updated_at) for global + brand events — used by the
    IntelligenceTab 'events changed since last research' banner."""
    return {"updated_at": await event_service.latest_updated_at(db, brand_id)}


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    event = await event_service.get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    data: EventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await event_service.create_event(db, data)


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: uuid.UUID,
    data: EventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    event = await event_service.update_event(db, event_id, data)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    ok = await event_service.delete_event(db, event_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Event not found")


@router.post("/detect", response_model=list[EventResponse])
@_limiter.limit("10/minute")
async def detect_events(
    request: Request,
    body: DetectEventsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """LLM-assisted event suggestions. Appends to the table; dedup on
    (title, month-day, brand_id)."""
    if not role_has_access(current_user.role, "editor"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    brand_dict: dict | None = None
    if body.brand_id is not None:
        brand = await brand_service.get_brand(db, body.brand_id)
        if brand is None:
            raise HTTPException(status_code=404, detail="Brand not found")
        brand_dict = {
            "name": brand.name,
            "description": brand.description,
            "target_audience": brand.target_audience or {},
            "brand_guidelines": brand.brand_guidelines or {},
        }

    created = await event_service.detect_events_via_llm(
        db,
        brand_dict,
        brand_id=body.brand_id,
        horizon_months=max(1, min(24, body.horizon_months or 12)),
    )
    return created
