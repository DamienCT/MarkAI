"""Tests for the stale-run reaper's per-agent-type thresholds."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.scheduler import stale_run_reaper
from app.scheduler.stale_run_reaper import (
    STALE_AFTER_HOURS,
    STALE_AFTER_HOURS_BY_AGENT_TYPE,
    reap_stale_agent_runs,
)

# Mirrored worst case from agents/shared/config.py::video_workflow_timeout_s:
# VIDEO_MAX_REEL_SHOTS(8) x VIDEO_RENDER_TIMEOUT_S(2400s)
# + VIDEO_FINISHING_BUDGET_S(6900s). The backend cannot import agents code, so
# this test pins the mirror — if the agents-side budget grows past the reaper
# threshold again, live reels get reaped mid-render and lose their dedup lock.
VIDEO_WORKFLOW_BUDGET_S = 8 * 2400 + (8 * 600 + 900 + 600 + 600)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Async-context-manager session that replays canned query results."""

    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.commit = AsyncMock()

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        return self._results.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_video_threshold_exceeds_render_budget():
    """A live reel may legitimately run ~7.25h; the reaper must wait longer,
    or the (brand, agent_type) dedup lock evaporates mid-render and a
    redelivered message starts a concurrent duplicate render on the GPU."""
    video_threshold_s = STALE_AFTER_HOURS_BY_AGENT_TYPE["video"] * 3600
    assert video_threshold_s > VIDEO_WORKFLOW_BUDGET_S
    # ...with at least one 30-minute reaper interval of slack on top.
    assert video_threshold_s >= VIDEO_WORKFLOW_BUDGET_S + 1800


def test_default_threshold_still_covers_ordinary_ack_window():
    # Generic subjects ack within 92 minutes; default must clear one full
    # redelivery of that window, and must NOT silently absorb the video value.
    assert STALE_AFTER_HOURS * 3600 > 2 * 92 * 60
    assert STALE_AFTER_HOURS < STALE_AFTER_HOURS_BY_AGENT_TYPE["video"]


@pytest.mark.anyio
async def test_reaper_binds_per_type_cutoffs(monkeypatch):
    """The single UPDATE must carry BOTH cutoffs: video rows compared against
    the long threshold, everything else against the generic one."""
    session = _FakeSession([_FakeResult([])])
    monkeypatch.setattr(
        stale_run_reaper, "async_session_factory", lambda: session
    )

    before = datetime.now(timezone.utc)
    count = await reap_stale_agent_runs()
    after = datetime.now(timezone.utc)

    assert count == 0
    stmt, params = session.executed[0]
    sql = str(stmt)
    assert "CASE" in sql
    assert "agent_type = :type_video" in sql
    assert "ELSE :cutoff_default" in sql
    assert params["type_video"] == "video"

    # Video cutoff is FURTHER in the past — video rows survive longer.
    assert params["cutoff_video"] < params["cutoff_default"]
    expected_default = timedelta(hours=STALE_AFTER_HOURS)
    expected_video = timedelta(hours=STALE_AFTER_HOURS_BY_AGENT_TYPE["video"])
    assert before - expected_default <= params["cutoff_default"] <= after - expected_default
    assert before - expected_video <= params["cutoff_video"] <= after - expected_video


@pytest.mark.anyio
async def test_reaper_returns_reaped_count_and_commits(monkeypatch):
    rows = [
        (uuid.uuid4(), "content", uuid.uuid4()),
        (uuid.uuid4(), "video", uuid.uuid4()),
    ]
    session = _FakeSession([_FakeResult(rows)])
    monkeypatch.setattr(
        stale_run_reaper, "async_session_factory", lambda: session
    )

    count = await reap_stale_agent_runs()

    assert count == 2
    session.commit.assert_awaited()
