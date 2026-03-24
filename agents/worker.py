"""MARKAI Agents Worker

Main entry point: connects to NATS JetStream, subscribes to all workflow
subjects, and dispatches incoming messages to the correct LangGraph graph.

Uses durable consumers for reliable message processing and supports
graceful shutdown via SIGINT/SIGTERM.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

import nats.aio.msg

from shared.config import settings

# Maximum time (seconds) a single workflow invocation may run before being cancelled
WORKFLOW_TIMEOUT = int(os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "1800"))  # 30 min default
from shared.nats_consumer import NATSConsumer

# ── Import all workflow graphs ───────────────────────────────────────────
from workflows.research.graph import research_graph
from workflows.strategy.graph import strategy_graph
from workflows.planning.graph import planning_graph
from workflows.content.graph import content_graph
from workflows.evaluation.graph import evaluation_graph
from workflows.product_intel.graph import product_intel_graph
from workflows.adaptation.graph import adaptation_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("worker")

# ── Subject → graph mapping ─────────────────────────────────────────────
WORKFLOW_MAP = {
    "research": research_graph,
    "strategy": strategy_graph,
    "planning": planning_graph,
    "content": content_graph,
    "evaluation": evaluation_graph,
    "product": product_intel_graph,
    "adaptation": adaptation_graph,
}

# Stream name that contains all workflow subjects
STREAM_NAME = "WORKFLOWS"

# Subjects to subscribe to with their durable consumer names
SUBSCRIPTIONS = [
    ("research.>", "research-worker"),
    ("strategy.>", "strategy-worker"),
    ("content.>", "content-worker"),
    ("evaluation.>", "evaluation-worker"),
    ("product.>", "product-worker"),
    ("planning.>", "planning-worker"),
    ("adaptation.>", "adaptation-worker"),
]


def _resolve_graph(subject: str):
    """Resolve a NATS subject to the appropriate LangGraph graph."""
    prefix = subject.split(".")[0]
    return WORKFLOW_MAP.get(prefix)


async def _handle_message(msg: nats.aio.msg.Msg) -> None:
    """Process an incoming NATS message by dispatching to the correct graph."""
    subject = msg.subject
    logger.info("Received message on %s (%d bytes)", subject, len(msg.data))

    graph = _resolve_graph(subject)
    if graph is None:
        logger.error("No graph registered for subject %s", subject)
        await msg.nak(delay=60)
        return

    try:
        payload: dict[str, Any] = json.loads(msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error("Invalid JSON payload on %s", subject)
        await msg.ack()  # Don't retry bad payloads
        return

    # Build initial state from the message payload
    initial_state: dict[str, Any] = {
        "brand_id": payload.get("brand_id", ""),
        "run_id": payload.get("run_id", ""),
        "status": "running",
        "errors": [],
        "messages": [],
    }
    # Merge any extra fields from the payload into the initial state
    for key, value in payload.items():
        if key not in initial_state:
            initial_state[key] = value

    try:
        logger.info(
            "Dispatching %s workflow for brand %s (run %s)",
            subject.split(".")[0],
            initial_state.get("brand_id"),
            initial_state.get("run_id"),
        )

        # For graphs with checkpointers (strategy, adaptation), pass a thread config
        config: dict[str, Any] = {}
        if hasattr(graph, "checkpointer") and graph.checkpointer is not None:
            config["configurable"] = {
                "thread_id": initial_state.get("run_id") or initial_state.get("brand_id", "default"),
            }

        result = await asyncio.wait_for(
            graph.ainvoke(initial_state, config=config if config else None),
            timeout=WORKFLOW_TIMEOUT,
        )

        logger.info(
            "Workflow %s completed for brand %s — status: %s",
            subject.split(".")[0],
            initial_state.get("brand_id"),
            result.get("status", "unknown"),
        )
        await msg.ack()

    except asyncio.TimeoutError:
        logger.error(
            "Workflow %s timed out after %d seconds for brand %s (run %s)",
            subject.split(".")[0],
            WORKFLOW_TIMEOUT,
            initial_state.get("brand_id"),
            initial_state.get("run_id"),
        )
        await msg.nak(delay=60)

    except Exception:
        logger.exception("Workflow %s failed for brand %s", subject, initial_state.get("brand_id"))
        # Nak with delay for retry
        await msg.nak(delay=30)


async def _ensure_stream(consumer: NATSConsumer) -> None:
    """Ensure the WORKFLOWS stream exists with the required subjects."""
    try:
        await consumer.js.find_stream_name_by_subject("research.>")
        logger.info("Stream %s already exists", STREAM_NAME)
    except Exception:
        await consumer.js.add_stream(
            name=STREAM_NAME,
            subjects=[
                "research.>",
                "strategy.>",
                "content.>",
                "evaluation.>",
                "product.>",
                "planning.>",
                "adaptation.>",
            ],
            retention="workqueue",
            max_age=86400 * 7,  # 7 days
        )
        logger.info("Created stream %s", STREAM_NAME)


async def main() -> None:
    """Start the worker, subscribe to all workflow subjects, and wait for shutdown."""
    consumer = NATSConsumer()
    loop = asyncio.get_running_loop()

    # ── Graceful shutdown ────────────────────────────────────────────────
    shutdown_triggered = False

    def _request_shutdown() -> None:
        nonlocal shutdown_triggered
        if not shutdown_triggered:
            shutdown_triggered = True
            logger.info("Shutdown signal received")
            asyncio.ensure_future(consumer.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except NotImplementedError:
            # Windows does not support add_signal_handler
            signal.signal(sig, lambda *_: _request_shutdown())

    # ── Connect and subscribe ────────────────────────────────────────────
    await consumer.connect()
    await _ensure_stream(consumer)

    for subject, durable in SUBSCRIPTIONS:
        await consumer.subscribe(
            subject=subject,
            durable_name=durable,
            stream=STREAM_NAME,
            handler=_handle_message,
        )

    logger.info("Worker started — listening on %d subjects", len(SUBSCRIPTIONS))
    await consumer.wait_for_shutdown()
    logger.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
