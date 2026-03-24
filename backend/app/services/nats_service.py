import json
import logging
from typing import Any

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext

from app.config import settings

logger = logging.getLogger(__name__)

_nc: NATSClient | None = None
_js: JetStreamContext | None = None

STREAMS = {
    "BRAND": {"subjects": ["brand.>"]},
    "RESEARCH": {"subjects": ["research.>"]},
    "STRATEGY": {"subjects": ["strategy.>"]},
    "CONTENT": {"subjects": ["content.>"]},
    "PUBLISH": {"subjects": ["publish.>"]},
    "ENGAGEMENT": {"subjects": ["engagement.>"]},
    "EVALUATION": {"subjects": ["evaluation.>"]},
    "PRODUCT": {"subjects": ["product.>"]},
}


async def connect() -> NATSClient:
    """Connect to NATS and set up JetStream streams."""
    global _nc, _js
    _nc = await nats.connect(settings.NATS_URL)
    _js = _nc.jetstream()

    # Ensure all streams exist
    for stream_name, stream_config in STREAMS.items():
        try:
            await _js.find_stream_name_by_subject(stream_config["subjects"][0])
        except Exception:
            await _js.add_stream(
                name=stream_name,
                subjects=stream_config["subjects"],
            )
            logger.info("Created NATS JetStream stream: %s", stream_name)

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
    deliver_policy: str = "all",
):
    """
    Create a pull subscription on a JetStream subject.
    Returns a subscription that can be used to fetch messages.
    """
    js = get_jetstream()
    sub = await js.pull_subscribe(subject, durable=durable)
    return sub
