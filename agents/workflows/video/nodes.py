"""Video generation workflow nodes — shot planning, keyframe, render, store.

Reuses the content workflow's context/brief/product-image machinery
(load_context, enrich_user_brief, source_product_image_node) and adds the
video-specific stages: plan_shots (LLM shot list with per-shot on-screen
overlay lines), make_keyframe (branded product keyframe at 9:16),
render_video (one shared.video provider call per shot, chained i2v from the
previous shot's last frame, ffmpeg concat into a ~30s master reel, then a
best-effort libass burn of the overlay text onto the master), and
store_video (MinIO + video_jobs/media_assets/content persistence).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any
from uuid import uuid4

from shared.brand_context import ENGLISH_ONLY_RULE as _ENGLISH_ONLY_RULE
from shared.image_processing import contrast_ratio, relative_luminance
from shared.language_guard import detect_non_english
from shared.config import (
    VIDEO_AUDIO_TIMEOUT_S,
    VIDEO_BURN_TIMEOUT_S,
    VIDEO_CONCAT_TIMEOUT_S,
    VIDEO_MAX_REEL_SHOTS,
    VIDEO_MUSIC_DIR,
    VIDEO_MUSIC_DUCKED_DB,
    VIDEO_MUSIC_SOLO_DB,
    VIDEO_NORMALIZE_TIMEOUT_S,
    VIDEO_SILENCE_PEAK_DB,
    VIDEO_TARGET_LUFS,
    VIDEO_TARGET_TRUE_PEAK_DB,
    settings as _config_settings,
)
from shared.editorial import TEMPORAL_RULES_BLOCK, build_temporal_block
from shared.llm import chat_completion, generate_image, parse_llm_json
from shared.sanitize import sanitize_for_prompt
from shared.tools.database import (
    execute_query,
    execute_update,
    store_content,
    update_agent_run_step,
)
from shared.product_swap import product_photo_is_swappable
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

# ── Plan-level limits ─────────────────────────────────────────────────────
# The LLM plans beats and gives each an intended on-screen length in seconds;
# the render fitter below turns those weights into renderable 3-5s clips.
MIN_FIRST_SHOT_S = 2.0
MIN_SHOT_S = 0.5
# A complete marketing story needs 6-8 beats (hook → tension → reveal →
# proof → use moment → payoff → CTA), and 6 is also the smallest shot count
# that can reach the ~30s target (6 x MAX_SHOT_RENDER_S = 30s exactly).
MIN_PLAN_SHOTS = 6
MAX_SHOTS = VIDEO_MAX_REEL_SHOTS  # 8 — also the worker's render-timeout basis
# Widest plan the fitter can actually render: MAX_SHOTS x MAX_SHOT_RENDER_S.
MAX_PLAN_TOTAL_S = 40.0
# The legacy single-call path renders the WHOLE plan in one provider call and
# every provider clamps that to ~5-10s, so that request is capped separately.
SINGLE_CALL_MAX_DURATION_S = 10.0

# ── Render-level limits ───────────────────────────────────────────────────
# Every provider clamps a single call to ~5s (forge MAX_FRAMES=121 @ 24fps
# ≈ 5.04s; fal/veo similar), so each planned shot is rendered as its own 3-5s
# clip and the clips are concatenated into the master reel.
MIN_SHOT_RENDER_S = 3.0
MAX_SHOT_RENDER_S = 5.0
# The reel AIMS at TARGET_TOTAL_S and must stay inside the master-spec window
# [TARGET_MIN_TOTAL_S, TARGET_MAX_TOTAL_S]. With every shot clamped to 3-5s,
# an N-shot plan can realise any total in [3N, 5N]; the fitter lands on the
# point of that band closest to 30s:
#     N=4 → 20.0s              N=5 → 25.0s
#     N=6 → 30.0s (5.00s each) N=7 → 30.0s (≈4.29s each)
#     N=8 → 30.0s (3.75s each) N=9 → 30.0s (≈3.33s each)
#     N=10 → 30.0s (3.0s each) N=11 → 33.0s (3.0s each, the band's floor)
#     N≥12 → trailing shots dropped until 3N fits under the 35s ceiling.
# So every plan with 6-11 beats — and plan_shots is asked for 6-8 — lands
# within 3s of 30s, and 6-10 beats land EXACTLY on it. Only plans of 5 beats
# or fewer fall short (best effort: MAX_SHOT_RENDER_S per shot).
TARGET_TOTAL_S = 30.0
TARGET_MIN_TOTAL_S = 20.0
TARGET_MAX_TOTAL_S = 35.0
# These three are the FOOTAGE budget — what plan_shots is asked for and what
# the fitter lands on. The delivered reel is footage plus the branded end
# card appended in post (see _END_CARD_S), so a 30s plan ships at ~32.4s.
# The card is best-effort, which is why the budget is stated this way round:
# a card that fails to render leaves the reel SHORTER than planned, never
# longer, so the delivered ceiling holds either way.
# Fewer than 4 renderable shots can never reach the 20s floor (N shots cap at
# N*5s) — short plans get their longest beats split before rendering.
MIN_RENDER_SHOTS = 4
# Veo bills on its snapped duration grid (4/6/8s) — hero-tier shots are fitted
# to the grid so requested == billed and the aggregate stays inside the spec.
_VEO_SHOT_GRID_SHORT = 4.0
_VEO_SHOT_GRID_LONG = 6.0

# Multi-shot progress: shots share 0..95, the concat/finishing pass gets the rest.
_CONCAT_PROGRESS_START = 95

# ── Chain discipline ──────────────────────────────────────────────────────
# Every shot after the first is i2v from the PREVIOUS shot's last frame, so
# an 8-beat reel put shot 8 seven generations downstream of the branded
# keyframe. i2v is lossy per hop: contrast flattens, the label softens, and
# the product silhouette drifts until the pack in the closing beat is not the
# pack that was sourced. Measured on rendered reels, the back half looked
# washed and the bottle had changed shape.
#
# Capping the depth bounds that: after _MAX_CHAIN_DEPTH consecutive chained
# shots the next one re-anchors on the branded keyframe, which is also the
# grammar real product ads use — they CUT back to the hero rather than
# holding one unbroken take for 30s.
_MAX_CHAIN_DEPTH = 2

# ── Motion floor ──────────────────────────────────────────────────────────
# Nothing measured whether a rendered shot actually moved. i2v models fail by
# returning the input image held for the whole duration — a clip that passes
# every structural check (right codec, right length, real bytes) and is a
# dead-obvious tell on screen. _measure_motion averages the mean absolute
# inter-frame luma difference.
#
# Calibrated on four rendered reels, per 5s window:
#     held-still control ....... 0.001
#     slowest real beat ........ 0.53  (a hand breaking chocolate over a bowl:
#                                       small subject motion, static frame)
#     ordinary beats ........... 1.2 - 5.3
#     fast dolly through a shop  9.29
# The floor sits between the control and the slowest real beat, nearer the
# control: a genuine freeze carries encoder noise so it will not measure
# 0.001 exactly, but it lands far below a shot where only a hand moves.
# Re-rendering costs a provider call, so the check is deliberately biased
# toward letting a slow shot through.
_MIN_MOTION_YAVG = 0.25
# The other failure mode: the frame dissolving into churn rather than moving.
# UNCALIBRATED — no smeared shot has been measured yet, so this is a
# catastrophe backstop set ~3.5x above the fastest real camera move observed,
# not a tuned threshold. Tighten it once a genuinely morphing shot is caught.
_MAX_MOTION_YAVG = 34.0
# Analysis width — the metric is a frame-difference average, so full
# resolution buys nothing and costs a decode.
_MOTION_ANALYSIS_W = 240
# A failed shot buys ONE re-render, and the reel buys at most this many in
# total: a mis-calibrated floor must not be able to double the render bill.
_MAX_MOTION_RETRIES = 2

# Burned-in overlay text: each planned shot carries an overlay_text line that
# is composited onto the FINISHED master as an .ass subtitle track rendered by
# ffmpeg's libass `ass` filter, using the brand fonts shipped in the agents
# image. The pass is strictly best-effort — any failure keeps the unburned
# master (see _burn_overlays).
FONTS_DIR = "/usr/share/fonts/truetype/markai"
MAX_OVERLAY_WORDS = 6
# 20 chars/line at 76px is NARROWER in pixels than the old 16 at 96px
# (20x76 = 1520 vs 16x96 = 1536), so the block still fills the frame fraction
# professional short-form uses while holding four more characters a line.
# That headroom is what stops ordinary six-word marketing lines losing their
# last word. At 16x2 a greedy wrap dropped "pour" from "Dinner starts with a
# clean pour", "bottle" from "Certified organic, every bottle" and
# "throughout" from "Open today, certified throughout" — all three shipped
# that way inside finished 30-second masters.
_OVERLAY_WRAP_CHARS = 20
_OVERLAY_MAX_LINES = 2
# The whole box holds two 18-char lines — overlay_text is clamped to that
# budget at plan normalization so _wrap_overlay_text rarely has to drop words
# (it warns when it still does; a greedy wrap can waste part of a line).
_OVERLAY_MAX_CHARS = _OVERLAY_WRAP_CHARS * _OVERLAY_MAX_LINES
_OVERLAY_PAD_IN_S = 0.2  # a line appears 0.2s into its shot window
_OVERLAY_PAD_OUT_S = 0.15  # and clears 0.15s before the cut
_OVERLAY_MIN_EVENT_S = 0.3
# Shortest a line may sit on screen and still be readable at phone scale
# (~6 words at ~4 words/s plus the 250ms fade in/out). A shot window under
# this holds its line over the following windows instead of flashing it —
# see _overlay_events. The multi-shot path clears it by construction
# (MIN_SHOT_RENDER_S - the pads = 2.65s); it only bites on the legacy
# single-call path, where the whole plan is spread across one ~5s clip.
_OVERLAY_MIN_ON_SCREEN_S = 1.6
# Sized for phone viewing: a full line fills ~55-60% of the 1080px frame, the
# scale professional short-form uses. Smaller reads as a subtitle, not a hook.
# 76 rather than 96 buys four characters a line at a slightly narrower block.
_OVERLAY_FONT_SIZE = 76
_CTA_FONT_SIZE = 96
# The CTA is set larger, so it fits FEWER characters per line than the overlay
# — wrapping it at the overlay's budget is what pushed "See clearer choices
# from shelf to table." past two lines and silently dropped "shelf to table."
# off the end of a finished reel. Scale the budget by the font ratio.
_CTA_WRAP_CHARS = max(1, (_OVERLAY_WRAP_CHARS * _OVERLAY_FONT_SIZE) // _CTA_FONT_SIZE)
_CTA_MAX_CHARS = _CTA_WRAP_CHARS * _OVERLAY_MAX_LINES
# ── Burn safe areas on the 1080x1920 grid ─────────────────────────────────
# Published creative specs, converted to pixels and intersected:
#   TikTok safe-zone template: left 44, right 140 (action rail), top 130,
#     bottom 483 (caption + handle + music row).
#   Instagram Reels: no text in the top ~14% (270px) or bottom ~20% (384px);
#     the organic right action rail is ~180px wide, caption block ~420px tall.
#   YouTube Shorts: right rail ~150px, bottom title/subscribe ~380px.
# Type may only occupy the union of all three.
_SAFE_LEFT = 80
_SAFE_RIGHT = 900  # 1080 - 180: clears the widest right action rail
_SAFE_TOP = 240
_SAFE_BOTTOM = 1420  # 1920 - 500: clears the widest bottom caption block
# Type is bottom-LEFT anchored and grows UPWARD, so adding a line can never
# push it into the bottom chrome. The previous \an5 centre at (540,1130) did
# both things wrong: a ~950px-wide centred line reached x=1015, 75px under the
# action rail, and the 1015..1245 band is exactly where a 9:16 product shot
# puts the bottle and the faces. Rendered reels showed lines sitting on an
# olive-oil label and across a presenter's chest.
_OVERLAY_POS_X = _SAFE_LEFT
_OVERLAY_POS_Y = _SAFE_BOTTOM
# Scrim: a feathered black plate under the type. Legibility was a property of
# the GLYPH (outline + shadow), which is backdrop-dependent by construction —
# white-on-beige at "Certified organic matters" was barely readable in a
# finished reel. A scrim makes the backdrop deterministic instead, which is
# also what makes the CTA contrast check below computable without decoding a
# frame. 55% is the lightest value that still holds white Poppins Bold over a
# blown-out white shot.
_SCRIM_ALPHA_HEX = "73"  # ASS alpha: 0x73/0xFF transparent => ~55% opaque
_SCRIM_TOP_Y = 980  # \blur feathers this edge upward from about y=900
# The worst backdrop the scrim can produce (55% black over pure white).
_SCRIM_WORST_BACKDROP = (115, 115, 115)
# WCAG 2.1 AA large-text is 3:1, and burned CTA type is large by definition
# (96px on a 1080 frame). The body-text floor of 4.5:1 is NOT usable here: the
# most contrast anything can reach against the scrim's worst backdrop is pure
# white at 4.69:1, so a 4.5 floor admits only near-white and turns the check
# into "always white" — a discriminator that never discriminates. At 3:1 a
# pale brand colour passes and a saturated one (Naturespan's lime, 2.1:1)
# does not, which is the distinction that matters.
_MIN_CTA_CONTRAST = 3.0
_OVERLAY_RISE_PX = 24  # entry travel for the settle

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
    #: True only when the keyframe's hero pack came from a real gallery photo.
    #: A keyframe can exist WITHOUT a verified pack (product-free or
    #: deliberately unreadable packaging), so render_video reads this rather
    #: than inferring pack provenance from the keyframe's existence.
    keyframe_verified_pack: bool
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
                "mode, prompt, status, error_message, cost_usd, generation_ledger) "
                "VALUES (:id, :brand_id, :calendar_item_id, :provider, :model, "
                ":mode, :prompt, 'failed', :error_message, :cost_usd, :ledger)",
                {
                    "id": str(uuid4()),
                    "brand_id": brand_id,
                    "calendar_item_id": item_id,
                    "provider": meta.get("provider") or "video-forge",
                    "model": meta.get("model") or "unknown",
                    "mode": "i2v" if state.get("keyframe_bytes") else "t2v",
                    "prompt": state.get("video_prompt") or "",
                    "error_message": message[:2000],
                    # Money already spent on paid shots before the failure —
                    # kept out of the ledger blob so cost aggregations over
                    # video_jobs.cost_usd see partial multi-shot spend too.
                    "cost_usd": meta.get("cost_usd") or 0,
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


def _clean_overlay_text(
    value: Any,
    max_chars: int = _OVERLAY_MAX_CHARS,
    wrap_chars: int = _OVERLAY_WRAP_CHARS,
) -> str:
    """Normalize one on-screen line (pure function).

    Strips newlines/extra whitespace, clamps to MAX_OVERLAY_WORDS words AND to
    the box budget — whole trailing words are dropped here rather than left for
    _wrap_overlay_text to discard silently at burn time, so what the plan
    stores is what the viewer sees. Absent/None becomes '' so pre-overlay shot
    plans keep working unchanged.

    The CTA passes its own, smaller budget (_CTA_MAX_CHARS / _CTA_WRAP_CHARS)
    because it is set at a larger size and so fits fewer characters per line.

    The budget is measured by SIMULATING the wrap, not by counting characters
    against ``wrap_chars * max_lines``. That product assumes perfect packing,
    and a greedy wrap never packs perfectly — it abandons the ragged end of
    every line. "Dinner starts with a clean pour" is 6 words and 30 characters,
    inside a nominal 32-character budget, yet wraps to "Dinner starts" +
    "with a clean" and loses "pour". Both that line and "Certified organic,
    every bottle" shipped a word short in a finished 30-second master. The
    ``max_chars`` argument is now an upper bound that the wrap check refines.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    # Mirror the burn exactly: _wrap_overlay_text truncates any word wider than
    # a line, so truncate here too or the stored text again promises more than
    # the screen shows.
    words = [w[:wrap_chars] for w in text.split()[:MAX_OVERLAY_WORDS]]
    max_lines = max(1, -(-max_chars // wrap_chars))

    def fits(candidate: list[str]) -> bool:
        """True when these words wrap into max_lines of wrap_chars."""
        lines, cur = 1, ""
        for word in candidate:
            nxt = f"{cur} {word}".strip() if cur else word
            if len(nxt) <= wrap_chars:
                cur = nxt
                continue
            lines += 1
            if lines > max_lines:
                return False
            cur = word
        return True

    kept = list(words)
    while kept and not fits(kept):
        kept.pop()
    if not kept and words:
        # A single oversized word: keep a one-line truncation rather than
        # losing the line entirely.
        kept = [words[0][:wrap_chars]]
    return _close_fragment(" ".join(kept))


# A burned line is read on its own, with nothing before or after it. Trailing
# punctuation and dangling connectives promise a continuation that the next
# cut never delivers: a rendered reel carried "AB Ecocert Eurofeuille," across
# a full beat, which reads as a line that got cut off rather than a claim.
_FRAGMENT_TAIL_PUNCT = ",;:-–—…"
_DANGLING_WORDS = frozenset(
    "and or but so with without for from to of in on at by as than that "
    "while when because plus into onto over under".split()
)


def _close_fragment(text: str) -> str:
    """Drop a trailing connective and open punctuation from a line (pure).

    Only the TAIL is touched, and only words that cannot end a thought —
    "Certified organic and" becomes "Certified organic", which is a line;
    "Shop the range" is left exactly as written.
    """
    out = str(text or "").strip()
    while out:
        stripped = out.rstrip(_FRAGMENT_TAIL_PUNCT + " ")
        if stripped != out:
            out = stripped
            continue
        words = out.split()
        if len(words) > 1 and words[-1].lower().strip(
            _FRAGMENT_TAIL_PUNCT + ".!?"
        ) in _DANGLING_WORDS:
            out = " ".join(words[:-1])
            continue
        break
    return out


def _normalize_shot_plan(plan: Any) -> dict[str, Any]:
    """Validate and normalize the LLM's shot plan JSON.

    Enforces: non-empty shots with scene text, per-shot duration >= 0.5s,
    first shot >= 2s, total duration <= MAX_PLAN_TOTAL_S, at most MAX_SHOTS
    shots, cleaned per-shot overlay_text (<= MAX_OVERLAY_WORDS words, no
    newlines, '' when absent), and cleaned hashtags (no '#', no spaces).

    Over-budget plans are scaled DOWN, never truncated: the hook keeps its
    floor and the remaining beats share whatever budget is left, because
    dropping beats here would fight the 6-8 shot count the render fitter
    needs to land on ~30s. A plan under MIN_PLAN_SHOTS beats is kept (it
    still renders, just shorter) and logged.

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
                "overlay_text": _clean_overlay_text(raw.get("overlay_text")),
            }
        )
    if not shots:
        raise ValueError("shot plan has no usable shots (missing scene text)")

    if len(shots) < MIN_PLAN_SHOTS:
        logger.warning(
            "Shot plan returned %d beats (asked for %d-%d) — the reel will "
            "be shorter than the %.0fs target",
            len(shots),
            MIN_PLAN_SHOTS,
            MAX_SHOTS,
            TARGET_TOTAL_S,
        )

    # First shot carries the hook — never shorter than 2s, and never so long
    # that the remaining beats cannot keep their MIN_SHOT_S floors.
    head_cap = max(MIN_SHOT_S, MAX_PLAN_TOTAL_S - MIN_SHOT_S * (len(shots) - 1))
    shots[0]["duration_s"] = min(
        head_cap, max(MIN_FIRST_SHOT_S, shots[0]["duration_s"])
    )

    # An over-budget tail is re-shared onto whatever the hook left, floors
    # included — no beat is ever dropped to make the arithmetic work.
    tail = shots[1:]
    tail_budget = round(MAX_PLAN_TOTAL_S - shots[0]["duration_s"], 2)
    if tail and sum(s["duration_s"] for s in tail) > tail_budget:
        allocated = _allocate_durations(
            [s["duration_s"] for s in tail], tail_budget, MIN_SHOT_S, tail_budget
        )
        for shot, duration in zip(tail, allocated):
            shot["duration_s"] = duration

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
        # The CTA is burned onto the final beat, so it is clamped to its own
        # (smaller) box budget here for the same reason overlay_text is: a line
        # trimmed at burn time leaves a half-sentence on a finished reel.
        "cta": _clean_overlay_text(
            plan.get("cta"), _CTA_MAX_CHARS, _CTA_WRAP_CHARS
        ),
        "music_mood": _normalize_music_mood(plan.get("music_mood")),
    }


# The music bed is chosen from <VIDEO_MUSIC_DIR>/<mood>/, so the vocabulary
# has to be CLOSED — an open-ended mood string means the operator cannot know
# which folders to create, and every reel silently falls through to the
# top-level pool. Five moods is enough to separate a calm provenance film
# from a fast promotional cut.
MUSIC_MOODS = ("warm", "upbeat", "calm", "bold", "elegant")


def _normalize_music_mood(value: Any) -> str:
    """One of MUSIC_MOODS, or '' when the plan named something else (pure)."""
    slug = re.sub(r"[^a-z]+", "", str(value or "").strip().lower())
    return slug if slug in MUSIC_MOODS else ""


# A MAX_SHOTS-beat plan carries a 7-label structured `scene` per shot plus
# overlay_text, hook_line, caption and hashtags — well past what a 4096-token
# completion holds. Truncation used to fail the calendar item outright
# (parse -> None -> _normalize_shot_plan raises -> _fail), the same
# single-call-truncation class the campaign path already removed.
_SHOT_PLAN_MAX_TOKENS = 8192


async def _repair_shot_plan_json(raw: str) -> Any:
    """One-shot JSON repair for a truncated shot plan; ``None`` if unrecoverable.

    Mirrors the campaign path's repair retry: a plan cut mid-value still holds
    several complete shots, and salvaging them beats failing the item.
    """
    logger.warning(
        "plan_shots: shot plan JSON unparseable (%d chars) — retrying with a "
        "repair prompt",
        len(raw),
    )
    repaired = await chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "You repair malformed JSON. The input below came from a "
                    "short-form video director and is invalid — most likely "
                    "truncated mid-value. Return ONLY a valid JSON object with "
                    'the keys "hook_line", "shots", "caption", "hashtags" and '
                    '"cta". Keep only the shots that are COMPLETE in the input '
                    "and drop any trailing shot whose fields were cut off. Do "
                    "not invent shots, do not add commentary, and keep every "
                    "intact field value verbatim."
                ),
            },
            {"role": "user", "content": sanitize_for_prompt(raw, max_length=12000)},
        ],
        category="text",
        temperature=0.0,
        max_tokens=_SHOT_PLAN_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    parsed = parse_llm_json(str(repaired), fallback=None)
    if parsed is not None:
        logger.info("plan_shots: repair retry recovered a parseable shot plan")
    return parsed


# Plan fields that end up in front of a viewer: burned onto the master, or
# published beside it. Anything here that is not English is a defect.
_PLAN_TEXT_FIELDS = ("hook_line", "caption", "cta")


def _plan_language_flags(plan: dict[str, Any], allow: Sequence[str]) -> dict[str, list[str]]:
    """Non-English markers per field across a normalized shot plan."""
    flags: dict[str, list[str]] = {}
    for field in _PLAN_TEXT_FIELDS:
        if markers := detect_non_english(str(plan.get(field) or ""), allow=allow):
            flags[field] = markers
    for index, shot in enumerate(plan.get("shots") or []):
        if markers := detect_non_english(
            str(shot.get("overlay_text") or ""), allow=allow
        ):
            flags[f"shots[{index}].overlay_text"] = markers
    return flags


async def _enforce_plan_language(
    plan: dict[str, Any],
    system: str,
    user: str,
    *,
    allow: Sequence[str] = (),
) -> dict[str, Any]:
    """Re-ask once if the plan came back in the wrong language.

    ENGLISH_ONLY_RULE sits at the top of the shot-plan system prompt and the
    model still mirrored a French brief on 2026-08-18 — five reels rendered
    with French burned onto the master, including the CTA card. Catching it
    here rather than in review is what makes the retry worth it: the render
    downstream costs tens of GPU-minutes per reel, so one extra text call to
    avoid producing an unusable master is cheap.

    A failed retry does NOT sink the item. The plan still describes a coherent
    reel and the warning names it for the QA loop; refusing to render leaves a
    hole in the calendar, which is the worse outcome.
    """
    allow = [a for a in allow if a]
    flags = _plan_language_flags(plan, allow)
    if not flags:
        return plan

    logger.warning(
        "PLAN_LANGUAGE: shot plan is not in English (%s) — re-asking once",
        "; ".join(f"{f}[{','.join(m[:4])}]" for f, m in flags.items()),
    )
    try:
        retry = await chat_completion(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {
                    "role": "user",
                    "content": (
                        "Your previous plan was written in the wrong language. "
                        "Rewrite the ENTIRE plan in English. Every hook_line, "
                        "overlay_text, caption and cta must be English — these "
                        "are burned onto the finished video. Keep proper nouns "
                        "(brand, product, place and certification names) "
                        "exactly as they are; translate everything else."
                    ),
                },
            ],
            category="text",
            temperature=0.2,
            max_tokens=_SHOT_PLAN_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        parsed = parse_llm_json(str(retry), fallback=None)
        if parsed is None:
            parsed = await _repair_shot_plan_json(str(retry))
        candidate = _normalize_shot_plan(parsed)
    except Exception as exc:
        logger.warning("PLAN_LANGUAGE: retry failed (%s) — keeping first plan", exc)
        return plan

    remaining = _plan_language_flags(candidate, allow)
    if remaining:
        logger.warning(
            "PLAN_LANGUAGE: retry STILL not English (%s) — rendering anyway, "
            "flag this reel in review",
            "; ".join(f"{f}[{','.join(m[:4])}]" for f, m in remaining.items()),
        )
    else:
        logger.info("PLAN_LANGUAGE: retry returned an English plan")
    return candidate


async def plan_shots(state: VideoState) -> dict[str, Any]:
    """One LLM call producing the strict-JSON shot plan.

    Asks for MIN_PLAN_SHOTS..MAX_SHOTS beats carrying a full marketing story;
    render_video refits each shot to a 3-5s clip so the final concatenated
    reel lands on the ~TARGET_TOTAL_S master-spec target."""
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
        # The video graph never runs content.generate_hook/generate_caption,
        # so this is the ONLY place the reel's own invented copy
        # (overlay_text, hook_line, caption, cta) meets the temporal guard.
        # "Opening soon" burned into a 30s master is the most visible
        # instance of the stale-anticipation defect.
        temporal_block = build_temporal_block(
            item.get("scheduled_at") or item.get("scheduled_date"),
            state.get("events", []),
        )
        product_section = ""
        if product.get("name"):
            product_section = (
                f"PRODUCT (the hero of this video):\n"
                f"  Name: {sanitize_for_prompt(product.get('name', ''))}\n"
                f"  Description: {sanitize_for_prompt(product.get('description', ''))}\n\n"
            )

        system = (
            f"{_ENGLISH_ONLY_RULE}\n\n"
            f"{voice_block}\n\n"
            f"{bible_section}"
            "You are a short-form video director planning a vertical (9:16) "
            "product reel. Each shot in your list is generated as its own "
            f"{MIN_SHOT_RENDER_S:.0f}-{MAX_SHOT_RENDER_S:.0f} second clip by "
            "an AI video model and the clips are cut together into a "
            f"{TARGET_TOTAL_S:.0f} second reel.\n\n"
            f"STORY ARC — plan {MIN_PLAN_SHOTS} to {MAX_SHOTS} beats that "
            "tell a COMPLETE marketing story, in this order:\n"
            "1. HOOK — the scroll-stopper: the product already in motion, "
            "the most arresting image you have.\n"
            "2. TENSION — the everyday friction or problem this product "
            "removes, shown (never narrated).\n"
            "3. REVEAL — the product itself, hero framing: its form, colour "
            "and material, held at natural product-shot distance.\n"
            "4. BENEFIT / PROOF — the promise made visible: texture, "
            "freshness, craft, the detail that proves the claim.\n"
            "5. USE MOMENT — a real person actually using or enjoying it in "
            "its natural setting.\n"
            "6. PAYOFF — the emotional result: the satisfied face, the "
            "finished table, the restored calm.\n"
            "7. CTA — the closing frame that carries the call to action.\n"
            f"Plan {MIN_PLAN_SHOTS} beats by merging two adjacent stages, "
            f"{MAX_SHOTS} by adding a second proof or use-moment beat. Never "
            f"return fewer than {MIN_PLAN_SHOTS} shots — a shorter list "
            "produces a reel that is too short to publish.\n\n"
            "SHORT-FORM DISCIPLINE (non-negotiable):\n"
            "- The product is VISIBLE and actively solving something within "
            "seconds 0-2. No slow establishing shots.\n"
            "- Each shot is exactly ONE beat with one clear visual change — "
            "it has to stay interesting for its full 3-5 seconds, so give it "
            "internal motion (a pour, a hand, a camera move), never a static "
            "hold.\n"
            "- The final shot resolves back toward the opening composition "
            "so the clip loops cleanly.\n"
            "- NEVER request on-screen text, captions, subtitles, prices, or "
            "logos in any scene — text is composited later in post.\n"
            "- NEVER make a product's LABEL the subject of a shot, and never "
            "frame the product so close that its label fills the frame. The "
            "video model repaints every pixel each shot, so lettering it is "
            "asked to hold comes back as convincing gibberish — a garbled "
            "brand name on screen is worse than no product shot at all. Show "
            "the product whole at natural product-shot distance; go tight on "
            "TEXTURE instead (the pour, the grain, the crumb, the leaf), "
            "never on printed words.\n"
            "- Audio is diegetic only: sounds that belong to the scene "
            "(sizzle, pour, clink, ambience). No voiceover, no music cues.\n"
            "- Stay strictly inside the brand voice above; never make claims "
            "the MUST NEVER DO list forbids.\n"
            "- NEVER call something upcoming, coming soon, or count down to "
            "it if the TEMPORAL CONTEXT block says it already happened by "
            "this reel's publish date — that line gets burned into the "
            "master.\n\n"
            + TEMPORAL_RULES_BLOCK
            + "Each shot's \"scene\" value is a structured prompt with exactly "
            "these labeled sections, one per line:\n"
            "SCENE CONTEXT: where we are and what is happening\n"
            "FIRST FRAME: precise description of the opening frame of this shot\n"
            "CAMERA/OPTICS: framing, movement, lens/depth-of-field\n"
            "LIGHTING: light quality, direction, color temperature\n"
            "AUDIO: the diegetic sound of this shot\n"
            "STYLE: photographic/commercial style anchors\n"
            "LOCKS: what must stay true across the shot (product identity, "
            "palette, setting)\n\n"
            "PACING — \"duration_s\" is the WEIGHT of each beat, not a "
            "formality:\n"
            f"- Use the full {MIN_SHOT_RENDER_S:.0f}-{MAX_SHOT_RENDER_S:.0f} "
            "second range. Giving every beat the same number produces a reel "
            "that ticks like a metronome, which is the single clearest tell "
            "of an automated edit.\n"
            "- Cut FAST through the opening and any montage of quick details; "
            "HOLD on the product reveal, the proof beat and the payoff, which "
            "are the shots a viewer actually needs time to take in.\n"
            "- At least two beats must differ by a full second from each "
            "other.\n\n"
            "OVERLAY TEXT (burned onto the video in post — the ONLY text "
            "that ever appears on screen):\n"
            f"- Every shot has an \"overlay_text\": a punchy on-screen line, "
            f"{MAX_OVERLAY_WORDS} words maximum, ALWAYS IN ENGLISH, "
            "marketing-grade.\n"
            "- The lines follow the story arc: shot 1 carries the hook_line, "
            "every middle shot carries the ONE idea its beat is about "
            "(tension, reveal, proof, use, payoff), and the final shot hands "
            "off to the cta (the final shot shows the cta on screen).\n"
            "- Consecutive lines must never repeat each other — each line "
            f"holds the screen for {MIN_SHOT_RENDER_S:.0f}-"
            f"{MAX_SHOT_RENDER_S:.0f} seconds, long enough to read twice.\n"
            "- EVERY LINE STANDS ALONE. A viewer reads it with nothing before "
            "or after it, so it must be a complete thought on its own — never "
            "a clause that runs on into the next shot. No trailing comma, "
            "dash or ellipsis, and never end on a connective word (and, with, "
            "for, to, of, because). \"Certified organic, every bottle\" is a "
            "line; \"AB Ecocert Eurofeuille,\" is a caption that got cut in "
            "half.\n"
            "- Write a CLAIM a shopper cares about, not a label transcription. "
            "Certification names, standard bodies and regulatory wording are "
            "packaging copy, not on-screen copy — say what it means for them "
            "instead.\n"
            "- Plain words only: no emojis, no hashtags, no quotation "
            "marks.\n\n"
            "Return STRICT JSON only, with this exact shape:\n"
            "{\n"
            '  "hook_line": "<scroll-stopping line under 8 words, ENGLISH>",\n'
            '  "shots": [\n'
            '    {"index": 1, "duration_s": 3.0, "overlay_text": "<on-screen line, 6 words max, ENGLISH>", "scene": "SCENE CONTEXT: ...\\nFIRST FRAME: ...\\nCAMERA/OPTICS: ...\\nLIGHTING: ...\\nAUDIO: ...\\nSTYLE: ...\\nLOCKS: ..."},\n'
            '    {"index": 2, "duration_s": 5.0, "overlay_text": "<...>", "scene": "..."}\n'
            "  ],\n"
            '  "music_mood": "<one of: ' + "|".join(MUSIC_MOODS) + '>",\n'
            '  "caption": "<post caption in the brand voice, ENGLISH>",\n'
            '  "hashtags": ["tag1", "tag2"],\n'
            f'  "cta": "<call to action, ENGLISH, at most {_CTA_MAX_CHARS} '
            'characters>"\n'
            "}\n\n"
            f"The cta is BURNED onto the last beat at a larger size than the "
            f"overlay lines, so it must fit {_OVERLAY_MAX_LINES} lines of "
            f"{_CTA_WRAP_CHARS} characters. Anything longer is cut, which "
            "leaves half a sentence on the finished reel.\n"
            f"Duration rules: return {MIN_PLAN_SHOTS} to {MAX_SHOTS} shots. "
            f"Every duration_s is between {MIN_SHOT_RENDER_S:.0f} and "
            f"{MAX_SHOT_RENDER_S:.0f} seconds and the durations sum to about "
            f"{TARGET_TOTAL_S:.0f} seconds — that IS the length of the "
            "finished reel. Give the hook and the CTA the longer slots and "
            "the connective beats the shorter ones.\n"
            f"Caption rules: under {settings['max_words']} words, between "
            f"{settings['hashtags_min']} and {settings['hashtags_max']} hashtags, "
            "no hashtags or URLs inside the caption body.\n"
            "LANGUAGE: the OUTPUT LANGUAGE hard rule at the top of this prompt "
            "applies to hook_line, every overlay_text, caption, and cta. The "
            "brief, theme and brand voice below may contain another language; "
            "that does NOT license you to answer in it. Do not mirror the "
            "brief's language — translate it. Every line you write is burned "
            "onto the finished video in English."
        )
        user = (
            f"{temporal_block}"
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
            max_tokens=_SHOT_PLAN_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        parsed = parse_llm_json(str(result), fallback=None)
        if parsed is None:
            parsed = await _repair_shot_plan_json(str(result))
        plan = _normalize_shot_plan(parsed)
        plan = await _enforce_plan_language(
            plan,
            system,
            user,
            allow=[product.get("name", ""), brand.get("name", ""), sub_brand],
        )
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

    # Ask BEFORE spending a generation whether the gallery photo can actually
    # carry a faithful swap. It used to be asked afterwards: the pipeline
    # rendered a 1024x1792 frame built around a blank placeholder, ran the
    # swap, watched it refuse on a 1200x630 share banner, and threw the whole
    # frame away — paying for an image and ~2 minutes to learn what one HTTP
    # fetch answers, and losing the chain anchor in the bargain. Asking first
    # turns that into a product-free frame we keep.
    swap_ready = has_product_image and not is_lifestyle_only
    if swap_ready and not await product_photo_is_swappable(
        str(state.get("product_image") or "")
    ):
        logger.warning(
            "make_keyframe: the gallery photo for %s/%s is too small to carry "
            "a faithful swap — composing a keyframe with no readable pack "
            "instead of building one around a placeholder we would discard",
            brand_id,
            item_id,
        )
        swap_ready = False

    no_text_rule = (
        "CRITICAL: ABSOLUTELY NO TEXT, WORDS, LETTERS, NUMBERS, LOGOS, "
        "WATERMARKS, LABELS, SIGNS, or TYPOGRAPHY of any kind. "
        "This is a photograph, not a graphic. "
    )
    pack_directive = ""
    if swap_ready:
        product_rule = (
            "Include a simple generic unlabeled product container (plain matte "
            "box or pouch with NO writing on it) placed naturally, FULLY "
            "visible within the frame with clear margin from every edge — "
            "never cropped. The container must be completely blank — it will "
            "be digitally replaced later. "
        )
    elif has_product_image and not is_lifestyle_only:
        # Still a product reel, but nothing will anchor the pack on a real
        # photo, so the keyframe follows the same contract the shots will:
        # packaging as colour, shape and material, never as readable copy.
        product_rule = (
            "Packaging may appear but reads as colour, shape and material "
            "only — turned partly away from camera, softened by shallow depth "
            "of field, or cropped by the frame edge. "
        )
        pack_directive = "\n\n" + _UNVERIFIED_PACK_DIRECTIVE
    else:
        product_rule = "Do NOT include any products. Focus on the scene and mood. "

    prompt_text = (
        f"REAL PHOTOGRAPH — Ultra realistic commercial photography, vertical "
        f"9:16 portrait frame, the opening frame of a short product video.\n\n"
        f"SCENE:\n{sanitize_for_prompt(first_frame, max_length=4000)}\n\n"
        # No brand NAME here. A name is a word, and image models typeset the
        # words you hand them — the same line was removed from the content
        # pipeline's prompts after a bake-off traced fabricated wordmarks in
        # the "reserved" logo corner directly to it. The keyframe seeds every
        # downstream shot, so a wordmark invented here propagates through the
        # whole reel.
        f"{product_rule}"
        f"Real shadows. Authentic textures. Natural depth of field. "
        f"{no_text_rule}"
        f"The image MUST look like a photograph captured with a real camera, "
        f"NOT an artwork, NOT a rendering, NOT an illustration."
        f"{pack_directive}"
    )

    try:
        channel = (item.get("channel", "") or "").lower()
        # The keyframe seeds every downstream shot, so hallucinated lettering
        # here propagates through the whole reel. No text is legitimate in it —
        # the real product (with its own packaging text) is composited in below.
        image_url = await generate_image(
            prompt_text,
            size="1024x1792",
            channel=channel or None,
            guard_label=f"video:keyframe:{channel or 'default'}",
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

        # Swap the blank placeholder for the real product photo. Identity is
        # the signal: every no-op path inside the swap returns the SAME bytes
        # object it was handed, so `is` separates "swapped" from "kept the
        # placeholder" without changing the swap's bytes-in/bytes-out contract.
        swapped = (
            await _replace_product_in_generated_image(state, image_data)
            if swap_ready
            else image_data
        )
        if swapped is image_data and swap_ready:
            # Keeping the placeholder is a sound outcome for a still post,
            # where a blank matte box is an inert prop. It is not sound here:
            # this frame seeds shot 1 and, through the i2v chain, every shot
            # after it, so a blank unbranded pouch becomes the hero of a 30s
            # reel — which is exactly what shipped in one Naturespan reel,
            # dominating four consecutive shots. No keyframe at all is better;
            # render_video downgrades cleanly to t2v.
            logger.warning(
                "make_keyframe: product swap did not fire for %s/%s — dropping "
                "the blank-placeholder keyframe and falling back to t2v",
                brand_id,
                item_id,
            )
            return {
                "keyframe_bytes": None,
                "keyframe_object": None,
                "keyframe_verified_pack": False,
            }
        image_data = swapped

        keyframe_object = f"{brand_id}/{item_id}/keyframe.png"
        await async_upload_file(VIDEO_BUCKET, keyframe_object, image_data, "image/png")
        logger.info(
            "Keyframe stored at %s/%s (%s)",
            VIDEO_BUCKET,
            keyframe_object,
            "real pack swapped in" if swap_ready else "no readable pack",
        )
        return {
            "keyframe_bytes": image_data,
            "keyframe_object": keyframe_object,
            "keyframe_verified_pack": swap_ready,
        }
    except Exception as exc:
        logger.warning("make_keyframe failed (%s) — falling back to t2v", exc)
        return {
            "keyframe_bytes": None,
            "keyframe_object": None,
            "keyframe_verified_pack": False,
        }


def _build_video_prompt(
    plan: dict[str, Any], *, unverified_pack: bool = False
) -> str:
    """Join the shot list into one structured multi-beat prompt with explicit
    CUT markers. Used for single-shot plans and as the degraded fallback when
    ffmpeg is unavailable (one provider call, ~5s clip)."""
    header = (
        "Vertical 9:16 short-form product video. Photorealistic commercial "
        "footage, one continuous generation with hard cuts between shots. "
        "Diegetic audio only — no voiceover, no music. No on-screen text, "
        "captions, or logos of any kind. The final shot resolves back toward "
        "the opening composition so the clip loops cleanly."
    )
    if unverified_pack:
        header += "\n\n" + _UNVERIFIED_PACK_DIRECTIVE
    parts = [
        f"SHOT {s['index']} ({s['duration_s']:.1f}s):\n{s['scene']}"
        for s in plan.get("shots") or []
    ]
    return header + "\n\n" + "\n\nCUT TO:\n\n".join(parts)


# ── Multi-shot render machinery ────────────────────────────────────────────
#
# Every video provider clamps a single call to ~5s, so a ~30s reel is built
# shot by shot: shot 1 is i2v from the branded keyframe, every later shot is
# i2v from the LAST FRAME of the previous shot's rendered clip (extracted with
# ffmpeg -sseof), carrying motion/scene continuity across cuts. The clips are
# then normalized to the master spec where needed and concatenated with ffmpeg.


def _allocate_durations(
    weights: list[float], target: float, lo: float, hi: float
) -> list[float]:
    """Split *target* seconds across *weights*, every share inside [lo, hi].

    Pure function, water-filling: shares start proportional to the weights;
    any share that would breach a bound is pinned there and the remaining
    seconds are re-shared over the still-free shots. *target* is first
    clamped into the band N shots can actually cover ([N*lo, N*hi]), so a
    short plan gets the longest reel it can reach and a long one the
    shortest. Shares are rounded to 2dp and sum to the clamped target.
    """
    n = len(weights)
    if n == 0:
        return []
    target = min(max(float(target), n * lo), n * hi)
    w = [max(0.0, float(x or 0.0)) for x in weights]
    if sum(w) <= 0:
        w = [1.0] * n
    out = [0.0] * n
    free = list(range(n))
    remaining = target
    while free:
        total_w = sum(w[i] for i in free)
        if total_w <= 0:  # pragma: no cover - guarded by the fallback above
            share = remaining / len(free)
            for i in free:
                out[i] = min(hi, max(lo, share))
            break
        pinned = []
        for i in free:
            share = remaining * w[i] / total_w
            if share < lo:
                out[i] = lo
                pinned.append(i)
            elif share > hi:
                out[i] = hi
                pinned.append(i)
        if not pinned:
            for i in free:
                out[i] = remaining * w[i] / total_w
            break
        remaining -= sum(out[i] for i in pinned)
        free = [i for i in free if i not in pinned]

    out = [round(v, 2) for v in out]
    # Rounding drift (a few hundredths) goes to whichever shots still have
    # room, lowest-priority first so the hook keeps its planned length.
    residue = round(target - sum(out), 2)
    for i in reversed(range(n)):
        if abs(residue) < 0.01:
            break
        room = (hi - out[i]) if residue > 0 else (out[i] - lo)
        if room <= 0:
            continue
        step = min(abs(residue), room) * (1.0 if residue > 0 else -1.0)
        out[i] = round(out[i] + step, 2)
        residue = round(residue - step, 2)
    return out


def _fit_shot_durations(
    shots: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Refit planned beat durations to renderable per-shot clip lengths.

    Pure function targeting TARGET_TOTAL_S (not merely "somewhere inside the
    20-35s window"): every duration is clamped to [MIN_SHOT_RENDER_S,
    MAX_SHOT_RENDER_S] and the 30s target is then distributed across the
    shots in proportion to their planned weights. Shots are dropped ONLY when
    even a minimum-length reel would breach the hard TARGET_MAX_TOTAL_S
    ceiling (plan order = priority, so trailing shots go first) — a plan of
    6-8 beats therefore keeps every beat and lands exactly on 30s; see the
    achievable-total table next to TARGET_TOTAL_S.

    Returns (fitted_shots, dropped_shots); input dicts are not mutated.
    """
    fitted = [
        {
            **s,
            "duration_s": min(
                MAX_SHOT_RENDER_S,
                max(MIN_SHOT_RENDER_S, float(s.get("duration_s") or 0.0)),
            ),
        }
        for s in shots
    ]
    dropped: list[dict[str, Any]] = []
    # Only a plan too long to fit even at MIN_SHOT_RENDER_S loses beats.
    while len(fitted) > 1 and len(fitted) * MIN_SHOT_RENDER_S > TARGET_MAX_TOTAL_S:
        dropped.append(fitted.pop())
    dropped.reverse()

    allocated = _allocate_durations(
        [s["duration_s"] for s in fitted],
        TARGET_TOTAL_S,
        MIN_SHOT_RENDER_S,
        MAX_SHOT_RENDER_S,
    )
    for shot, duration in zip(fitted, allocated):
        shot["duration_s"] = duration
    return fitted, dropped


def _split_to_min_shots(
    fitted: list[dict[str, Any]], min_count: int = MIN_RENDER_SHOTS
) -> list[dict[str, Any]]:
    """Split the longest beats in half until the plan has *min_count* shots.

    Pure function; input dicts are not mutated. A 1-3 shot plan can never
    reach the TARGET_MIN_TOTAL_S floor (N shots cap at N*MAX_SHOT_RENDER_S), so
    the longest scenes are split into two chained shots covering the same
    beat — the i2v chaining (next shot starts from the previous shot's last
    frame) keeps the beat continuous across the split. Both halves keep the
    plan index; the second half is marked as a continuation. Callers should
    refit durations afterwards (halves can fall under MIN_SHOT_RENDER_S).
    """
    out = [dict(s) for s in fitted]
    while 0 < len(out) < min_count:
        idx = max(range(len(out)), key=lambda i: out[i]["duration_s"])
        src = out[idx]
        half = round(float(src["duration_s"]) / 2.0, 2)
        first = {**src, "duration_s": half}
        scene = str(src.get("scene") or "")
        if "CONTINUATION:" not in scene:
            scene += (
                "\nCONTINUATION: second half of the same beat — carry the "
                "action forward without resetting the scene."
            )
        second = {
            **src,
            "duration_s": half,
            "scene": scene,
            "split_from": src.get("index"),
        }
        out[idx : idx + 1] = [first, second]
    return out


def _fit_hero_durations(
    fitted: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fit hero-tier shot durations to Veo's billing grid (pure function).

    Veo snaps every request to 4/6/8s and bills the snapped value
    (shared.video._snap_veo_duration: 5 → 6), so a hero reel requested at
    ~30s could render AND bill ~36s — over the 35s spec ceiling. Placing the
    shots on the grid here makes requested == snapped == billed.

    With N shots on the {4, 6} grid the reachable totals are 4N + 2k for k
    six-second shots, so k is chosen to land as close to TARGET_TOTAL_S as
    the grid allows without passing TARGET_MAX_TOTAL_S, and the 6s slots go
    to the highest-priority beats (longest fitted duration, plan order
    breaking ties). Trailing shots are dropped when even an all-4s reel would
    breach the ceiling. Reachable hero totals: N=4 → 24s, N=5/6/7 → 30s,
    N=8 → 32s. Input dicts are not mutated.

    Returns (fitted_shots, dropped_shots).
    """
    out = [dict(s) for s in fitted]
    dropped: list[dict[str, Any]] = []
    while len(out) > 1 and len(out) * _VEO_SHOT_GRID_SHORT > TARGET_MAX_TOTAL_S:
        dropped.append(out.pop())
    dropped.reverse()
    count = len(out)
    if not count:
        return out, dropped
    base = count * _VEO_SHOT_GRID_SHORT
    step = _VEO_SHOT_GRID_LONG - _VEO_SHOT_GRID_SHORT
    long_count = max(0, min(count, round((TARGET_TOTAL_S - base) / step)))
    while long_count > 0 and base + long_count * step > TARGET_MAX_TOTAL_S:
        long_count -= 1
    priority = sorted(range(count), key=lambda i: (-float(out[i]["duration_s"]), i))
    longs = set(priority[:long_count])
    for i, shot in enumerate(out):
        shot["duration_s"] = (
            _VEO_SHOT_GRID_LONG if i in longs else _VEO_SHOT_GRID_SHORT
        )
    return out, dropped


def _map_shot_progress(shot_idx: int, num_shots: int, percent: float) -> int:
    """Map one shot's 0-100 progress into the overall render window.

    Pure function. Shot k of N owns the proportional slice of
    [0, _CONCAT_PROGRESS_START); the tail is reserved for the concat pass.
    """
    clamped = max(0.0, min(100.0, float(percent)))
    if num_shots <= 1:
        return int(clamped)
    span = _CONCAT_PROGRESS_START / num_shots
    return int(shot_idx * span + (clamped / 100.0) * span)


def _wrap_progress(
    progress_cb: Callable[[int, str], Awaitable[None]],
    shot_idx: int,
    num_shots: int,
) -> Callable[[int, str], Awaitable[None]]:
    """Wrap the item-level progress callback into shot *shot_idx*'s window."""

    async def _cb(percent: int, stage: str) -> None:
        await progress_cb(
            _map_shot_progress(shot_idx, num_shots, percent),
            f"shot {shot_idx + 1}/{num_shots}:{stage}",
        )

    return _cb


# When the product swap did not fire, no verified pack exists anywhere in
# this reel: make_keyframe drops the keyframe and every shot is generated
# from the prompt alone. The model then draws a label, and what it draws is
# gibberish. One rendered reel carried "FIIRE CMIS", "THETE CCRE MAITENE OL"
# and "TWTL CCRE PAILSNEWE" across seven shots of olive-oil bottles.
#
# The general rule in the plan prompt ("never make the label the subject")
# does not cover this: the model obeyed it — the bottles sit at natural
# product-shot distance — and the labels are still legible enough to read as
# nonsense. With no reference to copy from, the only safe instruction is that
# printed copy must not resolve AT ALL.
_UNVERIFIED_PACK_DIRECTIVE = (
    "PACKAGING (hard constraint for this reel): no product label anywhere in "
    "frame may carry readable printed copy. Packs read as colour, shape and "
    "material only — turned partly away from camera, softened by shallow "
    "depth of field, or cropped by the frame edge. Never present a front-"
    "facing label at a size where a viewer could try to read it, and never "
    "invent a brand name, product name, weight, ingredient list or "
    "certification mark. Unreadable packaging is correct here; invented "
    "lettering is not."
)


async def _delabel_shot_scenes(
    shots: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """Rewrite scene descriptions so no pack label can be legible.

    Appending _UNVERIFIED_PACK_DIRECTIVE to the prompt was not enough, and a
    rendered reel proved it: the shot plan still described a hero bottle with
    its label to camera, and the model rendered exactly that — "FIRLINIE ORIE
    OIL", "FIRIE NOSI", "2HE G OIL". A negation appended after a scene loses
    to the scene, because the scene is what the model is being asked to make.

    So the scene changes instead. One text call rewrites the beats to carry
    the same story through texture, hands, pour, food, room and people, with
    packs present only where they cannot be read. That call costs a fraction
    of the seven GPU renders it protects.

    Returns (shots, rewritten). Best-effort: any failure returns the ORIGINAL
    shots with rewritten=False, and the prompt directive still applies.
    """
    if not shots:
        return shots, False
    payload = [
        {"index": s.get("index", i + 1), "scene": str(s.get("scene") or "")}
        for i, s in enumerate(shots)
    ]
    system = (
        "You are a short-form commercial director revising your own shot "
        "list under one hard constraint: NO PRODUCT LABEL IN THIS REEL MAY "
        "BE LEGIBLE. There is no verified photograph of the pack, so any "
        "lettering the camera resolves will be invented, and an invented "
        "brand name on a finished ad is worse than no pack shot at all.\n\n"
        "Revise each shot so it carries the SAME beat and the same story "
        "position, but the frame never presents readable printed copy:\n"
        "- Replace hero pack shots and label close-ups with the product IN "
        "USE — the pour, the hand, the food it lands on, the room, the "
        "people at the table.\n"
        "- Where a pack must appear, put it turned partly away from camera, "
        "well behind the focal plane, or cropped by the frame edge.\n"
        "- Keep the same labelled sections, the same lighting and style "
        "anchors, and the same overall look. Change framing and subject, not "
        "the brand's world.\n"
        "- Never introduce on-screen text, signage or logos.\n\n"
        'Return STRICT JSON: {"shots": [{"index": <int>, "scene": '
        '"<revised scene, same labelled sections>"}]}'
    )
    try:
        raw = await chat_completion(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": sanitize_for_prompt(
                        json.dumps({"shots": payload}), max_length=12000
                    ),
                },
            ],
            category="text",
            temperature=0.3,
            max_tokens=_SHOT_PLAN_MAX_TOKENS,
            response_format={"type": "json_object"},
        )
        parsed = parse_llm_json(str(raw), fallback=None)
        # parse_llm_json unwraps a single-key wrapper, so the revision can
        # arrive as either {"shots": [...]} or the bare list.
        revised = parsed.get("shots") if isinstance(parsed, dict) else parsed
        if not isinstance(revised, list) or not revised:
            raise ValueError("no shots in the revision")
        by_index = {
            r.get("index"): str(r.get("scene") or "").strip()
            for r in revised
            if isinstance(r, dict) and str(r.get("scene") or "").strip()
        }
        out: list[dict[str, Any]] = []
        replaced = 0
        for i, shot in enumerate(shots):
            scene = by_index.get(shot.get("index", i + 1))
            if scene:
                out.append({**shot, "scene": scene})
                replaced += 1
            else:
                out.append(shot)
        if not replaced:
            raise ValueError("the revision matched no shot indices")
        logger.info(
            "Rewrote %d/%d scenes to keep pack lettering illegible",
            replaced,
            len(shots),
        )
        return out, True
    except Exception as exc:
        # The prompt directive still ships; this only removes the scene text
        # working against it.
        logger.warning(
            "Could not rewrite scenes for the unverified pack (%s) — "
            "relying on the prompt directive alone",
            exc,
        )
        return shots, False


def _build_shot_prompt(
    shot: dict[str, Any],
    position: int,
    total: int,
    *,
    unverified_pack: bool = False,
) -> str:
    """Prompt for ONE shot rendered as its own continuous clip.

    Pure function. The source image (branded keyframe for shot 1, the previous
    shot's last frame afterwards) anchors continuity, so the prompt describes
    a single take and — for chained shots — the change-one-thing principle.

    *unverified_pack* is set when no keyframe survived, meaning nothing in
    this reel shows a real pack — see _UNVERIFIED_PACK_DIRECTIVE.
    """
    header = (
        "Vertical 9:16 photorealistic commercial product footage — one "
        "continuous take, no cuts, no transitions. Diegetic audio only — no "
        "voiceover, no music. No on-screen text, captions, or logos of any "
        "kind."
    )
    lines = [header, "", f"SHOT {position + 1} of {total}:", str(shot.get("scene") or "")]
    if unverified_pack:
        lines.append("\n" + _UNVERIFIED_PACK_DIRECTIVE)
    if position == 0:
        lines.append(
            "\nThe motion starts exactly from the provided first frame."
        )
    else:
        lines.append(
            "\nCONTINUITY: the provided image is the final frame of the "
            "previous shot. Continue from it, changing exactly one thing "
            "(camera, subject action, or framing) while product identity, "
            "palette and setting stay locked."
        )
    if total > 1 and position == total - 1:
        lines.append(
            "This is the final shot — resolve back toward the reel's opening "
            "composition so the clip loops cleanly."
        )
    return "\n".join(lines)


def _build_concat_list(paths: list[str]) -> str:
    """ffmpeg concat-demuxer list file content (pure function).

    Single quotes inside paths are escaped per the demuxer's quoting rules.
    """
    lines = []
    for p in paths:
        escaped = p.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


# Master spec every concat input must match: 1080x1920 H.264 yuv420p 30fps
# CFR closed-GOP + AAC 48kHz stereo (what the forge master_encode emits).
_MASTER_VF = (
    "scale=1080:1920:force_original_aspect_ratio=decrease,"
    "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p"
)
_MASTER_VIDEO_ARGS = [
    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
    "-g", "60", "-keyint_min", "60", "-sc_threshold", "0", "-flags", "+cgop",
]
_MASTER_AUDIO_ARGS = ["-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-ac", "2"]


def _normalize_cmd(
    src: str, dst: str, has_audio: bool, duration_s: float | None = None
) -> list[str]:
    """ffmpeg args re-encoding one shot to the master spec (pure function).

    fal/veo outputs come back AS-IS (shared.video never master-encodes them),
    so any non-forge shot goes through this pass before concat. Clips with no
    audio stream get anullsrc silence (infinite source, trimmed by -shortest).
    Clips with REAL audio keep the video length authoritative: the track is
    apad-ded and the output trimmed to the probed clip duration, so an audio
    track slightly shorter than the video can never shave frames off the shot
    (which would also invalidate the pre-extracted last-frame chain point).
    """
    args = ["ffmpeg", "-y", "-i", src]
    if not has_audio:
        args += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    args += [
        "-map", "0:v:0",
        "-map", "0:a:0" if has_audio else "1:a:0",
        "-vf", _MASTER_VF,
        *_MASTER_VIDEO_ARGS,
        *_MASTER_AUDIO_ARGS,
    ]
    if has_audio and duration_s and duration_s > 0:
        args += ["-af", "apad", "-t", f"{float(duration_s):.3f}"]
    else:
        # anullsrc silence, or no known duration to trim to — -shortest is
        # the only safe stop condition.
        args += ["-shortest"]
    args += ["-movflags", "+faststart", dst]
    return args


def _concat_copy_cmd(list_path: str, dst: str) -> list[str]:
    """ffmpeg args for a lossless concat-demuxer stream copy (pure function)."""
    return [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", "-movflags", "+faststart", dst,
    ]


def _concat_reencode_cmd(paths: list[str], dst: str) -> list[str]:
    """ffmpeg args for a filter_complex concat re-encode (pure function).

    Fallback for non-uniform inputs: every input is scaled/padded/CFR'd to the
    master spec inside the filter graph, then concatenated and re-encoded.
    """
    args: list[str] = ["ffmpeg", "-y"]
    for p in paths:
        args += ["-i", p]
    n = len(paths)
    parts: list[str] = []
    for i in range(n):
        parts.append(f"[{i}:v:0]{_MASTER_VF}[v{i}];")
        parts.append(f"[{i}:a:0]aresample=48000[a{i}];")
    interleaved = "".join(f"[v{i}][a{i}]" for i in range(n))
    filter_str = "".join(parts) + interleaved + f"concat=n={n}:v=1:a=1[v][a]"
    args += [
        "-filter_complex", filter_str,
        "-map", "[v]", "-map", "[a]",
        *_MASTER_VIDEO_ARGS,
        *_MASTER_AUDIO_ARGS,
        "-movflags", "+faststart",
        dst,
    ]
    return args


def _fps_value(rate: str | None) -> float:
    """Parse an ffprobe rational frame rate ('30/1') to a float (pure)."""
    try:
        num, _, den = str(rate or "").partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _is_master_conformant(info: dict[str, Any] | None) -> bool:
    """True when a probed shot already matches the concat master spec (pure)."""
    if not info or not info.get("video"):
        return False
    v = info["video"]
    a = info.get("audio")
    return (
        v.get("codec") == "h264"
        and v.get("width") == 1080
        and v.get("height") == 1920
        and v.get("pix_fmt") == "yuv420p"
        and abs(_fps_value(v.get("fps")) - 30.0) < 0.01
        and a is not None
        and a.get("codec") == "aac"
        and a.get("sample_rate") == 48000
    )


def _ffmpeg_ok() -> bool:
    """Same binary resolution the thumbnail path uses — ffmpeg on PATH."""
    return shutil.which("ffmpeg") is not None


def _ffprobe_ok() -> bool:
    """ffprobe on PATH. The multi-shot path requires it alongside ffmpeg:
    without probes every clip looks audio-less (real diegetic audio would be
    silently replaced with anullsrc silence) and duration verification is
    impossible, so the render degrades to the single-call path instead."""
    return shutil.which("ffprobe") is not None


def _run_ffmpeg(args: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Run one ffmpeg invocation, capturing output (call via asyncio.to_thread)."""
    return subprocess.run(args, capture_output=True, timeout=timeout)


def _stderr_tail(proc: subprocess.CompletedProcess, limit: int = 400) -> str:
    """Last *limit* chars of an ffmpeg run's stderr for error messages."""
    try:
        text = (proc.stderr or b"").decode("utf-8", errors="replace")
    except AttributeError:  # already str (mocked runs)
        text = str(proc.stderr or "")
    return text[-limit:].strip()


_MOTION_KEY_RE = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.]+)")


def _motion_cmd(path: str) -> list[str]:
    """ffmpeg args printing per-frame inter-frame difference (pure function).

    `tblend=difference` turns each frame into |frame - previous frame|, and
    signalstats' YAVG is then the mean absolute luma change over the whole
    frame. Averaging that across the clip gives one number for "how much did
    this shot actually move". Decoded at _MOTION_ANALYSIS_W and written to
    null — nothing is encoded.
    """
    return [
        "ffmpeg", "-v", "info", "-nostats", "-i", path,
        "-vf",
        f"scale={_MOTION_ANALYSIS_W}:-2,tblend=all_mode=difference,"
        "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
        "-an", "-f", "null", "-",
    ]


def _motion_from_stderr(stderr: str) -> float | None:
    """Mean YAVG across the printed frames, or None if nothing parsed (pure).

    The first tblend output compares frame 1 against itself and is always 0,
    so it is dropped — on a 3s clip keeping it would drag the average down
    by ~1%, but on a 2-frame probe it would halve it.
    """
    values = [float(m) for m in _MOTION_KEY_RE.findall(stderr or "")]
    if len(values) > 1:
        values = values[1:]
    if not values:
        return None
    return sum(values) / len(values)


def _measure_motion(path: str) -> float | None:
    """Average inter-frame luma difference for one clip, or None if unmeasurable.

    Runs in a worker thread. None means ffmpeg is unavailable or the filter
    chain failed — callers must treat that as "unknown", never as "static",
    so a missing measurement can never fail an otherwise good shot.
    """
    if not _ffmpeg_ok():
        return None
    try:
        proc = _run_ffmpeg(_motion_cmd(path), timeout=120)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    try:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    except AttributeError:  # already str (mocked runs)
        stderr = str(proc.stderr or "")
    return _motion_from_stderr(stderr)


def _motion_verdict(score: float | None) -> str | None:
    """'static' / 'smeared' / None(=ok) for a measured motion score (pure)."""
    if score is None:
        return None
    if score < _MIN_MOTION_YAVG:
        return "static"
    if score > _MAX_MOTION_YAVG:
        return "smeared"
    return None


def _probe_shot(path: str) -> dict[str, Any] | None:
    """ffprobe one clip: {duration, video: {...}, audio: {...}} or None.

    Runs in a worker thread. None means ffprobe is unavailable or failed —
    callers must treat that as "not conformant, duration unknown".
    """
    if not shutil.which("ffprobe"):
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate,sample_rate",
                "-show_entries", "format=duration",
                "-of", "json", path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
    except Exception:
        return None
    info: dict[str, Any] = {
        "duration": float((data.get("format") or {}).get("duration") or 0.0),
        "video": None,
        "audio": None,
    }
    for s in data.get("streams") or []:
        if s.get("codec_type") == "video" and info["video"] is None:
            info["video"] = {
                "codec": s.get("codec_name"),
                "width": int(s.get("width") or 0),
                "height": int(s.get("height") or 0),
                "pix_fmt": s.get("pix_fmt"),
                "fps": s.get("r_frame_rate"),
            }
        elif s.get("codec_type") == "audio" and info["audio"] is None:
            info["audio"] = {
                "codec": s.get("codec_name"),
                "sample_rate": int(s.get("sample_rate") or 0),
            }
    return info


def _extract_last_frame(video_path: str, workdir: str, shot_no: int) -> bytes | None:
    """Extract the last frame of a rendered shot as PNG bytes (worker thread).

    Seeks from the end (-sseof); a couple of wider offsets cover clips whose
    final 0.1s decodes to nothing.
    """
    dst = os.path.join(workdir, f"lastframe_{shot_no:02d}.png")
    for offset in ("-0.1", "-0.5", "-1.0"):
        proc = _run_ffmpeg(
            ["ffmpeg", "-y", "-sseof", offset, "-i", video_path,
             "-frames:v", "1", "-update", "1", dst],
            timeout=120,
        )
        if proc.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0:
            with open(dst, "rb") as fh:
                return fh.read()
    return None


def _write_bytes(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# ── Burned-in overlay text (post pass) ─────────────────────────────────────
#
# After the final master exists (concat output or single-call legacy clip),
# the plan's per-shot overlay_text lines are burned in via an .ass subtitle
# track rendered by ffmpeg's libass `ass` filter (the agents image ships
# ffmpeg with libass plus the brand fonts under FONTS_DIR). Filter
# availability is verified by simply running it — any failure degrades to
# the unburned master with overlay_burn='failed:<reason>'.


def _ass_escape(text: str) -> str:
    r"""Neutralize ASS metacharacters in overlay text (pure function).

    '{'/'}' open/close override blocks and '\' starts escape sequences —
    they are replaced rather than escaped (libass has no reliable literal
    escape for them). Newlines collapse to spaces; _wrap_overlay_text adds
    the only intentional '\N' breaks afterwards.
    """
    text = str(text or "")
    text = text.replace("\\", "/").replace("{", "(").replace("}", ")")
    return re.sub(r"\s+", " ", text).strip()


def _hex_to_ass_color(hex_color: str | None) -> str | None:
    """Convert '#rrggbb' to the ASS '&HBBGGRR&' form (pure function)."""
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(hex_color or "").strip())
    if not match:
        return None
    rgb = match.group(1)
    return f"&H{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}&".upper()


def _wrap_overlay_text(
    text: str,
    max_chars: int = _OVERLAY_WRAP_CHARS,
    max_lines: int = _OVERLAY_MAX_LINES,
) -> str:
    r"""Greedy word-wrap into at most *max_lines* lines of *max_chars*.

    Lines are joined with the ASS hard break '\N'; words that cannot fit the
    two-line box are dropped — the box must never overflow the safe zone.
    Dropping is a last resort (_clean_overlay_text already clamps the plan to
    the box budget) so it is logged as a WARNING: losing the tail of an
    on-screen line is a visible content defect QA must see, not a silent trim.
    """
    words = str(text or "").split()
    lines: list[str] = []
    cur = ""
    dropped: list[str] = []
    truncated: list[str] = []
    for i, raw in enumerate(words):
        word = raw[:max_chars]
        if word != raw:
            truncated.append(raw)
        candidate = f"{cur} {word}".strip() if cur else word
        if len(candidate) <= max_chars:
            cur = candidate
            continue
        lines.append(cur)
        cur = word
        if len(lines) == max_lines:
            dropped = words[i:]
            cur = ""
            break
    if cur:
        lines.append(cur)
    if dropped or truncated:
        logger.warning(
            "overlay text does not fit the %dx%d-char box — dropped %s, "
            "truncated %s (source: %r)",
            max_lines,
            max_chars,
            dropped or "nothing",
            truncated or "nothing",
            text,
        )
    return "\\N".join(lines[:max_lines])


def _format_ass_time(seconds: float) -> str:
    """Format seconds as the ASS 'H:MM:SS.CC' timestamp (pure function)."""
    total_cs = max(0, int(round(float(seconds) * 100)))
    cs = total_cs % 100
    total = total_cs // 100
    return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}.{cs:02d}"


def _distribute_durations(planned: list[float], total_s: float) -> list[float]:
    """Scale planned beat durations proportionally onto a real clip length.

    Pure function. Used by the single-call legacy path, where one clip covers
    the whole plan: each planned duration becomes its proportional share of
    the clip's real (ffprobe'd) duration. Zero/absent weights fall back to an
    equal split; the last share absorbs rounding so the shares sum exactly to
    total_s.
    """
    weights = [max(0.0, float(d or 0.0)) for d in planned]
    if not weights or total_s <= 0:
        return [0.0 for _ in weights]
    total_w = sum(weights)
    if total_w <= 0:
        weights = [1.0] * len(weights)
        total_w = float(len(weights))
    shares = [round(w / total_w * float(total_s), 2) for w in weights]
    shares[-1] = round(float(total_s) - sum(shares[:-1]), 2)
    return shares


def _overlay_events(
    shots: list[dict[str, Any]],
    durations: list[float],
    cta: str,
) -> list[dict[str, Any]]:
    """Compute the timed overlay events for the finished reel (pure function).

    Each shot's overlay_text spans that shot's ACTUAL time window, padded
    _OVERLAY_PAD_IN_S in and _OVERLAY_PAD_OUT_S out so lines never sit on a
    cut. The FINAL PLANNED shot shows the plan's cta (style 'CTA') instead of
    its own line — matched by the shot's ORIGINAL plan index, not its rendered
    position, because _split_to_min_shots can halve that last beat into two
    rendered shots that both belong to it; keying off the rendered index alone
    would leave the CTA covering only the second half. The merge below then
    folds those halves back into one continuous CTA event. Consecutive windows
    carrying the same text merge the same way (split-shot halves share their
    line); empty texts and sub-minimum windows are skipped.

    A line whose window is too short to read (_OVERLAY_MIN_ON_SCREEN_S) holds
    over the windows that follow it rather than flashing — never across the
    Overlay → CTA boundary, so the CTA can never be swallowed. On the
    multi-shot path this never triggers (MIN_SHOT_RENDER_S guarantees a 2.65s
    window); it exists for the legacy single-call path, where a 6-8 beat plan
    is distributed across one ~5s clip.
    """
    n = min(len(shots), len(durations))
    cta_text = str(cta or "").strip()
    # First rendered shot belonging to the final PLANNED beat.
    cta_from = n
    if cta_text and n:
        cta_from = n - 1
        final_index = shots[n - 1].get("index")
        if final_index is not None:
            while (
                cta_from > 0 and shots[cta_from - 1].get("index") == final_index
            ):
                cta_from -= 1
    entries: list[dict[str, Any]] = []
    t = 0.0
    for i in range(n):
        text = str(shots[i].get("overlay_text") or "").strip()
        style = "Overlay"
        if i >= cta_from:
            text = cta_text
            style = "CTA"
        end = t + max(0.0, float(durations[i] or 0.0))
        entries.append({"text": text, "style": style, "start": t, "end": end})
        t = end
    merged: list[dict[str, Any]] = []
    for entry in entries:
        if (
            merged
            and merged[-1]["text"] == entry["text"]
            and merged[-1]["style"] == entry["style"]
        ):
            merged[-1]["end"] = entry["end"]
        else:
            merged.append(dict(entry))

    # Hold short lines over the following windows so nothing flashes.
    dwell = _OVERLAY_MIN_ON_SCREEN_S + _OVERLAY_PAD_IN_S + _OVERLAY_PAD_OUT_S
    held: list[dict[str, Any]] = []
    i = 0
    while i < len(merged):
        window = dict(merged[i])
        nxt = i + 1
        if window["text"]:
            while (
                window["end"] - window["start"] < dwell
                and nxt < len(merged)
                and merged[nxt]["style"] == window["style"]
            ):
                window["end"] = merged[nxt]["end"]
                nxt += 1
            if nxt > i + 1:
                logger.info(
                    "Overlay line %r held over %d following window(s) — its "
                    "own window was under the %.1fs readable minimum",
                    window["text"],
                    nxt - i - 1,
                    _OVERLAY_MIN_ON_SCREEN_S,
                )
        held.append(window)
        i = nxt

    # A CTA cannot borrow from what comes after it, so when the reel is too
    # short to give it a readable window it takes the time back from the line
    # before it instead of being padded out of existence.
    if len(held) > 1 and held[-1]["style"] == "CTA" and held[-1]["text"]:
        cta_window, before = held[-1], held[-2]
        if cta_window["end"] - cta_window["start"] < dwell:
            cta_window["start"] = max(before["start"], cta_window["end"] - dwell)
            before["end"] = cta_window["start"]

    events: list[dict[str, Any]] = []
    for entry in held:
        if not entry["text"]:
            continue
        start = entry["start"] + _OVERLAY_PAD_IN_S
        end = entry["end"] - _OVERLAY_PAD_OUT_S
        if end - start < _OVERLAY_MIN_EVENT_S:
            continue
        events.append(
            {
                "text": entry["text"],
                "style": entry["style"],
                "start": round(start, 2),
                "end": round(end, 2),
            }
        )
    return events


def _brand_accent_hex(brand: dict[str, Any]) -> str | None:
    """Pull the brand accent (fallback: primary) hex from the brand config.

    Same color_palette / brand_guidelines.colors merge the content pipeline
    uses; returns '#rrggbb' or None when no valid hex is configured.
    """
    palette = brand.get("color_palette") or {}
    if isinstance(palette, str):
        try:
            palette = json.loads(palette)
        except (json.JSONDecodeError, TypeError):
            palette = {}
    guidelines = brand.get("brand_guidelines") or {}
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except (json.JSONDecodeError, TypeError):
            guidelines = {}
    legacy = guidelines.get("colors") if isinstance(guidelines, dict) else {}
    colors = {
        **(legacy if isinstance(legacy, dict) else {}),
        **(palette if isinstance(palette, dict) else {}),
    }
    for key in ("accent", "primary"):
        value = str(colors.get(key) or "").strip()
        if re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
            return value if value.startswith("#") else f"#{value}"
    return None


def _cta_primary_colour(accent_hex: str | None) -> str:
    """ASS PrimaryColour for the CTA — the brand accent only when it reads.

    The scrim makes the CTA's backdrop deterministic, so the accent can be
    checked against the WORST backdrop the scrim can produce (55% black over
    pure white) with the same WCAG helpers the logo placer uses, without
    decoding a frame. Naturespan's accent is a saturated lime (#80c020) that
    measures well under the floor; it shipped as bright green letters over a
    warm brown dinner scene, which reads as a glitch rather than a CTA.
    """
    accent = _hex_to_ass_color(accent_hex)
    if not accent:
        return "&H00FFFFFF"
    raw = str(accent_hex).lstrip("#")
    rgb = (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    ratio = contrast_ratio(
        relative_luminance(rgb), relative_luminance(_SCRIM_WORST_BACKDROP)
    )
    if ratio < _MIN_CTA_CONTRAST:
        logger.info(
            "CTA accent %s measures %.2f:1 on the scrim (floor %.1f:1) — "
            "rendering the CTA in white instead",
            accent_hex,
            ratio,
            _MIN_CTA_CONTRAST,
        )
        return "&H00FFFFFF"
    return f"&H00{accent[2:-1]}"


def _scrim_dialogue(start: float, end: float) -> str:
    r"""One feathered black plate under the type, as an ASS vector drawing.

    ``\an7`` + ``\pos(0,0)`` makes the ``\p1`` drawing coordinates frame
    coordinates; ``\blur`` feathers the top edge so the plate reads as a
    gradient rather than a rectangle.
    """
    body = (
        "{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&"
        f"\\1a&H{_SCRIM_ALPHA_HEX}&\\blur64\\fad(180,220)\\p1}}"
        f"m 0 {_SCRIM_TOP_Y} l 1080 {_SCRIM_TOP_Y} 1080 1920 0 1920"
        "{\\p0}"
    )
    return (
        f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(end)},"
        f"Scrim,,0,0,0,,{body}"
    )


def _build_overlay_ass(
    events: list[dict[str, Any]], accent_hex: str | None = None
) -> str:
    r"""Build the .ass subtitle document for the overlay events (pure).

    1080x1920 play grid. Type is Poppins Bold, bottom-LEFT anchored (\an1) on
    the safe baseline so it grows upward and can never drift into the bottom
    caption chrome or under the right action rail. Each line rides a feathered
    black scrim on the layer below, which is what carries legibility over
    arbitrary footage — an outline alone is backdrop-dependent, and white type
    over a pale wall was barely readable in a finished reel. The CTA takes the
    brand accent only when it measures against the scrim; otherwise white.
    """
    cta_color = _cta_primary_colour(accent_hex)
    # \move settles the line upward as it fades in: a short travel reads as
    # deliberate, where the old fade-plus-scale is the stock editor preset.
    tags = (
        "{\\an1\\move(%d,%d,%d,%d,0,220)\\fad(180,220)}"
        % (
            _OVERLAY_POS_X,
            _OVERLAY_POS_Y + _OVERLAY_RISE_PX,
            _OVERLAY_POS_X,
            _OVERLAY_POS_Y,
        )
    )
    margin_r = 1080 - _SAFE_RIGHT
    margin_v = 1920 - _SAFE_BOTTOM
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # Alignment 1 = bottom-left. The scrim carries legibility, so the type
        # keeps a 2px keyline rather than the 4px outline + 2px shadow that
        # reads as a sports lower-third. Spacing -1 tightens Poppins Bold at
        # display size.
        f"Style: Overlay,Poppins,{_OVERLAY_FONT_SIZE},&H00FFFFFF,&H00FFFFFF,"
        f"&H00141414,&H00000000,-1,0,0,0,100,100,-1,0,1,2,0,1,"
        f"{_SAFE_LEFT},{margin_r},{margin_v},1",
        f"Style: CTA,Poppins,{_CTA_FONT_SIZE},{cta_color},&H00FFFFFF,"
        f"&H00141414,&H00000000,-1,0,0,0,100,100,-1,0,1,2,0,1,"
        f"{_SAFE_LEFT},{margin_r},{margin_v},1",
        # Drawing-only style for the scrim plate. A small Fontsize keeps the
        # line box from contributing ascent to the \p1 drawing origin.
        "Style: Scrim,Poppins,20,&H00000000,&H00000000,&H00000000,"
        "&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
    ]
    for event in events:
        wrap = (
            _CTA_WRAP_CHARS if event["style"] == "CTA" else _OVERLAY_WRAP_CHARS
        )
        text = _wrap_overlay_text(_ass_escape(event["text"]), wrap)
        if not text:
            continue
        # Scrim first: same Layer, and libass draws same-layer events in file
        # order, so the plate lands under the type.
        lines.append(_scrim_dialogue(event["start"], event["end"]))
        lines.append(
            f"Dialogue: 0,{_format_ass_time(event['start'])},"
            f"{_format_ass_time(event['end'])},{event['style']},,0,0,0,,"
            f"{tags}{text}"
        )
    return "\n".join(lines) + "\n"


# Characters that terminate or re-parse an ffmpeg filter option value and so
# must be backslash-escaped inside one: ':' separates options within a filter,
# ',' separates filters in a -vf chain, ';' separates chains in a filtergraph,
# and "'" opens/closes ffmpeg's own quoting. Unescaped, a single comma in the
# temp path would split the -vf argument and make ffmpeg parse the rest of the
# path as another filter.
_FILTER_ESCAPE_CHARS = (":", ",", ";", "'")


def _filter_path(path: str) -> str:
    r"""Escape a path for use as an ffmpeg filter option value (pure).

    Backslashes become forward slashes (accepted on every platform, and it
    removes Windows' own escape ambiguity), then every filtergraph
    metacharacter is escaped — see _FILTER_ESCAPE_CHARS.
    """
    out = path.replace("\\", "/")
    for ch in _FILTER_ESCAPE_CHARS:
        out = out.replace(ch, f"\\{ch}")
    return out


def _burn_cmd(
    src: str, ass_path: str, dst: str, fontsdir: str | None = None
) -> list[str]:
    """ffmpeg args burning the .ass overlay into the master (pure function).

    The subtitle filter forces a video re-encode, so the pass re-applies the
    master spec (libx264 CRF19 medium, high profile, yuv420p, 30fps CFR, 2s
    closed GOPs, faststart) and stream-copies the audio untouched.
    """
    vf = f"ass={_filter_path(ass_path)}"
    if fontsdir:
        vf += f":fontsdir={_filter_path(fontsdir)}"
    vf += ",fps=30,format=yuv420p"
    return [
        "ffmpeg", "-y", "-i", src,
        "-vf", vf,
        *_MASTER_VIDEO_ARGS,
        "-profile:v", "high",
        "-c:a", "copy",
        "-movflags", "+faststart",
        dst,
    ]


async def _burn_overlays(
    video_bytes: bytes,
    shots: list[dict[str, Any]],
    cta: str,
    brand: dict[str, Any],
    durations: list[float] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Composite the shot plan's overlay text onto the finished master.

    *durations* are the per-shot lengths actually rendered (multi-shot
    concat path); when None (single-call legacy path) the planned durations
    are distributed proportionally across the clip's real ffprobe duration.
    Best-effort by contract: ANY failure (no ffmpeg, ass filter or fonts
    unavailable, encoder error) logs a warning and returns the ORIGINAL
    bytes with overlay_burn='failed:<reason>' — text burning never fails
    the item. Returns (video_bytes, meta_patch).
    """
    try:
        has_text = any(
            str(s.get("overlay_text") or "").strip() for s in shots
        ) or bool(str(cta or "").strip())
        if not has_text:
            return video_bytes, {"overlay_burn": "skipped:no overlay text"}
        if not _ffmpeg_ok():
            logger.warning("overlay burn skipped — ffmpeg unavailable")
            return video_bytes, {"overlay_burn": "failed:ffmpeg unavailable"}
        with tempfile.TemporaryDirectory(prefix="overlay_") as workdir:
            src = os.path.join(workdir, "master.mp4")
            await asyncio.to_thread(_write_bytes, src, video_bytes)
            if durations is None:
                info = await asyncio.to_thread(_probe_shot, src)
                total = float((info or {}).get("duration") or 0.0)
                if total <= 0:
                    total = sum(float(s.get("duration_s") or 0.0) for s in shots)
                durations = _distribute_durations(
                    [float(s.get("duration_s") or 0.0) for s in shots], total
                )
            events = _overlay_events(shots, durations, cta)
            if not events:
                return video_bytes, {
                    "overlay_burn": "skipped:no renderable overlay events"
                }
            ass_path = os.path.join(workdir, "overlay.ass")
            await asyncio.to_thread(
                _write_text,
                ass_path,
                _build_overlay_ass(events, _brand_accent_hex(brand)),
            )
            fontsdir = FONTS_DIR if os.path.isdir(FONTS_DIR) else None
            if fontsdir is None:
                logger.warning(
                    "overlay burn: fonts dir %s missing — relying on "
                    "fontconfig fallback faces",
                    FONTS_DIR,
                )
            dst = os.path.join(workdir, "master_overlay.mp4")
            proc = await asyncio.to_thread(
                _run_ffmpeg,
                _burn_cmd(src, ass_path, dst, fontsdir),
                VIDEO_BURN_TIMEOUT_S,
            )
            if (
                proc.returncode != 0
                or not os.path.exists(dst)
                or os.path.getsize(dst) == 0
            ):
                reason = _stderr_tail(proc, 200) or f"ffmpeg exit {proc.returncode}"
                logger.warning(
                    "overlay burn failed — keeping unburned master: %s", reason
                )
                return video_bytes, {"overlay_burn": f"failed:{reason}"[:220]}
            burned = await asyncio.to_thread(_read_bytes, dst)
            logger.info(
                "Burned %d overlay line(s) onto the master (%d → %d bytes)",
                len(events),
                len(video_bytes),
                len(burned),
            )
            return burned, {"overlay_burn": "ok", "overlay_lines": len(events)}
    except Exception as exc:
        logger.warning("overlay burn failed — keeping unburned master: %s", exc)
        return video_bytes, {"overlay_burn": f"failed:{exc}"[:220]}


# ── Branded end card (post pass) ───────────────────────────────────────────
#
# Reels ended on whatever frame the last i2v happened to land on, with the
# CTA burned over it. Every professionally cut product ad closes on the mark
# instead: a short branded card carrying the logo and the call to action.
# It is also the only frame in the reel guaranteed to be on-brand — the
# generated footage never is.
#
# The card is built at the master spec and concatenated onto the finished
# master, so it costs one short encode rather than a re-render. Best-effort:
# no logo, no ffmpeg, or any failure keeps the reel exactly as it was.

_END_CARD_S = 2.4
# The mark is fitted INSIDE a fixed box rather than scaled to a width, so
# every element below it sits at a known y whatever shape the logo is.
_END_CARD_LOGO_BOX_W = 720
_END_CARD_LOGO_BOX_H = 300
# The lockup is centred on the SAFE area, not the frame. Centring on the
# frame put the button at y=1170, drifting toward the caption chrome; the
# safe band is 240..1420, whose centre is 830.
_END_CARD_LOGO_Y = 560
_END_CARD_CTA_Y = 990
_END_CARD_FONT_SIZE = 60
_END_CARD_CTA_WRAP = 22
# The CTA rides an explicitly drawn chip. libass's BorderStyle 3 boxes each
# LINE separately, so a two-line call to action came out as two differently
# sized rectangles in a ragged step — fine for a subtitle, wrong for a button.
_END_CARD_CHIP_PAD_X = 44
_END_CARD_CHIP_PAD_Y = 30
_END_CARD_CHIP_LINE_H = 74
_END_CARD_CHIP_MAX_W = 780
# Mean advance of Poppins Bold as a fraction of the em. Measured off a
# rendered card: "Shop the pantry range" set 410px wide at 60px, so 21 chars
# x 60 x k = 410 gives k = 0.325. The first guess of 0.56 drew a button
# nearly twice the width of its own label. This only sizes the chip's
# padding — a wrong estimate makes the button roomier or tighter, it can
# never drop a word (unlike the overlay wrap, which is simulated exactly).
_END_CARD_CHAR_EM = 0.34
# A wordmark on its brand colour is the obvious card and the wrong one:
# Naturespan's dark mark on its mid-green measures ~2:1. The mark is fixed
# (no light variant is registered), so the GROUND has to give way.
_MIN_END_CARD_CONTRAST = 4.5
_DEFAULT_CARD_GROUND = "#f4f7f1"


def _hex_to_rgb(value: str | None) -> tuple[int, int, int] | None:
    """'#80c020' → (128, 192, 32), or None if it is not a hex colour (pure)."""
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _end_card_ground(brand: dict[str, Any]) -> str:
    """Card ground: the brand's light neutral when it carries the mark (pure).

    The mark is assumed dark — that is the variant every brand here has — so
    the ground must be light enough to clear _MIN_END_CARD_CONTRAST against
    it. A brand neutral that fails falls back to the default near-white
    rather than shipping a low-contrast wordmark.
    """
    palette = brand.get("color_palette")
    if isinstance(palette, str):
        try:
            palette = json.loads(palette)
        except (ValueError, TypeError):
            palette = None
    if not isinstance(palette, dict):
        palette = {}
    ink = _hex_to_rgb(palette.get("text_dark")) or (0x1A, 0x1A, 0x1A)
    for key in ("neutral_light", "background", "surface"):
        rgb = _hex_to_rgb(palette.get(key))
        if rgb and contrast_ratio(
            relative_luminance(rgb), relative_luminance(ink)
        ) >= _MIN_END_CARD_CONTRAST:
            return "#%02x%02x%02x" % rgb
    return _DEFAULT_CARD_GROUND


def _end_card_chip_box(text: str) -> tuple[int, int]:
    """(width, height) of the CTA chip for already-wrapped text (pure)."""
    lines = text.split("\\N") if text else [""]
    longest = max((len(line) for line in lines), default=0)
    width = round(longest * _END_CARD_FONT_SIZE * _END_CARD_CHAR_EM)
    width = min(_END_CARD_CHIP_MAX_W, width + 2 * _END_CARD_CHIP_PAD_X)
    height = 2 * _END_CARD_CHIP_PAD_Y + len(lines) * _END_CARD_CHIP_LINE_H
    return width, height


def _end_card_ass(cta: str, ground_hex: str, chip_hex: str) -> str:
    """The .ass document for the end card's call to action (pure function).

    The chip is an explicit \\p1 rectangle rather than libass's BorderStyle 3,
    which boxes each LINE separately — a two-line call to action came out as
    two differently sized rectangles in a ragged step.
    """
    text = _wrap_overlay_text(_ass_escape(cta), _END_CARD_CTA_WRAP)
    # The type is knocked out of the chip, so it takes the card's ground.
    # Both come back in the '&HBBGGRR&' form, which serves as a Style colour
    # and as a \1c override unchanged.
    fill = _hex_to_ass_color(ground_hex) or "&HFFFFFF&"
    chip = _hex_to_ass_color(chip_hex) or "&H000000&"
    width, height = _end_card_chip_box(text)
    x0, x1 = 540 - width // 2, 540 + width // 2
    y0, y1 = _END_CARD_CTA_Y - height // 2, _END_CARD_CTA_Y + height // 2
    end = _format_ass_time(_END_CARD_S)
    return "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: End,Poppins,{_END_CARD_FONT_SIZE},{fill},{fill},{fill},"
        "&H00000000,-1,0,0,0,100,100,1,0,1,0,0,5,0,0,0,1",
        # Drawing-only style for the chip, as with the overlay scrim.
        "Style: Chip,Poppins,20,&H00000000,&H00000000,&H00000000,"
        "&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text",
        # Chip first — libass draws same-layer events in file order.
        f"Dialogue: 0,0:00:00.00,{end},Chip,,0,0,0,,"
        f"{{\\an7\\pos(0,0)\\bord0\\shad0\\1c{chip}\\fad(250,0)\\p1}}"
        f"m {x0} {y0} l {x1} {y0} {x1} {y1} {x0} {y1}{{\\p0}}",
        f"Dialogue: 0,0:00:00.00,{end},End,,0,0,0,,"
        f"{{\\an5\\pos(540,{_END_CARD_CTA_Y})\\fad(250,0)}}{text}",
    ])


def _end_card_cmd(
    dst: str,
    ass_path: str,
    logo_path: str | None,
    ground_hex: str,
    fontsdir: str | None,
) -> list[str]:
    """ffmpeg args rendering the end card at the master spec (pure function)."""
    args = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={ground_hex}:s=1080x1920:r=30:d={_END_CARD_S}",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]
    ass = f"ass={_filter_path(ass_path)}"
    if fontsdir:
        ass += f":fontsdir={_filter_path(fontsdir)}"

    # No decorative rule between the mark and the button. One was tried and
    # landed a second green line directly under a wordmark that already
    # carries its own — and since the mark is padded into a fixed box, the
    # gap between its visible baseline and any fixed-y rule varies with
    # whatever logo the brand happens to have.
    parts: list[str] = []
    if logo_path:
        args += ["-i", logo_path]
        # Fit INSIDE a fixed box and pad back out to it, so the rule and the
        # chip below sit at a known y whatever the mark's aspect ratio is.
        parts.append(
            f"[2:v]scale={_END_CARD_LOGO_BOX_W}:{_END_CARD_LOGO_BOX_H}"
            ":force_original_aspect_ratio=decrease,"
            f"pad={_END_CARD_LOGO_BOX_W}:{_END_CARD_LOGO_BOX_H}"
            ":(ow-iw)/2:(oh-ih)/2:color=#00000000[lg];"
        )
        parts.append(f"[0:v][lg]overlay=(W-w)/2:{_END_CARD_LOGO_Y}[a];")
    else:
        parts.append("[0:v]null[a];")
    parts.append(f"[a]{ass},fps=30,format=yuv420p[v]")

    return args + [
        "-filter_complex", "".join(parts),
        "-map", "[v]", "-map", "1:a:0",
        *_MASTER_VIDEO_ARGS,
        "-profile:v", "high",
        *_MASTER_AUDIO_ARGS,
        "-t", f"{_END_CARD_S}",
        "-movflags", "+faststart", dst,
    ]


async def _brand_logo_png(brand: dict[str, Any]) -> bytes | None:
    """Fetch the brand mark and normalize it to PNG, or None."""
    url = str(brand.get("logo_url") or "").strip()
    if not url:
        return None
    try:
        import httpx

        from shared.image_processing import render_logo_png

        if url.startswith(("content-images/", "brand-assets/")):
            bucket, _, obj = url.partition("/")
            raw = await async_download_file(bucket, obj)
        else:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                raw = resp.content
        if not raw:
            return None
        if raw[:5] == b"<?xml" or raw[:4] == b"<svg":
            return await asyncio.to_thread(render_logo_png, raw, 1024)
        return raw
    except Exception as exc:
        logger.warning("end card: could not fetch the brand logo: %s", exc)
        return None


async def _build_end_card(
    brand: dict[str, Any], cta: str, workdir: str
) -> tuple[str | None, dict[str, Any]]:
    """Render the end card into *workdir*, or return None with the reason.

    Built BEFORE the overlay burn on purpose. The card carries the CTA, so
    the burn must know whether it exists — deciding afterwards would either
    ship a reel with no ask, or burn the overlays twice to add one back.
    """
    try:
        if not str(cta or "").strip():
            return None, {"end_card": "skipped:no cta"}
        if not _ffmpeg_ok():
            return None, {"end_card": "failed:ffmpeg unavailable"}
        logo_png = await _brand_logo_png(brand)
        if not logo_png:
            logger.info(
                "end card: no brand logo available — rendering the card "
                "without a mark"
            )
        accent = _brand_accent_hex(brand) or "#000000"
        ground = _end_card_ground(brand)
        logo_path = None
        if logo_png:
            logo_path = os.path.join(workdir, "endcard_logo.png")
            await asyncio.to_thread(_write_bytes, logo_path, logo_png)
        ass_path = os.path.join(workdir, "endcard.ass")
        await asyncio.to_thread(
            _write_text, ass_path, _end_card_ass(cta, ground, accent)
        )
        card = os.path.join(workdir, "endcard.mp4")
        fontsdir = FONTS_DIR if os.path.isdir(FONTS_DIR) else None
        proc = await asyncio.to_thread(
            _run_ffmpeg,
            _end_card_cmd(card, ass_path, logo_path, ground, fontsdir),
            VIDEO_BURN_TIMEOUT_S,
        )
        if proc.returncode != 0 or not os.path.exists(card):
            reason = _stderr_tail(proc, 200) or f"ffmpeg exit {proc.returncode}"
            logger.warning("end card render failed: %s", reason)
            return None, {"end_card": f"failed:{reason}"[:220]}
        return card, {
            "end_card": "ok",
            "end_card_s": _END_CARD_S,
            "end_card_logo": bool(logo_png),
        }
    except Exception as exc:
        logger.warning("end card render failed: %s", exc)
        return None, {"end_card": f"failed:{exc}"[:220]}


async def _attach_end_card(
    video_bytes: bytes, card_path: str, workdir: str
) -> tuple[bytes, dict[str, Any]]:
    """Concatenate an already-rendered end card onto the finished master.

    Best-effort: a failure here returns the ORIGINAL bytes, and the caller
    is left with a reel whose CTA was moved onto a card that never landed —
    so the reason is recorded rather than swallowed.
    """
    try:
        master = os.path.join(workdir, "master_for_card.mp4")
        await asyncio.to_thread(_write_bytes, master, video_bytes)
        out = os.path.join(workdir, "with_card.mp4")
        list_path = os.path.join(workdir, "card_concat.txt")
        await asyncio.to_thread(
            _write_text, list_path, _build_concat_list([master, card_path])
        )
        proc = await asyncio.to_thread(
            _run_ffmpeg, _concat_copy_cmd(list_path, out), VIDEO_CONCAT_TIMEOUT_S
        )
        if proc.returncode != 0 or not os.path.exists(out):
            # The master came out of the burn pass and the card out of the
            # card pass; both target the master spec, but a stream copy can
            # still trip on SPS/PPS differences.
            logger.info(
                "end card stream-copy concat failed — re-encoding: %s",
                _stderr_tail(proc, 160),
            )
            proc = await asyncio.to_thread(
                _run_ffmpeg,
                _concat_reencode_cmd([master, card_path], out),
                VIDEO_CONCAT_TIMEOUT_S,
            )
        if proc.returncode != 0 or not os.path.exists(out):
            reason = _stderr_tail(proc, 200) or f"ffmpeg exit {proc.returncode}"
            logger.warning("end card concat failed: %s", reason)
            return video_bytes, {"end_card": f"failed:concat {reason}"[:220]}
        result = await asyncio.to_thread(_read_bytes, out)
        logger.info("Appended a %.1fs branded end card", _END_CARD_S)
        return result, {}
    except Exception as exc:
        logger.warning("end card concat failed: %s", exc)
        return video_bytes, {"end_card": f"failed:concat {exc}"[:220]}


# ── Audio finishing (post pass) ────────────────────────────────────────────
#
# Nothing in the pipeline had ever measured a reel's loudness. Measured on
# four delivered reels against the -14 LUFS platform target:
#
#     reel        integrated   true peak   range
#     0903e649    -19.9 LUFS     -2.4 dB   20.3 LU
#     70036111    -34.8 LUFS    -12.5 dB   17.1 LU
#     914edae5    -42.6 LUFS    -22.8 dB   26.9 LU
#     d15857a0    -43.0 LUFS    -16.3 dB   21.4 LU
#
# So the reels are not silent — they carry a real track — they are delivered
# 6 to 29 LU under target. At -43 LUFS a viewer scrolling a feed at normal
# volume hears nothing at all, and the 23 LU spread BETWEEN reels means the
# same brand is inaudible in one post and merely quiet in the next. A 20-27
# LU internal range is the other half of it: the concat splices shots with
# wildly different levels, so what audio there is lurches beat to beat.
#
# Runs after the overlay burn, on the finished master. Three jobs, in order:
#
#   1. MEASURE what the master actually carries. "The file has an audio
#      stream" was the only check, and it is true of digital silence.
#   2. Lay a music bed under it — ducked below real diegetic audio, brought
#      up when it is carrying the reel alone — with a fade at each end so
#      the reel neither starts on a hard transient nor stops dead. A bed
#      also masks the noise floor that lifting a -43 LUFS track exposes.
#   3. Normalize to the platform delivery target, in two passes: measure the
#      finished mix, then apply the correction with those measurements.
#
# Best-effort by the same contract as the overlay burn: any failure keeps the
# master untouched and records why.

_AUDIO_EXTS = (".mp3", ".m4a", ".aac", ".wav", ".opus", ".ogg", ".flac")
# Fade at the head and tail of the bed. Short enough not to eat the hook.
_MUSIC_FADE_IN_S = 0.6
_MUSIC_FADE_OUT_S = 1.2
_PEAK_RE = re.compile(r"lavfi\.astats\.Overall\.Peak_level=(-?[0-9.]+|-inf)")


def _astats_cmd(path: str) -> list[str]:
    """ffmpeg args printing overall peak level for a clip (pure function)."""
    return [
        "ffmpeg", "-v", "info", "-nostats", "-i", path,
        "-af", "astats=metadata=1:reset=0,ametadata=print:"
               "key=lavfi.astats.Overall.Peak_level",
        "-vn", "-f", "null", "-",
    ]


def _peak_from_stderr(stderr: str) -> float | None:
    """Loudest overall peak in dBFS from an astats run, or None (pure).

    '-inf' is digital silence and comes back as -inf, which compares below
    any threshold — callers get "silent" rather than "unmeasurable".
    """
    matches = _PEAK_RE.findall(stderr or "")
    if not matches:
        return None
    values = [float("-inf") if m == "-inf" else float(m) for m in matches]
    return max(values)


def _measure_peak_db(path: str) -> float | None:
    """Peak level of a clip's audio in dBFS, or None if unmeasurable."""
    if not _ffmpeg_ok():
        return None
    try:
        proc = _run_ffmpeg(_astats_cmd(path), timeout=180)
    except Exception:
        return None
    try:
        stderr = (proc.stderr or b"").decode("utf-8", errors="replace")
    except AttributeError:  # already str (mocked runs)
        stderr = str(proc.stderr or "")
    return _peak_from_stderr(stderr)


def _has_real_audio(peak_db: float | None) -> bool:
    """True when a measured peak is a real signal rather than silence (pure).

    None means the measurement failed. That is reported as "no real audio"
    on purpose: the pass then lays a bed, which is the safe outcome either
    way — a bed under real diegetic audio is a mix, a bed under silence is
    the whole point.
    """
    if peak_db is None:
        return False
    return peak_db > VIDEO_SILENCE_PEAK_DB


def _music_moods(plan: dict[str, Any], brand: dict[str, Any]) -> list[str]:
    """Mood folder names to try, most specific first (pure function).

    Restricted to MUSIC_MOODS. An open vocabulary would name folders the
    operator has no way to predict, so every reel would fall through to the
    top-level pool and the mood would be decoration.
    """
    candidates = [
        plan.get("music_mood"),
        (brand.get("brand_voice") or {}).get("music_mood")
        if isinstance(brand.get("brand_voice"), dict)
        else None,
    ]
    out: list[str] = []
    for c in candidates:
        slug = _normalize_music_mood(c)
        if slug and slug not in out:
            out.append(slug)
    return out


def _pick_music_bed(
    music_dir: str, moods: Sequence[str], seed: str
) -> str | None:
    """Choose a bed file for this reel, or None when the library is empty.

    Tries each mood sub-directory in order, then the top level. Within a
    pool the choice is deterministic in *seed* (the item id), so a re-render
    of the same item reuses the same bed instead of shuffling the soundtrack
    under a reviewer.
    """
    if not music_dir or not os.path.isdir(music_dir):
        return None

    def pool(directory: str) -> list[str]:
        try:
            names = sorted(
                n for n in os.listdir(directory)
                if n.lower().endswith(_AUDIO_EXTS)
                and os.path.isfile(os.path.join(directory, n))
            )
        except OSError:
            return []
        return [os.path.join(directory, n) for n in names]

    for mood in list(moods) + [""]:
        files = pool(os.path.join(music_dir, mood) if mood else music_dir)
        if files:
            # zlib.crc32 rather than hash(): PYTHONHASHSEED randomizes str
            # hashing per process, which would defeat the whole point.
            return files[zlib.crc32(seed.encode("utf-8")) % len(files)]
    return None


# ffmpeg's loudnorm filter was the obvious tool and it does NOT work on this
# material. Measured across the four delivered reels:
#
#     reel        target   loudnorm two-pass   miss
#     0903e649    -14.0        -11.5 LUFS      +2.5, and +0.3 dBTP (clipped)
#     70036111    -14.0        -21.7 LUFS      -7.7
#     914edae5    -14.0        -18.2 LUFS      -4.2, and -0.1 dBTP
#     d15857a0    -14.0        -20.4 LUFS      -6.4, and +0.2 dBTP (clipped)
#
# Two reasons. loudnorm's dynamic mode rides gain frame by frame, so when the
# input range (17-27 LU here) far exceeds the target it lifts gated-out quiet
# passages into the measurement and drifts off target; and its warmup eats
# most of the correction on a 5s clip. It also missed the true-peak ceiling
# in both directions.
#
# A flat gain has neither problem — it moves integrated loudness by exactly
# the gain applied — so the correction is measured, applied, and re-measured
# until it lands. Measured with this approach the same four reels came in at
# -14.1, -14.4, -14.6 and -15.0 LUFS with true peak between -1.2 and -0.5
# dBTP, none clipping.
_MAX_GAIN_ROUNDS = 4
# Close enough to stop: platform normalization moves everything by more than
# this anyway.
_LOUDNESS_TOLERANCE_LU = 0.5
# Runaway guard. +40 dB would be lifting a track that is essentially a noise
# floor, and the result is amplified hiss rather than a louder reel.
_MAX_MAKEUP_GAIN_DB = 40.0
# alimiter caps the SAMPLE peak. Platforms measure the TRUE (inter-sample)
# peak, which sits above it — and the resample back down to 48k plus the AAC
# encode both add more on top. Measured overshoot past the ceiling was up to
# 1.7 dB, so a -1.5 dB ceiling still delivered +0.2 dBTP. The ceiling is set
# a full 2 dB under the delivery target to absorb that; it costs nothing in
# loudness because the gain search measures AFTER the limiter and simply
# converges to a higher gain.
_LIMITER_CEILING_DB = -3.0
_LIMITER_OVERSAMPLE_HZ = 192000
_EBUR128_I_RE = re.compile(r"^\s*I:\s*(-?[0-9.]+|-inf)\s*LUFS", re.M)
_EBUR128_TP_RE = re.compile(r"^\s*Peak:\s*(-?[0-9.]+|-inf)\s*dBFS", re.M)
_EBUR128_LRA_RE = re.compile(r"^\s*LRA:\s*(-?[0-9.]+)\s*LU", re.M)


def _limiter_chain() -> str:
    """True-peak brick wall: oversample, limit, come back down (pure)."""
    return (
        f"aresample={_LIMITER_OVERSAMPLE_HZ},"
        f"alimiter=level_in=1:level_out=1:limit={_LIMITER_CEILING_DB}dB"
        ":attack=5:release=50:level=disabled,"
        "aresample=48000"
    )


def _parse_ebur128(stderr: str) -> tuple[float, float, float] | None:
    """(integrated LUFS, true peak dBFS, range LU) from an ebur128 summary.

    Reads the LAST match of each: ebur128 logs progress lines throughout and
    prints the summary block at the end. None when the summary is absent —
    the caller must not treat that as "already on target".
    """
    i_matches = _EBUR128_I_RE.findall(stderr or "")
    tp_matches = _EBUR128_TP_RE.findall(stderr or "")
    if not i_matches or not tp_matches:
        return None
    lra_matches = _EBUR128_LRA_RE.findall(stderr or "")

    def num(value: str) -> float:
        return float("-inf") if value == "-inf" else float(value)

    return (
        num(i_matches[-1]),
        num(tp_matches[-1]),
        float(lra_matches[-1]) if lra_matches else 0.0,
    )


def _next_gain(current_db: float, measured_lufs: float) -> float:
    """Gain that should land the next round on target (pure function).

    Clamped both ways: a measurement of -inf (silence) would ask for infinite
    gain, and lifting a noise floor by 40 dB produces amplified hiss rather
    than a louder reel.
    """
    if measured_lufs == float("-inf"):
        return current_db
    proposed = current_db + (VIDEO_TARGET_LUFS - measured_lufs)
    return max(-_MAX_MAKEUP_GAIN_DB, min(_MAX_MAKEUP_GAIN_DB, proposed))


def _audio_finish_cmd(
    src: str,
    dst: str | None,
    duration_s: float,
    music_path: str | None,
    keep_source_audio: bool,
    gain_db: float = 0.0,
) -> list[str]:
    """ffmpeg args mixing the bed in and normalizing to target (pure function).

    *dst* None builds a MEASUREMENT pass: the identical graph, plus ebur128,
    decoded to null. Measuring the assembled mix rather than the source alone
    matters because the bed changes the loudness, and measuring the graph
    rather than an encoded file means each round of the gain search costs a
    decode instead of an encode.

    The bed is looped to cover the reel (a 12s track under a 30s reel would
    otherwise leave the last two thirds bare) and trimmed to the exact
    runtime. Video is stream-copied — this pass must never re-encode picture,
    which would spend a generation of quality on an audio change.
    """
    args = ["ffmpeg", "-y"]
    if dst is None:
        # Measurement runs decode audio only; pulling the video through is
        # pure cost.
        args += ["-vn"]
    args += ["-i", src]
    if music_path:
        args += ["-stream_loop", "-1", "-i", music_path]

    fade_out_at = max(0.0, duration_s - _MUSIC_FADE_OUT_S)
    chains: list[str] = []
    if music_path:
        level = VIDEO_MUSIC_DUCKED_DB if keep_source_audio else VIDEO_MUSIC_SOLO_DB
        chains.append(
            f"[1:a]atrim=0:{duration_s:.3f},asetpts=N/SR/TB,"
            f"volume={level:.1f}dB,"
            f"afade=t=in:st=0:d={_MUSIC_FADE_IN_S},"
            f"afade=t=out:st={fade_out_at:.3f}:d={_MUSIC_FADE_OUT_S}[bed]"
        )
        if keep_source_audio:
            # duration=first keeps the reel's length authoritative; dropout
            # transition 0 stops amix from pumping the bed up whenever the
            # diegetic track goes quiet.
            chains.append(
                "[0:a][bed]amix=inputs=2:duration=first:dropout_transition=0"
                ":normalize=0[mix]"
            )
            label = "[mix]"
        else:
            label = "[bed]"
    else:
        label = "[0:a]"

    tail = f"volume={gain_db:.2f}dB,{_limiter_chain()}"
    if dst is None:
        chains.append(f"{label}{tail},ebur128=peak=true[out]")
        return args + [
            "-filter_complex", ";".join(chains),
            "-map", "[out]", "-f", "null", "-",
        ]
    chains.append(f"{label}{tail}[out]")
    return args + [
        "-filter_complex", ";".join(chains),
        "-map", "0:v:0", "-map", "[out]",
        "-c:v", "copy",
        *_MASTER_AUDIO_ARGS,
        "-shortest", "-movflags", "+faststart", dst,
    ]


async def _finish_audio(
    video_bytes: bytes,
    plan: dict[str, Any],
    brand: dict[str, Any],
    seed: str,
    duration_s: float | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """Lay a music bed under the master and normalize it to platform target.

    Best-effort: ANY failure returns the ORIGINAL bytes with an audio_finish
    reason. Returns (video_bytes, meta_patch). The patch always carries
    `audio` — measured, never assumed — so a silent reel is recorded as one.
    """
    meta: dict[str, Any] = {}
    try:
        if not _ffmpeg_ok():
            return video_bytes, {
                "audio": False, "audio_finish": "failed:ffmpeg unavailable"
            }
        with tempfile.TemporaryDirectory(prefix="audio_") as workdir:
            src = os.path.join(workdir, "master.mp4")
            await asyncio.to_thread(_write_bytes, src, video_bytes)

            peak_db = await asyncio.to_thread(_measure_peak_db, src)
            keep_source_audio = _has_real_audio(peak_db)
            meta["source_peak_db"] = (
                None if peak_db is None or peak_db == float("-inf")
                else round(peak_db, 1)
            )

            if not duration_s or duration_s <= 0:
                info = await asyncio.to_thread(_probe_shot, src)
                duration_s = float((info or {}).get("duration") or 0.0)
            if duration_s <= 0:
                return video_bytes, {
                    **meta, "audio": keep_source_audio,
                    "audio_finish": "failed:unknown duration",
                }

            music_path = await asyncio.to_thread(
                _pick_music_bed,
                VIDEO_MUSIC_DIR,
                _music_moods(plan, brand),
                seed,
            )
            if music_path:
                meta["music_bed"] = os.path.basename(music_path)
            elif not keep_source_audio:
                # Nothing to mix and nothing to normalize — say so loudly
                # rather than shipping a silent reel that claims audio.
                logger.warning(
                    "Reel has no diegetic audio and no music bed in %s — "
                    "shipping SILENT. Drop licensed tracks in that directory "
                    "to give reels a bed.",
                    VIDEO_MUSIC_DIR,
                )
                return video_bytes, {
                    **meta, "audio": False, "audio_finish": "silent:no bed available"
                }

            # ── Converge on the loudness target ────────────────────────────
            # Measure the assembled mix, correct the gain, measure again.
            # Each round is a decode, not an encode, so the search is cheap;
            # only the final render writes a file.
            gain_db = 0.0
            rounds = 0
            first_lufs: float | None = None
            last: tuple[float, float, float] | None = None
            for rounds in range(1, _MAX_GAIN_ROUNDS + 1):
                analysis = await asyncio.to_thread(
                    _run_ffmpeg,
                    _audio_finish_cmd(
                        src, None, duration_s, music_path, keep_source_audio,
                        gain_db=gain_db,
                    ),
                    VIDEO_AUDIO_TIMEOUT_S,
                )
                if analysis.returncode != 0:
                    break
                try:
                    stderr = (analysis.stderr or b"").decode(
                        "utf-8", errors="replace"
                    )
                except AttributeError:  # already str (mocked runs)
                    stderr = str(analysis.stderr or "")
                measured = _parse_ebur128(stderr)
                if measured is None:
                    break
                last = measured
                if first_lufs is None:
                    first_lufs = measured[0]
                if abs(measured[0] - VIDEO_TARGET_LUFS) <= _LOUDNESS_TOLERANCE_LU:
                    break
                nxt = _next_gain(gain_db, measured[0])
                if abs(nxt - gain_db) < 0.05:
                    break  # clamped or already converged — more rounds are waste
                gain_db = nxt

            if first_lufs is not None and first_lufs != float("-inf"):
                meta["measured_lufs"] = round(first_lufs, 1)
            if last is not None:
                meta["delivered_lufs"] = round(last[0], 1) if last[0] != float(
                    "-inf"
                ) else None
                meta["delivered_true_peak_db"] = round(last[1], 1)
                meta["delivered_lra"] = round(last[2], 1)
            meta["gain_db"] = round(gain_db, 2)
            meta["loudness_rounds"] = rounds

            # Apply the converged gain.
            dst = os.path.join(workdir, "master_audio.mp4")
            proc = await asyncio.to_thread(
                _run_ffmpeg,
                _audio_finish_cmd(
                    src, dst, duration_s, music_path, keep_source_audio,
                    gain_db=gain_db,
                ),
                VIDEO_AUDIO_TIMEOUT_S,
            )
            if (
                proc.returncode != 0
                or not os.path.exists(dst)
                or os.path.getsize(dst) == 0
            ):
                reason = _stderr_tail(proc, 200) or f"ffmpeg exit {proc.returncode}"
                logger.warning(
                    "audio finish failed — keeping the unmixed master: %s", reason
                )
                return video_bytes, {
                    **meta,
                    "audio": keep_source_audio,
                    "audio_finish": f"failed:{reason}"[:220],
                }
            mixed = await asyncio.to_thread(_read_bytes, dst)
            on_target = (
                meta.get("delivered_lufs") is not None
                and abs(meta["delivered_lufs"] - VIDEO_TARGET_LUFS)
                <= _LOUDNESS_TOLERANCE_LU * 2
            )
            logger.info(
                "Audio finished: bed=%s diegetic=%s %s → %s LUFS "
                "(%+.1f dB in %d round(s), peak %s dBTP, %d → %d bytes)%s",
                meta.get("music_bed") or "none",
                "kept" if keep_source_audio else "none",
                meta.get("measured_lufs", "?"),
                meta.get("delivered_lufs", "?"),
                gain_db,
                rounds,
                meta.get("delivered_true_peak_db", "?"),
                len(video_bytes),
                len(mixed),
                "" if on_target else " — OFF TARGET",
            )
            return mixed, {
                **meta,
                "audio": True,
                "audio_finish": "ok" if on_target else "ok:off-target",
                "audio_lufs": meta.get("delivered_lufs"),
            }
    except Exception as exc:
        logger.warning("audio finish failed — keeping the unmixed master: %s", exc)
        return video_bytes, {**meta, "audio": False, "audio_finish": f"failed:{exc}"[:220]}


async def render_video(state: VideoState) -> dict[str, Any]:
    """Render the reel — one provider call per planned shot, chained i2v for
    continuity, an ffmpeg concat into the ~30s master final.mp4, then a
    best-effort overlay-text burn pass onto the finished master.

    Shot 1 is i2v from the branded keyframe; every later shot is i2v from the
    last frame of the previous shot's clip. Plans with fewer than
    MIN_RENDER_SHOTS usable shots get their longest beats split in two first
    (the 20s floor is unreachable below 4 shots), and hero-tier durations are
    fitted to Veo's 4/6s billing grid. A plan on a box without ffmpeg/ffprobe
    degrades to the legacy single-call path (~5s clip) with a warning instead
    of failing the item. Progress streams into
    calendar_items.generation_metadata.video_progress as before, with each
    shot mapped to its proportional window.
    """
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

    fitted, dropped = _fit_shot_durations(shots)
    dropped_indices = [s.get("index") for s in dropped]
    if dropped:
        logger.info(
            "render_video: dropped %d lowest-priority shot(s) %s to fit the "
            "%.0fs budget (plan order = priority)",
            len(dropped),
            dropped_indices,
            TARGET_MAX_TOTAL_S,
        )
    # Enforce the reel-length floor: fewer than MIN_RENDER_SHOTS shots can
    # never reach the 20s master-spec minimum, so split the longest beats in
    # two and refit (the refit re-clamps the halves and stretches toward 5s).
    split_shots = len(fitted) < MIN_RENDER_SHOTS
    if split_shots:
        pre_split = len(fitted)
        fitted = _split_to_min_shots(fitted)
        fitted, _ = _fit_shot_durations(fitted)
        logger.info(
            "render_video: split %d-shot plan into %d shots to reach the "
            "%.0fs floor",
            pre_split,
            len(fitted),
            TARGET_MIN_TOTAL_S,
        )
    keyframe = state.get("keyframe_bytes")
    quality_tier = state.get("quality_tier") or "standard"
    if quality_tier == "hero":
        # Veo bills its snapped grid (5s → 6s billed) — fit requests to the
        # grid so aggregate duration AND cost stay inside the 35s spec.
        fitted, hero_dropped = _fit_hero_durations(fitted)
        if hero_dropped:
            dropped_indices += [s.get("index") for s in hero_dropped]
            logger.info(
                "render_video: hero grid fit dropped %d trailing shot(s) %s",
                len(hero_dropped),
                [s.get("index") for s in hero_dropped],
            )
    requested_total = round(sum(s["duration_s"] for s in fitted), 2)
    logger.info(
        "render_video: %d shot(s) fitted to %.2fs (target %.0fs, window "
        "%.0f-%.0fs, tier=%s)",
        len(fitted),
        requested_total,
        TARGET_TOTAL_S,
        TARGET_MIN_TOTAL_S,
        TARGET_MAX_TOTAL_S,
        quality_tier,
    )
    base_key = f"{state['brand_id']}:{item_id}:{state.get('run_id', '')}"

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

    from shared.video import VideoRequest, generate_video

    multi = len(fitted) > 1
    # The multi-shot path needs ffprobe as much as ffmpeg: without probes
    # every clip would look audio-less (real diegetic audio replaced with
    # silence) and duration verification would be skipped entirely.
    ffmpeg_missing = multi and not (_ffmpeg_ok() and _ffprobe_ok())
    if ffmpeg_missing:
        logger.warning(
            "render_video: ffmpeg/ffprobe unavailable — degrading %d-shot "
            "plan to a single-call render (~5s clip)",
            len(fitted),
        )

    # ── Legacy single-call path: 1-shot plan, or no ffmpeg to chain/concat ──
    if not multi or ffmpeg_missing:
        prompt = _build_video_prompt(
            {**plan, "shots": fitted},
            unverified_pack=not state.get("keyframe_verified_pack"),
        )
        duration_s = (
            fitted[0]["duration_s"]
            if not multi
            else min(SINGLE_CALL_MAX_DURATION_S, requested_total)
        )
        try:
            req = VideoRequest(
                mode="i2v" if keyframe else "t2v",
                prompt=prompt,
                image_bytes=keyframe,
                duration_s=duration_s,
                aspect="9:16",
                audio=True,
                quality_tier=quality_tier,
                idempotency_key=base_key[:128],
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
            meta: dict[str, Any] = {
                "provider": result.provider,
                "model": result.model,
                "duration_s": result.duration_s,
                "width": result.width,
                "height": result.height,
                "cost_usd": result.cost_usd,
                "ledger": result.ledger,
                "idempotency_key": req.idempotency_key,
                "shot_count": len(fitted),
                "requested_total_s": requested_total,
            }
            if dropped_indices:
                meta["dropped_shots"] = dropped_indices
            if ffmpeg_missing:
                meta["multi_shot_fallback"] = "ffmpeg/ffprobe unavailable"
            # Burn the overlay text onto the clip (best-effort). No fitted
            # durations exist for a single call — the planned beats are
            # distributed proportionally across the clip's real duration.
            cta_text = str(plan.get("cta") or "")
            with tempfile.TemporaryDirectory(prefix="single_") as cardwork:
                # Same order as the multi-shot path: the card owns the CTA,
                # so it has to exist before the burn decides what to write
                # on the final beat.
                card_path, card_meta = await _build_end_card(
                    state.get("brand") or {}, cta_text, cardwork
                )
                video_bytes, overlay_meta = await _burn_overlays(
                    result.video_bytes,
                    fitted,
                    "" if card_path else cta_text,
                    state.get("brand") or {},
                )
                meta.update(overlay_meta)
                meta.update(card_meta)
                duration_s = result.duration_s
                if card_path:
                    video_bytes, attach_meta = await _attach_end_card(
                        video_bytes, card_path, cardwork
                    )
                    meta.update(attach_meta)
                    if not attach_meta:
                        duration_s = (duration_s or 0.0) + _END_CARD_S
                        meta["duration_s"] = duration_s
            video_bytes, audio_meta = await _finish_audio(
                video_bytes,
                plan,
                state.get("brand") or {},
                seed=str(item_id),
                duration_s=duration_s,
            )
            meta.update(audio_meta)
            return {
                "video_bytes": video_bytes,
                "video_prompt": prompt,
                "video_meta": meta,
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

    # ── Multi-shot path: N provider calls chained i2v, then ffmpeg concat ──
    num = len(fitted)
    # No VERIFIED pack means nothing in this reel is anchored on a real
    # product photo, so every label the model draws is invented. A keyframe
    # may still exist — make_keyframe now keeps a deliberately unreadable one
    # rather than discarding the frame — so ask the flag, not the bytes. Said
    # in every shot prompt rather than once at planning time, which runs
    # before make_keyframe and cannot know.
    unverified_pack = not state.get("keyframe_verified_pack")
    scenes_rewritten = False
    if unverified_pack:
        logger.info(
            "No verified pack for this reel — every shot prompt forbids "
            "readable label copy"
        )
        # The directive alone loses to a scene that asks for a hero bottle
        # with its label to camera; rewrite the scenes so nothing is asking
        # for the frame that produces invented lettering.
        fitted, scenes_rewritten = await _delabel_shot_scenes(fitted)
    shot_prompts = [
        _build_shot_prompt(s, i, num, unverified_pack=unverified_pack)
        for i, s in enumerate(fitted)
    ]
    full_prompt = "\n\n=== SHOT BREAK ===\n\n".join(shot_prompts)
    # generation_ledger becomes an array of per-shot ledger objects.
    shot_ledgers: list[dict[str, Any]] = []
    shot_metas: list[dict[str, Any]] = []
    total_cost = 0.0

    async def _fail_multi(message: str) -> dict[str, Any]:
        # total_cost is read at call time — paid shots completed before the
        # failure surface in the failed video_jobs row's cost_usd column.
        return await _fail(
            {
                **state,
                "video_prompt": full_prompt,
                "video_meta": {
                    "ledger": shot_ledgers,
                    "cost_usd": round(total_cost, 4),
                },
            },
            message,
        )

    try:
        # TemporaryDirectory guarantees partial shot files are cleaned up on
        # every exit path (success, _fail, unexpected exception).
        with tempfile.TemporaryDirectory(prefix=f"reel_{item_id}_") as workdir:
            chain_image = keyframe
            # The frame every re-anchor returns to. Normally the branded
            # keyframe — but make_keyframe drops it and falls back to t2v
            # whenever the product swap did not fire, and gating the cap on
            # `keyframe` alone left THAT reel chaining unbounded: shot 7 sat
            # six generations downstream with nothing to cut back to, which
            # is precisely the case where drift is worst. When there is no
            # keyframe, shot 1's own last frame becomes the anchor.
            anchor_image = keyframe
            # Depth of the CURRENT chain_image: 0 = the anchor itself,
            # 1 = one i2v hop downstream of it, and so on.
            chain_depth = 0
            motion_retries = 0
            shot_paths: list[str] = []
            for i, (shot, shot_prompt) in enumerate(zip(fitted, shot_prompts)):
                if chain_image is None:
                    # No keyframe and no chain yet: this is a text-to-video
                    # shot. Labelling it "keyframe" claimed an anchor that
                    # does not exist.
                    anchor = "t2v"
                elif chain_depth == 0:
                    anchor = "keyframe" if chain_image is keyframe else "anchor"
                else:
                    anchor = f"chain+{chain_depth}"
                req = VideoRequest(
                    mode="i2v" if chain_image else "t2v",
                    prompt=shot_prompt,
                    image_bytes=chain_image,
                    duration_s=shot["duration_s"],
                    aspect="9:16",
                    audio=True,
                    quality_tier=quality_tier,
                    idempotency_key=f"{base_key}:s{i + 1}"[:128],
                )
                try:
                    # Bound the SHOT, not just the run. shared.video gives
                    # every provider in the cascade its own
                    # VIDEO_RENDER_TIMEOUT_S deadline, so an unbounded shot
                    # can run 2-3x that — and the workflow budget
                    # (VIDEO_MAX_REEL_SHOTS x VIDEO_RENDER_TIMEOUT_S +
                    # finishing) only holds if each shot really costs one.
                    # Without this the worker's asyncio.wait_for could cancel
                    # a live render mid-flight, which is what that budget
                    # exists to prevent.
                    result = await asyncio.wait_for(
                        generate_video(
                            req, progress_cb=_wrap_progress(_progress, i, num)
                        ),
                        timeout=_config_settings.VIDEO_RENDER_TIMEOUT_S,
                    )
                except asyncio.TimeoutError:
                    shot_ledgers.append(
                        {"shot": i + 1, "status": "timeout", "ledger": []}
                    )
                    return await _fail_multi(
                        f"render_video: shot {i + 1}/{num} exceeded the "
                        f"{_config_settings.VIDEO_RENDER_TIMEOUT_S}s per-shot "
                        "render budget"
                    )
                except Exception as exc:
                    # A shot failing after the full provider cascade fails the
                    # whole item — a partial reel is worse than a retry.
                    shot_ledgers.append(
                        {
                            "shot": i + 1,
                            "status": "failed",
                            "ledger": getattr(exc, "ledger", []),
                        }
                    )
                    return await _fail_multi(
                        f"render_video failed at shot {i + 1}/{num}: {exc}"
                    )
                path = os.path.join(workdir, f"shot_{i + 1:02d}.mp4")
                await asyncio.to_thread(_write_bytes, path, result.video_bytes)
                total_cost += result.cost_usd or 0.0

                # ── Did the shot actually move? ────────────────────────────
                # i2v fails by returning the input image held for the whole
                # duration. That passes every structural check (right codec,
                # right length, real bytes) and is unmistakable on screen, so
                # it is measured rather than assumed.
                motion = await asyncio.to_thread(_measure_motion, path)
                verdict = _motion_verdict(motion)
                if (
                    verdict
                    and anchor_image
                    and chain_depth > 0
                    and motion_retries < _MAX_MOTION_RETRIES
                ):
                    # A frozen or churning shot usually means the chain frame
                    # was a poor starting point — most often it was itself the
                    # tail of a stalled shot. Re-anchor and pay for one retry.
                    motion_retries += 1
                    logger.warning(
                        "Shot %d/%d looks %s (motion %.2f) — re-rendering from "
                        "the anchor (retry %d/%d)",
                        i + 1, num, verdict, motion or 0.0,
                        motion_retries, _MAX_MOTION_RETRIES,
                    )
                    retry_req = replace(
                        req,
                        mode="i2v",
                        image_bytes=anchor_image,
                        # A fresh key, or a caching provider hands back the
                        # same frozen clip.
                        idempotency_key=f"{base_key}:s{i + 1}:r2"[:128],
                    )
                    try:
                        retry = await asyncio.wait_for(
                            generate_video(
                                retry_req,
                                progress_cb=_wrap_progress(_progress, i, num),
                            ),
                            timeout=_config_settings.VIDEO_RENDER_TIMEOUT_S,
                        )
                    except Exception as exc:
                        # Best-effort: the first clip is already in hand, so a
                        # failed retry keeps it rather than failing the reel.
                        logger.warning(
                            "Shot %d/%d motion retry failed (%s) — keeping the "
                            "%s take",
                            i + 1, num, exc, verdict,
                        )
                    else:
                        retry_path = os.path.join(
                            workdir, f"shot_{i + 1:02d}_r2.mp4"
                        )
                        await asyncio.to_thread(
                            _write_bytes, retry_path, retry.video_bytes
                        )
                        total_cost += retry.cost_usd or 0.0
                        retry_motion = await asyncio.to_thread(
                            _measure_motion, retry_path
                        )
                        # Keep the retry only if it is genuinely better —
                        # otherwise the reel pays twice for a worse take.
                        if _motion_verdict(retry_motion) is None:
                            logger.info(
                                "Shot %d/%d retry accepted (motion %.2f → %.2f)",
                                i + 1, num, motion or 0.0, retry_motion or 0.0,
                            )
                            path, result = retry_path, retry
                            motion, verdict = retry_motion, None
                            chain_depth = 0
                            anchor = "anchor:retry"
                        else:
                            logger.warning(
                                "Shot %d/%d retry still %s (motion %.2f) — "
                                "keeping the first take",
                                i + 1, num,
                                _motion_verdict(retry_motion), retry_motion or 0.0,
                            )

                shot_paths.append(path)
                shot_metas.append(
                    {
                        "index": shot.get("index", i + 1),
                        "provider": result.provider,
                        "model": result.model,
                        "requested_s": shot["duration_s"],
                        "rendered_s": result.duration_s,
                        "cost_usd": result.cost_usd,
                        "anchor": anchor,
                        "motion": round(motion, 2) if motion is not None else None,
                        "motion_verdict": verdict,
                    }
                )
                shot_ledgers.append(
                    {
                        "shot": i + 1,
                        "provider": result.provider,
                        "model": result.model,
                        "cost_usd": result.cost_usd,
                        "anchor": anchor,
                        "motion": round(motion, 2) if motion is not None else None,
                        "ledger": result.ledger,
                    }
                )
                logger.info(
                    "Shot %d/%d rendered: %s/%s %.1fs from %s, motion %s "
                    "(%d bytes, $%.4f)",
                    i + 1,
                    num,
                    result.provider,
                    result.model,
                    result.duration_s,
                    anchor,
                    "n/a" if motion is None else f"{motion:.2f}",
                    len(result.video_bytes),
                    result.cost_usd,
                )
                if i < num - 1:
                    # Chain: the next shot starts from this shot's last frame.
                    # Two things end a chain early, and both skip the
                    # extraction entirely rather than extracting a frame the
                    # next iteration would discard:
                    #
                    #  - the cap. Rendering from a frame that is already
                    #    _MAX_CHAIN_DEPTH hops downstream would put the next
                    #    shot further from the branded keyframe than the
                    #    pack survives.
                    #  - a shot that failed the motion floor. Its last frame
                    #    IS the still that stalled, so chaining off it hands
                    #    the next shot the same dead end.
                    reanchor = None
                    if verdict:
                        reanchor = f"shot {i + 1} looks {verdict}"
                    elif chain_depth >= _MAX_CHAIN_DEPTH:
                        reanchor = f"chain depth {chain_depth} reached the cap"
                    if reanchor and anchor_image:
                        logger.info(
                            "Shot %d/%d will re-anchor (%s)",
                            i + 2, num, reanchor,
                        )
                        chain_image, chain_depth = anchor_image, 0
                        continue
                    chain_image = await asyncio.to_thread(
                        _extract_last_frame, path, workdir, i + 1
                    )
                    if not chain_image:
                        return await _fail_multi(
                            f"render_video: last-frame extraction failed after "
                            f"shot {i + 1}/{num}"
                        )
                    chain_depth += 1
                    if anchor_image is None:
                        # No keyframe: adopt shot 1's last frame as the fixed
                        # reference so later shots have somewhere to cut back
                        # to. It is one generation old rather than zero, but
                        # it bounds the drift instead of letting it compound
                        # across the whole reel.
                        anchor_image = chain_image
                        chain_depth = 0
                        logger.info(
                            "No keyframe — anchoring the reel on shot 1's "
                            "last frame"
                        )

            # ── Normalize non-master shots, then concat ────────────────────
            await _progress(_CONCAT_PROGRESS_START + 1, "concat:normalize")
            norm_paths: list[str] = []
            normalized: list[int] = []
            probes: list[dict[str, Any] | None] = []
            for i, (path, smeta) in enumerate(zip(shot_paths, shot_metas)):
                info = await asyncio.to_thread(_probe_shot, path)
                if smeta["provider"] != "forge" or not _is_master_conformant(info):
                    # forge output is master-encoded by the gateway; fal/veo
                    # clips come back AS-IS and get the finishing pass here.
                    npath = os.path.join(workdir, f"norm_{i + 1:02d}.mp4")
                    proc = await asyncio.to_thread(
                        _run_ffmpeg,
                        _normalize_cmd(
                            path,
                            npath,
                            bool(info and info.get("audio")),
                            (info or {}).get("duration"),
                        ),
                        VIDEO_NORMALIZE_TIMEOUT_S,
                    )
                    if proc.returncode != 0 or not os.path.exists(npath):
                        return await _fail_multi(
                            f"render_video: shot {i + 1} normalization failed: "
                            f"{_stderr_tail(proc)}"
                        )
                    normalized.append(i + 1)
                    path = npath
                    info = await asyncio.to_thread(_probe_shot, path)
                norm_paths.append(path)
                probes.append(info)

            # Stream copy is only safe when every clip came out of the SAME
            # encoder — all forge master-encoded (normalized empty implies
            # every shot was forge-conformant) or all locally normalized in
            # this pass. Mixed sources can probe identically on
            # codec/resolution/fps yet differ in H.264 profile/level/SPS/PPS/
            # timebase/GOP placement, which -c copy splices silently (ffmpeg
            # exits 0, some players glitch at the seams).
            same_encoder = len(normalized) in (0, len(norm_paths))
            uniform = same_encoder and all(
                _is_master_conformant(p) for p in probes
            )
            await _progress(_CONCAT_PROGRESS_START + 2, "concat:join")
            final_path = os.path.join(workdir, "final.mp4")
            if uniform:
                list_path = os.path.join(workdir, "concat.txt")
                await asyncio.to_thread(
                    _write_text, list_path, _build_concat_list(norm_paths)
                )
                concat_mode = "copy"
                proc = await asyncio.to_thread(
                    _run_ffmpeg,
                    _concat_copy_cmd(list_path, final_path),
                    VIDEO_CONCAT_TIMEOUT_S,
                )
                if proc.returncode != 0 or not os.path.exists(final_path):
                    # Stream copy can trip on subtly non-uniform inputs —
                    # retry once with the re-encoding concat before failing.
                    logger.warning(
                        "concat stream-copy failed (%s) — retrying with "
                        "filter_complex re-encode",
                        _stderr_tail(proc, 160),
                    )
                    concat_mode = "reencode"
                    proc = await asyncio.to_thread(
                        _run_ffmpeg,
                        _concat_reencode_cmd(norm_paths, final_path),
                        VIDEO_CONCAT_TIMEOUT_S,
                    )
            else:
                concat_mode = "reencode"
                proc = await asyncio.to_thread(
                    _run_ffmpeg,
                    _concat_reencode_cmd(norm_paths, final_path),
                    VIDEO_CONCAT_TIMEOUT_S,
                )
            if proc.returncode != 0 or not os.path.exists(final_path):
                return await _fail_multi(
                    f"render_video: concat failed: {_stderr_tail(proc)}"
                )

            # ── Verify final duration ≈ sum of the shots ───────────────────
            expected = sum(
                (p or {}).get("duration") or m["requested_s"]
                for p, m in zip(probes, shot_metas)
            )
            final_info = await asyncio.to_thread(_probe_shot, final_path)
            final_duration = float((final_info or {}).get("duration") or 0.0)
            if final_info is not None and expected > 0:
                if final_duration < 0.5 * expected:
                    return await _fail_multi(
                        f"render_video: concat output too short "
                        f"({final_duration:.1f}s vs expected {expected:.1f}s)"
                    )
                if abs(final_duration - expected) > max(1.0, 0.05 * expected):
                    logger.warning(
                        "Final reel duration %.2fs deviates from expected %.2fs",
                        final_duration,
                        expected,
                    )
            video_bytes = await asyncio.to_thread(_read_bytes, final_path)
            final_video = (final_info or {}).get("video") or {}

            # ── Burn the overlay text onto the finished master ─────────────
            # Timing windows use the durations actually rendered (probed per
            # shot, falling back to the fitted request). Best-effort: failure
            # keeps the unburned master.
            await _progress(_CONCAT_PROGRESS_START + 3, "overlay:burn")
            rendered_durations = [
                float((p or {}).get("duration") or m["requested_s"])
                for p, m in zip(probes, shot_metas)
            ]
            cta_text = str(plan.get("cta") or "")
            # Render the card first: it carries the CTA, so whether it exists
            # decides what the burn puts on the final beat.
            card_path, card_meta = await _build_end_card(
                state.get("brand") or {}, cta_text, workdir
            )
            video_bytes, overlay_meta = await _burn_overlays(
                video_bytes,
                fitted,
                # With a card, the final beat keeps its own line and the ask
                # lands on the brand mark instead of over the footage.
                "" if card_path else cta_text,
                state.get("brand") or {},
                durations=rendered_durations,
            )
            overlay_meta = {**overlay_meta, **card_meta}
            if card_path:
                video_bytes, attach_meta = await _attach_end_card(
                    video_bytes, card_path, workdir
                )
                overlay_meta = {**overlay_meta, **attach_meta}
                if not attach_meta:
                    final_duration = (final_duration or 0.0) + _END_CARD_S

            # ── Music bed + platform loudness ──────────────────────────────
            await _progress(_CONCAT_PROGRESS_START + 4, "audio:finish")
            video_bytes, audio_meta = await _finish_audio(
                video_bytes,
                plan,
                state.get("brand") or {},
                seed=str(item_id),
                duration_s=final_duration or None,
            )
            overlay_meta = {**overlay_meta, **audio_meta}
            await _progress(100, "render:complete")
    except Exception as exc:
        return await _fail_multi(f"render_video failed: {exc}")

    providers = list(dict.fromkeys(m["provider"] for m in shot_metas))
    models = list(dict.fromkeys(m["model"] for m in shot_metas))
    logger.info(
        "Reel rendered: %d shots via %s, %.1fs, concat=%s (%d bytes, $%.4f)",
        num,
        "+".join(providers),
        final_duration or expected,
        concat_mode,
        len(video_bytes),
        total_cost,
    )
    meta = {
        "provider": "+".join(providers),
        "model": "+".join(models),
        "duration_s": final_duration or round(expected, 2),
        "width": final_video.get("width") or 1080,
        "height": final_video.get("height") or 1920,
        "cost_usd": round(total_cost, 4),
        # Per-shot ledger array — persisted into video_jobs.generation_ledger.
        "ledger": shot_ledgers,
        "idempotency_key": base_key[:128],
        "shot_count": num,
        "requested_total_s": requested_total,
        "shots": shot_metas,
        "dropped_shots": dropped_indices,
        "normalized_shots": normalized,
        "concat_mode": concat_mode,
        # Recorded because it changes what the reel SHOWS, not just how it was
        # made: an unverified-pack reel deliberately has no legible pack.
        "unverified_pack": unverified_pack,
        "scenes_delabelled": scenes_rewritten,
        **overlay_meta,
    }
    if split_shots:
        meta["split_to_min_shots"] = True
    if quality_tier == "hero":
        meta["hero_grid_fit"] = True
    return {
        "video_bytes": video_bytes,
        "video_prompt": full_prompt,
        "video_meta": meta,
    }


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
                "overlay_burn": meta.get("overlay_burn"),
                "overlay_lines": meta.get("overlay_lines"),
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
                        # MEASURED by the audio finishing pass, not assumed.
                        # This was hardcoded True while every reel shipped
                        # silent, so the column said nothing at all.
                        "audio": bool(meta.get("audio")),
                        "audio_finish": meta.get("audio_finish"),
                        "audio_lufs": meta.get("audio_lufs"),
                        "music_bed": meta.get("music_bed"),
                        "quality_tier": state.get("quality_tier") or "standard",
                        "width": meta.get("width"),
                        "height": meta.get("height"),
                        "shot_count": meta.get("shot_count"),
                        "requested_total_s": meta.get("requested_total_s"),
                        "concat_mode": meta.get("concat_mode"),
                        "dropped_shots": meta.get("dropped_shots"),
                        "overlay_burn": meta.get("overlay_burn"),
                        "overlay_lines": meta.get("overlay_lines"),
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
