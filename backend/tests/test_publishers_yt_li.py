"""Tests for the direct YouTube and LinkedIn publishers."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qsl

import httpx
import pytest

from app.config import settings
from app.services.publishers.base import MediaBundle
from app.services.publishers.linkedin import (
    LINKEDIN_VERSION,
    LinkedInChannelPublisher,
    LinkedInPublisher,
    LinkedInPublishError,
)
from app.services.publishers.youtube import (
    MAX_TITLE_LENGTH,
    YouTubePublisher,
    YouTubePublishError,
)

# Keep a reference to the real client class — the factory below closes over it
# after monkeypatch swaps httpx.AsyncClient for the factory itself.
_RealAsyncClient = httpx.AsyncClient


def _mock_async_client(monkeypatch, handler):
    """Route every httpx.AsyncClient request through a MockTransport handler."""

    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

_YT_CONFIG = {
    "client_id": "yt-client-id",
    "client_secret": "yt-client-secret",
    "refresh_token": "yt-refresh-token",
    "channel_id": "UC123",
}
_VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4-payload" * 64


def _youtube_handler(calls: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.startswith(
            "https://oauth2.googleapis.com/token"
        ):
            calls["token_form"] = dict(parse_qsl(request.content.decode()))
            return httpx.Response(200, json={"access_token": "fresh-token"})
        if request.method == "POST" and url.startswith(
            "https://www.googleapis.com/upload/youtube/v3/videos"
        ):
            calls["init_params"] = dict(request.url.params)
            calls["init_headers"] = dict(request.headers)
            calls["init_body"] = json.loads(request.content)
            return httpx.Response(
                200, headers={"Location": "https://upload.example.com/session-1"}
            )
        if request.method == "PUT" and url == "https://upload.example.com/session-1":
            calls["upload_headers"] = dict(request.headers)
            calls["upload_body"] = request.content
            return httpx.Response(
                200,
                json={"id": "yt-video-123", "status": {"privacyStatus": "public"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    return handler


@pytest.mark.anyio
async def test_youtube_refreshes_token_and_puts_to_resumable_location(monkeypatch):
    calls: dict = {}
    _mock_async_client(monkeypatch, _youtube_handler(calls))

    result = await YouTubePublisher(_YT_CONFIG).publish_video(
        _VIDEO_BYTES, title="My headline", description="Caption\n\n#tag1 #tag2"
    )

    # Token refresh used the brand's OAuth credentials
    assert calls["token_form"] == {
        "client_id": "yt-client-id",
        "client_secret": "yt-client-secret",
        "refresh_token": "yt-refresh-token",
        "grant_type": "refresh_token",
    }

    # Resumable init: right params, fresh token, spec-exact metadata
    assert calls["init_params"] == {"uploadType": "resumable", "part": "snippet,status"}
    assert calls["init_headers"]["authorization"] == "Bearer fresh-token"
    assert calls["init_headers"]["x-upload-content-length"] == str(len(_VIDEO_BYTES))
    assert calls["init_body"]["snippet"]["title"] == "My headline"
    assert calls["init_body"]["snippet"]["description"] == "Caption\n\n#tag1 #tag2"
    assert calls["init_body"]["snippet"]["categoryId"] == "22"
    assert calls["init_body"]["status"] == {
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": True,
    }

    # The raw bytes went to the Location URL with the fresh token
    assert calls["upload_body"] == _VIDEO_BYTES
    assert calls["upload_headers"]["authorization"] == "Bearer fresh-token"

    assert result["platform_post_id"] == "yt-video-123"
    assert result["status"] == "published"
    assert result["url"] == "https://www.youtube.com/watch?v=yt-video-123"


@pytest.mark.anyio
async def test_youtube_title_truncated_to_95_chars(monkeypatch):
    calls: dict = {}
    _mock_async_client(monkeypatch, _youtube_handler(calls))

    await YouTubePublisher(_YT_CONFIG).publish_video(
        _VIDEO_BYTES, title="x" * 200, description="d"
    )

    assert len(calls["init_body"]["snippet"]["title"]) == MAX_TITLE_LENGTH


@pytest.mark.anyio
async def test_youtube_missing_credentials_raises(monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "YOUTUBE_REFRESH_TOKEN", "")

    with pytest.raises(YouTubePublishError, match="credentials missing"):
        await YouTubePublisher({}).publish_video(b"x", title="t", description="d")


def test_youtube_falls_back_to_global_settings(monkeypatch):
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_ID", "global-id")
    monkeypatch.setattr(settings, "YOUTUBE_CLIENT_SECRET", "global-secret")
    monkeypatch.setattr(settings, "YOUTUBE_REFRESH_TOKEN", "global-refresh")

    publisher = YouTubePublisher({})
    assert publisher.client_id == "global-id"
    assert publisher.client_secret == "global-secret"
    assert publisher.refresh_token == "global-refresh"

    # Brand config wins over globals when present
    assert YouTubePublisher(_YT_CONFIG).client_id == "yt-client-id"


# ---------------------------------------------------------------------------
# LinkedIn
# ---------------------------------------------------------------------------

_LI_CONFIG = {"access_token": "li-token", "org_id": "555"}
_VIDEO_URN = "urn:li:video:C5F10AQGKQgqeSxAAA"

_9MB = 9 * 1024 * 1024
_CHUNK = 4 * 1024 * 1024
_9MB_BYTES = bytes(range(256)) * (_9MB // 256)

_INSTRUCTIONS = [
    {
        "uploadUrl": "https://upload.example.com/part1",
        "firstByte": 0,
        "lastByte": _CHUNK - 1,
    },
    {
        "uploadUrl": "https://upload.example.com/part2",
        "firstByte": _CHUNK,
        "lastByte": 2 * _CHUNK - 1,
    },
    {
        "uploadUrl": "https://upload.example.com/part3",
        "firstByte": 2 * _CHUNK,
        "lastByte": _9MB - 1,
    },
]
_ETAG_BY_URL = {
    "https://upload.example.com/part1": "etag-1",
    "https://upload.example.com/part2": "etag-2",
    "https://upload.example.com/part3": "etag-3",
}


def _linkedin_video_handler(calls: dict, video_status: str = "AVAILABLE"):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        action = request.url.params.get("action")

        if request.method == "PUT" and request.url.host == "upload.example.com":
            calls.setdefault("put_bodies", []).append((url, request.content))
            return httpx.Response(200, headers={"ETag": _ETAG_BY_URL[url]})

        if request.method == "POST" and request.url.path == "/rest/videos":
            calls.setdefault("video_headers", []).append(dict(request.headers))
            if action == "initializeUpload":
                calls["init_body"] = json.loads(request.content)
                return httpx.Response(
                    200,
                    json={
                        "value": {
                            "video": _VIDEO_URN,
                            "uploadInstructions": _INSTRUCTIONS,
                        }
                    },
                )
            if action == "finalizeUpload":
                calls["finalize_body"] = json.loads(request.content)
                return httpx.Response(200, json={})

        if request.method == "GET" and request.url.path.startswith("/rest/videos/"):
            calls["poll_path"] = request.url.raw_path.decode()
            return httpx.Response(200, json={"status": video_status})

        if request.method == "POST" and request.url.path == "/rest/posts":
            calls["post_body"] = json.loads(request.content)
            calls["post_headers"] = dict(request.headers)
            return httpx.Response(
                201, headers={"x-restli-id": "urn:li:share:7360000000000000001"}
            )

        raise AssertionError(f"Unexpected request: {request.method} {url}")

    return handler


async def _publish_linkedin_video(monkeypatch) -> tuple[dict, dict]:
    calls: dict = {}
    _mock_async_client(monkeypatch, _linkedin_video_handler(calls))
    result = await LinkedInPublisher(_LI_CONFIG).publish_video(
        _9MB_BYTES, caption="Big launch!", title="Launch video"
    )
    return calls, result


@pytest.mark.anyio
async def test_linkedin_video_chunks_match_upload_instructions(monkeypatch):
    calls, _ = await _publish_linkedin_video(monkeypatch)

    assert calls["init_body"] == {
        "initializeUploadRequest": {
            "owner": "urn:li:organization:555",
            "fileSizeBytes": _9MB,
        }
    }

    # Every REST call carried the versioned headers
    for headers in calls["video_headers"]:
        assert headers["linkedin-version"] == LINKEDIN_VERSION == "202508"
        assert headers["x-restli-protocol-version"] == "2.0.0"
        assert headers["authorization"] == "Bearer li-token"

    # Each PUT carried exactly the instructed byte range, in order
    assert [u for u, _ in calls["put_bodies"]] == [
        i["uploadUrl"] for i in _INSTRUCTIONS
    ]
    for (_, body), instruction in zip(calls["put_bodies"], _INSTRUCTIONS):
        assert body == _9MB_BYTES[instruction["firstByte"] : instruction["lastByte"] + 1]
    total = sum(len(body) for _, body in calls["put_bodies"])
    assert total == _9MB


@pytest.mark.anyio
async def test_linkedin_finalize_payload_shape(monkeypatch):
    calls, _ = await _publish_linkedin_video(monkeypatch)

    assert calls["finalize_body"] == {
        "finalizeUploadRequest": {
            "video": _VIDEO_URN,
            "uploadToken": "",
            "uploadedPartIds": ["etag-1", "etag-2", "etag-3"],  # ordered ETags
        }
    }
    # The AVAILABLE poll hit the URL-encoded video URN
    assert calls["poll_path"] == "/rest/videos/urn%3Ali%3Avideo%3AC5F10AQGKQgqeSxAAA"


@pytest.mark.anyio
async def test_linkedin_post_id_from_x_restli_id(monkeypatch):
    calls, result = await _publish_linkedin_video(monkeypatch)

    assert result["status"] == "published"
    assert result["platform_post_id"] == "urn:li:share:7360000000000000001"
    assert result["media_urn"] == _VIDEO_URN

    assert calls["post_body"] == {
        "author": "urn:li:organization:555",
        "commentary": "Big launch!",
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED"},
        "lifecycleState": "PUBLISHED",
        "content": {"media": {"id": _VIDEO_URN, "title": "Launch video"}},
    }


@pytest.mark.anyio
async def test_linkedin_video_processing_failed_raises(monkeypatch):
    calls: dict = {}
    _mock_async_client(
        monkeypatch, _linkedin_video_handler(calls, video_status="PROCESSING_FAILED")
    )

    with pytest.raises(LinkedInPublishError, match="processing failed"):
        await LinkedInPublisher(_LI_CONFIG).publish_video(
            _9MB_BYTES, caption="c", title="t"
        )


@pytest.mark.anyio
async def test_linkedin_text_post_captures_x_restli_id(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/posts"
        calls["post_body"] = json.loads(request.content)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:42"})

    _mock_async_client(monkeypatch, handler)

    result = await LinkedInPublisher(_LI_CONFIG).publish_text(caption="Hello LinkedIn")

    assert result["platform_post_id"] == "urn:li:share:42"
    assert "content" not in calls["post_body"]  # text-only: no media block


@pytest.mark.anyio
async def test_linkedin_image_one_shot_upload(monkeypatch):
    calls: dict = {}
    image_urn = "urn:li:image:C5F10AQabc"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and request.url.path == "/rest/images":
            assert request.url.params.get("action") == "initializeUpload"
            calls["init_body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.example.com/img1",
                        "image": image_urn,
                    }
                },
            )
        if request.method == "PUT" and url == "https://upload.example.com/img1":
            calls["upload_body"] = request.content
            return httpx.Response(201)
        if request.method == "POST" and request.url.path == "/rest/posts":
            calls["post_body"] = json.loads(request.content)
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:77"})
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    result = await LinkedInPublisher(_LI_CONFIG).publish_image(
        b"png-bytes", caption="Look at this"
    )

    assert calls["init_body"] == {
        "initializeUploadRequest": {"owner": "urn:li:organization:555"}
    }
    assert calls["upload_body"] == b"png-bytes"
    assert calls["post_body"]["content"] == {"media": {"id": image_urn}}
    assert result["platform_post_id"] == "urn:li:share:77"
    assert result["media_urn"] == image_urn


@pytest.mark.anyio
async def test_linkedin_missing_credentials_raises(monkeypatch):
    monkeypatch.setattr(settings, "LINKEDIN_ACCESS_TOKEN", "")
    monkeypatch.setattr(settings, "LINKEDIN_ORG_ID", "")

    with pytest.raises(LinkedInPublishError, match="credentials missing"):
        await LinkedInPublisher({}).publish_text(caption="hi")


# ---------------------------------------------------------------------------
# LinkedIn channel publisher (registry seam): image + text routing
# ---------------------------------------------------------------------------

_LI_CHANNEL_CREDS = {"linkedin_access_token": "li-token", "linkedin_org_id": "555"}
_LI_IMAGE_URN = "urn:li:image:C5F10AQdef"


def _li_content():
    return SimpleNamespace(
        generation_metadata={
            "platform_adaptations": {
                "linkedin": {"caption": "Adapted caption", "hashtags": ["#li"]}
            }
        },
        platform_metadata=None,
        caption="Primary caption",
        body_text="Body text",
        hashtags=["#fallback"],
        headline="A headline",
    )


def _li_image_media(with_bytes: bool = True) -> MediaBundle:
    async def loader():
        return b"png-bytes"

    return MediaBundle(
        kind="image",
        public_url="https://api.example.com/api/v1/files/images/i.png",
        bytes_loader=loader if with_bytes else None,
        mime="image/png",
    )


def _li_image_handler(calls: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and request.url.path == "/rest/images":
            assert request.url.params.get("action") == "initializeUpload"
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.example.com/img2",
                        "image": _LI_IMAGE_URN,
                    }
                },
            )
        if request.method == "PUT" and url == "https://upload.example.com/img2":
            calls["upload_body"] = request.content
            return httpx.Response(201)
        if request.method == "POST" and request.url.path == "/rest/posts":
            calls["post_body"] = json.loads(request.content)
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:88"})
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    return handler


@pytest.mark.anyio
async def test_linkedin_channel_publisher_routes_image(monkeypatch):
    calls: dict = {}
    _mock_async_client(monkeypatch, _li_image_handler(calls))

    outcome = await LinkedInChannelPublisher().publish(
        _li_content(),
        SimpleNamespace(channel="linkedin"),
        SimpleNamespace(name="Acme"),
        _LI_CHANNEL_CREDS,
        _li_image_media(),
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "urn:li:share:88"
    assert outcome.extra["media_urn"] == _LI_IMAGE_URN
    assert calls["upload_body"] == b"png-bytes"
    # The adapted caption + hashtags became the commentary.
    assert calls["post_body"]["commentary"].startswith("Adapted caption")
    assert "#li" in calls["post_body"]["commentary"]
    assert calls["post_body"]["content"] == {"media": {"id": _LI_IMAGE_URN}}


@pytest.mark.anyio
async def test_linkedin_channel_publisher_text_only_without_media_bytes(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/posts"
        calls["post_body"] = json.loads(request.content)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:99"})

    _mock_async_client(monkeypatch, handler)

    outcome = await LinkedInChannelPublisher().publish(
        _li_content(),
        SimpleNamespace(channel="linkedin"),
        SimpleNamespace(name="Acme"),
        _LI_CHANNEL_CREDS,
        _li_image_media(with_bytes=False),
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "urn:li:share:99"
    assert outcome.extra["media_urn"] is None
    assert "content" not in calls["post_body"]  # no bytes → text-only post
