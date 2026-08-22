"""The sequential content batch lives in the message, not the DB.

Every content.generate in a batch carries the rest of the batch as
remaining_queue — so every path that terminally drops ONE item's message
(workflow failure, code error, rejected run insert, final-delivery discard,
redelivery skip) used to strand every item queued behind it. The worker now
publishes a queue-less continuation (_continue_content_chain) on those paths
so the skip-forward logic re-derives the queue from status='queued' rows;
these tests pin each drop path to that contract, and pin the guards around
it (no respawn for queue-less messages, no replanning from a resume).
"""

import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

import worker
from shared.tools import database


# ── Fakes ────────────────────────────────────────────────────────────────


class _FakeMsg:
    def __init__(self, subject: str, payload: dict, num_delivered: int | None = None):
        self.subject = subject
        self.data = json.dumps(payload).encode()
        self.acked = False
        self.naks: list = []
        if num_delivered is not None:
            self.metadata = SimpleNamespace(num_delivered=num_delivered)

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


class _FakeGraph:
    """Stands in for the content graph; records the initial state it got."""

    def __init__(self, result=None, exc: Exception | None = None):
        self.calls: list[dict] = []
        self.result = result if result is not None else {"status": "completed"}
        self.exc = exc

    async def ainvoke(self, state, config=None):
        self.calls.append(state)
        if self.exc is not None:
            raise self.exc
        return self.result


def _wire(
    monkeypatch,
    *,
    guard_rows=None,
    reel_rows=None,
    queued_rows=None,
    graph=None,
    create_run_exc: Exception | None = None,
):
    """Stub the DB, NATS, and graph around _handle_message.

    Returns a dict of recorders: consumer (published), updates (execute_update
    SQL), notifs (notify_admins calls), graph, calls (create/complete flags).
    """
    consumer = _FakeConsumer()
    updates: list[tuple[str, dict]] = []
    notifs: list[dict] = []
    calls = {"create_run": 0, "completed": []}
    graph = graph or _FakeGraph()

    async def fake_query(sql, params=None):
        if "item_type" in sql:
            return reel_rows or []
        if "SELECT status FROM calendar_items" in sql:
            return guard_rows or []
        if "status = 'queued'" in sql:
            return queued_rows or []
        return []  # brand-name lookup, stage-skip checks, …

    async def fake_update(sql, params=None):
        updates.append((sql, params or {}))
        return 1

    async def fake_create_run(**kwargs):
        calls["create_run"] += 1
        if create_run_exc is not None:
            raise create_run_exc
        return "run-1"

    async def fake_complete_run(run_id, **kwargs):
        calls["completed"].append((run_id, kwargs.get("status")))

    async def fake_notify(**kwargs):
        notifs.append(kwargs)
        return 1

    monkeypatch.setattr(worker, "execute_query", fake_query)
    monkeypatch.setattr(worker, "execute_update", fake_update)
    monkeypatch.setattr(worker, "create_agent_run", fake_create_run)
    monkeypatch.setattr(worker, "complete_agent_run", fake_complete_run)
    monkeypatch.setattr(worker, "notify_admins", fake_notify)
    monkeypatch.setattr(worker, "_consumer", consumer)
    monkeypatch.setitem(worker.WORKFLOW_MAP, "content", graph)
    return {
        "consumer": consumer,
        "updates": updates,
        "notifs": notifs,
        "graph": graph,
        "calls": calls,
    }


def _published(w, subject):
    return [body for subj, body in w["consumer"].js.published if subj == subject]


_BATCH = {
    "brand_id": "b-1",
    "calendar_item_id": "ci-1",
    "trigger": "event",
    "chain_depth": 1,
    "scope_weeks": 2,
    "remaining_queue": ["ci-2", "ci-3"],
}


def _assert_queueless_resume(body):
    """The batch continuation: queue-less, resume-flagged, passthrough intact."""
    assert body.get("resume") is True
    assert "calendar_item_id" not in body
    assert "remaining_queue" not in body
    assert body["brand_id"] == "b-1"
    assert body["trigger"] == "event"
    assert body["chain_depth"] == 1  # passthrough, not incremented
    assert body["scope_weeks"] == 2


# ── Dispatch basics ──────────────────────────────────────────────────────


class TestDispatchBasics:
    def test_auto_approve_is_stripped_from_the_workflow_state(self, monkeypatch):
        # auto_approve is deliberately absent from every payload whitelist —
        # an external message must not be able to skip human review.
        w = _wire(monkeypatch, guard_rows=[{"status": "queued"}])
        payload = {**_BATCH, "auto_approve": True}
        payload.pop("remaining_queue")
        msg = _FakeMsg("content.generate", payload)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert len(w["graph"].calls) == 1
        state = w["graph"].calls[0]
        assert "auto_approve" not in state
        assert state["calendar_item_id"] == "ci-1"

    def test_success_chains_the_next_item_with_the_shrunk_queue(self, monkeypatch):
        w = _wire(monkeypatch, guard_rows=[{"status": "queued"}])
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        nxt = _published(w, "content.generate")
        assert len(nxt) == 1
        assert nxt[0]["calendar_item_id"] == "ci-2"
        assert nxt[0]["remaining_queue"] == ["ci-3"]
        assert nxt[0]["chain_depth"] == 2
        assert nxt[0]["scope_weeks"] == 2


# ── Already-generated guard (redelivery skip) ────────────────────────────


class TestAlreadyGeneratedGuard:
    @pytest.mark.parametrize(
        "status", ["in_review", "approved", "scheduled", "published"]
    )
    def test_skip_still_continues_the_batch(self, monkeypatch, status):
        w = _wire(monkeypatch, guard_rows=[{"status": status}])
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked and not msg.naks
        assert w["calls"]["create_run"] == 0
        cont = _published(w, "content.generate")
        assert len(cont) == 1
        _assert_queueless_resume(cont[0])


# ── Reel divert ──────────────────────────────────────────────────────────


class TestReelDivert:
    def test_queued_reel_is_diverted_and_the_chain_continues(self, monkeypatch):
        w = _wire(
            monkeypatch,
            guard_rows=[{"status": "queued"}],
            reel_rows=[{"item_type": "reel", "status": "queued"}],
        )
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert w["calls"]["create_run"] == 0
        renders = _published(w, "video.render")
        assert len(renders) == 1
        assert renders[0]["calendar_item_id"] == "ci-1"
        nxt = _published(w, "content.generate")
        assert len(nxt) == 1
        assert nxt[0]["calendar_item_id"] == "ci-2"
        assert nxt[0]["remaining_queue"] == ["ci-3"]

    def test_in_flight_reel_is_not_rediverted_but_the_chain_continues(
        self, monkeypatch
    ):
        # 'rendering' = a render already owns this reel; re-publishing
        # video.render is the duplicate-GPU-run path. The batch must still
        # move — via the explicit next-item message, shared with the divert
        # branch. (A reel already in_review is intercepted by the
        # already-generated guard instead, covered above.)
        w = _wire(
            monkeypatch,
            guard_rows=[{"status": "rendering"}],
            reel_rows=[{"item_type": "reel", "status": "rendering"}],
        )
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert _published(w, "video.render") == []
        nxt = _published(w, "content.generate")
        assert len(nxt) == 1
        assert nxt[0]["calendar_item_id"] == "ci-2"


# ── Terminal drop paths must continue the batch ──────────────────────────


class TestTerminalDropsContinueTheBatch:
    def test_workflow_failed(self, monkeypatch):
        w = _wire(
            monkeypatch,
            guard_rows=[{"status": "queued"}],
            graph=_FakeGraph(result={"status": "failed", "error": "image API dead"}),
        )
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert w["calls"]["completed"] == [("run-1", "failed")]
        # No next-item chain — only the queue-less continuation.
        cont = _published(w, "content.generate")
        assert len(cont) == 1
        _assert_queueless_resume(cont[0])
        # The stuck item was released…
        assert any(
            "UPDATE calendar_items" in sql and "'failed'" in sql
            for sql, _ in w["updates"]
        )
        # …and admins were told. 'error' is deliberate: it is in the
        # notifications CHECK constraint's allowed set, while a bespoke
        # 'workflow_failed' type would violate the CHECK and die as a
        # warning log — the exact silence the alert exists to end.
        assert len(w["notifs"]) == 1
        assert w["notifs"][0]["notification_type"] == "error"

    def test_broad_except(self, monkeypatch):
        w = _wire(
            monkeypatch,
            guard_rows=[{"status": "queued"}],
            graph=_FakeGraph(exc=RuntimeError("boom")),
        )
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked and not msg.naks
        cont = _published(w, "content.generate")
        assert len(cont) == 1
        _assert_queueless_resume(cont[0])
        assert len(w["notifs"]) == 1

    def test_run_insert_rejected_fails_the_queued_item_out(self, monkeypatch):
        # A check/FK violation is deterministic — retrying re-derives the same
        # item into the same wall, so the item must leave the queue too.
        rejected = IntegrityError(
            "stmt",
            {},
            Exception(
                'new row for relation "agent_runs" violates check constraint '
                '"agent_runs_trigger_check"'
            ),
        )
        w = _wire(
            monkeypatch, guard_rows=[{"status": "queued"}], create_run_exc=rejected
        )
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked and not msg.naks
        cont = _published(w, "content.generate")
        assert len(cont) == 1
        _assert_queueless_resume(cont[0])
        assert any(
            "'queued', 'working'" in sql and "'failed'" in sql
            for sql, _ in w["updates"]
        ), "the still-queued item must be failed out or re-derivation ping-pongs"
        assert len(w["notifs"]) == 1

    def test_notify_failure_never_breaks_the_ack_path(self, monkeypatch):
        _wire(
            monkeypatch,
            guard_rows=[{"status": "queued"}],
            graph=_FakeGraph(exc=RuntimeError("boom")),
        )

        async def broken_notify(**kwargs):
            raise RuntimeError("notifications table gone")

        monkeypatch.setattr(worker, "notify_admins", broken_notify)
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked


class TestDuplicateRun:
    _DUP = IntegrityError(
        "stmt",
        {},
        Exception('duplicate key value violates unique constraint "idx_agent_runs_running"'),
    )

    def test_batch_message_retries_instead_of_dropping_the_queue(self, monkeypatch):
        # "Already running" is transient (live run or reaper-cleared zombie) —
        # nak like video does; the remaining_queue survives inside the message.
        w = _wire(
            monkeypatch, guard_rows=[{"status": "queued"}], create_run_exc=self._DUP
        )
        msg = _FakeMsg("content.generate", _BATCH)
        asyncio.run(worker._handle_message(msg))
        assert msg.naks == [300] and not msg.acked
        assert _published(w, "content.generate") == []

    def test_final_delivery_hands_the_batch_to_rederivation(self, monkeypatch):
        # On attempt max_deliver a nak is a silent discard — the batch's last
        # carrier must publish the continuation before it dies.
        w = _wire(
            monkeypatch, guard_rows=[{"status": "queued"}], create_run_exc=self._DUP
        )
        msg = _FakeMsg("content.generate", _BATCH, num_delivered=worker._MAX_DELIVER)
        asyncio.run(worker._handle_message(msg))
        assert msg.acked and not msg.naks
        cont = _published(w, "content.generate")
        assert len(cont) == 1
        _assert_queueless_resume(cont[0])

    def test_queueless_duplicate_still_just_acks(self, monkeypatch):
        _wire(
            monkeypatch, guard_rows=[{"status": "queued"}], create_run_exc=self._DUP
        )
        msg = _FakeMsg("content.generate", {"brand_id": "b-1", "trigger": "event"})
        asyncio.run(worker._handle_message(msg))
        # No calendar_item_id → skip-forward path runs first; give it no rows
        # so it falls through… it re-triggers planning, acks, and never
        # reaches create_agent_run — the duplicate branch stays untouched.
        assert msg.acked


class TestTimeoutDiscard:
    def test_non_final_timeout_naks_without_continuation(self, monkeypatch):
        w = _wire(
            monkeypatch,
            guard_rows=[{"status": "queued"}],
            graph=_FakeGraph(exc=asyncio.TimeoutError()),
        )
        msg = _FakeMsg("content.generate", _BATCH)  # no metadata → attempt 1
        asyncio.run(worker._handle_message(msg))
        assert msg.naks == [60] and not msg.acked
        # A retry is coming with the queue intact — publishing now would
        # double the chain.
        assert _published(w, "content.generate") == []
        assert w["notifs"] == []

    def test_final_timeout_publishes_the_continuation(self, monkeypatch):
        w = _wire(
            monkeypatch,
            guard_rows=[{"status": "queued"}],
            graph=_FakeGraph(exc=asyncio.TimeoutError()),
        )
        msg = _FakeMsg("content.generate", _BATCH, num_delivered=worker._MAX_DELIVER)
        asyncio.run(worker._handle_message(msg))
        assert msg.naks == [60]
        cont = _published(w, "content.generate")
        assert len(cont) == 1
        _assert_queueless_resume(cont[0])
        assert len(w["notifs"]) == 1


# ── The continuation helper's own termination contract ───────────────────


class TestContinueContentChainHelper:
    def _consumer(self, monkeypatch):
        consumer = _FakeConsumer()
        monkeypatch.setattr(worker, "_consumer", consumer)
        return consumer

    def test_queueless_message_never_respawns(self, monkeypatch):
        # The helper's own continuations are queue-less — if they could
        # trigger the helper again, a failing brand would loop forever.
        c = self._consumer(monkeypatch)
        asyncio.run(
            worker._continue_content_chain(
                "content", {"brand_id": "b-1", "resume": True}, "test"
            )
        )
        assert c.js.published == []

    def test_empty_remaining_queue_does_not_count_as_a_batch(self, monkeypatch):
        c = self._consumer(monkeypatch)
        asyncio.run(
            worker._continue_content_chain(
                "content", {"brand_id": "b-1", "remaining_queue": []}, "test"
            )
        )
        assert c.js.published == []

    def test_calendar_item_id_alone_does_not_respawn(self, monkeypatch):
        # A single-item message (manual generate, morning top-up) strands
        # nothing behind it — letting it respawn made every routine
        # redelivery sweep the brand's whole queue into generation. Only a
        # non-empty remaining_queue proves a batch is stranded.
        c = self._consumer(monkeypatch)
        asyncio.run(
            worker._continue_content_chain(
                "content", {"brand_id": "b-1", "calendar_item_id": "ci-9"}, "test"
            )
        )
        assert c.js.published == []

    def test_remaining_queue_triggers_respawn(self, monkeypatch):
        c = self._consumer(monkeypatch)
        asyncio.run(
            worker._continue_content_chain(
                "content",
                {
                    "brand_id": "b-1",
                    "calendar_item_id": "ci-9",
                    "remaining_queue": ["ci-10"],
                },
                "test",
            )
        )
        assert len(c.js.published) == 1
        subj, body = c.js.published[0]
        assert subj == "content.generate"
        assert body["resume"] is True and "calendar_item_id" not in body

    def test_only_content_messages_qualify(self, monkeypatch):
        c = self._consumer(monkeypatch)
        asyncio.run(
            worker._continue_content_chain(
                "video", {"brand_id": "b-1", "calendar_item_id": "ci-9"}, "test"
            )
        )
        assert c.js.published == []

    def test_never_raises_even_when_publish_does(self, monkeypatch):
        class _BrokenJS:
            async def publish(self, subject, data):
                raise ConnectionError("nats gone")

        monkeypatch.setattr(
            worker, "_consumer", SimpleNamespace(js=_BrokenJS())
        )
        asyncio.run(  # must not raise — the caller is on its ack path
            worker._continue_content_chain(
                "content", {"brand_id": "b-1", "remaining_queue": ["x"]}, "test"
            )
        )

    def test_no_consumer_is_a_noop(self, monkeypatch):
        monkeypatch.setattr(worker, "_consumer", None)
        asyncio.run(
            worker._continue_content_chain(
                "content", {"brand_id": "b-1", "remaining_queue": ["x"]}, "test"
            )
        )


# ── Skip-forward (queue-less content.generate) ───────────────────────────


class TestSkipForward:
    def test_derives_the_queue_and_publishes_the_first_item(self, monkeypatch):
        w = _wire(monkeypatch, queued_rows=[{"id": "i1"}, {"id": "i2"}, {"id": "i3"}])
        msg = _FakeMsg(
            "content.generate",
            {"brand_id": "b-1", "trigger": "activation", "scope_weeks": 1},
        )
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert w["calls"]["create_run"] == 0
        first = _published(w, "content.generate")
        assert len(first) == 1
        assert first[0]["calendar_item_id"] == "i1"
        assert first[0]["remaining_queue"] == ["i2", "i3"]

    def test_resume_with_no_queued_items_never_replans(self, monkeypatch):
        # The destructive branch: no queued items normally deletes completed
        # planning runs and re-triggers planning. A batch resume reaching it
        # would turn one failed last item into an endless plan→generate loop.
        w = _wire(monkeypatch, queued_rows=[])
        msg = _FakeMsg(
            "content.generate",
            {"brand_id": "b-1", "trigger": "event", "resume": True},
        )
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert w["consumer"].js.published == []
        assert not any("DELETE FROM agent_runs" in sql for sql, _ in w["updates"])

    def test_resume_does_not_promote_planned_items(self, monkeypatch):
        # A resume finishes the queue the dead batch was already walking;
        # promoting planned→queued here would pull FUTURE planned items into
        # generation on the back of an unrelated failure.
        w = _wire(monkeypatch, queued_rows=[{"id": "i1"}])
        msg = _FakeMsg(
            "content.generate",
            {"brand_id": "b-1", "trigger": "event", "resume": True},
        )
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert not any(
            "SET status = 'queued'" in sql and "status = 'planned'" in sql
            for sql, _ in w["updates"]
        )
        # The already-queued item still gets its chain.
        first = _published(w, "content.generate")
        assert len(first) == 1 and first[0]["calendar_item_id"] == "i1"

    def test_activation_still_promotes_planned_items(self, monkeypatch):
        w = _wire(monkeypatch, queued_rows=[{"id": "i1"}])
        msg = _FakeMsg(
            "content.generate", {"brand_id": "b-1", "trigger": "activation"}
        )
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert any(
            "SET status = 'queued'" in sql and "status = 'planned'" in sql
            for sql, _ in w["updates"]
        )

    def test_without_resume_no_queued_items_still_replans(self, monkeypatch):
        # Pins the pre-existing activation behaviour the resume flag must
        # not disturb.
        w = _wire(monkeypatch, queued_rows=[])
        msg = _FakeMsg(
            "content.generate", {"brand_id": "b-1", "trigger": "activation"}
        )
        asyncio.run(worker._handle_message(msg))
        assert msg.acked
        assert len(_published(w, "planning.trigger")) == 1
        assert any("DELETE FROM agent_runs" in sql for sql, _ in w["updates"])


# ── store_content: demote before insert, supersede pending approvals ─────


class _FakeSession:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def execute(self, stmt, params=None):
        self.log.append((str(stmt), params or {}))

    async def commit(self):
        self.log.append(("COMMIT", {}))


class TestStoreContent:
    _DATA = {
        "brand_id": "b-1",
        "calendar_item_id": "ci-1",
        "headline": "Fresh headline",
        "caption": "Fresh caption",
    }

    def _run(self, monkeypatch, data):
        log: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            database, "async_session_factory", lambda: _FakeSession(log)
        )
        content_id = asyncio.run(database.store_content(dict(data)))
        return content_id, log

    def test_demote_then_supersede_then_insert_in_one_transaction(self, monkeypatch):
        content_id, log = self._run(monkeypatch, self._DATA)
        assert content_id
        sqls = [sql for sql, _ in log]
        demote = next(
            i for i, s in enumerate(sqls) if "SET is_current = false" in s
        )
        supersede = next(i for i, s in enumerate(sqls) if "UPDATE approvals" in s)
        insert = next(i for i, s in enumerate(sqls) if "INSERT INTO content" in s)
        commit = sqls.index("COMMIT")
        # Reviewers were approving version N while looking at N+1 — the old
        # pending row must die in the same transaction that demotes N.
        assert demote < supersede < insert < commit

    def test_supersede_targets_only_pending_rows_of_this_item(self, monkeypatch):
        _, log = self._run(monkeypatch, self._DATA)
        sql, params = next(
            (s, p) for s, p in log if "UPDATE approvals" in s
        )
        assert "status = 'pending'" in sql  # WHERE — never touches decided rows
        assert "'revision_requested'" in sql  # allowed by the status CHECK
        assert params["cid"] == "ci-1"
        assert "Superseded" in params["note"]

    def test_no_calendar_item_means_no_demote_and_no_supersede(self, monkeypatch):
        data = {k: v for k, v in self._DATA.items() if k != "calendar_item_id"}
        _, log = self._run(monkeypatch, data)
        sqls = [sql for sql, _ in log]
        assert not any("SET is_current = false" in s for s in sqls)
        assert not any("UPDATE approvals" in s for s in sqls)
        assert any("INSERT INTO content" in s for s in sqls)
