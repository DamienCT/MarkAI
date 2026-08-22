"""The agent.resume.run handler: single-winner CAS, checkpoint-lost safety.

The worker is the SINGLE WRITER of the paused_for_review→running transition:
the backend only publishes the resume message, so the CAS here either wins
exactly once (stamping claimed_by=WORKER_ID) or settles a no-op. After the
claim, the graph is resumed with Command(resume={"decision", "feedback"}) on
thread_id=run_id and the EXISTING post-invoke path settles the outcome —
interrupt again → paused_for_review, completed → chaining off the run's
ORIGINAL payload, failure → failed.

The checkpoint-lost invariant matters because langgraph 1.1.3 does NOT raise
when resuming an unknown thread — it silently re-runs the graph from the
entry point, spending the full LLM budget to arrive at a brand-new pause. A
resume for a run with no checkpoint (worker restarted on the MemorySaver
fallback) must instead fail the run with an operator-actionable error and
never leave it stuck in 'running'.
"""

import asyncio
import json

import pytest
from langgraph.types import Command, Interrupt
from sqlalchemy.exc import IntegrityError

import worker


# ── Fakes (mirroring test_worker_hitl_pause / test_worker_dispatch) ──────


class _FakeMsg:
    def __init__(self, payload: dict):
        self.subject = "agent.resume.run"
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


class _FakeSaver:
    def __init__(self, has_checkpoint: bool):
        self.has_checkpoint = has_checkpoint
        self.probes: list[dict] = []

    async def aget_tuple(self, config):
        self.probes.append(config)
        return object() if self.has_checkpoint else None


class _FakeGraph:
    def __init__(self, result=None, has_checkpoint=True, exc=None):
        self.result = result if result is not None else {"status": "approved"}
        self.checkpointer = _FakeSaver(has_checkpoint)
        self.exc = exc
        self.calls: list[tuple] = []

    async def ainvoke(self, state, config=None):
        self.calls.append((state, config))
        if self.exc is not None:
            raise self.exc
        return self.result


def _resume_msg(**overrides) -> _FakeMsg:
    payload = {
        "run_id": "run-1",
        "workflow_type": "strategy",
        "decision": "approved",
        "feedback": None,
        "actor": "reviewer@example.com",
        "requested_at": "2026-08-22T09:00:00Z",
    }
    payload.update(overrides)
    return _FakeMsg(payload)


def _wire(
    monkeypatch,
    *,
    graph=None,
    run_row=None,
    cas_result=1,
    cas_exc: Exception | None = None,
):
    """Stub DB, NATS, and the strategy graph around _handle_resume."""
    consumer = _FakeConsumer()
    updates: list[tuple[str, dict]] = []
    completions: list[tuple[str, dict]] = []
    notifs: list[dict] = []
    graph = graph or _FakeGraph()
    if run_row is None:
        run_row = {
            "brand_id": "b-1",
            "agent_type": "strategy",
            "status": "paused_for_review",
            "input_payload": json.dumps(
                {"brand_id": "b-1", "trigger": "activation"}
            ),
        }

    async def fake_query(sql, params=None):
        if "FROM agent_runs WHERE id" in sql:
            return [dict(run_row)] if run_row else []
        return []  # brand-name lookups etc.

    async def fake_update(sql, params=None):
        updates.append((sql, params or {}))
        if "paused_for_review'" in sql and cas_exc is not None:
            raise cas_exc
        if "paused_for_review'" in sql:
            return cas_result
        return 1

    async def fake_complete(run_id, **kwargs):
        completions.append((run_id, kwargs))

    async def fake_notify(**kwargs):
        notifs.append(kwargs)
        return 1

    monkeypatch.setattr(worker, "execute_query", fake_query)
    monkeypatch.setattr(worker, "execute_update", fake_update)
    monkeypatch.setattr(worker, "complete_agent_run", fake_complete)
    monkeypatch.setattr(worker, "notify_admins", fake_notify)
    monkeypatch.setattr(worker, "_consumer", consumer)
    monkeypatch.setitem(worker.WORKFLOW_MAP, "strategy", graph)
    return {
        "consumer": consumer,
        "updates": updates,
        "completions": completions,
        "notifs": notifs,
        "graph": graph,
    }


def _cas_updates(updates):
    return [
        (sql, params)
        for sql, params in updates
        if "status = 'paused_for_review'" in sql
    ]


# ── The claim (CAS) ──────────────────────────────────────────────────────


class TestResumeClaim:
    def test_winner_claims_with_lease_and_resumes(self, monkeypatch):
        w = _wire(monkeypatch)
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        # CAS shape: paused_for_review → running, stamping OUR lease.
        cas = _cas_updates(w["updates"])
        assert len(cas) == 1
        sql, params = cas[0]
        assert "status = 'running'" in sql
        assert "claimed_by = :wid" in sql
        assert "heartbeat_at = NOW()" in sql
        assert params == {"id": "run-1", "wid": worker.WORKER_ID}
        # The graph got Command(resume=...) on thread_id = run_id.
        (invoke_input, config) = w["graph"].calls[0]
        assert isinstance(invoke_input, Command)
        assert invoke_input.resume == {"decision": "approved", "feedback": None}
        assert config == {"configurable": {"thread_id": "run-1"}}

    def test_cas_loser_acks_without_invoking(self, monkeypatch):
        # Second delivery / second worker: the row is no longer paused when
        # the UPDATE runs — rowcount 0 means someone else won. Ack, no invoke.
        w = _wire(monkeypatch, cas_result=0)
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        assert w["graph"].calls == []
        assert w["completions"] == []

    def test_run_lock_conflict_naks_for_retry(self, monkeypatch):
        # idx_agent_runs_running: another run of this (brand, agent_type) is
        # live — transient, so hand the message back instead of dropping it.
        w = _wire(
            monkeypatch,
            cas_exc=IntegrityError(
                "stmt", {}, Exception("idx_agent_runs_running")
            ),
        )
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert not msg.acked and msg.naks == [300]
        assert w["graph"].calls == []

    def test_non_paused_run_is_a_duplicate(self, monkeypatch):
        w = _wire(
            monkeypatch,
            run_row={
                "brand_id": "b-1",
                "agent_type": "strategy",
                "status": "running",
                "input_payload": "{}",
            },
        )
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        assert _cas_updates(w["updates"]) == []
        assert w["graph"].calls == []


# ── Payload validation (fail closed, never retry garbage) ────────────────


class TestResumeValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"run_id": ""},
            {"workflow_type": "nonsense"},
            {"decision": "maybe"},
            {"decision": None},
        ],
    )
    def test_invalid_payloads_are_dropped(self, monkeypatch, overrides):
        w = _wire(monkeypatch)
        msg = _resume_msg(**overrides)
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        assert w["graph"].calls == []
        assert _cas_updates(w["updates"]) == []

    def test_unknown_run_is_dropped(self, monkeypatch):
        w = _wire(monkeypatch, run_row=False)

        async def no_rows(sql, params=None):
            return []

        monkeypatch.setattr(worker, "execute_query", no_rows)
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        assert w["graph"].calls == []

    def test_workflow_type_mismatch_is_dropped(self, monkeypatch):
        # Resuming through the WRONG graph would feed another workflow's
        # checkpoint this run's Command — fail closed.
        w = _wire(
            monkeypatch,
            run_row={
                "brand_id": "b-1",
                "agent_type": "adaptation",
                "status": "paused_for_review",
                "input_payload": "{}",
            },
        )
        msg = _resume_msg(workflow_type="strategy")
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        assert w["graph"].calls == []
        assert _cas_updates(w["updates"]) == []


# ── Checkpoint-lost invariant ────────────────────────────────────────────


class TestCheckpointLost:
    def test_no_checkpoint_fails_the_run_cleanly(self, monkeypatch):
        w = _wire(monkeypatch, graph=_FakeGraph(has_checkpoint=False))
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        # The graph is NEVER invoked — langgraph would silently re-run it
        # from the entry point instead of raising.
        assert w["graph"].calls == []
        # The claimed run is failed (not left 'running') with an
        # operator-actionable message.
        assert len(w["completions"]) == 1
        run_id, kwargs = w["completions"][0]
        assert run_id == "run-1"
        assert kwargs["status"] == "failed"
        assert "checkpoint lost" in kwargs["error_message"]
        assert "re-run the workflow" in kwargs["error_message"]
        # Operators hear about it.
        assert [n for n in w["notifs"] if n["notification_type"] == "error"]

    def test_probe_error_counts_as_lost(self, monkeypatch):
        class _BrokenSaver:
            async def aget_tuple(self, config):
                raise RuntimeError("saver down")

        graph = _FakeGraph()
        graph.checkpointer = _BrokenSaver()
        w = _wire(monkeypatch, graph=graph)
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked
        assert w["graph"].calls == []
        assert w["completions"][0][1]["status"] == "failed"


# ── Post-invoke path reuse ───────────────────────────────────────────────


_REVIEW_INTERRUPT = Interrupt(
    value={"type": "strategy_review", "brand_id": "b-1", "message": "review"},
    id="intr-2",
)


class TestResumeSettlement:
    def test_interrupt_on_resume_re_pauses(self, monkeypatch):
        # rejected → revision → the graph interrupts AGAIN: the run must land
        # back in paused_for_review with only the interrupt payload, no
        # chaining.
        w = _wire(
            monkeypatch,
            graph=_FakeGraph(
                result={
                    "status": "running",
                    "pillars": [{"name": "P"}],
                    "__interrupt__": [_REVIEW_INTERRUPT],
                }
            ),
        )
        msg = _resume_msg(decision="rejected", feedback="tone is off")
        asyncio.run(worker._handle_message(msg))

        assert msg.acked and not msg.naks
        (invoke_input, _) = w["graph"].calls[0]
        assert invoke_input.resume == {
            "decision": "rejected",
            "feedback": "tone is off",
        }
        run_id, kwargs = w["completions"][0]
        assert kwargs["status"] == "paused_for_review"
        assert kwargs["output_payload"]["paused_for_review"] is True
        assert "pillars" not in kwargs["output_payload"]
        assert w["consumer"].js.published == []

    def test_approved_completion_chains_off_the_original_payload(
        self, monkeypatch
    ):
        # The paused run was dispatched by an activation trigger — once the
        # resume completes it, the activation chain continues to planning
        # exactly as the original message would have.
        w = _wire(monkeypatch, graph=_FakeGraph(result={"status": "approved"}))
        msg = _resume_msg()
        asyncio.run(worker._handle_message(msg))

        assert msg.acked
        assert [c for c in w["completions"] if c[1]["status"] == "completed"]
        assert "planning.trigger" in [
            s for s, _ in w["consumer"].js.published
        ]

    def test_failed_result_fails_the_run_without_chaining(self, monkeypatch):
        # The revision cap: the graph returns status='failed' ("rejected
        # after N revisions") — the run fails, nothing chains.
        w = _wire(
            monkeypatch,
            graph=_FakeGraph(
                result={
                    "status": "failed",
                    "errors": ["strategy rejected after 2 revisions"],
                }
            ),
        )
        msg = _resume_msg(decision="rejected", feedback="still wrong")
        asyncio.run(worker._handle_message(msg))

        assert msg.acked
        assert [c for c in w["completions"] if c[1]["status"] == "failed"]
        assert w["consumer"].js.published == []
