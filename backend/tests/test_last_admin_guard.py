"""Last-admin lockout guards + real user audit rows (UX-02 / R-013).

PUT/PATCH /users/{id} must refuse, server-side:
- demoting or deactivating the LAST active admin (409) — the active-admin
  count runs on the same session/transaction as the update
- an admin demoting or deactivating THEMSELVES (400 — self-lockout)

and role/is_active changes must land as real ``audit_log`` rows
(entity_type 'user', old/new values) via audit_service.record_audit, not
just logger lines.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import users as users_api
from app.auth.models import User
from app.schemas.user import UserUpdate


def _make_user(role: str = "admin", is_active: bool = True) -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        entra_id=f"entra-{uid}",
        email=f"{uid}@test",
        display_name="Test User",
        role=role,
        is_active=is_active,
    )


class _Result:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar


class _Db:
    """Replays canned query results; records executed statements."""

    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, stmt, params=None):
        self.executed.append(stmt)
        return self._results.pop(0)


def _mock_audit(monkeypatch) -> AsyncMock:
    recorder = AsyncMock()
    monkeypatch.setattr(users_api.audit_service, "record_audit", recorder)
    return recorder


# ── Last active admin (409) ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_put_refuses_demoting_last_active_admin(monkeypatch):
    _mock_audit(monkeypatch)
    target = _make_user(role="admin", is_active=True)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=target), _Result(scalar=1)])  # lookup, admin count

    with pytest.raises(HTTPException) as exc:
        await users_api.update_user(
            target.id,
            UserUpdate(role="manager"),
            request=MagicMock(),
            db=db,
            current_user=acting,
        )

    assert exc.value.status_code == 409
    assert "last active admin" in exc.value.detail
    assert target.role == "admin"  # nothing applied
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_patch_refuses_deactivating_last_active_admin(monkeypatch):
    _mock_audit(monkeypatch)
    target = _make_user(role="admin", is_active=True)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=target), _Result(scalar=1)])

    with pytest.raises(HTTPException) as exc:
        await users_api.patch_user(
            target.id,
            UserUpdate(is_active=False),
            request=MagicMock(),
            db=db,
            current_user=acting,
        )

    assert exc.value.status_code == 409
    assert target.is_active is True
    db.commit.assert_not_awaited()


# ── Self-lockout (400) ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_put_refuses_admin_self_demotion_even_with_other_admins(monkeypatch):
    """Self-lockout is refused BEFORE the admin count — other admins existing
    doesn't make demoting yourself okay."""
    _mock_audit(monkeypatch)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=acting)])  # lookup only — no count query runs

    with pytest.raises(HTTPException) as exc:
        await users_api.update_user(
            acting.id,
            UserUpdate(role="viewer"),
            request=MagicMock(),
            db=db,
            current_user=acting,
        )

    assert exc.value.status_code == 400
    assert "themselves" in exc.value.detail
    assert acting.role == "admin"
    assert len(db.executed) == 1  # the count query never ran
    db.commit.assert_not_awaited()


@pytest.mark.anyio
async def test_patch_refuses_admin_self_deactivation(monkeypatch):
    _mock_audit(monkeypatch)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=acting)])

    with pytest.raises(HTTPException) as exc:
        await users_api.patch_user(
            acting.id,
            UserUpdate(is_active=False),
            request=MagicMock(),
            db=db,
            current_user=acting,
        )

    assert exc.value.status_code == 400
    assert acting.is_active is True
    db.commit.assert_not_awaited()


# ── Allowed changes go through + audit rows (R-013) ─────────────────────


@pytest.mark.anyio
async def test_put_demote_with_other_admins_succeeds_and_audits(monkeypatch):
    recorder = _mock_audit(monkeypatch)
    target = _make_user(role="admin", is_active=True)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=target), _Result(scalar=2)])  # 2 active admins

    result = await users_api.update_user(
        target.id,
        UserUpdate(role="manager"),
        request=MagicMock(),
        db=db,
        current_user=acting,
    )

    assert result.role == "manager"
    db.commit.assert_awaited()
    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["entity_type"] == "user"
    assert kwargs["action"] == "update"
    assert kwargs["user_id"] == acting.id
    assert kwargs["entity_id"] == target.id
    assert kwargs["old_values"] == {"role": "admin", "is_active": True}
    assert kwargs["new_values"] == {"role": "manager", "is_active": True}


@pytest.mark.anyio
async def test_patch_deactivating_non_admin_audits_without_count(monkeypatch):
    """Deactivating a non-admin needs no admin count and writes an audit
    row recording the is_active flip."""
    recorder = _mock_audit(monkeypatch)
    target = _make_user(role="viewer", is_active=True)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=target)])  # lookup only

    result = await users_api.patch_user(
        target.id,
        UserUpdate(is_active=False),
        request=MagicMock(),
        db=db,
        current_user=acting,
    )

    assert result.is_active is False
    assert len(db.executed) == 1  # no active-admin count query
    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["old_values"] == {"role": "viewer", "is_active": True}
    assert kwargs["new_values"] == {"role": "viewer", "is_active": False}


@pytest.mark.anyio
async def test_put_display_name_change_skips_guard_and_audit(monkeypatch):
    recorder = _mock_audit(monkeypatch)
    target = _make_user(role="viewer", is_active=True)
    acting = _make_user(role="admin", is_active=True)
    db = _Db([_Result(scalar=target)])

    result = await users_api.update_user(
        target.id,
        UserUpdate(display_name="New Name"),
        request=MagicMock(),
        db=db,
        current_user=acting,
    )

    assert result.display_name == "New Name"
    db.commit.assert_awaited()
    recorder.assert_not_awaited()  # no role/is_active change — no audit row
