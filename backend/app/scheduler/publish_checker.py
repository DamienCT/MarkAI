import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services.notification_service import notify_failure
from app.services.publish_service import dispatch_to_n8n

logger = logging.getLogger(__name__)

# Content overdue by more than this is moved to "failed" instead of published.
STALE_THRESHOLD = timedelta(days=1)


async def check_due_content() -> None:
    """
    Every N minutes: query PostgreSQL for calendar items with status='scheduled'
    and scheduled_at <= now. Items overdue by more than STALE_THRESHOLD are marked
    failed (stale content shouldn't be posted). The rest are dispatched to n8n.
    """
    logger.info("Checking for due content to publish")

    async with async_session_factory() as db:
        now = datetime.now(timezone.utc)

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

        # Expire stale items (overdue by more than 1 day)
        stale_cutoff = now - STALE_THRESHOLD
        fresh_items = []
        for item in due_items:
            if item.scheduled_at and item.scheduled_at < stale_cutoff:
                item.status = "failed"
                logger.warning(
                    "Calendar item %s expired — scheduled_at %s is over %s overdue",
                    item.id, item.scheduled_at, STALE_THRESHOLD,
                )
            else:
                fresh_items.append(item)

        if fresh_items != due_items:
            await db.commit()

        for calendar_item in fresh_items:
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
                # will set it to "published" or "failed" directly. Channels
                # WITHOUT a callback (teams posts directly, website_blog is
                # manual) must transition here or they re-dispatch every tick
                # (Teams used to re-post the same message every 5 minutes).
                dispatch_result = await dispatch_to_n8n(content, calendar_item, brand)
                result_status = (dispatch_result or {}).get("status")
                if result_status == "published":
                    calendar_item.status = "published"
                    calendar_item.published_at = datetime.now(timezone.utc)
                elif result_status == "ready_to_publish":
                    # Manual channel — park it back in review so it stops
                    # being picked up as due.
                    calendar_item.status = "in_review"

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
