"""Video generation workflow nodes — shot planning, keyframe, render, store.

Reuses the content workflow's context/brief/product-image machinery
(load_context, enrich_user_brief, source_product_image_node) and adds the
video-specific stages: plan_shots (LLM shot list), make_keyframe (branded
product keyframe at 9:16), render_video (shared.video provider chain), and
store_video (MinIO + video_jobs/media_assets/content persistence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any
from uuid import uuid4

from shared.llm import chat_completion, generate_image, parse_llm_json
from shared.sanitize import sanitize_for_prompt
from shared.tools.database import (
    execute_query,
    execute_update,
    store_content,
    update_agent_run_step,
)
from shared.tools.storage import async_download_file, async_upload_file

from workflows.content.nodes import (
    ContentRecordValidator,
    _build_brand_bible_block,
    _build_voice_block,
    _effective_caption_settings,
    _replace_product_in_generated_image,
    enrich_user_brief,
    load_context,
    source_product_image_node,
)
from workflows.content.state import ContentState

logger = logging.getLogger(__name__)

# MinIO bucket for rendered videos: {brand_id}/{calendar_item_id}/final.mp4
VIDEO_BUCKET = "videos"

# Hard limits for a short-form reel render
MAX_TOTAL_DURATION_S = 10.0
MIN_FIRST_SHOT_S = 2.0
MIN_SHOT_S = 0.5
MAX_SHOTS = 6

# Step tracking: maps node key to index for progress reporting
VIDEO_PIPELINE_STEPS = [
    "load_context",
    "enrich_user_brief",
    "source_product_image",
    "plan_shots",
    "make_keyframe",
    "render_video",
    "store_video",
]
_STEP_INDEX = {key: idx for idx, key in enumerate(VIDEO_PIPELINE_STEPS)}


class VideoState(ContentState, total=False):
    """Content state extended with the video pipeline's channels."""

    quality_tier: str
    shot_plan: dict[str, Any]
    video_prompt: str
    keyframe_bytes: bytes | None
    keyframe_object: str | None
    video_bytes: bytes | None
    video_meta: dict[str, Any]
    video_object: str | None
    thumbnail_object: str | None
    video_content_id: str | None


async def _fail(state: VideoState, message: str) -> dict[str, Any]:
    """Mark the run failed: calendar item → 'failed' with the error recorded
    in generation_metadata, plus a failed video_jobs row for traceability.

    Every DB write is best-effort — a failure to record the failure must not
    mask the original error.
    """
    logger.error(message)
    item_id = state.get("calendar_item_id")
    brand_id = state.get("brand_id")
    if item_id:
        try:
            await execute_update(
                "UPDATE calendar_items SET status = 'failed', "
                "generation_metadata = COALESCE(generation_metadata, '{}'::jsonb) || :patch "
                "WHERE id = :id",
                {
                    "id": item_id,
                    "patch": json.dumps({"last_error": message[:500]}),
                },
            )
        except Exception as exc:
            logger.warning("Failed to mark calendar_item %s failed: %s", item_id, exc)
    if item_id and brand_id:
        try:
            meta = state.get("video_meta") or {}
            await execute_update(
                "INSERT INTO video_jobs (id, brand_id, calendar_item_id, provider, model, "
                "mode, prompt, status, error_message, generation_ledger) "
                "VALUES (:id, :brand_id, :calendar_item_id, :provider, :model, "
                ":mode, :prompt, 'failed', :error_message, :ledger)",
                {
                    "id": str(uuid4()),
                    "brand_id": brand_id,
                    "calendar_item_id": item_id,
                    "provider": meta.get("provider") or "video-forge",
                    "model": meta.get("model") or "unknown",
                    "mode": "i2v" if state.get("keyframe_bytes") else "t2v",
                    "prompt": state.get("video_prompt") or "",
                    "error_message": message[:2000],
                    "ledger": json.dumps(meta.get("ledger") or []),
                },
            )
        except Exception as exc:
            logger.warning("Failed to write failed video_jobs row: %s", exc)
    return {
        "status": "failed",
        "errors": [*(state.get("errors") or []), message],
        # Never leave raw media bytes in the final state — the worker
        # serializes it into agent_runs.output_payload.
        "video_bytes": None,
        "keyframe_bytes": None,
    }


async def load_video_context(state: VideoState) -> dict[str, Any]:
    """Load full brand intelligence via the content workflow's load_context,
    then transition the calendar item to 'rendering' (video lifecycle)."""
    out = await load_context(state)
    if out.get("status") == "failed":
        return await _fail(
            state, "; ".join(out.get("errors") or ["load_context failed"])
        )
    # content's load_context sets queued → working; the video pipeline renders.
    await execute_update(
        "UPDATE calendar_items SET status = 'rendering' WHERE id = :id",
        {"id": state["calendar_item_id"]},
    )
    return out


def _normalize_shot_plan(plan: Any) -> dict[str, Any]:
    """Validate and normalize the LLM's shot plan JSON.

    Enforces: non-empty shots with scene text, per-shot duration >= 0.5s,
    first shot >= 2s, total duration <= 10s (proportional scale-down, then
    trailing shots dropped if still over), at most MAX_SHOTS shots, and
    cleaned hashtags (no '#', no spaces).

    Raises ValueError when the plan is unusable.
    """
    if not isinstance(plan, dict):
        raise ValueError("shot plan is not a JSON object")

    raw_shots = plan.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        raise ValueError("shot plan has no shots")

    shots: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_shots[:MAX_SHOTS]):
        if not isinstance(raw, dict):
            continue
        scene = str(raw.get("scene") or "").strip()
        if not scene:
            continue
        try:
            duration = float(raw.get("duration_s", 0))
        except (TypeError, ValueError):
            duration = 0.0
        shots.append(
            {
                "index": i + 1,
                "duration_s": max(MIN_SHOT_S, duration),
                "scene": scene,
            }
        )
    if not shots:
        raise ValueError("shot plan has no usable shots (missing scene text)")

    # First shot carries the hook — never shorter than 2s.
    shots[0]["duration_s"] = max(MIN_FIRST_SHOT_S, shots[0]["duration_s"])

    # Scale down proportionally when over budget, keeping the first-shot floor.
    total = sum(s["duration_s"] for s in shots)
    if total > MAX_TOTAL_DURATION_S:
        factor = MAX_TOTAL_DURATION_S / total
        for s in shots:
            s["duration_s"] = max(MIN_SHOT_S, round(s["duration_s"] * factor, 2))
        shots[0]["duration_s"] = max(MIN_FIRST_SHOT_S, shots[0]["duration_s"])
    # Floors can push the sum back over — drop trailing beats until it fits.
    while len(shots) > 1 and sum(s["duration_s"] for s in shots) > MAX_TOTAL_DURATION_S:
        shots.pop()
    shots[-1]["duration_s"] = min(
        shots[-1]["duration_s"],
        max(
            MIN_SHOT_S,
            MAX_TOTAL_DURATION_S - sum(s["duration_s"] for s in shots[:-1]),
        ),
    )

    hashtags: list[str] = []
    for tag in plan.get("hashtags") or []:
        cleaned = re.sub(r"[^A-Za-z0-9]", "", str(tag).lstrip("#"))
        if cleaned:
            hashtags.append(cleaned)

    return {
        "hook_line": str(plan.get("hook_line") or "").strip(),
        "shots": shots,
        "caption": str(plan.get("caption") or "").strip(),
        "hashtags": hashtags,
        "cta": str(plan.get("cta") or "").strip(),
    }


async def plan_shots(state: VideoState) -> dict[str, Any]:
    """One LLM call producing the strict-JSON shot plan for a 5-10s reel."""
    await update_agent_run_step(
        state.get("run_id", ""),
        "plan_shots",
        _STEP_INDEX["plan_shots"],
        total_steps=len(VIDEO_PIPELINE_STEPS),
    )
    try:
        brand = state.get("brand", {})
        item = state.get("calendar_item", {})
        positioning = state.get("positioning", {})
        relevant_audience = state.get("relevant_audience", {})
        product = state.get("product", {})

        channel = (item.get("channel", "") or "").lower()
        sub_brand = state.get("sub_brand") or brand.get("name", "")
        # Reels are consumer-facing — always the B2C voice.
        voice_block = _build_voice_block("b2c", sub_brand, brand.get("name", ""))
        settings = _effective_caption_settings(brand, channel)
        brand_bible_block = _build_brand_bible_block(brand, settings)
        bible_section = f"{brand_bible_block}\n\n" if brand_bible_block else ""

        brief = (item.get("content_brief") or item.get("description") or "").strip()
        product_section = ""
        if product.get("name"):
            product_section = (
                f"PRODUCT (the hero of this video):\n"
                f"  Name: {sanitize_for_prompt(product.get('name', ''))}\n"
                f"  Description: {sanitize_for_prompt(product.get('description', ''))}\n\n"
            )

        system = (
            f"{voice_block}\n\n"
            f"{bible_section}"
            "You are a short-form video director planning a 5-10 second "
            "vertical (9:16) product reel that will be generated by an AI "
            "video model from your shot list.\n\n"
            "SHORT-FORM DISCIPLINE (non-negotiable):\n"
            "- The product is VISIBLE and actively solving something within "
            "seconds 0-2. No slow establishing shots.\n"
            "- One clear visual change every ~1.5-2 seconds — each shot is "
            "exactly one beat.\n"
            "- The final shot resolves back toward the opening composition "
            "so the clip loops cleanly.\n"
            "- NEVER request on-screen text, captions, subtitles, prices, or "
            "logos in any scene — text is composited later in post.\n"
            "- Audio is diegetic only: sounds that belong to the scene "
            "(sizzle, pour, clink, ambience). No voiceover, no music cues.\n"
            "- Stay strictly inside the brand voice above; never make claims "
            "the MUST NEVER DO list forbids.\n\n"
            "Each shot's \"scene\" value is a structured prompt with exactly "
            "these labeled sections, one per line:\n"
            "SCENE CONTEXT: where we are and what is happening\n"
            "FIRST FRAME: precise description of the opening frame of this shot\n"
            "CAMERA/OPTICS: framing, movement, lens/depth-of-field\n"
            "LIGHTING: light quality, direction, color temperature\n"
            "AUDIO: the diegetic sound of this shot\n"
            "STYLE: photographic/commercial style anchors\n"
            "LOCKS: what must stay true across the shot (product identity, "
            "palette, setting)\n\n"
            "Return STRICT JSON only, with this exact shape:\n"
            "{\n"
            '  "hook_line": "<scroll-stopping line under 8 words>",\n'
            '  "shots": [\n'
            '    {"index": 1, "duration_s": 2.5, "scene": "SCENE CONTEXT: ...\\nFIRST FRAME: ...\\nCAMERA/OPTICS: ...\\nLIGHTING: ...\\nAUDIO: ...\\nSTYLE: ...\\nLOCKS: ..."}\n'
            "  ],\n"
            '  "caption": "<post caption in the brand voice>",\n'
            '  "hashtags": ["tag1", "tag2"],\n'
            '  "cta": "<short call to action>"\n'
            "}\n\n"
            "Duration rules: durations sum to 10 seconds or less; the first "
            f"shot is at least 2 seconds; use 3 to {MAX_SHOTS} shots.\n"
            f"Caption rules: under {settings['max_words']} words, between "
            f"{settings['hashtags_min']} and {settings['hashtags_max']} hashtags, "
            "no hashtags or URLs inside the caption body."
        )
        user = (
            f"WHAT THIS REEL IS ABOUT (primary intent — never override):\n"
            f"{sanitize_for_prompt(brief) or '(no brief — use the theme below)'}\n\n"
            f"PLATFORM: {sanitize_for_prompt(channel or 'instagram')}\n"
            f"THEME: {sanitize_for_prompt(item.get('theme', ''))}\n\n"
            f"{product_section}"
            f"BRAND VOICE REFERENCE: "
            f"{sanitize_for_prompt(str(positioning.get('brand_voice', '')))}\n"
            f"AUDIENCE: {sanitize_for_prompt(relevant_audience.get('name', ''))}"
        )

        result = await chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            category="text",
            temperature=0.7,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        parsed = parse_llm_json(str(result), fallback=None)
        plan = _normalize_shot_plan(parsed)
        logger.info(
            "Shot plan: %d shots, %.1fs total",
            len(plan["shots"]),
            sum(s["duration_s"] for s in plan["shots"]),
        )
        return {
            "shot_plan": plan,
            "hook": plan["hook_line"],
            "caption": plan["caption"],
            "hashtags": plan["hashtags"],
            "cta": plan["cta"],
        }
    except Exception as exc:
        return await _fail(state, f"plan_shots failed: {exc}")


# Matches a "FIRST FRAME:" section inside a structured shot scene, up to the
# next ALL-CAPS section label or the end of the text.
_FIRST_FRAME_RE = re.compile(
    r"FIRST FRAME:\s*(.+?)(?=\n[A-Z][A-Z/ ]+:|\Z)", re.DOTALL
)


def _extract_first_frame(scene: str) -> str:
    """Pull the FIRST FRAME description out of a structured shot scene."""
    match = _FIRST_FRAME_RE.search(scene or "")
    return match.group(1).strip() if match else ""


async def make_keyframe(state: VideoState) -> dict[str, Any]:
    """Generate the branded 9:16 product keyframe for shot 1's first frame.

    Reuses the content pipeline's image path: generate a portrait scene (with
    a blank placeholder container when a real product photo exists), then swap
    the real product in via Gemini. Degrades gracefully — a missing keyframe
    downgrades the render to t2v instead of failing the run.
    """
    await update_agent_run_step(
        state.get("run_id", ""),
        "make_keyframe",
        _STEP_INDEX["make_keyframe"],
        total_steps=len(VIDEO_PIPELINE_STEPS),
    )
    brand_id = state["brand_id"]
    item_id = state["calendar_item_id"]
    item = state.get("calendar_item", {})
    plan = state.get("shot_plan") or {}
    shots = plan.get("shots") or []
    if not shots:
        return await _fail(state, "make_keyframe: no shot plan available")

    first_scene = str(shots[0].get("scene") or "")
    first_frame = _extract_first_frame(first_scene) or first_scene
    has_product_image = state.get("product_image") is not None
    is_lifestyle_only = state.get("is_lifestyle_only", True)

    no_text_rule = (
        "CRITICAL: ABSOLUTELY NO TEXT, WORDS, LETTERS, NUMBERS, LOGOS, "
        "WATERMARKS, LABELS, SIGNS, or TYPOGRAPHY of any kind. "
        "This is a photograph, not a graphic. "
    )
    if has_product_image and not is_lifestyle_only:
        product_rule = (
            "Include a simple generic unlabeled product container (plain matte "
            "box or pouch with NO writing on it) placed naturally, FULLY "
            "visible within the frame with clear margin from every edge — "
            "never cropped. The container must be completely blank — it will "
            "be digitally replaced later. "
        )
    else:
        product_rule = "Do NOT include any products. Focus on the scene and mood. "

    prompt_text = (
        f"REAL PHOTOGRAPH — Ultra realistic commercial photography, vertical "
        f"9:16 portrait frame, the opening frame of a short product video.\n\n"
        f"SCENE:\n{sanitize_for_prompt(first_frame, max_length=4000)}\n\n"
        f"Brand: {sanitize_for_prompt(state.get('brand', {}).get('name', ''))}. "
        f"{product_rule}"
        f"Real shadows. Authentic textures. Natural depth of field. "
        f"{no_text_rule}"
        f"The image MUST look like a photograph captured with a real camera, "
        f"NOT an artwork, NOT a rendering, NOT an illustration."
    )

    try:
        channel = (item.get("channel", "") or "").lower()
        image_url = await generate_image(
            prompt_text, size="1024x1792", channel=channel or None
        )

        import base64 as _b64
        import httpx

        if image_url.startswith("data:"):
            _, b64_part = image_url.split(",", 1)
            image_data = _b64.b64decode(b64_part)
        elif image_url.startswith("content-images/"):
            image_data = await async_download_file(
                "content-images", image_url.replace("content-images/", "")
            )
        else:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                image_data = resp.content

        # Swap the blank placeholder for the real product photo (no-op when
        # lifestyle-only or no gallery image).
        image_data = await _replace_product_in_generated_image(state, image_data)

        keyframe_object = f"{brand_id}/{item_id}/keyframe.png"
        await async_upload_file(VIDEO_BUCKET, keyframe_object, image_data, "image/png")
        logger.info("Keyframe stored at %s/%s", VIDEO_BUCKET, keyframe_object)
        return {"keyframe_bytes": image_data, "keyframe_object": keyframe_object}
    except Exception as exc:
        logger.warning("make_keyframe failed (%s) — falling back to t2v", exc)
        return {"keyframe_bytes": None, "keyframe_object": None}


def _build_video_prompt(plan: dict[str, Any]) -> str:
    """Join the shot list into one structured multi-beat prompt with explicit
    CUT markers — LTX-2.3 (the FAL_VIDEO_MODEL default) handles multi-beat
    prompts in a single 5-10s clip."""
    header = (
        "Vertical 9:16 short-form product video. Photorealistic commercial "
        "footage, one continuous generation with hard cuts between shots. "
        "Diegetic audio only — no voiceover, no music. No on-screen text, "
        "captions, or logos of any kind. The final shot resolves back toward "
        "the opening composition so the clip loops cleanly."
    )
    parts = [
        f"SHOT {s['index']} ({s['duration_s']:.1f}s):\n{s['scene']}"
        for s in plan.get("shots") or []
    ]
    return header + "\n\n" + "\n\nCUT TO:\n\n".join(parts)


async def render_video(state: VideoState) -> dict[str, Any]:
    """Render the reel through the shared video provider chain (Video Forge
    first), streaming progress into calendar_items.generation_metadata."""
    await update_agent_run_step(
        state.get("run_id", ""),
        "render_video",
        _STEP_INDEX["render_video"],
        total_steps=len(VIDEO_PIPELINE_STEPS),
    )
    item_id = state["calendar_item_id"]
    plan = state.get("shot_plan") or {}
    shots = plan.get("shots") or []
    if not shots:
        return await _fail(state, "render_video: no shot plan available")

    prompt = _build_video_prompt(plan)
    duration_s = min(
        MAX_TOTAL_DURATION_S, sum(float(s.get("duration_s", 0)) for s in shots)
    )
    keyframe = state.get("keyframe_bytes")

    async def _progress(percent: int, stage: str) -> None:
        try:
            await execute_update(
                "UPDATE calendar_items "
                "SET generation_metadata = COALESCE(generation_metadata, '{}'::jsonb) || :patch "
                "WHERE id = :id",
                {
                    "id": item_id,
                    "patch": json.dumps(
                        {"video_progress": {"percent": int(percent), "stage": stage}}
                    ),
                },
            )
        except Exception as exc:
            logger.debug("Video progress update failed: %s", exc)

    try:
        from shared.video import VideoRequest, generate_video

        req = VideoRequest(
            mode="i2v" if keyframe else "t2v",
            prompt=prompt,
            image_bytes=keyframe,
            duration_s=duration_s,
            aspect="9:16",
            audio=True,
            quality_tier=state.get("quality_tier") or "standard",
            idempotency_key=f"{state['brand_id']}:{item_id}:{state.get('run_id', '')}"[
                :128
            ],
        )
        result = await generate_video(req, progress_cb=_progress)
        logger.info(
            "Video rendered: %s/%s %.1fs %dx%d (%d bytes, $%.4f)",
            result.provider,
            result.model,
            result.duration_s,
            result.width,
            result.height,
            len(result.video_bytes),
            result.cost_usd,
        )
        return {
            "video_bytes": result.video_bytes,
            "video_prompt": prompt,
            "video_meta": {
                "provider": result.provider,
                "model": result.model,
                "duration_s": result.duration_s,
                "width": result.width,
                "height": result.height,
                "cost_usd": result.cost_usd,
                "ledger": result.ledger,
                "idempotency_key": req.idempotency_key,
            },
        }
    except Exception as exc:
        # generate_video attaches the accumulated cascade ledger to the
        # exception (exc.ledger) — thread it into video_meta so _fail's
        # video_jobs row records every attempted provider, not [].
        return await _fail(
            {
                **state,
                "video_prompt": prompt,
                "video_meta": {"ledger": getattr(exc, "ledger", [])},
            },
            f"render_video failed: {exc}",
        )


async def _extract_thumbnail(
    video_bytes: bytes, brand_id: str, item_id: str
) -> str | None:
    """Grab a frame at 0.5s via ffmpeg and upload it as thumb.jpg.

    Returns the object name, or None when ffmpeg is unavailable or fails —
    the thumbnail is a nice-to-have, never a reason to fail the run.
    """
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        logger.info("ffmpeg not available — skipping thumbnail extraction")
        return None

    def _run() -> bytes | None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            src = os.path.join(tmp_dir, "final.mp4")
            dst = os.path.join(tmp_dir, "thumb.jpg")
            with open(src, "wb") as fh:
                fh.write(video_bytes)
            proc = subprocess.run(
                ["ffmpeg", "-y", "-ss", "0.5", "-i", src, "-frames:v", "1", dst],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0 or not os.path.exists(dst):
                return None
            with open(dst, "rb") as fh:
                return fh.read()

    try:
        thumb_bytes = await asyncio.to_thread(_run)
    except Exception as exc:
        logger.warning("Thumbnail extraction failed: %s", exc)
        return None
    if not thumb_bytes:
        logger.warning("ffmpeg produced no thumbnail — skipping")
        return None
    thumb_object = f"{brand_id}/{item_id}/thumb.jpg"
    await async_upload_file(VIDEO_BUCKET, thumb_object, thumb_bytes, "image/jpeg")
    return thumb_object


async def store_video(state: VideoState) -> dict[str, Any]:
    """Upload the render to MinIO, persist video_jobs/media_assets/content
    rows, and hand the item to review (same tail as the content workflow)."""
    await update_agent_run_step(
        state.get("run_id", ""),
        "store_video",
        _STEP_INDEX["store_video"],
        total_steps=len(VIDEO_PIPELINE_STEPS),
    )
    brand_id = state["brand_id"]
    item_id = state["calendar_item_id"]
    video_bytes = state.get("video_bytes")
    meta = state.get("video_meta") or {}
    plan = state.get("shot_plan") or {}
    if not video_bytes:
        return await _fail(state, "store_video: no video bytes in state")

    try:
        # ── 1. Upload the master MP4 (+ thumbnail) ─────────────────────────
        video_object = f"{brand_id}/{item_id}/final.mp4"
        await async_upload_file(VIDEO_BUCKET, video_object, video_bytes, "video/mp4")
        thumbnail_object = await _extract_thumbnail(video_bytes, brand_id, item_id)
        video_url = f"{VIDEO_BUCKET}/{video_object}"

        # ── 2. Content row (reuses the content workflow's store helper) ────
        content_record = {
            "brand_id": brand_id,
            "calendar_item_id": item_id,
            "hook": state.get("hook", ""),
            "caption": state.get("caption", ""),
            "hashtags": json.dumps(state.get("hashtags", [])),
            "cta": state.get("cta", ""),
            "product_image_url": state.get("product_image"),
            "generated_image_url": (
                f"{VIDEO_BUCKET}/{state['keyframe_object']}"
                if state.get("keyframe_object")
                else None
            ),
            "platform_adaptations": json.dumps({}),
            "metadata": {
                "video_url": video_url,
                "thumbnail_url": (
                    f"{VIDEO_BUCKET}/{thumbnail_object}" if thumbnail_object else None
                ),
                "keyframe_image": (
                    f"{VIDEO_BUCKET}/{state['keyframe_object']}"
                    if state.get("keyframe_object")
                    else None
                ),
                "shot_plan": plan,
                "video_provider": meta.get("provider"),
                "video_model": meta.get("model"),
                "video_duration_s": meta.get("duration_s"),
                "video_cost_usd": meta.get("cost_usd"),
            },
            "status": "in_review",
        }
        try:
            ContentRecordValidator(**content_record)
        except Exception as ve:
            return await _fail(state, f"store_video: content validation failed: {ve}")

        content_id = await store_content(content_record)
        await execute_update(
            "UPDATE content SET video_url = :video_url WHERE id = :id",
            {"id": content_id, "video_url": video_url},
        )
        logger.info("Stored video content %s for calendar item %s", content_id, item_id)

        # ── 3. video_jobs + media_assets bookkeeping ───────────────────────
        duration_s = float(meta.get("duration_s") or 0) or None
        await execute_update(
            "INSERT INTO video_jobs (id, brand_id, calendar_item_id, content_id, "
            "provider, model, mode, prompt, source_image_object, params, status, "
            "progress, idempotency_key, output_object, thumbnail_object, duration_s, "
            "cost_usd, generation_ledger, started_at, completed_at) "
            "VALUES (:id, :brand_id, :calendar_item_id, :content_id, "
            ":provider, :model, :mode, :prompt, :source_image_object, :params, 'succeeded', "
            "100, :idempotency_key, :output_object, :thumbnail_object, :duration_s, "
            ":cost_usd, :ledger, NOW(), NOW())",
            {
                "id": str(uuid4()),
                "brand_id": brand_id,
                "calendar_item_id": item_id,
                "content_id": content_id,
                "provider": meta.get("provider") or "video-forge",
                "model": meta.get("model") or "unknown",
                "mode": "i2v" if state.get("keyframe_object") else "t2v",
                "prompt": state.get("video_prompt") or "",
                "source_image_object": state.get("keyframe_object"),
                "params": json.dumps(
                    {
                        "aspect": "9:16",
                        "audio": True,
                        "quality_tier": state.get("quality_tier") or "standard",
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                    }
                ),
                "idempotency_key": (meta.get("idempotency_key") or "")[:128] or None,
                "output_object": video_object,
                "thumbnail_object": thumbnail_object,
                "duration_s": duration_s,
                "cost_usd": meta.get("cost_usd") or 0,
                "ledger": json.dumps(meta.get("ledger") or []),
            },
        )
        await execute_update(
            "INSERT INTO media_assets (id, brand_id, calendar_item_id, content_id, "
            "kind, role, bucket, object_name, mime_type, width, height, duration_s, "
            "size_bytes, provider, model, prompt, cost_usd, metadata) "
            "VALUES (:id, :brand_id, :calendar_item_id, :content_id, "
            "'video', 'final', :bucket, :object_name, 'video/mp4', :width, :height, "
            ":duration_s, :size_bytes, :provider, :model, :prompt, :cost_usd, :metadata)",
            {
                "id": str(uuid4()),
                "brand_id": brand_id,
                "calendar_item_id": item_id,
                "content_id": content_id,
                "bucket": VIDEO_BUCKET,
                "object_name": video_object,
                "width": meta.get("width"),
                "height": meta.get("height"),
                "duration_s": duration_s,
                "size_bytes": len(video_bytes),
                "provider": meta.get("provider"),
                "model": meta.get("model"),
                "prompt": state.get("video_prompt") or "",
                "cost_usd": meta.get("cost_usd"),
                "metadata": json.dumps({"thumbnail_object": thumbnail_object}),
            },
        )

        # ── 4. Hand the item to review (same tail as store_content_node) ──
        _hook_title = (state.get("hook") or "").strip()
        if _hook_title:
            await execute_update(
                "UPDATE calendar_items SET status = 'in_review', title = :title "
                "WHERE id = :id",
                {"id": item_id, "title": _hook_title[:200]},
            )
        else:
            await execute_update(
                "UPDATE calendar_items SET status = 'in_review' WHERE id = :id",
                {"id": item_id},
            )

        # Auto-create approval record so it appears in the Approvals page
        try:
            reviewers = await execute_query(
                "SELECT id FROM users WHERE role IN ('admin', 'manager') AND is_active = true LIMIT 1"
            )
            if reviewers:
                approval_id = str(uuid4())
                await execute_update(
                    "INSERT INTO approvals (id, content_id, calendar_item_id, reviewer_id, status) "
                    "VALUES (:id, :content_id, :calendar_item_id, :reviewer_id, 'pending')",
                    {
                        "id": approval_id,
                        "content_id": content_id,
                        "calendar_item_id": item_id,
                        "reviewer_id": str(reviewers[0]["id"]),
                    },
                )
                logger.info(
                    "Created approval %s for content %s", approval_id, content_id
                )
            else:
                logger.warning(
                    "No manager/admin user found — skipping approval creation"
                )
        except Exception as appr_exc:
            logger.warning("Failed to create approval record: %s", appr_exc)

        # Notify the calendar item's creator that the reel is ready for review.
        try:
            from shared.tools.database import create_notification

            ci = state.get("calendar_item", {}) or {}
            br = state.get("brand", {}) or {}
            recipient = ci.get("created_by") or br.get("created_by")
            if recipient:
                brand_name = br.get("name") or "your brand"
                channel = (ci.get("channel") or "").capitalize() or "Social"
                hook_preview = (
                    state.get("hook") or ci.get("title") or "Untitled"
                ).strip()
                if len(hook_preview) > 120:
                    hook_preview = hook_preview[:117].rstrip() + "…"
                await create_notification(
                    user_id=str(recipient),
                    notification_type="video_ready",
                    title=f"{channel} reel ready for review — {brand_name}",
                    body=hook_preview,
                    reference_type="content",
                    reference_id=content_id,
                )
        except Exception as notif_exc:
            logger.debug("video_ready notification skipped: %s", notif_exc)

        return {
            "status": "in_review",
            "video_content_id": content_id,
            "video_object": video_object,
            "thumbnail_object": thumbnail_object,
            # Drop raw media bytes from the final state — the worker
            # serializes it into agent_runs.output_payload.
            "video_bytes": None,
            "keyframe_bytes": None,
        }
    except Exception as exc:
        return await _fail(state, f"store_video failed: {exc}")
