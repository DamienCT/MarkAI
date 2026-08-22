"""Regression tests for the publishing-ops hardening (audit cluster D).

Covers, in the single-path world (native publishers only — the n8n hop and
its callback endpoint are gone):
- record_publish_result is the only result writer: published sets
  status/published_at and MERGES platform_metadata; failed stores the error
  without clobbering other generation metadata
- a background publish task refuses to run when the item's status changed
  underneath it (stuck sweep / operator action) — results stay monotonic
- dispatch claim is compare-and-set scheduled→publishing (P0-04, N-14)
- publishing kill switch blocks the direct path + freezes the sweep (P0-11),
  and an in-flight task releases its claim when the switch engages mid-tick
- media URLs handed to platforms are HMAC-signed; credentials never appear
  in request URLs or log lines (N-01)
- stuck-'publishing' sweep marks failed-unreconciled (reconcile-before-retry)
- kill-switch PUT endpoint is admin-only and audit-logged
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.api.v1 import system as system_api
from app.config import settings
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services import publish_service
from app.services.publish_service import (
    PublishingDisabledError,
    publish_direct,
    record_publish_result,
)
from app.services.publishers.base import PublishOutcome

BRAND_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


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


def _fake_db():
    db = MagicMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


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


# ── record_publish_result (the only result writer) ──────────────────────


@pytest.mark.anyio
async def test_record_publish_result_published_merges_platform_metadata():
    cal_item = _make_item("instagram", "publishing")
    content = _make_content(
        cal_item, platform_metadata={"instagram": {"caption": "Adapted caption"}}
    )
    db = _fake_db()

    await record_publish_result(
        db,
        content,
        cal_item,
        "instagram",
        PublishOutcome(platform_post_id="p42", status="published"),
    )

    assert cal_item.status == "published"
    assert cal_item.published_at is not None
    assert content.platform_post_id == "p42"
    channel_meta = content.platform_metadata["instagram"]
    assert channel_meta["post_id"] == "p42"
    assert channel_meta["published_at"]
    # Merge, not replace: pre-existing per-channel adaptation data survives.
    assert channel_meta["caption"] == "Adapted caption"
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_record_publish_result_failed_preserves_other_metadata():
    cal_item = _make_item("instagram", "publishing")
    content = _make_content(
        cal_item, generation_metadata={"branded_image": "images/b/i.png"}
    )
    db = _fake_db()

    await record_publish_result(
        db,
        content,
        cal_item,
        "instagram",
        PublishOutcome(platform_post_id=None, status="failed", error="token expired"),
    )

    assert cal_item.status == "failed"
    assert cal_item.published_at is None
    assert content.generation_metadata["publish_error"] == "token expired"
    assert content.generation_metadata["branded_image"] == "images/b/i.png"
    db.commit.assert_awaited()


# ── Background task status guard (monotonic results) ────────────────────


@pytest.mark.anyio
async def test_run_direct_publish_skips_when_status_changed(monkeypatch):
    """The stuck sweep (or an operator) changed the item's status while the
    task waited on the semaphore — publishing anyway would clobber that
    state and could duplicate a rescheduled post."""
    from app.scheduler import publish_checker

    cal_item = _make_item("instagram", "failed")  # swept while queued
    content = _make_content(cal_item)
    session = _Session([_Rows(scalar=cal_item), _Rows(scalar=content)])
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    direct = AsyncMock()
    monkeypatch.setattr(publish_checker, "publish_direct", direct)

    await publish_checker._run_direct_publish(cal_item.id, content.id)

    direct.assert_not_awaited()
    assert cal_item.status == "failed"


@pytest.mark.anyio
async def test_run_direct_publish_success_writes_job_log(monkeypatch):
    from app.scheduler import publish_checker

    brand = _make_brand()
    cal_item = _make_item("instagram", "publishing")
    cal_item.brand = brand
    content = _make_content(cal_item)
    session = _Session([_Rows(scalar=cal_item), _Rows(scalar=content)])
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    direct = AsyncMock(
        return_value=PublishOutcome(platform_post_id="p7", status="published")
    )
    monkeypatch.setattr(publish_checker, "publish_direct", direct)
    notify = AsyncMock()
    monkeypatch.setattr(publish_checker, "notify_failure", notify)

    await publish_checker._run_direct_publish(cal_item.id, content.id)

    direct.assert_awaited_once_with(session, content, cal_item, brand)
    log = session.add.call_args.args[0]
    assert log.job_name == "publish_direct"
    assert log.status == "completed"
    assert log.details["platform_post_id"] == "p7"
    session.commit.assert_awaited()
    notify.assert_not_awaited()


@pytest.mark.anyio
async def test_run_direct_publish_failure_notifies(monkeypatch):
    from app.scheduler import publish_checker

    brand = _make_brand()
    cal_item = _make_item("x", "publishing")
    cal_item.brand = brand
    content = _make_content(cal_item)
    session = _Session([_Rows(scalar=cal_item), _Rows(scalar=content)])
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    direct = AsyncMock(
        return_value=PublishOutcome(
            platform_post_id=None,
            status="failed",
            error="no publisher supports channel 'x' with media kind 'image'",
        )
    )
    monkeypatch.setattr(publish_checker, "publish_direct", direct)
    notify = AsyncMock()
    monkeypatch.setattr(publish_checker, "notify_failure", notify)

    await publish_checker._run_direct_publish(cal_item.id, content.id)

    log = session.add.call_args.args[0]
    assert log.status == "failed"
    assert "no publisher supports" in log.details["error"]
    notify.assert_awaited_once()


# ── Kill switch ─────────────────────────────────────────────────────────


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

    await publish_checker.check_due_content()

    assert len(session.executed) == 1  # only the kill-switch read ran
    spawn.assert_not_called()


@pytest.mark.anyio
async def test_killswitch_engaged_midflight_releases_claim(monkeypatch):
    """The switch flipped between the tick's claim and the background task's
    run: nothing left the backend, so the claim rolls back to 'scheduled'
    and the item publishes once the switch re-enables."""
    from app.scheduler import publish_checker

    brand = _make_brand()
    cal_item = _make_item("instagram", "publishing")
    cal_item.brand = brand
    content = _make_content(cal_item)
    session = _Session(
        [
            _Rows(scalar=cal_item),  # item re-load
            _Rows(scalar=content),  # content re-load
            _Rows(),  # _release_claim UPDATE
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    direct = AsyncMock(side_effect=PublishingDisabledError("switch engaged"))
    monkeypatch.setattr(publish_checker, "publish_direct", direct)

    await publish_checker._run_direct_publish(cal_item.id, content.id)

    release_params = session.executed[2].compile().params
    assert "scheduled" in release_params.values()
    assert "publishing" in release_params.values()
    session.commit.assert_awaited()
    session.add.assert_not_called()  # no job log — nothing was dispatched


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
            _Rows(scalar=None),  # per-item kill-switch read: global
            _Rows(scalar=None),  # per-item kill-switch read: brand scope
            _Rows(scalar=None),  # per-item kill-switch read: channel scope
            _Rows([content]),  # current content
            _Rows(scalar=None),  # CAS claim: no row — claimed elsewhere
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)

    await publish_checker.check_due_content()

    spawn.assert_not_called()


# ── Signed media URLs + credentials never in URLs/logs (N-01) ───────────


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


class _TokenCaptureClient:
    """Captures the FB page-token exchange request; never talks to Meta."""

    captured: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None, **kwargs):
        _TokenCaptureClient.captured = {
            "url": url,
            "params": params,
            "headers": headers,
        }
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"access_token": "PAGE-TOKEN"})
        return resp


@pytest.mark.anyio
async def test_fb_page_token_exchange_keeps_token_out_of_url(monkeypatch):
    """The stored token must ride in the Authorization header, never the URL
    or query params — httpx logs request URLs and str(HTTPStatusError)
    embeds them (N-01)."""
    monkeypatch.setattr(publish_service.httpx, "AsyncClient", _TokenCaptureClient)

    token = await publish_service._derive_facebook_page_token(
        "SECRET-USER-TOKEN", "page-1"
    )

    assert token == "PAGE-TOKEN"
    captured = _TokenCaptureClient.captured
    assert "SECRET-USER-TOKEN" not in captured["url"]
    assert "SECRET-USER-TOKEN" not in str(captured["params"])
    assert captured["headers"]["Authorization"] == "Bearer SECRET-USER-TOKEN"


@pytest.mark.anyio
async def test_fb_page_token_error_logs_are_redacted(monkeypatch, caplog):
    class _ExplodingClient(_TokenCaptureClient):
        async def get(self, url, params=None, headers=None, **kwargs):
            raise RuntimeError(
                "boom for url https://graph.facebook.com/"
                "?access_token=SECRET-USER-TOKEN"
            )

    monkeypatch.setattr(publish_service.httpx, "AsyncClient", _ExplodingClient)

    with caplog.at_level("WARNING", logger="app.services.publish_service"):
        token = await publish_service._derive_facebook_page_token(
            "SECRET-USER-TOKEN", "page-1"
        )

    assert token is None  # fails soft — caller falls back to the stored token
    assert "SECRET-USER-TOKEN" not in caplog.text


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
