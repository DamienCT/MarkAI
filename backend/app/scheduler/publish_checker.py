import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services.notification_service import notify_failure
from app.services.publish_service import dispatch_to_n8n

logger = logging.getLogger(__name__)


async def check_due_content() -> None:
    """
    Every N minutes: query PostgreSQL for calendar items with status='scheduled'
    and scheduled_at <= now. For each, dispatch the current content to the n8n
    publish webhook for the correct platform.
    """
    logger.info("Checking for due content to publish")

    async with async_session_factory() as db:
        result = await db.execute(
            select(CalendarItem)
            .where(CalendarItem.status == "scheduled")
            .where(CalendarItem.scheduled_at <= func.now())
            .options(
                selectinload(CalendarItem.content_items),
                selectinload(CalendarItem.brand),
            )
        )

        due_items = result.scalars().all()

        if not due_items:
            logger.debug("No due content found")
            return

        logger.info("Found %d calendar items due for publishing", len(due_items))

        for calendar_item in due_items:
            # Get the current content version for this calendar item
            content_result = await db.execute(
                select(Content)
                .where(Content.calendar_item_id == calendar_item.id)
                .where(Content.is_current == True)  # noqa: E712
                .options(selectinload(Content.brand))
            )
            content = content_result.scalar_one_or_none()
            if content is None:
                logger.warning(
                    "No current content for calendar item %s", calendar_item.id
                )
                continue

            brand = content.brand

            try:
                # Keep status as "scheduled" during dispatch — n8n callback
                # will set it to "published" or "failed" directly.
                await dispatch_to_n8n(content, calendar_item, brand)

                log = ScheduledJobLog(
                    job_name="publish_dispatch",
                    job_type="publish",
                    status="completed",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    details={
                        "content_id": str(content.id),
                        "channel": calendar_item.channel,
                    },
                )
                db.add(log)
                await db.commit()

                logger.info(
                    "Dispatched content %s to %s",
                    content.id,
                    calendar_item.channel,
                )
            except Exception as e:
                # Mark as failed so it can be retried via failed→scheduled transition
                calendar_item.status = "failed"
                await db.commit()
                logger.error(
                    "Publish dispatch failed for content %s: %s",
                    content.id,
                    e,
                )
                log = ScheduledJobLog(
                    job_name="publish_dispatch",
                    job_type="publish",
                    status="failed",
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                    details={
                        "content_id": str(content.id),
                        "error": str(e),
                    },
                )
                db.add(log)
                await db.commit()

                await notify_failure("publish_dispatch", content, e)
