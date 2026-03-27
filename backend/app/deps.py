import logging
from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import extract_groups, validate_entra_token
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
    - Otherwise, check DB is_active flag; new users without the security
      group are provisioned as viewer with is_active=False (pending approval)
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

    # Check if user belongs to the admin security group via JWT groups claim
    groups = extract_groups(claims)
    in_security_group = (
        bool(settings.ADMIN_SECURITY_GROUP_ID)
        and settings.ADMIN_SECURITY_GROUP_ID in groups
    )

    result = await db.execute(select(User).where(User.entra_id == entra_id))
    user = result.scalar_one_or_none()

    if user is None:
        if in_security_group:
            # Auto-provision security group members as active admins
            user = User(
                entra_id=entra_id,
                email=claims.get("preferred_username", claims.get("email", "")),
                display_name=claims.get("name", "Unknown"),
                role="admin",
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
        # Existing user: if they are in the security group, ensure active + admin
        if in_security_group and (not user.is_active or user.role != "admin"):
            user.is_active = True
            user.role = "admin"
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is pending approval. Contact an administrator.",
        )

    return user
