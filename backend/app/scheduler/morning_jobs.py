import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.services import nats_service
from app.services.notification_service import notify_admins, notify_failure

logger = logging.getLogger(__name__)

# Module-level dict to track job start times for duration calculation
_job_start_times: dict[str, datetime] = {}


async def _log_job(
    job_name: str, status: str, error_message: str | None = None
) -> None:
    now = datetime.now(timezone.utc)
    duration_ms = None
    completed_at = None
    started_at = now  # default for "started" entries

    if status == "started":
        _job_start_times[job_name] = now
    else:
        completed_at = now
        recorded_start = _job_start_times.pop(job_name, None)
        if recorded_start is not None:
            started_at = recorded_start
            duration_ms = int((now - recorded_start).total_seconds() * 1000)

    async with async_session_factory() as db:
        log = ScheduledJobLog(
            job_name=job_name,
            job_type="scheduled",
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        db.add(log)
        await db.commit()


async def run_morning_jobs() -> None:
    """
    Morning orchestrator: runs BC sync, engagement pull,
    and emits evaluation.trigger to NATS.
    """
    logger.info("Starting morning jobs")
    await _log_job("morning_jobs", "started")

    # 1. BC product sync
    try:
        from app.scheduler.bc_sync import sync_bc_products

        await sync_bc_products()
    except Exception as e:
        logger.error("BC sync failed in morning jobs: %s", e)
        await notify_failure("morning_jobs.bc_sync", None, e)

    # 2. Engagement pull
    try:
        from app.scheduler.engagement_puller import pull_all_engagement

        await pull_all_engagement()
    except Exception as e:
        logger.error("Engagement pull failed in morning jobs: %s", e)
        await notify_failure("morning_jobs.engagement_pull", None, e)

    # 3. Emit evaluation trigger to NATS — one per active brand (the agents
    # worker requires brand_id; a brandless trigger can never create a run).
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT id FROM brands WHERE status = 'active'")
            )
            active_brand_ids = [str(row[0]) for row in result.all()]

        for brand_id in active_brand_ids:
            await nats_service.publish(
                "evaluation.trigger",
                {
                    "brand_id": brand_id,
                    "triggered_by": "morning_jobs",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
        logger.info(
            "Emitted evaluation.trigger for %d active brand(s)", len(active_brand_ids)
        )
    except Exception as e:
        logger.error("NATS evaluation trigger failed: %s", e)
        await notify_failure("morning_jobs.evaluation_trigger", None, e)

    # 4. Daily content top-up — generate content for upcoming calendar items
    try:
        await _topup_content_generation()
    except Exception as e:
        logger.error("Content top-up failed in morning jobs: %s", e)
        await notify_failure("morning_jobs.content_topup", None, e)

    # 5. Runway alert — ping brand owners 2 days before their last scheduled
    # post runs out, so they have time to plan/generate more content.
    try:
        await _runway_alert()
    except Exception as e:
        logger.error("Runway alert failed: %s", e)
        await notify_failure("morning_jobs.runway_alert", None, e)

    # 6. Stuck-in-review alert — nudge owners when posts have been sitting
    # in `in_review` for more than 48h.
    try:
        await _stuck_in_review_alert()
    except Exception as e:
        logger.error("Stuck-in-review alert failed: %s", e)
        await notify_failure("morning_jobs.stuck_in_review_alert", None, e)

    await _log_job("morning_jobs", "completed")
    logger.info("Morning jobs completed")


# Per-run cap on top-up messages. The morning job is the only AUTOMATIC retry
# path for queued items (a backend redeploy drops the in-flight NATS queue),
# and it fires once a day. The agents worker consumes content.generate
# sequentially with a 92-minute per-item ack budget, so ~15 worst-case items
# fit between two morning runs; 10 leaves headroom for the activation-chain
# traffic sharing the same consumer while still draining a dropped backlog
# within a couple of mornings.
_TOPUP_BATCH_LIMIT = 10


async def _topup_content_generation() -> None:
    """
    Trigger content generation for calendar items still in 'queued' status,
    oldest scheduled_at first, up to _TOPUP_BATCH_LIMIT per run.

    The window deliberately has NO lower bound: a past-due queued item is
    exactly the failure this job exists to heal (redeploy-dropped queue,
    exhausted video nak retries) — the old future-only BETWEEN window meant
    those items were never retried automatically. Items already generated are
    ack-skipped by the worker's regeneration guard, and duplicate-run drops
    are retried the next morning since past-due items now qualify again.
    """
    from app.scheduler import get_app_setting

    days_ahead = await get_app_setting("content_generation_days_ahead", default=14)
    try:
        days_ahead = int(days_ahead)
    except (TypeError, ValueError):
        days_ahead = 14

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, brand_id, title, scheduled_at "
                "FROM calendar_items "
                "WHERE status = 'queued' "
                "  AND scheduled_at IS NOT NULL "
                "  AND scheduled_at <= :horizon "
                "ORDER BY scheduled_at ASC "
                "LIMIT :batch_limit"
            ),
            {"horizon": horizon, "batch_limit": _TOPUP_BATCH_LIMIT},
        )
        rows = result.all()

    if not rows:
        logger.info(
            "Content top-up: no queued items due or within %d-day window", days_ahead
        )
        return

    for calendar_item_id, brand_id, title, scheduled_at in rows:
        logger.info(
            "Content top-up: triggering generation for calendar item %s (%s) scheduled at %s",
            calendar_item_id,
            title,
            scheduled_at,
        )
        await nats_service.publish(
            "content.generate",
            {
                "brand_id": str(brand_id),
                "calendar_item_id": str(calendar_item_id),
                "triggered_by": "morning_jobs.content_topup",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
    logger.info("Content top-up: triggered %d item(s)", len(rows))


# Statuses that count as "still on the calendar" — published posts no longer
# extend the runway, but anything from planned to approved does.
_RUNWAY_STATUSES = ("planned", "queued", "working", "in_review", "approved")


async def _runway_alert() -> None:
    """For each active brand, notify the team (admins/managers) when the last
    scheduled post is ~2 days away — i.e., the calendar runs out soon and they
    need to plan or generate more.

    Anti-spam: skip when a `runway_alert` notification already exists for the
    same brand in the last 48h (per brand, regardless of recipient).
    """
    now = datetime.now(timezone.utc)
    window_start = now + timedelta(days=1, hours=12)
    window_end = now + timedelta(days=2, hours=12)
    dedup_since = now - timedelta(hours=48)

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT b.id, b.name, MAX(ci.scheduled_at) AS last_post "
                "FROM brands b "
                "JOIN calendar_items ci ON ci.brand_id = b.id "
                "WHERE b.is_active = true "
                f"  AND ci.status = ANY(ARRAY{list(_RUNWAY_STATUSES)}) "
                "  AND ci.scheduled_at IS NOT NULL "
                "GROUP BY b.id, b.name "
                "HAVING MAX(ci.scheduled_at) BETWEEN :ws AND :we"
            ),
            {"ws": window_start, "we": window_end},
        )
        candidates = result.fetchall()

        for brand_id, brand_name, last_post in candidates:
            dedup = await session.execute(
                text(
                    "SELECT 1 FROM notifications "
                    "WHERE notification_type = 'runway_alert' "
                    "  AND reference_id = :bid "
                    "  AND created_at >= :since "
                    "LIMIT 1"
                ),
                {"bid": brand_id, "since": dedup_since},
            )
            if dedup.first() is not None:
                continue

            last_date = (
                last_post.strftime("%a %b %d") if last_post else "—"
            )
            await notify_admins(
                db=session,
                notification_type="runway_alert",
                title=f"Content calendar runs out in 2 days — {brand_name}",
                body=(
                    f"{brand_name}: last scheduled post {last_date}. "
                    "Generate more content or plan a new batch to avoid a gap."
                ),
                reference_type="brand",
                reference_id=brand_id,
                roles=("admin", "manager", "editor"),
            )
            logger.info(
                "Runway alert sent for brand %s (last post %s)",
                brand_name, last_date,
            )


async def _stuck_in_review_alert() -> None:
    """Notify the team (editor/manager/admin) when one or more posts have been
    waiting in `in_review` for more than 48 hours. One grouped notification per
    brand at most (dedup window 72h, per brand).
    """
    now = datetime.now(timezone.utc)
    stuck_threshold = now - timedelta(hours=48)
    dedup_since = now - timedelta(hours=72)

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT b.id, b.name, "
                "       COUNT(ci.id) AS stuck_count, "
                "       MIN(ci.updated_at) AS oldest_updated, "
                "       (ARRAY_AGG(ci.title ORDER BY ci.updated_at ASC))[1] AS oldest_title "
                "FROM brands b "
                "JOIN calendar_items ci ON ci.brand_id = b.id "
                "WHERE b.is_active = true "
                "  AND ci.status = 'in_review' "
                "  AND ci.updated_at < :threshold "
                "GROUP BY b.id, b.name"
            ),
            {"threshold": stuck_threshold},
        )
        rows = result.fetchall()

        for brand_id, brand_name, stuck_count, oldest_updated, oldest_title in rows:
            dedup = await session.execute(
                text(
                    "SELECT 1 FROM notifications "
                    "WHERE notification_type = 'stuck_in_review' "
                    "  AND reference_id = :bid "
                    "  AND created_at >= :since "
                    "LIMIT 1"
                ),
                {"bid": brand_id, "since": dedup_since},
            )
            if dedup.first() is not None:
                continue

            age_days = max(1, int((now - oldest_updated).total_seconds() // 86400))
            preview = (oldest_title or "Untitled")[:80]
            await notify_admins(
                db=session,
                notification_type="stuck_in_review",
                title=(
                    f"{stuck_count} post{'s' if stuck_count != 1 else ''} "
                    f"waiting for review — {brand_name}"
                ),
                body=(
                    f"{brand_name}: oldest \"{preview}\" — "
                    f"{age_days} day{'s' if age_days != 1 else ''} ago"
                ),
                reference_type="brand",
                reference_id=brand_id,
                roles=("admin", "manager", "editor"),
            )
            logger.info(
                "Stuck-in-review alert sent for brand %s (%d posts, oldest %d days)",
                brand_name, stuck_count, age_days,
            )
