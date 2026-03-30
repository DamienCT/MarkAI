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

from langgraph.errors import GraphInterrupt
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

# Module-level reference to the consumer, set during main()
_consumer: NATSConsumer | None = None


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

    # Track this run in the database
    from shared.tools.database import create_agent_run, complete_agent_run
    agent_type = subject.split(".")[0]
    brand_id = initial_state.get("brand_id", "")
    run_id = ""

    # Ensure payload is JSON-safe (handle UUIDs, datetimes, etc.)
    safe_payload = json.loads(json.dumps(payload, default=str))

    # Idempotency: check if there's already a running workflow of this type for this brand
    try:
        from shared.tools.database import execute_query
        existing = await execute_query(
            "SELECT id FROM agent_runs WHERE brand_id = :brand_id AND agent_type = :agent_type "
            "AND status = 'running' AND started_at > NOW() - INTERVAL '30 minutes'",
            {"brand_id": brand_id, "agent_type": agent_type},
        )
        if existing:
            logger.warning(
                "Skipping duplicate %s workflow for brand %s — already running (run %s)",
                agent_type, brand_id, existing[0].get("id"),
            )
            await msg.ack()
            return
    except Exception:
        pass  # If check fails, proceed anyway

    try:
        run_id = await create_agent_run(
            brand_id=brand_id,
            agent_type=agent_type,
            trigger=payload.get("trigger", "manual"),
            input_payload=safe_payload,
        )
        initial_state["run_id"] = run_id

        logger.info("Dispatching %s workflow for brand %s (run %s)", agent_type, brand_id, run_id)

        config: dict[str, Any] = {}
        if hasattr(graph, "checkpointer") and graph.checkpointer is not None:
            config["configurable"] = {"thread_id": run_id or brand_id}

        result = await asyncio.wait_for(
            graph.ainvoke(initial_state, config=config if config else None),
            timeout=WORKFLOW_TIMEOUT,
        )

        # Ensure result is JSON-safe before storing (handle UUIDs, datetimes, etc.)
        safe_result = json.loads(json.dumps(result, default=str))
        await complete_agent_run(run_id, output_payload=safe_result, status="completed")
        logger.info("Workflow %s completed for brand %s", agent_type, brand_id)

        # ── Activation: mark brand as active once the planning pipeline finishes
        if agent_type == "planning" and payload.get("trigger") == "activation":
            if brand_id:
                try:
                    from shared.tools.database import execute_query
                    await execute_query(
                        "UPDATE brands SET status = 'active', is_active = true WHERE id = :id",
                        {"id": brand_id},
                    )
                    logger.info("Brand %s activated after planning pipeline", brand_id)
                except Exception as act_exc:
                    logger.error("Failed to activate brand %s: %s", brand_id, act_exc)

        await msg.ack()

        # Track chain depth (used by sequential chaining and pipeline chaining)
        current_depth = payload.get("chain_depth", 0)

        # ── Sequential content chaining: after content completes, queue next item
        if agent_type == "content" and payload.get("remaining_queue") and _consumer is not None:
            remaining = payload["remaining_queue"]
            if remaining:
                next_id = remaining[0]
                rest = remaining[1:]
                next_msg: dict[str, Any] = {
                    "brand_id": brand_id,
                    "calendar_item_id": next_id,
                    "trigger": payload.get("trigger", "event"),
                    "chain_depth": current_depth + 1,
                    "remaining_queue": rest,
                }
                if payload.get("scope_weeks") is not None:
                    next_msg["scope_weeks"] = payload["scope_weeks"]
                try:
                    await _consumer.js.publish("content.generate", json.dumps(next_msg).encode())
                    logger.info("Sequential content: queued next item %s (%d remaining)", next_id, len(rest))
                except Exception as seq_exc:
                    logger.error("Failed to queue next sequential content item %s: %s", next_id, seq_exc)

        # ── Chain: auto-trigger the next workflow in the pipeline ─────
        # Full pipeline chain only runs for "activation" triggers.
        # Regular triggers (manual research, auto-discover) run standalone.
        trigger_type = payload.get("trigger", "")
        CHAIN_NEXT: dict[str, str] = {}
        if trigger_type == "activation":
            CHAIN_NEXT = {
                "research": "strategy.trigger",
                "strategy": "planning.trigger",
                "planning": "content.generate",
            }
        # Evaluation always chains to adaptation regardless of trigger
        CHAIN_NEXT["evaluation"] = "adaptation.trigger"

        next_subject = CHAIN_NEXT.get(agent_type)

        # ── Product intel conditional chain ───────────────────────
        # After product_intel completes, chain to strategy ONLY if
        # the brand already has completed research (otherwise the
        # strategy graph would fail on load_research).
        if agent_type == "product" and brand_id and _consumer is not None:
            try:
                from shared.tools.database import get_latest_research
                existing_research = await get_latest_research(brand_id)
                if existing_research:
                    next_subject = "strategy.trigger"
                    logger.info(
                        "Product intel -> strategy chain enabled: research exists for brand %s",
                        brand_id,
                    )
                else:
                    logger.info(
                        "Product intel completed for brand %s but no research found — skipping strategy chain",
                        brand_id,
                    )
            except Exception as pi_exc:
                logger.warning("Could not check research for product_intel chain: %s", pi_exc)

        # ── Adaptation -> planning feedback loop (with guardrails) ─
        # Only chain if adaptation produced tier2 or tier3 applied
        # changes AND we haven't exceeded max chain depth.
        MAX_CHAIN_DEPTH = 2
        if agent_type == "adaptation" and brand_id and _consumer is not None:
            applied_changes = (result or {}).get("applied_changes", [])
            has_higher_tier = any(
                c.get("tier") in (2, 3) for c in applied_changes
            )
            if has_higher_tier and current_depth + 1 < MAX_CHAIN_DEPTH:
                next_subject = "planning.trigger"
                logger.info(
                    "Adaptation -> planning re-plan chain (depth %d/%d) for brand %s",
                    current_depth + 1, MAX_CHAIN_DEPTH, brand_id,
                )
            elif has_higher_tier:
                logger.info(
                    "Adaptation has tier2/3 changes but chain_depth %d >= max %d — stopping chain for brand %s",
                    current_depth, MAX_CHAIN_DEPTH, brand_id,
                )
                next_subject = None  # Override any default chain
            else:
                logger.info(
                    "Adaptation completed with tier1-only changes — no re-planning needed for brand %s",
                    brand_id,
                )
                next_subject = None  # Override evaluation->adaptation default

        if next_subject and brand_id and _consumer is not None:
            try:
                # ── Planning -> Content sequential: publish ONE item at a time
                if agent_type == "planning" and next_subject == "content.generate":
                    calendar_item_ids = (result or {}).get("calendar_item_ids", [])
                    if calendar_item_ids:
                        # Sort by scheduled_at (nearest first) so content is generated in order
                        from shared.tools.database import execute_query as _eq
                        items = await _eq(
                            "SELECT id FROM calendar_items WHERE id = ANY(:ids) ORDER BY scheduled_at ASC",
                            {"ids": calendar_item_ids},
                        )
                        sorted_ids = [str(r["id"]) for r in items] if items else [str(c) for c in calendar_item_ids]

                        # Publish only the FIRST item; remaining are chained via remaining_queue
                        first_id = sorted_ids[0]
                        remaining_ids = sorted_ids[1:]

                        item_msg: dict[str, Any] = {
                            "brand_id": brand_id,
                            "calendar_item_id": first_id,
                            "trigger": payload.get("trigger", "event"),
                            "chain_depth": current_depth + 1,
                            "remaining_queue": remaining_ids,
                        }
                        if payload.get("scope_weeks") is not None:
                            item_msg["scope_weeks"] = payload["scope_weeks"]
                        await _consumer.js.publish(next_subject, json.dumps(item_msg).encode())
                        logger.info(
                            "Sequential content: queued first item %s (%d remaining) for brand %s",
                            first_id, len(remaining_ids), brand_id,
                        )
                    else:
                        logger.warning("Planning completed but no calendar_item_ids in result — skipping content chain")
                else:
                    # Standard single-message chain — propagate trigger & scope_weeks
                    chain_msg: dict[str, Any] = {
                        "brand_id": brand_id,
                        "trigger": payload.get("trigger", "event"),
                        "chain_depth": current_depth + 1,
                    }
                    if payload.get("scope_weeks") is not None:
                        chain_msg["scope_weeks"] = payload["scope_weeks"]
                    chain_payload = json.dumps(chain_msg).encode()
                    await _consumer.js.publish(next_subject, chain_payload)
                    logger.info("Chained %s -> %s for brand %s (depth %d)", agent_type, next_subject, brand_id, current_depth + 1)
            except Exception as chain_exc:
                logger.error("Failed to chain %s -> %s: %s", agent_type, next_subject, chain_exc)
                # Update run status to indicate chain failure so the UI can show it
                if run_id:
                    await complete_agent_run(
                        run_id,
                        output_payload={**(safe_result or {}), "_chain_error": str(chain_exc)},
                        status="completed",
                    )

    except asyncio.TimeoutError:
        logger.error("Workflow %s timed out for brand %s", agent_type, brand_id)
        if run_id:
            await complete_agent_run(run_id, status="failed", error_message=f"Timed out after {WORKFLOW_TIMEOUT}s")
        await msg.nak(delay=60)

    except GraphInterrupt as gi:
        logger.info("Workflow %s paused for human review (brand %s)", agent_type, brand_id)
        if run_id:
            await complete_agent_run(
                run_id,
                status="paused_for_review",
                output_payload=gi.value if hasattr(gi, "value") else {"reason": str(gi)},
            )
        await msg.ack()

    except Exception as exc:
        logger.exception("Workflow %s failed for brand %s", agent_type, brand_id)
        if run_id:
            await complete_agent_run(run_id, status="failed", error_message=str(exc))
        await msg.ack()  # Don't retry indefinitely on code errors


REQUIRED_SUBJECTS = [
    "research.>", "strategy.>", "content.>",
    "evaluation.>", "product.>", "planning.>", "adaptation.>",
]


async def _ensure_stream(consumer: NATSConsumer) -> None:
    """Ensure the WORKFLOWS stream exists with the required subjects."""
    try:
        info = await consumer.js.find_stream_name_by_subject("research.>")
        logger.info("Stream %s already exists", STREAM_NAME)
        # Verify all subjects are configured
        try:
            stream_info = await consumer.js.stream_info(STREAM_NAME)
            existing_subjects = set(stream_info.config.subjects or [])
            missing = set(REQUIRED_SUBJECTS) - existing_subjects
            if missing:
                logger.warning("Stream %s missing subjects: %s — updating", STREAM_NAME, missing)
                await consumer.js.update_stream(
                    name=STREAM_NAME,
                    subjects=REQUIRED_SUBJECTS,
                )
        except Exception as e:
            logger.warning("Could not verify stream subjects: %s", e)
    except Exception:
        await consumer.js.add_stream(
            name=STREAM_NAME,
            subjects=REQUIRED_SUBJECTS,
            retention="workqueue",
            max_age=86400 * 7,  # 7 days
        )
        logger.info("Created stream %s", STREAM_NAME)


async def main() -> None:
    """Start the worker, subscribe to all workflow subjects, and wait for shutdown."""
    global _consumer
    consumer = NATSConsumer()
    _consumer = consumer
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
