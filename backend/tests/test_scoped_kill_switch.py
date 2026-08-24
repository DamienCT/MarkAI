"""Multi-scope publishing kill switch (R-012).

The single global ``publishing_enabled`` flag grows per-brand
(``publishing_enabled:brand:<uuid>``) and per-channel
(``publishing_enabled:channel:<channel>``) scopes:
- is_publishing_enabled requires ALL applicable flags enabled
  (absent = enabled, malformed = disabled fail-closed)
- publish_direct re-checks with the item's brand/channel
- the checker skips only the items a scoped flag covers (global still
  freezes the whole tick)
- the GET/PUT endpoints take an optional scope, admin-only + audit-logged
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import system as system_api
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services import publish_service
from app.services.publish_service import (
    PUBLISHING_KILL_SWITCH_KEY,
    PublishingDisabledError,
    is_publishing_enabled,
    kill_switch_key,
    kill_switch_scope_keys,
    publish_direct,
)

BRAND_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
OTHER_BRAND_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


# ── Helpers ─────────────────────────────────────────────────────────────


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FlagSession:
    """Serves system_flags reads from a dict keyed by flag key."""

    def __init__(self, flags: dict):
        self.flags = flags
        self.queried: list[str] = []

    async def execute(self, stmt, params=None):
        key = params["key"]
        self.queried.append(key)
        return _Scalar(self.flags.get(key))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _make_item(channel: str, status: str = "publishing") -> CalendarItem:
    return CalendarItem(
        id=uuid.uuid4(),
        brand_id=BRAND_ID,
        title="Test item",
        item_type="post",
        channel=channel,
        status=status,
    )


def _make_content(calendar_item: CalendarItem) -> Content:
    return Content(
        id=uuid.uuid4(),
        calendar_item_id=calendar_item.id,
        brand_id=BRAND_ID,
        caption="Caption",
        hashtags=["markai"],
    )


# ── Key composition ─────────────────────────────────────────────────────


def test_kill_switch_key_scopes():
    assert kill_switch_key() == "publishing_enabled"
    assert (
        kill_switch_key(brand_id=BRAND_ID)
        == f"publishing_enabled:brand:{BRAND_ID}"
    )
    assert kill_switch_key(channel="x") == "publishing_enabled:channel:x"


def test_scope_keys_include_all_applicable_flags():
    assert kill_switch_scope_keys() == [PUBLISHING_KILL_SWITCH_KEY]
    keys = kill_switch_scope_keys(brand_id=BRAND_ID, channel="instagram")
    assert keys == [
        "publishing_enabled",
        f"publishing_enabled:brand:{BRAND_ID}",
        "publishing_enabled:channel:instagram",
    ]


# ── is_publishing_enabled across scopes ─────────────────────────────────


@pytest.mark.anyio
async def test_all_flags_absent_means_enabled():
    session = _FlagSession({})
    assert await is_publishing_enabled(session, brand_id=BRAND_ID, channel="x")
    assert session.queried == kill_switch_scope_keys(brand_id=BRAND_ID, channel="x")


@pytest.mark.anyio
async def test_global_flag_blocks_every_scope():
    session = _FlagSession({PUBLISHING_KILL_SWITCH_KEY: {"enabled": False}})
    assert not await is_publishing_enabled(session)
    assert not await is_publishing_enabled(
        session, brand_id=BRAND_ID, channel="instagram"
    )


@pytest.mark.anyio
async def test_brand_flag_blocks_only_that_brand():
    session = _FlagSession(
        {f"publishing_enabled:brand:{BRAND_ID}": {"enabled": False}}
    )
    assert not await is_publishing_enabled(session, brand_id=BRAND_ID)
    assert await is_publishing_enabled(session, brand_id=OTHER_BRAND_ID)
    assert await is_publishing_enabled(session)  # global untouched


@pytest.mark.anyio
async def test_channel_flag_blocks_only_that_channel():
    session = _FlagSession(
        {"publishing_enabled:channel:x": '{"enabled": false}'}  # JSON string form
    )
    assert not await is_publishing_enabled(session, channel="x")
    assert await is_publishing_enabled(session, channel="instagram")


@pytest.mark.anyio
async def test_malformed_scoped_flag_fails_closed():
    session = _FlagSession(
        {f"publishing_enabled:brand:{BRAND_ID}": "{not valid json"}
    )
    assert not await is_publishing_enabled(session, brand_id=BRAND_ID)
    # Other scopes unaffected by the broken brand flag.
    assert await is_publishing_enabled(session, brand_id=OTHER_BRAND_ID)


# ── publish_direct re-checks with the item's scope ──────────────────────


@pytest.mark.anyio
async def test_publish_direct_checks_item_brand_and_channel(monkeypatch):
    enabled = AsyncMock(return_value=False)
    monkeypatch.setattr(publish_service, "is_publishing_enabled", enabled)
    cal_item = _make_item("instagram")

    with pytest.raises(PublishingDisabledError):
        await publish_direct(
            MagicMock(),
            _make_content(cal_item),
            cal_item,
            Brand(id=BRAND_ID, name="B", brand_guidelines={}),
        )

    kwargs = enabled.await_args.kwargs
    assert kwargs["brand_id"] == BRAND_ID
    assert kwargs["channel"] == "instagram"


@pytest.mark.anyio
async def test_publish_direct_brand_scoped_flag_blocks(monkeypatch):
    session = _FlagSession(
        {f"publishing_enabled:brand:{BRAND_ID}": {"enabled": False}}
    )
    cal_item = _make_item("instagram")
    with pytest.raises(PublishingDisabledError):
        await publish_direct(
            session,
            _make_content(cal_item),
            cal_item,
            Brand(id=BRAND_ID, name="B", brand_guidelines={}),
        )


# ── Checker: scoped flag skips the item, global freezes the tick ────────


class _Rows:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.commit = AsyncMock()
        self.add = MagicMock()

    async def execute(self, stmt, params=None):
        self.executed.append(stmt)
        return self._results.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.mark.anyio
async def test_checker_scoped_flag_skips_covered_item_and_continues(monkeypatch):
    """A channel-scoped flag skips its items (they stay scheduled) but the
    tick keeps dispatching everything else — unlike a global engage."""
    from app.scheduler import publish_checker

    brand = Brand(id=BRAND_ID, name="B", brand_guidelines={})
    blocked = _make_item("x", status="scheduled")
    allowed = _make_item("instagram", status="scheduled")
    for item in (blocked, allowed):
        item.scheduled_at = None  # not stale (falsy → skips the stale branch)
    content = _make_content(allowed)
    content.brand = brand

    session = _Session(
        [
            _Rows([]),  # stuck sweep
            _Rows([blocked, allowed]),  # due items
            _Rows([content]),  # current content for the ALLOWED item only
            _Rows(scalar=allowed.id),  # CAS claim for the allowed item
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)

    checked = []

    async def fake_enabled(db=None, *, brand_id=None, channel=None):
        checked.append((brand_id, channel))
        return channel != "x"  # channel-scoped flag engaged for X only

    monkeypatch.setattr(publish_checker, "is_publishing_enabled", fake_enabled)
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)

    await publish_checker.check_due_content()

    # The blocked item was checked with its scope, then skipped (the global
    # re-check confirmed only the scope is engaged) — the allowed item still
    # dispatched.
    assert (BRAND_ID, "x") in checked
    assert (BRAND_ID, "instagram") in checked
    spawn.assert_called_once_with(allowed.id, content.id)


@pytest.mark.anyio
async def test_checker_global_engage_midtick_still_freezes(monkeypatch):
    from app.scheduler import publish_checker

    item = _make_item("x", status="scheduled")
    item.scheduled_at = None

    session = _Session(
        [
            _Rows([]),  # stuck sweep
            _Rows([item]),  # due items
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)

    async def fake_enabled(db=None, *, brand_id=None, channel=None):
        # Sweep-start check passes, then the switch engages globally.
        return len(session.executed) == 0

    monkeypatch.setattr(publish_checker, "is_publishing_enabled", fake_enabled)
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)

    await publish_checker.check_due_content()

    spawn.assert_not_called()
    assert item.status == "scheduled"  # untouched — publishes on re-enable


# ── Endpoints: optional scope, admin-only, audit-logged ─────────────────


class _EndpointResult:
    def __init__(self, *, first=None, scalar=None, rows=None):
        self._first = first
        self._scalar = scalar
        self._rows = rows or []

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows


class _EndpointDb:
    def __init__(self, results):
        self._results = list(results)
        self.executed: list[tuple] = []
        self.commit = AsyncMock()

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))
        return self._results.pop(0)


def _admin():
    return MagicMock(role="admin", email="admin@test", id=uuid.uuid4())


@pytest.mark.anyio
async def test_put_brand_scope_writes_scoped_key_and_audits(monkeypatch):
    recorder = AsyncMock()
    monkeypatch.setattr(system_api.audit_service, "record_audit", recorder)
    db = _EndpointDb([_EndpointResult(scalar=None), _EndpointResult()])
    expected_key = f"publishing_enabled:brand:{BRAND_ID}"

    resp = await system_api.set_publishing_kill_switch(
        system_api.PublishingKillSwitch(enabled=False, brand_id=BRAND_ID),
        request=MagicMock(),
        db=db,
        current_user=_admin(),
    )

    assert resp == {"enabled": False, "key": expected_key}
    _stmt, upsert_params = db.executed[1]
    assert upsert_params["key"] == expected_key
    db.commit.assert_awaited()
    kwargs = recorder.await_args.kwargs
    assert kwargs["new_values"] == {
        "publishing_enabled": False,
        "scope": expected_key,
    }
    assert kwargs["old_values"]["scope"] == expected_key


@pytest.mark.anyio
async def test_put_channel_scope_writes_scoped_key(monkeypatch):
    monkeypatch.setattr(system_api.audit_service, "record_audit", AsyncMock())
    db = _EndpointDb([_EndpointResult(scalar=None), _EndpointResult()])

    resp = await system_api.set_publishing_kill_switch(
        system_api.PublishingKillSwitch(enabled=False, channel="instagram"),
        request=MagicMock(),
        db=db,
        current_user=_admin(),
    )

    assert resp["key"] == "publishing_enabled:channel:instagram"
    _stmt, upsert_params = db.executed[1]
    assert upsert_params["key"] == "publishing_enabled:channel:instagram"


@pytest.mark.anyio
async def test_put_global_response_and_audit_shape_unchanged(monkeypatch):
    recorder = AsyncMock()
    monkeypatch.setattr(system_api.audit_service, "record_audit", recorder)
    db = _EndpointDb([_EndpointResult(scalar=None), _EndpointResult()])

    resp = await system_api.set_publishing_kill_switch(
        system_api.PublishingKillSwitch(enabled=True),
        request=MagicMock(),
        db=db,
        current_user=_admin(),
    )

    assert resp == {"enabled": True}  # no "key" leak for the global switch
    assert recorder.await_args.kwargs["new_values"] == {"publishing_enabled": True}


@pytest.mark.anyio
async def test_put_rejects_brand_and_channel_together():
    with pytest.raises(HTTPException) as exc:
        await system_api.set_publishing_kill_switch(
            system_api.PublishingKillSwitch(
                enabled=False, brand_id=BRAND_ID, channel="x"
            ),
            request=MagicMock(),
            db=_EndpointDb([]),
            current_user=_admin(),
        )
    assert exc.value.status_code == 400


@pytest.mark.anyio
async def test_put_rejects_unknown_channel():
    """A typo'd channel would create a flag that gates nothing while the
    operator believes publishing is blocked — refused outright."""
    with pytest.raises(HTTPException) as exc:
        await system_api.set_publishing_kill_switch(
            system_api.PublishingKillSwitch(enabled=False, channel="instagramm"),
            request=MagicMock(),
            db=_EndpointDb([]),
            current_user=_admin(),
        )
    assert exc.value.status_code == 400
    assert "instagramm" in exc.value.detail


@pytest.mark.anyio
async def test_put_scoped_rejects_non_admin():
    with pytest.raises(HTTPException) as exc:
        await system_api.set_publishing_kill_switch(
            system_api.PublishingKillSwitch(enabled=False, channel="x"),
            request=MagicMock(),
            db=_EndpointDb([]),
            current_user=MagicMock(role="manager", email="m@test", id=uuid.uuid4()),
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_get_scoped_state_returns_flag_for_that_scope():
    row = SimpleNamespace(
        value={"enabled": False}, updated_by="admin@test", updated_at=None
    )
    db = _EndpointDb([_EndpointResult(first=row)])

    resp = await system_api.get_publishing_kill_switch(
        channel="x", db=db, current_user=_admin()
    )

    assert resp["enabled"] is False
    assert resp["key"] == "publishing_enabled:channel:x"
    assert "scoped" not in resp
    _stmt, params = db.executed[0]
    assert params["key"] == "publishing_enabled:channel:x"


@pytest.mark.anyio
async def test_get_global_lists_scoped_flags():
    scoped_row = SimpleNamespace(
        key=f"publishing_enabled:brand:{BRAND_ID}",
        value={"enabled": False},
        updated_by="admin@test",
        updated_at=None,
    )
    db = _EndpointDb(
        [
            _EndpointResult(first=None),  # global flag absent → enabled
            _EndpointResult(rows=[scoped_row]),  # scoped listing
        ]
    )

    resp = await system_api.get_publishing_kill_switch(
        db=db, current_user=_admin()
    )

    assert resp["enabled"] is True
    assert resp["scoped"] == [
        {
            "key": f"publishing_enabled:brand:{BRAND_ID}",
            "enabled": False,
            "updated_by": "admin@test",
            "updated_at": None,
        }
    ]
    _stmt, params = db.executed[1]
    assert params["prefix"] == "publishing_enabled:%"


# ── /publishing-status: read-only global boolean, any authenticated role ─


@pytest.mark.anyio
async def test_publishing_status_open_to_non_admins():
    """Editors must see WHY scheduled content is waiting — no role gate."""
    db = _EndpointDb([_EndpointResult(scalar={"enabled": False})])

    resp = await system_api.get_publishing_status(
        db=db,
        current_user=MagicMock(role="viewer", email="v@test", id=uuid.uuid4()),
    )

    assert resp == {"enabled": False}


@pytest.mark.anyio
async def test_publishing_status_absent_flag_means_enabled():
    db = _EndpointDb([_EndpointResult(scalar=None)])

    resp = await system_api.get_publishing_status(db=db, current_user=_admin())

    assert resp == {"enabled": True}


@pytest.mark.anyio
async def test_publishing_status_reads_global_key_and_nothing_else():
    """Only the boolean leaves this endpoint: one query, global key, no
    scoped listing and no updated_by/updated_at metadata."""
    db = _EndpointDb([_EndpointResult(scalar={"enabled": True})])

    resp = await system_api.get_publishing_status(db=db, current_user=_admin())

    assert resp == {"enabled": True}
    assert len(db.executed) == 1
    _stmt, params = db.executed[0]
    assert params["key"] == PUBLISHING_KILL_SWITCH_KEY
