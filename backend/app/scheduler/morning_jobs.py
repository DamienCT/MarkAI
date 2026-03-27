import logging
from datetime import datetime, timezone

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

    await _log_job("morning_jobs", "completed")
    logger.info("Morning jobs completed")
