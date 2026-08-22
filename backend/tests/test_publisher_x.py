"""Tests for the direct X (Twitter) publisher — in-repo OAuth 1.0a + tweet flows."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qsl

import httpx
import pytest

from app.services.publishers.base import MediaBundle
from app.services.publishers.x import (
    MEDIA_UPLOAD_URL,
    TWEETS_URL,
    XPublisher,
    oauth1_auth_header,
    oauth1_signature,
    truncate_tweet,
)

# Keep a reference to the real client class — the factory below closes over it
# after monkeypatch swaps httpx.AsyncClient for the factory itself.
_RealAsyncClient = httpx.AsyncClient


def _mock_async_client(monkeypatch, handler):
    """Route every httpx.AsyncClient request through a MockTransport handler."""

    def factory(*args, **kwargs):
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(httpx, "AsyncClient", factory)


X_CREDS = {
    "consumer_key": "ck-value",
    "consumer_secret": "consumer-secret-value",
    "access_token": "at-value",
    "access_token_secret": "token-secret-value",
    "handle": "@acme",
}


def _content(caption: str = "Adapted caption"):
    return SimpleNamespace(
        generation_metadata={
            "platform_adaptations": {
                "x": {"caption": caption, "hashtags": ["#launch"]}
            }
        },
        platform_metadata=None,
        caption="Primary caption",
        body_text="Body text",
        hashtags=["#fallback"],
        headline="A headline",
    )


_CALENDAR_ITEM = SimpleNamespace(channel="x")
_BRAND = SimpleNamespace(name="Acme")

_IMAGE_BYTES = b"\x89PNG-fake-image-bytes"
_VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"fake-mp4" * 32


def _media(kind: str, data: bytes | None):
    async def loader():
        return data

    return MediaBundle(
        kind=kind,
        public_url="https://api.example.com/api/v1/files/images/i.png",
        bytes_loader=loader if data is not None else None,
        mime="image/png" if kind == "image" else "video/mp4",
    )


# ---------------------------------------------------------------------------
# OAuth 1.0a signing — documented test vector
# ---------------------------------------------------------------------------

# The worked example from X's "Creating a signature" documentation
# (docs.x.com → OAuth 1.0a): POST statuses/update.json with fixed nonce and
# timestamp must produce exactly this signature.
_VECTOR_URL = "https://api.x.com/1.1/statuses/update.json"
_VECTOR_CONSUMER_KEY = "xvz1evFS4wEEPTGEFPHBog"
_VECTOR_CONSUMER_SECRET = "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw"
_VECTOR_TOKEN = "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb"
_VECTOR_TOKEN_SECRET = "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"
_VECTOR_NONCE = "kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg"
_VECTOR_TIMESTAMP = 1318622958
_VECTOR_REQUEST_PARAMS = {
    "include_entities": "true",
    "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
}
_VECTOR_SIGNATURE = "Ls93hJiZbQ3akF3HF3x1Bz8/zU4="


def test_oauth1_signature_matches_documented_example():
    params = {
        **_VECTOR_REQUEST_PARAMS,
        "oauth_consumer_key": _VECTOR_CONSUMER_KEY,
        "oauth_nonce": _VECTOR_NONCE,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(_VECTOR_TIMESTAMP),
        "oauth_token": _VECTOR_TOKEN,
        "oauth_version": "1.0",
    }
    signature = oauth1_signature(
        "POST", _VECTOR_URL, params, _VECTOR_CONSUMER_SECRET, _VECTOR_TOKEN_SECRET
    )
    assert signature == _VECTOR_SIGNATURE


def test_oauth1_auth_header_carries_percent_encoded_signature():
    header = oauth1_auth_header(
        "POST",
        _VECTOR_URL,
        consumer_key=_VECTOR_CONSUMER_KEY,
        consumer_secret=_VECTOR_CONSUMER_SECRET,
        access_token=_VECTOR_TOKEN,
        access_token_secret=_VECTOR_TOKEN_SECRET,
        request_params=_VECTOR_REQUEST_PARAMS,
        nonce=_VECTOR_NONCE,
        timestamp=_VECTOR_TIMESTAMP,
    )
    assert header.startswith("OAuth ")
    assert 'oauth_signature="Ls93hJiZbQ3akF3HF3x1Bz8%2FzU4%3D"' in header
    assert 'oauth_signature_method="HMAC-SHA1"' in header
    assert f'oauth_consumer_key="{_VECTOR_CONSUMER_KEY}"' in header
    # Secrets never travel in the header — only the derived signature does.
    assert _VECTOR_CONSUMER_SECRET not in header
    assert _VECTOR_TOKEN_SECRET not in header


# ---------------------------------------------------------------------------
# Caption truncation
# ---------------------------------------------------------------------------


def test_truncate_tweet_short_text_unchanged():
    assert truncate_tweet("Hello world") == "Hello world"
    assert truncate_tweet("x" * 280) == "x" * 280


def test_truncate_tweet_cuts_on_word_boundary_with_ellipsis():
    text = ("word " * 100).strip()  # 499 chars
    out = truncate_tweet(text)
    assert len(out) <= 280
    assert out.endswith("…")
    body = out[:-1]
    # The kept text is a clean prefix ending at a word boundary — no split word.
    assert text.startswith(body)
    assert text[len(body)] == " "


def test_truncate_tweet_never_cuts_mid_url():
    url = "https://example.com/a-very-long-path-segment"
    text = "x" * 270 + " " + url
    out = truncate_tweet(text)
    # The URL straddling the cut is dropped whole, never truncated mid-way.
    assert out == "x" * 270 + "…"
    assert "https" not in out


# ---------------------------------------------------------------------------
# Tweet flows (mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_x_text_only_tweet_when_no_media_bytes(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == TWEETS_URL
        calls["json"] = json.loads(request.content)
        calls["auth"] = request.headers["Authorization"]
        return httpx.Response(201, json={"data": {"id": "1801", "text": "t"}})

    _mock_async_client(monkeypatch, handler)

    outcome = await XPublisher().publish(
        _content(), _CALENDAR_ITEM, _BRAND, X_CREDS, _media("image", None)
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "1801"
    assert "media" not in calls["json"]  # no bytes → text-only tweet
    assert calls["json"]["text"].startswith("Adapted caption")
    assert "#launch" in calls["json"]["text"]

    auth = calls["auth"]
    assert auth.startswith("OAuth ")
    assert 'oauth_consumer_key="ck-value"' in auth
    assert 'oauth_token="at-value"' in auth
    assert "oauth_signature=" in auth
    assert "consumer-secret-value" not in auth
    assert "token-secret-value" not in auth


@pytest.mark.anyio
async def test_x_image_tweet_uploads_then_attaches_media(monkeypatch):
    calls: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(MEDIA_UPLOAD_URL):
            assert request.method == "POST"
            calls["upload_auth"] = request.headers["Authorization"]
            calls["upload_body"] = request.content
            return httpx.Response(
                200, json={"media_id": 710, "media_id_string": "710"}
            )
        if url == TWEETS_URL:
            calls["tweet_json"] = json.loads(request.content)
            return httpx.Response(201, json={"data": {"id": "1901"}})
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await XPublisher().publish(
        _content(), _CALENDAR_ITEM, _BRAND, X_CREDS, _media("image", _IMAGE_BYTES)
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "1901"
    assert outcome.extra["media_ids"] == ["710"]
    # The raw bytes went up in the multipart body, signed with OAuth 1.0a.
    assert _IMAGE_BYTES in calls["upload_body"]
    assert calls["upload_auth"].startswith("OAuth ")
    assert calls["tweet_json"]["media"] == {"media_ids": ["710"]}


@pytest.mark.anyio
async def test_x_video_chunked_upload_init_append_finalize_status(monkeypatch):
    calls: dict = {"appends": []}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = dict(request.url.params)
        if url.startswith(MEDIA_UPLOAD_URL):
            if params.get("command") == "APPEND":
                assert params["media_id"] == "77"
                calls["appends"].append((params["segment_index"], request.content))
                return httpx.Response(204)
            if request.method == "GET" and params.get("command") == "STATUS":
                calls["status_polled"] = True
                return httpx.Response(
                    200, json={"processing_info": {"state": "succeeded"}}
                )
            form = dict(parse_qsl(request.content.decode()))
            if form.get("command") == "INIT":
                calls["init_form"] = form
                return httpx.Response(202, json={"media_id_string": "77"})
            if form.get("command") == "FINALIZE":
                calls["finalize_form"] = form
                return httpx.Response(
                    200,
                    json={
                        "media_id_string": "77",
                        "processing_info": {"state": "pending", "check_after_secs": 0},
                    },
                )
        if url == TWEETS_URL:
            calls["tweet_json"] = json.loads(request.content)
            return httpx.Response(201, json={"data": {"id": "2001"}})
        raise AssertionError(f"Unexpected request: {request.method} {url}")

    _mock_async_client(monkeypatch, handler)

    outcome = await XPublisher().publish(
        _content(), _CALENDAR_ITEM, _BRAND, X_CREDS, _media("video", _VIDEO_BYTES)
    )

    assert outcome.status == "published"
    assert outcome.platform_post_id == "2001"
    assert calls["init_form"] == {
        "command": "INIT",
        "total_bytes": str(len(_VIDEO_BYTES)),
        "media_type": "video/mp4",
        "media_category": "tweet_video",
    }
    # Single segment (video is far under the 4MB chunk size), bytes intact.
    assert [i for i, _ in calls["appends"]] == ["0"]
    assert _VIDEO_BYTES in calls["appends"][0][1]
    assert calls["finalize_form"] == {"command": "FINALIZE", "media_id": "77"}
    assert calls["status_polled"] is True  # pending FINALIZE → STATUS poll
    assert calls["tweet_json"]["media"] == {"media_ids": ["77"]}


@pytest.mark.anyio
async def test_x_missing_credentials_fails_actionably():
    outcome = await XPublisher().publish(
        _content(), _CALENDAR_ITEM, _BRAND, {}, _media("image", None)
    )

    assert outcome.status == "failed"
    assert "not configured" in outcome.error
    assert "consumer_key" in outcome.error
    assert "Brand > Channels > X" in outcome.error


@pytest.mark.anyio
async def test_x_platform_error_mapped_actionably(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "title": "Forbidden",
                "detail": "Your client app is not configured with the "
                "appropriate oauth1 app permissions for this endpoint.",
                "status": 403,
            },
        )

    _mock_async_client(monkeypatch, handler)

    outcome = await XPublisher().publish(
        _content(), _CALENDAR_ITEM, _BRAND, X_CREDS, _media("image", None)
    )

    assert outcome.status == "failed"
    assert "X tweet creation failed" in outcome.error
    assert "oauth1 app permissions" in outcome.error
    assert "Read+Write" in outcome.error  # 401/403 adds the credentials hint
    # Credentials never leak into the error.
    assert "consumer-secret-value" not in outcome.error
    assert "token-secret-value" not in outcome.error
