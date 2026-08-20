"""Tests for the content versioning invariant — exactly one is_current row
per calendar item (partial unique index idx_content_current).

Covers: create_content demoting existing current rows in-transaction before
the insert, update_content ignoring is_current (a PUT must never strand an
item with zero current rows), and listings defaulting to current rows only.
"""

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Update

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.models.content import Content
from app.schemas.content import ContentCreate, ContentUpdate
from app.services import content_service

BRAND_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
CAL_ITEM_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


# ── Helpers ─────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Session double that replays canned results and records call order."""

    def __init__(self, results):
        self._results = list(results)
        self.executed = []
        self.added = []
        self.ops = []

    async def execute(self, stmt):
        self.ops.append("execute")
        self.executed.append(stmt)
        return self._results.pop(0)

    def add(self, obj):
        self.ops.append("add")
        self.added.append(obj)

    async def commit(self):
        self.ops.append("commit")

    async def refresh(self, obj):
        self.ops.append("refresh")


def _make_content(**overrides) -> Content:
    fields = dict(
        id=uuid.uuid4(),
        calendar_item_id=CAL_ITEM_ID,
        brand_id=BRAND_ID,
        is_current=True,
    )
    fields.update(overrides)
    return Content(**fields)


# ── create_content — demote-before-insert ───────────────────────────────


@pytest.mark.anyio
async def test_create_demotes_existing_current_rows_before_insert():
    data = ContentCreate(
        calendar_item_id=CAL_ITEM_ID, brand_id=BRAND_ID, caption="v2"
    )
    db = _FakeSession([_FakeResult([])])  # result of the demote UPDATE (unused)

    created = await content_service.create_content(db, data)

    # The demote runs first, inside the same transaction as the insert —
    # a single commit covers both, so a crash can't leave zero current rows.
    assert db.ops == ["execute", "add", "commit", "refresh"]
    assert db.added == [created]
    assert created.is_current is True

    stmt = db.executed[0]
    assert isinstance(stmt, Update)
    assert stmt.table.name == "content"
    where = str(stmt.whereclause)
    assert "calendar_item_id" in where
    assert "is_current" in where
    # The UPDATE scopes to this calendar item and clears the flag.
    params = stmt.compile().params
    assert params["is_current"] is False
    assert CAL_ITEM_ID in params.values()


@pytest.mark.anyio
async def test_create_history_row_skips_demote():
    # Explicitly inserting a non-current (history) row must not touch the
    # existing current row — there is nothing to demote.
    data = ContentCreate(
        calendar_item_id=CAL_ITEM_ID, brand_id=BRAND_ID, is_current=False
    )
    db = _FakeSession([])  # any execute would pop from an empty list and fail

    created = await content_service.create_content(db, data)

    assert db.ops == ["add", "commit", "refresh"]
    assert created.is_current is False


# ── update_content — is_current is not editable via PUT ─────────────────


@pytest.mark.anyio
async def test_update_ignores_is_current():
    content = _make_content(caption="old")
    db = _FakeSession([_FakeResult([content])])  # get_content lookup

    updated = await content_service.update_content(
        db, content.id, ContentUpdate(caption="new", is_current=False)
    )

    # The edit lands but the flag is untouched: flipping it would strand the
    # calendar item with zero current rows and silently block publish.
    assert updated is content
    assert content.caption == "new"
    assert content.is_current is True
    assert "commit" in db.ops


@pytest.mark.anyio
async def test_update_ignores_legacy_is_current_payload():
    # Back-compat: clients that still send is_current get it ignored, not a
    # 422 — same behavior as an unknown field under pydantic's default
    # extra="ignore".
    content = _make_content()
    db = _FakeSession([_FakeResult([content])])

    await content_service.update_content(
        db,
        content.id,
        ContentUpdate.model_validate({"is_current": False}),
    )

    assert content.is_current is True


# ── list_content — defaults to current rows ─────────────────────────────


@pytest.mark.anyio
async def test_list_defaults_to_current_rows_only():
    db = _FakeSession([_FakeResult([])])

    await content_service.list_content(db)

    stmt = db.executed[0]
    assert stmt.whereclause is not None
    assert "is_current" in str(stmt.whereclause)


@pytest.mark.anyio
async def test_list_explicit_none_returns_full_history():
    db = _FakeSession([_FakeResult([])])

    await content_service.list_content(db, is_current=None)

    assert db.executed[0].whereclause is None


@pytest.mark.anyio
async def test_api_listing_defaults_to_current(monkeypatch):
    # The route must not override the service default back to "everything".
    from app.api.v1 import content as content_api

    called: dict = {}

    async def _fake_list(db, **kwargs):
        called.update(kwargs)
        return []

    monkeypatch.setattr(content_api.content_service, "list_content", _fake_list)

    await content_api.list_content(
        db=MagicMock(), current_user=MagicMock(role="viewer")
    )

    assert called["is_current"] is True
