"""Turn brand hex codes into plain-English colour descriptions.

Image models cannot read a hex triplet as a colour. Worse, some of them read
it as *text to render*: a bake-off run caught Z-Image painting the literal
string "Primary #1F6B3B | Secondary #8CC63F | Accent #E8DCCC" along the bottom
of the frame as gibberish lettering, and dropping a fake logo reading
"PPONCLET" into the reserved top-right zone. Negative prompts listing
"text, words, letters, numbers, typography" did not suppress it — the model was
regurgitating strings it had been handed.

So the prompt must never carry hex at all. `describe_hex` maps a colour to the
kind of phrase a photographer would actually use ("deep forest green", "warm
sand"), which is both something the model can act on and nothing it can spell.

Pure functions, no dependencies — cheap to unit test.
"""

from __future__ import annotations

import colorsys
import re

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Hue bands in degrees, each mapped to the name a person would reach for.
# Upper bound is exclusive; the list wraps, so red spans the 345..15 seam.
_HUE_BANDS: tuple[tuple[float, float, str], ...] = (
    (345.0, 15.0, "red"),
    (15.0, 40.0, "orange"),
    (40.0, 65.0, "yellow"),
    # Yellow-greens get their own band: calling #8CC63F merely "green" loses
    # the character a brand chose it for, and "lime green" is the phrase a
    # photographer would actually use.
    (65.0, 95.0, "lime green"),
    (95.0, 150.0, "green"),
    (150.0, 190.0, "teal"),
    (190.0, 250.0, "blue"),
    (250.0, 290.0, "violet"),
    (290.0, 345.0, "pink"),
)

# A few bands read better with a more specific word at low lightness.
_DEEP_NAMES = {
    "green": "forest green",
    "lime green": "olive green",
    "blue": "navy",
    "red": "burgundy",
    "orange": "rust",
    "yellow": "olive",
    "teal": "deep teal",
    "violet": "aubergine",
    "pink": "plum",
}

# ...and at high lightness with low saturation, where "pale green" beats "green".
_SOFT_NAMES = {
    "orange": "sand",
    "yellow": "cream",
    "green": "sage",
    "lime green": "pale lime",
    "blue": "powder blue",
    "red": "blush",
    "pink": "blush",
    "teal": "seafoam",
    "violet": "lilac",
}


def parse_hex(value: str) -> tuple[int, int, int] | None:
    """Return (r, g, b) 0-255 for a hex string, or None if it isn't one."""
    match = _HEX_RE.match(str(value or "").strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return (
        int(digits[0:2], 16),
        int(digits[2:4], 16),
        int(digits[4:6], 16),
    )


def _hue_name(hue_deg: float) -> str:
    for low, high, name in _HUE_BANDS:
        if low > high:  # the wrapping red band
            if hue_deg >= low or hue_deg < high:
                return name
        elif low <= hue_deg < high:
            return name
    return "neutral"


def describe_hex(value: str) -> str | None:
    """Describe a hex colour in words. None when *value* isn't a hex colour.

    The description is deliberately the kind of phrase that appears in a photo
    brief — a hue name, qualified by lightness and saturation — never a code.
    """
    rgb = parse_hex(value)
    if rgb is None:
        return None
    r, g, b = (c / 255.0 for c in rgb)
    hue, lightness, saturation = colorsys.rgb_to_hls(r, g, b)
    hue_deg = hue * 360.0

    # Greys have no meaningful hue, so name them by lightness alone.
    if saturation < 0.10:
        if lightness < 0.12:
            return "near-black"
        if lightness < 0.32:
            return "charcoal"
        if lightness < 0.62:
            return "mid grey"
        if lightness < 0.88:
            return "light grey"
        return "off-white"

    base = _hue_name(hue_deg)
    if lightness < 0.30:
        return _DEEP_NAMES.get(base, f"deep {base}")
    if lightness > 0.78:
        if saturation < 0.45:
            return _SOFT_NAMES.get(base, f"pale {base}")
        return f"bright {base}"
    if saturation < 0.30:
        return _SOFT_NAMES.get(base, f"muted {base}")
    if saturation > 0.75:
        return f"vivid {base}"
    return base


def describe_palette(colors: dict, defaults: dict | None = None) -> str:
    """Render a brand palette as a prompt-safe phrase, with NO hex in it.

    *colors* is the brand's palette dict (primary/secondary/accent). Values that
    are already words ("sage", "warm sand") pass through untouched — some brands
    describe their palette in prose, and those are exactly what we want anyway.
    Returns '' when nothing usable is present, so the caller can drop the whole
    clause rather than emit a dangling label.
    """
    merged = {**(defaults or {}), **(colors or {})}
    parts: list[str] = []
    for role in ("primary", "secondary", "accent"):
        raw = merged.get(role)
        if not raw:
            continue
        described = describe_hex(str(raw))
        if described is None:
            # Not hex — a brand that already writes its palette in words.
            described = re.sub(r"\s+", " ", str(raw)).strip()
            if not described or _HEX_RE.match(described):
                continue
        parts.append(f"{role} {described}")
    return ", ".join(parts)
