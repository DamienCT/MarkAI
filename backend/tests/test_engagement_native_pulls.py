"""Native engagement pulls for X and YouTube (critic gap).

- pull_x_public_metrics: GET /2/tweets?ids=…&tweet.fields=public_metrics
  signed with the SAME OAuth 1.0a helper the X publisher uses; secrets
  never ride in the URL or query params
- pull_youtube_statistics: videos.list part=statistics; the API key rides
  in the X-Goog-Api-Key header, never the URL (N-01)
- the puller wires both in: configured creds → metrics row in the shared
  shape; unconfigured creds → the skip-with-log path, never an error;
  tiktok/teams/website_blog log an explicit unsupported reason
"""

import logging
import types
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.auth.models  # noqa: F401 — registers the User mapper
import app.models  # noqa: F401 — registers all model mappers
from app.scheduler import engagement_puller
from app.services import engagement_service

BRAND_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")

X_CREDS = {
    "consumer_key": "x-consumer-key",
    "consumer_secret": "x-consumer-SECRET",
    "access_token": "x-access-token",
    "access_token_secret": "x-token-SECRET",
}


def _content(post_id="1234567890"):
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
    payload: dict = {}

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
        return _FakeResponse(_RecordingClient.payload)


# ── X: tweet public_metrics via OAuth 1.0a ──────────────────────────────


@pytest.mark.anyio
async def test_x_pull_maps_public_metrics(monkeypatch):
    _RecordingClient.calls = []
    _RecordingClient.payload = {
        "data": [
            {
                "id": "1234567890",
                "public_metrics": {
                    "like_count": 5,
                    "reply_count": 2,
                    "retweet_count": 3,
                    "quote_count": 1,
                    "impression_count": 100,
                    "bookmark_count": 4,
                },
            }
        ]
    }
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)

    result = await engagement_service.pull_x_public_metrics(_content(), X_CREDS)

    assert result == {
        "impressions": 100,
        "likes": 5,
        "comments": 2,
        "shares": 4,  # retweets + quote tweets
        "saves": 4,
    }


@pytest.mark.anyio
async def test_x_pull_is_oauth1_signed_and_leaks_no_secrets(monkeypatch):
    _RecordingClient.calls = []
    _RecordingClient.payload = {"data": []}
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)

    await engagement_service.pull_x_public_metrics(_content("42"), X_CREDS)

    (call,) = _RecordingClient.calls
    assert call["url"] == "https://api.x.com/2/tweets"
    assert call["params"] == {"ids": "42", "tweet.fields": "public_metrics"}
    auth = call["headers"]["Authorization"]
    # Same OAuth 1.0a shape the X publisher emits (shared helper).
    assert auth.startswith("OAuth ")
    assert 'oauth_consumer_key="x-consumer-key"' in auth
    assert 'oauth_token="x-access-token"' in auth
    assert "oauth_signature=" in auth
    # The two SECRETS are HMAC key material — never transmitted anywhere.
    for secret in ("x-consumer-SECRET", "x-token-SECRET"):
        assert secret not in auth
        assert secret not in call["url"]
        assert secret not in str(call["params"])


@pytest.mark.anyio
async def test_x_pull_without_post_id_returns_zeros(monkeypatch):
    _RecordingClient.calls = []
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)

    result = await engagement_service.pull_x_public_metrics(
        _content(post_id=None), X_CREDS
    )

    assert result["likes"] == 0
    assert _RecordingClient.calls == []  # no HTTP call without a tweet id


# ── YouTube: videos.list statistics via API key ─────────────────────────


@pytest.mark.anyio
async def test_youtube_pull_maps_string_counts(monkeypatch):
    _RecordingClient.calls = []
    _RecordingClient.payload = {
        "items": [
            {
                "statistics": {
                    "viewCount": "1000",
                    "likeCount": "50",
                    "commentCount": "7",
                    "favoriteCount": "0",
                }
            }
        ]
    }
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)

    result = await engagement_service.pull_youtube_statistics(
        _content("vid-1"), "yt-api-key"
    )

    assert result == {
        "impressions": 1000,  # views double as the impression analogue
        "likes": 50,
        "comments": 7,
        "video_views": 1000,
    }


@pytest.mark.anyio
async def test_youtube_key_rides_in_header_not_url(monkeypatch):
    _RecordingClient.calls = []
    _RecordingClient.payload = {"items": []}
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)

    await engagement_service.pull_youtube_statistics(_content("vid-1"), "yt-KEY")

    (call,) = _RecordingClient.calls
    assert call["url"] == "https://www.googleapis.com/youtube/v3/videos"
    assert call["params"] == {"part": "statistics", "id": "vid-1"}
    assert "yt-KEY" not in call["url"]
    assert "yt-KEY" not in str(call["params"])
    assert call["headers"]["X-Goog-Api-Key"] == "yt-KEY"


@pytest.mark.anyio
async def test_youtube_pull_empty_items_returns_zeros(monkeypatch):
    _RecordingClient.calls = []
    _RecordingClient.payload = {"items": []}
    monkeypatch.setattr(engagement_service.httpx, "AsyncClient", _RecordingClient)

    result = await engagement_service.pull_youtube_statistics(
        _content("gone"), "yt-api-key"
    )

    assert result["video_views"] == 0
    assert result["likes"] == 0


# ── Puller wiring ───────────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows=None, scalar=None):
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        if self._scalar is not None:
            return self._scalar
        return self._rows[0] if self._rows else None


class _Session:
    def __init__(self, results):
        self._results = list(results)
        self.commit = AsyncMock()
        self.add = MagicMock()

    async def execute(self, stmt, params=None):
        return self._results.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _puller_fixture(channel: str, channel_cfg: dict):
    brand = types.SimpleNamespace(
        id=BRAND_ID,
        brand_guidelines={"channels": {channel: channel_cfg}} if channel_cfg else {},
    )
    cal_item = types.SimpleNamespace(id=uuid.uuid4(), brand_id=BRAND_ID, channel=channel)
    content = types.SimpleNamespace(
        id=uuid.uuid4(), platform_post_id="post-1", brand=brand
    )
    session = _Session([_Rows([cal_item]), _Rows(scalar=content)])
    return brand, cal_item, content, session


@pytest.mark.anyio
async def test_puller_x_configured_writes_metrics_row(monkeypatch):
    _brand, cal_item, content, session = _puller_fixture("x", X_CREDS)
    monkeypatch.setattr(engagement_puller, "async_session_factory", lambda: session)
    pull = AsyncMock(
        return_value={
            "impressions": 100, "likes": 5, "comments": 2, "shares": 4, "saves": 4,
        }
    )
    monkeypatch.setattr(engagement_puller, "pull_x_public_metrics", pull)

    await engagement_puller.pull_all_engagement()

    pull.assert_awaited_once()
    assert pull.await_args.args[0] is content
    assert pull.await_args.args[1]["consumer_key"] == "x-consumer-key"
    em = session.add.call_args.args[0]
    assert em.channel == "x"
    assert em.brand_id == BRAND_ID
    assert em.likes == 5
    assert em.shares == 4
    assert em.impressions == 100
    # Shared rate computation: (5+2+4+4)/100.
    assert em.engagement_rate == pytest.approx(0.15)
    session.commit.assert_awaited()


@pytest.mark.anyio
async def test_puller_x_unconfigured_skips_with_log(monkeypatch, caplog):
    _brand, _cal_item, _content, session = _puller_fixture(
        "x", {"consumer_key": "only-this"}
    )
    monkeypatch.setattr(engagement_puller, "async_session_factory", lambda: session)
    pull = AsyncMock()
    monkeypatch.setattr(engagement_puller, "pull_x_public_metrics", pull)

    with caplog.at_level(logging.INFO, logger="app.scheduler.engagement_puller"):
        await engagement_puller.pull_all_engagement()

    pull.assert_not_awaited()
    session.add.assert_not_called()
    assert "X credentials not configured" in caplog.text


@pytest.mark.anyio
async def test_puller_youtube_uses_brand_api_key(monkeypatch):
    _brand, _cal_item, content, session = _puller_fixture(
        "youtube", {"api_key": "brand-yt-key"}
    )
    monkeypatch.setattr(engagement_puller, "async_session_factory", lambda: session)
    pull = AsyncMock(
        return_value={
            "impressions": 1000, "likes": 50, "comments": 7, "video_views": 1000,
        }
    )
    monkeypatch.setattr(engagement_puller, "pull_youtube_statistics", pull)

    await engagement_puller.pull_all_engagement()

    pull.assert_awaited_once_with(content, "brand-yt-key")
    em = session.add.call_args.args[0]
    assert em.channel == "youtube"
    assert em.video_views == 1000
    assert em.likes == 50


@pytest.mark.anyio
async def test_puller_youtube_falls_back_to_settings_key(monkeypatch):
    _brand, _cal_item, content, session = _puller_fixture("youtube", {})
    monkeypatch.setattr(engagement_puller, "async_session_factory", lambda: session)
    # settings has no YOUTUBE_API_KEY field (yet) — the puller reads it via
    # getattr, so a stand-in settings object exercises the fallback.
    monkeypatch.setattr(
        engagement_puller,
        "settings",
        types.SimpleNamespace(YOUTUBE_API_KEY="global-yt-key"),
    )
    pull = AsyncMock(
        return_value={"impressions": 0, "likes": 0, "comments": 0, "video_views": 0}
    )
    monkeypatch.setattr(engagement_puller, "pull_youtube_statistics", pull)

    await engagement_puller.pull_all_engagement()

    pull.assert_awaited_once_with(content, "global-yt-key")


@pytest.mark.anyio
async def test_puller_youtube_without_any_key_skips_with_log(monkeypatch, caplog):
    _brand, _cal_item, _content, session = _puller_fixture("youtube", {})
    monkeypatch.setattr(engagement_puller, "async_session_factory", lambda: session)
    pull = AsyncMock()
    monkeypatch.setattr(engagement_puller, "pull_youtube_statistics", pull)

    with caplog.at_level(logging.INFO, logger="app.scheduler.engagement_puller"):
        await engagement_puller.pull_all_engagement()

    pull.assert_not_awaited()
    session.add.assert_not_called()
    assert "no YouTube Data API key" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("channel", "reason_snippet"),
    [
        ("tiktok", "Display API scopes"),
        ("teams", "write-only"),
        ("website_blog", "no metrics API"),
    ],
)
async def test_puller_unsupported_channels_log_reason(
    monkeypatch, caplog, channel, reason_snippet
):
    _brand, _cal_item, _content, session = _puller_fixture(channel, {})
    monkeypatch.setattr(engagement_puller, "async_session_factory", lambda: session)

    with caplog.at_level(logging.INFO, logger="app.scheduler.engagement_puller"):
        await engagement_puller.pull_all_engagement()

    session.add.assert_not_called()
    assert "unsupported" in caplog.text
    assert reason_snippet in caplog.text
