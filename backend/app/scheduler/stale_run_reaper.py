"""Reap agent runs stuck in 'running' after a worker crash.

The partial unique index idx_agent_runs_running blocks any new run of the same
(brand, agent_type) while a 'running' row exists, so a crashed worker used to
deadlock that workflow for the brand forever.

Primary rule (lease model, since migration 0006): a live worker heartbeats
``heartbeat_at`` every 30s for every run it owns, so a running row whose
heartbeat is older than HEARTBEAT_STALE_MINUTES belongs to a dead worker —
regardless of how young the run is. Legacy rows created before the migration
(or by a not-yet-updated worker) have ``heartbeat_at IS NULL`` and keep the
conservative age-only backstop: the agents worker acks within its 92-minute
ack window; anything 'running' far longer is dead — EXCEPT video, whose
legitimate budget is hours long (see the threshold table below).
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.models.base import async_session_factory

logger = logging.getLogger(__name__)

# A live worker renews every 30s; 5 minutes of silence = dead worker. Ten
# missed beats is far past any GC pause / event-loop stall a healthy worker
# can produce, while still freeing the (brand, agent_type) dedup lock fast.
HEARTBEAT_STALE_MINUTES = 5

# Comfortably beyond the agents worker's 92-minute ack_wait plus one redelivery.
STALE_AFTER_HOURS = 4

# Per-agent-type overrides. A reel render may legitimately run
# VIDEO_MAX_REEL_SHOTS(8) x VIDEO_RENDER_TIMEOUT_S(2400s) plus the ffmpeg
# finishing passes (6900s) = 26100s ~ 7.25h — the worst case computed by
# agents/shared/config.py::video_workflow_timeout_s. The backend cannot import
# agents code, so that derived value is MIRRORED here (change them together).
# Reaping a live reel at the generic 4h deletes the (brand, agent_type) dedup
# lock mid-render, letting a redelivered video.render message start a
# concurrent duplicate render on the same GPU. 10h = the 7.25h budget plus the
# same ~2.5h grace the generic threshold keeps over its 92-minute window.
STALE_AFTER_HOURS_BY_AGENT_TYPE = {"video": 10}


async def reap_stale_agent_runs() -> int:
    """Mark long-dead 'running' agent runs as failed. Returns rows reaped."""
    now = datetime.now(timezone.utc)
    params: dict[str, object] = {
        "cutoff_default": now - timedelta(hours=STALE_AFTER_HOURS),
        "heartbeat_cutoff": now - timedelta(minutes=HEARTBEAT_STALE_MINUTES),
    }
    # One CASE arm per override; only param NAMES are interpolated into the
    # SQL (the keys of a literal dict above), values are bound.
    when_arms = []
    for agent_type, hours in sorted(STALE_AFTER_HOURS_BY_AGENT_TYPE.items()):
        params[f"type_{agent_type}"] = agent_type
        params[f"cutoff_{agent_type}"] = now - timedelta(hours=hours)
        when_arms.append(
            f"WHEN agent_type = :type_{agent_type} THEN :cutoff_{agent_type}"
        )
    cutoff_expr = f"CASE {' '.join(when_arms)} ELSE :cutoff_default END"

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "UPDATE agent_runs "
                "SET status = 'failed', "
                "    error_message = COALESCE(error_message, '') || "
                "        ' [reaped: worker lease expired or stuck past stale"
                " threshold]', "
                "    completed_at = NOW() "
                "WHERE status = 'running' "
                "  AND ( "
                "        (heartbeat_at IS NOT NULL "
                "         AND heartbeat_at < :heartbeat_cutoff) "
                "     OR (heartbeat_at IS NULL "
                f"        AND COALESCE(started_at, created_at) < {cutoff_expr}) "
                "  ) "
                "RETURNING id, agent_type, brand_id"
            ),
            params,
        )
        reaped = result.all()
        await session.commit()

    for run_id, agent_type, brand_id in reaped:
        logger.warning(
            "Reaped stale agent run %s (%s) for brand %s", run_id, agent_type, brand_id
        )
    return len(reaped)
