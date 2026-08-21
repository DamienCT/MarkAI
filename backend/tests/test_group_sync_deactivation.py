"""N-03 regression: Entra group sync must never reactivate a deactivated user.

Activation-by-group applies only at first provisioning (row creation);
a manual deactivation sticks even when the user is still in the admin or
marketing security group.
"""

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app import deps
from app.config import settings

ADMIN_GID = "admin-group-id"
MKT_GID = "marketing-group-id"


class _StubUser:
    def __init__(self, role: str, is_active: bool):
        self.role = role
        self.is_active = is_active


class _FakeResult:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user


class _FakeSession:
    def __init__(self, user):
        self._user = user
        self.added = None
        self.commits = 0

    async def execute(self, stmt):
        return _FakeResult(self._user)

    def add(self, obj):
        self.added = obj

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


def _patch_auth(monkeypatch, groups):
    async def fake_validate(token):
        return {"oid": "entra-1", "preferred_username": "u@example.com", "name": "U"}

    async def fake_graph_check(entra_id, group_id):
        return group_id in groups

    monkeypatch.setattr(deps, "validate_entra_token", fake_validate)
    monkeypatch.setattr(deps, "extract_groups", lambda claims: list(groups))
    monkeypatch.setattr(deps, "check_user_in_security_group", fake_graph_check)
    monkeypatch.setattr(settings, "ADMIN_SECURITY_GROUP_ID", ADMIN_GID)
    monkeypatch.setattr(settings, "MARKETING_SECURITY_GROUP_ID", MKT_GID)


def _creds():
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="jwt")


@pytest.mark.anyio
async def test_deactivated_admin_group_user_stays_deactivated(monkeypatch):
    _patch_auth(monkeypatch, [ADMIN_GID])
    user = _StubUser(role="admin", is_active=False)
    db = _FakeSession(user)
    with pytest.raises(HTTPException) as excinfo:
        await deps.get_current_user(credentials=_creds(), db=db)
    assert excinfo.value.status_code == 403
    assert user.is_active is False
    assert db.commits == 0  # nothing written for an already-admin row


@pytest.mark.anyio
async def test_deactivated_marketing_group_user_stays_deactivated(monkeypatch):
    _patch_auth(monkeypatch, [MKT_GID])
    user = _StubUser(role="manager", is_active=False)
    db = _FakeSession(user)
    with pytest.raises(HTTPException) as excinfo:
        await deps.get_current_user(credentials=_creds(), db=db)
    assert excinfo.value.status_code == 403
    assert user.is_active is False


@pytest.mark.anyio
async def test_deactivated_user_role_sync_never_reactivates(monkeypatch):
    # Role may still be upgraded by the admin group, but is_active must not flip.
    _patch_auth(monkeypatch, [ADMIN_GID])
    user = _StubUser(role="viewer", is_active=False)
    db = _FakeSession(user)
    with pytest.raises(HTTPException) as excinfo:
        await deps.get_current_user(credentials=_creds(), db=db)
    assert excinfo.value.status_code == 403
    assert user.role == "admin"
    assert user.is_active is False


@pytest.mark.anyio
async def test_new_admin_group_user_provisioned_active(monkeypatch):
    _patch_auth(monkeypatch, [ADMIN_GID])
    db = _FakeSession(None)
    result = await deps.get_current_user(credentials=_creds(), db=db)
    assert result is db.added
    assert result.role == "admin"
    assert result.is_active is True


@pytest.mark.anyio
async def test_active_viewer_in_marketing_group_upgraded_not_touched(monkeypatch):
    _patch_auth(monkeypatch, [MKT_GID])
    user = _StubUser(role="viewer", is_active=True)
    db = _FakeSession(user)
    result = await deps.get_current_user(credentials=_creds(), db=db)
    assert result is user
    assert user.role == "manager"
    assert user.is_active is True
