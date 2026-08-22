"""Run leases: birth stamp, 30s heartbeat renewal, claimed_by-scoped drain.

Every agent_runs row a worker creates or resumes carries its lease
(claimed_by=WORKER_ID, heartbeat_at). The heartbeat task renews ONLY rows
this worker owns; the shutdown drain releases ONLY rows this worker owns.
With two workers sharing the stack, neither may ever touch the other's live
rows — the fake DB below enforces the WHERE clause semantics with two
distinct WORKER_IDs instead of only asserting SQL substrings.
"""

import asyncio
import json

import worker
from shared.tools import database


# ── A tiny agent_runs table that honours the lease WHERE clause ──────────


class _LeaseDB:
    """Applies the heartbeat/drain UPDATE semantics to in-memory rows."""

    def __init__(self, rows: dict[str, dict]):
        self.rows = rows  # id → {"status", "claimed_by", "heartbeats": int}
        self.updates: list[tuple[str, dict]] = []

    async def execute_update(self, sql, params=None):
        params = params or {}
        self.updates.append((sql, params))
        row = self.rows.get(params.get("id"))
        if row is None:
            return 0
        if row["status"] != "running":
            return 0
        if "claimed_by = :wid" in sql and row["claimed_by"] != params.get("wid"):
            return 0
        if "SET heartbeat_at" in sql:
            row["heartbeats"] = row.get("heartbeats", 0) + 1
        elif "status = 'failed'" in sql:
            row["status"] = "failed"
        return 1


def _seed_in_flight(run_id: str | None) -> int:
    token = next(worker._in_flight_tokens)
    entry = {
        "msg": None,
        "subject": "strategy.trigger",
        "agent_type": "strategy",
        "payload": {},
        "started": 0.0,
    }
    if run_id is not None:
        entry["run_id"] = run_id
    worker._in_flight[token] = entry
    return token


class TestHeartbeat:
    def setup_method(self):
        worker._in_flight.clear()

    def teardown_method(self):
        worker._in_flight.clear()

    def test_renews_only_registered_runs_owned_by_this_worker(
        self, monkeypatch
    ):
        db = _LeaseDB(
            {
                "run-mine": {"status": "running", "claimed_by": worker.WORKER_ID},
                "run-theirs": {"status": "running", "claimed_by": "other-host:1"},
            }
        )
        monkeypatch.setattr(worker, "execute_update", db.execute_update)
        _seed_in_flight("run-mine")
        _seed_in_flight("run-theirs")  # e.g. a stale registry entry
        _seed_in_flight(None)  # not yet registered — no run row exists

        asyncio.run(worker._heartbeat_once())

        # One per-id UPDATE per REGISTERED id (no ANY() batching), each
        # carrying this worker's id …
        assert len(db.updates) == 2
        for sql, params in db.updates:
            assert "WHERE id = :id" in sql
            assert "status = 'running'" in sql
            assert "claimed_by = :wid" in sql
            assert "ANY(" not in sql
            assert params["wid"] == worker.WORKER_ID
        # … and only OUR row actually renewed.
        assert db.rows["run-mine"].get("heartbeats") == 1
        assert "heartbeats" not in db.rows["run-theirs"]

    def test_one_failing_update_does_not_stop_the_rest(self, monkeypatch):
        renewed: list[str] = []

        async def flaky_update(sql, params=None):
            if params["id"] == "run-bad":
                raise RuntimeError("connection reset")
            renewed.append(params["id"])
            return 1

        monkeypatch.setattr(worker, "execute_update", flaky_update)
        _seed_in_flight("run-bad")
        _seed_in_flight("run-good")

        asyncio.run(worker._heartbeat_once())  # must not raise

        assert renewed == ["run-good"]

    def test_idle_worker_touches_nothing(self, monkeypatch):
        db = _LeaseDB({})
        monkeypatch.setattr(worker, "execute_update", db.execute_update)
        asyncio.run(worker._heartbeat_once())
        assert db.updates == []


# ── Drain release is scoped to this worker's lease ───────────────────────


class _FakeMsg:
    def __init__(self, subject):
        self.subject = subject
        self.acked = False
        self.naks: list = []

    async def ack(self):
        self.acked = True

    async def nak(self, delay=0):
        self.naks.append(delay)


class _FakeConsumer:
    async def shutdown(self):
        pass


class TestDrainLeaseScope:
    def setup_method(self):
        worker._draining = False
        worker._in_flight.clear()
        worker._deferred_naks.clear()
        worker._drain_task = None

    def teardown_method(self):
        worker._draining = False
        worker._in_flight.clear()
        worker._deferred_naks.clear()
        worker._drain_task = None

    def test_drain_never_releases_another_workers_row(self, monkeypatch):
        # Two workers, one DB: our drain hands back our registered run but
        # the row re-claimed by ANOTHER worker id survives untouched.
        monkeypatch.setattr(worker, "DRAIN_BUDGET_SECONDS", 0.05)
        monkeypatch.setattr(worker, "_DRAIN_POLL_SECONDS", 0.01)
        db = _LeaseDB(
            {
                "run-mine": {"status": "running", "claimed_by": worker.WORKER_ID},
                "run-stolen": {"status": "running", "claimed_by": "worker-b:42"},
            }
        )
        monkeypatch.setattr(worker, "execute_update", db.execute_update)

        for rid in ("run-mine", "run-stolen"):
            token = next(worker._in_flight_tokens)
            worker._in_flight[token] = {
                "msg": _FakeMsg("strategy.trigger"),
                "subject": "strategy.trigger",
                "agent_type": "strategy",
                "payload": {},
                "started": 0.0,
                "run_id": rid,
            }

        asyncio.run(worker._drain_and_shutdown(_FakeConsumer()))

        releases = [
            (sql, params)
            for sql, params in db.updates
            if "status = 'failed'" in sql
        ]
        assert len(releases) == 2
        for sql, params in releases:
            assert "claimed_by = :wid" in sql
            assert params["wid"] == worker.WORKER_ID
        assert db.rows["run-mine"]["status"] == "failed"
        # The other worker's lease held: its run is still live.
        assert db.rows["run-stolen"]["status"] == "running"


# ── create_agent_run stamps the lease at birth ───────────────────────────


class _RecordingSession:
    def __init__(self, log):
        self.log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        self.log.append((str(stmt), params or {}))

    async def commit(self):
        pass


class TestCreateAgentRunLease:
    def test_insert_carries_claimed_by_and_heartbeat(self, monkeypatch):
        log: list[tuple[str, dict]] = []
        monkeypatch.setattr(
            database, "async_session_factory", lambda: _RecordingSession(log)
        )

        run_id = asyncio.run(
            database.create_agent_run(
                brand_id="b-1",
                agent_type="strategy",
                trigger="event",
                input_payload={"brand_id": "b-1"},
            )
        )

        assert run_id
        sql, params = log[0]
        assert "claimed_by" in sql and "heartbeat_at" in sql
        assert params["claimed_by"] == database.WORKER_ID
        assert params["heartbeat_at"] is not None
        assert params["id"] == run_id
        assert json.loads(params["input_payload"]) == {"brand_id": "b-1"}
