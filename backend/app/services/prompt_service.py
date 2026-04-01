import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_version import PromptVersion
from app.schemas.prompt_version import PromptVersionCreate, PromptVersionUpdate


async def list_prompt_versions(
    db: AsyncSession,
    *,
    category: str | None = None,
    is_active: bool | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Sequence[PromptVersion]:
    stmt = select(PromptVersion).offset(skip).limit(limit)
    if category is not None:
        stmt = stmt.where(PromptVersion.category == category)
    if is_active is not None:
        stmt = stmt.where(PromptVersion.is_active == is_active)
    stmt = stmt.order_by(
        PromptVersion.category, PromptVersion.slug, PromptVersion.version.desc()
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def get_prompt_version(
    db: AsyncSession, prompt_id: uuid.UUID
) -> PromptVersion | None:
    result = await db.execute(
        select(PromptVersion).where(PromptVersion.id == prompt_id)
    )
    return result.scalar_one_or_none()


async def create_prompt_version(
    db: AsyncSession, data: PromptVersionCreate, created_by: uuid.UUID | None = None
) -> PromptVersion:
    pv = PromptVersion(**data.model_dump(), created_by=created_by)
    db.add(pv)
    await db.commit()
    await db.refresh(pv)
    return pv


async def update_prompt_version(
    db: AsyncSession, prompt_id: uuid.UUID, data: PromptVersionUpdate
) -> PromptVersion | None:
    pv = await get_prompt_version(db, prompt_id)
    if pv is None:
        return None
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(pv, key, value)
    await db.commit()
    await db.refresh(pv)
    return pv


async def activate_prompt(
    db: AsyncSession, prompt_id: uuid.UUID
) -> PromptVersion | None:
    """Activate a prompt version and deactivate others for the same category/slug."""
    pv = await get_prompt_version(db, prompt_id)
    if pv is None:
        return None

    # Deactivate all other versions for this category/slug
    others = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.category == pv.category)
        .where(PromptVersion.slug == pv.slug)
        .where(PromptVersion.id != pv.id)
    )
    for other in others.scalars():
        other.is_active = False

    pv.is_active = True
    await db.commit()
    await db.refresh(pv)
    return pv


async def deactivate_prompt(
    db: AsyncSession, prompt_id: uuid.UUID
) -> PromptVersion | None:
    pv = await get_prompt_version(db, prompt_id)
    if pv is None:
        return None
    pv.is_active = False
    await db.commit()
    await db.refresh(pv)
    return pv


async def select_ab_prompt(
    db: AsyncSession, category: str, slug: str
) -> PromptVersion | None:
    """
    Select the active prompt version for the given category/slug.
    If multiple are active, returns the one with the highest version.
    """
    result = await db.execute(
        select(PromptVersion)
        .where(PromptVersion.category == category)
        .where(PromptVersion.slug == slug)
        .where(PromptVersion.is_active == True)  # noqa: E712
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
