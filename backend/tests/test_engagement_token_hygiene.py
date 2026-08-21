"""N-01 regression: Meta Graph calls in engagement_service must never put the
access token in the URL, and failed calls must never log the raw token."""

import logging
import types

import httpx
import pytest

from app.services import engagement_service

TOKEN = "EAAB-SECRET-META-TOKEN"


def _content(post_id="17890000000000001"):
    # engagement_service only reads .platform_post_id
    return types.SimpleNamespace(platform_post_id=post_id)


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingClient:
    """Stands in for httpx.AsyncClient; records every GET."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None, headers=None):
        _RecordingClient.calls.append(
            {"url": url, "params": dict(params or {}), "headers": dict(headers or {})}
        )
        return _FakeResponse({"data": []})


class _FailingClient(_RecordingClient):
    """Every GET fails with an old-style token-in-URL error message."""

    async def get(self, url, params=None, headers=None):
        await super().get(url, params=params, headers=headers)
        raise httpx.HTTPStatusError(
            "Client error '401 Unauthorized' for url "
            f"'https://graph.facebook.com/v25.0/x?access_token={TOKEN}'",
            request=None,
            response=None,
        )


def _assert_no_token_in_transport(calls):
    assert calls, "expected at least one Graph API call"
    for call in calls:
        assert TOKEN not in call["url"]
        assert "access_token" not in call["params"]
        assert call["headers"].get("Authorization") == f"Bearer {TOKEN}"


@pytest.mark.anyio
async def test_instagram_pull_sends_bearer_header(monkeypatch):
    _RecordingClient.calls = []
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)
    await engagement_service.pull_instagram_insights(_content(), TOKEN)
    _assert_no_token_in_transport(_RecordingClient.calls)


@pytest.mark.anyio
async def test_facebook_pull_sends_bearer_header(monkeypatch):
    _RecordingClient.calls = []
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)
    await engagement_service.pull_facebook_insights(_content(), TOKEN)
    _assert_no_token_in_transport(_RecordingClient.calls)


@pytest.mark.anyio
async def test_failed_calls_log_redacted_token(monkeypatch, caplog):
    _RecordingClient.calls = []
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _FailingClient)
    with caplog.at_level(logging.WARNING, logger="app.services.engagement_service"):
        result = await engagement_service.pull_instagram_insights(_content(), TOKEN)
    # Degrades to zeros instead of raising…
    assert result["likes"] == 0
    # …and the token never reaches the log, even when embedded in the message.
    assert caplog.text, "expected warnings for the failed calls"
    assert TOKEN not in caplog.text
    assert "access_token=***" in caplog.text
