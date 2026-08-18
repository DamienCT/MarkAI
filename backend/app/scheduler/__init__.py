from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings

scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)


async def get_app_setting(key: str, default=None):
    """Read a setting from the app_settings table at runtime (not cached)."""
    from app.models.base import async_session_factory
    from sqlalchemy import text

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT value FROM app_settings WHERE key = :key"),
                {"key": key},
            )
            row = result.first()
            if row:
                import json

                return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception:
        pass
    return default


def setup_scheduler() -> None:
    """Register all scheduled jobs and start the scheduler.

    MUST be called from an async context (e.g. FastAPI lifespan) so that
    AsyncIOScheduler.start() binds to the running event loop.
    """
    from datetime import datetime, timedelta, timezone

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

    # Every N minutes — check for content due to publish.
    # Fire 30s after startup so overdue content is caught immediately,
    # then repeat on the regular interval.
    scheduler.add_job(
        check_due_content,
        IntervalTrigger(minutes=settings.PUBLISH_CHECK_INTERVAL_MINUTES),
        id="publish_checker",
        name="Check due content for publishing",
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=30),
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

    # Every 6 hours — pull Google Trends and LLM-score per active brand
    from app.services.trends_service import pull_and_score_all_brands

    scheduler.add_job(
        pull_and_score_all_brands,
        IntervalTrigger(hours=6),
        id="trends_pull",
        name="Pull trending topics + LLM score per brand",
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
        replace_existing=True,
    )

    # Every 30 minutes — free brands deadlocked by crashed 'running' agent runs
    from app.scheduler.stale_run_reaper import reap_stale_agent_runs

    scheduler.add_job(
        reap_stale_agent_runs,
        IntervalTrigger(minutes=30),
        id="stale_run_reaper",
        name="Reap agent runs stuck in running",
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=5),
        replace_existing=True,
    )

    # Every 6 hours — alert the team before a brand's LinkedIn token expires
    from app.scheduler.linkedin_token_alert import linkedin_token_expiry_check

    scheduler.add_job(
        linkedin_token_expiry_check,
        IntervalTrigger(hours=6),
        id="linkedin_token_expiry",
        name="Alert before LinkedIn token expiry",
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3),
        replace_existing=True,
    )

    # Start the scheduler on the current (running) event loop.
    # This MUST happen inside an async context so get_event_loop()
    # returns the uvicorn loop, not a new detached one.
    scheduler.start()
