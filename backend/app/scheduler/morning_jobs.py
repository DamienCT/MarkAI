import logging
from datetime import datetime

from app.auth.models import ScheduledJobLog
from app.models.base import async_session_factory
from app.services import nats_service
from app.services.notification_service import notify_failure

logger = logging.getLogger(__name__)


async def _log_job(job_name: str, status: str, error_message: str | None = None) -> None:
    async with async_session_factory() as db:
        log = ScheduledJobLog(
            job_name=job_name,
            status=status,
            completed_at=datetime.now() if status != "started" else None,
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
            "timestamp": datetime.now().isoformat(),
        })
        logger.info("Emitted evaluation.trigger to NATS")
    except Exception as e:
        logger.error("NATS evaluation trigger failed: %s", e)
        await notify_failure("morning_jobs.evaluation_trigger", None, e)

    await _log_job("morning_jobs", "completed")
    logger.info("Morning jobs completed")
