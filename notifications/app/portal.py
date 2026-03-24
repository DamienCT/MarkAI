"""In-app notifications via SSE backed by Valkey (Redis-compatible) pub/sub.

Real Valkey connections for publish and subscribe operations.
"""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import valkey.asyncio as valkey

from app.config import settings

logger = logging.getLogger("notifications.portal")


def _channel_name(user_id: str) -> str:
    return f"markai:notifications:{user_id}"


def _valkey_url() -> str:
    return f"redis://{settings.VALKEY_HOST}:{settings.VALKEY_PORT}"


async def publish_notification(user_id: str, notification: dict) -> int:
    """Publish a notification dict to the Valkey channel for *user_id*.

    Returns the number of subscribers that received the message.
    """
    client = valkey.from_url(_valkey_url())
    try:
        channel = _channel_name(user_id)
        payload = json.dumps(notification)
        count = await client.publish(channel, payload)
        logger.info(
            "Published notification to user=%s channel=%s subscribers=%d",
            user_id,
            channel,
            count,
        )
        return count
    finally:
        await client.aclose()


async def subscribe_user(user_id: str) -> valkey.client.PubSub:
    """Create a Valkey pub/sub subscription for *user_id*.

    Returns the PubSub object (caller must close it).
    """
    client = valkey.from_url(_valkey_url())
    pubsub = client.pubsub()
    channel = _channel_name(user_id)
    await pubsub.subscribe(channel)
    logger.info("Subscribed to channel=%s for user=%s", channel, user_id)
    return pubsub


async def sse_stream(user_id: str) -> AsyncIterator[dict]:
    """Async generator yielding SSE-formatted events from Valkey pub/sub.

    Each yielded dict has 'event' and 'data' keys compatible with
    sse-starlette's EventSourceResponse.
    """
    pubsub = await subscribe_user(user_id)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield {
                    "event": "notification",
                    "data": data,
                }
    except Exception:
        logger.exception("SSE stream error for user=%s", user_id)
        raise
    finally:
        await pubsub.unsubscribe(_channel_name(user_id))
        await pubsub.aclose()
