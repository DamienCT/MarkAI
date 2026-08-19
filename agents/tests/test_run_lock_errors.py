"""Only the idempotency index means "already running".

A video.render message carrying trigger='manual-qa' violated
agent_runs_trigger_check. The worker caught the IntegrityError, logged
"Video render for brand ... already running", and NAK'd with a 5-minute
delay — forever, for a message that could never insert. The reel sat in
'queued' while the logs blamed a run that did not exist.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from worker import _is_duplicate_run_error  # noqa: E402


class _Err(Exception):
    pass


DUPLICATE = _Err(
    'duplicate key value violates unique constraint "idx_agent_runs_running"\n'
    "DETAIL:  Key (brand_id, agent_type)=(8d0fb129, video) already exists."
)
CHECK_VIOLATION = _Err(
    "<class 'asyncpg.exceptions.CheckViolationError'>: new row for relation "
    '"agent_runs" violates check constraint "agent_runs_trigger_check"\n'
    "DETAIL:  Failing row contains (4d1fa54c, video, manual-qa, running, ...)."
)
FOREIGN_KEY = _Err(
    'insert or update on table "agent_runs" violates foreign key constraint '
    '"agent_runs_brand_id_fkey"'
)


class TestDuplicateRunDetection:
    def test_the_idempotency_index_is_a_duplicate(self):
        assert _is_duplicate_run_error(DUPLICATE)

    def test_a_check_constraint_is_not_a_duplicate(self):
        # This is the one that retried forever.
        assert not _is_duplicate_run_error(CHECK_VIOLATION)

    def test_a_foreign_key_violation_is_not_a_duplicate(self):
        assert not _is_duplicate_run_error(FOREIGN_KEY)

    def test_the_asyncpg_class_name_alone_is_enough(self):
        # SQLAlchemy wraps asyncpg errors and the index name is not always
        # in the rendered string.
        assert _is_duplicate_run_error(
            _Err("<class 'asyncpg.exceptions.UniqueViolationError'>: oops")
        )

    def test_matching_is_case_insensitive(self):
        assert _is_duplicate_run_error(_Err("IDX_AGENT_RUNS_RUNNING"))


class TestWorkerBranches:
    def test_a_non_duplicate_acks_instead_of_retrying_forever(self):
        import inspect

        import worker

        src = inspect.getsource(worker._handle_message)
        head = src[src.index("except IntegrityError"):]
        # The guard must come BEFORE the video nak-and-retry branch.
        assert head.index("_is_duplicate_run_error") < head.index("msg.nak")

    def test_the_calendar_item_is_released_not_left_rendering(self):
        import inspect

        import worker

        src = inspect.getsource(worker._handle_message)
        head = src[src.index("except IntegrityError"):]
        guard = head[: head.index("msg.nak")]
        assert "_release_stuck_calendar_item" in guard, (
            "a rejected run leaves the item stuck in 'rendering' otherwise"
        )
