"""video.render redelivery must never re-render a finished reel.

Measured incident, 2026-08-20: two redeploys each restarted the agents
container, JetStream redelivered an unacked video.render, and the GPU
rendered the same 30-second reel twice more at full length before the
triggered render ran — three renders, one deliverable. The worker now
ack-skips a video.render whose calendar item is already reviewable, or
which carries a current reel without having been re-queued ('queued' is
the one status the manual re-render endpoint sets before publishing).
"""

import asyncio
import json

import pytest

import worker


class _FakeMsg:
    def __init__(self, subject: str, payload: dict):
        self.subject = subject
        self.data = json.dumps(payload).encode()
        self.acked = False
        self.naks: list = []

    async def ack(self):
        self.acked = True

    async def nak(self, delay=0):
        self.naks.append(delay)


class _Sentinel(Exception):
    """Raised by the create_agent_run stub to prove the guard fell through."""


def _wire(monkeypatch, guard_rows):
    """Stub the guard's DB read and fence everything past the guard."""
    calls = {"create_run": False}

    async def fake_query(sql, params=None):
        return guard_rows

    async def fake_create_run(**kwargs):
        calls["create_run"] = True
        raise _Sentinel()

    monkeypatch.setattr(worker, "execute_query", fake_query)
    monkeypatch.setattr(worker, "create_agent_run", fake_create_run)
    return calls


_PAYLOAD = {"brand_id": "b-1", "calendar_item_id": "ci-1", "trigger": "manual"}


@pytest.mark.parametrize(
    "status", ["in_review", "approved", "scheduled", "published"]
)
def test_reviewable_item_is_ack_skipped(monkeypatch, status):
    calls = _wire(monkeypatch, [{"status": status, "video_url": None}])
    msg = _FakeMsg("video.render", _PAYLOAD)
    asyncio.run(worker._handle_message(msg))
    assert msg.acked and not msg.naks
    assert calls["create_run"] is False


def test_current_reel_without_requeue_is_ack_skipped(monkeypatch):
    # A redelivery interrupting a RE-render: item stuck 'rendering' but the
    # OLD reel is still the current content — skip, don't re-render.
    calls = _wire(
        monkeypatch, [{"status": "rendering", "video_url": "videos/x/final.mp4"}]
    )
    msg = _FakeMsg("video.render", _PAYLOAD)
    asyncio.run(worker._handle_message(msg))
    assert msg.acked and not msg.naks
    assert calls["create_run"] is False


@pytest.mark.parametrize(
    "row",
    [
        # The manual endpoint flips to 'queued' before publishing — a queued
        # item renders even when an older reel exists (that IS the re-render).
        {"status": "queued", "video_url": "videos/x/final.mp4"},
        # First render ever: crashed worker left 'rendering', no reel yet —
        # redelivery is the recovery path and must proceed.
        {"status": "rendering", "video_url": None},
    ],
)
def test_legitimate_render_proceeds(monkeypatch, row):
    calls = _wire(monkeypatch, [row])
    msg = _FakeMsg("video.render", _PAYLOAD)
    with pytest.raises(_Sentinel):
        asyncio.run(worker._handle_message(msg))
    assert calls["create_run"] is True


def test_guard_fails_open(monkeypatch):
    calls = {"create_run": False}

    async def broken_query(sql, params=None):
        raise RuntimeError("db down")

    async def fake_create_run(**kwargs):
        calls["create_run"] = True
        raise _Sentinel()

    monkeypatch.setattr(worker, "execute_query", broken_query)
    monkeypatch.setattr(worker, "create_agent_run", fake_create_run)
    msg = _FakeMsg("video.render", _PAYLOAD)
    with pytest.raises(_Sentinel):
        asyncio.run(worker._handle_message(msg))
    assert calls["create_run"] is True
