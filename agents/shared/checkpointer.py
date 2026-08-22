"""Durable LangGraph checkpointer for the HITL (interrupt) workflows.

A paused graph can only be resumed from its checkpoint. The per-graph
MemorySaver the HITL graphs used to compile with dies with the process, so a
worker redeploy between pause and resume made every paused_for_review run
unresumable (the deferred half of P0-01). This module owns ONE process-wide
checkpointer:

- ``AsyncPostgresSaver`` (langgraph-checkpoint-postgres) over its own psycopg3
  connection pool — checkpoints survive restarts and redeploys. Its tables
  live next to the app schema and ``setup()`` is idempotent.
- ``MemorySaver`` fallback when the package or the database is unavailable at
  startup, announced by ONE loud error: pausing itself stays safe either way,
  but resume will not survive a restart. The worker's resume handler probes
  ``aget_tuple`` and fails a checkpoint-less run with an operator-actionable
  error — necessary because langgraph 1.1.3 does NOT raise on
  ``Command(resume=...)`` for an unknown thread: it silently re-runs the graph
  from the entry point (verified against the installed version).

Import-time vs. startup: graphs are compiled at module import, before any
event loop exists, but ``AsyncPostgresSaver`` can only be constructed inside a
running loop (its ``__init__`` captures ``asyncio.get_running_loop()``). So
graphs compile with :func:`get_checkpointer`'s MemorySaver, and worker startup
calls :func:`setup_checkpointer` then re-points every checkpointed graph at
the saver it returns.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from shared.config import settings

logger = logging.getLogger(__name__)

#: The process-wide checkpointer. MemorySaver until setup_checkpointer()
#: upgrades it; never None after the first get_checkpointer() call.
_saver: Any | None = None

#: The psycopg connection pool behind the durable saver (None on fallback).
_pool: Any | None = None

#: How long startup waits for the pool's first connection before falling
#: back. Postgres is on the same compose network, so 30s is generous.
_POOL_OPEN_TIMEOUT_S = 30


def get_checkpointer() -> Any:
    """Return the process-wide checkpointer.

    Graph modules call this at compile time (import time — no loop yet), so
    it hands out a MemorySaver until :func:`setup_checkpointer` builds the
    durable saver; the worker then re-points the compiled graphs.
    """
    global _saver
    if _saver is None:
        _saver = MemorySaver()
    return _saver


async def setup_checkpointer() -> Any:
    """Build the durable AsyncPostgresSaver and make it the active saver.

    Called once at worker startup, inside the running loop. Idempotent: a
    second call returns the already-durable saver. On ANY failure — package
    missing, database unreachable, setup() error — it logs one loud error and
    leaves the MemorySaver fallback active (fail closed: pausing stays safe,
    resume degrades detectably instead of crashing the worker).

    Callers must re-point already-compiled graphs at the returned saver: they
    captured the import-time MemorySaver by reference.
    """
    global _saver, _pool
    if _pool is not None:
        return _saver  # already durable
    pool = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg.rows import dict_row
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            conninfo=settings.postgres_dsn_psycopg,
            min_size=1,
            max_size=4,
            open=False,
            kwargs={
                # The saver's own queries require exactly these (mirrors
                # AsyncPostgresSaver.from_conn_string, which is unusable
                # here: it is a context manager that closes the connection
                # when its scope exits, and this saver must outlive setup).
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        # wait=True makes an unreachable database fail HERE, at startup,
        # instead of on the first checkpoint write mid-workflow.
        await pool.open(wait=True, timeout=_POOL_OPEN_TIMEOUT_S)
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # idempotent: CREATE IF NOT EXISTS + migrations
    except Exception as exc:
        if pool is not None:
            try:
                await pool.close()
            except Exception:  # the pool never opened — nothing to release
                pass
        logger.error(
            "Durable checkpointer unavailable (%s) — falling back to "
            "MemorySaver: pausing stays safe, but RESUME WILL NOT SURVIVE A "
            "WORKER RESTART. A run paused by a previous process has no "
            "checkpoint here and will be failed with 'checkpoint lost — "
            "re-run the workflow' on its first resume attempt.",
            exc,
        )
        return get_checkpointer()
    _pool = pool
    _saver = saver
    logger.info(
        "Durable Postgres checkpointer ready (thread_id = agent run id)"
    )
    return _saver
