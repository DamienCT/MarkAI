"""Tests for the direct TikTok publisher — FILE_UPLOAD flow + token refresh."""

import json
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qsl

import httpx
import pytest

import app.auth.models  # noqa: F401 — registers the User mapper (Brand FKs reference it)
import app.models  # noqa: F401 — registers all model mappers
from app.models.brand import Brand
from app.services.publishers import tiktok as tiktok_module
from app.services.publishers.base import MediaBundle
from app.services.publishers.tiktok import (
    INIT_URL,
    STATUS_URL,
    TOKEN_URL,
    TikTokPublisher,
    _plan_chunks,
)

# Keep a reference to the real client class — the factory below closes over it
# after monkeypatch swaps httpx.AsyncClient for the factory itself.
_RealAsyncClient = httpx.AsyncClient


def _mock_async_client(monkeypatch, handler):
    """Route every httpx.AsyncClient request through a MockTransport handler."""

    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


TIKTOK_CREDS = {
    "client_key": "ckey-value",
    "client_secret": "csecret-value",
    "access_token": "old-access-token",
    "refresh_token": "old-refresh-token",
    "handle": "@acme",
}

_UPLOAD_URL = "https://upload.tiktokapis.example.com/video/upload?upload_token=SECRET-UPLOAD-SIG"
_VIDEO_BYTES = b"0123456789"  # 10 bytes → single chunk


def _content():
    return SimpleNamespace(
        generation_metadata={
            "platform_adaptations": {
                "tiktok": {"caption": "Adapted caption", "hashtags": ["#fyp"]}
            }
        },
        platform_metadata=None,
        caption="Primary caption",
        body_text="Body text",
        hashtags=["#fallback"],
        headline="A headline",
    )


_CALENDAR_ITEM = SimpleNamespace(channel="tiktok")


def _brand(channel_cfg: dict | None = None) -> Brand:
    return Brand(
        id=uuid.uuid4(),
        name="Acme",
        brand_guidelines={
            "channels": {
                "tiktok": channel_cfg
                if channel_cfg is not None
                else dict(TIKTOK_CREDS)
            }
        },
    )


def _video_media(data: bytes = _VIDEO_BYTES):
    async def loader():
        return data

    return MediaBundle(kind="video", bytes_loader=loader, mime="video/mp4")


def _image_media():
    return MediaBundle(kind="image", public_url="https://api.example.com/x.png")


def _ok(data: dict) -> dict:
    return {"data": data, "error": {"code": "ok", "message": ""}}


# ---------------------------------------------------------------------------
# Chunk planning
# ---------------------------------------------------------------------------


def test_plan_chunks_single_chunk_up_to_64mb():
    assert _plan_chunks(10) == (10, 1)  # <5MB uploads whole as one chunk
    assert _plan_chunks(64 * 1024 * 1024) == (64 * 1024 * 1024, 1)


def test_plan_chunks_large_video_uses_10mb_chunks_with_merged_tail():
    size = 95 * 1024 * 1024
    chunk_size, total = _plan_chunks(size)
    assert chunk_size == 10 * 1024 * 1024
    # floor(95/10) = 9 chunks; the 5MB tail merges into the final chunk.
    assert total == 9


# ---------------------------------------------------------------------------
# Publish flow (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_tiktok_happy_path_init_upload_status(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == INIT_URL:
            calls["init_auth"] = request.headers["Authorization"]
            calls["init_body"] = json.loads(request.content)
            return httpx.Response(
                200, json=_ok({"publish_id": "pub-1", "upload_url": _UPLOAD_URL})
            )
        if url == _UPLOAD_URL and request.method == "PUT":
            calls["upload_headers"] = dict(request.headers)
            calls["upload_body"] = request.content
            return httpx.Response(201)
        if url == STATUS_URL:
            calls["status_body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json=_ok(
                    {
                        "status": "PUBLISH_COMPLETE",
                        "publicaly_available_post_id": [7245316],
                    }
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, _brand(), TIKTOK_CREDS, _video_media()
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "7245316"
    assert outcome.extra["publish_id"] == "pub-1"
    assert outcome.extra["privacy_level"] == "SELF_ONLY"  # unaudited-app default

    assert calls["init_auth"] == "Bearer old-access-token"
    assert calls["init_body"]["source_info"] == {
        "source": "FILE_UPLOAD",
        "video_size": len(_VIDEO_BYTES),
        "chunk_size": len(_VIDEO_BYTES),
        "total_chunk_count": 1,
    }
    assert calls["init_body"]["post_info"]["privacy_level"] == "SELF_ONLY"
    assert calls["init_body"]["post_info"]["title"].startswith("Adapted caption")
    assert "#fyp" in calls["init_body"]["post_info"]["title"]

    assert calls["upload_body"] == _VIDEO_BYTES
    assert calls["upload_headers"]["content-range"] == "bytes 0-9/10"
    assert calls["status_body"] == {"publish_id": "pub-1"}


@pytest.mark.anyio
async def test_tiktok_privacy_level_read_from_channel_cfg(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == INIT_URL:
            calls["init_body"] = json.loads(request.content)
            return httpx.Response(
                200, json=_ok({"publish_id": "pub-2", "upload_url": _UPLOAD_URL})
            )
        if url == _UPLOAD_URL:
            return httpx.Response(201)
        if url == STATUS_URL:
            return httpx.Response(200, json=_ok({"status": "PUBLISH_COMPLETE"}))
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)
    brand = _brand({**TIKTOK_CREDS, "privacy_level": "PUBLIC_TO_EVERYONE"})

    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, brand, TIKTOK_CREDS, _video_media()
    )

    assert outcome.status == "published"
    # No publicaly_available_post_id yet → the publish_id is recorded.
    assert outcome.platform_post_id == "pub-2"
    assert calls["init_body"]["post_info"]["privacy_level"] == "PUBLIC_TO_EVERYONE"


@pytest.mark.anyio
async def test_tiktok_401_refreshes_token_and_writes_back(monkeypatch):
    calls: dict = {"init_auths": []}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == INIT_URL:
            auth = request.headers["Authorization"]
            calls["init_auths"].append(auth)
            if auth == "Bearer old-access-token":
                return httpx.Response(
                    401,
                    json={
                        "data": {},
                        "error": {
                            "code": "access_token_invalid",
                            "message": "The access token is invalid",
                        },
                    },
                )
            assert auth == "Bearer new-access-token"
            return httpx.Response(
                200, json=_ok({"publish_id": "pub-3", "upload_url": _UPLOAD_URL})
            )
        if url == TOKEN_URL:
            calls["token_form"] = dict(parse_qsl(request.content.decode()))
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 86400,
                },
            )
        if url == _UPLOAD_URL:
            return httpx.Response(201)
        if url == STATUS_URL:
            assert request.headers["Authorization"] == "Bearer new-access-token"
            return httpx.Response(
                200,
                json=_ok(
                    {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [9]}
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    # Spy on flag_modified while still exercising the real ORM call.
    flagged = []
    real_flag_modified = tiktok_module.flag_modified

    def spy(obj, attr):
        flagged.append((obj, attr))
        real_flag_modified(obj, attr)

    monkeypatch.setattr(tiktok_module, "flag_modified", spy)

    brand = _brand()
    creds = dict(TIKTOK_CREDS)
    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, brand, creds, _video_media()
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "9"
    assert calls["init_auths"] == [
        "Bearer old-access-token",
        "Bearer new-access-token",
    ]
    assert calls["token_form"] == {
        "client_key": "ckey-value",
        "client_secret": "csecret-value",
        "grant_type": "refresh_token",
        "refresh_token": "old-refresh-token",
    }

    # New tokens written back into the brand's channel config + flag_modified.
    cfg = brand.brand_guidelines["channels"]["tiktok"]
    assert cfg["access_token"] == "new-access-token"
    assert cfg["refresh_token"] == "new-refresh-token"
    assert flagged == [(brand, "brand_guidelines")]


@pytest.mark.anyio
async def test_tiktok_401_without_refresh_materials_fails_with_24h_hint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == INIT_URL
        return httpx.Response(
            401,
            json={
                "data": {},
                "error": {"code": "access_token_invalid", "message": "invalid"},
            },
        )

    _mock_async_client(monkeypatch, handler)
    creds = {"access_token": "old-access-token", "handle": "@acme"}

    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, _brand({}), creds, _video_media()
    )

    assert outcome.status == "failed"
    assert "24h" in outcome.error
    assert "Brand > Channels > TikTok" in outcome.error
    assert "old-access-token" not in outcome.error


@pytest.mark.anyio
async def test_tiktok_failed_status_maps_fail_reason(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == INIT_URL:
            return httpx.Response(
                200, json=_ok({"publish_id": "pub-4", "upload_url": _UPLOAD_URL})
            )
        if url == _UPLOAD_URL:
            return httpx.Response(201)
        if url == STATUS_URL:
            return httpx.Response(
                200,
                json=_ok(
                    {"status": "FAILED", "fail_reason": "video_format_check_failed"}
                ),
            )
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, _brand(), TIKTOK_CREDS, _video_media()
    )

    assert outcome.status == "failed"
    assert "video_format_check_failed" in outcome.error
    # The pre-signed upload URL is a credential — never in the error.
    assert "SECRET-UPLOAD-SIG" not in outcome.error


@pytest.mark.anyio
async def test_tiktok_image_content_rejected():
    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, _brand(), TIKTOK_CREDS, _image_media()
    )

    assert outcome.status == "failed"
    assert "TikTok requires video content" in outcome.error


@pytest.mark.anyio
async def test_tiktok_unconfigured_fails_actionably():
    outcome = await TikTokPublisher().publish(
        _content(), _CALENDAR_ITEM, _brand({}), {}, _video_media()
    )

    assert outcome.status == "failed"
    assert "not configured" in outcome.error
    assert "Brand > Channels > TikTok" in outcome.error
