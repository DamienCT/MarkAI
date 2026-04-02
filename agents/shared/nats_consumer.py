"""Base NATS JetStream consumer with connect, subscribe, ack/nak, and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy

from shared.config import settings

logger = logging.getLogger(__name__)


class NATSConsumer:
    """Manages a durable JetStream push-subscription."""

    def __init__(self) -> None:
        self._nc: NATSClient | None = None
        self._js: JetStreamContext | None = None
        self._subscriptions: list[nats.js.JetStreamContext.PushSubscription] = []
        self._shutdown_event = asyncio.Event()

    async def connect(self) -> None:
        """Connect to the NATS server."""
        connect_opts: dict = {
            "servers": settings.NATS_URL,
            "reconnect_time_wait": 2,
            "max_reconnect_attempts": -1,
        }
        if settings.NATS_AUTH_TOKEN:
            connect_opts["token"] = settings.NATS_AUTH_TOKEN
        self._nc = await nats.connect(**connect_opts)
        self._js = self._nc.jetstream()
        logger.info("Connected to NATS at %s", settings.NATS_URL)

    @property
    def js(self) -> JetStreamContext:
        assert self._js is not None, "Call connect() first"
        return self._js

    async def subscribe(
        self,
        subject: str,
        durable_name: str,
        stream: str,
        handler: Callable[[nats.aio.msg.Msg], Awaitable[None]],
    ) -> None:
        """Create a durable push subscription on *subject*."""
        config = ConsumerConfig(
            durable_name=durable_name,
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=1860,  # 31 minutes — must exceed WORKFLOW_TIMEOUT (30 min)
            max_deliver=5,  # after 5 delivery attempts, message is discarded
        )
        sub = await self.js.subscribe(
            subject,
            stream=stream,
            config=config,
            cb=handler,
            manual_ack=True,
        )
        self._subscriptions.append(sub)
        logger.info("Subscribed to %s (durable=%s)", subject, durable_name)

    @staticmethod
    async def ack(msg: nats.aio.msg.Msg) -> None:
        await msg.ack()

    @staticmethod
    async def nak(msg: nats.aio.msg.Msg, delay: int = 5) -> None:
        await msg.nak(delay=delay)

    async def shutdown(self) -> None:
        """Unsubscribe from all subjects and close the connection."""
        logger.info("Shutting down NATS consumer …")
        for sub in self._subscriptions:
            try:
                await sub.unsubscribe()
            except Exception:
                logger.exception("Error unsubscribing")
        self._subscriptions.clear()
        if self._nc and not self._nc.is_closed:
            await self._nc.drain()
            await self._nc.close()
        self._shutdown_event.set()
        logger.info("NATS consumer shut down.")

    async def wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()
