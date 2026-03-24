from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)


def setup_scheduler() -> None:
    """Register all scheduled jobs. Called on FastAPI startup."""
    from app.scheduler.morning_jobs import run_morning_jobs
    from app.scheduler.publish_checker import check_due_content
    from app.scheduler.engagement_puller import pull_all_engagement
    from app.scheduler.bc_sync import sync_bc_products

    # Daily morning job — BC sync + engagement pull + evaluation trigger
    scheduler.add_job(
        run_morning_jobs,
        CronTrigger(
            hour=settings.MORNING_SCHEDULE_HOUR,
            minute=settings.MORNING_SCHEDULE_MINUTE,
        ),
        id="morning_jobs",
        name="Morning: BC sync + engagement + evaluation",
        replace_existing=True,
    )

    # Every N minutes — check for content due to publish
    scheduler.add_job(
        check_due_content,
        IntervalTrigger(minutes=settings.PUBLISH_CHECK_INTERVAL_MINUTES),
        id="publish_checker",
        name="Check due content for publishing",
        replace_existing=True,
    )

    # Every N hours — pull engagement metrics
    scheduler.add_job(
        pull_all_engagement,
        IntervalTrigger(hours=settings.ENGAGEMENT_PULL_INTERVAL_HOURS),
        id="engagement_puller",
        name="Pull engagement from social platforms",
        replace_existing=True,
    )

    # Every N hours — sync BC products
    scheduler.add_job(
        sync_bc_products,
        IntervalTrigger(hours=settings.BC_SYNC_INTERVAL_HOURS),
        id="bc_sync",
        name="Sync Business Central products",
        replace_existing=True,
    )

    # Daily at 3 AM — discover available AI models from providers
    from app.scheduler.model_discovery import discover_ai_models

    scheduler.add_job(
        discover_ai_models,
        CronTrigger(hour=3, minute=0),
        id="ai_model_discovery",
        name="Discover available AI models from providers",
        replace_existing=True,
    )

    scheduler.start()
