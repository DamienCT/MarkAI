"""Tests for the morning content top-up: past-due retry + bounded batch."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.scheduler import morning_jobs
from app.scheduler.morning_jobs import _TOPUP_BATCH_LIMIT, _topup_content_generation


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


def _row(scheduled_at):
    return (uuid.uuid4(), uuid.uuid4(), "Test item", scheduled_at)


@pytest.fixture()
def publish(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(morning_jobs.nats_service, "publish", mock)
    monkeypatch.setattr("app.scheduler.get_app_setting", AsyncMock(return_value=14))
    return mock


def test_batch_limit_is_bounded():
    """One morning run a day; the worker chews content.generate sequentially
    at up to 92 minutes per item, so ~15 worst-case items fit between runs.
    The cap must stay inside that budget but well above the old LIMIT 1."""
    assert 1 < _TOPUP_BATCH_LIMIT <= 15


@pytest.mark.anyio
async def test_topup_query_includes_past_due_items(publish, monkeypatch):
    """The window must have NO lower bound — a past-due queued item (redeploy-
    dropped queue, exhausted video retries) is exactly what this job heals."""
    past_due = _row(datetime.now(timezone.utc) - timedelta(days=3))
    session = _FakeSession([_FakeResult([past_due])])
    monkeypatch.setattr(morning_jobs, "async_session_factory", lambda: session)

    await _topup_content_generation()

    stmt, params = session.executed[0]
    sql = str(stmt)
    assert "scheduled_at <= :horizon" in sql
    assert "BETWEEN" not in sql  # the old future-only window
    assert "now" not in params  # no lower-bound parameter at all
    assert params["batch_limit"] == _TOPUP_BATCH_LIMIT

    publish.assert_awaited_once()
    subject, msg = publish.await_args.args
    assert subject == "content.generate"
    assert msg["calendar_item_id"] == str(past_due[0])
    assert msg["brand_id"] == str(past_due[1])
    assert msg["triggered_by"] == "morning_jobs.content_topup"


@pytest.mark.anyio
async def test_topup_triggers_one_message_per_item(publish, monkeypatch):
    rows = [
        _row(datetime.now(timezone.utc) - timedelta(hours=6)),
        _row(datetime.now(timezone.utc) + timedelta(days=1)),
        _row(datetime.now(timezone.utc) + timedelta(days=2)),
    ]
    session = _FakeSession([_FakeResult(rows)])
    monkeypatch.setattr(morning_jobs, "async_session_factory", lambda: session)

    await _topup_content_generation()

    assert publish.await_count == 3
    sent_ids = [call.args[1]["calendar_item_id"] for call in publish.await_args_list]
    assert sent_ids == [str(r[0]) for r in rows]


@pytest.mark.anyio
async def test_topup_no_rows_publishes_nothing(publish, monkeypatch):
    session = _FakeSession([_FakeResult([])])
    monkeypatch.setattr(morning_jobs, "async_session_factory", lambda: session)

    await _topup_content_generation()

    publish.assert_not_awaited()
