import asyncio
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Notification, User
from app.deps import get_current_user, get_db
from app.models.base import async_session_factory

router = APIRouter()


def _serialize_notification(n: Notification) -> dict:
    return {
        "id": str(n.id),
        "notification_type": n.notification_type,
        "title": n.title,
        "body": n.body,
        "channel": n.channel,
        "reference_type": n.reference_type,
        "reference_id": str(n.reference_id) if n.reference_id else None,
        "is_read": n.is_read,
        "read_at": n.read_at.isoformat() if n.read_at else None,
        "sent_at": n.sent_at.isoformat() if n.sent_at else None,
        "created_at": n.created_at.isoformat(),
    }


@router.get("/")
async def list_notifications(
    read: bool | None = Query(None),
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return notifications for the current user, optionally filtered by read status."""
    limit = min(limit, 200)
    stmt = (
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    if read is not None:
        stmt = stmt.where(Notification.is_read == read)

    result = await db.execute(stmt)
    notifications = result.scalars().all()

    return [_serialize_notification(n) for n in notifications]


@router.get("/stream")
async def stream_notifications(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """SSE endpoint that streams unread notifications every 10 seconds."""

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            async with async_session_factory() as db:
                stmt = (
                    select(Notification)
                    .where(Notification.user_id == current_user.id)
                    .where(Notification.is_read == False)  # noqa: E712
                    .order_by(Notification.created_at.desc())
                    .limit(50)
                )
                result = await db.execute(stmt)
                notifications = result.scalars().all()

            payload = json.dumps(
                {
                    "notifications": [
                        _serialize_notification(n) for n in notifications
                    ],
                    "unread_count": len(notifications),
                }
            )
            yield f"data: {payload}\n\n"

            await asyncio.sleep(10)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
