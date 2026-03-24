import logging
from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.entra import extract_groups, validate_entra_token
from app.auth.models import User
from app.config import settings
from app.models.base import async_session_factory

logger = logging.getLogger(__name__)

# In dev mode, make the bearer token optional so unauthenticated
# requests fall through to the dev user path.
security = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def _get_or_create_dev_user(db: AsyncSession) -> User:
    """Return a dev admin user, creating it if it doesn't exist."""
    result = await db.execute(select(User).where(User.entra_id == "dev-admin"))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            entra_id="dev-admin",
            email="admin@localhost",
            display_name="Dev Admin",
            role="admin",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Validate the Entra ID JWT and return the corresponding User record.
    Creates the user on first login if they don't exist yet.

    In development mode (MARKAI_ENV=development), if no token is provided,
    returns a dev admin user so the UI can be used without Entra ID.

    In production mode:
    - JWT must be valid
    - If the user's groups claim contains ADMIN_SECURITY_GROUP_ID,
      auto-provision as admin with is_active=True
    - Otherwise, check DB is_active flag; new users without the security
      group are provisioned as viewer with is_active=False (pending approval)
    """
    # Dev mode: no token provided -> return dev admin user
    if credentials is None or not credentials.credentials:
        if settings.MARKAI_ENV == "development":
            return await _get_or_create_dev_user(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        claims = await validate_entra_token(token)
    except Exception as exc:
        # In dev mode, if token validation fails, fall back to dev user
        if settings.MARKAI_ENV == "development":
            logger.info("Dev mode: JWT validation failed, using dev user")
            return await _get_or_create_dev_user(db)
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
