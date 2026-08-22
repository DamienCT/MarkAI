import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.auth.entra import (  # noqa: E402
    get_graph_users_by_ids,
    search_graph_users,
)
from app.auth.models import User  # noqa: E402
from app.auth.permissions import ROLES, role_has_access  # noqa: E402
from app.config import settings  # noqa: E402
from app.deps import get_current_user, get_db  # noqa: E402
from app.schemas.user import UserCreate, UserResponse, UserUpdate  # noqa: E402
from app.services import audit_service  # noqa: E402

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


async def _require_admin_grant_permission(current_user: User) -> None:
    """Granting the admin role requires membership in the admin security group.

    Shared by grant-access and the PUT/PATCH user endpoints so role escalation
    is gated (and audit-logged by the callers) identically everywhere.
    """
    from app.auth.entra import check_user_in_security_group

    if not settings.ADMIN_SECURITY_GROUP_ID:
        raise HTTPException(
            status_code=403,
            detail="Admin security group not configured; cannot grant admin role",
        )
    is_in_group = await check_user_in_security_group(
        current_user.entra_id, settings.ADMIN_SECURITY_GROUP_ID
    )
    if not is_in_group:
        raise HTTPException(
            status_code=403,
            detail="Only security group members can grant admin role",
        )


async def _refuse_admin_lockout(
    db: AsyncSession,
    user: User,
    update_data: dict[str, Any],
    current_user: User,
) -> None:
    """Server-side guards against losing admin access entirely (UX-02).

    Refuses, before anything is applied:
    - an admin demoting or deactivating THEMSELVES (400 — self-lockout; the
      change must come from another admin), and
    - demoting or deactivating the LAST active admin (409 — would leave the
      app with nobody able to administer it).

    The active-admin count runs on the same session/transaction as the
    update, so a concurrent demote can't slip past the check.
    """
    new_role = update_data.get("role")
    demotes = user.role == "admin" and new_role is not None and new_role != "admin"
    deactivates = bool(user.is_active) and update_data.get("is_active") is False
    if not (demotes or deactivates):
        return

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Admins cannot demote or deactivate themselves — "
                "ask another admin to make this change"
            ),
        )

    if user.role == "admin" and user.is_active:
        result = await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin")
            .where(User.is_active == True)  # noqa: E712
        )
        if (result.scalar_one() or 0) <= 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot demote or deactivate the last active admin — "
                    "grant another user the admin role first"
                ),
            )


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
            detail="Failed to search Entra ID users",
        ) from exc
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

    if data.role not in ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    # Prevent granting admin role unless the current user is in the security group
    if data.role == "admin":
        await _require_admin_grant_permission(current_user)

    # Fetch user details from Graph API
    try:
        graph_users = await get_graph_users_by_ids(data.user_ids)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch user details from Entra ID",
        ) from exc

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
            old_role = existing.role
            existing.is_active = True
            existing.role = data.role
            existing.display_name = display_name
            if email:
                existing.email = email
            if old_role != data.role:
                logger.info(
                    "AUDIT: User %s role changed from '%s' to '%s' by %s (%s)",
                    user_id,
                    old_role,
                    data.role,
                    current_user.id,
                    current_user.email,
                )
        else:
            new_user = User(
                entra_id=user_id,
                email=email,
                display_name=display_name,
                role=data.role,
                is_active=True,
            )
            db.add(new_user)
            logger.info(
                "AUDIT: New user %s granted role '%s' by %s (%s)",
                user_id,
                data.role,
                current_user.id,
                current_user.email,
            )

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
    request: Request,
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

    new_role = update_data.get("role")
    if new_role is not None:
        if new_role not in ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        # Same gate as grant-access: only security group members may set admin
        if new_role == "admin":
            await _require_admin_grant_permission(current_user)

    # Self-lockout / last-active-admin guards (UX-02) — before applying.
    await _refuse_admin_lockout(db, user, update_data, current_user)

    old_role = user.role
    old_is_active = user.is_active
    for key, value in update_data.items():
        setattr(user, key, value)

    if new_role is not None and new_role != old_role:
        logger.info(
            "AUDIT: User %s role changed from '%s' to '%s' by %s (%s)",
            user.entra_id,
            old_role,
            new_role,
            current_user.id,
            current_user.email,
        )

    await db.commit()
    await db.refresh(user)

    # Real audit rows for role/is_active changes (R-013) — the log lines
    # above are not queryable; the Audit Log UI reads audit_log rows.
    if user.role != old_role or user.is_active != old_is_active:
        await audit_service.record_audit(
            action="update",
            entity_type="user",
            user_id=current_user.id,
            entity_id=user.id,
            old_values={"role": old_role, "is_active": old_is_active},
            new_values={"role": user.role, "is_active": user.is_active},
            request=request,
        )
    return user


@router.patch("/{user_id}", response_model=UserResponse)
async def patch_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    request: Request,
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

    new_role = update_data.get("role")
    if new_role is not None:
        if new_role not in ROLES:
            raise HTTPException(status_code=400, detail="Invalid role")
        # Same gate as grant-access: only security group members may set admin
        if new_role == "admin":
            await _require_admin_grant_permission(current_user)

    # Self-lockout / last-active-admin guards (UX-02) — before applying.
    await _refuse_admin_lockout(db, user, update_data, current_user)

    old_role = user.role
    old_is_active = user.is_active
    for key, value in update_data.items():
        setattr(user, key, value)

    if new_role is not None and new_role != old_role:
        logger.info(
            "AUDIT: User %s role changed from '%s' to '%s' by %s (%s)",
            user.entra_id,
            old_role,
            new_role,
            current_user.id,
            current_user.email,
        )

    await db.commit()
    await db.refresh(user)

    # Real audit rows for role/is_active changes (R-013) — the log lines
    # above are not queryable; the Audit Log UI reads audit_log rows.
    if user.role != old_role or user.is_active != old_is_active:
        await audit_service.record_audit(
            action="update",
            entity_type="user",
            user_id=current_user.id,
            entity_id=user.id,
            old_values={"role": old_role, "is_active": old_is_active},
            new_values={"role": user.role, "is_active": user.is_active},
            request=request,
        )
    return user
