"""Reap agent runs stuck in 'running' after a worker crash.

The partial unique index idx_agent_runs_running blocks any new run of the same
(brand, agent_type) while a 'running' row exists, so a crashed worker used to
deadlock that workflow for the brand forever. The agents worker acks within its
92-minute ack window; anything 'running' for far longer is dead.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.models.base import async_session_factory

logger = logging.getLogger(__name__)

# Comfortably beyond the agents worker's 92-minute ack_wait plus one redelivery.
STALE_AFTER_HOURS = 4


async def reap_stale_agent_runs() -> int:
    """Mark long-dead 'running' agent runs as failed. Returns rows reaped."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "UPDATE agent_runs "
                "SET status = 'failed', "
                "    error_message = COALESCE(error_message, '') || "
                "        ' [reaped: stuck in running past stale threshold]', "
                "    completed_at = NOW() "
                "WHERE status = 'running' "
                "  AND COALESCE(started_at, created_at) < :cutoff "
                "RETURNING id, agent_type, brand_id"
            ),
            {"cutoff": cutoff},
        )
        reaped = result.all()
        await session.commit()

    for run_id, agent_type, brand_id in reaped:
        logger.warning(
            "Reaped stale agent run %s (%s) for brand %s", run_id, agent_type, brand_id
        )
    return len(reaped)
