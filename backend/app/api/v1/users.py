import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.auth.entra import (  # noqa: E402
    get_graph_users_by_ids,
    search_graph_users,
)
from app.auth.models import User  # noqa: E402
from app.auth.permissions import role_has_access  # noqa: E402
from app.config import settings  # noqa: E402
from app.deps import get_current_user, get_db  # noqa: E402
from app.schemas.user import UserCreate, UserResponse, UserUpdate  # noqa: E402

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic models for new endpoints
# ---------------------------------------------------------------------------


class EntraUserResult(BaseModel):
    id: str
    displayName: str
    mail: str | None = None
    userPrincipalName: str | None = None


class GrantAccessRequest(BaseModel):
    user_ids: list[str]  # Entra object IDs
    role: str = "viewer"


class GrantAccessResult(BaseModel):
    granted: list[str]
    errors: list[str]


# ---------------------------------------------------------------------------
# Entra ID user search
# ---------------------------------------------------------------------------


@router.get("/search", response_model=list[EntraUserResult])
async def search_entra_users(
    q: str = Query(..., min_length=1, description="Search query for name or email"),
    current_user: User = Depends(get_current_user),
):
    """Search Entra ID users by name or email using Microsoft Graph API."""
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    try:
        results = await search_graph_users(q)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to search Entra ID users: {exc}",
        )
    return results


# ---------------------------------------------------------------------------
# Bulk grant access
# ---------------------------------------------------------------------------


@router.post("/grant-access", response_model=GrantAccessResult)
async def grant_access(
    data: GrantAccessRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Grant app access to selected Entra ID users."""
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not data.user_ids:
        raise HTTPException(status_code=400, detail="No user IDs provided")

    if data.role not in ("admin", "manager", "editor", "viewer"):
        raise HTTPException(status_code=400, detail="Invalid role")

    # Fetch user details from Graph API
    try:
        graph_users = await get_graph_users_by_ids(data.user_ids)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch user details from Entra ID: {exc}",
        )

    graph_user_map: dict[str, dict[str, Any]] = {u["id"]: u for u in graph_users}

    granted: list[str] = []
    errors: list[str] = []

    for user_id in data.user_ids:
        graph_info = graph_user_map.get(user_id)
        if not graph_info:
            errors.append(f"User {user_id} not found in Entra ID")
            continue

        email = graph_info.get("mail") or graph_info.get("userPrincipalName") or ""
        display_name = graph_info.get("displayName", "Unknown")

        # Check if user already exists
        result = await db.execute(select(User).where(User.entra_id == user_id))
        existing = result.scalar_one_or_none()

        if existing:
            existing.is_active = True
            existing.role = data.role
            existing.display_name = display_name
            if email:
                existing.email = email
        else:
            new_user = User(
                entra_id=user_id,
                email=email,
                display_name=display_name,
                role=data.role,
                is_active=True,
            )
            db.add(new_user)

        granted.append(user_id)

    if granted:
        await db.commit()

    return GrantAccessResult(granted=granted, errors=errors)


# ---------------------------------------------------------------------------
# Security group membership check
# ---------------------------------------------------------------------------


@router.get("/security-group-members", response_model=list[str])
async def get_security_group_members(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return Entra object IDs of ALL members in the admin security group (from Graph API)."""
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if not settings.ADMIN_SECURITY_GROUP_ID:
        return []

    try:
        from app.auth.entra import get_graph_api_token
        import httpx

        token = await get_graph_api_token()
        member_ids: list[str] = []
        url = f"https://graph.microsoft.com/v1.0/groups/{settings.ADMIN_SECURITY_GROUP_ID}/members"
        params = {"$select": "id", "$top": "999"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {token}"}
            )
            resp.raise_for_status()
            for member in resp.json().get("value", []):
                if member.get("id"):
                    member_ids.append(member["id"])

        return member_ids
    except Exception as exc:
        logger.warning("Failed to fetch security group members: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Existing CRUD endpoints
# ---------------------------------------------------------------------------


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
):
    """Get the currently authenticated user."""
    return current_user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    limit = min(limit, 200)
    result = await db.execute(
        select(User).offset(skip).limit(limit).order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    existing = await db.execute(
        select(User).where(
            (User.entra_id == data.entra_id) | (User.email == data.email)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User already exists")

    user = User(**data.model_dump())
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def patch_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Partial update for a user (PATCH)."""
    if not role_has_access(current_user.role, "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    await db.commit()
    await db.refresh(user)
    return user
