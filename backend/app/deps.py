import logging
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import (
    check_user_in_security_group,
    extract_groups,
    validate_entra_token,
)
from app.auth.models import User
from app.config import settings
from app.models.base import async_session_factory

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=True)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate the Entra ID JWT and return the corresponding User record.
    Creates the user on first login if they don't exist yet.

    - JWT must be valid (issued by our Entra ID tenant)
    - If the user's groups claim contains ADMIN_SECURITY_GROUP_ID,
      auto-provision as admin with is_active=True
    - Else if it contains MARKETING_SECURITY_GROUP_ID, auto-provision
      as manager with is_active=True
    - Otherwise, check DB is_active flag; new users without any security
      group are provisioned as viewer with is_active=False (pending approval)
    - Activation-by-group applies ONLY at first provisioning: group
      membership never flips is_active back to True on an existing row, so
      a manual deactivation sticks (N-03)
    """
    token = credentials.credentials
    try:
        claims = await validate_entra_token(token)
    except Exception as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    entra_id = claims.get("oid") or claims.get("sub")
    if not entra_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier",
        )

    # Check security group membership.
    # First try JWT groups claim (fast, if app registration emits group claims)
    groups = extract_groups(claims)
    in_admin_group = (
        bool(settings.ADMIN_SECURITY_GROUP_ID)
        and settings.ADMIN_SECURITY_GROUP_ID in groups
    )
    in_marketing_group = (
        bool(settings.MARKETING_SECURITY_GROUP_ID)
        and settings.MARKETING_SECURITY_GROUP_ID in groups
    )
    # Fallback: check via Graph API (works even without group claims in token)
    if not in_admin_group and settings.ADMIN_SECURITY_GROUP_ID:
        try:
            in_admin_group = await check_user_in_security_group(
                entra_id, settings.ADMIN_SECURITY_GROUP_ID
            )
        except Exception as exc:
            logger.warning("Graph API admin group check failed: %s", exc)
    if not in_marketing_group and settings.MARKETING_SECURITY_GROUP_ID:
        try:
            in_marketing_group = await check_user_in_security_group(
                entra_id, settings.MARKETING_SECURITY_GROUP_ID
            )
        except Exception as exc:
            logger.warning("Graph API marketing group check failed: %s", exc)

    # Admin takes precedence over marketing
    if in_admin_group:
        provisioned_role: str | None = "admin"
    elif in_marketing_group:
        provisioned_role = "manager"
    else:
        provisioned_role = None

    result = await db.execute(select(User).where(User.entra_id == entra_id))
    user = result.scalar_one_or_none()

    if user is None:
        if provisioned_role is not None:
            # Auto-provision security group members as active users
            user = User(
                entra_id=entra_id,
                email=claims.get("preferred_username", claims.get("email", "")),
                display_name=claims.get("name", "Unknown"),
                role=provisioned_role,
                is_active=True,
            )
        else:
            # Non-group users are provisioned as inactive viewers (pending approval)
            user = User(
                entra_id=entra_id,
                email=claims.get("preferred_username", claims.get("email", "")),
                display_name=claims.get("name", "Unknown"),
                role="viewer",
                is_active=False,
            )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        # Existing user: keep the group-derived ROLE in sync, but never touch
        # is_active — group membership must not silently reactivate a user an
        # admin deactivated (N-03). Activation-by-group only applies at first
        # provisioning above; a deactivated user still fails the gate below.
        if in_admin_group and user.role != "admin":
            user.role = "admin"
            await db.commit()
            await db.refresh(user)
        elif in_marketing_group and user.role in ("viewer", "editor"):
            # Upgrade lower roles to manager. Never downgrade admin.
            user.role = "manager"
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is pending approval. Contact an administrator.",
        )

    return user
