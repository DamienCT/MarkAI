import functools
from typing import Callable

from fastapi import HTTPException, status

ROLES = {
    "admin": 100,
    "manager": 80,
    "editor": 60,
    "viewer": 10,
}

ROLE_HIERARCHY = {role: level for role, level in ROLES.items()}


def role_has_access(user_role: str, required_role: str) -> bool:
    """Check if a user role has at least the required permission level."""
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    required_level = ROLE_HIERARCHY.get(required_role, 999)
    return user_level >= required_level


def require_role(required_role: str) -> Callable:
    """
    Dependency-compatible decorator that checks user role.
    Use as: @require_role("brand_manager") on route handlers
    where the handler receives current_user from deps.get_current_user.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get("current_user")
            if current_user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                )
            if not role_has_access(current_user.role, required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role '{current_user.role}' does not have "
                    f"'{required_role}' access",
                )
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_role_dependency(required_role: str):
    """
    FastAPI Depends-compatible role checker.
    Usage: Depends(require_role_dependency("brand_manager"))
    """
    from app.auth.models import User

    async def _check(current_user: "User"):
        if not role_has_access(current_user.role, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' does not have "
                f"'{required_role}' access",
            )
        return current_user

    return _check
