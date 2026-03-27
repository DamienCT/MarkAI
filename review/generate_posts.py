"""Generate 3 social media posts for Healthspan Mauritius.

v4 — Full rewrite with:
1. Transparent PNG logo (rendered from SVG via ImageMagick)
2. Smart logo placement on monotone/sky areas (numpy variance analysis)
3. Concise captions (half previous length)
4. Social platform mobile mockup previews (Instagram, Facebook, LinkedIn, X)
"""

import openai
import base64
import json
import os
import time
import numpy as np
from pathlib import Path
from PIL import Image, ImageEnhance, ImageDraw, ImageFont, ImageFilter
from io import BytesIO
from google import genai
from google.genai import types

oai = openai.OpenAI()
gem = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

all_prompts = []
LOGO = "review/prompts/healthspan_logo_primary.png"
FINAL_DIR = Path("review/final_posts")
PROMPTS_DIR = Path("review/prompts")

# ═══════════════════════════════════════════════════════════════════
# LOGO UTILITIES
# ═══════════════════════════════════════════════════════════════════

def find_best_logo_region(image_path, logo_w, logo_h, margin=40):
    """Find the most monotone/low-contrast corner region for logo placement.

    Scans candidate positions (corners + mid-edges) and picks the region
    with lowest pixel variance — sky, solid surfaces, shadows, etc.
    """
    img = Image.open(image_path).convert("RGB")
    arr = np.array(img, dtype=np.float32)
    w, h = img.size

    # Candidate positions: (x, y) for top-left corner of logo box
    # NEVER use bottom-left — that's reserved for the text overlay
    candidates = {
        "top-right":    (w - logo_w - margin, margin),
        "top-left":     (margin, margin),
        "bottom-right": (w - logo_w - margin, h - logo_h - margin),
    }

    best_pos = None
    best_var = float("inf")
    best_name = ""

    for name, (cx, cy) in candidates.items():
        # Ensure within bounds
        cx = max(0, min(cx, w - logo_w))
        cy = max(0, min(cy, h - logo_h))
        region = arr[cy:cy + logo_h, cx:cx + logo_w]
        # Variance across all channels — lower = more uniform
        var = np.var(region)
        if var < best_var:
            best_var = var
            best_pos = (cx, cy)
            best_name = name

    print(f"    Logo placement: {best_name} (variance={best_var:.0f})")
    return best_pos


def overlay_logo_and_text(base_path, output_path, text_line1, text_line2=None,
                          logo_opacity=0.92, logo_scale=0.18):
    """Overlay transparent logo on best monotone area + text bar at bottom."""
    base = Image.open(base_path).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # --- Logo (smart placement) ---
    logo = Image.open(LOGO).convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    logo_w = int(base.width * logo_scale)
    logo_h = int(logo.height * (logo_w / logo.width))
    logo = logo.resize((logo_w, logo_h), Image.LANCZOS)

    # Apply opacity
    alpha = logo.split()[3]
    alpha = ImageEnhance.Brightness(alpha).enhance(logo_opacity)
    logo.putalpha(alpha)

    # Find best monotone region
    lx, ly = find_best_logo_region(base_path, logo_w, logo_h)
    overlay.paste(logo, (lx, ly), logo)

    # --- Text overlay (bottom area with semi-transparent strip) ---
    font_size_large = int(base.width * 0.040)
    font_size_small = int(base.width * 0.026)
    try:
        font_large = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", font_size_large)
        font_small = ImageFont.truetype("C:/Windows/Fonts/segoeuil.ttf", font_size_small)
    except (OSError, IOError):
        try:
            font_large = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", font_size_large)
            font_small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", font_size_small)
        except (OSError, IOError):
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

    margin = int(base.width * 0.04)

    # Measure text
    bbox1 = draw.textbbox((0, 0), text_line1, font=font_large)
    text_w1 = bbox1[2] - bbox1[0]
    text_h1 = bbox1[3] - bbox1[1]

    if text_line2:
        bbox2 = draw.textbbox((0, 0), text_line2, font=font_small)
        text_w2 = bbox2[2] - bbox2[0]
        text_h2 = bbox2[3] - bbox2[1]
    else:
        text_w2, text_h2 = 0, 0

    total_text_w = max(text_w1, text_w2)
    total_text_h = text_h1 + (text_h2 + 8 if text_line2 else 0)

    # Semi-transparent dark background behind text (bottom-left)
    pad = 16
    bar_x1 = margin - pad
    bar_y1 = base.height - total_text_h - margin - pad * 2
    bar_x2 = margin + total_text_w + pad * 2
    bar_y2 = bar_y1 + total_text_h + pad * 2

    draw.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=12, fill=(0, 0, 0, 140))

    # Draw text
    ty = bar_y1 + pad
    draw.text((margin + pad, ty), text_line1, font=font_large, fill=(255, 255, 255, 240))
    if text_line2:
        ty += text_h1 + 8
        draw.text((margin + pad, ty), text_line2, font=font_small, fill=(255, 255, 255, 200))

    result = Image.alpha_composite(base, overlay)
    result.convert("RGB").save(output_path, quality=95)
    print(f"    Final saved: {output_path}")


# ═══════════════════════════════════════════════════════════════════
# SOCIAL MOCKUP GENERATOR
# ═══════════════════════════════════════════════════════════════════

def load_font(size, bold=False):
    """Load system font with fallback."""
    try:
        if bold:
            return ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", size)
        return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", size)
    except (OSError, IOError):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf", size)
        except (OSError, IOError):
            return ImageFont.load_default()


def draw_status_bar(draw, width, y_offset=0, dark=False):
    """Draw a simplified mobile status bar."""
    fg = (255, 255, 255) if dark else (0, 0, 0)
    font = load_font(13)
    draw.text((20, y_offset + 4), "9:41", font=font, fill=fg)
    # Signal + wifi + battery icons (simplified)
    bx = width - 75
    by = y_offset + 8
    # Battery outline
    draw.rounded_rectangle([bx, by, bx + 28, by + 13], radius=3, outline=fg, width=1)
    draw.rectangle([bx + 28, by + 3, bx + 31, by + 10], fill=fg)
    draw.rectangle([bx + 2, by + 2, bx + 22, by + 11], fill=fg)
    # Wifi dots
    draw.ellipse([bx - 20, by + 3, bx - 12, by + 11], fill=fg)
    # Signal bars
    for i in range(4):
        bh = 4 + i * 2
        draw.rectangle([bx - 45 + i * 5, by + 13 - bh, bx - 42 + i * 5, by + 13], fill=fg)


def draw_rounded_rect(draw, box, radius, fill):
    """Draw a rounded rectangle."""
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def wrap_text(text, font, max_width, draw):
    """Wrap text to fit within max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_instagram_mockup(post_image_path, caption, username="healthspan.mu",
                               output_path=None):
    """Generate a realistic Instagram mobile feed mockup."""
    # Phone dimensions (iPhone-like)
    PW, PH = 390, 844
    SCALE = 2  # 2x for crisp rendering
    W, H = PW * SCALE, PH * SCALE

    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = 0
    # Status bar
    draw_status_bar(draw, W, y)
    y += 44

    # Instagram header bar
    draw.rectangle([0, y, W, y + 56], fill=(255, 255, 255))
    header_font = load_font(28, bold=True)
    draw.text((16, y + 12), "Instagram", font=header_font, fill=(0, 0, 0))
    # Heart + messenger icons (simplified)
    draw.text((W - 80, y + 14), "\u2661", font=load_font(26), fill=(0, 0, 0))
    y += 56

    # Thin separator
    draw.line([(0, y), (W, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Stories bar (simplified circles)
    stories_h = 100
    draw.rectangle([0, y, W, y + stories_h], fill=(255, 255, 255))
    story_labels = ["Your story", "wellness", "fitness", "mindful", "nutrition"]
    for i, label in enumerate(story_labels):
        cx = 44 + i * 84
        cy_c = y + 38
        r = 32
        # Gradient ring for stories (simplified as colored circle)
        if i > 0:
            draw.ellipse([cx - r - 3, cy_c - r - 3, cx + r + 3, cy_c + r + 3],
                        outline=(225, 48, 108), width=3)
        draw.ellipse([cx - r, cy_c - r, cx + r, cy_c + r], fill=(240, 240, 240))
        lbl_font = load_font(11)
        lbl_bbox = draw.textbbox((0, 0), label, font=lbl_font)
        lbl_w = lbl_bbox[2] - lbl_bbox[0]
        draw.text((cx - lbl_w // 2, cy_c + r + 6), label, font=lbl_font, fill=(100, 100, 100))
    y += stories_h

    draw.line([(0, y), (W, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Post header (avatar + username + ...)
    post_header_h = 56
    draw.rectangle([0, y, W, y + post_header_h], fill=(255, 255, 255))
    # Avatar circle
    avatar_r = 18
    ax, ay = 16 + avatar_r, y + post_header_h // 2
    draw.ellipse([ax - avatar_r, ay - avatar_r, ax + avatar_r, ay + avatar_r],
                fill=(79, 220, 239))  # Brand cyan
    # "H" inside avatar
    h_font = load_font(18, bold=True)
    draw.text((ax - 7, ay - 11), "H", font=h_font, fill=(255, 255, 255))
    # Username
    name_font = load_font(15, bold=True)
    draw.text((ax + avatar_r + 12, ay - 8), username, font=name_font, fill=(0, 0, 0))
    # Three dots menu
    draw.text((W - 40, ay - 6), "...", font=load_font(18, bold=True), fill=(0, 0, 0))
    y += post_header_h

    # Post image (square)
    post_img = Image.open(post_image_path).convert("RGB")
    img_size = W  # Full width square
    post_img = post_img.resize((img_size, img_size), Image.LANCZOS)
    img.paste(post_img, (0, y))
    y += img_size

    # Action buttons (heart, comment, share, bookmark)
    action_h = 50
    draw.rectangle([0, y, W, y + action_h], fill=(255, 255, 255))
    icon_font = load_font(24)
    icons = [("\u2661", 16), ("\U0001F4AC", 56), ("\u2933", 96)]
    for icon, ix in icons:
        draw.text((ix, y + 12), icon, font=icon_font, fill=(0, 0, 0))
    # Bookmark on right
    draw.text((W - 40, y + 12), "\U0001F516", font=icon_font, fill=(0, 0, 0))
    y += action_h

    # Likes count
    likes_font = load_font(14, bold=True)
    draw.text((16, y), "2,847 likes", font=likes_font, fill=(0, 0, 0))
    y += 22

    # Caption (wrapped)
    caption_font = load_font(14)
    caption_bold = load_font(14, bold=True)
    # Username in bold + caption
    max_text_w = W - 32
    full_caption = f"{username} {caption}"
    # Draw username bold
    draw.text((16, y), username, font=caption_bold, fill=(0, 0, 0))
    uname_w = draw.textbbox((0, 0), username + " ", font=caption_bold)[2]

    # Wrap remaining caption
    lines = wrap_text(caption, caption_font, max_text_w, draw)
    # First line continues after username
    if lines:
        first_line = lines[0]
        draw.text((16 + uname_w, y), first_line, font=caption_font, fill=(38, 38, 38))
        y += 20
        for line in lines[1:]:
            draw.text((16, y), line, font=caption_font, fill=(38, 38, 38))
            y += 20

    y += 8
    # "View all comments" + time
    draw.text((16, y), "View all 42 comments", font=load_font(14), fill=(150, 150, 150))
    y += 22
    draw.text((16, y), "2 hours ago", font=load_font(12), fill=(150, 150, 150))
    y += 30

    # Bottom nav bar
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)
    nav_icons = ["\U0001F3E0", "\U0001F50D", "\u271A", "\u2661", "\u25CF"]
    nav_spacing = W // len(nav_icons)
    for i, icon in enumerate(nav_icons):
        nx = nav_spacing * i + nav_spacing // 2 - 10
        draw.text((nx, nav_y + 16), icon, font=load_font(22), fill=(0, 0, 0))

    if output_path:
        img.save(output_path, quality=95)
        print(f"    Instagram mockup: {output_path}")
    return img


def generate_facebook_mockup(post_image_path, caption, username="Healthspan Mauritius",
                              output_path=None):
    """Generate a realistic Facebook mobile feed mockup."""
    PW, PH = 390, 844
    SCALE = 2
    W, H = PW * SCALE, PH * SCALE

    img = Image.new("RGB", (W, H), (240, 242, 245))  # FB gray bg
    draw = ImageDraw.Draw(img)

    y = 0
    # Status bar (dark for FB blue header)
    draw.rectangle([0, 0, W, 44], fill=(255, 255, 255))
    draw_status_bar(draw, W, 0, dark=False)
    y += 44

    # Facebook header
    fb_header_h = 52
    draw.rectangle([0, y, W, y + fb_header_h], fill=(255, 255, 255))
    fb_font = load_font(30, bold=True)
    draw.text((16, y + 8), "facebook", font=fb_font, fill=(24, 119, 242))
    # Search + messenger icons
    draw.text((W - 90, y + 12), "\U0001F50D", font=load_font(22), fill=(0, 0, 0))
    draw.text((W - 45, y + 12), "\U0001F4AC", font=load_font(22), fill=(0, 0, 0))
    y += fb_header_h

    # Tab bar (Feed, Friends, Watch, etc)
    tab_h = 48
    draw.rectangle([0, y, W, y + tab_h], fill=(255, 255, 255))
    draw.line([(0, y + tab_h - 1), (W, y + tab_h - 1)], fill=(219, 219, 219), width=1)
    tab_labels = ["\U0001F3E0", "\U0001F465", "\u25B6", "\U0001F514", "\u2630"]
    tab_spacing = W // len(tab_labels)
    for i, label in enumerate(tab_labels):
        tx = tab_spacing * i + tab_spacing // 2 - 10
        color = (24, 119, 242) if i == 0 else (100, 100, 100)
        draw.text((tx, y + 12), label, font=load_font(22), fill=color)
    # Blue underline on first tab
    draw.rectangle([0, y + tab_h - 3, tab_spacing, y + tab_h], fill=(24, 119, 242))
    y += tab_h

    # "What's on your mind?" bar
    mind_h = 60
    draw.rectangle([0, y, W, y + mind_h], fill=(255, 255, 255))
    draw.ellipse([16, y + 14, 48, y + 46], fill=(240, 240, 240))
    draw.text((58, y + 18), "What's on your mind?", font=load_font(15), fill=(150, 150, 150))
    y += mind_h

    # Spacer
    y += 8

    # Post card
    card_start = y
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))

    # Post header
    ph_h = 60
    # Avatar
    av_r = 22
    ax, ay_c = 16 + av_r, y + ph_h // 2
    draw.ellipse([ax - av_r, ay_c - av_r, ax + av_r, ay_c + av_r], fill=(79, 220, 239))
    h_font = load_font(20, bold=True)
    draw.text((ax - 8, ay_c - 12), "H", font=h_font, fill=(255, 255, 255))
    # Page name + time
    name_font = load_font(15, bold=True)
    draw.text((ax + av_r + 12, ay_c - 16), username, font=name_font, fill=(0, 0, 0))
    time_font = load_font(13)
    draw.text((ax + av_r + 12, ay_c + 4), "2h \u00B7 \U0001F310", font=time_font, fill=(100, 100, 100))
    # Three dots
    draw.text((W - 40, ay_c - 6), "...", font=load_font(18, bold=True), fill=(100, 100, 100))
    y += ph_h

    # Caption text (above image on Facebook)
    caption_font = load_font(15)
    max_text_w = W - 32
    lines = wrap_text(caption, caption_font, max_text_w, draw)
    for line in lines:
        draw.text((16, y), line, font=caption_font, fill=(38, 38, 38))
        y += 22
    y += 8

    # Post image
    post_img = Image.open(post_image_path).convert("RGB")
    # Facebook uses wider aspect, but we'll keep square for consistency
    img_w = W
    img_h = W  # Square
    post_img = post_img.resize((img_w, img_h), Image.LANCZOS)
    img.paste(post_img, (0, y))
    y += img_h

    # Reactions bar
    react_h = 36
    draw.rectangle([0, y, W, y + react_h], fill=(255, 255, 255))
    react_font = load_font(13)
    # Like emoji + count
    draw.text((16, y + 8), "\U0001F44D\u2764\uFE0F", font=load_font(14), fill=(0, 0, 0))
    draw.text((56, y + 10), "1.2K", font=react_font, fill=(100, 100, 100))
    draw.text((W - 160, y + 10), "89 comments \u00B7 34 shares", font=react_font, fill=(100, 100, 100))
    y += react_h

    # Separator
    draw.line([(16, y), (W - 16, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Action buttons (Like, Comment, Share)
    action_h = 46
    draw.rectangle([0, y, W, y + action_h], fill=(255, 255, 255))
    actions = [("\U0001F44D Like", W // 6), ("\U0001F4AC Comment", W // 2), ("\u21AA Share", W * 5 // 6)]
    act_font = load_font(14)
    for label, cx in actions:
        lbl_bbox = draw.textbbox((0, 0), label, font=act_font)
        lbl_w = lbl_bbox[2] - lbl_bbox[0]
        draw.text((cx - lbl_w // 2, y + 14), label, font=act_font, fill=(100, 100, 100))

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)

    if output_path:
        img.save(output_path, quality=95)
        print(f"    Facebook mockup: {output_path}")
    return img


def generate_linkedin_mockup(post_image_path, caption, username="Healthspan Mauritius",
                              output_path=None):
    """Generate a LinkedIn mobile feed mockup."""
    PW, PH = 390, 844
    SCALE = 2
    W, H = PW * SCALE, PH * SCALE

    img = Image.new("RGB", (W, H), (240, 240, 240))
    draw = ImageDraw.Draw(img)

    y = 0
    # Status bar
    draw.rectangle([0, 0, W, 44], fill=(255, 255, 255))
    draw_status_bar(draw, W, 0)
    y += 44

    # LinkedIn header
    li_h = 52
    draw.rectangle([0, y, W, y + li_h], fill=(255, 255, 255))
    li_font = load_font(26, bold=True)
    draw.text((16, y + 10), "in", font=li_font, fill=(0, 119, 181))
    # Search bar
    draw.rounded_rectangle([56, y + 10, W - 60, y + 40], radius=6, fill=(238, 242, 246))
    draw.text((68, y + 14), "\U0001F50D Search", font=load_font(14), fill=(130, 130, 130))
    # Message icon
    draw.text((W - 45, y + 12), "\U0001F4AC", font=load_font(22), fill=(100, 100, 100))
    y += li_h

    # Spacer
    y += 8

    # Post card
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))

    # Post header
    ph_h = 68
    av_r = 24
    ax, ay_c = 16 + av_r, y + ph_h // 2
    draw.ellipse([ax - av_r, ay_c - av_r, ax + av_r, ay_c + av_r], fill=(79, 220, 239))
    h_font = load_font(18, bold=True)
    draw.text((ax - 8, ay_c - 11), "H", font=h_font, fill=(255, 255, 255))
    # Company name + tagline
    name_font = load_font(15, bold=True)
    draw.text((ax + av_r + 12, ay_c - 20), username, font=name_font, fill=(0, 0, 0))
    sub_font = load_font(12)
    draw.text((ax + av_r + 12, ay_c), "Health & Wellness \u00B7 1,234 followers", font=sub_font, fill=(100, 100, 100))
    draw.text((ax + av_r + 12, ay_c + 16), "2h \u00B7 \U0001F310", font=sub_font, fill=(100, 100, 100))
    y += ph_h

    # Caption
    caption_font = load_font(14)
    max_w = W - 32
    lines = wrap_text(caption, caption_font, max_w, draw)
    for line in lines:
        draw.text((16, y), line, font=caption_font, fill=(38, 38, 38))
        y += 20
    y += 8

    # Post image
    post_img = Image.open(post_image_path).convert("RGB")
    img_h = W
    post_img = post_img.resize((W, img_h), Image.LANCZOS)
    img.paste(post_img, (0, y))
    y += img_h

    # Reactions
    react_h = 36
    draw.rectangle([0, y, W, y + react_h], fill=(255, 255, 255))
    draw.text((16, y + 8), "\U0001F44D\u2764\uFE0F\U0001F4A1 847", font=load_font(13), fill=(100, 100, 100))
    draw.text((W - 180, y + 8), "52 comments \u00B7 18 reposts", font=load_font(13), fill=(100, 100, 100))
    y += react_h
    draw.line([(16, y), (W - 16, y)], fill=(219, 219, 219), width=1)
    y += 1

    # Actions
    action_h = 46
    draw.rectangle([0, y, W, y + action_h], fill=(255, 255, 255))
    actions = [("\U0001F44D Like", W // 8), ("\U0001F4AC Comment", W * 3 // 8),
               ("\u21BA Repost", W * 5 // 8), ("\u2709 Send", W * 7 // 8)]
    act_font = load_font(13)
    for label, cx in actions:
        lbl_bbox = draw.textbbox((0, 0), label, font=act_font)
        lbl_w = lbl_bbox[2] - lbl_bbox[0]
        draw.text((cx - lbl_w // 2, y + 14), label, font=act_font, fill=(100, 100, 100))

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(219, 219, 219), width=1)
    nav_items = ["\U0001F3E0", "\U0001F465", "\u271A", "\U0001F4AC", "\U0001F514"]
    nav_sp = W // len(nav_items)
    for i, icon in enumerate(nav_items):
        draw.text((nav_sp * i + nav_sp // 2 - 10, nav_y + 16), icon, font=load_font(22), fill=(100, 100, 100))

    if output_path:
        img.save(output_path, quality=95)
        print(f"    LinkedIn mockup: {output_path}")
    return img


def generate_x_mockup(post_image_path, caption, username="HealthspanMU",
                       display_name="Healthspan Mauritius", output_path=None):
    """Generate an X (Twitter) mobile feed mockup."""
    PW, PH = 390, 844
    SCALE = 2
    W, H = PW * SCALE, PH * SCALE

    img = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = 0
    # Status bar
    draw_status_bar(draw, W, 0)
    y += 44

    # X header
    x_h = 52
    draw.rectangle([0, y, W, y + x_h], fill=(255, 255, 255))
    # Profile pic on left
    draw.ellipse([16, y + 10, 48, y + 42], fill=(240, 240, 240))
    # X logo center
    x_font = load_font(26, bold=True)
    x_bbox = draw.textbbox((0, 0), "X", font=x_font)
    x_w = x_bbox[2] - x_bbox[0]
    draw.text((W // 2 - x_w // 2, y + 10), "X", font=x_font, fill=(0, 0, 0))
    y += x_h

    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)
    y += 1

    # Tabs (For you / Following)
    tab_h = 48
    draw.rectangle([0, y, W, y + tab_h], fill=(255, 255, 255))
    tab_font = load_font(15, bold=True)
    draw.text((W // 4 - 30, y + 12), "For you", font=tab_font, fill=(0, 0, 0))
    # Blue underline
    draw.rectangle([W // 4 - 35, y + tab_h - 4, W // 4 + 35, y + tab_h], fill=(29, 155, 240))
    draw.text((W * 3 // 4 - 40, y + 12), "Following", font=load_font(15), fill=(100, 100, 100))
    y += tab_h
    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)
    y += 1

    # Tweet/Post
    tweet_start = y
    draw.rectangle([0, y, W, H - 56], fill=(255, 255, 255))

    # Avatar
    av_r = 22
    ax = 16 + av_r
    ay = y + 16 + av_r
    draw.ellipse([ax - av_r, ay - av_r, ax + av_r, ay + av_r], fill=(79, 220, 239))
    draw.text((ax - 8, ay - 11), "H", font=load_font(18, bold=True), fill=(255, 255, 255))

    # Display name + handle + time
    name_x = ax + av_r + 12
    draw.text((name_x, y + 12), display_name, font=load_font(15, bold=True), fill=(0, 0, 0))
    handle_text = f"@{username} \u00B7 2h"
    draw.text((name_x, y + 32), handle_text, font=load_font(13), fill=(100, 100, 100))
    y += 56

    # Tweet text
    caption_font = load_font(15)
    max_w = W - 80
    lines = wrap_text(caption, caption_font, max_w, draw)
    for line in lines:
        draw.text((ax - av_r, y), line, font=caption_font, fill=(15, 20, 25))
        y += 22
    y += 8

    # Image (rounded corners)
    post_img = Image.open(post_image_path).convert("RGB")
    img_w = W - 80
    img_h = img_w  # Square
    post_img = post_img.resize((img_w, img_h), Image.LANCZOS)
    # Create rounded mask
    mask = Image.new("L", (img_w, img_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([0, 0, img_w, img_h], radius=16, fill=255)
    # Paste with rounded corners
    rounded_img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    rounded_img.paste(post_img, (0, 0))
    img.paste(rounded_img, (ax - av_r, y), mask)
    y += img_h + 12

    # Engagement buttons
    action_font = load_font(13)
    actions = [("\U0001F4AC 42", 60), ("\U0001F501 128", 180), ("\u2661 847", 300), ("\U0001F4CA 12K", 420)]
    for label, ox in actions:
        draw.text((ox, y), label, font=action_font, fill=(100, 100, 100))
    y += 36

    draw.line([(0, y), (W, y)], fill=(239, 243, 244), width=1)

    # Bottom nav
    nav_y = H - 56
    draw.rectangle([0, nav_y, W, H], fill=(255, 255, 255))
    draw.line([(0, nav_y), (W, nav_y)], fill=(239, 243, 244), width=1)
    nav_icons = ["\U0001F3E0", "\U0001F50D", "\U0001F465", "\U0001F514", "\u2709"]
    nav_sp = W // len(nav_icons)
    for i, icon in enumerate(nav_icons):
        draw.text((nav_sp * i + nav_sp // 2 - 10, nav_y + 16), icon, font=load_font(22), fill=(0, 0, 0))

    if output_path:
        img.save(output_path, quality=95)
        print(f"    X mockup: {output_path}")
    return img


def generate_all_mockups(post_image_path, caption, post_name):
    """Generate mockups for all 4 platforms."""
    mockup_dir = FINAL_DIR / "mockups"
    mockup_dir.mkdir(exist_ok=True)

    print(f"  Generating social mockups for {post_name}...")
    generate_instagram_mockup(
        post_image_path, caption,
        output_path=str(mockup_dir / f"{post_name}_instagram.png")
    )
    generate_facebook_mockup(
        post_image_path, caption,
        output_path=str(mockup_dir / f"{post_name}_facebook.png")
    )
    generate_linkedin_mockup(
        post_image_path, caption,
        output_path=str(mockup_dir / f"{post_name}_linkedin.png")
    )
    generate_x_mockup(
        post_image_path, caption,
        output_path=str(mockup_dir / f"{post_name}_x.png")
    )


# ═══════════════════════════════════════════════════════════════════
# CAPTIONS (medium length — balanced between detail and brevity)
# ═══════════════════════════════════════════════════════════════════

CAPTIONS = {
    "ringconn": {
        "en": (
            "Track sleep, heart rate, stress & blood oxygen — all from your finger.\n\n"
            "The RingConn Gen 2 is the smart ring that fits your lifestyle. "
            "Lightweight titanium, 7-day battery life, and no bulky screen "
            "to get in the way. It tracks what matters while you go about your day.\n\n"
            "Whether you're optimising recovery after a workout or understanding "
            "your sleep patterns, this tiny device delivers real insights.\n\n"
            "Now available in Mauritius at healthspan.mu \U0001F48D\n\n"
            "#RingConn #HealthTracking #WearableTech #SmartRing #HealthspanMU #Mauritius"
        ),
        "fr": (
            "Suivez votre sommeil, rythme cardiaque, stress et oxygenation — directement depuis votre doigt.\n\n"
            "Le RingConn Gen 2 est la bague intelligente qui s'adapte a votre quotidien. "
            "Titane leger, 7 jours d'autonomie, et aucun ecran encombrant. "
            "Elle suit ce qui compte pendant que vous vivez votre vie.\n\n"
            "Que vous optimisiez votre recuperation ou compreniez vos cycles de sommeil, "
            "ce petit appareil vous donne de vraies donnees.\n\n"
            "Disponible a Maurice sur healthspan.mu \U0001F48D\n\n"
            "#RingConn #SanteMaurice #TechSante #BagueConnectee #HealthspanMU"
        ),
    },
    "sibionics": {
        "en": (
            "See how food, sleep & stress affect your glucose — in real time.\n\n"
            "The SiBionics GS1 is a continuous glucose monitor that sits discreetly "
            "on your arm and tracks your levels for 14 days straight. No finger pricks, "
            "no interruptions — just a steady stream of data to help you make "
            "better decisions about what you eat and how you live.\n\n"
            "Understanding your glucose response is one of the most powerful things "
            "you can do for long-term health. This makes it easy.\n\n"
            "Learn more at healthspan.mu \U0001F4C8\n\n"
            "#CGM #GlucoseMonitoring #SiBionics #MetabolicHealth #HealthspanMU #Mauritius"
        ),
        "fr": (
            "Decouvrez comment votre alimentation, sommeil et stress impactent votre glycemie — en temps reel.\n\n"
            "Le SiBionics GS1 est un capteur de glycemie en continu, discret sur votre bras, "
            "qui suit vos niveaux pendant 14 jours. Sans piqure, sans interruption — "
            "juste des donnees concretes pour mieux manger et mieux vivre.\n\n"
            "Comprendre votre reponse glycemique est l'un des gestes les plus puissants "
            "pour votre sante a long terme.\n\n"
            "En savoir plus sur healthspan.mu \U0001F4C8\n\n"
            "#CGM #Glycemie #SiBionics #SanteMetabolique #HealthspanMU"
        ),
    },
    "educational": {
        "en": (
            "Health isn't just inherited — it's the habits you pass on.\n\n"
            "Morning walks with someone you love. Real food cooked at home. "
            "Daily movement that doesn't need a gym. These are the rituals "
            "that compound over a lifetime and carry across generations.\n\n"
            "Your grandparents' habits shaped your parents. Your habits "
            "are shaping the next generation right now. Make them count.\n\n"
            "Start your family's wellness journey at healthspan.mu \U0001F331\n\n"
            "#WellnessJourney #HealthyHabits #Longevity #Generations #HealthspanMU #Mauritius"
        ),
        "fr": (
            "La sante ne se transmet pas seulement par les genes — mais par les habitudes.\n\n"
            "Marche matinale avec un etre cher. Repas faits maison. "
            "Mouvement quotidien sans besoin de salle de sport. Ce sont ces rituels "
            "qui s'accumulent au fil d'une vie et se transmettent entre generations.\n\n"
            "Les habitudes de vos grands-parents ont faconne vos parents. "
            "Vos habitudes faconnent la prochaine generation maintenant.\n\n"
            "Commencez votre parcours bien-etre sur healthspan.mu \U0001F331\n\n"
            "#BienEtre #Sante #Longevite #Generations #HealthspanMU"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════════
# POST 1: RingConn Gen 2 — Morning Wellness
# ═══════════════════════════════════════════════════════════════════
print("=" * 60)
print("POST 1: RingConn Gen 2")
print("=" * 60)

ringconn_scene_prompt = (
    "A premium Instagram lifestyle photograph shot from a 45-degree angle "
    "on a dark teak veranda table in Mauritius at golden hour morning light. "
    "\n\n"
    "Main subject: a sleek silver smart health tracking ring placed on a small "
    "white marble dish, angled to catch the warm light. "
    "\n\n"
    "Supporting elements (keep it balanced, not crowded): "
    "- A ceramic cup of green tea with a sprig of mint, slightly behind and to the left. "
    "- Two white frangipani flowers resting on the dark wood surface. "
    "- Soft golden morning light from the left, casting gentle shadows. "
    "- A hint of tropical greenery blurred in the background. "
    "\n\n"
    "IMPORTANT COMPOSITION: The top-right area must be open sky or soft blurred "
    "greenery (monotone, low-contrast) — this area will be used for a logo overlay. "
    "The bottom-left should have some dark space for text overlay. "
    "\n\n"
    "Style: Premium lifestyle product photography. Warm tones, clean composition, "
    "editorial quality. Shot on 50mm f/2.0 with medium depth of field. "
    "No text, no logos, no watermarks."
)

scene_path = Path("review/prompts/ringconn_step1_scene.png")
if scene_path.exists():
    print("  Step 1: Scene exists, reusing...")
    scene_bytes = scene_path.read_bytes()
else:
    print("  Step 1: Generating scene (GPT Image)...")
    result = oai.images.generate(
        model="gpt-image-1",
        prompt=ringconn_scene_prompt,
        size="1024x1024",
        quality="high",
    )
    scene_bytes = base64.b64decode(result.data[0].b64_json)
    scene_path.write_bytes(scene_bytes)
    print(f"    Scene saved: {len(scene_bytes) // 1024} KB")
all_prompts.append({"post": "RingConn", "step": 1, "model": "gpt-image-1",
                     "type": "scene_generation", "prompt": ringconn_scene_prompt})

# Step 2: Gemini product replacement
ringconn_replace_prompt = (
    "Edit Image 1: replace the generic silver ring on the marble dish with "
    "the exact RingConn Gen 2 Smart Ring from Image 2. "
    "Match its exact shape, titanium/silver finish, inner sensor details, and proportions. "
    "Light it consistently with the warm golden scene lighting. "
    "Keep everything else identical. The result should look like a real photo."
)
print("  Step 2: Replacing product (Gemini)...")
scene_img = Image.open(BytesIO(scene_bytes))
product_img = Image.open("review/product_images/ringconn_2.webp")
resp = gem.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[ringconn_replace_prompt, scene_img, product_img],
    config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
)
for part in resp.candidates[0].content.parts:
    if part.inline_data is not None:
        img = Image.open(BytesIO(part.inline_data.data))
        img.save("review/prompts/ringconn_step2_replaced.png")
        print(f"    Replaced: {img.size}")
        break
all_prompts.append({"post": "RingConn", "step": 2, "model": "gemini-2.5-flash-image",
                     "type": "product_replacement", "prompt": ringconn_replace_prompt})

# Step 3: Logo + text overlay
print("  Step 3: Logo + text overlay...")
overlay_logo_and_text(
    "review/prompts/ringconn_step2_replaced.png",
    "review/final_posts/ringconn_image.png",
    text_line1="Your health, always on.",
    text_line2="RingConn Gen 2 \u2014 healthspan.mu",
)

# Step 4: Mockups
generate_all_mockups(
    "review/final_posts/ringconn_image.png",
    CAPTIONS["ringconn"]["en"],
    "ringconn"
)

time.sleep(3)

# ═══════════════════════════════════════════════════════════════════
# POST 2: SiBionics GS1 CGM — Empowered Living
# ═══════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("POST 2: SiBionics GS1 CGM")
print("=" * 60)

sibionics_scene_prompt = (
    "A warm, natural Instagram lifestyle photograph of a woman in a bright "
    "Mauritian kitchen, seen from the side at waist level. "
    "\n\n"
    "She has medium-brown skin and is wearing a casual sleeveless top. "
    "On the back of her left upper arm, a small round white medical sensor "
    "patch is clearly visible (about 3cm diameter, circular, slightly raised). "
    "\n\n"
    "She is smiling gently and holding a bowl of fresh tropical fruit salad "
    "(papaya, mango, dragon fruit) with both hands. "
    "\n\n"
    "NO phone, NO screen, NO other devices visible — just her, the sensor, "
    "and the fruit bowl. "
    "\n\n"
    "IMPORTANT COMPOSITION: The top-right corner must be a plain, monotone "
    "blurred wall or window light (low-contrast area for logo overlay). "
    "The bottom-left should have some open space for text overlay. "
    "\n\n"
    "Style: Warm, intimate editorial lifestyle photography. Natural, empowering. "
    "Shot on 50mm f/1.8. No text, logos, or watermarks."
)

scene2_path = Path("review/prompts/sibionics_step1_scene.png")
if scene2_path.exists():
    print("  Step 1: Scene exists, reusing...")
    scene2_bytes = scene2_path.read_bytes()
else:
    print("  Step 1: Generating scene (GPT Image)...")
    result2 = oai.images.generate(
        model="gpt-image-1",
        prompt=sibionics_scene_prompt,
        size="1024x1024",
        quality="high",
    )
    scene2_bytes = base64.b64decode(result2.data[0].b64_json)
    scene2_path.write_bytes(scene2_bytes)
    print(f"    Scene saved: {len(scene2_bytes) // 1024} KB")
all_prompts.append({"post": "SiBionics", "step": 1, "model": "gpt-image-1",
                     "type": "scene_generation", "prompt": sibionics_scene_prompt})

# Step 2: Gemini product replacement
sibionics_replace_prompt = (
    "Edit Image 1: replace the generic white CGM sensor on the woman's upper arm "
    "with the exact SiBionics GS1 sensor from Image 2. "
    "Match its exact shape, color, transmitter profile, and adhesive edge appearance. "
    "Conform naturally to the arm curvature. Correct lighting and shadow. "
    "Keep everything else identical."
)
print("  Step 2: Replacing product (Gemini)...")
scene2_img = Image.open(BytesIO(scene2_bytes))
sib_product = Image.open("review/product_images/sibionics_1.jpg")
resp2 = gem.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[sibionics_replace_prompt, scene2_img, sib_product],
    config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
)
for part in resp2.candidates[0].content.parts:
    if part.inline_data is not None:
        img2 = Image.open(BytesIO(part.inline_data.data))
        img2.save("review/prompts/sibionics_step2_replaced.png")
        print(f"    Replaced: {img2.size}")
        break
all_prompts.append({"post": "SiBionics", "step": 2, "model": "gemini-2.5-flash-image",
                     "type": "product_replacement", "prompt": sibionics_replace_prompt})

# Step 3: Logo + text overlay
print("  Step 3: Logo + text overlay...")
overlay_logo_and_text(
    "review/prompts/sibionics_step2_replaced.png",
    "review/final_posts/sibionics_image.png",
    text_line1="Know your glucose. Own your health.",
    text_line2="SiBionics GS1 \u2014 healthspan.mu",
)

# Step 4: Mockups
generate_all_mockups(
    "review/final_posts/sibionics_image.png",
    CAPTIONS["sibionics"]["en"],
    "sibionics"
)

time.sleep(3)

# ═══════════════════════════════════════════════════════════════════
# POST 3: Educational — Generations of Wellness
# ═══════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("POST 3: Educational (no product)")
print("=" * 60)

edu_scene_prompt = (
    "A beautiful Instagram photograph of two women walking together along a "
    "tropical coastal path at sunrise. "
    "\n\n"
    "An older woman (grandmother, 65+, in a comfortable light outfit) and "
    "a younger woman (granddaughter, late 20s, in athleisure) walk side by side. "
    "The grandmother's hand rests gently on the younger woman's arm. "
    "Both are smiling warmly, captured mid-stride in natural conversation. "
    "\n\n"
    "Background: a dramatic mountain silhouette against a pastel pink and "
    "gold sunrise sky. Turquoise ocean visible. A few tropical trees framing "
    "the path on the right side. "
    "\n\n"
    "IMPORTANT COMPOSITION: The top-right area must be open sky (pastel tones, "
    "low-contrast, monotone) — reserved for logo overlay. "
    "The bottom-left should have some darker space for text overlay. "
    "\n\n"
    "Golden hour backlighting creating beautiful rim light on their hair. "
    "Style: National Geographic portrait quality. Shot on 85mm f/1.4. "
    "Warm color grading. No text, logos, or watermarks."
)

scene3_path = Path("review/prompts/educational_step1_scene.png")
if scene3_path.exists():
    print("  Step 1: Scene exists, reusing...")
    scene3_bytes = scene3_path.read_bytes()
else:
    print("  Step 1: Generating scene (GPT Image)...")
    result3 = oai.images.generate(
        model="gpt-image-1",
        prompt=edu_scene_prompt,
        size="1024x1024",
        quality="high",
    )
    scene3_bytes = base64.b64decode(result3.data[0].b64_json)
    scene3_path.write_bytes(scene3_bytes)
    print(f"    Scene saved: {len(scene3_bytes) // 1024} KB")
all_prompts.append({"post": "Educational", "step": 1, "model": "gpt-image-1",
                     "type": "scene_generation", "prompt": edu_scene_prompt})

# Step 2: Logo + text overlay (no product replacement)
print("  Step 2: Logo + text overlay...")
overlay_logo_and_text(
    "review/prompts/educational_step1_scene.png",
    "review/final_posts/educational_image.png",
    text_line1="Health is not inherited. It's handed down.",
    text_line2="Start your wellness journey \u2014 healthspan.mu",
)

# Step 3: Mockups
generate_all_mockups(
    "review/final_posts/educational_image.png",
    CAPTIONS["educational"]["en"],
    "educational"
)


# ═══════════════════════════════════════════════════════════════════
# SAVE CAPTIONS AS MARKDOWN
# ═══════════════════════════════════════════════════════════════════
for name, caps in CAPTIONS.items():
    md = f"# {name.title()} Post\n\n"
    md += f"## English\n\n{caps['en']}\n\n"
    md += f"## French\n\n{caps['fr']}\n\n"
    (FINAL_DIR / f"{name}_post.md").write_text(md, encoding="utf-8")
    print(f"  Caption saved: final_posts/{name}_post.md")


# ═══════════════════════════════════════════════════════════════════
# SAVE PROMPTS LOG
# ═══════════════════════════════════════════════════════════════════
with open("review/prompts/all_prompts.json", "w") as f:
    json.dump(all_prompts, f, indent=2)

print()
print("=" * 60)
print("ALL COMPLETE")
print("=" * 60)
for d in ["review/final_posts", "review/final_posts/mockups", "review/prompts"]:
    p = Path(d)
    if p.exists():
        print(f"\n{d}/")
        for f in sorted(p.iterdir()):
            if f.is_file():
                print(f"  {f.name} ({f.stat().st_size // 1024} KB)")
