"""Tests for the direct Teams (MessageCard webhook) and WordPress blog publishers."""

import base64
import json
import logging
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.config import settings
from app.services.publishers.base import MediaBundle
from app.services.publishers.blog import BlogPublisher, _render_paragraphs
from app.services.publishers.teams import TEAMS_MEDIA_URL_TTL, TeamsPublisher
from app.utils.media_sign import verify_media_sig

# Keep a reference to the real client class — the factory below closes over it
# after monkeypatch swaps httpx.AsyncClient for the factory itself.
_RealAsyncClient = httpx.AsyncClient


def _mock_async_client(monkeypatch, handler):
    """Route every httpx.AsyncClient request through a MockTransport handler."""

    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _content(body_text: str = "Body text"):
    return SimpleNamespace(
        generation_metadata={},
        platform_metadata=None,
        caption="Primary caption",
        body_text=body_text,
        hashtags=["#fallback"],
        headline="A headline",
    )


_BRAND = SimpleNamespace(name="Acme")

_IMAGE_BYTES = b"\x89PNG-fake-image"
_MEDIA_PATH = "/api/v1/files/content-images/pic.png"
_PUBLIC_URL = f"https://api.example.com{_MEDIA_PATH}?mt=short-sig&exp=123"


def _media(kind: str, data: bytes | None = _IMAGE_BYTES, public_url: str | None = _PUBLIC_URL):
    async def loader():
        return data

    return MediaBundle(
        kind=kind,
        public_url=public_url,
        bytes_loader=loader if data is not None else None,
        mime="image/png" if kind == "image" else "video/mp4",
    )


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

_WEBHOOK_URL = "https://acme.webhook.office.example.com/webhookb2/SECRET-PATH-TOKEN/IncomingWebhook/abc"
TEAMS_CREDS = {"webhook_url": _WEBHOOK_URL}


def _assert_signed_for_30_days(url: str) -> None:
    parts = urlsplit(url)
    assert parts.path == _MEDIA_PATH
    query = parse_qs(parts.query)
    mt, exp = query["mt"][0], query["exp"][0]
    # Valid signature over the URL path, expiring ~30 days out (not the
    # short publish-window TTL the bundle URL carried).
    assert verify_media_sig(_MEDIA_PATH, mt, exp)
    assert int(exp) > time.time() + TEAMS_MEDIA_URL_TTL - 3600


@pytest.mark.anyio
async def test_teams_image_card_with_30_day_signed_url(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROXY_TOKEN", "test-media-token")
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == _WEBHOOK_URL
        calls["json"] = json.loads(request.content)
        return httpx.Response(200, text="1")

    _mock_async_client(monkeypatch, handler)

    outcome = await TeamsPublisher().publish(
        _content(), SimpleNamespace(channel="teams"), _BRAND, TEAMS_CREDS,
        _media("image"),
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id is None  # webhooks return no post id
    assert outcome.extra["synthetic_post_id"] == "teams-webhook"

    card = calls["json"]
    assert card["@type"] == "MessageCard"
    assert card["summary"] == "A headline"
    section = card["sections"][0]
    assert section["activityTitle"] == "A headline"
    assert section["text"] == "Primary caption"
    _assert_signed_for_30_days(section["images"][0]["image"])


@pytest.mark.anyio
async def test_teams_video_card_gets_view_video_action(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROXY_TOKEN", "test-media-token")
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["json"] = json.loads(request.content)
        return httpx.Response(200, text="1")

    _mock_async_client(monkeypatch, handler)

    outcome = await TeamsPublisher().publish(
        _content(), SimpleNamespace(channel="teams"), _BRAND, TEAMS_CREDS,
        _media("video"),
    )

    assert outcome.status == "published"
    card = calls["json"]
    assert "images" not in card["sections"][0]
    (action,) = card["potentialAction"]
    assert action["@type"] == "OpenUri"
    assert action["name"] == "View video"
    _assert_signed_for_30_days(action["targets"][0]["uri"])


@pytest.mark.anyio
async def test_teams_missing_webhook_url_fails_actionably():
    outcome = await TeamsPublisher().publish(
        _content(), SimpleNamespace(channel="teams"), _BRAND, {}, _media("image")
    )

    assert outcome.status == "failed"
    assert "Teams webhook URL not configured" in outcome.error
    assert "Brand > Channels > Teams" in outcome.error


@pytest.mark.anyio
async def test_teams_http_error_never_leaks_webhook_url(monkeypatch, caplog):
    monkeypatch.setattr(settings, "MEDIA_PROXY_TOKEN", "test-media-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    _mock_async_client(monkeypatch, handler)

    with caplog.at_level(logging.DEBUG):
        outcome = await TeamsPublisher().publish(
            _content(), SimpleNamespace(channel="teams"), _BRAND, TEAMS_CREDS,
            _media("image"),
        )

    assert outcome.status == "failed"
    assert outcome.error == "Teams webhook returned HTTP 500"
    assert "SECRET-PATH-TOKEN" not in outcome.error
    # The webhook URL is a credential — no app log line may carry it.
    for record in caplog.records:
        if record.name.startswith("app"):
            assert "SECRET-PATH-TOKEN" not in record.getMessage()


@pytest.mark.anyio
async def test_teams_transport_error_reduced_to_exception_type(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_PROXY_TOKEN", "test-media-token")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await TeamsPublisher().publish(
        _content(), SimpleNamespace(channel="teams"), _BRAND, TEAMS_CREDS,
        _media("image"),
    )

    assert outcome.status == "failed"
    assert outcome.error == "Teams webhook request failed: ConnectError"
    assert "SECRET-PATH-TOKEN" not in outcome.error


# ---------------------------------------------------------------------------
# Blog (WordPress)
# ---------------------------------------------------------------------------

BLOG_CREDS = {
    "platform": "wordpress",
    "base_url": "https://blog.example.com",
    "username": "author",
    "app_password": "abcd efgh ijkl",
}

_EXPECTED_BASIC = "Basic " + base64.b64encode(b"author:abcd efgh ijkl").decode()


def test_render_paragraphs_escapes_and_splits():
    html_out = _render_paragraphs("First para\nsecond line\n\n<b>Second</b> para")
    assert html_out == (
        "<p>First para<br />second line</p>\n"
        "<p>&lt;b&gt;Second&lt;/b&gt; para</p>"
    )


@pytest.mark.anyio
async def test_blog_uploads_media_and_publishes_post(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://blog.example.com/wp-json/wp/v2/media":
            calls["media_auth"] = request.headers["Authorization"]
            calls["media_body"] = request.content
            return httpx.Response(
                201,
                json={"id": 55, "source_url": "https://blog.example.com/f.png"},
            )
        if url == "https://blog.example.com/wp-json/wp/v2/posts":
            calls["post_auth"] = request.headers["Authorization"]
            calls["post_json"] = json.loads(request.content)
            return httpx.Response(
                201, json={"id": 900, "link": "https://blog.example.com/?p=900"}
            )
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await BlogPublisher().publish(
        _content(), SimpleNamespace(channel="website_blog", id="item-1"), _BRAND,
        BLOG_CREDS, _media("image"),
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "900"
    assert outcome.extra["link"] == "https://blog.example.com/?p=900"

    # Application-password Basic auth on both requests.
    assert calls["media_auth"] == _EXPECTED_BASIC
    assert calls["post_auth"] == _EXPECTED_BASIC
    # Multipart upload carried the raw bytes + alt text.
    assert _IMAGE_BYTES in calls["media_body"]
    assert b'name="alt_text"' in calls["media_body"]

    post = calls["post_json"]
    assert post["title"] == "A headline"
    assert post["status"] == "publish"
    assert post["featured_media"] == 55
    assert post["content"] == "<p>Body text</p>"


@pytest.mark.anyio
async def test_blog_video_embedded_not_featured(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/wp-json/wp/v2/media"):
            return httpx.Response(
                201,
                json={"id": 56, "source_url": "https://blog.example.com/v.mp4"},
            )
        if url.endswith("/wp-json/wp/v2/posts"):
            calls["post_json"] = json.loads(request.content)
            return httpx.Response(201, json={"id": 901, "link": "l"})
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await BlogPublisher().publish(
        _content(), SimpleNamespace(channel="website_blog", id="item-2"), _BRAND,
        BLOG_CREDS, _media("video", data=b"mp4-bytes"),
    )

    assert outcome.status == "published"
    post = calls["post_json"]
    assert "featured_media" not in post  # videos embed instead of featuring
    assert '<video controls src="https://blog.example.com/v.mp4">' in post["content"]


@pytest.mark.anyio
async def test_blog_unconfigured_fails_with_manual_publish_hint():
    outcome = await BlogPublisher().publish(
        _content(), SimpleNamespace(channel="website_blog", id="i"), _BRAND, {},
        _media("image"),
    )

    assert outcome.status == "failed"
    assert "website_blog not configured" in outcome.error
    assert "WordPress credentials" in outcome.error
    assert "publish manually from Content Studio" in outcome.error


@pytest.mark.anyio
async def test_blog_unsupported_platform_names_drivers():
    outcome = await BlogPublisher().publish(
        _content(), SimpleNamespace(channel="website_blog", id="i"), _BRAND,
        {**BLOG_CREDS, "platform": "ghost"}, _media("image"),
    )

    assert outcome.status == "failed"
    assert "'ghost' is not supported" in outcome.error
    assert "supported drivers: wordpress" in outcome.error


@pytest.mark.anyio
async def test_blog_wp_error_mapped_with_credentials_hint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "code": "incorrect_password",
                "message": "The provided password is an invalid application password.",
            },
        )

    _mock_async_client(monkeypatch, handler)

    outcome = await BlogPublisher().publish(
        _content(), SimpleNamespace(channel="website_blog", id="i"), _BRAND,
        BLOG_CREDS, _media("image"),
    )

    assert outcome.status == "failed"
    assert "invalid application password" in outcome.error
    assert "Brand > Channels > Website/Blog" in outcome.error
    # The actual credential never leaks into the error.
    assert "abcd efgh ijkl" not in outcome.error
