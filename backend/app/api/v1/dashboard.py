from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.deps import get_current_user, get_db

router = APIRouter()


@router.get("/stats")
async def dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate dashboard statistics."""
    total_brands = (await db.execute(text("SELECT count(*) FROM brands"))).scalar() or 0
    total_content = (await db.execute(text("SELECT count(*) FROM content"))).scalar() or 0
    pending_approvals = (
        await db.execute(text("SELECT count(*) FROM approvals WHERE status = 'pending'"))
    ).scalar() or 0
    scheduled_posts = (
        await db.execute(
            text("SELECT count(*) FROM calendar_items WHERE status = 'scheduled'")
        )
    ).scalar() or 0
    published_this_week = (
        await db.execute(
            text(
                "SELECT count(*) FROM calendar_items "
                "WHERE status = 'published' AND published_at >= now() - interval '7 days'"
            )
        )
    ).scalar() or 0
    active_workflows = (
        await db.execute(
            text("SELECT count(*) FROM agent_runs WHERE status = 'running'")
        )
    ).scalar() or 0

    return {
        "total_brands": total_brands,
        "total_content": total_content,
        "pending_approvals": pending_approvals,
        "scheduled_posts": scheduled_posts,
        "published_this_week": published_this_week,
        "active_workflows": active_workflows,
    }
