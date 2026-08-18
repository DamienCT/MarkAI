import json
import logging
from typing import Any

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext
from nats.js.api import RetentionPolicy, StreamConfig

from app.config import settings

logger = logging.getLogger(__name__)

_nc: NATSClient | None = None
_js: JetStreamContext | None = None

# Single unified stream matching the agents worker expectation
STREAMS = {
    "WORKFLOWS": {
        "subjects": [
            "research.>",
            "strategy.>",
            "content.>",
            "evaluation.>",
            "product.>",
            "planning.>",
            "adaptation.>",
            "publish.>",
            "engagement.>",
            "brand.>",
        ]
    },
    # Dedicated stream for video render jobs: long-running work with its own
    # retention/ack characteristics, kept separate from WORKFLOWS so its
    # config can evolve without touching the running workflow consumers.
    "VIDEO": {
        "subjects": ["video.>"],
        "retention": RetentionPolicy.LIMITS,
        "max_age": 7 * 24 * 3600,  # seconds — renders older than a week are dead
    },
}


async def _ensure_stream(js: JetStreamContext, name: str, config: dict) -> None:
    """Create the stream, or converge an existing stream's subjects.

    add_stream fails when the stream already exists with a different config;
    previously that error was swallowed, so subject additions never applied to
    running deployments. On conflict we union-merge subjects via update_stream.
    """
    subjects = config["subjects"]
    stream_config = StreamConfig(
        name=name,
        subjects=subjects,
        retention=config.get("retention", RetentionPolicy.LIMITS),
        max_age=config.get("max_age"),
    )
    try:
        await js.add_stream(stream_config)
        return
    except Exception:
        pass

    try:
        info = await js.stream_info(name)
        existing = list(info.config.subjects or [])
        merged = sorted(set(existing) | set(subjects))
        if set(merged) != set(existing):
            info.config.subjects = merged
            await js.update_stream(info.config)
            logger.info("Stream %s subjects updated to %s", name, merged)
    except Exception as exc:
        logger.error("Stream %s setup failed: %s", name, exc)


async def connect() -> NATSClient:
    """Connect to NATS and set up JetStream streams."""
    global _nc, _js
    connect_opts: dict = {"servers": settings.NATS_URL, "connect_timeout": 5}
    if settings.NATS_AUTH_TOKEN:
        connect_opts["token"] = settings.NATS_AUTH_TOKEN
    _nc = await nats.connect(**connect_opts)
    _js = _nc.jetstream()

    for stream_name, stream_config in STREAMS.items():
        await _ensure_stream(_js, stream_name, stream_config)

    logger.info("Connected to NATS at %s", settings.NATS_URL)
    return _nc


async def disconnect() -> None:
    """Gracefully close the NATS connection."""
    global _nc, _js
    if _nc is not None:
        await _nc.drain()
        _nc = None
        _js = None


def get_jetstream() -> JetStreamContext:
    """Return the JetStream context. Raises if not connected."""
    if _js is None:
        raise RuntimeError("NATS not connected. Call connect() first.")
    return _js


async def publish(subject: str, data: dict[str, Any]) -> None:
    """Publish a JSON message to a NATS JetStream subject."""
    js = get_jetstream()
    payload = json.dumps(data, default=str).encode()
    ack = await js.publish(subject, payload)
    logger.debug("Published to %s, stream=%s, seq=%d", subject, ack.stream, ack.seq)


async def subscribe(
    subject: str,
    durable: str,
):
    """
    Create a pull subscription on a JetStream subject.
    Returns a subscription that can be used to fetch messages.
    """
    js = get_jetstream()
    sub = await js.pull_subscribe(subject, durable=durable)
    return sub
