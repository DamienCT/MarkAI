import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.services import nats_service
from app.services.notification_service import notify_failure

logger = logging.getLogger(__name__)

# Module-level dict to track job start times for duration calculation
_job_start_times: dict[str, datetime] = {}


async def _log_job(job_name: str, status: str, error_message: str | None = None) -> None:
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

    # 3. Emit evaluation trigger to NATS
    try:
        await nats_service.publish("evaluation.trigger", {
            "triggered_by": "morning_jobs",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Emitted evaluation.trigger to NATS")
    except Exception as e:
        logger.error("NATS evaluation trigger failed: %s", e)
        await notify_failure("morning_jobs.evaluation_trigger", None, e)

    # 4. Daily content top-up — generate content for upcoming calendar items
    try:
        await _topup_content_generation()
    except Exception as e:
        logger.error("Content top-up failed in morning jobs: %s", e)
        await notify_failure("morning_jobs.content_topup", None, e)

    await _log_job("morning_jobs", "completed")
    logger.info("Morning jobs completed")


async def _topup_content_generation() -> None:
    """
    Check for calendar items within the content_generation_days_ahead window
    that are still in 'queued' or 'planned' status and trigger content
    generation for the nearest one (sequential, one per run).
    """
    from app.scheduler import get_app_setting

    days_ahead = await get_app_setting("content_generation_days_ahead", default=7)
    try:
        days_ahead = int(days_ahead)
    except (TypeError, ValueError):
        days_ahead = 7

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=days_ahead)

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, brand_id, title, scheduled_at "
                "FROM calendar_items "
                "WHERE status IN ('queued', 'planned') "
                "  AND scheduled_at IS NOT NULL "
                "  AND scheduled_at BETWEEN :now AND :horizon "
                "ORDER BY scheduled_at ASC "
                "LIMIT 1"
            ),
            {"now": now, "horizon": horizon},
        )
        row = result.first()

    if row is None:
        logger.info("Content top-up: no queued/planned items within %d-day window", days_ahead)
        return

    calendar_item_id, brand_id, title, scheduled_at = row
    logger.info(
        "Content top-up: triggering generation for calendar item %s (%s) scheduled at %s",
        calendar_item_id, title, scheduled_at,
    )

    await nats_service.publish("content.generate", {
        "brand_id": str(brand_id),
        "calendar_item_id": str(calendar_item_id),
        "triggered_by": "morning_jobs.content_topup",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
