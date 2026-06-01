"""Image processing utilities for the content pipeline.

Provides:
- SVG-to-PNG logo rendering (ImageMagick)
- Smart logo placement on monotone/low-contrast regions
- Text overlay with semi-transparent background
- Social platform mockup generation (Instagram, Facebook, LinkedIn, X)
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# ── Font loading ─────────────────────────────────────────────────

# Try multiple font paths (Linux containers + Windows dev)
_FONT_PATHS = {
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ],
    "light": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/segoeuil.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


def _load_font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS.get(weight, _FONT_PATHS["regular"]):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ── Logo rendering ───────────────────────────────────────────────


def render_logo_png(svg_bytes: bytes, size: int = 1024) -> bytes | None:
    """Render an SVG logo to transparent PNG bytes using ImageMagick.

    Returns None if ImageMagick is not available.
    """
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as svg_f:
        svg_f.write(svg_bytes)
        svg_path = svg_f.name

    png_path = svg_path.replace(".svg", ".png")

    try:
        subprocess.run(
            [
                "magick",
                "-background",
                "none",
                "-density",
                "300",
                svg_path,
                "-resize",
                f"{size}x{size}",
                png_path,
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return Path(png_path).read_bytes()
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.error(
            "ImageMagick not available — cannot render SVG to PNG. Install ImageMagick."
        )
        return None
    finally:
        Path(svg_path).unlink(missing_ok=True)
        Path(png_path).unlink(missing_ok=True)


# ── Smart logo placement ─────────────────────────────────────────


def find_best_logo_position(
    image_data: bytes,
    logo_w: int,
    logo_h: int,
    margin: int = 40,
) -> tuple[int, int]:
    """Find the most monotone/low-contrast region for logo placement.

    Scans candidate corner positions and picks the one with lowest pixel
    variance — sky, solid surfaces, shadows, etc.

    NEVER returns bottom-left or bottom-right — the bottom region is reserved
    for the text overlay bar which can span a significant width.
    """
    img = Image.open(BytesIO(image_data)).convert("RGB")
    arr = np.array(img, dtype=np.float32)
    w, h = img.size

    candidates = {
        "top-right": (w - logo_w - margin, margin),
        "top-left": (margin, margin),
    }

    best_pos = (w - logo_w - margin, margin)  # default: top-right
    best_var = float("inf")

    for name, (cx, cy) in candidates.items():
        cx = max(0, min(cx, max(0, w - logo_w)))
        cy = max(0, min(cy, max(0, h - logo_h)))
        region = arr[cy : cy + logo_h, cx : cx + logo_w]
        var = float(np.var(region))
        if var < best_var:
            best_var = var
            best_pos = (cx, cy)

    logger.info("Logo placement selected (variance=%.0f)", best_var)
    return best_pos


def analyze_logo_region_brightness(
    image_data: bytes,
    logo_w: int,
    logo_h: int,
    margin: int = 40,
) -> tuple[float, float]:
    """Analyze the brightness and variance of the region where the logo will be placed.

    Returns (mean_brightness, variance) where brightness is 0-255.
    - mean_brightness < 100  → dark region  → use light/white logo
    - mean_brightness > 160  → light region → use dark/primary logo
    - high variance (>2000)  → busy region  → use watermark
    """
    img = Image.open(BytesIO(image_data)).convert("RGB")
    arr = np.array(img, dtype=np.float32)
    w, h = img.size

    # Use the same placement logic to find where the logo will go
    lx, ly = find_best_logo_position(image_data, logo_w, logo_h, margin)

    # Clamp to image bounds
    lx = max(0, min(lx, w - logo_w))
    ly = max(0, min(ly, h - logo_h))

    region = arr[ly : ly + logo_h, lx : lx + logo_w]
    if region.size == 0:
        return 128.0, 0.0

    # Convert to grayscale luminance
    gray = 0.299 * region[:, :, 0] + 0.587 * region[:, :, 1] + 0.114 * region[:, :, 2]
    mean_brightness = float(np.mean(gray))
    variance = float(np.var(gray))

    logger.info(
        "Logo region analysis: brightness=%.0f, variance=%.0f",
        mean_brightness,
        variance,
    )
    return mean_brightness, variance


def select_logo_variant(
    brightness: float,
    variance: float,
    available_labels: list[str],
) -> str:
    """Select the best logo variant based on image brightness at the placement region.

    Label keys match the UI (frontend LogosTab): primary, icon, watermark, dark, light.
    Semantically — 'dark' is the variant FOR dark backgrounds (i.e. a light
    logo); 'light' is the variant FOR light backgrounds (i.e. a dark logo).

    Priority logic:
    - Very busy background → watermark if available (rare — threshold raised
      because watermark prints too faint to be legible on most photos)
    - Dark background (brightness < 100) → dark variant (light logo for dark bg)
    - Light background (brightness > 160) → light variant (dark logo for light bg)
    - Mid-tone → primary
    """
    labels = set(available_labels)

    # Only fall back to watermark when the background is genuinely chaotic
    # (sky + faces + product) AND no proper dark/light variant exists. The
    # earlier 2000 threshold was triggering on normal mid-frame textures.
    if variance > 5000 and "watermark" in labels and not (
        "dark" in labels or "light" in labels
    ):
        return "watermark"

    # Dark background → need a light-colored logo
    if brightness < 100:
        for pref in ["dark", "light", "primary", "icon"]:
            if pref in labels:
                return pref

    # Light background → need a dark-colored logo
    if brightness > 160:
        for pref in ["light", "primary", "dark", "icon"]:
            if pref in labels:
                return pref

    # Mid-tone fallback
    for pref in ["primary", "light", "dark", "icon"]:
        if pref in labels:
            return pref
    return available_labels[0] if available_labels else "primary"


# Logos with a wordmark (text alongside the symbol) need more width to be
# legible; icon-only marks (favicon/watermark) become visually heavy at the
# same width and should be scaled down. Tuned smaller after user feedback
# that the overlay was visually overpowering the product.
_LOGO_SCALE_BY_VARIANT = {
    "primary": 0.17,
    "light": 0.17,
    "dark": 0.17,
    "icon": 0.10,
    "watermark": 0.10,
}


def scale_for_logo_variant(variant: str) -> float:
    """Return the recommended logo_scale for a given variant label."""
    return _LOGO_SCALE_BY_VARIANT.get(variant, 0.18)


# ── Logo + text overlay ──────────────────────────────────────────


_TEXT_ANCHORS = {"bottom-left", "bottom-right", "top-left", "top-right"}
_LOGO_ANCHORS = {"top-left", "top-right", "bottom-left", "bottom-right"}


def _anchor_to_position(
    anchor: str, box_w: int, box_h: int, img_w: int, img_h: int, margin: int
) -> tuple[int, int]:
    """Convert an anchor keyword to a pixel (x, y) top-left coordinate."""
    if anchor == "top-left":
        return (margin, margin)
    if anchor == "top-right":
        return (max(margin, img_w - box_w - margin), margin)
    if anchor == "bottom-left":
        return (margin, max(margin, img_h - box_h - margin))
    if anchor == "bottom-right":
        return (
            max(margin, img_w - box_w - margin),
            max(margin, img_h - box_h - margin),
        )
    return (margin, margin)


def overlay_logo_and_text(
    image_data: bytes,
    logo_data: bytes,
    text_line1: str,
    text_line2: str | None = None,
    logo_opacity: float = 0.95,
    logo_scale: float = 0.17,
    logo_anchor: str | None = None,
    text_anchor: str | None = None,
) -> bytes:
    """Overlay a transparent logo on the best monotone area + text bar.

    ``logo_anchor`` / ``text_anchor`` are corner keywords
    ('top-left'|'top-right'|'bottom-left'|'bottom-right') typically supplied
    by the vision-critic step. When unset, the legacy heuristics are used:
    variance-based corner selection for the logo, and bottom-left for the
    text bar.

    Returns the composited image as PNG bytes.
    """
    base = Image.open(BytesIO(image_data)).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # --- Logo ---
    logo = Image.open(BytesIO(logo_data)).convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    if logo.width == 0 or logo.height == 0:
        logger.warning("Logo has zero dimensions — skipping logo overlay")
        # Still apply text overlay below, so don't return early
        logo = None
    logo_w = int(base.width * logo_scale) if logo else 0
    logo_h = (
        int(logo.height * (logo_w / logo.width))
        if (logo and logo_w > 0 and logo.width > 0)
        else 0
    )
    if logo and logo_w > 0 and logo_h > 0:
        logo = logo.resize((logo_w, logo_h), Image.LANCZOS)
    else:
        logo = None

    if logo is not None:
        alpha = logo.split()[3]
        alpha = ImageEnhance.Brightness(alpha).enhance(logo_opacity)
        logo.putalpha(alpha)

        if logo_anchor in _LOGO_ANCHORS:
            lx, ly = _anchor_to_position(
                logo_anchor, logo_w, logo_h, base.width, base.height,
                margin=int(base.width * 0.04),
            )
        else:
            lx, ly = find_best_logo_position(image_data, logo_w, logo_h)
        overlay.paste(logo, (lx, ly), logo)

    # --- Text overlay (frosted glass card) ---
    # The card is a blurred crop of the underlying photo + a semi-transparent
    # tint (dark on bright backgrounds, light on dark backgrounds) so it stays
    # legible across very different scenes without us having to hand-tune
    # opacity per image. Sizing trimmed down from the original spec — the
    # earlier card was visually overpowering the product.
    font_large = _load_font(int(base.width * 0.030), "regular")
    font_small = _load_font(int(base.width * 0.019), "light")
    margin = int(base.width * 0.04)
    pad_x = max(14, int(base.width * 0.014))
    pad_y = max(10, int(base.width * 0.010))
    radius = max(12, int(base.width * 0.011))
    max_text_w = int(base.width * 0.72) - 2 * pad_x  # cap card to ~72% of image width

    # Truncate text to fit within image width
    def _fit_text(text: str, font) -> str:
        if not text:
            return text
        w = draw.textbbox((0, 0), text, font=font)[2]
        if w <= max_text_w:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = text[:mid].rstrip() + "\u2026"
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_text_w:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "\u2026" if lo < len(text) else text

    text_line1 = _fit_text(text_line1, font_large)
    if text_line2:
        text_line2 = _fit_text(text_line2, font_small)

    bbox1 = draw.textbbox((0, 0), text_line1, font=font_large)
    text_w1, text_h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    line_gap = max(6, int(base.width * 0.006))
    text_w2, text_h2 = 0, 0
    if text_line2:
        bbox2 = draw.textbbox((0, 0), text_line2, font=font_small)
        text_w2, text_h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]

    total_w = max(text_w1, text_w2)
    total_h = text_h1 + (text_h2 + line_gap if text_line2 else 0)

    card_w_full = total_w + 2 * pad_x
    card_h_full = total_h + 2 * pad_y

    anchor = text_anchor if text_anchor in _TEXT_ANCHORS else "bottom-left"
    if anchor == "bottom-left":
        card_x1 = margin
        card_y1 = base.height - margin - card_h_full
    elif anchor == "bottom-right":
        card_x1 = base.width - margin - card_w_full
        card_y1 = base.height - margin - card_h_full
    elif anchor == "top-left":
        card_x1 = margin
        card_y1 = margin
    else:  # top-right
        card_x1 = base.width - margin - card_w_full
        card_y1 = margin

    card_x2 = card_x1 + card_w_full
    card_y2 = card_y1 + card_h_full
    # Clamp to image bounds defensively
    card_x1 = max(card_x1, 0)
    card_y1 = max(card_y1, 0)
    card_x2 = min(card_x2, base.width)
    card_y2 = min(card_y2, base.height)
    card_w = card_x2 - card_x1
    card_h = card_y2 - card_y1

    # Crop a slightly larger region so the Gaussian blur has clean edges,
    # then crop back to the card dimensions after blurring.
    blur_pad = max(8, int(base.width * 0.012))
    src_left = max(0, card_x1 - blur_pad)
    src_top = max(0, card_y1 - blur_pad)
    src_right = min(base.width, card_x2 + blur_pad)
    src_bottom = min(base.height, card_y2 + blur_pad)
    under = base.crop((src_left, src_top, src_right, src_bottom))
    blur_radius = max(12, int(base.width * 0.020))
    blurred = under.filter(ImageFilter.GaussianBlur(radius=blur_radius))

    # Average luminance of the blurred backdrop drives tint direction.
    sample = blurred.convert("L").resize((32, 32), Image.LANCZOS)
    avg_lum = float(np.array(sample).mean())
    bright_bg = avg_lum > 128

    if bright_bg:
        tint_rgba = (10, 12, 16, 130)         # dark tint over bright photos
        text_color_main = (255, 255, 255, 245)
        text_color_sub = (255, 255, 255, 215)
        border_rgba = (255, 255, 255, 90)
    else:
        tint_rgba = (245, 245, 248, 140)      # light tint over dark photos
        text_color_main = (18, 20, 24, 250)
        text_color_sub = (40, 44, 50, 220)
        border_rgba = (255, 255, 255, 130)

    tint_layer = Image.new("RGBA", blurred.size, tint_rgba)
    frosted_full = Image.alpha_composite(blurred.convert("RGBA"), tint_layer)

    # Slice the frosted region back down to the card rect (we cropped extra
    # for the blur \u2014 that extra is discarded here).
    inner_left = card_x1 - src_left
    inner_top = card_y1 - src_top
    frosted_card = frosted_full.crop(
        (inner_left, inner_top, inner_left + card_w, inner_top + card_h)
    )

    # Rounded-rectangle mask gives the card its soft corners.
    card_mask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle(
        (0, 0, card_w, card_h), radius=radius, fill=255
    )

    # Paste the frosted card directly into the base image (under the
    # logo + text overlay we composite at the very end).
    base.paste(frosted_card, (card_x1, card_y1), card_mask)

    # 1px hairline border drawn on the overlay layer for a clean edge.
    draw.rounded_rectangle(
        (card_x1, card_y1, card_x2 - 1, card_y2 - 1),
        radius=radius,
        outline=border_rgba,
        width=1,
    )

    text_x = card_x1 + pad_x
    text_y = card_y1 + pad_y
    draw.text((text_x, text_y), text_line1, font=font_large, fill=text_color_main)
    if text_line2:
        text_y += text_h1 + line_gap
        draw.text((text_x, text_y), text_line2, font=font_small, fill=text_color_sub)

    result = Image.alpha_composite(base, overlay)
    buf = BytesIO()
    result.convert("RGB").save(buf, format="PNG", quality=95)
    return buf.getvalue()


# ── Social platform mockups ──────────────────────────────────────


def _center_crop_square(img: Image.Image, target_size: int) -> Image.Image:
    """Center-crop an image to square, then resize. Avoids stretching non-square inputs."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((target_size, target_size), Image.LANCZOS)


def resize_preserve_aspect(
    img: Image.Image, target_size: tuple[int, int]
) -> Image.Image:
    """Resize *img* to *target_size* without stretching.

    If the source aspect ratio differs from the target, the source is
    center-cropped to the target aspect first, then resized. Avoids the
    horizontal/vertical squish that ``img.resize(target_size)`` produces
    when aspects don't match (e.g. Gemini returning portrait when the
    pipeline expected landscape).
    """
    target_w, target_h = target_size
    if target_w <= 0 or target_h <= 0:
        return img

    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        return img

    target_aspect = target_w / target_h
    src_aspect = src_w / src_h

    # Tolerance: aspects within 1% are treated as equal — direct resize.
    if abs(src_aspect - target_aspect) <= max(target_aspect, src_aspect) * 0.01:
        return img.resize(target_size, Image.LANCZOS)

    if src_aspect > target_aspect:
        # Source too wide: crop sides
        new_w = int(round(src_h * target_aspect))
        left = (src_w - new_w) // 2
        img = img.crop((left, 0, left + new_w, src_h))
    else:
        # Source too tall: crop top/bottom
        new_h = int(round(src_w / target_aspect))
        top = (src_h - new_h) // 2
        img = img.crop((0, top, src_w, top + new_h))

    return img.resize(target_size, Image.LANCZOS)


def aspect_hint_for_size(target_size: tuple[int, int]) -> str:
    """Return a short natural-language aspect-ratio hint for image-gen prompts.

    Used to nudge Gemini (and similar) into returning a result that already
    matches the pipeline canvas, so the post-resize step does less cropping.
    """
    w, h = target_size
    if w <= 0 or h <= 0:
        return ""
    aspect = w / h
    if abs(aspect - 1.0) < 0.05:
        return "Output a square 1:1 aspect ratio image."
    if aspect > 1.0:
        return (
            f"Output a landscape image with a {w}:{h} aspect ratio "
            f"(roughly 16:9, wider than tall)."
        )
    return (
        f"Output a portrait image with a {w}:{h} aspect ratio "
        f"(roughly 9:16, taller than wide)."
    )


def _wrap_text(text: str, font, max_width: int, draw: ImageDraw.Draw) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = f"{current} {word}".strip()
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_status_bar(draw: ImageDraw.Draw, width: int, y: int = 0):
    font = _load_font(13)
    fg = (0, 0, 0)
    draw.text((20, y + 4), "9:41", font=font, fill=fg)
    bx = width - 75
    by = y + 8
    draw.rounded_rectangle([bx, by, bx + 28, by + 13], radius=3, outline=fg, width=1)
    draw.rectangle([bx + 28, by + 3, bx + 31, by + 10], fill=fg)
    draw.rectangle([bx + 2, by + 2, bx + 22, by + 11], fill=fg)


def _draw_avatar(
    draw: ImageDraw.Draw,
    cx: int,
    cy: int,
    r: int = 22,
    initial: str = "H",
    color: tuple[int, int, int] = (79, 220, 239),
    logo_image: Image.Image | None = None,
    canvas: Image.Image | None = None,
):
    if logo_image is not None and canvas is not None:
        # Use the actual logo as a circular avatar
        size = r * 2
        avatar = logo_image.convert("RGBA").resize((size, size), Image.LANCZOS)
        # Create circular mask
        mask = Image.new("L", (size, size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse([0, 0, size - 1, size - 1], fill=255)
        # Draw a white circle background first (for transparency)
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255))
        canvas.paste(avatar, (cx - r, cy - r), mask)
    else:
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
        draw.text(
            (cx - 8, cy - 11), initial, font=_load_font(18, "bold"), fill=(255, 255, 255)
        )


def generate_mockup(
    image_data: bytes,
    caption: str,
    platform: Literal["instagram", "facebook", "linkedin", "x"],
    username: str = "",
    display_name: str = "",
    avatar_initial: str | None = None,
    avatar_color: tuple[int, int, int] = (79, 220, 239),
    avatar_logo_data: bytes | None = None,
) -> bytes:
    """Generate a realistic mobile feed mockup for a given platform.

    Returns PNG bytes of the mockup image (780x1688 — 2x iPhone resolution).
    ``avatar_initial`` defaults to the first character of *display_name*.
    ``avatar_logo_data`` — if provided, uses this image as the profile avatar
    instead of a colored circle with an initial letter.
    """
    initial = avatar_initial or (display_name[0].upper() if display_name else "H")
    avatar_logo = None
    if avatar_logo_data:
        try:
            avatar_logo = Image.open(BytesIO(avatar_logo_data)).convert("RGBA")
        except Exception:
            logger.warning("Failed to load avatar logo image — using initial fallback")

    W, H = 780, 1688
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    post_img = Image.open(BytesIO(image_data)).convert("RGB")

    if platform == "instagram":
        img = _mockup_instagram(
            img,
            draw,
            post_img,
            caption,
            username,
            W,
            H,
            initial=initial,
            avatar_color=avatar_color,
            avatar_logo=avatar_logo,
        )
    elif platform == "facebook":
        img = _mockup_facebook(
            img,
            draw,
            post_img,
            caption,
            display_name,
            W,
            H,
            initial=initial,
            avatar_color=avatar_color,
            avatar_logo=avatar_logo,
        )
    elif platform == "linkedin":
        img = _mockup_linkedin(
            img,
            draw,
            post_img,
            caption,
            display_name,
            W,
            H,
            initial=initial,
            avatar_color=avatar_color,
            avatar_logo=avatar_logo,
        )
    elif platform == "x":
        img = _mockup_x(
            img,
            draw,
            post_img,
            caption,
            username,
            display_name,
            W,
            H,
            initial=initial,
            avatar_color=avatar_color,
            avatar_logo=avatar_logo,
        )

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def _mockup_instagram(
    img,
    draw,
    post_img,
    caption,
    username,
    W,
    H,
    initial="H",
    avatar_color=(79, 220, 239),
    avatar_logo=None,
):
    y = 0
    _draw_status_bar(draw, W, y)
    y += 44

    # Header
    draw.text((16, y + 12), "Instagram", font=_load_font(28, "bold"), fill=(0, 0, 0))
    y += 56
    draw.line([(0, y), (W, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Stories
    labels = ["Your story", "wellness", "fitness", "mindful", "nutrition"]
    for i, label in enumerate(labels):
        cx, cy = 44 + i * 84, y + 38
        if i > 0:
            draw.ellipse(
                [cx - 35, cy - 35, cx + 35, cy + 35], outline=(225, 48, 108), width=3
            )
        draw.ellipse([cx - 32, cy - 32, cx + 32, cy + 32], fill=(240, 240, 240))
        lf = _load_font(11)
        lw = draw.textbbox((0, 0), label, font=lf)[2]
        draw.text((cx - lw // 2, cy + 38), label, font=lf, fill=(100, 100, 100))
    y += 100
    draw.line([(0, y), (W, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Post header
    _draw_avatar(draw, 34, y + 28, initial=initial, color=avatar_color, logo_image=avatar_logo, canvas=img)
    draw.text((60, y + 20), username, font=_load_font(15, "bold"), fill=(0, 0, 0))
    y += 56

    # Post image
    post_img = _center_crop_square(post_img, W)
    img.paste(post_img, (0, y))
    y += W

    # Actions + likes
    draw.text(
        (16, y + 12), "\u2661  \U0001f4ac  \u2933", font=_load_font(24), fill=(0, 0, 0)
    )
    y += 50
    draw.text((16, y), "2,847 likes", font=_load_font(14, "bold"), fill=(0, 0, 0))
    y += 22

    # Caption
    bf = _load_font(14, "bold")
    cf = _load_font(14)
    draw.text((16, y), username, font=bf, fill=(0, 0, 0))
    uw = draw.textbbox((0, 0), username + " ", font=bf)[2]
    lines = _wrap_text(caption, cf, W - 32, draw)
    if lines:
        draw.text((16 + uw, y), lines[0], font=cf, fill=(38, 38, 38))
        y += 20
        for line in lines[1:5]:  # Cap at 5 lines for mockup
            draw.text((16, y), line, font=cf, fill=(38, 38, 38))
            y += 20
    if len(lines) > 5:
        draw.text((16, y), "... more", font=cf, fill=(150, 150, 150))
        y += 20

    y += 8
    draw.text(
        (16, y), "View all 42 comments", font=_load_font(14), fill=(150, 150, 150)
    )
    y += 22
    draw.text((16, y), "2 hours ago", font=_load_font(12), fill=(150, 150, 150))

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)
    icons = ["\U0001f3e0", "\U0001f50d", "\u271a", "\u2661", "\u25cf"]
    sp = W // len(icons)
    for i, ic in enumerate(icons):
        draw.text(
            (sp * i + sp // 2 - 10, nav_y + 16), ic, font=_load_font(22), fill=(0, 0, 0)
        )

    return img


def _mockup_facebook(
    img,
    draw,
    post_img,
    caption,
    display_name,
    W,
    H,
    initial="H",
    avatar_color=(79, 220, 239),
    avatar_logo=None,
):
    img = Image.new("RGB", (W, H), (240, 242, 245))
    draw = ImageDraw.Draw(img)
    y = 0

    draw.rectangle([0, 0, W, 44], fill=(255, 255, 255))
    _draw_status_bar(draw, W, 0)
    y += 44

    # Header
    draw.rectangle([0, y, W, y + 52], fill=(255, 255, 255))
    draw.text((16, y + 8), "facebook", font=_load_font(30, "bold"), fill=(24, 119, 242))
    y += 52

    # Tabs
    draw.rectangle([0, y, W, y + 48], fill=(255, 255, 255))
    draw.line([(0, y + 47), (W, y + 47)], fill=(219, 219, 219), width=1)
    tabs = ["\U0001f3e0", "\U0001f465", "\u25b6", "\U0001f514", "\u2630"]
    sp = W // len(tabs)
    for i, t in enumerate(tabs):
        color = (24, 119, 242) if i == 0 else (100, 100, 100)
        draw.text((sp * i + sp // 2 - 10, y + 12), t, font=_load_font(22), fill=color)
    draw.rectangle([0, y + 45, sp, y + 48], fill=(24, 119, 242))
    y += 48

    # "What's on your mind?"
    draw.rectangle([0, y, W, y + 60], fill=(255, 255, 255))
    draw.text(
        (58, y + 18), "What's on your mind?", font=_load_font(15), fill=(150, 150, 150)
    )
    y += 68

    # Post card
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))
    _draw_avatar(draw, 38, y + 30, initial=initial, color=avatar_color, logo_image=avatar_logo, canvas=img)
    draw.text((68, y + 14), display_name, font=_load_font(15, "bold"), fill=(0, 0, 0))
    draw.text(
        (68, y + 34), "2h \u00b7 \U0001f310", font=_load_font(13), fill=(100, 100, 100)
    )
    y += 60

    # Caption above image
    cf = _load_font(15)
    for line in _wrap_text(caption, cf, W - 32, draw)[:4]:
        draw.text((16, y), line, font=cf, fill=(38, 38, 38))
        y += 22
    y += 8

    # Image
    post_img = _center_crop_square(post_img, W)
    img.paste(post_img, (0, y))
    y += W

    # Reactions
    draw.rectangle([0, y, W, y + 36], fill=(255, 255, 255))
    draw.text(
        (16, y + 8),
        "\U0001f44d\u2764\ufe0f 1.2K",
        font=_load_font(13),
        fill=(100, 100, 100),
    )
    draw.text(
        (W - 180, y + 8),
        "89 comments \u00b7 34 shares",
        font=_load_font(13),
        fill=(100, 100, 100),
    )
    y += 36
    draw.line([(16, y), (W - 16, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Actions
    draw.rectangle([0, y, W, y + 46], fill=(255, 255, 255))
    actions = [
        ("\U0001f44d Like", W // 6),
        ("\U0001f4ac Comment", W // 2),
        ("\u21aa Share", W * 5 // 6),
    ]
    af = _load_font(14)
    for label, cx in actions:
        lw = draw.textbbox((0, 0), label, font=af)[2]
        draw.text((cx - lw // 2, y + 14), label, font=af, fill=(100, 100, 100))

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)

    return img


def _mockup_linkedin(
    img,
    draw,
    post_img,
    caption,
    display_name,
    W,
    H,
    initial="H",
    avatar_color=(79, 220, 239),
    avatar_logo=None,
):
    img = Image.new("RGB", (W, H), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    y = 0

    draw.rectangle([0, 0, W, 44], fill=(255, 255, 255))
    _draw_status_bar(draw, W, 0)
    y += 44

    # Header
    draw.rectangle([0, y, W, y + 52], fill=(255, 255, 255))
    draw.text((16, y + 10), "in", font=_load_font(26, "bold"), fill=(0, 119, 181))
    draw.rounded_rectangle([56, y + 10, W - 60, y + 40], radius=6, fill=(238, 242, 246))
    draw.text(
        (68, y + 14), "\U0001f50d Search", font=_load_font(14), fill=(130, 130, 130)
    )
    y += 60

    # Post card
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))
    _draw_avatar(draw, 40, y + 34, 24, initial=initial, color=avatar_color, logo_image=avatar_logo, canvas=img)
    draw.text((72, y + 14), display_name, font=_load_font(15, "bold"), fill=(0, 0, 0))
    draw.text(
        (72, y + 34),
        "Health & Wellness \u00b7 1,234 followers",
        font=_load_font(12),
        fill=(100, 100, 100),
    )
    draw.text(
        (72, y + 50), "2h \u00b7 \U0001f310", font=_load_font(12), fill=(100, 100, 100)
    )
    y += 68

    cf = _load_font(14)
    for line in _wrap_text(caption, cf, W - 32, draw)[:4]:
        draw.text((16, y), line, font=cf, fill=(38, 38, 38))
        y += 20
    y += 8

    post_img = _center_crop_square(post_img, W)
    img.paste(post_img, (0, y))
    y += W

    draw.rectangle([0, y, W, y + 36], fill=(255, 255, 255))
    draw.text(
        (16, y + 8),
        "\U0001f44d\u2764\ufe0f\U0001f4a1 847",
        font=_load_font(13),
        fill=(100, 100, 100),
    )
    draw.text(
        (W - 200, y + 8),
        "52 comments \u00b7 18 reposts",
        font=_load_font(13),
        fill=(100, 100, 100),
    )
    y += 36
    draw.line([(16, y), (W - 16, y)], fill=(219, 219, 219), width=1)
    y += 1

    draw.rectangle([0, y, W, y + 46], fill=(255, 255, 255))
    actions = [
        ("\U0001f44d Like", W // 8),
        ("\U0001f4ac Comment", W * 3 // 8),
        ("\u21ba Repost", W * 5 // 8),
        ("\u2709 Send", W * 7 // 8),
    ]
    af = _load_font(13)
    for label, cx in actions:
        lw = draw.textbbox((0, 0), label, font=af)[2]
        draw.text((cx - lw // 2, y + 14), label, font=af, fill=(100, 100, 100))

    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)

    return img


def _mockup_x(
    img,
    draw,
    post_img,
    caption,
    username,
    display_name,
    W,
    H,
    initial="H",
    avatar_color=(79, 220, 239),
    avatar_logo=None,
):
    y = 0
    _draw_status_bar(draw, W, 0)
    y += 44

    xf = _load_font(26, "bold")
    xw = draw.textbbox((0, 0), "X", font=xf)[2]
    draw.text((W // 2 - xw // 2, y + 10), "X", font=xf, fill=(0, 0, 0))
    y += 52
    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)
    y += 1

    # Tabs
    draw.text(
        (W // 4 - 30, y + 12), "For you", font=_load_font(15, "bold"), fill=(0, 0, 0)
    )
    draw.rectangle([W // 4 - 35, y + 44, W // 4 + 35, y + 48], fill=(29, 155, 240))
    draw.text(
        (W * 3 // 4 - 40, y + 12),
        "Following",
        font=_load_font(15),
        fill=(100, 100, 100),
    )
    y += 49
    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)
    y += 1

    # Tweet
    ax = 38
    ay = y + 38
    _draw_avatar(draw, ax, ay, initial=initial, color=avatar_color, logo_image=avatar_logo, canvas=img)
    name_x = ax + 34
    draw.text(
        (name_x, y + 12), display_name, font=_load_font(15, "bold"), fill=(0, 0, 0)
    )
    draw.text(
        (name_x, y + 32),
        f"@{username} \u00b7 2h",
        font=_load_font(13),
        fill=(100, 100, 100),
    )
    y += 56

    cf = _load_font(15)
    for line in _wrap_text(caption, cf, W - 80, draw)[:5]:
        draw.text((16, y), line, font=cf, fill=(15, 20, 25))
        y += 22
    y += 8

    # Image with rounded corners
    img_w = W - 80
    post_img = _center_crop_square(post_img, img_w)
    mask = Image.new("L", (img_w, img_w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img_w, img_w], radius=16, fill=255)
    rounded = Image.new("RGB", (img_w, img_w), (255, 255, 255))
    rounded.paste(post_img, (0, 0))
    img.paste(rounded, (16, y), mask)
    y += img_w + 12

    af = _load_font(13)
    for label, ox in [
        ("\U0001f4ac 42", 60),
        ("\U0001f501 128", 180),
        ("\u2661 847", 300),
        ("\U0001f4ca 12K", 420),
    ]:
        draw.text((ox, y), label, font=af, fill=(100, 100, 100))
    y += 36
    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)

    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(239, 243, 244), width=1)

    return img
