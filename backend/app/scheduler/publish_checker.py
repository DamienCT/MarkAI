import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services.notification_service import notify_failure
from app.services.publish_service import (
    PublishingDisabledError,
    is_publishing_enabled,
    publish_direct,
)

logger = logging.getLogger(__name__)

# Content overdue by more than this is moved to "failed" instead of published.
STALE_THRESHOLD = timedelta(days=1)

# A publish stuck in "publishing" longer than this (crashed task, lost event
# loop, backend restart mid-upload) is swept to "failed" with an
# "unreconciled" note. NEVER auto-retried: the post may have reached the
# platform, so an operator must verify there before re-scheduling.
PUBLISHING_TIMEOUT = timedelta(minutes=45)

# Note stamped on swept items (shown in generation_metadata.publish_note).
UNRECONCILED_NOTE = "unreconciled — verify on platform before re-scheduling"

# At most this many direct publishes run concurrently — container status
# polls (IG Reels, LinkedIn video) can take minutes each.
MAX_CONCURRENT_DIRECT_PUBLISHES = 3

# In-flight direct publish tasks, kept referenced so they aren't garbage
# collected mid-flight; the done-callback discards finished tasks.
_direct_tasks: set[asyncio.Task] = set()
_direct_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DIRECT_PUBLISHES)


async def _claim_for_publishing(db, calendar_item_id: uuid.UUID) -> bool:
    """Atomically claim a due item for dispatch: scheduled → publishing.

    Compare-and-set so a concurrent scheduler (second process/replica) or an
    in-flight task can never dispatch the same item twice — the item leaves
    'scheduled' before ANY external call. Returns False when another process
    already claimed it.
    """
    result = await db.execute(
        update(CalendarItem)
        .where(CalendarItem.id == calendar_item_id)
        .where(CalendarItem.status == "scheduled")
        .values(status="publishing")
        .returning(CalendarItem.id)
    )
    await db.commit()
    return result.scalar_one_or_none() is not None


async def _release_claim(db, calendar_item_id: uuid.UUID) -> None:
    """Return a claimed-but-never-dispatched item to 'scheduled'.

    Only valid when NO external call was made (kill switch engaged before
    dispatch) — anything after a dispatch attempt must go through the
    recorded outcome / failed path instead.
    """
    await db.execute(
        update(CalendarItem)
        .where(CalendarItem.id == calendar_item_id)
        .where(CalendarItem.status == "publishing")
        .values(status="scheduled")
    )
    await db.commit()


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

                try:
                    outcome = await publish_direct(
                        db, content, calendar_item, calendar_item.brand
                    )
                except PublishingDisabledError:
                    # Kill switch engaged after the claim but before any
                    # external call — release the claim so the item publishes
                    # once the switch is re-enabled.
                    await _release_claim(db, calendar_item_id)
                    logger.warning(
                        "Publishing kill switch engaged — released claim on "
                        "calendar item %s (nothing was dispatched)",
                        calendar_item_id,
                    )
                    return

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
    failed (stale content shouldn't be posted). Every due item is claimed
    (scheduled → publishing) and published natively in a background task —
    channels without a registered publisher fail with an actionable error
    inside ``publish_direct``.
    """
    logger.info("Checking for due content to publish")

    async with async_session_factory() as db:
        # Kill switch — checked at sweep start; when engaged the whole tick
        # is frozen (no dispatch, no state changes) until re-enabled.
        if not await is_publishing_enabled(db):
            logger.warning(
                "Publishing kill switch is engaged — skipping publish sweep"
            )
            return

        now = datetime.now(timezone.utc)

        # Sweep items stuck in 'publishing' (task crashed, backend restarted
        # mid-upload). Marked failed with an 'unreconciled' note — NEVER
        # auto-retried, because the post may have reached the platform; an
        # operator must verify there before re-scheduling
        # (reconcile-before-retry).
        stuck_result = await db.execute(
            select(CalendarItem)
            .where(CalendarItem.status == "publishing")
            .where(CalendarItem.updated_at < now - PUBLISHING_TIMEOUT)
        )
        stuck_items = stuck_result.scalars().all()
        for item in stuck_items:
            item.status = "failed"
            item.generation_metadata = {
                **(item.generation_metadata or {}),
                "publish_note": UNRECONCILED_NOTE,
            }
            logger.warning(
                "Calendar item %s stuck in 'publishing' for over %s — marking "
                "failed (%s)",
                item.id,
                PUBLISHING_TIMEOUT,
                UNRECONCILED_NOTE,
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
                        f"{PUBLISHING_TIMEOUT} — marked failed; "
                        f"{UNRECONCILED_NOTE}"
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
            # Kill switch — re-checked before every dispatch so an operator
            # flip mid-tick stops the remaining items (they stay scheduled).
            if not await is_publishing_enabled(db):
                logger.warning(
                    "Publishing kill switch engaged mid-tick — leaving "
                    "remaining due items scheduled"
                )
                break

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

            # ── Single dispatch path: native in-backend publishers ──────
            # Atomically claim (scheduled → publishing, so no other tick/
            # process picks the item up) and run the platform flow in a
            # background task. ``publish_direct`` resolves the publisher from
            # the registry; unsupported channel/media combinations fail with
            # an actionable error instead of silently queuing.
            if not await _claim_for_publishing(db, calendar_item.id):
                logger.info(
                    "Calendar item %s already claimed elsewhere — skipping",
                    calendar_item.id,
                )
                continue
            _spawn_direct_publish(calendar_item.id, content.id)
            logger.info(
                "Spawned direct publish of content %s to %s",
                content.id,
                calendar_item.channel,
            )
