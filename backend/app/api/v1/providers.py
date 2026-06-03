from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.config import settings
from app.deps import get_current_user, get_db
from app.models.channel_model_fallback import ChannelModelFallback
from app.schemas.ai_model import (
    AIModelResponse,
    AIModelSelectionResponse,
    AIModelSelectionUpdate,
    DiscoverModelsResponse,
)
from app.services.ai_model_service import (
    discover_models,
    get_all_active_models,
    list_categories,
    list_models_by_category,
    set_active_model,
)

# Channels that can have a per-channel fallback model. Image-publishing
# surfaces only — Teams / website blog don't generate images via this path.
SUPPORTED_FALLBACK_CHANNELS = ("instagram", "facebook", "linkedin")

router = APIRouter()


@router.get("/categories", response_model=list[dict])
async def get_categories(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all model categories with their active selections."""
    categories = await list_categories(db)
    # Serialize active_model manually for the response
    result = []
    for cat in categories:
        entry = {
            "id": str(cat["id"]),
            "slug": cat["slug"],
            "display_name": cat["display_name"],
            "description": cat["description"],
            "active_model": None,
        }
        if cat["active_model"]:
            m = cat["active_model"]
            entry["active_model"] = {
                "id": str(m.id),
                "provider": m.provider,
                "model_id": m.model_id,
                "display_name": m.display_name,
                "category_id": str(m.category_id) if m.category_id else None,
                "is_available": m.is_available,
                "capabilities": m.capabilities,
                "discovered_at": m.discovered_at.isoformat()
                if m.discovered_at
                else None,
            }
        result.append(entry)
    return result


@router.get("/models", response_model=list[AIModelResponse])
async def get_models(
    category: str | None = Query(None, description="Filter by category slug"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List available models, optionally filtered by category."""
    models = await list_models_by_category(db, category)
    return models


@router.get("/active")
async def get_active_models(
    db: AsyncSession = Depends(get_db),
):
    """Get the active model for each category (dict: slug -> model_id).

    No auth required — used by agents service internally and only returns model IDs.
    """
    models = await get_all_active_models(db)
    return {"models": models}


@router.put("/active/{category_slug}", response_model=AIModelSelectionResponse)
async def update_active_model(
    category_slug: str,
    body: AIModelSelectionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set the active model for a category. Admin only."""
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        selection = await set_active_model(
            category_slug=category_slug,
            model_id=body.model_id,
            user_id=current_user.id,
            db=db,
        )
        return selection
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/discover", response_model=DiscoverModelsResponse)
async def trigger_discover(
    current_user: User = Depends(get_current_user),
):
    """Manually trigger model discovery from OpenAI API. Admin only."""
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        result = await discover_models()
        return DiscoverModelsResponse(**result)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to discover models: {exc}",
        )


@router.get("/health")
async def provider_health(
    current_user: User = Depends(get_current_user),
):
    """Check LiteLLM proxy health."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {}
            if settings.LITELLM_MASTER_KEY:
                headers["Authorization"] = f"Bearer {settings.LITELLM_MASTER_KEY}"
            resp = await client.get(
                f"{settings.LITELLM_BASE_URL}/health", headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
            data["status"] = "healthy"
            return data
    except httpx.ConnectError:
        return {"status": "unreachable", "detail": "Cannot connect to LiteLLM proxy"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


# ──────────────────────────────────────────────────────────────────────
# Channel-specific model fallbacks
# ──────────────────────────────────────────────────────────────────────


class ChannelFallbackResponse(BaseModel):
    channel: str
    category: str
    model_id: str
    is_active: bool


class ChannelFallbackUpdate(BaseModel):
    channel: str
    category: str
    model_id: str
    is_active: bool = True


@router.get("/channel-fallbacks", response_model=list[ChannelFallbackResponse])
async def list_channel_fallbacks(
    category: str = Query("image"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List configured channel-specific fallback models for a category.

    Returns one entry per (channel, category) row that exists in the DB.
    Channels without a configured fallback simply don't appear.
    """
    result = await db.execute(
        select(ChannelModelFallback).where(ChannelModelFallback.category == category)
    )
    return [
        ChannelFallbackResponse(
            channel=row.channel,
            category=row.category,
            model_id=row.model_id,
            is_active=row.is_active,
        )
        for row in result.scalars().all()
    ]


@router.put("/channel-fallbacks", response_model=ChannelFallbackResponse)
async def update_channel_fallback(
    body: ChannelFallbackUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a channel-specific fallback model. Admin only.

    Matches the permission level of `update_active_model` so the active
    model and its channel-level fallbacks live under the same gate.
    """
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    channel = body.channel.lower().strip()
    if channel not in SUPPORTED_FALLBACK_CHANNELS:
        raise HTTPException(
            status_code=400,
            detail=f"Channel '{channel}' not supported. Use one of: {', '.join(SUPPORTED_FALLBACK_CHANNELS)}",
        )

    stmt = pg_insert(ChannelModelFallback).values(
        channel=channel,
        category=body.category,
        model_id=body.model_id,
        is_active=body.is_active,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="channel_model_fallbacks_uniq",
        set_={
            "model_id": stmt.excluded.model_id,
            "is_active": stmt.excluded.is_active,
        },
    )
    await db.execute(stmt)
    await db.commit()

    return ChannelFallbackResponse(
        channel=channel,
        category=body.category,
        model_id=body.model_id,
        is_active=body.is_active,
    )
