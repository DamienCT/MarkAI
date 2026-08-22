"""Tests for the direct in-backend publishing path (registry + dispatch)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.auth.models  # noqa: F401 — registers the User mapper (Approval references it)
import app.models  # noqa: F401 — registers all model mappers
from app.config import settings
from app.models.brand import Brand
from app.models.calendar_item import CalendarItem
from app.models.content import Content
from app.services.publishers import registry
from app.services.publishers.base import ChannelPublisher, PublishOutcome
from app.services.publishers.registry import get_publisher
from app.services.publish_service import publish_direct, resolve_media

BRAND_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_brand() -> Brand:
    return Brand(
        id=BRAND_ID,
        name="Test Brand",
        brand_guidelines={
            "channels": {
                "instagram": {"access_token": "ig-token", "account_id": "ig-123"},
            }
        },
    )


def _make_calendar_item(channel: str, item_type: str, status: str) -> CalendarItem:
    return CalendarItem(
        id=uuid.uuid4(),
        brand_id=BRAND_ID,
        title="Test item",
        item_type=item_type,
        channel=channel,
        status=status,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
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


def _enable_publishing(monkeypatch):
    """Bypass the kill-switch DB read (fake sessions can't serve it)."""
    monkeypatch.setattr(
        "app.services.publish_service.is_publishing_enabled",
        AsyncMock(return_value=True),
    )


# ── Registry mapping ────────────────────────────────────────────────────


def test_registry_resolves_real_publishers_for_all_mapped_combos():
    """Every mapped (channel, media_kind) pair must resolve against the REAL
    publisher modules on disk — no sys.modules stubbing — to an instance
    exposing the ``publish`` seam ``publish_direct`` calls. This is exactly
    where a wrong module/class name in ``_PUBLISHERS`` silently breaks a
    channel (there is no fallback path anymore)."""
    for channel, media_kind in registry._PUBLISHERS:
        publisher = get_publisher(channel, media_kind)
        assert publisher is not None, (
            f"get_publisher({channel!r}, {media_kind!r}) returned None — the "
            "registry entry points at a missing module/class"
        )
        assert isinstance(publisher, ChannelPublisher)
        assert callable(publisher.publish)


def test_registry_maps_supported_channel_media_pairs():
    assert type(get_publisher("instagram", "image")).__name__ == "InstagramPublisher"
    assert type(get_publisher("instagram", "video")).__name__ == "InstagramPublisher"
    assert type(get_publisher("facebook", "image")).__name__ == "FacebookPublisher"
    assert type(get_publisher("facebook", "video")).__name__ == "FacebookPublisher"
    assert type(get_publisher("youtube", "video")).__name__ == "YouTubeChannelPublisher"
    assert type(get_publisher("linkedin", "video")).__name__ == "LinkedInChannelPublisher"


def test_registry_returns_none_for_unsupported_combinations():
    # None now means "unsupported channel/media combination" — there is no
    # fallback; publish_direct records an actionable failure instead.
    assert get_publisher("youtube", "image") is None
    assert get_publisher("no_such_channel", "image") is None
    assert get_publisher("no_such_channel", "video") is None


def test_registry_falls_back_to_none_when_module_missing(monkeypatch):
    monkeypatch.setattr(
        registry,
        "_PUBLISHERS",
        {("instagram", "image"): ("does_not_exist", "NopePublisher")},
    )
    assert registry.get_publisher("instagram", "image") is None


# ── Media resolution ────────────────────────────────────────────────────


def test_resolve_media_picks_video_for_reels(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.test")
    calendar_item = _make_calendar_item("instagram", "reel", "scheduled")
    content = _make_content(
        calendar_item,
        video_url="videos/brand/item/final.mp4",
        generation_metadata={"branded_image": "images/brand/item.png"},
    )

    media = resolve_media(content, calendar_item)

    assert media.kind == "video"
    # Prefix match: the URL gains a signed access token (mt=…&exp=…) once
    # app.utils.media_sign is present.
    assert media.public_url.startswith(
        "https://api.test/api/v1/files/videos/brand/item/final.mp4"
    )
    assert media.bytes_loader is not None
    assert media.mime == "video/mp4"


def test_resolve_media_picks_branded_image_for_posts(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.test")
    calendar_item = _make_calendar_item("instagram", "post", "scheduled")
    # Even with a video present, non-reel/video items publish the image.
    content = _make_content(
        calendar_item,
        video_url="videos/brand/item/final.mp4",
        generation_metadata={"branded_image": "images/brand/item.png"},
    )

    media = resolve_media(content, calendar_item)

    assert media.kind == "image"
    # Meta channels get the JPEG-converted variant (prefix match: a signed
    # access token may precede fmt=jpg in the query string).
    assert media.public_url.startswith(
        "https://api.test/api/v1/files/images/brand/item.png"
    )
    assert "fmt=jpg" in media.public_url
    assert media.bytes_loader is not None


def test_resolve_media_no_jpg_suffix_for_non_meta_channels(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.test")
    calendar_item = _make_calendar_item("linkedin", "post", "scheduled")
    content = _make_content(
        calendar_item,
        generation_metadata={"branded_image": "images/brand/item.png"},
    )

    media = resolve_media(content, calendar_item)

    assert media.kind == "image"
    assert media.public_url.startswith(
        "https://api.test/api/v1/files/images/brand/item.png"
    )
    assert "fmt=jpg" not in media.public_url


# ── publish_direct ──────────────────────────────────────────────────────


class _FakePublisher:
    def __init__(self, outcome: PublishOutcome):
        self.outcome = outcome
        self.calls = []

    async def publish(self, content, calendar_item, brand, creds, media):
        self.calls.append(
            {
                "content": content,
                "calendar_item": calendar_item,
                "brand": brand,
                "creds": creds,
                "media": media,
            }
        )
        return self.outcome


@pytest.mark.anyio
async def test_publish_direct_success_updates_status_and_platform_metadata(monkeypatch):
    _enable_publishing(monkeypatch)
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.test")
    brand = _make_brand()
    calendar_item = _make_calendar_item("instagram", "reel", "publishing")
    content = _make_content(
        calendar_item,
        video_url="videos/brand/item/final.mp4",
        generation_metadata={"branded_image": "images/brand/item.png"},
        platform_metadata={"instagram": {"caption": "Adapted caption"}},
    )
    publisher = _FakePublisher(
        PublishOutcome(platform_post_id="1789", status="published")
    )
    monkeypatch.setattr(
        "app.services.publish_service.get_publisher", lambda ch, kind: publisher
    )
    db = _fake_db()

    outcome = await publish_direct(db, content, calendar_item, brand)

    assert outcome.status == "published"
    assert calendar_item.status == "published"
    assert calendar_item.published_at is not None
    assert content.platform_post_id == "1789"
    channel_meta = content.platform_metadata["instagram"]
    assert channel_meta["post_id"] == "1789"
    assert channel_meta["published_at"]
    # Pre-existing per-channel adaptation data survives the write-back.
    assert channel_meta["caption"] == "Adapted caption"
    db.commit.assert_awaited()

    # The publisher received the brand's channel credentials and the video.
    call = publisher.calls[0]
    assert call["creds"]["meta_access_token"] == "ig-token"
    assert call["creds"]["instagram_account_id"] == "ig-123"
    assert call["media"].kind == "video"


@pytest.mark.anyio
async def test_publish_direct_failure_marks_failed_with_error(monkeypatch):
    _enable_publishing(monkeypatch)
    brand = _make_brand()
    calendar_item = _make_calendar_item("instagram", "post", "publishing")
    content = _make_content(
        calendar_item,
        generation_metadata={"branded_image": "images/brand/item.png"},
    )
    publisher = _FakePublisher(
        PublishOutcome(
            platform_post_id=None, status="failed", error="container EXPIRED"
        )
    )
    monkeypatch.setattr(
        "app.services.publish_service.get_publisher", lambda ch, kind: publisher
    )
    db = _fake_db()

    outcome = await publish_direct(db, content, calendar_item, brand)

    assert outcome.status == "failed"
    assert calendar_item.status == "failed"
    assert calendar_item.published_at is None
    assert content.generation_metadata["publish_error"] == "container EXPIRED"
    # Other generation metadata is preserved.
    assert content.generation_metadata["branded_image"] == "images/brand/item.png"
    db.commit.assert_awaited()


@pytest.mark.anyio
async def test_publish_direct_without_publisher_fails_item(monkeypatch):
    _enable_publishing(monkeypatch)
    brand = _make_brand()
    calendar_item = _make_calendar_item("no_such_channel", "post", "publishing")
    content = _make_content(calendar_item)
    monkeypatch.setattr(
        "app.services.publish_service.get_publisher", lambda ch, kind: None
    )
    db = _fake_db()

    outcome = await publish_direct(db, content, calendar_item, brand)

    assert outcome.status == "failed"
    assert calendar_item.status == "failed"
    # The error names the exact channel/media combination so an operator can act.
    assert (
        "no publisher supports channel 'no_such_channel' with media kind 'image'"
        in content.generation_metadata["publish_error"]
    )


@pytest.mark.anyio
async def test_publish_direct_youtube_image_gets_actionable_error(monkeypatch):
    """youtube+image has no publisher by design — the failure must say WHY
    (YouTube only takes video) instead of a generic no-publisher message."""
    _enable_publishing(monkeypatch)
    brand = _make_brand()
    calendar_item = _make_calendar_item("youtube", "post", "publishing")
    content = _make_content(
        calendar_item,
        generation_metadata={"branded_image": "images/brand/item.png"},
    )
    monkeypatch.setattr(
        "app.services.publish_service.get_publisher", lambda ch, kind: None
    )
    db = _fake_db()

    outcome = await publish_direct(db, content, calendar_item, brand)

    assert outcome.status == "failed"
    assert "YouTube requires video content" in outcome.error
    assert (
        "YouTube requires video content"
        in content.generation_metadata["publish_error"]
    )


# ── Publish checker ─────────────────────────────────────────────────────


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Async-context-manager session that replays canned query results."""

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


@pytest.mark.anyio
async def test_checker_due_query_skips_publishing_items(monkeypatch):
    """The due query selects status='scheduled' only, so items an in-flight
    direct task moved to 'publishing' are not picked up again; stuck
    'publishing' items are swept to failed by a dedicated query."""
    from app.scheduler import publish_checker

    # Results: kill-switch read (absent → enabled), stuck sweep, due query.
    session = _FakeSession([_FakeResult([]), _FakeResult([]), _FakeResult([])])
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)

    await publish_checker.check_due_content()

    assert len(session.executed) == 3
    sweep_params = session.executed[1].compile().params
    due_params = session.executed[2].compile().params
    assert "publishing" in sweep_params.values()
    assert "scheduled" in due_params.values()
    assert "publishing" not in due_params.values()


@pytest.mark.anyio
async def test_checker_direct_path_marks_publishing_and_spawns_task(monkeypatch):
    from app.scheduler import publish_checker

    brand = _make_brand()
    calendar_item = _make_calendar_item("instagram", "reel", "scheduled")
    content = _make_content(
        calendar_item,
        video_url="videos/brand/item/final.mp4",
        generation_metadata={"branded_image": "images/brand/item.png"},
    )
    content.brand = brand

    session = _FakeSession(
        [
            _FakeResult([]),  # kill-switch read at sweep start (absent → enabled)
            _FakeResult([]),  # stuck-'publishing' sweep
            _FakeResult([calendar_item]),  # due items
            _FakeResult([]),  # per-item kill-switch read
            _FakeResult([content]),  # current content for the item
            _FakeResult([calendar_item.id]),  # CAS claim scheduled→publishing
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)

    await publish_checker.check_due_content()

    # The claim is an atomic compare-and-set: scheduled → publishing.
    claim_params = session.executed[5].compile().params
    assert "publishing" in claim_params.values()
    assert "scheduled" in claim_params.values()
    spawn.assert_called_once_with(calendar_item.id, content.id)
    session.commit.assert_awaited()


@pytest.mark.anyio
async def test_checker_spawns_direct_publish_for_every_channel(monkeypatch):
    """Single-path regression: channels that used to fall back to the n8n
    dispatch (x, tiktok, teams, website_blog, …) now go through the exact
    same claim + background direct publish as everything else — the checker
    no longer consults the registry before claiming."""
    from app.scheduler import publish_checker

    brand = _make_brand()
    calendar_item = _make_calendar_item("x", "post", "scheduled")
    content = _make_content(
        calendar_item,
        generation_metadata={"branded_image": "images/brand/item.png"},
    )
    content.brand = brand

    session = _FakeSession(
        [
            _FakeResult([]),  # kill-switch read at sweep start
            _FakeResult([]),  # stuck-'publishing' sweep
            _FakeResult([calendar_item]),  # due items
            _FakeResult([]),  # per-item kill-switch read
            _FakeResult([content]),  # current content for the item
            _FakeResult([calendar_item.id]),  # CAS claim scheduled→publishing
        ]
    )
    monkeypatch.setattr(publish_checker, "async_session_factory", lambda: session)
    spawn = MagicMock()
    monkeypatch.setattr(publish_checker, "_spawn_direct_publish", spawn)

    await publish_checker.check_due_content()

    claim_params = session.executed[5].compile().params
    assert "publishing" in claim_params.values()
    assert "scheduled" in claim_params.values()
    spawn.assert_called_once_with(calendar_item.id, content.id)
