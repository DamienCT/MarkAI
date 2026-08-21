"""Interrupted runs pause instead of completing; drains stay in their lane.

P0-01: langgraph 1.1.3 does NOT raise GraphInterrupt out of ainvoke — a node
hitting interrupt() returns NORMALLY with the pending interrupts under
result["__interrupt__"]. The worker used to treat that as success: it stamped
the run 'completed' (whose completed-shaped payload then satisfied
get_latest_strategy — N-09) and chained planning off a strategy no human had
approved. These tests pin the safe-stop contract: an interrupted invoke is
recorded paused_for_review with ONLY the interrupt payload, the reviewers are
notified, and nothing chains.

AG-11: the shutdown drain used to release run locks with a GLOBAL
UPDATE agent_runs SET status='failed' WHERE status='running' — correct only
while this worker is the stack's sole executor. The release is now scoped to
the run ids this worker registered in its in-flight registry.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from langgraph.errors import GraphInterrupt
from langgraph.types import Interrupt

import worker


# ── Fakes (mirroring test_worker_dispatch / test_worker_shutdown) ────────


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


class _FakeJS:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def publish(self, subject, data):
        self.published.append((subject, json.loads(data.decode())))


class _FakeConsumer:
    def __init__(self):
        self.js = _FakeJS()
        self.shutdowns = 0

    async def shutdown(self):
        self.shutdowns += 1


class _FakeGraph:
    def __init__(self, result=None, exc: Exception | None = None):
        self.calls: list[dict] = []
        self.result = result if result is not None else {"status": "completed"}
        self.exc = exc

    async def ainvoke(self, state, config=None):
        self.calls.append(state)
        if self.exc is not None:
            raise self.exc
        return self.result


def _wire(monkeypatch, *, graph=None):
    """Stub DB, NATS, and the strategy graph around _handle_message."""
    consumer = _FakeConsumer()
    updates: list[tuple[str, dict]] = []
    notifs: list[dict] = []
    completions: list[tuple[str, dict]] = []
    graph = graph or _FakeGraph()

    async def fake_query(sql, params=None):
        return []  # brand-name lookup, stage-skip checks, …

    async def fake_update(sql, params=None):
        updates.append((sql, params or {}))
        return 1

    async def fake_create_run(**kwargs):
        return "run-1"

    async def fake_complete_run(run_id, **kwargs):
        completions.append((run_id, kwargs))

    async def fake_notify(**kwargs):
        notifs.append(kwargs)
        return 1

    monkeypatch.setattr(worker, "execute_query", fake_query)
    monkeypatch.setattr(worker, "execute_update", fake_update)
    monkeypatch.setattr(worker, "create_agent_run", fake_create_run)
    monkeypatch.setattr(worker, "complete_agent_run", fake_complete_run)
    monkeypatch.setattr(worker, "notify_admins", fake_notify)
    monkeypatch.setattr(worker, "_consumer", consumer)
    monkeypatch.setitem(worker.WORKFLOW_MAP, "strategy", graph)
    return {
        "consumer": consumer,
        "updates": updates,
        "notifs": notifs,
        "completions": completions,
        "graph": graph,
    }


_REVIEW_INTERRUPT = Interrupt(
    value={
        "type": "strategy_review",
        "brand_id": "b-1",
        "message": "Please review and approve the generated strategy.",
    },
    id="intr-1",
)

# What an interrupted strategy invoke actually returns on langgraph 1.1.3:
# the accumulated (UNAPPROVED) state plus the interrupt marker.
_INTERRUPTED_RESULT = {
    "status": "running",
    "pillars": [{"name": "Sustainability"}],
    "__interrupt__": [_REVIEW_INTERRUPT],
}


# ── _extract_interrupts unit behaviour ───────────────────────────────────


class TestExtractInterrupts:
    def test_reads_the_installed_langgraph_shape(self):
        got = worker._extract_interrupts(_INTERRUPTED_RESULT)
        assert len(got) == 1
        assert got[0]["value"]["type"] == "strategy_review"
        assert got[0]["interrupt_id"] == "intr-1"

    def test_no_marker_means_no_interrupt(self):
        assert worker._extract_interrupts({"status": "completed"}) == []
        assert worker._extract_interrupts({"__interrupt__": []}) == []
        assert worker._extract_interrupts(None) == []
        assert worker._extract_interrupts("not-a-dict") == []

    def test_bare_payloads_survive_extraction(self):
        # Defensive: a non-Interrupt item must not crash the safe-stop path.
        got = worker._extract_interrupts(
            {"__interrupt__": [{"message": "raw dict"}]}
        )
        assert got == [{"value": {"message": "raw dict"}, "interrupt_id": None}]


# ── The safe-stop contract through _handle_message ───────────────────────


class TestInterruptPausesRun:
    def test_interrupt_records_pause_and_never_chains(self, monkeypatch):
        w = _wire(monkeypatch, graph=_FakeGraph(result=dict(_INTERRUPTED_RESULT)))
        msg = _FakeMsg(
            "strategy.trigger", {"brand_id": "b-1", "trigger": "activation"}
        )
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        # Recorded paused, not completed …
        assert len(w["completions"]) == 1
        run_id, kwargs = w["completions"][0]
        assert run_id == "run-1"
        assert kwargs["status"] == "paused_for_review"
        # … with ONLY the interrupt payload — no completed-looking artifacts
        # for get_latest_strategy to pick up (N-09).
        payload = kwargs["output_payload"]
        assert payload["paused_for_review"] is True
        assert payload["interrupts"][0]["value"]["type"] == "strategy_review"
        assert "pillars" not in payload
        # No chaining: an unapproved strategy must not reach planning.
        assert w["consumer"].js.published == []
        # Operators are told a decision is waiting (legal notification_type).
        assert [n for n in w["notifs"] if n["notification_type"] == "approval_request"]

    def test_completed_without_interrupt_still_chains(self, monkeypatch):
        w = _wire(monkeypatch, graph=_FakeGraph(result={"status": "approved"}))
        msg = _FakeMsg(
            "strategy.trigger", {"brand_id": "b-1", "trigger": "activation"}
        )
        asyncio.run(worker._handle_message(msg))

        assert msg.acked
        assert [rid for rid, k in w["completions"] if k["status"] == "completed"]
        chained = [s for s, _ in w["consumer"].js.published]
        assert "planning.trigger" in chained

    def test_graphinterrupt_exception_still_pauses(self, monkeypatch):
        # Belt-and-suspenders: should a future langgraph raise again, the
        # except handler must land on the same pause/notify path.
        w = _wire(
            monkeypatch,
            graph=_FakeGraph(exc=GraphInterrupt([_REVIEW_INTERRUPT])),
        )
        msg = _FakeMsg("strategy.trigger", {"brand_id": "b-1", "trigger": "manual"})
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        assert len(w["completions"]) == 1
        run_id, kwargs = w["completions"][0]
        assert kwargs["status"] == "paused_for_review"
        assert (
            kwargs["output_payload"]["interrupts"][0]["value"]["type"]
            == "strategy_review"
        )
        assert w["consumer"].js.published == []


# ── Drain release stays scoped to this worker's runs (AG-11) ─────────────


@pytest.fixture()
def _clean_drain_state(monkeypatch):
    worker._draining = False
    worker._in_flight.clear()
    worker._deferred_naks.clear()
    worker._drain_task = None
    monkeypatch.setattr(worker, "_DRAIN_POLL_SECONDS", 0.01)

    updates: list[tuple[str, dict]] = []

    async def fake_update(sql, params=None):
        updates.append((sql, params or {}))
        return 0

    monkeypatch.setattr(worker, "execute_update", fake_update)
    yield updates
    worker._draining = False
    worker._in_flight.clear()
    worker._deferred_naks.clear()
    worker._drain_task = None


def _seed(msg: _FakeMsg, payload: dict, run_id: str | None = None) -> int:
    token = next(worker._in_flight_tokens)
    entry = {
        "msg": msg,
        "subject": msg.subject,
        "agent_type": msg.subject.split(".")[0],
        "payload": payload,
        "started": 0.0,
    }
    if run_id is not None:
        entry["run_id"] = run_id
    worker._in_flight[token] = entry
    return token


def _agent_run_updates(updates):
    return [(sql, params) for sql, params in updates if "UPDATE agent_runs" in sql]


class TestDrainScopedRelease:
    def test_exhausted_drain_releases_only_registered_run_ids(
        self, monkeypatch, _clean_drain_state
    ):
        monkeypatch.setattr(worker, "DRAIN_BUDGET_SECONDS", 0.05)
        _seed(_FakeMsg("content.generate", {}), {"brand_id": "b-1"}, run_id="run-a")
        _seed(_FakeMsg("planning.trigger", {}), {"brand_id": "b-2"}, run_id="run-b")
        asyncio.run(worker._drain_and_shutdown(_FakeConsumer()))

        releases = _agent_run_updates(_clean_drain_state)
        # One UPDATE per registered id (list-binding through raw text() is
        # unproven with asyncpg uuid arrays — the loop is the robust shape).
        assert len(releases) == 2
        for sql, params in releases:
            # Scoped, never global: another worker's live runs must survive.
            assert "WHERE id = :id" in sql
            assert "status = 'running'" in sql
            assert "ANY(" not in sql
        assert sorted(p["id"] for _, p in releases) == ["run-a", "run-b"]

    def test_abandoned_preforge_video_release_is_scoped(
        self, monkeypatch, _clean_drain_state
    ):
        async def not_reached(payload):
            return False

        monkeypatch.setattr(worker, "_video_reached_forge", not_reached)
        _seed(
            _FakeMsg("video.render", {}),
            {"brand_id": "b-1", "calendar_item_id": "ci-1"},
            run_id="run-v",
        )
        asyncio.run(worker._drain_and_shutdown(_FakeConsumer()))

        releases = _agent_run_updates(_clean_drain_state)
        assert len(releases) == 1
        sql, params = releases[0]
        assert "WHERE id = :id" in sql
        assert "ANY(" not in sql
        assert params["id"] == "run-v"

    def test_no_registered_ids_means_no_release_update(
        self, monkeypatch, _clean_drain_state
    ):
        # A handler cancelled before create_agent_run returned never
        # registered an id — the stale-run reaper owns any orphan row, and
        # the drain must NOT fall back to a global update.
        monkeypatch.setattr(worker, "DRAIN_BUDGET_SECONDS", 0.05)
        _seed(_FakeMsg("content.generate", {}), {"brand_id": "b-1"})
        asyncio.run(worker._drain_and_shutdown(_FakeConsumer()))

        assert _agent_run_updates(_clean_drain_state) == []

    def test_clean_drain_touches_nothing(self, _clean_drain_state):
        asyncio.run(worker._drain_and_shutdown(_FakeConsumer()))
        assert _agent_run_updates(_clean_drain_state) == []


class TestRegisterRunId:
    def test_binds_to_the_current_tasks_entry_only(self, _clean_drain_state):
        async def scenario():
            other = SimpleNamespace()  # some other task's entry
            token_other = next(worker._in_flight_tokens)
            worker._in_flight[token_other] = {"task": other}
            token_mine = next(worker._in_flight_tokens)
            worker._in_flight[token_mine] = {"task": asyncio.current_task()}
            worker._register_run_id("run-mine")
            return token_other, token_mine

        token_other, token_mine = asyncio.run(scenario())
        assert worker._in_flight[token_mine]["run_id"] == "run-mine"
        assert "run_id" not in worker._in_flight[token_other]
