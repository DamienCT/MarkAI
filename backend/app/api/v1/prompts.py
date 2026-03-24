import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import role_has_access
from app.deps import get_current_user, get_db
from app.schemas.prompt_version import (
    PromptVersionCreate,
    PromptVersionResponse,
    PromptVersionUpdate,
)
from app.services import prompt_service

router = APIRouter()


@router.get("/", response_model=list[PromptVersionResponse])
async def list_prompts(
    category: str | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await prompt_service.list_prompt_versions(
        db, category=category, is_active=is_active, skip=skip, limit=limit
    )


@router.get("/{prompt_id}", response_model=PromptVersionResponse)
async def get_prompt(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    pv = await prompt_service.get_prompt_version(db, prompt_id)
    if pv is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return pv


@router.post(
    "/", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED
)
async def create_prompt(
    data: PromptVersionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return await prompt_service.create_prompt_version(db, data, created_by=current_user.id)


@router.put("/{prompt_id}", response_model=PromptVersionResponse)
async def update_prompt(
    prompt_id: uuid.UUID,
    data: PromptVersionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    pv = await prompt_service.update_prompt_version(db, prompt_id, data)
    if pv is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return pv


@router.post("/{prompt_id}/activate", response_model=PromptVersionResponse)
async def activate_prompt(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    pv = await prompt_service.activate_prompt(db, prompt_id)
    if pv is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return pv


@router.post("/{prompt_id}/deactivate", response_model=PromptVersionResponse)
async def deactivate_prompt(
    prompt_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    pv = await prompt_service.deactivate_prompt(db, prompt_id)
    if pv is None:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    return pv


@router.post("/ab-select", response_model=PromptVersionResponse)
async def ab_select_prompt(
    category: str,
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Select an active prompt version for the given category/slug."""
    pv = await prompt_service.select_ab_prompt(db, category, slug)
    if pv is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active prompts found for {category}/{slug}",
        )
    return pv
