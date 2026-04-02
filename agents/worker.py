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
from sqlalchemy.exc import IntegrityError

# Maximum time (seconds) a single workflow invocation may run before being cancelled
WORKFLOW_TIMEOUT = int(
    os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "1800")
)  # 30 min default
from shared.nats_consumer import NATSConsumer  # noqa: E402
from shared.tools.database import (  # noqa: E402
    create_agent_run,
    complete_agent_run,
    execute_query,
    execute_update,
    get_latest_research,
)

# ── Import all workflow graphs ───────────────────────────────────────────
from workflows.research.graph import research_graph  # noqa: E402
from workflows.strategy.graph import strategy_graph  # noqa: E402
from workflows.planning.graph import planning_graph  # noqa: E402
from workflows.content.graph import content_graph  # noqa: E402
from workflows.evaluation.graph import evaluation_graph  # noqa: E402
from workflows.product_intel.graph import product_intel_graph  # noqa: E402
from workflows.adaptation.graph import adaptation_graph  # noqa: E402


def _setup_json_logging() -> None:
    """Configure structured JSON logging for observability."""
    try:
        from pythonjsonlogger.json import JsonFormatter

        formatter = JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
        )
    except ImportError:
        # Fallback if python-json-logger not installed
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_setup_json_logging()
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


async def _handle_image_regeneration(payload: dict[str, Any]) -> None:
    """Regenerate the image for an existing content piece."""
    from shared.llm import generate_image
    from shared.tools.storage import async_upload_file, async_ensure_bucket

    content_id = payload.get("content_id", "")
    brand_id = payload.get("brand_id", "")
    calendar_item_id = payload.get("calendar_item_id", "")
    custom_prompt = payload.get("custom_prompt")

    logger.info("Regenerating image for content %s (brand %s)", content_id, brand_id)

    # Get the content record for context
    content_rows = await execute_query(
        "SELECT headline, caption, generation_metadata FROM content WHERE id = :id",
        {"id": content_id},
    )
    if not content_rows:
        logger.error("Content %s not found for image regeneration", content_id)
        return

    content = content_rows[0]
    headline = content.get("headline", "")
    caption = content.get("caption", "")

    # Build image prompt
    if custom_prompt:
        from shared.sanitize import sanitize_for_prompt

        image_prompt = sanitize_for_prompt(custom_prompt, max_length=500)
    else:
        image_prompt = (
            f"Create a professional social media lifestyle image. "
            f"Theme: {headline}. "
            f"Context: {caption[:200]}. "
            f"Clean, modern aesthetic. Golden hour lighting. No text or logos in the image."
        )

    # Generate image
    image_url = await generate_image(image_prompt)
    logger.info("Image generated for content %s: %s chars", content_id, len(image_url))

    # Upload to MinIO
    import base64 as _b64
    import httpx as _httpx

    await async_ensure_bucket("content-images")

    if image_url.startswith("data:"):
        _, b64_part = image_url.split(",", 1)
        image_data = _b64.b64decode(b64_part)
    else:
        async with _httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            image_data = resp.content

    object_name = f"{brand_id}/{calendar_item_id}/background.png"
    await async_upload_file("content-images", object_name, image_data, "image/png")
    stored_url = f"content-images/{object_name}"

    # Update content record with the new image
    import json as _json

    existing_metadata = content.get("generation_metadata") or {}
    if isinstance(existing_metadata, str):
        try:
            existing_metadata = _json.loads(existing_metadata)
        except Exception:
            existing_metadata = {}
    existing_metadata["raw_image"] = stored_url
    existing_metadata["generated_image_url"] = stored_url

    await execute_update(
        "UPDATE content SET generation_metadata = :metadata WHERE id = :id",
        {"id": content_id, "metadata": _json.dumps(existing_metadata, default=str)},
    )

    logger.info(
        "Image regeneration complete for content %s — stored at %s",
        content_id,
        stored_url,
    )


def _resolve_graph(subject: str):
    """Resolve a NATS subject to the appropriate LangGraph graph."""
    prefix = subject.split(".")[0]
    return WORKFLOW_MAP.get(prefix)


async def _handle_message(msg: nats.aio.msg.Msg) -> None:
    """Process an incoming NATS message by dispatching to the correct graph."""
    subject = msg.subject
    logger.info("Received message on %s (%d bytes)", subject, len(msg.data))

    # ── Special handler: image regeneration (not a graph workflow) ──────
    if subject == "content.regenerate-image":
        try:
            payload = json.loads(msg.data.decode())
            await _handle_image_regeneration(payload)
        except Exception as exc:
            logger.exception("Image regeneration failed: %s", exc)
        await msg.ack()
        return

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

    # Track this run in the database
    agent_type = subject.split(".")[0]

    # Build initial state from the message payload
    initial_state: dict[str, Any] = {
        "brand_id": payload.get("brand_id", ""),
        "run_id": payload.get("run_id", ""),
        "status": "running",
        "errors": [],
        "messages": [],
    }

    # Whitelist of allowed external payload fields per workflow type
    # Fields not in the whitelist are silently dropped to prevent injection
    _PAYLOAD_WHITELIST: dict[str, set[str]] = {
        "research": {"brand_id", "run_id", "trigger", "params", "scope_weeks", "triggered_by", "timestamp"},
        "strategy": {"brand_id", "run_id", "trigger", "params", "scope_weeks", "triggered_by", "timestamp"},
        "planning": {"brand_id", "run_id", "trigger", "params", "scope_weeks", "triggered_by", "timestamp"},
        "content": {"brand_id", "run_id", "trigger", "params", "scope_weeks", "calendar_item_id", "chain_depth", "remaining_queue", "triggered_by", "timestamp"},
        "evaluation": {"brand_id", "run_id", "trigger", "params", "content_id", "triggered_by", "timestamp"},
        "product": {"brand_id", "run_id", "trigger", "params", "triggered_by", "timestamp"},
        "adaptation": {"brand_id", "run_id", "trigger", "params", "chain_depth", "triggered_by", "timestamp"},
    }
    # "auto_approve" is intentionally excluded from all whitelists

    allowed_fields = _PAYLOAD_WHITELIST.get(agent_type, {"brand_id", "run_id", "trigger", "params"})

    # Merge only whitelisted fields from the payload into the initial state
    for key, value in payload.items():
        if key not in initial_state and key in allowed_fields:
            initial_state[key] = value

    brand_id = initial_state.get("brand_id", "")
    run_id = ""

    # Ensure payload is JSON-safe (handle UUIDs, datetimes, etc.)
    safe_payload = json.loads(json.dumps(payload, default=str))

    # ── Content without calendar_item_id: query DB for queued items ──────
    # This happens when content.generate is forwarded from skip logic
    if (
        agent_type == "content"
        and not payload.get("calendar_item_id")
        and brand_id
        and _consumer is not None
    ):
        try:
            queued_items = await execute_query(
                "SELECT id FROM calendar_items WHERE brand_id = :brand_id AND status = 'queued' ORDER BY scheduled_at ASC LIMIT 100",
                {"brand_id": brand_id},
            )
            if queued_items:
                sorted_ids = [str(r["id"]) for r in queued_items]
                first_id = sorted_ids[0]
                remaining_ids = sorted_ids[1:]
                item_msg: dict[str, Any] = {
                    "brand_id": brand_id,
                    "calendar_item_id": first_id,
                    "trigger": payload.get("trigger", "activation"),
                    "chain_depth": payload.get("chain_depth", 0),
                    "remaining_queue": remaining_ids,
                }
                if payload.get("scope_weeks") is not None:
                    item_msg["scope_weeks"] = payload["scope_weeks"]
                await _consumer.js.publish(
                    "content.generate", json.dumps(item_msg).encode()
                )
                logger.info(
                    "Content skip-forward: queued first item %s (%d remaining) for brand %s",
                    first_id,
                    len(remaining_ids),
                    brand_id,
                )
            else:
                # No queued items — need to re-run planning to generate calendar items
                # Delete the old planning run so it can run fresh
                logger.info(
                    "No queued calendar items for brand %s — re-triggering planning to generate new calendar",
                    brand_id,
                )
                await execute_update(
                    "DELETE FROM agent_runs WHERE brand_id = :brand_id AND agent_type IN ('planning', 'content_calendar') AND status = 'completed'",
                    {"brand_id": brand_id},
                )
                chain_msg = json.dumps(
                    {
                        "brand_id": brand_id,
                        "trigger": payload.get("trigger", "activation"),
                        "scope_weeks": payload.get("scope_weeks", 12),
                    }
                ).encode()
                await _consumer.js.publish("planning.trigger", chain_msg)
                logger.info("Re-triggered planning.trigger for brand %s", brand_id)
            await msg.ack()
            return
        except Exception as content_skip_exc:
            logger.warning(
                "Content skip-forward failed: %s — proceeding normally",
                content_skip_exc,
            )

    # ── Skip already-completed stages on activation restart ──────
    # If this is an activation trigger and this stage already completed,
    # skip directly to the next uncompleted stage instead of re-running.
    if payload.get("trigger") == "activation" and brand_id and _consumer is not None:
        # Content is per-item — never skip it at entry point; only skip report stages
        REPORT_STAGES = ["research", "strategy", "planning"]
        ACTIVATION_CHAIN_ORDER = ["research", "strategy", "planning", "content"]
        if agent_type in REPORT_STAGES:
            try:
                already_done = await execute_query(
                    "SELECT id FROM agent_runs WHERE brand_id = :brand_id AND agent_type = :agent_type AND status = 'completed' LIMIT 1",
                    {"brand_id": brand_id, "agent_type": agent_type},
                )
                if already_done:
                    logger.info(
                        "Skipping %s — already completed for brand %s (entry-point skip)",
                        agent_type,
                        brand_id,
                    )
                    # Find next uncompleted stage
                    idx = ACTIVATION_CHAIN_ORDER.index(agent_type)
                    CHAIN_SUBJECTS = {
                        "research": "research.trigger",
                        "strategy": "strategy.trigger",
                        "planning": "planning.trigger",
                        "content": "content.generate",
                    }
                    forwarded = False
                    for next_stage in ACTIVATION_CHAIN_ORDER[idx + 1 :]:
                        if next_stage == "content":
                            # Content is per-item — always forward to it (it will pick up queued items)
                            chain_msg = json.dumps(
                                {
                                    "brand_id": brand_id,
                                    "trigger": "activation",
                                    "scope_weeks": payload.get("scope_weeks", 12),
                                }
                            ).encode()
                            await _consumer.js.publish("content.generate", chain_msg)
                            logger.info(
                                "Forwarded activation to content.generate for brand %s",
                                brand_id,
                            )
                            forwarded = True
                            break
                        next_existing = await execute_query(
                            "SELECT id FROM agent_runs WHERE brand_id = :brand_id AND agent_type = :agent_type AND status = 'completed' LIMIT 1",
                            {"brand_id": brand_id, "agent_type": next_stage},
                        )
                        if not next_existing:
                            next_subj = CHAIN_SUBJECTS.get(next_stage)
                            if next_subj:
                                chain_msg = json.dumps(
                                    {
                                        "brand_id": brand_id,
                                        "trigger": "activation",
                                        "scope_weeks": payload.get("scope_weeks", 12),
                                    }
                                ).encode()
                                await _consumer.js.publish(next_subj, chain_msg)
                                logger.info(
                                    "Forwarded activation to %s for brand %s",
                                    next_subj,
                                    brand_id,
                                )
                                forwarded = True
                            break
                    if not forwarded:
                        logger.info(
                            "All stages already completed for brand %s", brand_id
                        )
                    await msg.ack()
                    return
            except Exception as skip_exc:
                logger.warning(
                    "Entry-point skip check failed: %s — proceeding normally", skip_exc
                )

    # Idempotency: the partial unique index idx_agent_runs_running on
    # (brand_id, agent_type) WHERE status='running' prevents duplicates.
    # We catch the unique violation instead of a TOCTOU SELECT check.
    try:
        run_id = await create_agent_run(
            brand_id=brand_id,
            agent_type=agent_type,
            trigger=payload.get("trigger", "manual"),
            input_payload=safe_payload,
        )
        initial_state["run_id"] = run_id

        logger.info(
            "Dispatching %s workflow for brand %s (run %s)",
            agent_type,
            brand_id,
            run_id,
        )

        config: dict[str, Any] = {}
        if hasattr(graph, "checkpointer") and graph.checkpointer is not None:
            config["configurable"] = {"thread_id": run_id or brand_id}

        result = await asyncio.wait_for(
            graph.ainvoke(initial_state, config=config if config else None),
            timeout=WORKFLOW_TIMEOUT,
        )

        # Ensure result is JSON-safe before storing (handle UUIDs, datetimes, etc.)
        safe_result = json.loads(json.dumps(result, default=str))

        # Extract total token usage if the workflow tracked it
        tokens_used = None
        workflow_failed = False
        if isinstance(result, dict):
            tokens_used = result.get("_total_tokens") or None
            # Check if the workflow itself reported an internal failure
            if result.get("status") == "failed":
                workflow_failed = True

        final_status = "failed" if workflow_failed else "completed"
        await complete_agent_run(
            run_id,
            output_payload=safe_result,
            status=final_status,
            tokens_used=tokens_used,
        )
        logger.info(
            "Workflow %s %s for brand %s (tokens: %s)",
            agent_type,
            final_status,
            brand_id,
            tokens_used,
        )

        # ── Activation: mark brand as active once the planning pipeline finishes
        if (
            agent_type == "planning"
            and payload.get("trigger") == "activation"
            and not workflow_failed
        ):
            if brand_id:
                try:
                    await execute_update(
                        "UPDATE brands SET status = 'active', is_active = true WHERE id = :id",
                        {"id": brand_id},
                    )
                    logger.info("Brand %s activated after planning pipeline", brand_id)
                except Exception as act_exc:
                    logger.error("Failed to activate brand %s: %s", brand_id, act_exc)

        await msg.ack()

        # ── Don't chain if the workflow failed internally ──────────
        if workflow_failed:
            logger.warning(
                "Workflow %s reported internal failure for brand %s — not chaining next stage",
                agent_type,
                brand_id,
            )
            return

        # Track chain depth (used by sequential chaining and pipeline chaining)
        current_depth = payload.get("chain_depth", 0)

        # ── Sequential content chaining: after content completes, queue next item
        if (
            agent_type == "content"
            and payload.get("remaining_queue")
            and _consumer is not None
        ):
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
                    await _consumer.js.publish(
                        "content.generate", json.dumps(next_msg).encode()
                    )
                    logger.info(
                        "Sequential content: queued next item %s (%d remaining)",
                        next_id,
                        len(rest),
                    )
                except Exception as seq_exc:
                    logger.error(
                        "Failed to queue next sequential content item %s: %s",
                        next_id,
                        seq_exc,
                    )

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
                logger.warning(
                    "Could not check research for product_intel chain: %s", pi_exc
                )

        # ── Adaptation -> planning feedback loop (with guardrails) ─
        # Only chain if adaptation produced tier2 or tier3 applied
        # changes AND we haven't exceeded max chain depth.
        MAX_CHAIN_DEPTH = 2
        if agent_type == "adaptation" and brand_id and _consumer is not None:
            applied_changes = (result or {}).get("applied_changes", [])
            has_higher_tier = any(c.get("tier") in (2, 3) for c in applied_changes)
            if has_higher_tier and current_depth + 1 < MAX_CHAIN_DEPTH:
                next_subject = "planning.trigger"
                logger.info(
                    "Adaptation -> planning re-plan chain (depth %d/%d) for brand %s",
                    current_depth + 1,
                    MAX_CHAIN_DEPTH,
                    brand_id,
                )
            elif has_higher_tier:
                logger.info(
                    "Adaptation has tier2/3 changes but chain_depth %d >= max %d — stopping chain for brand %s",
                    current_depth,
                    MAX_CHAIN_DEPTH,
                    brand_id,
                )
                next_subject = None  # Override any default chain
            else:
                logger.info(
                    "Adaptation completed with tier1-only changes — no re-planning needed for brand %s",
                    brand_id,
                )
                next_subject = None  # Override evaluation->adaptation default

        # ── Skip completed report stages on restart ─────────────────────
        # When restarting, if the next REPORT stage already completed, skip ahead.
        # Content is per-item and should never be skipped.
        ACTIVATION_CHAIN_ORDER = ["research", "strategy", "planning", "content"]
        if (
            next_subject
            and brand_id
            and trigger_type == "activation"
            and _consumer is not None
        ):
            next_agent_type = next_subject.split(".")[0]
            # Never skip content — it's per-item
            if next_agent_type != "content":
                try:
                    existing = await execute_query(
                        "SELECT id FROM agent_runs WHERE brand_id = :brand_id AND agent_type = :agent_type AND status = 'completed' LIMIT 1",
                        {"brand_id": brand_id, "agent_type": next_agent_type},
                    )
                    if existing:
                        logger.info(
                            "Skipping %s — already completed for brand %s",
                            next_agent_type,
                            brand_id,
                        )
                        if next_agent_type in ACTIVATION_CHAIN_ORDER:
                            idx = ACTIVATION_CHAIN_ORDER.index(next_agent_type)
                            skipped = True
                            while skipped and idx + 1 < len(ACTIVATION_CHAIN_ORDER):
                                candidate = ACTIVATION_CHAIN_ORDER[idx + 1]
                                if candidate == "content":
                                    # Always forward to content — it processes queued items
                                    next_subject = "content.generate"
                                    skipped = False
                                    break
                                candidate_existing = await execute_query(
                                    "SELECT id FROM agent_runs WHERE brand_id = :brand_id AND agent_type = :agent_type AND status = 'completed' LIMIT 1",
                                    {"brand_id": brand_id, "agent_type": candidate},
                                )
                                if candidate_existing:
                                    logger.info(
                                        "Skipping %s — already completed for brand %s",
                                        candidate,
                                        brand_id,
                                    )
                                    idx += 1
                                else:
                                    CHAIN_SUBJECTS = {
                                        "strategy": "strategy.trigger",
                                        "planning": "planning.trigger",
                                        "content": "content.generate",
                                    }
                                    next_subject = CHAIN_SUBJECTS.get(candidate)
                                    skipped = False
                            else:
                                if skipped:
                                    logger.info(
                                        "All activation stages already completed for brand %s — no chaining needed",
                                        brand_id,
                                    )
                                    next_subject = None
                except Exception as skip_exc:
                    logger.warning(
                        "Could not check completed stages for skip logic: %s", skip_exc
                    )

        if next_subject and brand_id and _consumer is not None:
            try:
                # ── Planning -> Content sequential: publish ONE item at a time
                if agent_type == "planning" and next_subject == "content.generate":
                    calendar_item_ids = (result or {}).get("calendar_item_ids", [])
                    if calendar_item_ids:
                        # Sort by scheduled_at (nearest first) so content is generated in order
                        items = await execute_query(
                            "SELECT id FROM calendar_items WHERE id = ANY(:ids) ORDER BY scheduled_at ASC",
                            {"ids": calendar_item_ids},
                        )
                        sorted_ids = (
                            [str(r["id"]) for r in items]
                            if items
                            else [str(c) for c in calendar_item_ids]
                        )

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
                        await _consumer.js.publish(
                            next_subject, json.dumps(item_msg).encode()
                        )
                        logger.info(
                            "Sequential content: queued first item %s (%d remaining) for brand %s",
                            first_id,
                            len(remaining_ids),
                            brand_id,
                        )
                    else:
                        logger.warning(
                            "Planning completed but no calendar_item_ids in result for brand %s — querying DB for recent items",
                            brand_id,
                        )
                        # Fallback: query DB for recently stored calendar items
                        db_items = await execute_query(
                            "SELECT id FROM calendar_items WHERE brand_id = :brand_id AND status = 'queued' ORDER BY scheduled_at ASC LIMIT 100",
                            {"brand_id": brand_id},
                        )
                        if db_items:
                            sorted_ids = [str(r["id"]) for r in db_items]
                            first_id = sorted_ids[0]
                            remaining_ids = sorted_ids[1:]
                            item_msg = {
                                "brand_id": brand_id,
                                "calendar_item_id": first_id,
                                "trigger": payload.get("trigger", "event"),
                                "chain_depth": current_depth + 1,
                                "remaining_queue": remaining_ids,
                            }
                            await _consumer.js.publish(
                                next_subject, json.dumps(item_msg).encode()
                            )
                            logger.info(
                                "Fallback: queued first DB item %s (%d remaining) for brand %s",
                                first_id,
                                len(remaining_ids),
                                brand_id,
                            )
                        else:
                            logger.warning(
                                "No calendar items found in DB for brand %s — content generation skipped",
                                brand_id,
                            )
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
                    logger.info(
                        "Chained %s -> %s for brand %s (depth %d)",
                        agent_type,
                        next_subject,
                        brand_id,
                        current_depth + 1,
                    )
            except Exception as chain_exc:
                logger.error(
                    "Failed to chain %s -> %s: %s", agent_type, next_subject, chain_exc
                )
                # Log chain error separately — do NOT overwrite the already-completed run
                if run_id:
                    try:
                        await execute_update(
                            "UPDATE agent_runs SET output_payload = output_payload || :patch WHERE id = :id",
                            {
                                "id": run_id,
                                "patch": json.dumps({"_chain_error": str(chain_exc)}),
                            },
                        )
                    except Exception as patch_exc:
                        logger.warning(
                            "Could not patch chain error onto run %s: %s",
                            run_id,
                            patch_exc,
                        )

    except IntegrityError:
        # Unique violation from idx_agent_runs_running — another instance is already running
        logger.warning(
            "Skipping duplicate %s workflow for brand %s — already running (unique constraint)",
            agent_type,
            brand_id,
        )
        await msg.ack()
        return

    except asyncio.TimeoutError:
        logger.error("Workflow %s timed out for brand %s", agent_type, brand_id)
        if run_id:
            await complete_agent_run(
                run_id,
                status="failed",
                error_message=f"Timed out after {WORKFLOW_TIMEOUT}s",
            )
        await msg.nak(delay=60)

    except GraphInterrupt as gi:
        logger.info(
            "Workflow %s paused for human review (brand %s)", agent_type, brand_id
        )
        if run_id:
            await complete_agent_run(
                run_id,
                status="paused_for_review",
                output_payload=gi.value
                if hasattr(gi, "value")
                else {"reason": str(gi)},
            )
        await msg.ack()

    except Exception as exc:
        logger.exception("Workflow %s failed for brand %s", agent_type, brand_id)
        if run_id:
            await complete_agent_run(run_id, status="failed", error_message=str(exc))
        await msg.ack()  # Don't retry indefinitely on code errors


REQUIRED_SUBJECTS = [
    "research.>",
    "strategy.>",
    "content.>",
    "evaluation.>",
    "product.>",
    "planning.>",
    "adaptation.>",
]


async def _ensure_stream(consumer: NATSConsumer) -> None:
    """Ensure the WORKFLOWS stream exists with the required subjects."""
    try:
        await consumer.js.find_stream_name_by_subject("research.>")
        logger.info("Stream %s already exists", STREAM_NAME)
        # Verify all subjects are configured
        try:
            stream_info = await consumer.js.stream_info(STREAM_NAME)
            existing_subjects = set(stream_info.config.subjects or [])
            missing = set(REQUIRED_SUBJECTS) - existing_subjects
            if missing:
                logger.warning(
                    "Stream %s missing subjects: %s — updating", STREAM_NAME, missing
                )
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
