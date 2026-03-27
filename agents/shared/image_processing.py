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
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

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


def render_logo_png(svg_bytes: bytes, size: int = 1024) -> bytes:
    """Render an SVG logo to transparent PNG bytes using ImageMagick.

    Falls back to Pillow white-removal if ImageMagick is not available.
    """
    with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as svg_f:
        svg_f.write(svg_bytes)
        svg_path = svg_f.name

    png_path = svg_path.replace(".svg", ".png")

    try:
        subprocess.run(
            ["magick", "-background", "none", "-density", "300",
             svg_path, "-resize", f"{size}x{size}", png_path],
            check=True, capture_output=True, timeout=30,
        )
        return Path(png_path).read_bytes()
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("ImageMagick not available — falling back to Pillow white-removal")
        # Fallback: open as-is and remove white background
        img = Image.open(svg_path).convert("RGBA")
        data = img.getdata()
        new_data = []
        for r, g, b, a in data:
            if r > 240 and g > 240 and b > 240:
                new_data.append((255, 255, 255, 0))
            else:
                new_data.append((r, g, b, a))
        img.putdata(new_data)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
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

    NEVER returns bottom-left — that region is reserved for text overlay.
    """
    img = Image.open(BytesIO(image_data)).convert("RGB")
    arr = np.array(img, dtype=np.float32)
    w, h = img.size

    candidates = {
        "top-right": (w - logo_w - margin, margin),
        "top-left": (margin, margin),
        "bottom-right": (w - logo_w - margin, h - logo_h - margin),
    }

    best_pos = (w - logo_w - margin, margin)  # default: top-right
    best_var = float("inf")

    for name, (cx, cy) in candidates.items():
        cx = max(0, min(cx, w - logo_w))
        cy = max(0, min(cy, h - logo_h))
        region = arr[cy:cy + logo_h, cx:cx + logo_w]
        var = float(np.var(region))
        if var < best_var:
            best_var = var
            best_pos = (cx, cy)

    logger.info("Logo placement selected (variance=%.0f)", best_var)
    return best_pos


# ── Logo + text overlay ──────────────────────────────────────────


def overlay_logo_and_text(
    image_data: bytes,
    logo_data: bytes,
    text_line1: str,
    text_line2: str | None = None,
    logo_opacity: float = 0.92,
    logo_scale: float = 0.18,
) -> bytes:
    """Overlay a transparent logo on the best monotone area + text bar at bottom.

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
    logo_w = int(base.width * logo_scale)
    logo_h = int(logo.height * (logo_w / logo.width))
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

    alpha = logo.split()[3]
    alpha = ImageEnhance.Brightness(alpha).enhance(logo_opacity)
    logo.putalpha(alpha)

    lx, ly = find_best_logo_position(image_data, logo_w, logo_h)
    overlay.paste(logo, (lx, ly), logo)

    # --- Text overlay ---
    font_large = _load_font(int(base.width * 0.040), "regular")
    font_small = _load_font(int(base.width * 0.026), "light")
    margin = int(base.width * 0.04)

    bbox1 = draw.textbbox((0, 0), text_line1, font=font_large)
    text_w1, text_h1 = bbox1[2] - bbox1[0], bbox1[3] - bbox1[1]
    text_w2, text_h2 = 0, 0
    if text_line2:
        bbox2 = draw.textbbox((0, 0), text_line2, font=font_small)
        text_w2, text_h2 = bbox2[2] - bbox2[0], bbox2[3] - bbox2[1]

    total_w = max(text_w1, text_w2)
    total_h = text_h1 + (text_h2 + 8 if text_line2 else 0)

    pad = 16
    bar_x1 = margin - pad
    bar_y1 = base.height - total_h - margin - pad * 2
    bar_x2 = margin + total_w + pad * 2
    bar_y2 = bar_y1 + total_h + pad * 2

    draw.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=12, fill=(0, 0, 0, 140))

    ty = bar_y1 + pad
    draw.text((margin + pad, ty), text_line1, font=font_large, fill=(255, 255, 255, 240))
    if text_line2:
        ty += text_h1 + 8
        draw.text((margin + pad, ty), text_line2, font=font_small, fill=(255, 255, 255, 200))

    result = Image.alpha_composite(base, overlay)
    buf = BytesIO()
    result.convert("RGB").save(buf, format="PNG", quality=95)
    return buf.getvalue()


# ── Social platform mockups ──────────────────────────────────────


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


def _draw_avatar(draw: ImageDraw.Draw, cx: int, cy: int, r: int = 22):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(79, 220, 239))
    draw.text((cx - 8, cy - 11), "H", font=_load_font(18, "bold"), fill=(255, 255, 255))


def generate_mockup(
    image_data: bytes,
    caption: str,
    platform: Literal["instagram", "facebook", "linkedin", "x"],
    username: str = "healthspan.mu",
    display_name: str = "Healthspan Mauritius",
) -> bytes:
    """Generate a realistic mobile feed mockup for a given platform.

    Returns PNG bytes of the mockup image (780x1688 — 2x iPhone resolution).
    """
    W, H = 780, 1688
    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    post_img = Image.open(BytesIO(image_data)).convert("RGB")

    if platform == "instagram":
        img = _mockup_instagram(img, draw, post_img, caption, username, W, H)
    elif platform == "facebook":
        img = _mockup_facebook(img, draw, post_img, caption, display_name, W, H)
    elif platform == "linkedin":
        img = _mockup_linkedin(img, draw, post_img, caption, display_name, W, H)
    elif platform == "x":
        img = _mockup_x(img, draw, post_img, caption, username, display_name, W, H)

    buf = BytesIO()
    img.save(buf, format="PNG", quality=95)
    return buf.getvalue()


def _mockup_instagram(img, draw, post_img, caption, username, W, H):
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
            draw.ellipse([cx - 35, cy - 35, cx + 35, cy + 35], outline=(225, 48, 108), width=3)
        draw.ellipse([cx - 32, cy - 32, cx + 32, cy + 32], fill=(240, 240, 240))
        lf = _load_font(11)
        lw = draw.textbbox((0, 0), label, font=lf)[2]
        draw.text((cx - lw // 2, cy + 38), label, font=lf, fill=(100, 100, 100))
    y += 100
    draw.line([(0, y), (W, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Post header
    _draw_avatar(draw, 34, y + 28)
    draw.text((60, y + 20), username, font=_load_font(15, "bold"), fill=(0, 0, 0))
    y += 56

    # Post image
    post_img = post_img.resize((W, W), Image.LANCZOS)
    img.paste(post_img, (0, y))
    y += W

    # Actions + likes
    draw.text((16, y + 12), "\u2661  \U0001F4AC  \u2933", font=_load_font(24), fill=(0, 0, 0))
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
    draw.text((16, y), "View all 42 comments", font=_load_font(14), fill=(150, 150, 150))
    y += 22
    draw.text((16, y), "2 hours ago", font=_load_font(12), fill=(150, 150, 150))

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)
    icons = ["\U0001F3E0", "\U0001F50D", "\u271A", "\u2661", "\u25CF"]
    sp = W // len(icons)
    for i, ic in enumerate(icons):
        draw.text((sp * i + sp // 2 - 10, nav_y + 16), ic, font=_load_font(22), fill=(0, 0, 0))

    return img


def _mockup_facebook(img, draw, post_img, caption, display_name, W, H):
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
    tabs = ["\U0001F3E0", "\U0001F465", "\u25B6", "\U0001F514", "\u2630"]
    sp = W // len(tabs)
    for i, t in enumerate(tabs):
        color = (24, 119, 242) if i == 0 else (100, 100, 100)
        draw.text((sp * i + sp // 2 - 10, y + 12), t, font=_load_font(22), fill=color)
    draw.rectangle([0, y + 45, sp, y + 48], fill=(24, 119, 242))
    y += 48

    # "What's on your mind?"
    draw.rectangle([0, y, W, y + 60], fill=(255, 255, 255))
    draw.text((58, y + 18), "What's on your mind?", font=_load_font(15), fill=(150, 150, 150))
    y += 68

    # Post card
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))
    _draw_avatar(draw, 38, y + 30)
    draw.text((68, y + 14), display_name, font=_load_font(15, "bold"), fill=(0, 0, 0))
    draw.text((68, y + 34), "2h \u00B7 \U0001F310", font=_load_font(13), fill=(100, 100, 100))
    y += 60

    # Caption above image
    cf = _load_font(15)
    for line in _wrap_text(caption, cf, W - 32, draw)[:4]:
        draw.text((16, y), line, font=cf, fill=(38, 38, 38))
        y += 22
    y += 8

    # Image
    post_img = post_img.resize((W, W), Image.LANCZOS)
    img.paste(post_img, (0, y))
    y += W

    # Reactions
    draw.rectangle([0, y, W, y + 36], fill=(255, 255, 255))
    draw.text((16, y + 8), "\U0001F44D\u2764\uFE0F 1.2K", font=_load_font(13), fill=(100, 100, 100))
    draw.text((W - 180, y + 8), "89 comments \u00B7 34 shares", font=_load_font(13), fill=(100, 100, 100))
    y += 36
    draw.line([(16, y), (W - 16, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Actions
    draw.rectangle([0, y, W, y + 46], fill=(255, 255, 255))
    actions = [("\U0001F44D Like", W // 6), ("\U0001F4AC Comment", W // 2), ("\u21AA Share", W * 5 // 6)]
    af = _load_font(14)
    for label, cx in actions:
        lw = draw.textbbox((0, 0), label, font=af)[2]
        draw.text((cx - lw // 2, y + 14), label, font=af, fill=(100, 100, 100))

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)

    return img


def _mockup_linkedin(img, draw, post_img, caption, display_name, W, H):
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
    draw.text((68, y + 14), "\U0001F50D Search", font=_load_font(14), fill=(130, 130, 130))
    y += 60

    # Post card
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))
    _draw_avatar(draw, 40, y + 34, 24)
    draw.text((72, y + 14), display_name, font=_load_font(15, "bold"), fill=(0, 0, 0))
    draw.text((72, y + 34), "Health & Wellness \u00B7 1,234 followers", font=_load_font(12), fill=(100, 100, 100))
    draw.text((72, y + 50), "2h \u00B7 \U0001F310", font=_load_font(12), fill=(100, 100, 100))
    y += 68

    cf = _load_font(14)
    for line in _wrap_text(caption, cf, W - 32, draw)[:4]:
        draw.text((16, y), line, font=cf, fill=(38, 38, 38))
        y += 20
    y += 8

    post_img = post_img.resize((W, W), Image.LANCZOS)
    img.paste(post_img, (0, y))
    y += W

    draw.rectangle([0, y, W, y + 36], fill=(255, 255, 255))
    draw.text((16, y + 8), "\U0001F44D\u2764\uFE0F\U0001F4A1 847", font=_load_font(13), fill=(100, 100, 100))
    draw.text((W - 200, y + 8), "52 comments \u00B7 18 reposts", font=_load_font(13), fill=(100, 100, 100))
    y += 36
    draw.line([(16, y), (W - 16, y)], fill=(219, 219, 219), width=1)
    y += 1

    draw.rectangle([0, y, W, y + 46], fill=(255, 255, 255))
    actions = [("\U0001F44D Like", W // 8), ("\U0001F4AC Comment", W * 3 // 8),
               ("\u21BA Repost", W * 5 // 8), ("\u2709 Send", W * 7 // 8)]
    af = _load_font(13)
    for label, cx in actions:
        lw = draw.textbbox((0, 0), label, font=af)[2]
        draw.text((cx - lw // 2, y + 14), label, font=af, fill=(100, 100, 100))

    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)

    return img


def _mockup_x(img, draw, post_img, caption, username, display_name, W, H):
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
    draw.text((W // 4 - 30, y + 12), "For you", font=_load_font(15, "bold"), fill=(0, 0, 0))
    draw.rectangle([W // 4 - 35, y + 44, W // 4 + 35, y + 48], fill=(29, 155, 240))
    draw.text((W * 3 // 4 - 40, y + 12), "Following", font=_load_font(15), fill=(100, 100, 100))
    y += 49
    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)
    y += 1

    # Tweet
    ax = 38
    ay = y + 38
    _draw_avatar(draw, ax, ay)
    name_x = ax + 34
    draw.text((name_x, y + 12), display_name, font=_load_font(15, "bold"), fill=(0, 0, 0))
    draw.text((name_x, y + 32), f"@{username} \u00B7 2h", font=_load_font(13), fill=(100, 100, 100))
    y += 56

    cf = _load_font(15)
    for line in _wrap_text(caption, cf, W - 80, draw)[:5]:
        draw.text((16, y), line, font=cf, fill=(15, 20, 25))
        y += 22
    y += 8

    # Image with rounded corners
    img_w = W - 80
    post_img = post_img.resize((img_w, img_w), Image.LANCZOS)
    mask = Image.new("L", (img_w, img_w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img_w, img_w], radius=16, fill=255)
    rounded = Image.new("RGB", (img_w, img_w), (255, 255, 255))
    rounded.paste(post_img, (0, 0))
    img.paste(rounded, (16, y), mask)
    y += img_w + 12

    af = _load_font(13)
    for label, ox in [("\U0001F4AC 42", 60), ("\U0001F501 128", 180), ("\u2661 847", 300), ("\U0001F4CA 12K", 420)]:
        draw.text((ox, y), label, font=af, fill=(100, 100, 100))
    y += 36
    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)

    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(239, 243, 244), width=1)

    return img
