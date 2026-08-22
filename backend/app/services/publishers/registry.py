"""Channel/media-kind → publisher lookup for direct in-backend publishing.

Every channel publishes natively from the backend: ``get_publisher`` returns
a ``ChannelPublisher`` instance for supported (channel, media_kind) pairs
and ``None`` when the combination is unsupported (e.g. youtube or tiktok
images). There is no fallback dispatch path — the caller must fail the item
with an actionable error naming the unsupported combination.
"""

import logging
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.publishers.base import ChannelPublisher

logger = logging.getLogger(__name__)

# (channel, media_kind) → (module in this package, publisher class name).
# Publisher modules are imported lazily so a single broken/missing publisher
# degrades only its own channel (those items fail with an actionable error)
# instead of breaking dispatch for every channel.
_PUBLISHERS: dict[tuple[str, str], tuple[str, str]] = {
    ("instagram", "image"): ("meta", "InstagramPublisher"),
    ("instagram", "video"): ("meta", "InstagramPublisher"),
    ("facebook", "image"): ("meta", "FacebookPublisher"),
    ("facebook", "video"): ("meta", "FacebookPublisher"),
    ("youtube", "video"): ("youtube", "YouTubeChannelPublisher"),
    ("linkedin", "image"): ("linkedin", "LinkedInChannelPublisher"),
    ("linkedin", "video"): ("linkedin", "LinkedInChannelPublisher"),
    ("x", "image"): ("x", "XPublisher"),
    ("x", "video"): ("x", "XPublisher"),
    # Image maps to the publisher too so callers get its precise
    # "TikTok requires video content" error, not the generic no-entry one.
    ("tiktok", "image"): ("tiktok", "TikTokPublisher"),
    ("tiktok", "video"): ("tiktok", "TikTokPublisher"),
    ("teams", "image"): ("teams", "TeamsPublisher"),
    ("teams", "video"): ("teams", "TeamsPublisher"),
    ("website_blog", "image"): ("blog", "BlogPublisher"),
    ("website_blog", "video"): ("blog", "BlogPublisher"),
}


def get_publisher(channel: str, media_kind: str) -> "ChannelPublisher | None":
    """Return a publisher instance for (channel, media_kind), or None.

    None means "unsupported channel/media combination" — no fallback exists,
    so the caller records a failed outcome with an actionable error instead
    of dispatching anywhere.
    """
    entry = _PUBLISHERS.get((channel, media_kind))
    if entry is None:
        return None
    module_name, class_name = entry
    try:
        module = import_module(f"app.services.publishers.{module_name}")
        publisher_cls = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        logger.warning(
            "Publisher %s.%s unavailable (%s) — items for this channel/media "
            "will fail until the module is fixed",
            module_name,
            class_name,
            exc,
        )
        return None
    return publisher_cls()
