"""Regression tests for the learning recommendation decision path.

The recommendation queue now populates ('proposed' rows), and
POST /api/v1/learning/adaptations/{id}/decision is the only human path to
the legal 'applied'/'rejected' statuses. Covers:

- happy-path apply + reject (CAS update, audit record, notes envelope)
- non-manager 403
- double decision → 409 (both the pre-check and the CAS race)
- malformed adaptation_notes rows still listed (tier/confidence defaults)
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import learning
from app.api.v1.learning import AdaptationDecision, decide_adaptation, list_adaptations
from app.models.adaptation import Adaptation

CONTENT_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _make_adaptation(status="proposed", notes=None) -> Adaptation:
    return Adaptation(
        id=uuid.uuid4(),
        source_content_id=CONTENT_ID,
        target_channel="instagram",
        adapted_text="Post at 18:00 instead of 09:00",
        adaptation_notes=notes,
        status=status,
        created_at=datetime.now(timezone.utc),
    )


def _envelope(tier=1, confidence=0.9, data=None) -> str:
    return json.dumps({"tier": tier, "confidence": confidence, "data": data or {}})


class _Result:
    _UNSET = object()

    def __init__(self, rows=None, scalar=_UNSET, rowcount=None):
        self._rows = rows or []
        self._scalar = scalar
        self.rowcount = rowcount

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


def _manager(role="manager"):
    return MagicMock(role=role, email=f"{role}@test", id=uuid.uuid4())


def _patch_audit(monkeypatch):
    recorder = AsyncMock()
    monkeypatch.setattr(learning.audit_service, "record_audit", recorder)
    return recorder


# ── Happy paths ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_apply_happy_path(monkeypatch):
    recorder = _patch_audit(monkeypatch)
    adaptation = _make_adaptation(notes=_envelope(tier=1, confidence=0.9))
    db = _Session([_Result(scalar=adaptation), _Result(rowcount=1)])
    user = _manager()

    resp = await decide_adaptation(
        adaptation_id=adaptation.id,
        payload=AdaptationDecision(action="apply"),
        request=MagicMock(),
        db=db,
        current_user=user,
    )

    assert resp == {"id": str(adaptation.id), "status": "applied"}
    db.commit.assert_awaited_once()

    # The CAS update carries the new status AND the decision-stamped notes
    # envelope (tier/confidence keys preserved, actor recorded).
    update_params = db.executed[1].compile().params
    assert "applied" in update_params.values()
    new_notes = next(
        v for v in update_params.values()
        if isinstance(v, str) and v.lstrip().startswith("{")
    )
    parsed = json.loads(new_notes)
    assert parsed["tier"] == 1
    assert parsed["decision"]["action"] == "apply"
    assert parsed["decision"]["actor"] == user.email

    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["action"] == "apply"
    assert kwargs["entity_type"] == "adaptation"
    assert kwargs["old_values"] == {"status": "proposed"}
    assert kwargs["new_values"]["status"] == "applied"


@pytest.mark.anyio
async def test_reject_happy_path_with_note(monkeypatch):
    recorder = _patch_audit(monkeypatch)
    adaptation = _make_adaptation(notes=_envelope())
    db = _Session([_Result(scalar=adaptation), _Result(rowcount=1)])

    resp = await decide_adaptation(
        adaptation_id=adaptation.id,
        payload=AdaptationDecision(action="reject", note="off-brand"),
        request=MagicMock(),
        db=db,
        current_user=_manager("admin"),
    )

    assert resp["status"] == "rejected"
    db.commit.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["action"] == "reject"
    assert kwargs["new_values"] == {"status": "rejected", "note": "off-brand"}


@pytest.mark.anyio
async def test_legacy_free_text_notes_left_untouched(monkeypatch):
    """A legacy free-text notes row is decidable; its notes stay verbatim."""
    _patch_audit(monkeypatch)
    adaptation = _make_adaptation(notes="tweaked tone for LinkedIn")
    db = _Session([_Result(scalar=adaptation), _Result(rowcount=1)])

    resp = await decide_adaptation(
        adaptation_id=adaptation.id,
        payload=AdaptationDecision(action="apply"),
        request=MagicMock(),
        db=db,
        current_user=_manager(),
    )

    assert resp["status"] == "applied"
    update_params = db.executed[1].compile().params
    assert "tweaked tone for LinkedIn" in update_params.values()


# ── Authorization ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_non_manager_403(monkeypatch):
    _patch_audit(monkeypatch)
    db = _Session([])

    with pytest.raises(HTTPException) as exc:
        await decide_adaptation(
            adaptation_id=uuid.uuid4(),
            payload=AdaptationDecision(action="apply"),
            request=MagicMock(),
            db=db,
            current_user=_manager("editor"),
        )

    assert exc.value.status_code == 403
    assert db.executed == []  # rejected before touching the DB


# ── Double decision ─────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_double_decision_409(monkeypatch):
    recorder = _patch_audit(monkeypatch)
    adaptation = _make_adaptation(status="applied")
    db = _Session([_Result(scalar=adaptation)])

    with pytest.raises(HTTPException) as exc:
        await decide_adaptation(
            adaptation_id=adaptation.id,
            payload=AdaptationDecision(action="reject"),
            request=MagicMock(),
            db=db,
            current_user=_manager(),
        )

    assert exc.value.status_code == 409
    db.commit.assert_not_awaited()
    recorder.assert_not_awaited()


@pytest.mark.anyio
async def test_concurrent_decision_race_409(monkeypatch):
    """Row read as proposed but the CAS update matches nothing (raced)."""
    recorder = _patch_audit(monkeypatch)
    adaptation = _make_adaptation()
    db = _Session([_Result(scalar=adaptation), _Result(rowcount=0)])

    with pytest.raises(HTTPException) as exc:
        await decide_adaptation(
            adaptation_id=adaptation.id,
            payload=AdaptationDecision(action="apply"),
            request=MagicMock(),
            db=db,
            current_user=_manager(),
        )

    assert exc.value.status_code == 409
    db.commit.assert_not_awaited()
    recorder.assert_not_awaited()


@pytest.mark.anyio
async def test_missing_row_404(monkeypatch):
    _patch_audit(monkeypatch)
    db = _Session([_Result(scalar=None)])

    with pytest.raises(HTTPException) as exc:
        await decide_adaptation(
            adaptation_id=uuid.uuid4(),
            payload=AdaptationDecision(action="apply"),
            request=MagicMock(),
            db=db,
            current_user=_manager(),
        )

    assert exc.value.status_code == 404


# ── Listing lifts the notes envelope (and survives malformed rows) ──────


@pytest.mark.anyio
async def test_list_lifts_tier_confidence_data():
    adaptation = _make_adaptation(
        notes=_envelope(tier=3, confidence=0.7, data={"pillar": "education"})
    )
    db = _Session([_Result(rows=[adaptation])])

    rows = await list_adaptations(db=db, current_user=_manager("viewer"))

    assert rows[0]["tier"] == 3
    assert rows[0]["confidence"] == 0.7
    assert rows[0]["data"] == {"pillar": "education"}
    assert rows[0]["adaptation_notes"] == adaptation.adaptation_notes


@pytest.mark.anyio
async def test_malformed_notes_row_still_listed():
    malformed = _make_adaptation(notes="{this is not json")
    free_text = _make_adaptation(notes="plain human note")
    db = _Session([_Result(rows=[malformed, free_text])])

    rows = await list_adaptations(db=db, current_user=_manager("viewer"))

    assert len(rows) == 2
    for row in rows:
        # Defaults mirror agents/shared/tools/database._lift_adaptation_row:
        # tier 2 (human review), 0.5 confidence — the listing never raises.
        assert row["tier"] == 2
        assert row["confidence"] == 0.5
