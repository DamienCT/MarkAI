import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services.notification_service import notify_failure
from app.services.publish_service import dispatch_to_n8n, publish_direct, resolve_media
from app.services.publishers.registry import get_publisher

logger = logging.getLogger(__name__)

# Content overdue by more than this is moved to "failed" instead of published.
STALE_THRESHOLD = timedelta(days=1)

# A direct publish stuck in "publishing" longer than this (crashed worker,
# lost event loop, backend restart mid-upload) is swept to "failed" so it can
# be retried via the failed→scheduled transition.
PUBLISHING_TIMEOUT = timedelta(minutes=30)

# At most this many direct publishes run concurrently — container status
# polls (IG Reels, LinkedIn video) can take minutes each.
MAX_CONCURRENT_DIRECT_PUBLISHES = 3

# In-flight direct publish tasks, kept referenced so they aren't garbage
# collected mid-flight; the done-callback discards finished tasks.
_direct_tasks: set[asyncio.Task] = set()
_direct_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DIRECT_PUBLISHES)


def _spawn_direct_publish(calendar_item_id: uuid.UUID, content_id: uuid.UUID) -> None:
    """Run a direct publish in a background task so a slow platform flow
    (e.g. a 5-minute container poll) never blocks the scheduler tick."""
    task = asyncio.create_task(_run_direct_publish(calendar_item_id, content_id))
    _direct_tasks.add(task)
    task.add_done_callback(_direct_tasks.discard)


async def _run_direct_publish(
    calendar_item_id: uuid.UUID, content_id: uuid.UUID
) -> None:
    """Execute one direct publish under the concurrency cap.

    Opens its own session (the tick's session is closed by the time this
    runs) and re-loads the rows by id. The calendar item was already moved to
    'publishing' by the tick, so the due query won't pick it up again.
    """
    async with _direct_semaphore:
        started_at = datetime.now(timezone.utc)
        try:
            async with async_session_factory() as db:
                item_result = await db.execute(
                    select(CalendarItem)
                    .where(CalendarItem.id == calendar_item_id)
                    .options(selectinload(CalendarItem.brand))
                )
                calendar_item = item_result.scalar_one_or_none()
                content_result = await db.execute(
                    select(Content).where(Content.id == content_id)
                )
                content = content_result.scalar_one_or_none()
                if calendar_item is None or content is None:
                    logger.warning(
                        "Direct publish skipped — calendar item %s / content %s "
                        "no longer exists",
                        calendar_item_id,
                        content_id,
                    )
                    return
                if calendar_item.status != "publishing":
                    # The stuck-'publishing' sweep (or a user action) changed
                    # the status while this task waited on the semaphore —
                    # publishing anyway would clobber that state and could
                    # duplicate a rescheduled post.
                    logger.warning(
                        "Direct publish skipped — calendar item %s status is "
                        "'%s' (expected 'publishing')",
                        calendar_item_id,
                        calendar_item.status,
                    )
                    return

                outcome = await publish_direct(
                    db, content, calendar_item, calendar_item.brand
                )

                details: dict = {
                    "content_id": str(content_id),
                    "channel": calendar_item.channel,
                }
                if outcome.platform_post_id:
                    details["platform_post_id"] = outcome.platform_post_id
                if outcome.error:
                    details["error"] = outcome.error
                log = ScheduledJobLog(
                    job_name="publish_direct",
                    job_type="publish",
                    status="completed" if outcome.status == "published" else "failed",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    details=details,
                )
                db.add(log)
                await db.commit()

                if outcome.status != "published":
                    await notify_failure(
                        "publish_direct",
                        content,
                        Exception(outcome.error or "publish failed"),
                    )
        except Exception:
            logger.exception(
                "Direct publish task for calendar item %s crashed", calendar_item_id
            )
            # Best effort: fail the item now instead of waiting for the
            # PUBLISHING_TIMEOUT sweep.
            try:
                async with async_session_factory() as db:
                    item_result = await db.execute(
                        select(CalendarItem).where(CalendarItem.id == calendar_item_id)
                    )
                    calendar_item = item_result.scalar_one_or_none()
                    if calendar_item is not None and calendar_item.status == "publishing":
                        calendar_item.status = "failed"
                        await db.commit()
            except Exception:
                logger.exception(
                    "Could not mark calendar item %s as failed", calendar_item_id
                )


async def check_due_content() -> None:
    """
    Every N minutes: query PostgreSQL for calendar items with status='scheduled'
    and scheduled_at <= now. Items overdue by more than STALE_THRESHOLD are marked
    failed (stale content shouldn't be posted). Items with a direct in-backend
    publisher move to 'publishing' and run in a background task; the rest are
    dispatched to n8n.
    """
    logger.info("Checking for due content to publish")

    async with async_session_factory() as db:
        now = datetime.now(timezone.utc)

        # Sweep items stuck in 'publishing' (direct task crashed or the
        # backend restarted mid-upload) so they become retryable.
        stuck_result = await db.execute(
            select(CalendarItem)
            .where(CalendarItem.status == "publishing")
            .where(CalendarItem.updated_at < now - PUBLISHING_TIMEOUT)
        )
        stuck_items = stuck_result.scalars().all()
        for item in stuck_items:
            item.status = "failed"
            logger.warning(
                "Calendar item %s stuck in 'publishing' for over %s — marking failed",
                item.id,
                PUBLISHING_TIMEOUT,
            )
        if stuck_items:
            await db.commit()
            for item in stuck_items:
                await notify_failure(
                    "publish_stuck_sweep",
                    item,
                    Exception(
                        f"Calendar item {item.id} ('{item.title}', "
                        f"{item.channel}) stuck in 'publishing' for over "
                        f"{PUBLISHING_TIMEOUT} — marked failed"
                    ),
                )

        # Only 'scheduled' items are due — items an in-flight direct task
        # already moved to 'publishing' are naturally skipped here.
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
        stale_items = []
        for item in due_items:
            if item.scheduled_at and item.scheduled_at < stale_cutoff:
                item.status = "failed"
                stale_items.append(item)
                logger.warning(
                    "Calendar item %s expired — scheduled_at %s is over %s overdue",
                    item.id, item.scheduled_at, STALE_THRESHOLD,
                )
            else:
                fresh_items.append(item)

        if stale_items:
            await db.commit()
            for item in stale_items:
                await notify_failure(
                    "publish_stale_expiry",
                    item,
                    Exception(
                        f"Calendar item {item.id} ('{item.title}', "
                        f"{item.channel}) expired — scheduled_at "
                        f"{item.scheduled_at} is over {STALE_THRESHOLD} "
                        f"overdue; marked failed instead of published"
                    ),
                )

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

            # ── Direct in-backend publisher path ────────────────────────
            # Supported channel/media combinations publish straight from the
            # backend: mark 'publishing' now (so the next tick skips the
            # item) and run the platform flow in a background task.
            media = resolve_media(content, calendar_item)
            if get_publisher(calendar_item.channel, media.kind) is not None:
                calendar_item.status = "publishing"
                await db.commit()
                _spawn_direct_publish(calendar_item.id, content.id)
                logger.info(
                    "Spawned direct publish of content %s to %s (%s)",
                    content.id,
                    calendar_item.channel,
                    media.kind,
                )
                continue

            # ── n8n fallback path (teams, website_blog, x, tiktok, …) ───
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
