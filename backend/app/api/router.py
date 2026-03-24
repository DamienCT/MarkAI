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
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])

# Alias: frontend calls /api/v1/audit directly
from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.deps import get_current_user, get_db
from app.auth.models import AuditLog, User


@api_router.get("/audit", tags=["system"])
async def list_audit_log(
    page: int = 1,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * limit
    result = await db.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    )
    return [
        {
            "id": str(row.id),
            "user_id": str(row.user_id) if row.user_id else None,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id) if row.entity_id else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in result.scalars().all()
    ]
