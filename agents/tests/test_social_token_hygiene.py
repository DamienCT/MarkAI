"""N-01 regression: Meta Graph tools must send the access token via the
Authorization header, never as a URL query param (query strings end up in
httpx log lines and str(HTTPStatusError))."""

import asyncio

from shared.config import settings
from shared.tools import social

TOKEN = "EAAB-SECRET-META-TOKEN"


class _FakeResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": []}


class _FakeClient:
    is_closed = False

    def __init__(self):
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return _FakeResponse()


def _run_all_meta_calls(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(social, "_http_client", fake)
    monkeypatch.setattr(social, "_RATE_LIMIT_DELAY", 0)
    monkeypatch.setattr(settings, "META_ACCESS_TOKEN", TOKEN)

    asyncio.run(social.ig_get_profile("ig-user-1"))
    asyncio.run(social.ig_get_recent_posts("ig-user-1", limit=5))
    asyncio.run(social.ig_get_post_insights("media-1"))
    asyncio.run(social.fb_get_page("page-1"))
    asyncio.run(social.fb_get_recent_posts("page-1", limit=5))
    return fake.calls


def test_meta_calls_never_put_token_in_url(monkeypatch):
    calls = _run_all_meta_calls(monkeypatch)
    assert len(calls) == 5
    for call in calls:
        assert TOKEN not in call["url"]
        params = call.get("params") or {}
        assert "access_token" not in params
        assert TOKEN not in str(params)


def test_meta_calls_send_bearer_header(monkeypatch):
    calls = _run_all_meta_calls(monkeypatch)
    for call in calls:
        headers = call.get("headers") or {}
        assert headers.get("Authorization") == f"Bearer {TOKEN}"
