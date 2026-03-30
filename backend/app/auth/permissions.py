from fastapi import HTTPException, status

ROLES = {
    "admin": 100,
    "manager": 80,
    "editor": 60,
    "viewer": 10,
}

# Backward-compatible alias — previously a redundant copy of ROLES
ROLE_HIERARCHY = ROLES


def role_has_access(user_role: str, required_role: str) -> bool:
    """Check if a user role has at least the required permission level."""
    user_level = ROLES.get(user_role, 0)
    required_level = ROLES.get(required_role, 999)
    return user_level >= required_level


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
