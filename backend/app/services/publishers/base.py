"""Shared building blocks for in-backend channel publishers.

Publishers post content directly to social platforms from the backend
(replacing the n8n webhook hop for supported channels/media). Each channel
gets a ``ChannelPublisher`` subclass; the dispatcher hands it the content
row, calendar item, brand, resolved credentials and a ``MediaBundle``
describing the asset to publish.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """A publishing step failed with a human-readable detail message."""

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


@dataclass
class PublishOutcome:
    """Result of a publish attempt, mirrored into calendar item / content."""

    platform_post_id: str | None
    status: Literal["published", "failed"]
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaBundle:
    """The media asset a publisher should post.

    ``public_url`` is the externally reachable file-proxy URL (used by
    platforms that pull media themselves, e.g. Instagram). ``bytes_loader``
    loads the raw bytes from MinIO (used by platforms we push bytes to,
    e.g. Facebook's rupload endpoint) — publishers must prefer it over
    re-fetching the public URL.
    """

    kind: Literal["image", "video"]
    public_url: str | None = None
    bytes_loader: Callable[[], Awaitable[bytes]] | None = None
    mime: str = "application/octet-stream"
    size_bytes: int | None = None

    async def get_bytes(self) -> bytes:
        """Load the raw media bytes and backfill ``size_bytes``."""
        if self.bytes_loader is None:
            raise PublishError("No media bytes available for this asset")
        data = await self.bytes_loader()
        self.size_bytes = len(data)
        return data


def resolve_caption_and_hashtags(content: Any, channel: str) -> tuple[str, list[str]]:
    """Resolve the channel-specific caption and hashtags for a content row.

    Mirrors the resolution in ``publish_service.dispatch_to_n8n`` (and is the
    shared helper both paths should use): per-channel adaptations from
    ``generation_metadata.platform_adaptations`` win, then legacy
    ``platform_metadata``, then the primary caption / body_text.
    """
    gen_adaptations = (content.generation_metadata or {}).get("platform_adaptations") or {}
    platform_meta = content.platform_metadata or {}
    channel_data = gen_adaptations.get(channel) or platform_meta.get(channel) or {}
    if not isinstance(channel_data, dict):
        channel_data = {}
    caption = channel_data.get("caption") or content.caption or content.body_text or ""
    hashtags = channel_data.get("hashtags")
    if not isinstance(hashtags, list) or not hashtags:
        hashtags = content.hashtags or []
    return caption, hashtags


def resolve_title(content: Any, caption: str = "", default: str = "Video") -> str:
    """Short human-readable title for platforms that require one.

    Prefers ``content.headline``, then a pipeline-provided hook from
    ``generation_metadata``, then the first caption line, then ``default``.
    """
    title = (getattr(content, "headline", None) or "").strip()
    if not title:
        title = str((content.generation_metadata or {}).get("hook") or "").strip()
    if not title:
        lines = (caption or "").strip().splitlines()
        title = lines[0].strip() if lines else ""
    return title or default


def format_caption(caption: str, hashtags: list[str] | None) -> str:
    """Append hashtags (as ``#tag``) to a caption, skipping ones already in it."""
    caption = (caption or "").strip()
    tags = [t if t.startswith("#") else f"#{t}" for t in (hashtags or []) if t]
    missing = [t for t in tags if t.lower() not in caption.lower()]
    if missing:
        return (caption + "\n\n" + " ".join(missing)).strip()
    return caption


async def poll_until(
    fn: Callable[[], Awaitable[Any]],
    interval_s: float = 10,
    max_wait_s: float = 300,
    description: str = "operation",
) -> Any:
    """Await ``fn`` until it returns a non-None result.

    ``fn`` returns None to keep polling; any other value is returned to the
    caller. Raises PublishError when ``max_wait_s`` elapses. The first call
    happens immediately (no initial sleep).
    """
    deadline = time.monotonic() + max_wait_s
    while True:
        result = await fn()
        if result is not None:
            return result
        if time.monotonic() >= deadline:
            raise PublishError(
                f"Timed out after {int(max_wait_s)}s waiting for {description}"
            )
        await asyncio.sleep(interval_s)


class ChannelPublisher(ABC):
    """Base class for direct-to-platform publishers.

    Subclasses implement ``_publish`` and raise PublishError on failure;
    ``publish`` maps errors to a failed PublishOutcome so callers get a
    uniform result either way.
    """

    channel: str = ""

    async def publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        try:
            return await self._publish(content, calendar_item, brand, creds, media)
        except PublishError as exc:
            logger.error("%s publish failed: %s", self.channel or type(self).__name__, exc.detail)
            return PublishOutcome(platform_post_id=None, status="failed", error=exc.detail)
        except httpx.HTTPError as exc:
            detail = f"HTTP error talking to {self.channel or 'platform'}: {exc}"
            logger.error("%s publish failed: %s", self.channel or type(self).__name__, detail)
            return PublishOutcome(platform_post_id=None, status="failed", error=detail)

    @abstractmethod
    async def _publish(
        self,
        content: Any,
        calendar_item: Any,
        brand: Any,
        creds: dict[str, Any],
        media: MediaBundle,
    ) -> PublishOutcome:
        """Perform the platform-specific publish flow. Raise PublishError to fail."""
        ...

    def _http(self) -> httpx.AsyncClient:
        """Shared HTTP client for platform API calls (long timeout for uploads)."""
        return httpx.AsyncClient(timeout=120)
