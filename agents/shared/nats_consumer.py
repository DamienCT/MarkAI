"""Base NATS JetStream consumer with connect, subscribe, ack/nak, and graceful shutdown."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, Awaitable

import nats
from nats.aio.client import Client as NATSClient
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig, DeliverPolicy, AckPolicy

from shared.config import settings, video_workflow_timeout_s

logger = logging.getLogger(__name__)

# NATS ack_wait MUST exceed the workflow timeout of the subject it serves,
# otherwise JetStream redelivers a message while its workflow is still running
# (or just finished), spawning duplicate/looping runs of the same item.
#
# Per-subject, deliberately: the reel budget is hours long, and applying it to
# research/strategy/content/planning would leave THOSE messages unredelivered
# for the same hours after a worker dies (x max_deliver=5 for the full retry
# horizon). Both values derive from the SAME env var as worker.WORKFLOW_TIMEOUT
# — and the video one from the SAME helper as worker.VIDEO_WORKFLOW_TIMEOUT —
# plus a buffer, so they can never drift apart.
_ACK_WAIT_BUFFER_S = 120
WORKFLOW_TIMEOUT_SECONDS = int(os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "5400"))

#: ack_wait for ordinary workflow subjects.
ACK_WAIT_SECONDS = WORKFLOW_TIMEOUT_SECONDS + _ACK_WAIT_BUFFER_S

#: ack_wait for video.render — per-shot render budget x the reel's shot cap,
#: plus the ffmpeg finishing passes.
VIDEO_ACK_WAIT_SECONDS = (
    video_workflow_timeout_s(WORKFLOW_TIMEOUT_SECONDS) + _ACK_WAIT_BUFFER_S
)


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
        ack_wait: int | None = None,
    ) -> None:
        """Create a durable push subscription on *subject*.

        *ack_wait* defaults to :data:`ACK_WAIT_SECONDS`; long-running subjects
        (video.render) pass their own. It must exceed the workflow timeout the
        worker applies to this subject.
        """
        wait = int(ack_wait or ACK_WAIT_SECONDS)
        config = ConsumerConfig(
            durable_name=durable_name,
            deliver_policy=DeliverPolicy.ALL,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=wait,  # must exceed this subject's workflow timeout
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
        logger.info(
            "Subscribed to %s (durable=%s, ack_wait=%ss)", subject, durable_name, wait
        )
        # JetStream does not always apply a changed ack_wait to an ALREADY
        # EXISTING durable consumer, so the deployed value can silently stay
        # at the old one. Report the drift instead of assuming subscribe()
        # re-applied it — fixing it needs an explicit `nats consumer edit`.
        try:
            info = await sub.consumer_info()
            live = int(getattr(info.config, "ack_wait", 0) or 0)
            if live and live != wait:
                logger.warning(
                    "Durable %s on %s still has ack_wait=%ss (wanted %ss) — "
                    "JetStream kept the existing consumer config; run "
                    "`nats consumer edit %s %s` to apply it",
                    durable_name, subject, live, wait, stream, durable_name,
                )
        except Exception as exc:  # informational only — never block startup
            logger.debug("Could not verify ack_wait for %s: %s", durable_name, exc)

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
