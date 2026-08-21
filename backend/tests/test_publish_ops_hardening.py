"""Regression tests for the publishing-ops hardening (audit cluster D).

Covers:
- replayed/late 'failed' callback cannot regress a 'published' item (P0-05, addendum 2.3)
- late 'published' never overwrites an operator-pulled item (monotonic guard)
- X-Webhook-Event-Id replay no-ops (P0-05)
- inbound HMAC verification when the HMAC secret is set
- outbound dispatch refuses to run without the shared secret (N-15)
- outbound dispatch always sends secret + event id (and HMAC when configured)
- dispatch claim is compare-and-set scheduled→publishing (P0-04, N-14)
- publishing kill switch blocks every dispatch path + freezes the sweep (P0-11)
- kill-switch PUT endpoint is admin-only and audit-logged
"""

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import system as system_api
from app.api.v1 import webhooks
from app.api.v1.webhooks import PublishResultPayload, publish_result
from app.config import settings
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services import publish_service
from app.services.publish_service import (
    PublishingDisabledError,
    PublishPreflightError,
    dispatch_to_n8n,
    publish_direct,
)

BRAND_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CB_SECRET = "cb-static-secret"


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_brand() -> Brand:
    return Brand(id=BRAND_ID, name="Test Brand", brand_guidelines={})


def _make_item(channel: str, status: str) -> CalendarItem:
    return CalendarItem(
        id=uuid.uuid4(),
        brand_id=BRAND_ID,
        title="Test item",
        item_type="post",
        channel=channel,
        status=status,
    )


def _make_content(calendar_item: CalendarItem, **kwargs) -> Content:
    return Content(
        id=uuid.uuid4(),
        calendar_item_id=calendar_item.id,
        brand_id=BRAND_ID,
        caption="Primary caption",
        hashtags=["markai"],
        **kwargs,
    )


class _FakeRequest:
    def __init__(self, headers=None, body: bytes = b"{}"):
        self.headers = headers or {}
        self._body = body

    async def body(self) -> bytes:
        return self._body


class _WebhookDb:
    """Serves the webhook endpoint's queries: the optional webhook_events
    insert (dispatched by SQL text), then the CalendarItem select."""

    def __init__(self, cal_item=None, event_insert_rowcount=1):
        self.cal_item = cal_item
        self.event_insert_rowcount = event_insert_rowcount
        self.commits = 0
        self.event_inserts = []

    async def execute(self, stmt, params=None):
        result = MagicMock()
        if "webhook_events" in str(stmt):
            self.event_inserts.append(params)
            result.rowcount = self.event_insert_rowcount
        else:
            result.scalar_one_or_none = MagicMock(return_value=self.cal_item)
        return result

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        pass


class _Rows:
    """Result stub serving both .scalars().all() and .scalar_one_or_none()."""

    _UNSET = object()

    def __init__(self, rows=None, scalar=_UNSET):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if self._scalar is not _Rows._UNSET:
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


def _legacy_auth(monkeypatch):
    """Static-secret-only inbound auth (HMAC secret unset)."""
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", CB_SECRET)
    monkeypatch.setattr(webhooks, "_hmac_secret", lambda: "")


def _patch_content(monkeypatch, content):
    getter = AsyncMock(return_value=content)
    monkeypatch.setattr(webhooks.content_service, "get_content", getter)
    return getter


# ── Monotonic transition guard (P0-05 / addendum 2.3) ───────────────────


@pytest.mark.anyio
async def test_replayed_failed_callback_cannot_regress_published(monkeypatch):
    _legacy_auth(monkeypatch)
    cal_item = _make_item("instagram", "published")
    content = _make_content(cal_item)
    _patch_content(monkeypatch, content)
    db = _WebhookDb(cal_item=cal_item)

    resp = await publish_result(
        _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
        PublishResultPayload(
            content_id=str(content.id), status="failed", error_message="replayed"
        ),
        db,
    )

    assert resp["status"] == "ignored"
    assert cal_item.status == "published"
    assert not (content.generation_metadata or {}).get("publish_error")


@pytest.mark.anyio
async def test_late_published_never_overwrites_operator_pullback(monkeypatch):
    """An operator moved the item out of the queue (any non-scheduled/
    publishing status) — a late 'published' callback must not resurrect it."""
    _legacy_auth(monkeypatch)
    cal_item = _make_item("instagram", "in_review")
    content = _make_content(cal_item)
    _patch_content(monkeypatch, content)
    db = _WebhookDb(cal_item=cal_item)

    resp = await publish_result(
        _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
        PublishResultPayload(
            content_id=str(content.id), status="published", platform_post_id="p1"
        ),
        db,
    )

    assert resp["status"] == "ignored"
    assert cal_item.status == "in_review"
    assert content.platform_post_id is None


@pytest.mark.anyio
async def test_publishing_to_published_transition_is_allowed(monkeypatch):
    _legacy_auth(monkeypatch)
    cal_item = _make_item("instagram", "publishing")
    content = _make_content(cal_item)
    _patch_content(monkeypatch, content)
    db = _WebhookDb(cal_item=cal_item)

    resp = await publish_result(
        _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
        PublishResultPayload(
            content_id=str(content.id), status="published", platform_post_id="p42"
        ),
        db,
    )

    assert resp["status"] == "published"
    assert cal_item.status == "published"
    assert cal_item.published_at is not None
    assert content.platform_post_id == "p42"
    assert db.commits >= 1


# ── Event-id replay dedup ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_event_id_replay_noops(monkeypatch):
    _legacy_auth(monkeypatch)
    getter = _patch_content(monkeypatch, None)
    db = _WebhookDb(event_insert_rowcount=0)  # conflict: already consumed

    resp = await publish_result(
        _FakeRequest(
            {"X-Webhook-Secret": CB_SECRET, "X-Webhook-Event-Id": "evt-1"}
        ),
        PublishResultPayload(
            content_id=str(uuid.uuid4()), status="failed", error_message="x"
        ),
        db,
    )

    assert resp["status"] == "duplicate"
    getter.assert_not_awaited()  # replay short-circuits before any state read


@pytest.mark.anyio
async def test_first_event_id_delivery_is_processed(monkeypatch):
    _legacy_auth(monkeypatch)
    cal_item = _make_item("instagram", "publishing")
    content = _make_content(cal_item)
    _patch_content(monkeypatch, content)
    db = _WebhookDb(cal_item=cal_item, event_insert_rowcount=1)

    resp = await publish_result(
        _FakeRequest(
            {"X-Webhook-Secret": CB_SECRET, "X-Webhook-Event-Id": "evt-2"}
        ),
        PublishResultPayload(
            content_id=str(content.id), status="published", platform_post_id="p7"
        ),
        db,
    )

    assert resp["status"] == "published"
    assert db.event_inserts[0]["event_id"] == "evt-2"
    assert cal_item.status == "published"


# ── Inbound HMAC verification ───────────────────────────────────────────


def _signed_headers(secret: str, body: bytes, ts: str | None = None):
    ts = ts or str(int(time.time()))
    sig = hmac.new(
        secret.encode(), ts.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    return {
        "X-Webhook-Secret": CB_SECRET,
        "X-Webhook-Timestamp": ts,
        "X-Webhook-Signature": f"sha256={sig}",
    }


@pytest.mark.anyio
async def test_hmac_valid_signature_accepted(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", CB_SECRET)
    monkeypatch.setattr(webhooks, "_hmac_secret", lambda: "hmac-secret")
    cal_item = _make_item("instagram", "publishing")
    content = _make_content(cal_item)
    _patch_content(monkeypatch, content)
    db = _WebhookDb(cal_item=cal_item)

    payload = {
        "content_id": str(content.id),
        "status": "published",
        "platform_post_id": "p9",
    }
    body = json.dumps(payload).encode()
    resp = await publish_result(
        _FakeRequest(_signed_headers("hmac-secret", body), body=body),
        PublishResultPayload(**payload),
        db,
    )
    assert resp["status"] == "published"
    assert cal_item.status == "published"


@pytest.mark.anyio
async def test_hmac_invalid_signature_rejected(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", CB_SECRET)
    monkeypatch.setattr(webhooks, "_hmac_secret", lambda: "hmac-secret")
    payload = {"content_id": str(uuid.uuid4()), "status": "published"}
    body = json.dumps(payload).encode()
    headers = _signed_headers("WRONG-secret", body)

    with pytest.raises(HTTPException) as exc:
        await publish_result(
            _FakeRequest(headers, body=body), PublishResultPayload(**payload), _WebhookDb()
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_hmac_missing_timestamp_rejected(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", CB_SECRET)
    monkeypatch.setattr(webhooks, "_hmac_secret", lambda: "hmac-secret")

    with pytest.raises(HTTPException) as exc:
        await publish_result(
            _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
            PublishResultPayload(content_id=str(uuid.uuid4()), status="published"),
            _WebhookDb(),
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_hmac_stale_timestamp_rejected(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", CB_SECRET)
    monkeypatch.setattr(webhooks, "_hmac_secret", lambda: "hmac-secret")
    payload = {"content_id": str(uuid.uuid4()), "status": "published"}
    body = json.dumps(payload).encode()
    stale = str(int(time.time()) - 4000)
    headers = _signed_headers("hmac-secret", body, ts=stale)

    with pytest.raises(HTTPException) as exc:
        await publish_result(
            _FakeRequest(headers, body=body), PublishResultPayload(**payload), _WebhookDb()
        )
    assert exc.value.status_code == 403


@pytest.mark.anyio
async def test_legacy_mode_accepts_but_logs_deprecation(monkeypatch, caplog):
    _legacy_auth(monkeypatch)
    cal_item = _make_item("instagram", "scheduled")
    content = _make_content(cal_item)
    _patch_content(monkeypatch, content)
    db = _WebhookDb(cal_item=cal_item)

    with caplog.at_level("WARNING", logger="app.api.v1.webhooks"):
        resp = await publish_result(
            _FakeRequest({"X-Webhook-Secret": CB_SECRET}),
            PublishResultPayload(
                content_id=str(content.id), status="published", platform_post_id="p1"
            ),
            db,
        )
    assert resp["status"] == "published"
    assert any("static secret only" in r.message for r in caplog.records)


@pytest.mark.anyio
async def test_inbound_503_when_static_secret_unset(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", "")
    with pytest.raises(HTTPException) as exc:
        await publish_result(
            _FakeRequest({}),
            PublishResultPayload(content_id=str(uuid.uuid4()), status="published"),
            _WebhookDb(),
        )
    assert exc.value.status_code == 503


# ── Outbound dispatch (N-15 + signing) ──────────────────────────────────


@pytest.mark.anyio
async def test_outbound_refuses_to_dispatch_without_secret(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_BASE", "https://n8n.test/webhook")
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", "")
    monkeypatch.setattr(
        publish_service, "is_publishing_enabled", AsyncMock(return_value=True)
    )
    brand = _make_brand()
    cal_item = _make_item("x", "publishing")
    content = _make_content(cal_item)

    with pytest.raises(PublishPreflightError, match="N8N_WEBHOOK_SECRET"):
        await dispatch_to_n8n(content, cal_item, brand)


class _CaptureClient:
    captured: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, content=None, headers=None, **kwargs):
        _CaptureClient.captured = {"url": url, "content": content, "headers": headers}
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"status": "accepted"})
        return resp


@pytest.mark.anyio
async def test_outbound_sends_secret_and_event_id(monkeypatch):
    monkeypatch.setattr(settings, "N8N_WEBHOOK_BASE", "https://n8n.test/webhook")
    monkeypatch.setattr(settings, "N8N_WEBHOOK_SECRET", "out-secret")
    monkeypatch.setattr(
        publish_service, "is_publishing_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(publish_service.httpx, "AsyncClient", _CaptureClient)
    # The HMAC config field lands with the concurrent config change set; a
    # pydantic model rejects assignment to undeclared fields, so probe it.
    original_hmac = getattr(settings, "N8N_WEBHOOK_HMAC_SECRET", None)
    try:
        settings.N8N_WEBHOOK_HMAC_SECRET = "out-hmac"
        hmac_configurable = True
    except Exception:
        hmac_configurable = False

    try:
        brand = _make_brand()
        cal_item = _make_item("x", "publishing")
        content = _make_content(cal_item)

        result = await dispatch_to_n8n(content, cal_item, brand)
        assert result == {"status": "accepted"}

        headers = _CaptureClient.captured["headers"]
        body = _CaptureClient.captured["content"]
        assert headers["X-Webhook-Secret"] == "out-secret"
        assert headers["X-Webhook-Event-Id"]
        assert json.loads(body)["channel"] == "x"
        if hmac_configurable:
            ts = headers["X-Webhook-Timestamp"]
            expected = hmac.new(
                b"out-hmac", ts.encode() + b"." + body, hashlib.sha256
            ).hexdigest()
            assert headers["X-Webhook-Signature"] == f"sha256={expected}"
    finally:
        if hmac_configurable and original_hmac is not None:
            settings.N8N_WEBHOOK_HMAC_SECRET = original_hmac


# ── Kill switch ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_killswitch_blocks_n8n_dispatch(monkeypatch):
    monkeypatch.setattr(
        publish_service, "is_publishing_enabled", AsyncMock(return_value=False)
    )
    with pytest.raises(PublishingDisabledError):
        await dispatch_to_n8n(
            _make_content(_make_item("x", "publishing")),
            _make_item("x", "publishing"),
            _make_brand(),
        )


@pytest.mark.anyio
async def test_killswitch_blocks_direct_publish(monkeypatch):
    monkeypatch.setattr(
        publish_service, "is_publishing_enabled", AsyncMock(return_value=False)
    )
    cal_item = _make_item("instagram", "publishing")
    with pytest.raises(PublishingDisabledError):
        await publish_direct(
            MagicMock(), _make_content(cal_item), cal_item, _make_brand()
        )


@pytest.mark.anyio
async def test_killswitch_freezes_scheduler_sweep(monkeypatch):
    from app.scheduler import publish_checker

    session = _Session([_Rows(scalar={"enabled": False})])
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)
    n8n = AsyncMock()
    monkeypatch.setattr(publish_checker, "dispatch_to_n8n", n8n)

    await publish_checker.check_due_content()

    assert len(session.executed) == 1  # only the kill-switch read ran
    spawn.assert_not_called()
    n8n.assert_not_awaited()


@pytest.mark.anyio
async def test_killswitch_read_fails_closed(monkeypatch):
    class _BrokenSession:
        async def execute(self, *a, **kw):
            raise RuntimeError("system_flags table missing")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(
        publish_service, "async_session_factory", lambda: _BrokenSession()
    )
    assert await publish_service.is_publishing_enabled() is False


# ── Compare-and-set claim (P0-04 / N-14) ────────────────────────────────


@pytest.mark.anyio
async def test_claim_is_compare_and_set():
    from app.scheduler import publish_checker

    session = _Session([_Rows(scalar=None)])  # another process won the row
    claimed = await publish_checker._claim_for_publishing(session, uuid.uuid4())

    assert claimed is False
    params = session.executed[0].compile().params
    assert "publishing" in params.values()
    assert "scheduled" in params.values()
    session.commit.assert_awaited()


@pytest.mark.anyio
async def test_checker_skips_item_claimed_elsewhere(monkeypatch):
    from app.scheduler import publish_checker

    brand = _make_brand()
    cal_item = _make_item("instagram", "scheduled")
    content = _make_content(cal_item)
    content.brand = brand

    session = _Session(
        [
            _Rows(scalar=None),  # sweep-start kill-switch read (absent → on)
            _Rows([]),  # stuck sweep
            _Rows([cal_item]),  # due items
            _Rows(scalar=None),  # per-item kill-switch read
            _Rows([content]),  # current content
            _Rows(scalar=None),  # CAS claim: no row — claimed elsewhere
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    monkeypatch.setattr(publish_checker, "get_publisher", lambda ch, kind: object())
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)
    n8n = AsyncMock()
    monkeypatch.setattr(publish_checker, "dispatch_to_n8n", n8n)

    await publish_checker.check_due_content()

    spawn.assert_not_called()
    n8n.assert_not_awaited()


# ── Signed media URLs for third-party fetchers ──────────────────────────


def test_media_urls_for_third_parties_are_signed(monkeypatch):
    from urllib.parse import parse_qs, urlparse

    from app.utils.media_sign import verify_media_sig

    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.test")
    monkeypatch.setattr(settings, "MEDIA_PROXY_TOKEN", "media-token")
    cal_item = _make_item("instagram", "scheduled")
    content = _make_content(
        cal_item, generation_metadata={"branded_image": "images/b/i.png"}
    )

    media = publish_service.resolve_media(content, cal_item)

    assert media.public_url.startswith("https://api.test/api/v1/files/images/b/i.png?")
    query = parse_qs(urlparse(media.public_url).query)
    assert verify_media_sig("images/b/i.png", query["mt"][0], query["exp"][0])
    # Transform params stay outside the signature.
    assert query["fmt"] == ["jpg"]


# ── Stuck-publishing sweep (reconcile-before-retry) ─────────────────────


@pytest.mark.anyio
async def test_stuck_sweep_marks_failed_with_unreconciled_note(monkeypatch):
    from app.scheduler import publish_checker

    stuck = _make_item("instagram", "publishing")
    session = _Session(
        [
            _Rows(scalar=None),  # kill-switch read (absent → enabled)
            _Rows([stuck]),  # stuck items
            _Rows([]),  # due query
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    notify = AsyncMock()
    monkeypatch.setattr(publish_checker, "notify_failure", notify)

    await publish_checker.check_due_content()

    assert stuck.status == "failed"
    assert (
        stuck.generation_metadata["publish_note"]
        == publish_checker.UNRECONCILED_NOTE
    )
    notify.assert_awaited_once()


# ── Kill-switch endpoint (admin-only + audit-logged) ────────────────────


@pytest.mark.anyio
async def test_killswitch_put_is_audit_logged(monkeypatch):
    user = MagicMock(role="admin", email="admin@test", id=uuid.uuid4())
    db = _Session([_Rows(scalar=None), _Rows()])
    recorder = AsyncMock()
    monkeypatch.setattr(system_api.audit_service, "record_audit", recorder)

    resp = await system_api.set_publishing_kill_switch(
        system_api.PublishingKillSwitch(enabled=False),
        request=MagicMock(),
        db=db,
        current_user=user,
    )

    assert resp == {"enabled": False}
    recorder.assert_awaited_once()
    kwargs = recorder.await_args.kwargs
    assert kwargs["new_values"] == {"publishing_enabled": False}
    assert kwargs["entity_type"] == "system"
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_killswitch_put_rejects_non_admin(monkeypatch):
    user = MagicMock(role="manager", email="m@test", id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await system_api.set_publishing_kill_switch(
            system_api.PublishingKillSwitch(enabled=False),
            request=MagicMock(),
            db=_Session([]),
            current_user=user,
        )
    assert exc.value.status_code == 403
