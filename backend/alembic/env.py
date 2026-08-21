import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models.base import Base

# Import all models so Alembic sees them
from app.auth.models import User, Notification, AuditLog, ScheduledJobLog  # noqa: F401
from app.models.brand import Brand  # noqa: F401
from app.models.content import Content  # noqa: F401
from app.models.campaign import Campaign  # noqa: F401
from app.models.calendar_item import CalendarItem  # noqa: F401
from app.models.approval import Approval  # noqa: F401
from app.models.prompt_version import PromptVersion  # noqa: F401
from app.models.agent_run import AgentRun  # noqa: F401
from app.models.engagement import EngagementMetric  # noqa: F401
from app.models.adaptation import Adaptation  # noqa: F401
from app.models.competitor import Competitor  # noqa: F401
from app.models.product import Product  # noqa: F401
from app.models.ai_model import AIModelCategory, AIModel, AIModelSelection  # noqa: F401
from app.models.event import Event  # noqa: F401
from app.models.trending_topic import TrendingTopic  # noqa: F401
from app.models.channel_model_fallback import ChannelModelFallback  # noqa: F401
from app.models.video_job import VideoJob  # noqa: F401
from app.models.media_asset import MediaAsset  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required for migrations")


def include_object(object, name, type_, reflected, compare_to):
    """Keep --autogenerate from emitting DROPs for schema that has no ORM model.

    brand_model_profiles (0004), system_flags and webhook_events (0005) exist
    only as SQL — no model imports them above — and the hand-written partial
    indexes (idx_brand_model_profiles_ready, idx_products_brand_bc_item,
    idx_video_jobs_idempotency, idx_agent_runs_running, idx_content_current, …)
    never appear in metadata either. Without this hook a future autogenerate
    would emit DROP TABLE / DROP INDEX for all of them (N-16). Anything
    reflected from the database with no metadata counterpart is therefore
    ignored; removing schema stays the job of hand-written convergence
    migrations.
    """
    if reflected and compare_to is None:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = DATABASE_URL
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
