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
    os.environ.get("WORKFLOW_TIMEOUT_SECONDS", "5400")
)  # 90 min default (full-year calendar = 200+ LLM calls)
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


async def _release_stuck_calendar_item(
    agent_type: str, payload: dict[str, Any], reason: str
) -> None:
    """Move a calendar_item out of 'working' when its content workflow fails.

    Without this, an item set to 'working' by content/nodes.py stays stuck
    forever if the graph dies (timeout, exception, internal failure) and
    blocks the UI from showing it correctly.
    """
    if agent_type != "content":
        return
    calendar_item_id = payload.get("calendar_item_id")
    if not calendar_item_id:
        return
    try:
        await execute_update(
            "UPDATE calendar_items "
            "SET status = 'failed', "
            "    generation_metadata = COALESCE(generation_metadata, '{}'::jsonb) "
            "        || jsonb_build_object('last_error', :reason) "
            "WHERE id = :id AND status = 'working'",
            {"id": calendar_item_id, "reason": reason},
        )
        logger.info(
            "Released stuck calendar_item %s (status=working → failed): %s",
            calendar_item_id,
            reason,
        )
    except Exception as rel_exc:
        logger.warning(
            "Failed to release stuck calendar_item %s: %s",
            calendar_item_id,
            rel_exc,
        )


async def _replace_product_in_image(
    image_data: bytes, product_image_url: str, product_name: str
) -> bytes:
    """Use Gemini to swap a generic placeholder with the real product photo.

    Mirrors agents.workflows.content.nodes._replace_product_in_generated_image
    so regeneration preserves the same product across runs.
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
            from shared.config import settings as _cfg
            backend_url = getattr(_cfg, "BACKEND_URL", "http://backend:8000")
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(f"{backend_url}{product_image_url}")
                resp.raise_for_status()
                product_image_data = resp.content
        else:
            from shared.config import settings as _storage_cfg
            from shared.tools.storage import async_download_file as _adl
            default_bucket = getattr(_storage_cfg, "MINIO_BUCKET", "markai-assets")
            try:
                product_image_data = await _adl(default_bucket, product_image_url)
            except Exception:
                backend_url = getattr(_storage_cfg, "BACKEND_URL", "http://backend:8000")
                async with _httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        f"{backend_url}/api/v1/files/{product_image_url}"
                    )
                    resp.raise_for_status()
                    product_image_data = resp.content

        from shared.config import settings as _settings
        if not getattr(_settings, "GEMINI_API_KEY", ""):
            logger.warning("GEMINI_API_KEY not set — skipping product replacement on regen")
            return image_data

        from google import genai
        from google.genai import types as gtypes
        from PIL import Image as PILImage
        from io import BytesIO
        from shared.image_processing import (
            resize_preserve_aspect,
            aspect_hint_for_size,
        )

        gemini_client = genai.Client(api_key=_settings.GEMINI_API_KEY)
        marketing_img = PILImage.open(BytesIO(image_data))
        product_img = PILImage.open(BytesIO(product_image_data))
        input_size = marketing_img.size
        aspect_hint = aspect_hint_for_size(input_size)

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=[
                f"Replace the generic product in Image 1 with the real product from Image 2 "
                f"('{product_name or 'product'}'). Keep everything else exactly the same. "
                f"Match lighting and perspective. "
                f"{aspect_hint}",
                marketing_img,
                product_img,
            ],
            config=gtypes.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                result_data = part.inline_data.data
                result_img = PILImage.open(BytesIO(result_data))
                if result_img.size != input_size:
                    logger.info(
                        "Gemini returned %s, aspect-preserving resize to %s (regen)",
                        result_img.size, input_size,
                    )
                    result_img = resize_preserve_aspect(result_img, input_size)
                    buf = BytesIO()
                    result_img.save(buf, format="PNG", quality=95)
                    result_data = buf.getvalue()
                logger.info("Gemini product replacement successful (regen) for %s", product_name)
                return result_data
    except Exception as exc:
        logger.warning("Gemini product replacement failed on regen: %s — using base image", exc)

    return image_data


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

    logger.info("Regenerating image for content %s (brand %s)", content_id, brand_id)

    # ── Set calendar item status to "working" ──────────────────────────
    await execute_update(
        "UPDATE calendar_items SET status = 'working' WHERE id = :id",
        {"id": calendar_item_id},
    )

    try:
        # Get the content record for context
        content_rows = await execute_query(
            "SELECT headline, caption, generation_metadata FROM content WHERE id = :id",
            {"id": content_id},
        )
        if not content_rows:
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
            "SELECT name, slug, website_url, brand_guidelines FROM brands WHERE id = :id",
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

        # ── 0. Source product image (preserve product context across regen) ──
        # Look up the calendar item to find associated product, then fetch its
        # gallery image. If found, the new background is generated with a generic
        # product placeholder and Gemini swaps the real product back in.
        product_image_url: str | None = None
        product_name = ""
        cal_channel = ""
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
                    "SELECT id, name, image_urls, primary_image_url FROM products "
                    "WHERE id = :pid AND is_active = true LIMIT 1",
                    {"pid": str(pid)},
                )

            if product_rows:
                product = product_rows[0]
                if not product_name:
                    product_name = product.get("name", "")
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

        image_url = await generate_image(image_prompt, size=image_size)
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
            image_data = await _replace_product_in_image(
                image_data, product_image_url, product_name
            )

        raw_obj = f"{brand_id}/{calendar_item_id}/background.png"
        await async_upload_file("content-images", raw_obj, image_data, "image/png")
        raw_url = f"content-images/{raw_obj}"

        # ── 2. Apply branding (logo + text overlay) ────────────────────
        branded_url = raw_url  # fallback if branding fails

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
                        logo_url = available_logos[try_label]
                        async with _httpx.AsyncClient(timeout=30) as client:
                            resp = await client.get(logo_url)
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
                    branded_bytes = overlay_logo_and_text(
                        image_data, logo_png,
                        text_line1=text_line1, text_line2=text_line2,
                        logo_scale=scale_for_logo_variant(chosen_label),
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
                    _logo_url = logo_info["url"]
                    if _logo_url.startswith("/"):
                        _logo_url = f"{api_base}{_logo_url}"
                    async with _httpx.AsyncClient(timeout=30) as client:
                        resp = await client.get(_logo_url)
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
                )
                obj_name = f"{brand_id}/{calendar_item_id}/mockup_{platform}.png"
                await async_upload_file("content-images", obj_name, mockup_bytes, "image/png")
                mockup_urls[platform] = f"content-images/{obj_name}"
            except Exception as exc:
                logger.warning("Mockup generation failed for %s: %s", platform, exc)

        # ── 4. Update content metadata ─────────────────────────────────
        existing_metadata = content_row.get("generation_metadata") or {}
        if isinstance(existing_metadata, str):
            try:
                existing_metadata = _json.loads(existing_metadata)
            except Exception:
                existing_metadata = {}

        existing_metadata["raw_image"] = raw_url
        existing_metadata["generated_image_url"] = raw_url
        existing_metadata["branded_image"] = branded_url
        if mockup_urls:
            existing_metadata["mockup_urls"] = mockup_urls

        await execute_update(
            "UPDATE content SET generation_metadata = :metadata WHERE id = :id",
            {"id": content_id, "metadata": _json.dumps(existing_metadata, default=str)},
        )

        # ── 5. Set calendar item status back to "in_review" ────────────
        await execute_update(
            "UPDATE calendar_items SET status = 'in_review' WHERE id = :id",
            {"id": calendar_item_id},
        )

        logger.info(
            "Image regeneration complete for content %s — branded at %s",
            content_id, branded_url,
        )

    except Exception as exc:
        logger.exception("Image regeneration failed for content %s: %s", content_id, exc)
        # Restore calendar item to in_review so it's not stuck in working
        await execute_update(
            "UPDATE calendar_items SET status = 'in_review' WHERE id = :id",
            {"id": calendar_item_id},
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
            # Planning agent inserts items in status='planned' (commit 854a0a7
            # split the lifecycle: planning → 'planned', user/system explicitly
            # transitions to 'queued' before the content factory picks them up).
            # In the activation chain there is no human in the loop, so we
            # transition every 'planned' item for this brand to 'queued' here
            # — otherwise the next query finds zero queued items and the
            # `else` branch re-triggers planning, creating an infinite loop.
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
    try:
        run_id = await create_agent_run(
            brand_id=brand_id,
            agent_type=agent_type,
            trigger=payload.get("trigger", "manual"),
            input_payload=safe_payload,
        )
    except IntegrityError as ie:
        logger.warning(
            "Skipping duplicate %s workflow for brand %s — already running (unique constraint). Detail: %s",
            agent_type,
            brand_id,
            str(ie),
        )
        await msg.ack()
        return

    initial_state["run_id"] = run_id

    logger.info(
        "Dispatching %s workflow for brand %s (run %s)",
        agent_type,
        brand_id,
        run_id,
    )

    try:
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

        # ── Notify brand owner when a context report finishes ─────────
        if (
            not workflow_failed
            and brand_id
            and run_id
            and agent_type in ("research", "strategy", "planning")
        ):
            try:
                from shared.tools.database import create_notification, execute_query

                _DOC_LABEL = {
                    "research": "Research Report",
                    "strategy": "Marketing Strategy",
                    "planning": "Marketing Plan",
                }
                rows = await execute_query(
                    "SELECT name, created_by FROM brands WHERE id = :bid",
                    {"bid": brand_id},
                )
                if rows and rows[0].get("created_by"):
                    await create_notification(
                        user_id=str(rows[0]["created_by"]),
                        notification_type="context_ready",
                        title=f"{_DOC_LABEL[agent_type]} ready — {rows[0].get('name') or 'your brand'}",
                        body="Click to review and approve.",
                        reference_type="agent_run",
                        reference_id=str(run_id),
                    )

                    # Final "all 4 reports ready" notif when the planning
                    # agent finishes the activation chain — last gate before
                    # the brand can start generating content.
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
                            await create_notification(
                                user_id=str(rows[0]["created_by"]),
                                notification_type="context_all_ready",
                                title=f"All 4 context reports ready — {rows[0].get('name') or 'your brand'}",
                                body="Approve them on the brand page to unlock content generation.",
                                reference_type="brand",
                                reference_id=str(brand_id),
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
            await _release_stuck_calendar_item(
                agent_type,
                payload,
                (safe_result or {}).get("error", "workflow reported failed"),
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
                error_message=f"Timed out after {WORKFLOW_TIMEOUT}s",
            )
        await _release_stuck_calendar_item(agent_type, payload, "timeout")
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
        await _release_stuck_calendar_item(agent_type, payload, str(exc)[:200])
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
