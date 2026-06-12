import logging
import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Notification, User
from app.config import settings
from app.models.base import async_session_factory

logger = logging.getLogger(__name__)


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    channel: str = "in_app",
) -> Notification:
    """Create an in-app notification record."""
    notif = Notification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        body=body,
        channel=channel,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return notif


async def notify_admins(
    db: AsyncSession,
    notification_type: str,
    title: str,
    body: str | None = None,
    reference_type: str | None = None,
    reference_id: uuid.UUID | None = None,
    roles: tuple[str, ...] = ("admin", "manager"),
) -> int:
    """Create the same in-app notification for every user with one of `roles`.

    Used for brand-level alerts that should reach the team regardless of who
    (if anyone) owns the brand — brands with a NULL created_by would otherwise
    notify nobody. Returns the number of recipients.
    """
    result = await db.execute(select(User.id).where(User.role.in_(roles)))
    ids = [row[0] for row in result.all()]
    for uid in ids:
        await create_notification(
            db=db,
            user_id=uid,
            notification_type=notification_type,
            title=title,
            body=body,
            reference_type=reference_type,
            reference_id=reference_id,
        )
    return len(ids)


async def send_teams_message(title: str, text: str, color: str = "0076D7") -> None:
    """Send a message to the configured Microsoft Teams webhook."""
    if not settings.TEAMS_WEBHOOK_URL:
        logger.warning("TEAMS_WEBHOOK_URL not configured, skipping Teams notification")
        return

    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": title,
        "sections": [
            {
                "activityTitle": title,
                "text": text,
                "markdown": True,
            }
        ],
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(settings.TEAMS_WEBHOOK_URL, json=payload)
        resp.raise_for_status()

    logger.info("Teams message sent: %s", title)


async def notify_failure(job_name: str, entity: Any, error: Exception) -> None:
    """
    Send failure alerts to Teams and create in-app notifications for admins.
    Replaces n8n error handler workflow.
    """
    error_text = f"**Job:** {job_name}\n\n**Error:** {str(error)}"

    # Teams
    try:
        await send_teams_message(
            title=f"MARKAI Alert: {job_name} failed",
            text=error_text,
            color="FF0000",
        )
    except Exception:
        logger.error("Teams notification failed", exc_info=True)

    # In-app notification for all admins
    async with async_session_factory() as db:
        admins = await db.execute(
            select(User).where(User.role.in_(["admin", "manager"]))
        )
        for admin in admins.scalars():
            await create_notification(
                db,
                admin.id,
                "system",
                f"Job '{job_name}' failed",
                str(error),
            )


async def notify_approval_requested(
    db: AsyncSession,
    reviewer_id: uuid.UUID,
    content_id: uuid.UUID,
    requester_name: str,
) -> None:
    """Notify a user that an approval is pending."""
    await create_notification(
        db,
        reviewer_id,
        "approval_request",
        f"Approval requested by {requester_name}",
        "Please review the content.",
        reference_type="content",
        reference_id=content_id,
    )

    # Also notify via Teams
    try:
        await send_teams_message(
            title="Approval Needed",
            text=f"**{requester_name}** requested approval for content. Review in the MARKAI portal.",
        )
    except Exception:
        logger.error("Teams approval notification failed", exc_info=True)
