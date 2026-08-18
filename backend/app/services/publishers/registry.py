"""Channel/media-kind → publisher lookup for direct in-backend publishing.

The registry decides which calendar items publish directly from the backend
and which keep going through the n8n webhook: ``get_publisher`` returns a
``ChannelPublisher`` instance for supported (channel, media_kind) pairs and
``None`` for everything else (teams, website_blog, x, tiktok, youtube images,
…), in which case the caller falls back to ``dispatch_to_n8n``.
"""

import logging
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.publishers.base import ChannelPublisher

logger = logging.getLogger(__name__)

# (channel, media_kind) → (module in this package, publisher class name).
# Publisher modules are imported lazily so a single broken/missing publisher
# degrades that channel to the n8n fallback instead of breaking dispatch.
_PUBLISHERS: dict[tuple[str, str], tuple[str, str]] = {
    ("instagram", "image"): ("meta", "InstagramPublisher"),
    ("instagram", "video"): ("meta", "InstagramPublisher"),
    ("facebook", "image"): ("meta", "FacebookPublisher"),
    ("facebook", "video"): ("meta", "FacebookPublisher"),
    ("youtube", "video"): ("youtube", "YouTubeChannelPublisher"),
    ("linkedin", "video"): ("linkedin", "LinkedInChannelPublisher"),
}


def get_publisher(channel: str, media_kind: str) -> "ChannelPublisher | None":
    """Return a publisher instance for (channel, media_kind), or None.

    None means "no direct publisher for this combination" — the caller must
    keep dispatching through n8n (the pre-existing webhook path).
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
            "Publisher %s.%s unavailable (%s) — falling back to n8n dispatch",
            module_name,
            class_name,
            exc,
        )
        return None
    return publisher_cls()
