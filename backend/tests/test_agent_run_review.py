"""Regression tests for the HITL agent-run review path.

Paused runs (status 'paused_for_review', recorded by the worker on a graph
interrupt) are listed via GET /api/v1/agents/runs/paused and decided via
POST /api/v1/agents/runs/{run_id}/review. The backend NEVER mutates
agent_runs.status — the worker owns the paused_for_review→running CAS — so
the endpoint only validates, audits, and publishes the pinned NATS resume
payload to agent.resume.run. Covers:

- approve/reject happy paths: 202, exact pinned payload, audit record,
  and NO status write from the backend
- 404 unknown run, 409 not-paused, 403 below-manager roles
- NATS publish failure fails closed (503, nothing audited)
- paused-run listing shape + interrupt-summary degradation
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import agents
from app.api.v1.agents import (
    AgentRunReview,
    _interrupt_summary,
    list_paused_agent_runs,
    review_agent_run,
)
from app.models.agent_run import AgentRun
from app.models.brand import Brand

BRAND_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")

# The exact shape the worker stores on pause (agents/worker._record_paused_run).
_PAUSED_PAYLOAD = {
    "paused_for_review": True,
    "interrupts": [
        {
            "value": {
                "type": "strategy_review",
                "brand_id": str(BRAND_ID),
                "message": "Please review and approve the generated strategy.",
            },
            "interrupt_id": "intr-1",
        }
    ],
}


def _make_run(status="paused_for_review", output_payload=None, brand=None) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        agent_type="strategy",
        trigger="activation",
        status=status,
        brand_id=BRAND_ID,
        output_payload=(
            output_payload if output_payload is not None else dict(_PAUSED_PAYLOAD)
        ),
        created_at=datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 22, 9, 5, tzinfo=timezone.utc),
    )
    if brand is not None:
        run.brand = brand
    return run


class _Result:
    _UNSET = object()

    def __init__(self, rows=None, scalar=_UNSET):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if self._scalar is not _Result._UNSET:
            return self._scalar
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.commit = AsyncMock()

    async def execute(self, stmt, params=None):
        self.executed.append(stmt)
        return self._results.pop(0)


def _user(role="manager"):
    return MagicMock(role=role, email=f"{role}@test", id=uuid.uuid4())


def _patch_dispatch(monkeypatch, *, publish_exc: Exception | None = None):
    """Mock the NATS publish + audit recorder around the endpoint."""
    publisher = AsyncMock(side_effect=publish_exc)
    recorder = AsyncMock()
    monkeypatch.setattr(agents.nats_service, "publish", publisher)
    monkeypatch.setattr(agents.audit_service, "record_audit", recorder)
    return publisher, recorder


# ── Happy paths ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_approve_publishes_pinned_payload(monkeypatch):
    publisher, recorder = _patch_dispatch(monkeypatch)
    run = _make_run()
    db = _Session([_Result(scalar=run)])
    user = _user()

    resp = await review_agent_run(
        run_id=run.id,
        payload=AgentRunReview(action="approve"),
        request=MagicMock(),
        db=db,
        current_user=user,
    )

    assert resp == {"status": "resume_requested"}

    # The pinned resume contract — the worker's agent.resume.run handler
    # depends on these exact keys.
    publisher.assert_awaited_once()
    subject, sent = publisher.await_args.args
    assert subject == "agent.resume.run"
    assert set(sent) == {
        "run_id",
        "workflow_type",
        "decision",
        "feedback",
        "actor",
        "requested_at",
    }
    assert sent["run_id"] == str(run.id)
    assert sent["workflow_type"] == "strategy"
    assert sent["decision"] == "approved"
    assert sent["feedback"] is None
    assert sent["actor"] == user.email
    datetime.fromisoformat(sent["requested_at"])  # valid iso8601

    # Audited with the decision — but NO status write: the worker owns the
    # paused_for_review→running CAS, so the only DB touch is the SELECT.
    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["action"] == "approve"
    assert kwargs["entity_type"] == "agent_run"
    assert kwargs["entity_id"] == run.id
    assert kwargs["user_id"] == user.id
    assert kwargs["old_values"] == {"status": "paused_for_review"}
    assert kwargs["new_values"] == {"decision": "approved", "feedback": None}
    assert len(db.executed) == 1
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_reject_carries_feedback(monkeypatch):
    publisher, recorder = _patch_dispatch(monkeypatch)
    run = _make_run()
    db = _Session([_Result(scalar=run)])

    resp = await review_agent_run(
        run_id=run.id,
        payload=AgentRunReview(action="reject", feedback="Pillars are off-brand"),
        request=MagicMock(),
        db=db,
        current_user=_user("admin"),
    )

    assert resp == {"status": "resume_requested"}
    _, sent = publisher.await_args.args
    assert sent["decision"] == "rejected"
    assert sent["feedback"] == "Pillars are off-brand"
    kwargs = recorder.await_args.kwargs
    assert kwargs["action"] == "reject"
    assert kwargs["new_values"] == {
        "decision": "rejected",
        "feedback": "Pillars are off-brand",
    }
    db.commit.assert_not_awaited()


# ── Authorization ───────────────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["viewer", "editor"])
async def test_below_manager_403(monkeypatch, role):
    publisher, recorder = _patch_dispatch(monkeypatch)
    db = _Session([])

    with pytest.raises(HTTPException) as exc:
        await review_agent_run(
            run_id=uuid.uuid4(),
            payload=AgentRunReview(action="approve"),
            request=MagicMock(),
            db=db,
            current_user=_user(role),
        )

    assert exc.value.status_code == 403
    assert db.executed == []  # rejected before touching the DB
    publisher.assert_not_awaited()
    recorder.assert_not_awaited()


# ── Unknown / not-paused runs ───────────────────────────────────────────


@pytest.mark.anyio
async def test_unknown_run_404(monkeypatch):
    publisher, recorder = _patch_dispatch(monkeypatch)
    db = _Session([_Result(scalar=None)])

    with pytest.raises(HTTPException) as exc:
        await review_agent_run(
            run_id=uuid.uuid4(),
            payload=AgentRunReview(action="approve"),
            request=MagicMock(),
            db=db,
            current_user=_user(),
        )

    assert exc.value.status_code == 404
    publisher.assert_not_awaited()
    recorder.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["running", "completed", "failed"])
async def test_not_paused_409(monkeypatch, status):
    publisher, recorder = _patch_dispatch(monkeypatch)
    run = _make_run(status=status)
    db = _Session([_Result(scalar=run)])

    with pytest.raises(HTTPException) as exc:
        await review_agent_run(
            run_id=run.id,
            payload=AgentRunReview(action="approve"),
            request=MagicMock(),
            db=db,
            current_user=_user(),
        )

    assert exc.value.status_code == 409
    publisher.assert_not_awaited()
    recorder.assert_not_awaited()


# ── Fail closed on dispatch failure ─────────────────────────────────────


@pytest.mark.anyio
async def test_publish_failure_503_and_nothing_audited(monkeypatch):
    # NATS down (get_jetstream raises) or publish errors: no 202 without a
    # dispatched resume. The run stays paused, so a retry is always safe.
    publisher, recorder = _patch_dispatch(
        monkeypatch, publish_exc=RuntimeError("NATS not connected")
    )
    run = _make_run()
    db = _Session([_Result(scalar=run)])

    with pytest.raises(HTTPException) as exc:
        await review_agent_run(
            run_id=run.id,
            payload=AgentRunReview(action="approve"),
            request=MagicMock(),
            db=db,
            current_user=_user(),
        )

    assert exc.value.status_code == 503
    recorder.assert_not_awaited()
    db.commit.assert_not_awaited()


# ── Paused-run listing ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_list_paused_runs_shape():
    brand = Brand(id=BRAND_ID, name="NatureSpan", slug="naturespan")
    run = _make_run(brand=brand)
    db = _Session([_Result(rows=[run])])

    rows = await list_paused_agent_runs(db=db, current_user=_user("viewer"))

    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == str(run.id)
    assert row["workflow_type"] == "strategy"
    assert row["brand_id"] == str(BRAND_ID)
    assert row["brand_name"] == "NatureSpan"
    assert row["created_at"] == "2026-08-22T09:00:00+00:00"
    assert row["paused_at"] == "2026-08-22T09:05:00+00:00"
    assert row["interrupt"]["type"] == "strategy_review"
    assert (
        row["interrupt"]["message"]
        == "Please review and approve the generated strategy."
    )
    assert row["interrupt"]["interrupt_id"] == "intr-1"
    assert row["interrupt"]["count"] == 1


class TestInterruptSummary:
    def test_worker_shaped_payload(self):
        got = _interrupt_summary(_PAUSED_PAYLOAD)
        assert got["type"] == "strategy_review"
        assert got["interrupt_id"] == "intr-1"
        assert got["count"] == 1

    def test_odd_shapes_never_raise(self):
        # Legacy / partial rows must degrade, not 500 the listing.
        assert _interrupt_summary(None)["count"] == 0
        assert _interrupt_summary({})["count"] == 0
        assert _interrupt_summary({"interrupts": "not-a-list"})["count"] == 0
        got = _interrupt_summary({"interrupts": [{"value": "bare string"}]})
        assert got["message"] == "bare string"
        assert got["interrupt_id"] is None
