"""The durable checkpointer's tables get pruned — and only when it is safe.

AsyncPostgresSaver writes checkpoint rows for every checkpointed
strategy/adaptation run and langgraph never deletes them, so the tables grew
without bound. The worker's daily retention sweep deletes the rows of runs
that reached a terminal status more than CHECKPOINT_RETENTION_DAYS ago.
These tests pin the sweep's contract: all three data tables cleared per
thread with ``checkpoints`` last (it drives the SELECT, so a half-deleted
thread is re-selected next pass), one bad thread never stops the rest, a
zero-progress pass ends the sweep instead of hammering the same failures,
and a sweep failure is swallowed — pruning must never affect run processing.
"""

import asyncio

import worker


def _install_db(monkeypatch, batches, fail_threads=()):
    """Wire fake execute_query/execute_update into worker.

    ``batches`` is a list of thread-id lists returned by successive SELECTs.
    Threads in ``fail_threads`` make their FIRST delete raise. Returns the
    log of (table, thread_id) deletes that succeeded.
    """
    deletes: list[tuple[str, str]] = []
    selects = {"count": 0}

    async def fake_query(query, params=None):
        assert "FROM checkpoints c" in query
        assert "agent_runs" in query
        assert "'completed', 'failed', 'cancelled'" in query
        i = selects["count"]
        selects["count"] += 1
        rows = batches[i] if i < len(batches) else []
        return [{"thread_id": tid} for tid in rows]

    async def fake_update(query, params=None):
        table = query.split("DELETE FROM ", 1)[1].split(" ", 1)[0]
        tid = params["tid"]
        if tid in fail_threads:
            raise RuntimeError(f"db down for {tid}")
        deletes.append((table, tid))
        return 1

    monkeypatch.setattr(worker, "execute_query", fake_query)
    monkeypatch.setattr(worker, "execute_update", fake_update)
    return deletes, selects


class TestPruneOnce:
    def test_all_three_tables_cleared_checkpoints_last(self, monkeypatch):
        deletes, _ = _install_db(monkeypatch, [["t1"], []])
        pruned = asyncio.run(worker._prune_checkpoints_once())
        assert pruned == 1
        assert deletes == [
            ("checkpoint_writes", "t1"),
            ("checkpoint_blobs", "t1"),
            ("checkpoints", "t1"),
        ], "checkpoints must go LAST so a half-deleted thread is re-selected"

    def test_one_bad_thread_never_stops_the_rest(self, monkeypatch):
        deletes, _ = _install_db(
            monkeypatch, [["t1", "t2", "t3"], []], fail_threads={"t2"}
        )
        pruned = asyncio.run(worker._prune_checkpoints_once())
        assert pruned == 2
        pruned_tids = {tid for table, tid in deletes if table == "checkpoints"}
        assert pruned_tids == {"t1", "t3"}

    def test_nothing_to_prune_is_a_quiet_zero(self, monkeypatch):
        deletes, selects = _install_db(monkeypatch, [[]])
        assert asyncio.run(worker._prune_checkpoints_once()) == 0
        assert deletes == []
        assert selects["count"] == 1

    def test_a_full_batch_paginates_until_drained(self, monkeypatch):
        monkeypatch.setattr(worker, "_CHECKPOINT_SWEEP_BATCH", 2)
        deletes, selects = _install_db(monkeypatch, [["t1", "t2"], ["t3"]])
        pruned = asyncio.run(worker._prune_checkpoints_once())
        assert pruned == 3
        # second batch was short — no third SELECT needed
        assert selects["count"] == 2

    def test_a_zero_progress_pass_ends_the_sweep(self, monkeypatch):
        # Every candidate fails: without the progress guard the sweep would
        # re-select the same ids _CHECKPOINT_SWEEP_MAX_BATCHES times over.
        monkeypatch.setattr(worker, "_CHECKPOINT_SWEEP_BATCH", 1)
        deletes, selects = _install_db(
            monkeypatch, [["t1"]] * 50, fail_threads={"t1"}
        )
        assert asyncio.run(worker._prune_checkpoints_once()) == 0
        assert selects["count"] == 1

    def test_one_sweep_is_bounded_even_with_a_huge_backlog(self, monkeypatch):
        monkeypatch.setattr(worker, "_CHECKPOINT_SWEEP_BATCH", 1)
        batches = [[f"t{i}"] for i in range(100)]
        _, selects = _install_db(monkeypatch, batches)
        pruned = asyncio.run(worker._prune_checkpoints_once())
        assert pruned == worker._CHECKPOINT_SWEEP_MAX_BATCHES
        assert selects["count"] == worker._CHECKPOINT_SWEEP_MAX_BATCHES


class TestRetentionLoop:
    def test_a_sweep_failure_is_swallowed_and_the_loop_lives_on(
        self, monkeypatch
    ):
        # First sweep blows up (e.g. MemorySaver fallback — tables absent);
        # the loop must swallow it and come back for the next day's sleep.
        async def boom():
            raise RuntimeError("relation \"checkpoints\" does not exist")

        sleeps: list[float] = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) >= 2:  # survived one failed sweep — enough proof
                raise asyncio.CancelledError

        monkeypatch.setattr(worker, "_prune_checkpoints_once", boom)
        monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

        async def run():
            try:
                await worker._checkpoint_retention_loop()
            except asyncio.CancelledError:
                return "cancelled"

        assert asyncio.run(run()) == "cancelled"
        assert sleeps[0] == worker.CHECKPOINT_SWEEP_STARTUP_DELAY_SECONDS
        assert sleeps[1] == worker.CHECKPOINT_SWEEP_INTERVAL_SECONDS

    def test_the_first_sweep_does_not_wait_a_whole_day(self):
        # Push-to-main auto-deploys restart the worker often; a loop that
        # slept 24h before its first pass would never actually prune.
        assert (
            worker.CHECKPOINT_SWEEP_STARTUP_DELAY_SECONDS
            < worker.CHECKPOINT_SWEEP_INTERVAL_SECONDS / 100
        )
