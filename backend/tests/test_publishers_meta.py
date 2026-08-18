"""Tests for the Meta (Instagram/Facebook) direct publishers."""

import logging
from types import SimpleNamespace

import pytest

from app.services.publishers.base import MediaBundle
from app.services.publishers.meta import FacebookPublisher, InstagramPublisher

IG_CREDS = {"meta_access_token": "user-token", "instagram_account_id": "igid"}
FB_CREDS = {"meta_access_token": "user-token", "page_id": "pageid"}


# ── Fakes ────────────────────────────────────────────────────────────


class FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json = json_data
        self.status_code = status_code
        self.text = text or (str(json_data) if json_data is not None else "")

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class FakeClient:
    """Stand-in for httpx.AsyncClient — routes requests through a handler."""

    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self._handler("GET", url, kwargs)

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self._handler("POST", url, kwargs)


def _content(channel: str, caption: str = "Adapted caption"):
    return SimpleNamespace(
        generation_metadata={
            "platform_adaptations": {
                channel: {"caption": caption, "hashtags": ["#reels", "brand"]}
            }
        },
        platform_metadata=None,
        caption="Primary caption",
        body_text="Body text",
        hashtags=["#fallback"],
        headline="A headline",
    )


def _calendar_item(channel: str):
    return SimpleNamespace(channel=channel)


_BRAND = SimpleNamespace(name="Acme")

_VIDEO_BYTES = b"0123456789"  # 10 bytes


def _video_media():
    async def loader():
        return _VIDEO_BYTES

    return MediaBundle(
        kind="video",
        public_url="https://api.example.com/api/v1/files/videos/acme/item1/final.mp4",
        bytes_loader=loader,
        mime="video/mp4",
        size_bytes=None,
    )


def _calls_to(client, needle, method=None):
    return [
        c
        for c in client.calls
        if needle in c[1] and (method is None or c[0] == method)
    ]


# ── Instagram ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_ig_reels_happy_path(monkeypatch):
    """Container -> FINISHED -> media_publish, with the adapted caption."""

    def handler(method, url, kw):
        if "content_publishing_limit" in url:
            return FakeResponse({"data": [{"quota_usage": 3}]})
        if url.endswith("/igid/media") and method == "POST":
            return FakeResponse({"id": "container1"})
        if url.endswith("/container1") and method == "GET":
            return FakeResponse({"status_code": "FINISHED", "status": "Finished"})
        if url.endswith("/igid/media_publish") and method == "POST":
            return FakeResponse({"id": "17900001"})
        raise AssertionError(f"unexpected request: {method} {url}")

    client = FakeClient(handler)
    publisher = InstagramPublisher()
    monkeypatch.setattr(publisher, "_http", lambda: client)

    media = _video_media()
    outcome = await publisher.publish(
        _content("instagram"), _calendar_item("instagram"), _BRAND, IG_CREDS, media
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "17900001"
    assert outcome.extra["creation_id"] == "container1"

    # Container creation carries the REELS payload with the adapted caption
    (container_call,) = _calls_to(client, "/igid/media", method="POST")[:1]
    data = container_call[2]["data"]
    assert data["media_type"] == "REELS"
    assert data["video_url"] == media.public_url
    assert data["share_to_feed"] == "true"
    assert data["access_token"] == "user-token"
    assert data["caption"].startswith("Adapted caption")
    assert "#reels" in data["caption"] and "#brand" in data["caption"]

    # media_publish references the container
    publish_call = _calls_to(client, "media_publish", method="POST")[0]
    assert publish_call[2]["data"]["creation_id"] == "container1"


@pytest.mark.anyio
async def test_ig_container_error_fails_cleanly(monkeypatch):
    """A container that goes to ERROR fails with the status detail, no publish."""

    def handler(method, url, kw):
        if "content_publishing_limit" in url:
            return FakeResponse({"data": [{"quota_usage": 3}]})
        if url.endswith("/igid/media") and method == "POST":
            return FakeResponse({"id": "container1"})
        if url.endswith("/container1") and method == "GET":
            return FakeResponse(
                {"status_code": "ERROR", "status": "Error: video format not supported"}
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    client = FakeClient(handler)
    publisher = InstagramPublisher()
    monkeypatch.setattr(publisher, "_http", lambda: client)

    outcome = await publisher.publish(
        _content("instagram"),
        _calendar_item("instagram"),
        _BRAND,
        IG_CREDS,
        _video_media(),
    )

    assert outcome.status == "failed"
    assert outcome.platform_post_id is None
    assert "ERROR" in outcome.error
    assert "video format not supported" in outcome.error
    assert _calls_to(client, "media_publish") == []


@pytest.mark.anyio
async def test_ig_quota_warning_tolerated(monkeypatch, caplog):
    """quota_usage >= 90 logs a warning but never blocks publishing."""

    def handler(method, url, kw):
        if "content_publishing_limit" in url:
            return FakeResponse({"data": [{"quota_usage": 95}]})
        if url.endswith("/igid/media") and method == "POST":
            return FakeResponse({"id": "container1"})
        if url.endswith("/container1") and method == "GET":
            return FakeResponse({"status_code": "FINISHED"})
        if url.endswith("/igid/media_publish") and method == "POST":
            return FakeResponse({"id": "17900002"})
        raise AssertionError(f"unexpected request: {method} {url}")

    client = FakeClient(handler)
    publisher = InstagramPublisher()
    monkeypatch.setattr(publisher, "_http", lambda: client)

    with caplog.at_level(logging.WARNING, logger="app.services.publishers.meta"):
        outcome = await publisher.publish(
            _content("instagram"),
            _calendar_item("instagram"),
            _BRAND,
            IG_CREDS,
            _video_media(),
        )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "17900002"
    assert any("quota" in r.message.lower() for r in caplog.records)


# ── Facebook ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_fb_reels_three_phase_happy_path(monkeypatch):
    """start -> rupload binary (offset/file_size headers) -> finish -> ready."""

    upload_url = "https://rupload.facebook.com/video-upload/v25.0/vid1"

    def handler(method, url, kw):
        if url.endswith("/pageid/video_reels") and method == "POST":
            phase = kw["data"]["upload_phase"]
            if phase == "start":
                return FakeResponse({"video_id": "vid1", "upload_url": upload_url})
            if phase == "finish":
                assert kw["data"]["video_id"] == "vid1"
                assert kw["data"]["video_state"] == "PUBLISHED"
                assert kw["data"]["description"].startswith("Adapted caption")
                return FakeResponse({"success": True})
        if url == upload_url and method == "POST":
            return FakeResponse({"success": True})
        if url.endswith("/vid1") and method == "GET":
            return FakeResponse({"status": {"video_status": "ready"}})
        raise AssertionError(f"unexpected request: {method} {url}")

    async def fake_derive(token, page_id):
        assert token == "user-token"
        assert page_id == "pageid"
        return "page-token-xyz"

    monkeypatch.setattr(
        "app.services.publishers.meta._derive_facebook_page_token", fake_derive
    )

    client = FakeClient(handler)
    publisher = FacebookPublisher()
    monkeypatch.setattr(publisher, "_http", lambda: client)

    outcome = await publisher.publish(
        _content("facebook"),
        _calendar_item("facebook"),
        _BRAND,
        FB_CREDS,
        _video_media(),
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "vid1"
    assert outcome.extra.get("video_status") == "ready"

    # Binary upload used the rupload URL with the exact headers + raw bytes
    (upload_call,) = _calls_to(client, "rupload.facebook.com", method="POST")
    headers = upload_call[2]["headers"]
    assert headers["Authorization"] == "OAuth page-token-xyz"
    assert headers["offset"] == "0"
    assert headers["file_size"] == str(len(_VIDEO_BYTES))
    assert upload_call[2]["content"] == _VIDEO_BYTES

    # All Graph calls after derivation used the derived page token
    start_call = _calls_to(client, "/pageid/video_reels", method="POST")[0]
    assert start_call[2]["data"]["access_token"] == "page-token-xyz"
