"""SIGTERM drains the worker instead of killing the in-flight run.

A redeploy recreates the agents container mid-workflow: the run used to die
with it, the calendar item stranded until the release guards fired, and
JetStream redelivered the message hours later (or, for video, re-rendered
the reel — the measured 2026-08-20 duplicate-render incident). The worker
now drains on SIGTERM/SIGINT: the dispatch gate stops NEW work immediately,
in-flight workflows get the remaining grace budget, and whatever cannot
finish is nak'd back with a short delay at exit — deferred to exit on
purpose, because compose starts the replacement container only after this
one is gone, so an earlier nak could only bounce off this container's own
gate and burn max_deliver attempts.

Windows note: production is Linux under docker where loop.add_signal_handler
works; these tests exercise the handler functions directly, never OS signals.
"""

import asyncio
import json
import signal

import pytest

import worker
from shared.nats_consumer import ACK_WAIT_SECONDS


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


class _FakeConsumer:
    def __init__(self):
        self.shutdowns = 0

    async def shutdown(self):
        self.shutdowns += 1


@pytest.fixture(autouse=True)
def _clean_drain_state(monkeypatch):
    """Drain state is module-global; every test starts and ends clean.

    execute_update is stubbed because any drain that abandons or outlives a
    workflow releases its agent_runs row — a real connection attempt here
    would hang the event loop past every wait_for in this file.
    """
    worker._draining = False
    worker._in_flight.clear()
    worker._deferred_naks.clear()
    worker._drain_task = None
    monkeypatch.setattr(worker, "_DRAIN_POLL_SECONDS", 0.01)

    released: list = []

    async def fake_update(sql, params=None):
        released.append(sql)
        return 0

    monkeypatch.setattr(worker, "execute_update", fake_update)
    yield
    worker._draining = False
    worker._in_flight.clear()
    worker._deferred_naks.clear()
    worker._drain_task = None


def _seed(msg: _FakeMsg, payload: dict, agent_type: str | None = None) -> int:
    """Put an entry in the in-flight registry without running a handler.

    Mirrors a workflow that keeps running until process exit — exactly the
    shape the drain has to reason about.
    """
    token = next(worker._in_flight_tokens)
    worker._in_flight[token] = {
        "msg": msg,
        "subject": msg.subject,
        "agent_type": agent_type or msg.subject.split(".")[0],
        "payload": payload,
        "started": 0.0,
    }
    return token


# ── The dispatch gate ────────────────────────────────────────────────────


class TestDrainGate:
    def test_draining_flag_stops_new_dispatch(self, monkeypatch):
        handled = []

        async def fake_handle(msg):
            handled.append(msg)

        monkeypatch.setattr(worker, "_handle_message", fake_handle)
        worker._draining = True
        msg = _FakeMsg("content.generate", {"brand_id": "b-1"})
        asyncio.run(worker._dispatch_message(msg))
        assert handled == []
        # Held, not settled — the nak fires at exit so it cannot bounce
        # back onto this container's own gate.
        assert not msg.acked and not msg.naks
        assert worker._deferred_naks[0]["msg"] is msg
        assert worker._in_flight == {}

    def test_gate_held_messages_are_naked_at_exit(self):
        consumer = _FakeConsumer()

        async def scenario():
            worker._draining = True
            msg = _FakeMsg("planning.trigger", {"brand_id": "b-1"})
            await worker._dispatch_message(msg)  # gate holds it
            await worker._drain_and_shutdown(consumer)
            return msg

        msg = asyncio.run(scenario())
        assert msg.naks == [worker.DRAIN_NAK_DELAY_SECONDS]
        assert consumer.shutdowns == 1
        assert worker._deferred_naks == []

    def test_normal_dispatch_registers_then_unregisters(self, monkeypatch):
        seen = {}

        async def fake_handle(msg):
            seen["in_flight"] = dict(worker._in_flight)

        monkeypatch.setattr(worker, "_handle_message", fake_handle)
        msg = _FakeMsg("research.trigger", {"brand_id": "b-1"})
        asyncio.run(worker._dispatch_message(msg))
        assert len(seen["in_flight"]) == 1
        entry = next(iter(seen["in_flight"].values()))
        assert entry["agent_type"] == "research"
        assert entry["payload"]["brand_id"] == "b-1"
        assert entry["msg"] is msg
        assert worker._in_flight == {}

    def test_registry_pops_even_when_the_handler_raises(self, monkeypatch):
        async def broken(msg):
            raise RuntimeError("boom")

        monkeypatch.setattr(worker, "_handle_message", broken)
        with pytest.raises(RuntimeError):
            asyncio.run(worker._dispatch_message(_FakeMsg("content.generate", {})))
        assert worker._in_flight == {}


# ── Waiting out the in-flight work ───────────────────────────────────────


class TestDrainWaitsForInFlight:
    def test_in_flight_completion_is_awaited(self, monkeypatch):
        consumer = _FakeConsumer()
        order = []

        async def scenario():
            release = asyncio.Event()

            async def slow_handle(msg):
                await release.wait()
                order.append("workflow finished")

            monkeypatch.setattr(worker, "_handle_message", slow_handle)
            msg = _FakeMsg("content.generate", {"brand_id": "b-1"})
            work = asyncio.ensure_future(worker._dispatch_message(msg))
            await asyncio.sleep(0)  # let it register and suspend
            drain = asyncio.ensure_future(worker._drain_and_shutdown(consumer))
            await asyncio.sleep(0.05)
            assert consumer.shutdowns == 0  # still waiting on the workflow
            release.set()
            await asyncio.wait_for(drain, timeout=2)
            order.append("drain finished")
            await work
            return msg

        msg = asyncio.run(scenario())
        assert order == ["workflow finished", "drain finished"]
        assert consumer.shutdowns == 1
        # A run that finished inside the budget settles its own message —
        # the drain must not hand it back on top.
        assert msg.naks == []

    def test_budget_expiry_naks_with_short_delay(self, monkeypatch):
        consumer = _FakeConsumer()
        monkeypatch.setattr(worker, "DRAIN_BUDGET_SECONDS", 0.05)

        async def scenario():
            hang = asyncio.Event()

            async def never_finishes(msg):
                await hang.wait()

            monkeypatch.setattr(worker, "_handle_message", never_finishes)
            msg = _FakeMsg("content.generate", {"brand_id": "b-1"})
            work = asyncio.ensure_future(worker._dispatch_message(msg))
            await asyncio.sleep(0)
            await asyncio.wait_for(worker._drain_and_shutdown(consumer), timeout=2)
            # Cancel-before-nak: the drain itself cancels the over-budget
            # handler and awaits it before nak'ing, so by the time it
            # returns the task is settled — no cleanup left for the test.
            assert work.cancelled()
            return msg

        msg = asyncio.run(scenario())
        assert msg.naks == [worker.DRAIN_NAK_DELAY_SECONDS]
        assert not msg.acked
        assert consumer.shutdowns == 1

    def test_settled_abandoned_message_is_not_double_settled(self):
        # An abandoned run that manages to ack/nak its own message before
        # exit (the token left the registry) must not be nak'd again; a
        # gate-held message (token None) always is.
        consumer = _FakeConsumer()
        settled = _FakeMsg("video.render", {})
        held = _FakeMsg("content.generate", {})
        worker._deferred_naks.append(
            {"msg": settled, "label": "video.render", "token": 99}
        )
        worker._deferred_naks.append(
            {"msg": held, "label": "content.generate", "token": None}
        )
        asyncio.run(worker._drain_and_shutdown(consumer))
        assert settled.naks == []
        assert held.naks == [worker.DRAIN_NAK_DELAY_SECONDS]

    def test_nak_failure_never_blocks_the_exit(self):
        consumer = _FakeConsumer()

        class _BrokenMsg(_FakeMsg):
            async def nak(self, delay=0):
                raise ConnectionError("nats gone")

        worker._deferred_naks.append(
            {"msg": _BrokenMsg("content.generate", {}), "label": "x", "token": None}
        )
        asyncio.run(worker._drain_and_shutdown(consumer))  # must not raise
        assert consumer.shutdowns == 1


# ── Video triage ─────────────────────────────────────────────────────────


class TestVideoTriage:
    _PAYLOAD = {"brand_id": "b-1", "calendar_item_id": "ci-1"}

    def test_pre_forge_video_is_handed_back_without_waiting(self, monkeypatch):
        # Budget far above the wait_for timeout: if the triage failed to
        # abandon the render, the drain would wait it out and the test
        # would time out — returning fast IS the assertion.
        consumer = _FakeConsumer()
        monkeypatch.setattr(worker, "DRAIN_BUDGET_SECONDS", 30)

        async def fake_query(sql, params=None):
            return [{"stage": None}]

        monkeypatch.setattr(worker, "execute_query", fake_query)
        msg = _FakeMsg("video.render", self._PAYLOAD)
        _seed(msg, self._PAYLOAD)
        asyncio.run(
            asyncio.wait_for(worker._drain_and_shutdown(consumer), timeout=2)
        )
        assert msg.naks == [worker.DRAIN_NAK_DELAY_SECONDS]
        assert consumer.shutdowns == 1

    def test_submitted_video_is_waited_for_not_handed_back(self, monkeypatch):
        # Once a render job is live, a duplicate render costs more than the
        # wait: the drain polls until the run settles its own message.
        consumer = _FakeConsumer()

        async def fake_query(sql, params=None):
            return [{"stage": "shot 2/7:forge:running"}]

        monkeypatch.setattr(worker, "execute_query", fake_query)

        async def scenario():
            msg = _FakeMsg("video.render", self._PAYLOAD)
            token = _seed(msg, self._PAYLOAD)

            async def finish_later():
                await asyncio.sleep(0.05)
                msg.acked = True
                worker._in_flight.pop(token)

            fin = asyncio.ensure_future(finish_later())
            await asyncio.wait_for(worker._drain_and_shutdown(consumer), timeout=2)
            await fin
            return msg

        msg = asyncio.run(scenario())
        # Had the triage abandoned it, the exit nak would have fired before
        # finish_later's pop — naks stay empty only on the waiting path.
        assert msg.naks == []
        assert msg.acked

    def test_non_video_workflows_are_never_triaged(self, monkeypatch):
        # A content run gets the budget, full stop — no progress probe.
        consumer = _FakeConsumer()
        monkeypatch.setattr(worker, "DRAIN_BUDGET_SECONDS", 0.05)
        probes = []

        async def fake_query(sql, params=None):
            probes.append(sql)
            return []

        monkeypatch.setattr(worker, "execute_query", fake_query)
        msg = _FakeMsg("content.generate", self._PAYLOAD)
        _seed(msg, self._PAYLOAD)
        asyncio.run(worker._drain_and_shutdown(consumer))
        assert probes == []
        assert msg.naks == [worker.DRAIN_NAK_DELAY_SECONDS]  # budget path


class TestVideoReachedForge:
    def test_no_item_id_means_wait(self):
        # No probe target → wait the budget like everything else.
        assert asyncio.run(worker._video_reached_forge({})) is True

    def test_stage_present_means_submitted(self, monkeypatch):
        async def q(sql, params=None):
            return [{"stage": "multishot:forge:running"}]

        monkeypatch.setattr(worker, "execute_query", q)
        assert (
            asyncio.run(worker._video_reached_forge({"calendar_item_id": "ci-1"}))
            is True
        )

    def test_null_stage_means_not_submitted(self, monkeypatch):
        # video_progress is written by provider polls and finishing passes
        # only — nothing before job submission touches it.
        async def q(sql, params=None):
            return [{"stage": None}]

        monkeypatch.setattr(worker, "execute_query", q)
        assert (
            asyncio.run(worker._video_reached_forge({"calendar_item_id": "ci-1"}))
            is False
        )

    def test_missing_row_means_not_submitted(self, monkeypatch):
        async def q(sql, params=None):
            return []

        monkeypatch.setattr(worker, "execute_query", q)
        assert (
            asyncio.run(worker._video_reached_forge({"calendar_item_id": "ci-1"}))
            is False
        )

    def test_db_error_means_wait(self, monkeypatch):
        async def q(sql, params=None):
            raise RuntimeError("db down")

        monkeypatch.setattr(worker, "execute_query", q)
        assert (
            asyncio.run(worker._video_reached_forge({"calendar_item_id": "ci-1"}))
            is True
        )


# ── Signal wiring ────────────────────────────────────────────────────────


class TestSignalRegistration:
    def test_registers_sigterm_and_sigint_on_the_loop(self):
        class _Loop:
            def __init__(self):
                self.registered = {}

            def add_signal_handler(self, sig, cb):
                self.registered[sig] = cb

        loop = _Loop()
        hits = []
        worker._install_signal_handlers(loop, lambda: hits.append(1))
        assert set(loop.registered) == {signal.SIGINT, signal.SIGTERM}
        loop.registered[signal.SIGTERM]()
        assert hits == [1]

    def test_windows_falls_back_to_signal_signal(self, monkeypatch):
        # loop.add_signal_handler raises NotImplementedError on Windows
        # event loops; production (Linux/docker) never takes this branch.
        class _Loop:
            def add_signal_handler(self, sig, cb):
                raise NotImplementedError

        recorded = {}
        monkeypatch.setattr(
            signal, "signal", lambda sig, h: recorded.setdefault(sig, h)
        )
        hits = []
        worker._install_signal_handlers(_Loop(), lambda: hits.append(1))
        assert set(recorded) == {signal.SIGINT, signal.SIGTERM}
        recorded[signal.SIGTERM](signal.SIGTERM, None)  # (signum, frame)
        assert hits == [1]


class TestRequestDrain:
    def test_drain_starts_once_and_repeat_signals_are_ignored(self):
        # docker escalates to SIGKILL after the grace period on its own —
        # a second SIGTERM must not restart the clock or double-nak.
        consumer = _FakeConsumer()

        async def scenario():
            worker._request_drain(consumer)
            first = worker._drain_task
            assert first is not None
            worker._request_drain(consumer)  # second SIGTERM mid-drain
            assert worker._drain_task is first
            await asyncio.wait_for(first, timeout=2)

        asyncio.run(scenario())
        assert consumer.shutdowns == 1


# ── Deploy-facing invariants ─────────────────────────────────────────────


class TestConfigInvariants:
    def test_budget_fits_inside_the_compose_grace_period(self):
        # docker-compose.yml sets stop_grace_period: 15m — the budget plus
        # the exit tail (naks + NATS close) must beat the SIGKILL.
        assert worker.DRAIN_BUDGET_SECONDS < 15 * 60

    def test_nak_delay_is_prompt_not_ack_wait(self):
        # The whole point of the exit nak: redelivery lands about one delay
        # after the new container subscribes, not after a multi-hour
        # ack_wait times out.
        assert worker.DRAIN_NAK_DELAY_SECONDS < ACK_WAIT_SECONDS
