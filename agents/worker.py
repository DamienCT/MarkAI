"""MARKAI Agents Worker

Main entry point: connects to NATS JetStream, subscribes to all workflow
subjects, and dispatches incoming messages to the correct LangGraph graph.

Uses durable consumers for reliable message processing. SIGINT/SIGTERM
starts a graceful drain: no new messages, in-flight workflows finish inside
the grace budget, everything else is nak'd back for the next container.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import signal
import sys
import time
import uuid as _uuid
from typing import Any, Callable

import nats.aio.msg

from langgraph.errors import GraphInterrupt
from sqlalchemy.exc import IntegrityError

# Maximum time (seconds) a single workflow invocation may run before being cancelled
WORKFLOW_TIMEOUT = int(
    os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "5400")
)  # 90 min default (full-year calendar = 200+ LLM calls)
from shared.config import video_workflow_timeout_s as _video_timeout  # noqa: E402
from shared.nats_consumer import (  # noqa: E402
    VIDEO_ACK_WAIT_SECONDS,
    NATSConsumer,
)

# A reel renders up to VIDEO_MAX_REEL_SHOTS shots SEQUENTIALLY (each one
# provider call bounded by VIDEO_RENDER_TIMEOUT_S — render_video wraps every
# shot in its own asyncio.wait_for, so a shot cannot spend the whole cascade's
# worth of deadlines) plus the ffmpeg normalize/concat/burn passes. Budgeting
# the video workflow timeout for that worst case is what keeps asyncio.wait_for
# from cancelling a live render mid-flight. nats_consumer.VIDEO_ACK_WAIT_SECONDS
# derives from the SAME helper (+ buffer) so JetStream never redelivers a live
# run; the other subjects keep the ordinary, much shorter ack_wait.
VIDEO_WORKFLOW_TIMEOUT = _video_timeout(WORKFLOW_TIMEOUT)
from shared.tools.database import (  # noqa: E402
    create_agent_run,
    complete_agent_run,
    execute_query,
    execute_update,
    get_latest_research,
    notify_admins,
)

# ── Import all workflow graphs ───────────────────────────────────────────
from workflows.research.graph import research_graph  # noqa: E402
from workflows.strategy.graph import strategy_graph  # noqa: E402
from workflows.planning.graph import planning_graph  # noqa: E402
from workflows.content.graph import content_graph  # noqa: E402
from workflows.evaluation.graph import evaluation_graph  # noqa: E402
from workflows.product_intel.graph import product_intel_graph  # noqa: E402
from workflows.adaptation.graph import adaptation_graph  # noqa: E402
from workflows.video.graph import video_graph  # noqa: E402


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

    # httpx/httpcore log every request line — full URL, query string included —
    # at INFO, which is how credential-bearing URLs reach stdout (N-01).
    # Keep them at WARNING so request URLs never enter the logs (mirrors
    # backend main.py).
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


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
    "video": video_graph,
}

# Stream name that contains all workflow subjects
STREAM_NAME = "WORKFLOWS"

# Dedicated stream for video render jobs (created by the backend's
# nats_service; ensured here too so worker startup order doesn't matter)
VIDEO_STREAM_NAME = "VIDEO"

# Subjects to subscribe to with their durable consumer names, stream, and
# ack_wait. None = the ordinary WORKFLOW_TIMEOUT-derived wait; only video.render
# needs the hours-long reel budget, and giving it to the others would leave a
# planning message unredelivered for hours after a worker dies.
SUBSCRIPTIONS = [
    ("research.>", "research-worker", STREAM_NAME, None),
    ("strategy.>", "strategy-worker", STREAM_NAME, None),
    ("content.>", "content-worker", STREAM_NAME, None),
    ("evaluation.>", "evaluation-worker", STREAM_NAME, None),
    ("product.>", "product-worker", STREAM_NAME, None),
    ("planning.>", "planning-worker", STREAM_NAME, None),
    ("adaptation.>", "adaptation-worker", STREAM_NAME, None),
    ("video.render", "video-worker", VIDEO_STREAM_NAME, VIDEO_ACK_WAIT_SECONDS),
]

# Module-level reference to the consumer, set during main()
_consumer: NATSConsumer | None = None

# ── Graceful drain (SIGTERM/SIGINT) ─────────────────────────────────────
# docker compose sends SIGTERM on redeploy and escalates to SIGKILL after
# stop_grace_period (15m). Killing the worker mid-workflow strands the
# calendar item until the release guards fire and parks the message for a
# multi-hour ack_wait before redelivery — so on SIGTERM the worker stops
# taking new messages, lets the in-flight workflow(s) finish inside this
# budget, and hands everything else back with a short nak. The budget must
# stay comfortably under stop_grace_period: the exit tail (deferred naks +
# NATS close) has to run before docker stops asking nicely.
# Clamped to 840s: compose SIGKILLs at stop_grace_period (900s), and a
# budget above it silently guarantees the kill lands BEFORE the exit naks —
# strictly worse than the default, and invisible until the next incident.
_DRAIN_BUDGET_CAP = 840
DRAIN_BUDGET_SECONDS = int(os.environ.get("DRAIN_BUDGET_SECONDS", "840"))
if DRAIN_BUDGET_SECONDS > _DRAIN_BUDGET_CAP:
    logging.getLogger(__name__).warning(
        "DRAIN_BUDGET_SECONDS=%d exceeds the %ds cap (stop_grace_period "
        "minus the exit tail) — clamping",
        DRAIN_BUDGET_SECONDS,
        _DRAIN_BUDGET_CAP,
    )
    DRAIN_BUDGET_SECONDS = _DRAIN_BUDGET_CAP

# nak delay for work handed back at exit. The naks fire immediately before
# the process exits, and compose starts the replacement container only after
# this one is gone — so the redelivery lands on the NEW container about one
# delay after it subscribes, instead of waiting out ack_wait.
DRAIN_NAK_DELAY_SECONDS = int(os.environ.get("DRAIN_NAK_DELAY_SECONDS", "60"))

_DRAIN_POLL_SECONDS = 2.0

_draining = False
#: token → {msg, subject, agent_type, payload, started} for every message a
#: workflow is currently running on. The drain uses it to know when the last
#: in-flight workflow finishes — and whose message to hand back if the
#: budget expires first.
_in_flight: dict[int, dict[str, Any]] = {}
_in_flight_tokens = itertools.count(1)
#: Messages to hand back right before exit: [{"msg", "label", "token"}].
#: Deferred to exit ON PURPOSE: compose starts the replacement only after
#: this container exits, so an early nak can only redeliver HERE, where the
#: drain gate bounces it again — every bounce burning one of max_deliver=5
#: attempts toward a silent discard. One nak at exit costs one attempt and
#: reaches the new container just as fast.
_deferred_naks: list[dict[str, Any]] = []
_drain_task: asyncio.Task | None = None


# The only integrity failure that means "a run is already in flight" is the
# partial unique index. Anything else — a check constraint, a bad foreign key
# — is a message that will NEVER insert, and NAKing it as a duplicate retries
# it forever under a log line saying something untrue.
_DUPLICATE_RUN_MARKERS = ("idx_agent_runs_running", "uniqueviolation")


def _is_duplicate_run_error(exc: Exception) -> bool:
    """True only for the idempotency index violation (pure function)."""
    text = str(exc).lower()
    return any(marker in text for marker in _DUPLICATE_RUN_MARKERS)


# Mirrors ConsumerConfig(max_deliver=5) in shared/nats_consumer.py — after this
# many delivery attempts JetStream discards the message silently, so a nak on
# the final attempt is a goodbye, not a retry.
_MAX_DELIVER = 5


def _delivery_attempt(msg: Any) -> int:
    """Which delivery attempt this is (1-based).

    Falls back to 1 when the metadata is unreadable (e.g. a malformed reply
    subject): treating an unknown attempt as the first errs toward "a retry is
    still coming", which never publishes a continuation too early.
    """
    try:
        return int(msg.metadata.num_delivered or 1)
    except Exception:
        return 1


def _register_run_id(run_id: str) -> None:
    """Attach the freshly created agent_runs id to this task's in-flight entry.

    The shutdown drain scopes its release UPDATE to exactly the run ids
    registered here (AG-11): a global WHERE status='running' would fail
    ANOTHER worker's live runs — and free their dedup locks — the moment a
    second worker exists.
    """
    task = asyncio.current_task()
    for entry in _in_flight.values():
        if entry.get("task") is task:
            entry["run_id"] = run_id
            return


def _extract_interrupts(result: Any) -> list[dict[str, Any]]:
    """JSON-safe interrupt payloads from a graph invoke result ([] = none).

    langgraph 1.1.3 does NOT raise GraphInterrupt out of (a)invoke: a node
    hitting interrupt() makes the invocation return NORMALLY with the pending
    interrupts under result["__interrupt__"] as a list of
    langgraph.types.Interrupt (attrs: value, id) — verified against the
    installed version, with and without a checkpointer. Missing this marker
    records an unapproved, half-done run as 'completed' and chains it
    downstream (P0-01).
    """
    if not isinstance(result, dict):
        return []
    raw = result.get("__interrupt__") or []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    interrupts: list[dict[str, Any]] = []
    for item in raw:
        value = getattr(item, "value", item)
        try:
            value = json.loads(json.dumps(value, default=str))
        except Exception:
            value = {"repr": repr(item)}
        interrupt_id = getattr(item, "id", None)
        interrupts.append(
            {
                "value": value,
                "interrupt_id": str(interrupt_id) if interrupt_id else None,
            }
        )
    return interrupts


async def _record_paused_run(
    run_id: str | None,
    agent_type: str,
    brand_id: str,
    interrupts: list[dict[str, Any]],
) -> None:
    """Persist an interrupted run as paused_for_review + notify the operators.

    Only the interrupt payload is stored — NOT the graph's half-done
    artifacts: a 'completed'-shaped strategy payload from an interrupted run
    is exactly what poisoned get_latest_strategy with an unapproved,
    wrong-shaped strategy (N-09; the getter filters status='completed').
    """
    logger.info(
        "Workflow %s paused for human review (brand %s, run %s)",
        agent_type,
        brand_id,
        run_id,
    )
    if run_id:
        try:
            await complete_agent_run(
                run_id,
                status="paused_for_review",
                output_payload={
                    "paused_for_review": True,
                    "interrupts": interrupts,
                },
            )
        except Exception as pause_exc:
            logger.error(
                "Could not record run %s as paused_for_review: %s",
                run_id,
                pause_exc,
            )
    try:
        brand_name = "a brand"
        if brand_id:
            rows = await execute_query(
                "SELECT name FROM brands WHERE id = :bid", {"bid": brand_id}
            )
            brand_name = (rows[0].get("name") if rows else None) or brand_name
        first_message = ""
        if interrupts and isinstance(interrupts[0].get("value"), dict):
            first_message = str(interrupts[0]["value"].get("message") or "")
        # 'approval_request' is in the notifications CHECK constraint;
        # 'review_required' etc. are not.
        await notify_admins(
            notification_type="approval_request",
            title=f"{agent_type.capitalize()} run paused for review — {brand_name}",
            body=first_message
            or f"{brand_name}: the {agent_type} workflow is waiting for a human decision.",
            reference_type="agent_run",
            reference_id=str(run_id) if run_id else None,
            roles=("admin", "manager", "editor"),
        )
    except Exception as notif_exc:
        logger.warning(
            "paused_for_review notification skipped for run %s: %s",
            run_id,
            notif_exc,
        )


async def _continue_content_chain(
    agent_type: str, payload: dict[str, Any], reason: str
) -> None:
    """Keep a sequential content batch moving past a terminally-dropped item.

    The batch lives ONLY in the in-flight message's remaining_queue — when a
    per-item terminal outcome (workflow failure, code error, rejected run
    insert, final-delivery discard, redelivery skip) acks that message, every
    item behind it is stranded in status='queued' with nothing left to carry
    it forward. Publishing a QUEUE-LESS content.generate for the brand lets
    the skip-forward path at the top of _handle_message re-derive the queue
    from the status='queued' rows and start a fresh chain.

    Termination — this must never become a message loop:

    - Publishes only when the dying message carried a NON-EMPTY
      remaining_queue — i.e. items are demonstrably stranded BEHIND it. A
      single-item message (manual generate, morning top-up) strands nothing:
      the morning top-up retries past-due queued items daily, and letting
      those messages respawn made every routine redelivery sweep the brand's
      whole queue into generation. A batch's LAST item carries an empty
      queue and likewise needs no continuation. The queue-less continuations
      this helper publishes can therefore never respawn themselves.
    - The continuation carries resume=True, which tells the skip-forward path
      that finding zero queued items means "batch complete" — it must NOT
      fall into the re-trigger-planning branch, which would turn one failed
      last item into an endless plan → generate → fail cycle.
    - Callers on paths where the dying item may still be status='queued'
      (the rejected-run-insert path dies before the graph ever flips it)
      must fail that item out of the queue first — otherwise re-derivation
      re-picks the same item and the failure ping-pongs forever.

    Best-effort: the caller is on its way to ack a message JetStream will
    never redeliver, so this must never raise.
    """
    try:
        if agent_type != "content":
            return
        brand_id = payload.get("brand_id") or ""
        if not brand_id or _consumer is None:
            return
        if not payload.get("remaining_queue"):
            return
        cont: dict[str, Any] = {
            "brand_id": brand_id,
            "trigger": payload.get("trigger", "event"),
            "chain_depth": payload.get("chain_depth", 0),
            "resume": True,
        }
        if payload.get("scope_weeks") is not None:
            cont["scope_weeks"] = payload["scope_weeks"]
        await _consumer.js.publish("content.generate", json.dumps(cont).encode())
        logger.info(
            "Continued content batch for brand %s after terminal drop (%s)",
            brand_id,
            reason,
        )
    except Exception as cont_exc:
        logger.warning(
            "Could not continue content batch for brand %s: %s — remaining "
            "queued items stay queued until the next trigger",
            payload.get("brand_id"),
            cont_exc,
        )


async def _notify_workflow_failure(
    agent_type: str, brand_id: str, run_id: str, reason: str
) -> None:
    """Best-effort admin alert when a workflow dies for good.

    Terminal failures were only discoverable by opening the runs page — the
    calendar quietly showed a 'failed' item days later. Never raises: the
    caller is on its ack path, and a dead notifications table must not turn
    one failure into a redelivery loop.
    """
    try:
        brand_name = ""
        if brand_id:
            rows = await execute_query(
                "SELECT name FROM brands WHERE id = :bid", {"bid": brand_id}
            )
            brand_name = (rows[0].get("name") if rows else None) or ""
        label = agent_type.replace("_", " ").capitalize()
        title = f"{label} workflow failed"
        if brand_name:
            title = f"{title} — {brand_name}"
        await notify_admins(
            # 'error' is in the notifications CHECK constraint's allowed set;
            # a bespoke 'workflow_failed' type is NOT — the insert would
            # violate the CHECK and the alert would die as a warning log,
            # which is the exact silence this function exists to end.
            notification_type="error",
            title=title,
            body=(reason or "Unknown error")[:500],
            reference_type="agent_run" if run_id else "brand",
            reference_id=str(run_id) if run_id else (str(brand_id) or None),
        )
    except Exception as notif_exc:
        logger.warning("workflow_failed notification skipped: %s", notif_exc)


async def _release_stuck_calendar_item(
    agent_type: str,
    payload: dict[str, Any],
    reason: str,
    *,
    include_queued: bool = False,
) -> None:
    """Move a calendar_item out of its in-flight status when its workflow dies.

    Without this, an item set to 'working' by content/nodes.py — or to
    'working'/'rendering' by the video pipeline — stays stuck forever if the
    graph dies (timeout, exception, internal failure) and blocks the UI from
    showing it correctly.

    include_queued is for the rejected-run-insert path only: it dies BEFORE
    the graph ever flips the item out of 'queued', and the rejection is
    deterministic (a check/FK violation retries into the same wall). Leaving
    the item queued would make the batch-continue re-derivation pick the very
    same item again and ping-pong forever — so that one caller fails the
    queued item out too. Every other caller fires after the graph ran, when a
    still-'queued' item means the graph never claimed it and a retry can.
    """
    if agent_type == "content":
        stuck_filter = (
            "status IN ('queued', 'working')"
            if include_queued
            else "status = 'working'"
        )
    elif agent_type == "video":
        # load_video_context moves the item queued → working → rendering;
        # a dead run can strand it in either intermediate state.
        stuck_filter = (
            "status IN ('queued', 'working', 'rendering')"
            if include_queued
            else "status IN ('working', 'rendering')"
        )
    else:
        return
    calendar_item_id = payload.get("calendar_item_id")
    if not calendar_item_id:
        return
    try:
        await execute_update(
            # CAST(:reason AS text), not :reason::text — SQLAlchemy's bind-param
            # regex refuses to match a name followed by ':', so the ::-form ships
            # the literal ":reason" to Postgres and the statement dies on syntax.
            "UPDATE calendar_items "
            "SET status = 'failed', "
            "    generation_metadata = COALESCE(generation_metadata, '{}'::jsonb) "
            "        || jsonb_build_object('last_error', CAST(:reason AS text)) "
            f"WHERE id = :id AND {stuck_filter}",
            {"id": calendar_item_id, "reason": reason},
        )
        logger.info(
            "Released stuck calendar_item %s (%s → failed): %s",
            calendar_item_id,
            stuck_filter,
            reason,
        )
    except Exception as rel_exc:
        logger.warning(
            "Failed to release stuck calendar_item %s: %s",
            calendar_item_id,
            rel_exc,
        )


async def _replace_product_in_image(
    image_data: bytes,
    product_image_url: str,
    product_name: str,
    vendor_name: str = "",
) -> bytes:
    """Resolve the product photo, then run the shared guarded swap.

    Only the URL resolution lives here; the swap itself is
    shared.product_swap.swap_product_into_image, the same call the content
    workflow makes. This function used to hold a second, divergent copy of
    the swap that skipped the fabrication guard entirely.
    """
    import httpx as _httpx

    try:
        # Resolve product image URL → bytes (http URL, /api path, or MinIO key)
        if product_image_url.startswith(("http://", "https://")):
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(product_image_url)
                resp.raise_for_status()
                product_image_data = resp.content
        elif product_image_url.startswith("/"):
            from shared.config import media_auth_headers, settings as _cfg
            backend_url = getattr(_cfg, "BACKEND_URL", "http://backend:8000")
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"{backend_url}{product_image_url}",
                    headers=media_auth_headers(),
                )
                resp.raise_for_status()
                product_image_data = resp.content
        else:
            from shared.config import media_auth_headers, settings as _storage_cfg
            from shared.tools.storage import async_download_file as _adl
            default_bucket = getattr(_storage_cfg, "MINIO_BUCKET", "markai-assets")
            try:
                product_image_data = await _adl(default_bucket, product_image_url)
            except Exception:
                backend_url = getattr(_storage_cfg, "BACKEND_URL", "http://backend:8000")
                async with _httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        f"{backend_url}/api/v1/files/{product_image_url}",
                        headers=media_auth_headers(),
                    )
                    resp.raise_for_status()
                    product_image_data = resp.content

        from shared.product_swap import swap_product_into_image

        # One implementation, shared with the content workflow. This path used
        # to carry its own copy that returned the editor's first output
        # UNREAD — no fabrication guard, no retry — so a post regenerated from
        # the UI, the button a reviewer presses precisely BECAUSE the image
        # was wrong, had less protection than the run that produced it.
        return await swap_product_into_image(
            image_data,
            product_image_data,
            product_name,
            vendor_name=vendor_name,
            label=f"regen:{product_name[:40]}",
        )
    except Exception as exc:
        logger.warning("Gemini product replacement failed on regen: %s — using base image", exc)

    return image_data


async def _download_product_asset(ref: str | None) -> bytes | None:
    """Download a product asset (logo) from a MinIO object name or URL."""
    if not ref:
        return None
    import httpx as _httpx
    from shared.config import media_auth_headers, settings as _cfg
    from shared.tools.storage import async_download_file as _adl

    try:
        if ref.startswith("http://") or ref.startswith("https://"):
            async with _httpx.AsyncClient(timeout=30) as c:
                r = await c.get(ref)
                r.raise_for_status()
                return r.content
        if ref.startswith("/"):
            async with _httpx.AsyncClient(timeout=30) as c:
                r = await c.get(
                    f"{_cfg.BACKEND_URL}{ref}", headers=media_auth_headers()
                )
                r.raise_for_status()
                return r.content
        bucket = getattr(_cfg, "MINIO_BUCKET", "markai-assets")
        try:
            return await _adl(bucket, ref)
        except Exception:
            async with _httpx.AsyncClient(timeout=30) as c:
                r = await c.get(
                    f"{_cfg.BACKEND_URL}/api/v1/files/{ref}",
                    headers=media_auth_headers(),
                )
                r.raise_for_status()
                return r.content
    except Exception as exc:
        logger.warning("Failed to download product asset %s: %s", ref, exc)
        return None


async def _resolve_pl_variant_bytes(
    light_obj: str | None,
    dark_obj: str | None,
    override: str | None,
    enabled: bool,
) -> tuple[bytes | None, bytes | None]:
    """Return (primary_bytes, dark_bytes) for the vendor logo.

    - With an explicit ``override`` ("light"/"dark") the chosen variant is the
      sole logo (no auto-pick) → dark_bytes is None.
    - Otherwise the renderer auto-picks by background: pass light as primary and
      dark as the alternate (only when BOTH exist). A single version is always
      used as the primary.
    """
    if not enabled:
        return None, None
    if override == "dark" and dark_obj:
        return await _download_product_asset(dark_obj), None
    if override == "light" and light_obj:
        return await _download_product_asset(light_obj), None
    light = await _download_product_asset(light_obj) if light_obj else None
    dark = await _download_product_asset(dark_obj) if dark_obj else None
    primary = light or dark
    alt = dark if (light and dark) else None
    return primary, alt


async def _handle_image_regeneration(payload: dict[str, Any]) -> None:
    """Regenerate the image for an existing content piece.

    Full pipeline: generate new base image → apply branding (logo + text overlay)
    → generate mockups → update content record and calendar item status.
    """
    import base64 as _b64
    import json as _json

    import httpx as _httpx

    from shared.llm import generate_image
    from shared.tools.storage import async_upload_file, async_ensure_bucket, async_download_file
    from shared.image_processing import (
        overlay_logo_and_text,
        generate_mockup,
        render_logo_png,
        analyze_logo_region_brightness,
        select_logo_variant,
        scale_for_logo_variant,
    )

    content_id = payload.get("content_id", "")
    brand_id = payload.get("brand_id", "")
    calendar_item_id = payload.get("calendar_item_id", "")
    custom_prompt = payload.get("custom_prompt")
    # "lifestyle" (real-looking generated scene, default) | "ad" (clean studio
    # product advertisement). Drives the base scene prompt below.
    image_format = (payload.get("image_format") or "lifestyle").lower()
    # AI-chosen headline placement (set below for "ad" posts; None = default).
    ad_text_xy: tuple[float, float] | None = None
    ad_text_scale: float = 1.0
    ad_text_width: float | None = None
    ad_headline_colors: dict | None = None
    ad_font_family: str | None = None
    ad_logo_xy: tuple[float, float] | None = None

    logger.info(
        "Regenerating image for content %s (brand %s, format=%s)",
        content_id, brand_id, image_format,
    )

    # ── Claim the item ('working') ──────────────────────────────────────
    # The backend endpoint now flips to 'working' synchronously before
    # publishing (so the client's poll can't race the render), making this a
    # no-op for current messages — kept, idempotent, for messages published
    # by older backends. The matching release lives in the finally below.
    # Clearing regen_error here means a stale error from a PREVIOUS attempt
    # can never masquerade as this attempt's outcome in the UI.
    await execute_update(
        "UPDATE calendar_items SET status = 'working', "
        "generation_metadata = COALESCE(generation_metadata, '{}'::jsonb) "
        "|| '{\"regen_error\": null}'::jsonb "
        "WHERE id = :id",
        {"id": calendar_item_id},
    )

    try:
        # Get the content record for context
        content_rows = await execute_query(
            "SELECT headline, caption, generation_metadata FROM content WHERE id = :id",
            {"id": content_id},
        )
        if not content_rows:
            # The finally below still releases the 'working' claim — this
            # early return used to strand the item in 'working' forever.
            logger.error("Content %s not found for image regeneration", content_id)
            return

        content_row = content_rows[0]
        headline = content_row.get("headline", "")
        caption = content_row.get("caption", "")
        gen_meta = content_row.get("generation_metadata") or {}
        if isinstance(gen_meta, str):
            try:
                gen_meta = _json.loads(gen_meta)
            except Exception:
                gen_meta = {}
        hook = gen_meta.get("hook", headline)

        # Get brand data for branding overlay
        brand_rows = await execute_query(
            "SELECT name, slug, website_url, brand_guidelines, color_palette FROM brands WHERE id = :id",
            {"id": brand_id},
        )
        brand = brand_rows[0] if brand_rows else {}
        brand_name = brand.get("name", "")
        website = brand.get("website_url", "")

        # Parse brand guidelines
        brand_guidelines = brand.get("brand_guidelines") or {}
        if isinstance(brand_guidelines, str):
            try:
                brand_guidelines = _json.loads(brand_guidelines)
            except (ValueError, TypeError):
                brand_guidelines = {}

        # Brand colors for headline emphasis (palette column wins over legacy).
        _palette = brand.get("color_palette") or {}
        if isinstance(_palette, str):
            try:
                _palette = _json.loads(_palette)
            except (ValueError, TypeError):
                _palette = {}
        brand_colors = {**(brand_guidelines.get("colors") or {}), **_palette}

        # ── 0. Source product image (preserve product context across regen) ──
        # Look up the calendar item to find associated product, then fetch its
        # gallery image. If found, the new background is generated with a generic
        # product placeholder and Gemini swaps the real product back in.
        product_image_url: str | None = None
        product_name = ""
        # The swap's guard allow-lists the vendor's own wordmark, so a
        # faithful pack is not reported as invented copy. Regen resolved the
        # vendor for the logo overlay but never passed it to the swap.
        product_vendor = ""
        cal_channel = ""
        # Resolve the vendor (manufacturer) logo from the product's vendor_name
        # so posts generated BEFORE the vendor-logo feature pick it up on regen,
        # even though their generation_metadata has no product_logo_image yet.
        resolved_vendor_logo: str | None = None
        resolved_vendor_logo_dark: str | None = None
        resolved_product_logo_xy: tuple[float, float] | None = None
        cal_rows = await execute_query(
            "SELECT product_ids, title, channel FROM calendar_items WHERE id = :id",
            {"id": calendar_item_id},
        )
        if cal_rows:
            cal_row = cal_rows[0]
            product_ids = cal_row.get("product_ids") or []
            product_name = cal_row.get("title", "")
            cal_channel = (cal_row.get("channel", "") or "").lower()

            product_rows = []
            if product_ids:
                pid = product_ids[0] if isinstance(product_ids, list) else product_ids
                product_rows = await execute_query(
                    "SELECT id, name, image_urls, primary_image_url, vendor_name, category FROM products "
                    "WHERE id = :pid AND is_active = true LIMIT 1",
                    {"pid": str(pid)},
                )

            if product_rows:
                product = product_rows[0]
                if not product_name:
                    product_name = product.get("name", "")
                _vendor = (product.get("vendor_name") or "").strip()
                product_vendor = _vendor
                if _vendor:
                    _vlogos = brand_guidelines.get("vendor_logos", {})
                    _ventry = _vlogos.get(_vendor) if isinstance(_vlogos, dict) else None
                    if isinstance(_ventry, dict):
                        # Normalize light/dark variants (legacy flat → light).
                        if _ventry.get("object_name"):
                            resolved_vendor_logo = _ventry["object_name"]
                        else:
                            _l = _ventry.get("light")
                            _d = _ventry.get("dark")
                            if isinstance(_l, dict):
                                resolved_vendor_logo = _l.get("object_name")
                            if isinstance(_d, dict):
                                resolved_vendor_logo_dark = _d.get("object_name")
                        # Always show *a* logo even with a single version.
                        resolved_vendor_logo = resolved_vendor_logo or resolved_vendor_logo_dark
                        if resolved_vendor_logo or resolved_vendor_logo_dark:
                            logger.info(
                                "Regen: resolved vendor logo for '%s' (vendor=%s)",
                                product_name, _vendor,
                            )
                # Fallback to the product's category logo when the vendor has none
                # (e.g. wearables with a blank/blocked vendor).
                _category = (product.get("category") or "").strip()
                if not resolved_vendor_logo and not resolved_vendor_logo_dark and _category:
                    _clogos = brand_guidelines.get("category_logos", {})
                    _centry = _clogos.get(_category) if isinstance(_clogos, dict) else None
                    if isinstance(_centry, dict):
                        if _centry.get("object_name"):
                            resolved_vendor_logo = _centry["object_name"]
                        else:
                            _cl = _centry.get("light")
                            _cd = _centry.get("dark")
                            if isinstance(_cl, dict):
                                resolved_vendor_logo = _cl.get("object_name")
                            if isinstance(_cd, dict):
                                resolved_vendor_logo_dark = _cd.get("object_name")
                        resolved_vendor_logo = resolved_vendor_logo or resolved_vendor_logo_dark
                        if resolved_vendor_logo or resolved_vendor_logo_dark:
                            logger.info(
                                "Regen: resolved category logo for '%s' (category=%s)",
                                product_name, _category,
                            )
                gallery = product.get("image_urls")
                primary = product.get("primary_image_url")
                if not primary and isinstance(gallery, list) and gallery:
                    first = gallery[0]
                    if isinstance(first, dict):
                        primary = first.get("url")
                    elif isinstance(first, str):
                        primary = first
                if primary:
                    product_image_url = primary
                    logger.info(
                        "Regen: using gallery image for product '%s'", product_name
                    )

        # ── 1. Generate new base image ─────────────────────────────────
        from shared.sanitize import sanitize_for_prompt

        composition_rules = (
            "IMPORTANT COMPOSITION: The top-right area of the image must be open sky, "
            "soft blurred background, or a monotone surface — reserved for a logo overlay. "
            "The bottom-left area should have darker or open space for text overlay. "
        )
        no_text_rule = (
            "CRITICAL: ABSOLUTELY NO TEXT, WORDS, LETTERS, NUMBERS, LOGOS, WATERMARKS, "
            "LABELS, SIGNS, or TYPOGRAPHY of any kind. This is a photograph, not a graphic."
        )

        if custom_prompt:
            # Short user briefs (< SHORT_BRIEF_WORD_LIMIT words) get expanded by
            # the art-director LLM. Long briefs are kept as-is — the user knows
            # what they want.
            from shared.prompt_enhancer import (
                enhance_image_prompt as enhance_image_prompt_fn,
                is_short_brief,
            )

            if is_short_brief(custom_prompt):
                enhanced = await enhance_image_prompt_fn(
                    brief=custom_prompt,
                    brand_name=brand_name,
                    product_name=product_name,
                    channel=cal_channel,
                    has_product_image=bool(product_image_url),
                    is_lifestyle_only=not product_image_url,
                )
                if enhanced:
                    base_prompt = sanitize_for_prompt(enhanced, max_length=4000)
                    logger.info(
                        "Regen: enhanced custom prompt (%d → %d words)",
                        len(custom_prompt.split()),
                        len(enhanced.split()),
                    )
                else:
                    base_prompt = sanitize_for_prompt(custom_prompt, max_length=500)
            else:
                base_prompt = sanitize_for_prompt(custom_prompt, max_length=4000)
        elif image_format == "ad":
            base_prompt = (
                f"Create a clean, professional PRODUCT ADVERTISEMENT image in a studio "
                f"commercial style. Tagline concept: {sanitize_for_prompt(headline)}. "
                f"Premium minimal background: a smooth gradient or subtle textured surface "
                f"(brushed metal, soft seamless studio backdrop, or a clean colour wash), "
                f"even commercial lighting, strong product focus and lots of negative space "
                f"for a short tagline and brand logos."
            )
        else:
            base_prompt = (
                f"Create a professional social media lifestyle image. "
                f"Theme: {sanitize_for_prompt(headline)}. "
                f"Context: {sanitize_for_prompt(caption[:200])}. "
                f"Clean modern aesthetic. Golden hour lighting."
            )

        if product_image_url:
            # Scene with generic product placeholder — Gemini will replace it later
            image_prompt = (
                f"{base_prompt} "
                f"Include a simple generic unlabeled product container "
                f"(plain matte box or pouch with NO writing on it) placed naturally in the scene. "
                f"The product container must be completely blank — it will be digitally replaced. "
                f"The product container MUST be FULLY visible within the frame, positioned in the "
                f"central area with clear margin from every edge — never cropped, never touching or "
                f"running off the edges of the image. "
                f"{composition_rules}"
                f"{no_text_rule}"
            )
        else:
            image_prompt = (
                f"{base_prompt} "
                f"{composition_rules}"
                f"{no_text_rule} "
                f"Do NOT include any products. Focus on the lifestyle and mood."
            )

        # Match aspect ratio to the channel so the post/preview doesn't crop.
        if cal_channel in {"facebook", "linkedin", "youtube"}:
            image_size = "1792x1024"
        elif cal_channel in {"tiktok"}:
            image_size = "1024x1792"
        else:
            image_size = "1024x1024"

        # The prompt above already forbids all lettering (no_text_rule), so the
        # guard's default "no text is legitimate" is the right rule here; the
        # real product packaging is composited in afterwards.
        image_url = await generate_image(
            image_prompt,
            size=image_size,
            channel=cal_channel,
            guard_label=f"regen:{cal_channel or 'default'}:{image_format}",
        )
        logger.info(
            "Image generated for content %s (channel=%s, size=%s): %s chars",
            content_id, cal_channel or "default", image_size, len(image_url),
        )

        await async_ensure_bucket("content-images")

        if image_url.startswith("data:"):
            _, b64_part = image_url.split(",", 1)
            image_data = _b64.b64decode(b64_part)
        else:
            async with _httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                image_data = resp.content

        # ── 1b. Replace generic placeholder with real product via Gemini ──
        if product_image_url:
            # Pack owner comes from the item name itself, never from
            # products.vendor_name — the vendor is a supplier and supplier
            # names stay out of prompts (shared.suppliers).
            from shared.suppliers import pack_owner as _pack_owner

            image_data = await _replace_product_in_image(
                image_data, product_image_url, product_name,
                _pack_owner(product_name),
            )

        raw_obj = f"{brand_id}/{calendar_item_id}/background.png"
        await async_upload_file("content-images", raw_obj, image_data, "image/png")
        raw_url = f"content-images/{raw_obj}"

        # ── 2. Apply branding (logo + text overlay) ────────────────────
        branded_url = raw_url  # fallback if branding fails
        chosen_label = ""      # set when a logo variant is picked below

        logos_cfg = brand_guidelines.get("logos", {})
        from shared.config import settings as _settings
        api_base = getattr(_settings, "BACKEND_URL", "") or "http://backend:8000"

        available_logos: dict[str, str] = {}
        for label, info in logos_cfg.items():
            if isinstance(info, dict):
                url = info.get("url", "")
                if url and url.startswith("/"):
                    url = f"{api_base}{url}"
                if url:
                    available_logos[label] = url

        if available_logos:
            try:
                # Analyze brightness to pick best logo variant
                from PIL import Image as _PILImage
                from io import BytesIO as _BytesIO
                _tmp = _PILImage.open(_BytesIO(image_data))
                approx_w = int(_tmp.width * 0.18)
                approx_h = int(approx_w * 0.5)
                _tmp.close()

                brightness, variance = analyze_logo_region_brightness(
                    image_data, approx_w, approx_h
                )
                chosen_label = select_logo_variant(
                    brightness, variance, list(available_logos.keys())
                )

                # Download and convert logo
                logo_png = None
                for try_label in [chosen_label] + [l for l in available_logos if l != chosen_label]:
                    try:
                        from shared.config import media_auth_headers as _mah

                        logo_url = available_logos[try_label]
                        async with _httpx.AsyncClient(timeout=30) as client:
                            resp = await client.get(
                                logo_url,
                                # Backend media GETs need the token; never
                                # send it to an external logo host.
                                headers=(
                                    _mah()
                                    if logo_url.startswith(api_base)
                                    else None
                                ),
                            )
                            resp.raise_for_status()
                            logo_raw = resp.content
                        is_svg = logo_raw[:5] == b"<?xml" or logo_raw[:4] == b"<svg" or b"<svg" in logo_raw[:500]
                        logo_png = render_logo_png(logo_raw) if is_svg else logo_raw
                        if logo_png:
                            break
                    except Exception:
                        continue

                if logo_png:
                    text_line1 = hook or headline
                    text_line2 = f"{brand_name}" + (f" — {website}" if website else "")
                    # For ad/headline posts, let the AI pick a good spot + size +
                    # width + colors + font for the big title (clean negative
                    # space, off the product). Vision first, variance fallback.
                    _product_box = None
                    if image_format == "ad":
                        from shared.placement import plan_headline_placement
                        try:
                            (ad_text_xy, ad_text_scale, ad_text_width,
                             ad_headline_colors, ad_font_family, ad_logo_xy,
                             _product_box) = (
                                await plan_headline_placement(
                                    image_data, text_line1, brand_colors
                                )
                            )
                        except Exception as exc:
                            logger.warning("Headline placement failed, using default: %s", exc)
                        # Regen used to trust the planner's logo spot unread.
                        # Gate it like the first render does: never on the
                        # text block, never on the product.
                        try:
                            from io import BytesIO as _BytesIO

                            from PIL import Image as _PILImage

                            from shared.image_processing import (
                                choose_logo_placement as _choose,
                                compute_text_region as _text_region,
                                logo_ink_rgb as _ink_of,
                            )
                            from shared.placement import DEFAULT_PRODUCT_BOX

                            with _PILImage.open(_BytesIO(image_data)) as _im:
                                _iw, _ih = _im.width, _im.height
                            with _PILImage.open(_BytesIO(logo_png)) as _lg:
                                _lg = _lg.convert("RGBA")
                                _lb = _lg.getbbox()
                                if _lb:
                                    _lg = _lg.crop(_lb)
                                _lw = max(1, int(_iw * scale_for_logo_variant(chosen_label)))
                                _lh = max(1, int(_lg.height * (_lw / _lg.width))) if _lg.width else 1
                                _lg_ink = _ink_of(_lg)
                            _pb = _product_box or DEFAULT_PRODUCT_BOX
                            _reserved = _text_region(
                                _iw, _ih, text_line1, "headline",
                                ad_text_scale, None, ad_text_xy,
                                ad_text_width, ad_font_family or "Montserrat",
                            )
                            ad_logo_xy, _gate = _choose(
                                image_data, _lw, _lh, _lg_ink,
                                proposed_xy=ad_logo_xy or (0.85, 0.12),
                                avoid_rect=_reserved,
                                avoid_rects=[(
                                    int(_pb[0] * _iw), int(_pb[1] * _ih),
                                    int(_pb[2] * _iw), int(_pb[3] * _ih),
                                )],
                            )
                            if _gate.get("changed"):
                                logger.info("regen branding: %s", _gate.get("reason"))
                        except Exception as exc:
                            logger.warning("regen logo gate failed: %s", exc)
                    # User's manual choices win; otherwise use the AI's (first render).
                    headline_font = gen_meta.get("font_family") or ad_font_family or "Montserrat"
                    effective_colors = gen_meta.get("headline_colors") or ad_headline_colors
                    # Product (manufacturer) logo — keep it across regenerations,
                    # falling back to the vendor logo for older posts that have
                    # none stored yet.
                    _pl_vars = gen_meta.get("product_logo_variants") or {}
                    _pl_light_obj = (
                        _pl_vars.get("light")
                        or gen_meta.get("product_logo_image")
                        or resolved_vendor_logo
                    )
                    _pl_dark_obj = _pl_vars.get("dark") or resolved_vendor_logo_dark
                    _pl_on = bool(_pl_light_obj or _pl_dark_obj) and (
                        gen_meta.get("product_logo_enabled") is not False
                    )
                    _pl_bytes, _pl_dark_bytes = await _resolve_pl_variant_bytes(
                        _pl_light_obj, _pl_dark_obj,
                        gen_meta.get("product_logo_variant"), _pl_on,
                    )
                    _pl_xy = gen_meta.get("product_logo_xy")
                    # Keep the vendor logo clear of the headline (opposite
                    # vertical half) and the brand logo (opposite side) when the
                    # user hasn't placed it — avoids it landing on the title.
                    if image_format == "ad" and _pl_bytes and not _pl_xy:
                        _hy = ad_text_xy[1] if ad_text_xy else 0.2
                        _bx = (ad_logo_xy or (0.85, 0.85))[0]
                        _pl_xy = (
                            0.16 if _bx >= 0.5 else 0.84,
                            0.90 if _hy < 0.5 else 0.12,
                        )
                    resolved_product_logo_xy = tuple(_pl_xy) if _pl_xy else None
                    branded_bytes = overlay_logo_and_text(
                        image_data, logo_png,
                        text_line1=text_line1, text_line2=text_line2,
                        logo_scale=scale_for_logo_variant(chosen_label),
                        text_style=("headline" if image_format == "ad" else "glass"),
                        text_xy=ad_text_xy,
                        text_scale=ad_text_scale,
                        # Logo placed clear of the headline (ad only); else heuristic.
                        logo_xy=(ad_logo_xy if image_format == "ad" else None),
                        font_family=headline_font,
                        headline_colors=effective_colors,
                        text_width=(
                            ad_text_width
                            if ad_text_width is not None
                            else gen_meta.get("text_width")
                        ),
                        product_logo_data=_pl_bytes,
                        product_logo_dark_data=_pl_dark_bytes,
                        product_logo_xy=tuple(_pl_xy) if _pl_xy else None,
                        product_logo_scale=gen_meta.get("product_logo_scale"),
                    )
                    branded_obj = f"{brand_id}/{calendar_item_id}/branded.png"
                    await async_upload_file("content-images", branded_obj, branded_bytes, "image/png")
                    branded_url = f"content-images/{branded_obj}"
                    logger.info("Branding applied for content %s", content_id)
            except Exception as exc:
                logger.warning("Branding overlay failed during regeneration: %s", exc)

        # ── 3. Generate mockups ────────────────────────────────────────
        # Derive brand handle
        channels_cfg = brand_guidelines.get("channels", {})
        social_links = brand_guidelines.get("social_links", {})
        brand_handle = ""
        ig_link = social_links.get("instagram", "")
        if ig_link:
            brand_handle = ig_link.rstrip("/").rsplit("/", 1)[-1]
        if not brand_handle:
            ig_channel = channels_cfg.get("instagram", {})
            if isinstance(ig_channel, dict):
                ig_handle = ig_channel.get("handle", "")
                if ig_handle:
                    brand_handle = ig_handle.lstrip("@")
        if not brand_handle:
            brand_handle = brand.get("slug", brand_name.lower().replace(" ", ""))

        # Load avatar logo
        avatar_logo_data = None
        for avatar_label in ["watermark", "icon", "secondary", "primary"]:
            logo_info = logos_cfg.get(avatar_label)
            if isinstance(logo_info, dict) and logo_info.get("url"):
                try:
                    from shared.config import media_auth_headers as _mah

                    _logo_url = logo_info["url"]
                    if _logo_url.startswith("/"):
                        _logo_url = f"{api_base}{_logo_url}"
                    async with _httpx.AsyncClient(timeout=30) as client:
                        resp = await client.get(
                            _logo_url,
                            headers=(
                                _mah()
                                if _logo_url.startswith(api_base)
                                else None
                            ),
                        )
                        resp.raise_for_status()
                        _raw = resp.content
                    is_svg = _raw[:5] == b"<?xml" or _raw[:4] == b"<svg" or b"<svg" in _raw[:500]
                    avatar_logo_data = render_logo_png(_raw) if is_svg else _raw
                    if avatar_logo_data:
                        break
                except Exception:
                    pass
            avatar_logo_data = None

        # Read branded image bytes for mockups
        if branded_url.startswith("content-images/"):
            mockup_image_data = await async_download_file(
                "content-images", branded_url.replace("content-images/", "")
            )
        else:
            mockup_image_data = image_data

        mockup_platforms = ["instagram", "facebook", "linkedin", "x"]
        enabled = [ch for ch, cfg in channels_cfg.items()
                   if isinstance(cfg, dict) and cfg.get("enabled") and ch in mockup_platforms]
        if not enabled:
            enabled = mockup_platforms

        mockup_urls = {}
        brand_initial = brand_name[0].upper() if brand_name else "H"
        for platform in enabled:
            try:
                mockup_bytes = generate_mockup(
                    mockup_image_data, caption, platform,
                    username=brand_handle, display_name=brand_name,
                    avatar_initial=brand_initial, avatar_logo_data=avatar_logo_data,
                    industry=str(brand_guidelines.get("industry") or ""),
                )
                obj_name = f"{brand_id}/{calendar_item_id}/mockup_{platform}.png"
                await async_upload_file("content-images", obj_name, mockup_bytes, "image/png")
                mockup_urls[platform] = f"content-images/{obj_name}"
            except Exception as exc:
                logger.warning("Mockup generation failed for %s: %s", platform, exc)

        # ── 4. Patch content metadata ──────────────────────────────────
        # Merged server-side (JSONB ||) into whatever generation_metadata
        # holds NOW, not the copy read at the top of this handler — the
        # overlay editor and other paths write their own keys while a regen
        # is in flight, and a full-blob write from that stale read erased
        # them.
        meta_patch: dict[str, Any] = {
            "raw_image": raw_url,
            "generated_image_url": raw_url,
            "branded_image": branded_url,
            # Clean base (no logo/text) for the manual logo/overlay editor —
            # here the overlay was applied onto image_data, which IS raw_url.
            "composed_image": raw_url,
            "logo_variant_used": chosen_label,
            "logo_scale": scale_for_logo_variant(chosen_label),
            # Persist the text style so the logo/overlay editor re-renders the
            # same look (ad = big headline, lifestyle = glass card) when the
            # user fine-tunes.
            "text_style": "headline" if image_format == "ad" else "glass",
            "font_family": (
                gen_meta.get("font_family") or ad_font_family or "Montserrat"
            ),
        }
        _colors = gen_meta.get("headline_colors") or ad_headline_colors
        if _colors:
            meta_patch["headline_colors"] = _colors
        # Persist the AI-chosen headline placement so the overlay editor opens
        # on the same spot/size/width (the user can still drag/resize from there).
        if ad_text_xy is not None:
            meta_patch["text_xy"] = list(ad_text_xy)
            meta_patch["text_scale"] = float(ad_text_scale)
        if ad_text_width is not None:
            meta_patch["text_width"] = float(ad_text_width)
        if mockup_urls:
            meta_patch["mockup_urls"] = mockup_urls
        # Persist the product/vendor logo (and any prior placement) so the
        # logo/overlay editor can show & adjust it after this regeneration —
        # critical for older posts where it was resolved from the vendor.
        _persist_pl = gen_meta.get("product_logo_image") or resolved_vendor_logo
        # Persist the resolved light/dark variants so the editor + later regens
        # see both versions (older posts only had a single product_logo_image).
        _persist_vars = dict(gen_meta.get("product_logo_variants") or {})
        if resolved_vendor_logo and not _persist_vars.get("light"):
            _persist_vars["light"] = resolved_vendor_logo
        if resolved_vendor_logo_dark and not _persist_vars.get("dark"):
            _persist_vars["dark"] = resolved_vendor_logo_dark
        if _persist_pl:
            meta_patch["product_logo_image"] = _persist_pl
            if _persist_vars:
                meta_patch["product_logo_variants"] = _persist_vars
            _pxy = gen_meta.get("product_logo_xy")
            if _pxy is None and resolved_product_logo_xy is not None:
                _pxy = list(resolved_product_logo_xy)
            if _pxy is not None:
                meta_patch["product_logo_xy"] = _pxy

        await execute_update(
            # CAST(:patch AS jsonb), not :patch::jsonb — see the bind-param
            # note in _release_stuck_calendar_item.
            "UPDATE content SET generation_metadata = "
            "COALESCE(generation_metadata, '{}'::jsonb) || CAST(:patch AS jsonb) "
            "WHERE id = :id",
            {"id": content_id, "patch": _json.dumps(meta_patch, default=str)},
        )

        # (Step 5 — releasing the item back to 'in_review' — lives in the
        # finally below so every exit takes it.)

        # A regen of a REJECTED item re-enters review with its last approval
        # already resolved — without a fresh pending row the item never
        # reappears in the Approvals queue (the backend recreates approvals on
        # its PATCH path, but this write bypasses the API). Idempotent: the
        # common in_review regen still has its pending row and is a no-op.
        try:
            pending = await execute_query(
                "SELECT id FROM approvals WHERE calendar_item_id = :cid "
                "AND status = 'pending' LIMIT 1",
                {"cid": calendar_item_id},
            )
            if not pending:
                reviewers = await execute_query(
                    "SELECT reviewer_id AS id FROM approvals "
                    "WHERE calendar_item_id = :cid "
                    "ORDER BY created_at DESC LIMIT 1",
                    {"cid": calendar_item_id},
                ) or await execute_query(
                    "SELECT id FROM users WHERE role IN ('admin', 'manager') "
                    "AND is_active = true LIMIT 1"
                )
                if reviewers:
                    await execute_update(
                        "INSERT INTO approvals (id, content_id, calendar_item_id, "
                        "reviewer_id, status) VALUES (:id, :content_id, "
                        ":calendar_item_id, :reviewer_id, 'pending')",
                        {
                            "id": str(_uuid.uuid4()),
                            "content_id": content_id,
                            "calendar_item_id": calendar_item_id,
                            "reviewer_id": str(reviewers[0]["id"]),
                        },
                    )
                    logger.info(
                        "Recreated pending approval for regenerated item %s",
                        calendar_item_id,
                    )
        except Exception as appr_exc:
            logger.warning("Approval recreation after regen failed: %s", appr_exc)

        logger.info(
            "Image regeneration complete for content %s — branded at %s",
            content_id, branded_url,
        )

    except Exception as exc:
        logger.exception("Image regeneration failed for content %s: %s", content_id, exc)
        # Record the failure where the detail page reads it — without this
        # the UI's "Image regeneration failed: …" branch can never fire and
        # every failure shows as the generic no-new-image message.
        try:
            await execute_update(
                "UPDATE calendar_items SET generation_metadata = "
                "COALESCE(generation_metadata, '{}'::jsonb) "
                "|| jsonb_build_object('regen_error', CAST(:err AS text)) "
                "WHERE id = :id",
                {"id": calendar_item_id, "err": str(exc)[:300]},
            )
        except Exception as rec_exc:
            logger.warning("Could not record regen_error: %s", rec_exc)
    finally:
        # Success and failure alike end in 'in_review' — but release only OUR
        # 'working' claim (WHERE status = 'working'), so a status somebody
        # else set while we ran (approved, cancelled, …) is not clobbered.
        await execute_update(
            "UPDATE calendar_items SET status = 'in_review' "
            "WHERE id = :id AND status = 'working'",
            {"id": calendar_item_id},
        )


async def _handle_logo_rebrand(payload: dict[str, Any]) -> None:
    """Re-composite the logo + text overlay at manually-edited positions.

    The user dragged/resized the logo and/or the text card in the editor; we
    re-render the branded image from the CLEAN base (``composed_image`` — no
    logo/text) using the supplied normalized positions, so the underlying
    photo is unchanged. Mirrors the branding half of image regeneration.

    Payload: {content_id, brand_id, calendar_item_id, logo_xy:[x,y],
    logo_scale, text_xy:[x,y]|None, text_scale}.
    """
    import json as _json

    import httpx as _httpx

    from shared.tools.storage import async_upload_file, async_ensure_bucket, async_download_file
    from shared.image_processing import (
        overlay_logo_and_text,
        generate_mockup,
        render_logo_png,
        analyze_brightness_at_xy,
        select_logo_variant,
        scale_for_logo_variant,
    )

    content_id = payload.get("content_id", "")
    brand_id = payload.get("brand_id", "")
    calendar_item_id = payload.get("calendar_item_id", "")
    logo_scale = payload.get("logo_scale")
    text_scale = payload.get("text_scale", 1.0)
    text_style = (payload.get("text_style") or "glass").lower()
    if text_style not in ("glass", "solid", "headline", "none"):
        text_style = "glass"
    font_family = payload.get("font_family") or None
    headline_colors = payload.get("headline_colors")
    if not isinstance(headline_colors, dict):
        headline_colors = None

    def _wrap_frac(v):
        try:
            return max(0.3, min(0.98, float(v))) if v is not None else None
        except (TypeError, ValueError):
            return None

    text_width = _wrap_frac(payload.get("text_width"))

    # Product logo manual placement / on-off from the editor.
    product_logo_enabled = payload.get("product_logo_enabled")
    product_logo_scale = payload.get("product_logo_scale")

    def _xy(v):
        if isinstance(v, (list, tuple)) and len(v) == 2:
            try:
                return (
                    max(0.0, min(1.0, float(v[0]))),
                    max(0.0, min(1.0, float(v[1]))),
                )
            except (TypeError, ValueError):
                return None
        return None

    logo_xy = _xy(payload.get("logo_xy"))
    text_xy = _xy(payload.get("text_xy"))
    product_logo_xy = _xy(payload.get("product_logo_xy"))

    logger.info(
        "Logo rebrand for content %s (logo_xy=%s text_xy=%s)",
        content_id, logo_xy, text_xy,
    )

    # The status to restore when done. The API already flipped the item to
    # 'working' before publishing (so the client's poll can't race the fast
    # re-render), and passes the real prior status here. Fall back to a DB
    # read for older messages, and never restore to 'working' (would stick).
    prior_status = payload.get("prior_status") or ""
    if not prior_status:
        prior_rows = await execute_query(
            "SELECT status FROM calendar_items WHERE id = :id", {"id": calendar_item_id}
        )
        prior_status = (prior_rows[0].get("status") if prior_rows else None) or "in_review"
    if prior_status == "working":
        prior_status = "in_review"
    # Ensure 'working' even if the API path didn't set it (idempotent).
    await execute_update(
        "UPDATE calendar_items SET status = 'working' WHERE id = :id",
        {"id": calendar_item_id},
    )

    try:
        content_rows = await execute_query(
            "SELECT headline, caption, generation_metadata FROM content WHERE id = :id",
            {"id": content_id},
        )
        if not content_rows:
            logger.error("Content %s not found for logo rebrand", content_id)
            return
        content_row = content_rows[0]
        headline = content_row.get("headline", "")
        caption = content_row.get("caption", "")
        gen_meta = content_row.get("generation_metadata") or {}
        if isinstance(gen_meta, str):
            try:
                gen_meta = _json.loads(gen_meta)
            except Exception:
                gen_meta = {}
        hook = gen_meta.get("hook", headline)

        # Clean base: composed (no logo/text) → raw fallback.
        base_ref = gen_meta.get("composed_image") or gen_meta.get("raw_image")
        if not base_ref or not str(base_ref).startswith("content-images/"):
            logger.error(
                "No clean base image for content %s — cannot rebrand", content_id
            )
            return
        base_data = await async_download_file(
            "content-images", str(base_ref).replace("content-images/", "")
        )

        brand_rows = await execute_query(
            "SELECT name, slug, website_url, brand_guidelines FROM brands WHERE id = :id",
            {"id": brand_id},
        )
        brand = brand_rows[0] if brand_rows else {}
        brand_name = brand.get("name", "")
        website = brand.get("website_url", "")
        brand_guidelines = brand.get("brand_guidelines") or {}
        if isinstance(brand_guidelines, str):
            try:
                brand_guidelines = _json.loads(brand_guidelines)
            except (ValueError, TypeError):
                brand_guidelines = {}

        # Resolve the vendor logo light/dark variants for this post's product so
        # the editor's manual swap works even on posts generated before variants
        # existed (their gen_meta has no product_logo_variants).
        _rb_vendor_light: str | None = None
        _rb_vendor_dark: str | None = None
        try:
            _cal = await execute_query(
                "SELECT product_ids FROM calendar_items WHERE id = :id",
                {"id": calendar_item_id},
            )
            _pids = (_cal[0].get("product_ids") if _cal else None) or []
            if _pids:
                _pid = _pids[0] if isinstance(_pids, list) else _pids
                _prow = await execute_query(
                    "SELECT vendor_name, category FROM products WHERE id = :pid LIMIT 1",
                    {"pid": str(_pid)},
                )
                _vn = ((_prow[0].get("vendor_name") if _prow else "") or "").strip()
                if _vn:
                    _vl = brand_guidelines.get("vendor_logos", {})
                    _ve = _vl.get(_vn) if isinstance(_vl, dict) else None
                    if isinstance(_ve, dict):
                        if _ve.get("object_name"):  # legacy flat → light
                            _rb_vendor_light = _ve["object_name"]
                        else:
                            if isinstance(_ve.get("light"), dict):
                                _rb_vendor_light = _ve["light"].get("object_name")
                            if isinstance(_ve.get("dark"), dict):
                                _rb_vendor_dark = _ve["dark"].get("object_name")
                # Fallback to the category logo when the vendor has none.
                _cat = ((_prow[0].get("category") if _prow else "") or "").strip()
                if not _rb_vendor_light and not _rb_vendor_dark and _cat:
                    _cl = brand_guidelines.get("category_logos", {})
                    _ce = _cl.get(_cat) if isinstance(_cl, dict) else None
                    if isinstance(_ce, dict):
                        if _ce.get("object_name"):  # legacy flat → light
                            _rb_vendor_light = _ce["object_name"]
                        else:
                            if isinstance(_ce.get("light"), dict):
                                _rb_vendor_light = _ce["light"].get("object_name")
                            if isinstance(_ce.get("dark"), dict):
                                _rb_vendor_dark = _ce["dark"].get("object_name")
        except Exception as exc:
            logger.warning("Rebrand vendor variant resolve failed: %s", exc)

        logos_cfg = brand_guidelines.get("logos", {})
        from shared.config import settings as _settings
        api_base = getattr(_settings, "BACKEND_URL", "") or "http://backend:8000"
        available_logos: dict[str, str] = {}
        for label, info in logos_cfg.items():
            if isinstance(info, dict):
                url = info.get("url", "")
                if url and url.startswith("/"):
                    url = f"{api_base}{url}"
                if url:
                    available_logos[label] = url

        await async_ensure_bucket("content-images")
        branded_url = base_ref  # fallback if branding fails
        chosen_label = gen_meta.get("logo_variant_used") or ""

        if available_logos:
            # Honor the variant explicitly chosen via the editor's reverse
            # button; else keep the one chosen at generation, re-picking for
            # the spot the logo now occupies only if it's gone.
            requested_variant = payload.get("logo_variant") or ""
            chosen_label = (
                requested_variant
                if requested_variant in available_logos
                else (gen_meta.get("logo_variant_used") or "")
            )
            if chosen_label not in available_logos:
                if logo_xy:
                    try:
                        from PIL import Image as _PILImage
                        from io import BytesIO as _BytesIO
                        _img = _PILImage.open(_BytesIO(base_data))
                        _lw = int(_img.width * float(logo_scale or 0.2))
                        _lh = int(_lw * 0.5)
                        _img.close()
                        b_at, v_at = analyze_brightness_at_xy(
                            base_data, logo_xy[0], logo_xy[1], _lw, _lh
                        )
                        chosen_label = select_logo_variant(
                            b_at, v_at, list(available_logos.keys())
                        ) or list(available_logos.keys())[0]
                    except Exception:
                        chosen_label = list(available_logos.keys())[0]
                else:
                    chosen_label = list(available_logos.keys())[0]

            logo_png = None
            for try_label in [chosen_label] + [l for l in available_logos if l != chosen_label]:
                try:
                    from shared.config import media_auth_headers as _mah

                    logo_url = available_logos[try_label]
                    async with _httpx.AsyncClient(timeout=30) as client:
                        resp = await client.get(
                            logo_url,
                            # Backend media GETs need the token; never send
                            # it to an external logo host.
                            headers=(
                                _mah()
                                if logo_url.startswith(api_base)
                                else None
                            ),
                        )
                        resp.raise_for_status()
                        logo_raw = resp.content
                    is_svg = logo_raw[:5] == b"<?xml" or logo_raw[:4] == b"<svg" or b"<svg" in logo_raw[:500]
                    logo_png = render_logo_png(logo_raw) if is_svg else logo_raw
                    if logo_png:
                        chosen_label = try_label
                        break
                except Exception:
                    continue

            if logo_png:
                text_line1 = hook or headline
                text_line2 = f"{brand_name}" + (f" — {website}" if website else "")
                # Product logo: editor value wins; else keep what's stored.
                # Vendor light/dark variants — the editor's manual variant pick
                # (product_logo_variant) overrides the background auto-pick.
                _pl_vars = gen_meta.get("product_logo_variants") or {}
                _pl_light_obj = (
                    _pl_vars.get("light")
                    or gen_meta.get("product_logo_image")
                    or _rb_vendor_light
                )
                _pl_dark_obj = _pl_vars.get("dark") or _rb_vendor_dark
                _pl_override = payload.get("product_logo_variant") or gen_meta.get("product_logo_variant")
                _pl_on = bool(_pl_light_obj or _pl_dark_obj) and (
                    product_logo_enabled
                    if product_logo_enabled is not None
                    else gen_meta.get("product_logo_enabled") is not False
                )
                _pl_bytes, _pl_dark_bytes = await _resolve_pl_variant_bytes(
                    _pl_light_obj, _pl_dark_obj, _pl_override, _pl_on,
                )
                _eff_pl_xy = product_logo_xy if product_logo_xy is not None else _xy(gen_meta.get("product_logo_xy"))
                _eff_pl_scale = (
                    product_logo_scale
                    if product_logo_scale is not None
                    else gen_meta.get("product_logo_scale")
                )
                try:
                    branded_bytes = overlay_logo_and_text(
                        base_data, logo_png,
                        text_line1=text_line1, text_line2=text_line2,
                        logo_scale=(float(logo_scale) if logo_scale else scale_for_logo_variant(chosen_label)),
                        logo_xy=logo_xy,
                        text_xy=text_xy,
                        text_scale=float(text_scale or 1.0),
                        text_style=text_style,
                        # Manual editor: the user dragged the logo there on
                        # purpose, so the automatic clearance/contrast gate
                        # must not second-guess them.
                        enforce_logo_clearance=(logo_xy is None),
                        text_anchor=gen_meta.get("text_anchor_used"),
                        font_family=font_family or gen_meta.get("font_family"),
                        headline_colors=(
                            headline_colors
                            if headline_colors is not None
                            else gen_meta.get("headline_colors")
                        ),
                        text_width=(
                            text_width
                            if text_width is not None
                            else gen_meta.get("text_width")
                        ),
                        product_logo_data=_pl_bytes,
                        product_logo_dark_data=_pl_dark_bytes,
                        product_logo_xy=_eff_pl_xy,
                        product_logo_scale=_eff_pl_scale,
                    )
                    branded_obj = f"{brand_id}/{calendar_item_id}/branded.png"
                    await async_upload_file(
                        "content-images", branded_obj, branded_bytes, "image/png"
                    )
                    branded_url = f"content-images/{branded_obj}"
                    logger.info("Logo rebrand applied for content %s", content_id)
                except Exception as exc:
                    logger.warning("Logo rebrand overlay failed: %s", exc)

        # ── Regenerate social mockups from the new branded image ───────
        mockup_urls: dict[str, str] = {}
        try:
            if branded_url.startswith("content-images/"):
                mockup_base = await async_download_file(
                    "content-images", branded_url.replace("content-images/", "")
                )
            else:
                mockup_base = base_data

            channels_cfg = brand_guidelines.get("channels", {})
            social_links = brand_guidelines.get("social_links", {})
            brand_handle = ""
            ig_link = social_links.get("instagram", "")
            if ig_link:
                brand_handle = ig_link.rstrip("/").rsplit("/", 1)[-1]
            if not brand_handle:
                ig_channel = channels_cfg.get("instagram", {})
                if isinstance(ig_channel, dict) and ig_channel.get("handle"):
                    brand_handle = ig_channel["handle"].lstrip("@")
            if not brand_handle:
                brand_handle = brand.get("slug", brand_name.lower().replace(" ", ""))

            avatar_logo_data = None
            for avatar_label in ["watermark", "icon", "secondary", "primary"]:
                logo_info = logos_cfg.get(avatar_label)
                if isinstance(logo_info, dict) and logo_info.get("url"):
                    try:
                        from shared.config import media_auth_headers as _mah

                        _logo_url = logo_info["url"]
                        if _logo_url.startswith("/"):
                            _logo_url = f"{api_base}{_logo_url}"
                        async with _httpx.AsyncClient(timeout=30) as client:
                            resp = await client.get(
                                _logo_url,
                                headers=(
                                    _mah()
                                    if _logo_url.startswith(api_base)
                                    else None
                                ),
                            )
                            resp.raise_for_status()
                            _raw = resp.content
                        is_svg = _raw[:5] == b"<?xml" or _raw[:4] == b"<svg" or b"<svg" in _raw[:500]
                        avatar_logo_data = render_logo_png(_raw) if is_svg else _raw
                        if avatar_logo_data:
                            break
                    except Exception:
                        pass

            mockup_platforms = ["instagram", "facebook", "linkedin", "x"]
            enabled = [ch for ch, cfg in channels_cfg.items()
                       if isinstance(cfg, dict) and cfg.get("enabled") and ch in mockup_platforms]
            if not enabled:
                enabled = mockup_platforms
            brand_initial = brand_name[0].upper() if brand_name else "H"
            for platform in enabled:
                try:
                    mockup_bytes = generate_mockup(
                        mockup_base, caption, platform,
                        username=brand_handle, display_name=brand_name,
                        avatar_initial=brand_initial, avatar_logo_data=avatar_logo_data,
                        industry=str(brand_guidelines.get("industry") or ""),
                    )
                    obj_name = f"{brand_id}/{calendar_item_id}/mockup_{platform}.png"
                    await async_upload_file("content-images", obj_name, mockup_bytes, "image/png")
                    mockup_urls[platform] = f"content-images/{obj_name}"
                except Exception as exc:
                    logger.warning("Mockup regen failed for %s: %s", platform, exc)
        except Exception as exc:
            logger.warning("Mockup regeneration skipped during rebrand: %s", exc)

        # ── Update content metadata with new branded image + placement ──
        # A PATCH of only the keys this rebrand produced, merged server-side:
        # gen_meta was read at entry, and a full-blob write of that snapshot
        # erases whatever a concurrent writer (image regen, publish pipeline)
        # merged in the meantime — the same lost-update _handle_image_
        # regeneration was cured of.
        _prior_meta = gen_meta if isinstance(gen_meta, dict) else {}
        meta_patch: dict[str, Any] = {
            "branded_image": branded_url,
            "logo_variant_used": chosen_label
            or _prior_meta.get("logo_variant_used"),
            "logo_xy": list(logo_xy) if logo_xy else None,
            "logo_scale": float(logo_scale) if logo_scale else None,
            "text_xy": list(text_xy) if text_xy else None,
            "text_scale": float(text_scale or 1.0),
            "text_style": text_style,
        }
        if font_family or _prior_meta.get("font_family"):
            meta_patch["font_family"] = font_family or _prior_meta.get("font_family")
        # Per-word headline colors: an empty dict explicitly clears them.
        if headline_colors is not None:
            meta_patch["headline_colors"] = headline_colors
        if text_width is not None:
            meta_patch["text_width"] = text_width
        # Product logo placement / on-off / variant from the editor.
        if product_logo_enabled is not None:
            meta_patch["product_logo_enabled"] = bool(product_logo_enabled)
        if product_logo_xy is not None:
            meta_patch["product_logo_xy"] = list(product_logo_xy)
        if product_logo_scale is not None:
            meta_patch["product_logo_scale"] = float(product_logo_scale)
        _pl_variant_choice = payload.get("product_logo_variant")
        if _pl_variant_choice in ("light", "dark"):
            meta_patch["product_logo_variant"] = _pl_variant_choice
        # Persist resolved light/dark objects so later edits keep both variants
        # without re-resolving from the brand (older posts pick these up here).
        _persist_vars = dict(_prior_meta.get("product_logo_variants") or {})
        if _rb_vendor_light and not _persist_vars.get("light"):
            _persist_vars["light"] = _rb_vendor_light
        if _rb_vendor_dark and not _persist_vars.get("dark"):
            _persist_vars["dark"] = _rb_vendor_dark
        if _persist_vars:
            meta_patch["product_logo_variants"] = _persist_vars
        if mockup_urls:
            meta_patch["mockup_urls"] = mockup_urls
        await execute_update(
            "UPDATE content SET generation_metadata = "
            "COALESCE(generation_metadata, '{}'::jsonb) || CAST(:patch AS jsonb) "
            "WHERE id = :id",
            {"id": content_id, "patch": _json.dumps(meta_patch, default=str)},
        )
        logger.info(
            "Logo rebrand complete for content %s — branded at %s",
            content_id, branded_url,
        )
    except Exception as exc:
        logger.exception("Logo rebrand failed for content %s: %s", content_id, exc)
    finally:
        # Restore the prior status so the item is never stuck in 'working' —
        # but only if it still IS 'working': an unconditional restore would
        # clobber a status a reviewer (or another handler) set while this
        # rebrand ran.
        await execute_update(
            "UPDATE calendar_items SET status = :st "
            "WHERE id = :id AND status = 'working'",
            {"id": calendar_item_id, "st": prior_status},
        )


def _resolve_graph(subject: str):
    """Resolve a NATS subject to the appropriate LangGraph graph."""
    prefix = subject.split(".")[0]
    return WORKFLOW_MAP.get(prefix)


# Image fields the content workflow carries in its state. The actual images are
# uploaded to MinIO (URLs live in content.generation_metadata); the base64 copy
# kept here is write-only dead weight that bloated agent_runs.output_payload to
# >100MB and OOM-killed the backend on serialization. We strip it before storing.
_STRIPPED_IMAGE_KEYS = {
    "generated_image",
    "branded_image",
    "composed_image",
    "product_image",
}


def _strip_images(obj: Any) -> Any:
    """Recursively replace base64 image blobs with a small placeholder.

    Targets known image fields and ``data:`` URIs only — long *text* values
    (e.g. strategy/research documents that downstream nodes read back) are left
    untouched, so this is safe for every agent type.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in _STRIPPED_IMAGE_KEYS and isinstance(v, str) and len(v) > 200:
                out[k] = f"[image stripped: {len(v) // 1024} kB]"
            else:
                out[k] = _strip_images(v)
        return out
    if isinstance(obj, list):
        return [_strip_images(x) for x in obj]
    if isinstance(obj, str) and obj.startswith("data:") and len(obj) > 200:
        return f"[image stripped: {len(obj) // 1024} kB]"
    return obj


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

    # ── Special handler: manual logo/overlay re-render (not a workflow) ──
    if subject == "content.rebrand-logo":
        try:
            payload = json.loads(msg.data.decode())
            await _handle_logo_rebrand(payload)
        except Exception as exc:
            logger.exception("Logo rebrand failed: %s", exc)
        await msg.ack()
        return

    # ── Special handler: standalone competitor discovery (no doc/agent_run) ──
    # The "Auto-discover" button: finds competitors via web search + LLM and
    # upserts them, WITHOUT running research or regenerating any document.
    if subject == "research.discover-competitors":
        try:
            payload = json.loads(msg.data.decode())
            from workflows.research.discover_competitors import (
                discover_competitors_standalone,
            )

            brand_id = payload.get("brand_id")
            if brand_id:
                await discover_competitors_standalone(str(brand_id))
            else:
                logger.error("discover-competitors message missing brand_id")
        except Exception as exc:
            logger.exception("Competitor discovery failed: %s", exc)
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
        "planning": {"brand_id", "run_id", "trigger", "params", "scope_weeks", "target_months", "triggered_by", "timestamp"},
        "content": {"brand_id", "run_id", "trigger", "params", "scope_weeks", "calendar_item_id", "chain_depth", "remaining_queue", "triggered_by", "timestamp"},
        "evaluation": {"brand_id", "run_id", "trigger", "params", "content_id", "triggered_by", "timestamp"},
        "product": {"brand_id", "run_id", "trigger", "params", "triggered_by", "timestamp"},
        "adaptation": {"brand_id", "run_id", "trigger", "params", "chain_depth", "triggered_by", "timestamp"},
        "video": {"brand_id", "run_id", "trigger", "params", "calendar_item_id", "quality_tier", "triggered_by", "timestamp"},
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
            # Planning agent inserts items in status='planned' (commit 854a0a7
            # split the lifecycle: planning → 'planned', user/system explicitly
            # transitions to 'queued' before the content factory picks them up).
            # In the activation chain there is no human in the loop, so we
            # transition every 'planned' item for this brand to 'queued' here
            # — otherwise the next query finds zero queued items and the
            # `else` branch re-triggers planning, creating an infinite loop.
            # A batch-continue resume does NOT promote: it exists to finish
            # the queue the dead batch was already walking, and promoting
            # would pull future planned items into generation on the back of
            # an unrelated failure.
            if not payload.get("resume"):
                await execute_update(
                    "UPDATE calendar_items "
                    "SET status = 'queued' "
                    "WHERE brand_id = :brand_id AND status = 'planned'",
                    {"brand_id": brand_id},
                )
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
            elif payload.get("resume"):
                # A batch-continue message (_continue_content_chain) found
                # nothing left to do: the batch is simply finished (or its
                # remnants were failed out/cancelled). Falling through to the
                # replan branch below would turn one dead item into an endless
                # plan → generate → fail cycle — a resume never replans.
                logger.info(
                    "Batch resume for brand %s found no queued items — batch complete",
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
                        "scope_weeks": payload.get("scope_weeks", 1),
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

    # ── Guard: never regenerate a content item that's already past generation ──
    # If a content.generate message is redelivered (e.g. a slow run that exceeded
    # ack_wait during an image-API storm), the calendar item may already be
    # in_review/approved/scheduled/published. Regenerating wastes LLM/image calls
    # and creates duplicate versions — ack and skip instead of looping.
    if agent_type == "content" and payload.get("calendar_item_id"):
        try:
            _existing = await execute_query(
                "SELECT status FROM calendar_items WHERE id = :id",
                {"id": payload["calendar_item_id"]},
            )
            if _existing:
                _item_status = _existing[0].get("status")
                if _item_status in ("in_review", "approved", "scheduled", "published"):
                    logger.info(
                        "Skipping content for item %s — already '%s' (no regeneration)",
                        payload["calendar_item_id"],
                        _item_status,
                    )
                    # A redelivered batch message may be the only carrier of
                    # the remaining_queue (the first delivery died between
                    # generating this item and chaining the next) — re-derive
                    # and keep the batch moving instead of stranding it.
                    await _continue_content_chain(
                        agent_type, payload, f"item already '{_item_status}'"
                    )
                    await msg.ack()
                    return
        except Exception as guard_exc:
            logger.warning(
                "Content already-generated guard failed: %s — proceeding",
                guard_exc,
            )

    # ── Guard: never re-render a reel that's already past generation ──────
    # video.render redelivery is the money-burn path: a redeploy kills the
    # worker mid-render, JetStream redelivers under a fresh delivery, and the
    # GPU renders the same reel again (measured 2026-08-20: two duplicate
    # full renders after the morning's two redeploys). The manual re-render
    # endpoint flips the item to 'queued' BEFORE publishing, so 'queued' is
    # the one status that means "somebody asked for this render". Anything
    # already reviewable is a duplicate; so is an item that carries a current
    # reel without having been re-queued (which also means a redelivery that
    # interrupts a RE-render stays skipped — the old reel is still live, and
    # recovery is one manual click, not seven unpaid-for GPU minutes).
    if agent_type == "video" and payload.get("calendar_item_id"):
        try:
            _vrows = await execute_query(
                "SELECT ci.status, c.video_url FROM calendar_items ci "
                "LEFT JOIN content c "
                "  ON c.calendar_item_id = ci.id AND c.is_current = true "
                "WHERE ci.id = :id",
                {"id": payload["calendar_item_id"]},
            )
            if _vrows:
                _vstatus = _vrows[0].get("status")
                _has_reel = bool(_vrows[0].get("video_url"))
                if _vstatus in (
                    "in_review",
                    "approved",
                    "scheduled",
                    "published",
                ) or (_has_reel and _vstatus != "queued"):
                    logger.info(
                        "Skipping video.render for item %s — status '%s'%s "
                        "(redelivery guard)",
                        payload["calendar_item_id"],
                        _vstatus,
                        " with current reel" if _has_reel else "",
                    )
                    await msg.ack()
                    return
        except Exception as guard_exc:
            logger.warning(
                "Video already-rendered guard failed: %s — proceeding",
                guard_exc,
            )

    # ── Reels take the video pipeline, not the static-image chain ──────
    # The planner deterministically creates item_type='reel' calendar items;
    # running them through the content workflow would pay for a static image
    # nobody ships. Divert the item to video.render (the video worker flips
    # it queued → working → rendering → in_review) and keep the sequential
    # content chain moving over the remaining queue.
    if (
        agent_type == "content"
        and payload.get("calendar_item_id")
        and _consumer is not None
    ):
        try:
            _item_rows = await execute_query(
                "SELECT item_type, status FROM calendar_items WHERE id = :id",
                {"id": payload["calendar_item_id"]},
            )
            if _item_rows and _item_rows[0].get("item_type") == "reel":
                # Divert only an item still waiting its turn. A redelivered
                # batch message re-walks items the first delivery already
                # diverted — re-publishing video.render for those is the
                # duplicate-render path the video guard above exists to stop,
                # so don't create the message in the first place. The chain
                # continuation below still runs either way.
                _reel_status = _item_rows[0].get("status")
                if _reel_status in ("queued", "planned"):
                    await _consumer.js.publish(
                        "video.render",
                        json.dumps(
                            {
                                "brand_id": brand_id,
                                "calendar_item_id": str(
                                    payload["calendar_item_id"]
                                ),
                                "trigger": payload.get("trigger", "event"),
                            }
                        ).encode(),
                    )
                    logger.info(
                        "Diverted reel item %s to video.render",
                        payload["calendar_item_id"],
                    )
                else:
                    logger.info(
                        "Reel item %s already '%s' — not re-diverting; "
                        "continuing the content chain",
                        payload["calendar_item_id"],
                        _reel_status,
                    )
                remaining = payload.get("remaining_queue") or []
                if remaining:
                    next_msg: dict[str, Any] = {
                        "brand_id": brand_id,
                        "calendar_item_id": remaining[0],
                        "trigger": payload.get("trigger", "event"),
                        "chain_depth": payload.get("chain_depth", 0) + 1,
                        "remaining_queue": remaining[1:],
                    }
                    if payload.get("scope_weeks") is not None:
                        next_msg["scope_weeks"] = payload["scope_weeks"]
                    await _consumer.js.publish(
                        "content.generate", json.dumps(next_msg).encode()
                    )
                    logger.info(
                        "Sequential content: queued next item %s (%d remaining) after reel divert",
                        remaining[0],
                        len(remaining) - 1,
                    )
                await msg.ack()
                return
        except Exception as reel_exc:
            logger.warning(
                "Reel divert check failed: %s — proceeding as content", reel_exc
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
                                    "scope_weeks": payload.get("scope_weeks", 1),
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
                                        "scope_weeks": payload.get("scope_weeks", 1),
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
    #
    # Only THAT violation means "already running" — see _is_duplicate_run_error.
    try:
        run_id = await create_agent_run(
            brand_id=brand_id,
            agent_type=agent_type,
            trigger=payload.get("trigger", "manual"),
            input_payload=safe_payload,
        )
    except IntegrityError as ie:
        # Not every IntegrityError is the idempotency index. A message
        # carrying a trigger outside agent_runs_trigger_check also lands
        # here, and treating THAT as "already running" retried a message
        # that could never succeed every 5 minutes, logging a reason that
        # was not true — the render looked blocked by a phantom run.
        if not _is_duplicate_run_error(ie):
            logger.error(
                "Cannot start %s workflow for brand %s — the run row was "
                "rejected: %s",
                agent_type,
                brand_id,
                str(ie)[:400],
            )
            # include_queued: this path dies before the graph claims the item,
            # and the rejection is deterministic — the item must leave the
            # queue or the batch continuation below re-picks it forever.
            await _release_stuck_calendar_item(
                agent_type,
                payload,
                "agent_runs insert rejected",
                include_queued=True,
            )
            await _notify_workflow_failure(
                agent_type,
                brand_id,
                "",
                f"The run could not be recorded: {str(ie)[:300]}",
            )
            await _continue_content_chain(
                agent_type, payload, "run insert rejected"
            )
            await msg.ack()
            return
        if agent_type == "video":
            # A video run for this brand is already in flight. Unlike content
            # there is no remaining_queue chaining to pick this item back up,
            # so ack-dropping would strand the second reel in 'queued' forever
            # — retry later instead (max_deliver bounds the attempts).
            logger.info(
                "Video render for brand %s already running — retrying item %s later",
                brand_id,
                payload.get("calendar_item_id"),
            )
            await msg.nak(delay=300)
            return
        if agent_type == "content" and (
            payload.get("calendar_item_id") or payload.get("remaining_queue")
        ):
            # A content run for this brand is already live and this message
            # carries batch state. "Already running" is transient — the live
            # run continues its own chain, and if it is a zombie the stale-run
            # reaper clears it — so retry like video does rather than dropping
            # the queue. On the FINAL delivery a nak is a discard, so hand the
            # batch to queue re-derivation instead (the item is still 'queued'
            # and will be re-picked once the brand's run lock frees up).
            if _delivery_attempt(msg) >= _MAX_DELIVER:
                logger.warning(
                    "Content run for brand %s still blocked by a running run "
                    "on final delivery — re-deriving the batch",
                    brand_id,
                )
                await _continue_content_chain(
                    agent_type, payload, "duplicate run on final delivery"
                )
                await msg.ack()
                return
            logger.info(
                "Content run for brand %s already running — retrying item %s later",
                brand_id,
                payload.get("calendar_item_id"),
            )
            await msg.nak(delay=300)
            return
        logger.warning(
            "Skipping duplicate %s workflow for brand %s — already running (unique constraint). Detail: %s",
            agent_type,
            brand_id,
            str(ie),
        )
        await msg.ack()
        return

    initial_state["run_id"] = run_id
    # Drain scoping (AG-11): the shutdown release must only ever touch runs
    # THIS worker created — record the id on our in-flight registry entry.
    _register_run_id(run_id)

    logger.info(
        "Dispatching %s workflow for brand %s (run %s)",
        agent_type,
        brand_id,
        run_id,
    )

    # Video gets the provider-cascade budget; everything else the default.
    timeout_s = VIDEO_WORKFLOW_TIMEOUT if agent_type == "video" else WORKFLOW_TIMEOUT

    try:
        config: dict[str, Any] = {}
        if hasattr(graph, "checkpointer") and graph.checkpointer is not None:
            config["configurable"] = {"thread_id": run_id or brand_id}

        result = await asyncio.wait_for(
            graph.ainvoke(initial_state, config=config if config else None),
            timeout=timeout_s,
        )

        # ── HITL safe-stop (P0-01): interrupts come back IN the result ──
        # On langgraph 1.1.3 an interrupt() returns normally with an
        # "__interrupt__" marker — the except GraphInterrupt below never
        # fires. Without this check the run is stamped 'completed' and
        # chained, sending an UNAPPROVED strategy downstream. Record the
        # pause (interrupt payload only — no completed-looking artifacts),
        # notify the reviewers, ack, and never chain.
        interrupts = _extract_interrupts(result)
        if interrupts:
            await _record_paused_run(run_id, agent_type, brand_id, interrupts)
            await msg.ack()
            return

        # Ensure result is JSON-safe before storing (handle UUIDs, datetimes, etc.)
        safe_result = json.loads(json.dumps(result, default=str))
        # Drop base64 image blobs — they live in MinIO, keeping them here bloats
        # agent_runs.output_payload (>100MB) and OOM-kills the API on read.
        safe_result = _strip_images(safe_result)

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

        # ── Notify brand owner when a context report finishes ─────────
        if (
            not workflow_failed
            and brand_id
            and run_id
            and agent_type in ("research", "strategy", "planning")
        ):
            try:
                _DOC_LABEL = {
                    "research": "Research Report",
                    "strategy": "Marketing Strategy",
                    "planning": "Marketing Plan",
                }
                rows = await execute_query(
                    "SELECT name FROM brands WHERE id = :bid",
                    {"bid": brand_id},
                )
                brand_name = (rows[0].get("name") if rows else None) or "a brand"

                # Notify the whole team (admins/managers), not just the owner —
                # brands with no created_by would otherwise notify nobody.
                await notify_admins(
                    notification_type="context_ready",
                    title=f"{_DOC_LABEL[agent_type]} ready — {brand_name}",
                    body=f"{brand_name}: click to review and approve.",
                    reference_type="agent_run",
                    reference_id=str(run_id),
                    roles=("admin", "manager", "editor"),
                )

                # Final "all 4 reports ready" notif when the planning agent
                # finishes — last gate before content generation can run.
                if agent_type == "planning":
                    done = await execute_query(
                        "SELECT DISTINCT agent_type FROM agent_runs "
                        "WHERE brand_id = :bid "
                        "  AND agent_type IN ('research','strategy','planning','content_calendar') "
                        "  AND status = 'completed'",
                        {"bid": brand_id},
                    )
                    done_types = {r["agent_type"] for r in done}
                    if done_types >= {"research", "strategy", "planning", "content_calendar"}:
                        await notify_admins(
                            notification_type="context_all_ready",
                            title=f"All 4 context reports ready — {brand_name}",
                            body=f"{brand_name}: approve them on the brand page to unlock content generation.",
                            reference_type="brand",
                            reference_id=str(brand_id),
                            roles=("admin", "manager", "editor"),
                        )
            except Exception as notif_exc:
                logger.debug("context_ready notification skipped: %s", notif_exc)

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
            _fail_reason = (safe_result or {}).get(
                "error", "workflow reported failed"
            )
            # include_queued: a graph can fail BEFORE claiming the item (the
            # empty-brief validation runs pre-claim), leaving it 'queued' —
            # and the batch continuation below would re-derive, re-pick the
            # SAME item first, and fail again forever. This ack is terminal
            # for the message, so it is terminal for the item too.
            await _release_stuck_calendar_item(
                agent_type, payload, _fail_reason, include_queued=True
            )
            await _notify_workflow_failure(
                agent_type, brand_id, run_id, _fail_reason
            )
            # "Not chaining next stage" must not also mean "strand the rest
            # of the batch" — one bad item, not the whole run of the factory.
            await _continue_content_chain(
                agent_type, payload, "workflow reported failed"
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
        # ── Skip completed report stages on restart ─────────────────────
        # When restarting activation, if the next stage already completed, skip ahead.
        # Context Generation chain: research → strategy → planning (no content).
        ACTIVATION_CHAIN_ORDER = ["research", "strategy", "planning"]
        if (
            next_subject
            and brand_id
            and trigger_type == "activation"
            and _consumer is not None
        ):
            next_agent_type = next_subject.split(".")[0]
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
                                }
                                next_subject = CHAIN_SUBJECTS.get(candidate)
                                skipped = False
                        else:
                            if skipped:
                                logger.info(
                                    "All context generation stages already completed for brand %s — no chaining needed",
                                    brand_id,
                                )
                                next_subject = None
            except Exception as skip_exc:
                logger.warning(
                    "Could not check completed stages for skip logic: %s", skip_exc
                )

        if next_subject and brand_id and _consumer is not None:
            try:
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

        # ── Context Generation complete: mark brand as active ─────
        # When planning finishes during activation and there's no next
        # chain step, context generation is done.
        if (
            not next_subject
            and agent_type == "planning"
            and trigger_type == "activation"
            and brand_id
        ):
            try:
                await execute_update(
                    "UPDATE brands SET status = 'active' WHERE id = :bid",
                    {"bid": brand_id},
                )
                logger.info(
                    "Context Generation complete for brand %s — status set to 'active'",
                    brand_id,
                )
            except Exception as status_exc:
                logger.warning(
                    "Failed to update brand %s status to active: %s",
                    brand_id,
                    status_exc,
                )

    except asyncio.TimeoutError:
        logger.error("Workflow %s timed out for brand %s", agent_type, brand_id)
        if run_id:
            await complete_agent_run(
                run_id,
                status="failed",
                error_message=f"Timed out after {timeout_s}s",
            )
        # include_queued only on the FINAL attempt: a non-final timeout naks
        # and the redelivery can still legitimately claim a 'queued' item,
        # but the final nak is a JetStream discard — leaving the item queued
        # then would hand the batch continuation an infinite re-pick loop.
        await _release_stuck_calendar_item(
            agent_type,
            payload,
            "timeout",
            include_queued=_delivery_attempt(msg) >= _MAX_DELIVER,
        )
        if _delivery_attempt(msg) >= _MAX_DELIVER:
            # JetStream discards after max_deliver attempts — this nak is a
            # goodbye, not a retry, so the timeout just became terminal.
            await _notify_workflow_failure(
                agent_type,
                brand_id,
                run_id,
                f"Timed out after {timeout_s}s on the final delivery attempt",
            )
            await _continue_content_chain(
                agent_type, payload, "timed out on final delivery"
            )
        await msg.nak(delay=60)

    except GraphInterrupt as gi:
        # Dead on langgraph 1.1.3 (interrupts return via "__interrupt__",
        # handled above) — kept as belt-and-suspenders for a version that
        # raises again, routed through the same pause/notify path.
        raw = gi.args[0] if gi.args else []
        interrupts = _extract_interrupts({"__interrupt__": raw}) or [
            {"value": {"reason": str(gi)}, "interrupt_id": None}
        ]
        await _record_paused_run(run_id, agent_type, brand_id, interrupts)
        await msg.ack()

    except Exception as exc:
        logger.exception("Workflow %s failed for brand %s", agent_type, brand_id)
        if run_id:
            await complete_agent_run(run_id, status="failed", error_message=str(exc))
        # include_queued: acked without retry, so terminal — same re-pick
        # loop as the workflow-failed branch if the item never left 'queued'.
        await _release_stuck_calendar_item(
            agent_type, payload, str(exc)[:200], include_queued=True
        )
        await _notify_workflow_failure(agent_type, brand_id, run_id, str(exc)[:400])
        await _continue_content_chain(agent_type, payload, "unhandled workflow error")
        await msg.ack()  # Don't retry indefinitely on code errors


async def _dispatch_message(msg: nats.aio.msg.Msg) -> None:
    """Subscription callback: drain gate + in-flight registry around _handle_message.

    These are push subscriptions — messages arrive by callback, so "stop
    pulling new work" is this gate, not a paused pull loop. Once draining,
    an arriving message is held untouched and nak'd at exit (see
    _deferred_naks for why not immediately).
    """
    if _draining:
        logger.info(
            "draining: no new work — holding %s for the next container",
            msg.subject,
        )
        _deferred_naks.append({"msg": msg, "label": msg.subject, "token": None})
        return
    try:
        payload = json.loads(msg.data.decode())
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}  # _handle_message settles bad payloads itself
    token = next(_in_flight_tokens)
    _in_flight[token] = {
        "msg": msg,
        "subject": msg.subject,
        "agent_type": msg.subject.split(".")[0],
        "payload": payload,
        "started": time.monotonic(),
        # The drain cancels abandoned/over-budget workflows through this
        # handle BEFORE nak'ing their messages — a workflow that kept
        # running could submit a paid render mid-drain, or ack its message
        # concurrently with the exit nak (a double-settle).
        "task": asyncio.current_task(),
    }
    try:
        await _handle_message(msg)
    finally:
        _in_flight.pop(token, None)


async def _video_reached_forge(payload: dict[str, Any]) -> bool:
    """Has this in-flight video run already submitted its render job?

    The only live marker the video pipeline leaves mid-run is
    calendar_items.generation_metadata.video_progress — written by the
    provider poll callbacks (forge:/fal:/veo:*) and the ffmpeg finishing
    passes, and by NOTHING before the first job submission (context, shot
    plan, keyframe never touch it). A non-null stage therefore means a
    render job is (or was) live, and a duplicate render costs more than
    waiting for this one.

    Every uncertain answer is deliberately "wait":
    - A stale stage left by a PREVIOUS reel of this item reads as
      submitted. That run is a re-render, and the redelivery guard skips
      re-render redeliveries anyway (the old reel is still current), so
      handing it back early would strand the run with no upside.
    - No calendar_item_id / DB error → wait the budget like everything
      else; if the budget expires first, the redelivery guard makes the
      redelivery safe.
    """
    item_id = payload.get("calendar_item_id")
    if not item_id:
        return True
    try:
        rows = await execute_query(
            "SELECT generation_metadata #>> '{video_progress,stage}' AS stage "
            "FROM calendar_items WHERE id = :id",
            {"id": item_id},
        )
        return bool(rows and rows[0].get("stage"))
    except Exception as probe_exc:
        logger.warning(
            "draining: video progress probe failed for item %s: %s — waiting",
            item_id,
            probe_exc,
        )
        return True


async def _drain_and_shutdown(consumer: NATSConsumer) -> None:
    """SIGTERM path: no new work → finish in-flight → hand back the rest → exit 0.

    Operators tail these lines during a deploy:
      "draining: no new work …"      — the signal was seen, intake is closed
      "drain complete after Ns"      — every awaited workflow finished
      "drain budget exhausted — nak and exit" — something outlived the
        budget; its message redelivers ~DRAIN_NAK_DELAY_SECONDS after the
        new container subscribes, and the release guards + redelivery
        machinery own recovery of the half-done run.
    """
    global _draining
    _draining = True
    started = time.monotonic()
    logger.info(
        "draining: no new work — %d workflow(s) in flight (budget %ss)",
        len(_in_flight),
        DRAIN_BUDGET_SECONDS,
    )

    # ── Video triage: a reel can legitimately render longer than any sane
    # drain budget, so don't start a wait that cannot end well. A run that
    # has not yet submitted its render job is handed back now — re-running
    # it on the next container repeats no paid work. Once a job IS
    # submitted, waiting is cheaper than a duplicate render, so that run
    # queues with everything else.
    abandoned: set[int] = set()
    # agent_runs ids of every workflow THIS drain cancels — captured before
    # the cancel, because the dispatch finally pops the registry entry. The
    # release UPDATE below is scoped to exactly these ids (AG-11).
    released_run_ids: list[str] = []
    for token, entry in list(_in_flight.items()):
        if entry["agent_type"] != "video":
            continue
        item_id = entry["payload"].get("calendar_item_id")
        if await _video_reached_forge(entry["payload"]):
            logger.info(
                "draining: video render %s already submitted its job — "
                "waiting (a duplicate render costs more than the wait)",
                item_id,
            )
            continue
        logger.info(
            "draining: video render %s has not reached the forge — handing "
            "it back for a prompt re-render on the next container",
            item_id,
        )
        _deferred_naks.append(
            {
                "msg": entry["msg"],
                "label": entry["subject"],
                "token": token,
                "cancelled": True,
            }
        )
        abandoned.add(token)
        if entry.get("run_id"):
            released_run_ids.append(entry["run_id"])
        # Cancel NOW, not at exit: an abandoned pre-forge workflow left
        # running through the wait could submit its render job mid-drain —
        # after the nak decision was made on "has not reached the forge" —
        # and the nak would then buy the duplicate render the triage exists
        # to avoid.
        _task = entry.get("task")
        if _task is not None and not _task.done():
            _task.cancel()

    if abandoned:
        _abandoned_tasks = [
            e["task"]
            for t, e in list(_in_flight.items())
            if t in abandoned and e.get("task") is not None
        ]
        if _abandoned_tasks:
            await asyncio.gather(*_abandoned_tasks, return_exceptions=True)

    # ── Wait out the in-flight workflows, up to the budget ──────────────
    exhausted = False
    while any(t not in abandoned for t in _in_flight):
        if time.monotonic() - started >= DRAIN_BUDGET_SECONDS:
            exhausted = True
            break
        await asyncio.sleep(_DRAIN_POLL_SECONDS)

    if exhausted:
        leftovers = [(t, e) for t, e in _in_flight.items() if t not in abandoned]
        logger.warning(
            "drain budget exhausted — nak and exit: handing back %d "
            "workflow(s); the release guards + redelivery machinery own "
            "the half-done runs",
            len(leftovers),
        )
        # Cancel FIRST and await the cancellations, THEN nak: a workflow
        # finishing in the nak window could otherwise ack the same message
        # the drain is nak'ing (nats-py only flips _ackd after its awaited
        # publish, so both settles can reach the wire).
        for token, entry in leftovers:
            if entry.get("run_id"):
                released_run_ids.append(entry["run_id"])
            _task = entry.get("task")
            if _task is not None and not _task.done():
                _task.cancel()
        _left_tasks = [
            e["task"] for _, e in leftovers if e.get("task") is not None
        ]
        if _left_tasks:
            await asyncio.gather(*_left_tasks, return_exceptions=True)
        for token, entry in leftovers:
            _deferred_naks.append(
                {
                    "msg": entry["msg"],
                    "label": entry["subject"],
                    "token": token,
                    "cancelled": True,
                }
            )
    else:
        logger.info("drain complete after %ds", int(time.monotonic() - started))

    # ── Release the run locks the cancelled workflows left behind ───────
    # A cancelled handler does no failure bookkeeping (CancelledError skips
    # its except branches), so its agent_runs row stays 'running' — and on
    # the NEW container that zombie row makes the redelivered message hit
    # the duplicate-run branch, which ACKS non-video work permanently.
    # Scoped to the run ids registered by THIS worker's cancelled workflows
    # (AG-11): a global WHERE status='running' fails ANOTHER worker's live
    # runs the moment a second worker exists — their successful completion
    # then silently no-ops and the freed dedup lock permits a duplicate
    # (paid) run. A run cancelled before it registered its id is left to
    # the stale-run reaper.
    # One UPDATE per id rather than id = ANY(:ids): binding a Python list
    # through the raw text() helper to an asyncpg uuid[] parameter is
    # unproven in this repo (text() bindings have bitten before), and a
    # drain releases a handful of rows at most — the loop is the provably
    # correct shape. Per-id try/except: one bad row must not strand the rest.
    for _rel_id in released_run_ids:
        try:
            await execute_update(
                "UPDATE agent_runs SET status = 'failed', "
                "error_message = 'abandoned by draining worker (redeploy)', "
                "completed_at = NOW() "
                "WHERE id = :id AND status = 'running'",
                {"id": _rel_id},
            )
        except Exception as rel_exc:
            logger.warning(
                "draining: could not release running agent_runs row %s: %s "
                "— the stale-run reaper owns it",
                _rel_id,
                rel_exc,
            )

    # ── Hand back everything deferred, then close ───────────────────────
    for item in _deferred_naks:
        token = item["token"]
        if (
            token is not None
            and token not in _in_flight
            and not item.get("cancelled")
        ):
            # The workflow settled its own message (acked or nak'd) after
            # we decided to abandon it — nothing left to hand back. A
            # CANCELLED workflow never settles, so its token leaving the
            # registry (the dispatch finally) does not mean settled.
            continue
        try:
            await item["msg"].nak(delay=DRAIN_NAK_DELAY_SECONDS)
            logger.info(
                "draining: nak %s (delay=%ss)",
                item["label"],
                DRAIN_NAK_DELAY_SECONDS,
            )
        except Exception as nak_exc:
            logger.warning(
                "draining: nak of %s failed: %s", item["label"], nak_exc
            )
    _deferred_naks.clear()

    # shutdown() unsubscribes any remaining delivery tasks, then drains the
    # connection so the naks above flush, and releases main() to exit 0.
    # Guarded: a connection mid-reconnect makes nats drain() raise, and an
    # unhandled raise here would kill the drain task and leave main()
    # hanging until docker's SIGKILL with every nak unflushed.
    try:
        await consumer.shutdown()
    except Exception as close_exc:
        logger.warning(
            "draining: consumer shutdown raised (%s) — exiting anyway",
            close_exc,
        )


def _request_drain(consumer: NATSConsumer) -> None:
    """Signal-handler body: start the drain exactly once.

    Repeat signals must not restart the clock or double-hand-back work —
    compose escalates to SIGKILL after stop_grace_period on its own, so
    there is no "force" second stage to implement here.
    """
    global _drain_task
    if _drain_task is not None:
        return
    logger.info("Shutdown signal received — draining")
    _drain_task = asyncio.ensure_future(_drain_and_shutdown(consumer))


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop, on_signal: Callable[[], None]
) -> None:
    """Register *on_signal* for SIGINT/SIGTERM.

    loop.add_signal_handler is the correct integration on the production
    platform (Linux under docker); Windows' event loops raise
    NotImplementedError, so dev boxes fall back to plain signal.signal —
    that handler still runs on the loop thread between bytecodes, which is
    enough for ensure_future to reach the running loop.
    """
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: on_signal())


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

    # ── VIDEO stream (video.render consumer binds to it) ────────────────
    # Normally created by the backend's nats_service on startup; ensured
    # here too (same config) so the worker never crash-loops on a race.
    try:
        await consumer.js.find_stream_name_by_subject("video.>")
        logger.info("Stream %s already exists", VIDEO_STREAM_NAME)
    except Exception:
        await consumer.js.add_stream(
            name=VIDEO_STREAM_NAME,
            subjects=["video.>"],
            retention="limits",
            max_age=86400 * 7,  # 7 days — renders older than a week are dead
        )
        logger.info("Created stream %s", VIDEO_STREAM_NAME)


async def main() -> None:
    """Start the worker, subscribe to all workflow subjects, and wait for shutdown."""
    global _consumer
    consumer = NATSConsumer()
    _consumer = consumer
    loop = asyncio.get_running_loop()

    # ── Graceful shutdown: SIGTERM starts the drain, not an instant close ──
    _install_signal_handlers(loop, lambda: _request_drain(consumer))

    # ── Connect and subscribe ────────────────────────────────────────────
    await consumer.connect()
    await _ensure_stream(consumer)

    for subject, durable, stream, ack_wait in SUBSCRIPTIONS:
        await consumer.subscribe(
            subject=subject,
            durable_name=durable,
            stream=stream,
            handler=_dispatch_message,
            ack_wait=ack_wait,
        )

    logger.info("Worker started — listening on %d subjects", len(SUBSCRIPTIONS))
    await consumer.wait_for_shutdown()
    logger.info("Worker stopped.")


if __name__ == "__main__":
    asyncio.run(main())
