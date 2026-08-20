"""Tests for the approval state machine — resolve_approval decisions,
past-schedule roll-forward, and pending-approval recreation on re-entry
into review (calendar PATCH handler)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.auth.models  # noqa: F401 — registers the User mapper (Approval references it)
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1.calendar import patch_calendar_item
from app.models.approval import Approval
from app.models.calendar_item import CalendarItem
from app.schemas.approval import ApprovalDecision
from app.schemas.calendar_item import CalendarItemUpdate
from app.services import calendar_service
from app.services.approval_service import _roll_schedule_forward, resolve_approval
from app.services.content_service import InvalidStatusTransition

BRAND_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CONTENT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
REVIEWER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_calendar_item(status: str, scheduled_at: datetime | None) -> CalendarItem:
    return CalendarItem(
        id=uuid.uuid4(),
        brand_id=BRAND_ID,
        title="Test item",
        item_type="post",
        channel="instagram",
        status=status,
        scheduled_at=scheduled_at,
    )


def _make_approval(calendar_item: CalendarItem, status: str = "pending") -> Approval:
    return Approval(
        id=uuid.uuid4(),
        content_id=CONTENT_ID,
        calendar_item_id=calendar_item.id,
        reviewer_id=REVIEWER_ID,
        status=status,
    )


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Session double that replays canned query results."""

    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()
        self.add = MagicMock()

    async def execute(self, stmt):
        self.executed.append(stmt)
        return self._results.pop(0)


# ── _roll_schedule_forward ──────────────────────────────────────────────


class TestRollScheduleForward:
    NOW = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)

    def test_keeps_time_of_day_today_when_still_ahead(self):
        old = datetime(2026, 8, 1, 15, 30, tzinfo=timezone.utc)
        assert _roll_schedule_forward(old, self.NOW) == datetime(
            2026, 8, 20, 15, 30, tzinfo=timezone.utc
        )

    def test_moves_to_tomorrow_when_time_already_passed_today(self):
        old = datetime(2026, 8, 1, 8, 0, tzinfo=timezone.utc)
        assert _roll_schedule_forward(old, self.NOW) == datetime(
            2026, 8, 21, 8, 0, tzinfo=timezone.utc
        )

    def test_exact_now_rolls_to_tomorrow(self):
        # candidate == now must not schedule an already-due slot.
        old = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
        assert _roll_schedule_forward(old, self.NOW) == datetime(
            2026, 8, 21, 10, 0, tzinfo=timezone.utc
        )

    def test_none_falls_back_to_tomorrow(self):
        assert _roll_schedule_forward(None, self.NOW) == self.NOW + timedelta(days=1)


# ── resolve_approval ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_approve_moves_item_to_scheduled_keeping_future_slot():
    future = datetime.now(timezone.utc) + timedelta(days=2)
    cal_item = _make_calendar_item("in_review", future)
    approval = _make_approval(cal_item)
    db = _FakeSession([_FakeResult([approval]), _FakeResult([cal_item])])

    result = await resolve_approval(
        db, approval.id, ApprovalDecision(status="approved")
    )

    assert result is approval
    assert approval.status == "approved"
    assert approval.decided_at is not None
    assert cal_item.status == "scheduled"
    # A future slot is kept as-is — no silent reschedule, no note.
    assert cal_item.scheduled_at == future
    assert approval.feedback is None
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_approve_with_past_schedule_rolls_forward_with_note():
    now = datetime.now(timezone.utc)
    past = (now - timedelta(days=3, minutes=5)).replace(microsecond=0)
    cal_item = _make_calendar_item("in_review", past)
    approval = _make_approval(cal_item)
    db = _FakeSession([_FakeResult([approval]), _FakeResult([cal_item])])

    await resolve_approval(
        db, approval.id, ApprovalDecision(status="approved", feedback="Looks good")
    )

    assert cal_item.status == "scheduled"
    # Rolled forward, not scheduled blindly in the past.
    assert cal_item.scheduled_at > now
    assert cal_item.scheduled_at - now <= timedelta(days=1)
    # Original time-of-day is preserved.
    assert cal_item.scheduled_at.hour == past.hour
    assert cal_item.scheduled_at.minute == past.minute
    # The reschedule is surfaced on the approval, after the reviewer's note.
    assert approval.feedback.startswith("Looks good")
    assert "rescheduled to" in approval.feedback


@pytest.mark.anyio
async def test_approve_with_missing_schedule_falls_back_to_tomorrow():
    now = datetime.now(timezone.utc)
    cal_item = _make_calendar_item("in_review", None)
    approval = _make_approval(cal_item)
    db = _FakeSession([_FakeResult([approval]), _FakeResult([cal_item])])

    await resolve_approval(db, approval.id, ApprovalDecision(status="approved"))

    assert cal_item.status == "scheduled"
    assert cal_item.scheduled_at is not None
    # ~1 day out (the service reads its own now() a moment after ours).
    assert timedelta(hours=23) < cal_item.scheduled_at - now < timedelta(hours=25)
    assert "rescheduled to" in approval.feedback


@pytest.mark.anyio
@pytest.mark.parametrize("decision_status", ["rejected", "revision_requested"])
async def test_reject_moves_item_to_reworking(decision_status):
    scheduled_at = datetime.now(timezone.utc) + timedelta(days=1)
    cal_item = _make_calendar_item("in_review", scheduled_at)
    approval = _make_approval(cal_item)
    db = _FakeSession([_FakeResult([approval]), _FakeResult([cal_item])])

    await resolve_approval(
        db, approval.id, ApprovalDecision(status=decision_status, feedback="Redo it")
    )

    assert approval.status == decision_status
    assert approval.feedback == "Redo it"
    assert cal_item.status == "reworking"
    # Rejection leaves the schedule untouched.
    assert cal_item.scheduled_at == scheduled_at
    db.commit.assert_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("resolved_status", ["approved", "rejected"])
async def test_double_resolve_is_rejected(resolved_status):
    cal_item = _make_calendar_item("scheduled", datetime.now(timezone.utc))
    approval = _make_approval(cal_item, status=resolved_status)
    db = _FakeSession([_FakeResult([approval])])

    with pytest.raises(ValueError, match=f"already '{resolved_status}'"):
        await resolve_approval(db, approval.id, ApprovalDecision(status="approved"))

    # Nothing was persisted and the item was left alone.
    db.commit.assert_not_awaited()
    assert cal_item.status == "scheduled"


@pytest.mark.anyio
async def test_approve_from_non_review_status_is_invalid():
    # The state machine only allows in_review → scheduled; approving an
    # already-published item must blow up, not double-schedule it.
    cal_item = _make_calendar_item("published", None)
    approval = _make_approval(cal_item)
    db = _FakeSession([_FakeResult([approval]), _FakeResult([cal_item])])

    with pytest.raises(InvalidStatusTransition):
        await resolve_approval(db, approval.id, ApprovalDecision(status="approved"))

    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_resolve_unknown_approval_returns_none():
    db = _FakeSession([_FakeResult([])])
    result = await resolve_approval(
        db, uuid.uuid4(), ApprovalDecision(status="approved")
    )
    assert result is None


# ── PATCH /calendar/{id} — pending approval recreation ──────────────────


def _editor():
    return MagicMock(role="editor")


def _patch_calendar_mocks(monkeypatch, existing: CalendarItem, updated: CalendarItem):
    monkeypatch.setattr(
        calendar_service, "get_calendar_item", AsyncMock(return_value=existing)
    )
    monkeypatch.setattr(
        calendar_service, "update_calendar_item", AsyncMock(return_value=updated)
    )


@pytest.mark.anyio
async def test_resubmit_from_reworking_recreates_pending_approval(monkeypatch):
    existing = _make_calendar_item("reworking", None)
    updated = _make_calendar_item("in_review", None)
    updated.id = existing.id
    prior = _make_approval(existing, status="rejected")
    _patch_calendar_mocks(monkeypatch, existing, updated)
    db = _FakeSession([_FakeResult([prior])])

    await patch_calendar_item(
        existing.id,
        CalendarItemUpdate(status="in_review"),
        db=db,
        current_user=_editor(),
    )

    # A fresh pending approval reusing the prior (rejected) one's identity.
    db.add.assert_called_once()
    recreated = db.add.call_args[0][0]
    assert isinstance(recreated, Approval)
    assert recreated.status == "pending"
    assert recreated.content_id == prior.content_id
    assert recreated.reviewer_id == prior.reviewer_id
    assert recreated.calendar_item_id == existing.id
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_unschedule_to_in_review_recreates_pending_approval(monkeypatch):
    existing = _make_calendar_item("scheduled", datetime.now(timezone.utc))
    updated = _make_calendar_item("in_review", None)
    updated.id = existing.id
    prior = _make_approval(existing, status="approved")
    _patch_calendar_mocks(monkeypatch, existing, updated)
    db = _FakeSession([_FakeResult([prior])])

    await patch_calendar_item(
        existing.id,
        CalendarItemUpdate(status="in_review"),
        db=db,
        current_user=_editor(),
    )

    db.add.assert_called_once()
    assert db.add.call_args[0][0].status == "pending"


@pytest.mark.anyio
async def test_no_recreation_when_item_stays_in_review(monkeypatch):
    existing = _make_calendar_item("in_review", None)
    updated = _make_calendar_item("in_review", None)
    updated.id = existing.id
    _patch_calendar_mocks(monkeypatch, existing, updated)
    db = _FakeSession([])  # any query would pop from an empty list and fail

    await patch_calendar_item(
        existing.id,
        CalendarItemUpdate(title="New title"),
        db=db,
        current_user=_editor(),
    )

    assert db.executed == []
    db.add.assert_not_called()


@pytest.mark.anyio
async def test_no_recreation_without_prior_approval(monkeypatch):
    # First-time working → in_review entries get their approval from the
    # normal approval-request flow, not from the PATCH handler.
    existing = _make_calendar_item("working", None)
    updated = _make_calendar_item("in_review", None)
    updated.id = existing.id
    _patch_calendar_mocks(monkeypatch, existing, updated)
    db = _FakeSession([_FakeResult([])])

    await patch_calendar_item(
        existing.id,
        CalendarItemUpdate(status="in_review"),
        db=db,
        current_user=_editor(),
    )

    db.add.assert_not_called()


@pytest.mark.anyio
async def test_no_duplicate_when_pending_approval_already_exists(monkeypatch):
    existing = _make_calendar_item("reworking", None)
    updated = _make_calendar_item("in_review", None)
    updated.id = existing.id
    prior = _make_approval(existing, status="pending")
    _patch_calendar_mocks(monkeypatch, existing, updated)
    db = _FakeSession([_FakeResult([prior])])

    await patch_calendar_item(
        existing.id,
        CalendarItemUpdate(status="in_review"),
        db=db,
        current_user=_editor(),
    )

    db.add.assert_not_called()
