from fastapi import APIRouter

from app.api.v1 import (
    agents,
    analytics,
    approvals,
    brands,
    calendar,
    campaigns,
    content,
    dashboard,
    events,
    files,
    intelligence,
    learning,
    notifications,
    products,
    prompts,
    providers,
    settings,
    system,
    users,
    webhooks,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(brands.router, prefix="/brands", tags=["brands"])
api_router.include_router(content.router, prefix="/content", tags=["content"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
api_router.include_router(providers.router, prefix="/providers", tags=["providers"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(
    intelligence.router, prefix="/intelligence", tags=["intelligence"]
)
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
api_router.include_router(learning.router, prefix="/learning", tags=["learning"])
api_router.include_router(files.router, prefix="/files", tags=["files"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(events.router, prefix="/events", tags=["events"])

# Alias: frontend calls /api/v1/audit directly — redirects to system/audit-log
from fastapi import Depends  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402
from app.deps import get_current_user, get_db  # noqa: E402
from app.auth.models import AuditLog, User  # noqa: E402
from app.auth.permissions import role_has_access  # noqa: E402
from fastapi import HTTPException  # noqa: E402


@api_router.get("/audit", tags=["system"])
async def list_audit_log(
    page: int = 1,
    limit: int = 50,
    action: str | None = None,
    resource_type: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not role_has_access(current_user.role, "manager"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    limit = min(limit, 200)
    offset = (page - 1) * limit
    # Join the user so the UI can show a name instead of a bare UUID.
    stmt = (
        select(AuditLog, User.email)
        .outerjoin(User, AuditLog.user_id == User.id)
        .order_by(AuditLog.created_at.desc())
    )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:  # frontend's "resource_type" maps to entity_type
        stmt = stmt.where(AuditLog.entity_type == resource_type)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(AuditLog.action.ilike(like) | AuditLog.entity_type.ilike(like))
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [
        {
            "id": str(row.id),
            "user_id": str(row.user_id) if row.user_id else None,
            "user_name": email,
            "action": row.action,
            # Expose under the names the Audit Log UI reads.
            "resource_type": row.entity_type,
            "resource_id": str(row.entity_id) if row.entity_id else None,
            "ip_address": str(row.ip_address) if row.ip_address else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row, email in result.all()
    ]

# NOTE: the DELETE /audit hard-wipe endpoint was deliberately removed
# (P0-11): the audit log is append-only evidence — an admin-reachable,
# itself-unaudited wipe made every other audit record untrustworthy.
# Retention/purge, if ever needed, must be a separately audited,
# break-glass operation — not an API endpoint.
