"""Regression tests for verifier-identified residuals (backend API cluster).

Covers:
- FLAG-DISPLAY: the kill-switch GET fails closed on a malformed
  system_flags value, matching the enforcement path (never shows
  "enabled" while dispatch is blocked)
- PUBLISHED-AT-CLAMP: a malformed published_at in the n8n publish callback
  is clamped to the current UTC time instead of raising a 500 post-auth
- QUALITY-FLAGS-COMPLETE: _video_job_quality_flags reads label_guard from
  params (chained/single-call lanes) as well as the generation ledger
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import webhooks
from app.api.v1.content import _video_job_quality_flags
from app.api.v1.system import _flag_enabled
from app.api.v1.webhooks import PublishResultPayload, publish_result
from app.config import settings
from app.models.calendar_item import CalendarItem
from app.models.content import Content

BRAND_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CB_SECRET = "cb-static-secret"


# ── FLAG-DISPLAY: kill-switch GET decode fails closed ───────────────────


def test_flag_enabled_absent_means_enabled():
    assert _flag_enabled(None) is True


def test_flag_enabled_decodes_dict_and_json():
    assert _flag_enabled({"enabled": False}) is False
    assert _flag_enabled({"enabled": True}) is True
    assert _flag_enabled('{"enabled": false}') is False
    assert _flag_enabled('{"enabled": true}') is True


def test_flag_enabled_malformed_fails_closed():
    """Enforcement (publish_service.is_publishing_enabled) fails closed on a
    malformed flag — the display must agree, never show enabled while
    dispatch is blocked."""
    assert _flag_enabled("{not valid json") is False
    assert _flag_enabled("") is False


# ── PUBLISHED-AT-CLAMP: malformed callback timestamp never 500s ─────────


class _FakeRequest:
    def __init__(self, headers=None, body: bytes = b"{}"):
        self.headers = headers or {}
        self._body = body

    async def body(self) -> bytes:
        return self._body


class _WebhookDb:
    def __init__(self, cal_item=None):
        self.cal_item = cal_item
        self.commits = 0

    async def execute(self, stmt, params=None):
        result = MagicMock()
        if "webhook_events" in str(stmt):
            result.rowcount = 1
        else:
            result.scalar_one_or_none = MagicMock(return_value=self.cal_item)
        return result

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


def _make_item(status: str) -> CalendarItem:
    return CalendarItem(
        id=uuid.uuid4(),
        brand_id=BRAND_ID,
        title="Test item",
        item_type="post",
        channel="instagram",
        status=status,
    )


def _webhook_setup(monkeypatch, cal_item):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", CB_SECRET)
    monkeypatch.setattr(webhooks, "_hmac_secret", lambda: "")
    content = Content(
        id=uuid.uuid4(),
        calendar_item_id=cal_item.id,
        brand_id=BRAND_ID,
        caption="Caption",
        hashtags=["markai"],
    )
    monkeypatch.setattr(
        webhooks.content_service, "get_content", AsyncMock(return_value=content)
    )
    return content, _WebhookDb(cal_item=cal_item)


@pytest.mark.anyio
async def test_malformed_published_at_clamped_to_now(monkeypatch, caplog):
    cal_item = _make_item("publishing")
    content, db = _webhook_setup(monkeypatch, cal_item)

    before = datetime.now(timezone.utc)
    with caplog.at_level("WARNING", logger="app.api.v1.webhooks"):
        resp = await publish_result(
            _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
            PublishResultPayload(
                content_id=str(content.id),
                status="published",
                platform_post_id="p1",
                published_at="not-a-timestamp",
            ),
            db,
        )
    after = datetime.now(timezone.utc)

    assert resp["status"] == "published"  # no 500 — garbage never propagates
    assert cal_item.status == "published"
    published_at = cal_item.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    assert before - timedelta(seconds=5) <= published_at <= after + timedelta(seconds=5)
    assert any("published_at" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_valid_published_at_still_honored(monkeypatch):
    cal_item = _make_item("publishing")
    content, db = _webhook_setup(monkeypatch, cal_item)
    stamp = "2026-08-21T10:30:00+00:00"

    resp = await publish_result(
        _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
        PublishResultPayload(
            content_id=str(content.id),
            status="published",
            platform_post_id="p2",
            published_at=stamp,
        ),
        db,
    )

    assert resp["status"] == "published"
    assert cal_item.published_at == datetime.fromisoformat(stamp)


# ── QUALITY-FLAGS-COMPLETE: label_guard read from params too ────────────


def test_quality_flags_reads_label_guard_from_params():
    job = SimpleNamespace(
        params={"label_guard": {"status": "flagged", "frames": 3}},
        generation_ledger=None,
    )
    flags = _video_job_quality_flags(job)
    assert flags["label_guard"] == {"status": "flagged", "frames": 3}


def test_quality_flags_ledger_still_wins_for_native_lane():
    job = SimpleNamespace(
        params={"label_guard": {"status": "params"}, "audio_finish": "trimmed"},
        generation_ledger=[{"label_guard": {"status": "ledger"}}],
    )
    flags = _video_job_quality_flags(job)
    assert flags["label_guard"] == {"status": "ledger"}
    assert flags["audio_finish"] == "trimmed"
