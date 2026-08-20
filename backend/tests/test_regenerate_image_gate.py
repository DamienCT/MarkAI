"""Tests for the regenerate-image status gate.

The regen worker always finishes by flipping the calendar item to
'in_review', so a regen queued from 'scheduled' used to silently un-approve
the post. The endpoint now mirrors rebrand-logo: only in-review statuses may
trigger a regen, and the item is flipped to 'working' synchronously before
the NATS publish so the UI reflects it immediately and a double-submit hits
the gate.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1.content import ImageRegenerateRequest, regenerate_image
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services import content_service, nats_service

BRAND_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ── Helpers ─────────────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Session double that replays canned results and records call order."""

    def __init__(self, results):
        self._results = list(results)
        self.ops = []

    async def execute(self, stmt):
        self.ops.append("execute")
        return self._results.pop(0)

    async def commit(self):
        self.ops.append("commit")


def _make_pair(status: str) -> tuple[Content, CalendarItem]:
    cal_item = CalendarItem(
        id=uuid.uuid4(),
        brand_id=BRAND_ID,
        title="Test item",
        item_type="post",
        channel="instagram",
        status=status,
    )
    content = Content(
        id=uuid.uuid4(),
        calendar_item_id=cal_item.id,
        brand_id=BRAND_ID,
        is_current=True,
    )
    return content, cal_item


def _editor():
    return MagicMock(role="editor")


def _wire(monkeypatch, content: Content, publish_log: list | None = None):
    monkeypatch.setattr(
        content_service, "get_content", AsyncMock(return_value=content)
    )
    publish = AsyncMock(
        side_effect=lambda *a, **k: (
            publish_log.append("publish") if publish_log is not None else None
        )
    )
    monkeypatch.setattr(nats_service, "publish", publish)
    return publish


# ── Allowed statuses ────────────────────────────────────────────────────


@pytest.mark.anyio
# 'failed' is allowed on purpose: regenerating IS the healing action the
# failed-state UI offers (mirrors the video trigger's allowed set).
@pytest.mark.parametrize("status", ["in_review", "reworking", "failed"])
async def test_regen_allowed_flips_working_then_queues(monkeypatch, status):
    content, cal_item = _make_pair(status)
    db = _FakeSession([_FakeResult([cal_item])])
    publish = _wire(monkeypatch, content, publish_log=db.ops)

    resp = await regenerate_image(
        content.id, body=None, db=db, current_user=_editor()
    )

    assert resp["status"] == "queued"
    assert cal_item.status == "working"
    # The flip is committed BEFORE the publish — the UI's status poll must
    # see 'working' even if the worker hasn't picked the message up yet.
    assert db.ops.index("commit") < db.ops.index("publish")

    subject, payload = publish.await_args.args
    assert subject == "content.regenerate-image"
    assert payload["content_id"] == str(content.id)
    assert payload["brand_id"] == str(content.brand_id)
    assert payload["calendar_item_id"] == str(content.calendar_item_id)
    assert payload["custom_prompt"] is None
    assert payload["image_format"] == "lifestyle"


@pytest.mark.anyio
async def test_regen_passes_prompt_and_format_through(monkeypatch):
    content, cal_item = _make_pair("in_review")
    db = _FakeSession([_FakeResult([cal_item])])
    publish = _wire(monkeypatch, content)

    await regenerate_image(
        content.id,
        body=ImageRegenerateRequest(prompt="make it rainy", format="ad"),
        db=db,
        current_user=_editor(),
    )

    _, payload = publish.await_args.args
    assert payload["custom_prompt"] == "make it rainy"
    assert payload["image_format"] == "ad"


# ── Blocked statuses ────────────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status", ["planned", "queued", "working", "scheduled", "published"]
)
async def test_regen_blocked_outside_review(monkeypatch, status):
    # 'scheduled' is the original bug: the worker ends at in_review, so a
    # regen from 'scheduled' would silently un-approve the post.
    content, cal_item = _make_pair(status)
    db = _FakeSession([_FakeResult([cal_item])])
    publish = _wire(monkeypatch, content)

    with pytest.raises(HTTPException) as exc:
        await regenerate_image(content.id, body=None, db=db, current_user=_editor())

    assert exc.value.status_code == 400
    assert cal_item.status == status  # untouched
    assert "commit" not in db.ops
    publish.assert_not_awaited()


@pytest.mark.anyio
async def test_double_submit_is_rejected(monkeypatch):
    # First submit flips the item to 'working'; a second click while the
    # regen is in flight lands on the gate instead of queueing again.
    content, cal_item = _make_pair("in_review")
    db = _FakeSession([_FakeResult([cal_item])])
    publish = _wire(monkeypatch, content)

    await regenerate_image(content.id, body=None, db=db, current_user=_editor())
    assert cal_item.status == "working"

    db2 = _FakeSession([_FakeResult([cal_item])])
    with pytest.raises(HTTPException) as exc:
        await regenerate_image(content.id, body=None, db=db2, current_user=_editor())

    assert exc.value.status_code == 400
    assert publish.await_count == 1


@pytest.mark.anyio
async def test_regen_missing_calendar_item_is_404(monkeypatch):
    content, _ = _make_pair("in_review")
    db = _FakeSession([_FakeResult([])])
    publish = _wire(monkeypatch, content)

    with pytest.raises(HTTPException) as exc:
        await regenerate_image(content.id, body=None, db=db, current_user=_editor())

    assert exc.value.status_code == 404
    publish.assert_not_awaited()
