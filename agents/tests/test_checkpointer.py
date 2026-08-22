"""shared.checkpointer: one process-wide saver, loud MemorySaver fallback.

The HITL graphs compile at import time against get_checkpointer()'s
MemorySaver; worker startup upgrades to the durable Postgres saver via
setup_checkpointer(). When the database (or the driver stack) is unavailable
the setup must fall back to the SAME MemorySaver instance the graphs already
hold — announced by exactly ONE loud error — so pausing keeps working and
nothing is left half-open.
"""

import asyncio
import logging

import pytest
from langgraph.checkpoint.memory import MemorySaver

import shared.checkpointer as checkpointer_mod
from shared.config import settings


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch):
    """Isolate the module-level singleton per test (and restore after)."""
    monkeypatch.setattr(checkpointer_mod, "_saver", None)
    monkeypatch.setattr(checkpointer_mod, "_pool", None)
    yield


def test_get_checkpointer_is_a_process_wide_singleton():
    a = checkpointer_mod.get_checkpointer()
    b = checkpointer_mod.get_checkpointer()
    assert a is b
    assert isinstance(a, MemorySaver)


def test_setup_falls_back_loudly_when_the_db_is_unreachable(
    monkeypatch, caplog
):
    monkeypatch.setattr(checkpointer_mod, "_POOL_OPEN_TIMEOUT_S", 0.3)
    monkeypatch.setattr(settings, "POSTGRES_HOST", "no-such-host.invalid")
    imported_saver = checkpointer_mod.get_checkpointer()

    with caplog.at_level(logging.ERROR):
        saver = asyncio.run(checkpointer_mod.setup_checkpointer())

    # The graphs' import-time saver stays the active one — pause still works.
    assert saver is imported_saver
    assert isinstance(saver, MemorySaver)
    # Exactly ONE loud error, naming the consequence an operator must know.
    own_errors = [
        r
        for r in caplog.records
        if r.name == "shared.checkpointer" and r.levelno >= logging.ERROR
    ]
    assert len(own_errors) == 1
    assert "RESUME WILL NOT SURVIVE" in own_errors[0].getMessage()
    assert "checkpoint lost" in own_errors[0].getMessage()
    # Nothing half-open left behind: a later call may retry from scratch.
    assert checkpointer_mod._pool is None
