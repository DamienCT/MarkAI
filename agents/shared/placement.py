"""Smart placement for the big "headline" overlay (ad / poster text).

The Regenerate-Pub path used to drop the headline at a fixed top-center spot
regardless of the image, which often landed it over the product. This module
picks a good spot + size:

  1. ``vision_headline_placement`` — a vision LLM LOOKS at the image and returns
     a free center (text_xy) on the cleanest empty area + a size class.
  2. ``variance_headline_placement`` — a deterministic fallback that scans
     horizontal bands and picks the lowest-variance (cleanest) one.
  3. ``plan_headline_placement`` — tries vision first, falls back to variance.

All return ``(text_xy, text_scale, text_width, headline_colors, font_family,
logo_xy)``: text_xy is a normalized (x, y) center in 0..1, text_scale multiplies
the headline font size, text_width is the wrap width as a fraction of image
width (so the text re-flows to fit the chosen empty area), headline_colors maps
a word index (as a string) to a "#RRGGBB" color for emphasized words (empty =
all white), font_family is one of the bundled headline fonts, and logo_xy is a
normalized (x, y) center for the brand logo placed CLEAR of the headline so the
two never overlap (None → caller uses its own heuristic).
"""

from __future__ import annotations

import base64 as _b64
import logging
from io import BytesIO

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Size class → text_scale (matches overlay_logo_and_text headline sizing).
_SIZE_SCALE = {"s": 0.8, "m": 1.05, "l": 1.35}
_DEFAULT_SCALE = 1.0
_DEFAULT_WIDTH = 0.86
_DEFAULT_FONT = "Montserrat"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _norm_hex(v) -> str | None:
    """Validate/normalize a '#RRGGBB' (or 'RRGGBB') string."""
    if not isinstance(v, str):
        return None
    h = v.strip().lstrip("#")
    if len(h) == 6:
        try:
            int(h, 16)
            return "#" + h.lower()
        except ValueError:
            return None
    return None


def variance_headline_placement(
    image_data: bytes,
) -> tuple[tuple[float, float], float, float, dict, str, tuple[float, float]]:
    """Pick the cleanest horizontal band for the headline (no LLM).

    Scans candidate bands and returns the center of the one with the lowest
    pixel variance — i.e. the calmest, emptiest strip (sky, gradient, table,
    blur). The hero product usually sits dead-center and is busy, so it gets
    rejected naturally by its high variance. Also measures how wide that clean
    band is around the center so the wrap width adapts to the space.
    """
    try:
        img = Image.open(BytesIO(image_data)).convert("L")
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("variance placement: cannot open image (%s)", exc)
        return ((0.5, 0.15), _DEFAULT_SCALE, _DEFAULT_WIDTH, {}, _DEFAULT_FONT, (0.85, 0.88))

    arr = np.asarray(img, dtype=np.float32)
    h, w = arr.shape
    if h == 0 or w == 0:
        return ((0.5, 0.15), _DEFAULT_SCALE, _DEFAULT_WIDTH, {}, _DEFAULT_FONT, (0.85, 0.88))

    # Sample the central 86% of the width (where the text would sit).
    x0, x1 = int(w * 0.07), int(w * 0.93)
    band_half = max(1, int(h * 0.11))  # strip ≈ 22% of height

    best_y = 0.15
    best_var = float("inf")
    best_y0, best_y1 = 0, min(h, 2 * band_half)
    for cy_frac in (0.15, 0.30, 0.50, 0.70, 0.85):
        cy = int(h * cy_frac)
        y0 = max(0, cy - band_half)
        y1 = min(h, cy + band_half)
        region = arr[y0:y1, x0:x1]
        if region.size == 0:
            continue
        var = float(np.var(region))
        if var < best_var:
            best_var = var
            best_y = cy_frac
            best_y0, best_y1 = y0, y1

    # Width: grow a centered window across columns that stay "clean" (per-column
    # variance below a soft threshold) so the wrap width hugs the empty space.
    width_frac = _DEFAULT_WIDTH
    band = arr[best_y0:best_y1, :]
    if band.size and band.shape[0] > 1:
        col_var = np.var(band, axis=0)
        thr = float(np.percentile(col_var, 55))
        center = w // 2
        left = center
        while left > 0 and col_var[left - 1] <= thr:
            left -= 1
        right = center
        while right < w - 1 and col_var[right + 1] <= thr:
            right += 1
        width_frac = _clamp((right - left) / float(w), 0.4, 0.92)

    logger.info(
        "variance headline placement: y=%.2f width=%.2f (variance=%.0f)",
        best_y, width_frac, best_var,
    )
    # Logo goes to a corner in the vertical band OPPOSITE the headline so the
    # two never overlap (headline is a centered horizontal band).
    logo_xy = (0.85, 0.88) if best_y < 0.5 else (0.85, 0.12)

    # No semantic color/font choice without an LLM — white text, default font.
    return ((0.5, best_y), _DEFAULT_SCALE, width_frac, {}, _DEFAULT_FONT, logo_xy)


async def vision_headline_placement(
    image_data: bytes,
    headline_text: str,
    brand_colors: dict | None = None,
) -> tuple[tuple[float, float], float, float, dict, str, tuple[float, float] | None] | None:
    """Ask a vision LLM where a big headline should go, how big, how wide,
    which word(s) to color, which font, and where the logo goes (clear of it).

    Returns ``(text_xy, text_scale, text_width, headline_colors, font_family,
    logo_xy)`` or ``None`` on any failure (caller falls back to variance).
    """
    from shared.llm import chat_completion, parse_llm_json
    from shared.image_processing import HEADLINE_FONTS

    words = (headline_text or "").split()
    n_words = len(words)
    # Brand palette the model may use for emphasis (legibility permitting).
    palette = []
    for key in ("primary", "secondary", "accent"):
        hx = _norm_hex((brand_colors or {}).get(key))
        if hx:
            palette.append(f"{key} {hx}")
    palette_str = ", ".join(palette) if palette else "(no brand palette — use white or a clearly legible color)"

    try:
        b64 = _b64.b64encode(image_data).decode("ascii")
    except Exception as exc:  # pragma: no cover
        logger.warning("vision placement: cannot encode image (%s)", exc)
        return None
    data_url = f"data:image/png;base64,{b64}"

    system = (
        "You decide WHERE to place a large marketing HEADLINE (big bold title "
        "text, possibly 2-3 lines) on an advertising image, BEFORE it is drawn. "
        "Look carefully at the image and find the cleanest, emptiest area with "
        "enough room for the headline. NEVER place it over the hero product, "
        "packaging, food, drinks, logos, faces, or hands — put it on negative "
        "space (open sky, a wall, a table, a gradient, or soft blur).\n\n"
        "Choose:\n"
        "- text_xy: the CENTER of the text block, as two fractions x and y "
        "between 0 and 1 (x=0 left, x=1 right, y=0 top, y=1 bottom).\n"
        "- text_size: 's' (small), 'm' (medium) or 'l' (large) — how big the "
        "headline should be to fill the empty area WITHOUT crowding the product "
        "or running off the edges.\n"
        "- text_width: the fraction of image width the text block should span "
        "(0.3-0.95), matching the WIDTH of the empty area so the text wraps to "
        "fit it and never overlaps the product. Use a small value for a narrow "
        "empty column, a large value for a wide-open area.\n"
        "- text_colors: OPTIONALLY emphasize 1 or 2 KEY words by coloring them. "
        f"The headline has {n_words} words (0-indexed when split on spaces). "
        f"Brand palette for emphasis: {palette_str}. Only color a word if the "
        "color stays clearly legible on the background at that spot; the rest "
        "stay white. Default to NO colors (empty) if unsure. Map word index "
        '(as a string) to a "#RRGGBB" hex.\n'
        "- font_family: pick ONE font that matches the brand/product mood: "
        "'Montserrat' (modern, clean, versatile), 'Poppins' (friendly, rounded, "
        "approachable), 'Oswald' (bold, condensed, high-impact), 'Playfair "
        "Display' (elegant serif, premium/luxury), 'Dancing Script' (handwritten, "
        "casual/playful). Default 'Montserrat' if unsure.\n"
        "- logo_xy: the CENTER of the brand logo as x and y fractions 0..1, in a "
        "clean area in a DIFFERENT part of the image from the headline so the "
        "logo and headline NEVER overlap (a corner far from the headline is "
        "ideal). Avoid the hero product, faces, and packaging.\n\n"
        "Return strict JSON only:\n"
        '{"text_xy": {"x": 0.0-1.0, "y": 0.0-1.0}, '
        '"text_size": "s"|"m"|"l", "text_width": 0.3-0.95, '
        '"text_colors": {"<word_index>": "#RRGGBB"}, '
        '"font_family": "Montserrat", '
        '"logo_xy": {"x": 0.0-1.0, "y": 0.0-1.0}, '
        '"reason": "where the empty area is"}'
    )
    user_text = (
        f'Plan the placement for this headline: "{(headline_text or "").strip()[:200]}". '
        "Where should it go, how big, which key word(s) to color, and which font?"
    )
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    try:
        result = await chat_completion(
            messages,
            category="vision",
            temperature=0.2,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("vision headline placement LLM call failed: %s", exc)
        return None

    plan = parse_llm_json(str(result), fallback=None)
    if not isinstance(plan, dict):
        logger.warning("vision headline placement returned non-dict: %r", plan)
        return None

    xy = plan.get("text_xy")
    cx = cy = None
    if isinstance(xy, dict):
        cx, cy = xy.get("x"), xy.get("y")
    elif isinstance(xy, (list, tuple)) and len(xy) == 2:
        cx, cy = xy[0], xy[1]
    try:
        cx = _clamp(float(cx), 0.08, 0.92)
        cy = _clamp(float(cy), 0.08, 0.92)
    except (TypeError, ValueError):
        logger.warning("vision headline placement: bad text_xy %r", xy)
        return None

    size = str(plan.get("text_size", "m")).strip().lower()[:1]
    scale = _SIZE_SCALE.get(size, _DEFAULT_SCALE)

    try:
        width = _clamp(float(plan.get("text_width")), 0.3, 0.95)
    except (TypeError, ValueError):
        width = _DEFAULT_WIDTH

    # Per-word colors: keep only valid hex on in-range word indices.
    colors: dict[str, str] = {}
    raw_colors = plan.get("text_colors")
    if isinstance(raw_colors, dict):
        for k, v in raw_colors.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            hx = _norm_hex(v)
            if hx and 0 <= idx < n_words:
                colors[str(idx)] = hx

    # Font: must be one of the bundled headline fonts (case-insensitive match).
    font = _DEFAULT_FONT
    raw_font = str(plan.get("font_family", "")).strip()
    for f in HEADLINE_FONTS:
        if f.lower() == raw_font.lower():
            font = f
            break

    # Logo position, kept clear of the headline. None → caller's own heuristic.
    logo_xy: tuple[float, float] | None = None
    lxy = plan.get("logo_xy")
    lcx = lcy = None
    if isinstance(lxy, dict):
        lcx, lcy = lxy.get("x"), lxy.get("y")
    elif isinstance(lxy, (list, tuple)) and len(lxy) == 2:
        lcx, lcy = lxy[0], lxy[1]
    try:
        logo_xy = (_clamp(float(lcx), 0.05, 0.95), _clamp(float(lcy), 0.05, 0.95))
    except (TypeError, ValueError):
        logo_xy = None

    logger.info(
        "vision headline placement: xy=(%.2f,%.2f) size=%s width=%.2f colors=%s font=%s logo=%s (%s)",
        cx, cy, size, width, colors, font, logo_xy, str(plan.get("reason", ""))[:120],
    )
    return ((cx, cy), scale, width, colors, font, logo_xy)


async def plan_headline_placement(
    image_data: bytes,
    headline_text: str,
    brand_colors: dict | None = None,
) -> tuple[tuple[float, float], float, float, dict, str, tuple[float, float] | None]:
    """Vision first, deterministic variance band as a fallback.

    Always returns ``(text_xy, text_scale, text_width, headline_colors,
    font_family, logo_xy)``.
    """
    plan = await vision_headline_placement(image_data, headline_text, brand_colors)
    if plan is not None:
        return plan
    logger.info("headline placement: falling back to variance heuristic")
    return variance_headline_placement(image_data)
