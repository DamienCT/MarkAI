"""Deterministic preparation for the generative product swap.

WHY THIS MODULE EXISTS
----------------------
The content pipeline generates a scene containing a *blank* placeholder
container and then hands that scene, plus a real product photo from the
gallery, to a generative image editor with the instruction "replace the
generic product with the real product". That editor does not composite —
it re-synthesises every pixel of the pack, including the pack's printed
copy. Left unconstrained it invents plausible-looking letterforms:

    "Une recette croortillante an ble fomgnis pour nn bien-etre dlgestil"
    "RICHE au FER, MACROUOM ut PHOESNORE"      (MAGNESIUM et PHOSPHORE)
    "1B%ARA&RICA"                              (100% ARABICA)
    "OIRETTIC"                                 (CITTERIO, mirrored)

Two deterministic levers make that far less likely, and both live here so
the content workflow, the regeneration worker and the video first-frame
path all share one implementation:

1. SPEND THE EDITOR'S INPUT BUDGET ON THE PACK.  Catalogue photos are
   mostly flat white background — the Favrichon reference is an 800x800
   JPEG in which the pack's body copy is only ~8 px tall.  The editor
   tokenises the reference at a fixed grid, so every pixel of white
   border is resolution it never spends on the lettering it is being
   asked to reproduce.  ``prepare_product_reference`` crops the flat
   border away and rescales the pack into a known working envelope.

2. STATE THE LETTERING CONTRACT.  ``build_swap_instruction`` replaces the
   one-line "keep everything else the same" prompt with an explicit
   copy-don't-draw contract, including the rule the video director
   already enforces (``workflows/video/nodes.py``): a garbled brand name
   is worse than no brand name, so copy too small to reproduce
   character-for-character must be rendered as out-of-focus texture
   rather than invented.

3. DON'T ASK FOR A LABEL MACRO.  ``pack_framing_directive`` caps the
   placeholder's footprint in the *generation* prompt.  A pack rendered
   at 85% of the frame height (the Favrichon blocker) has body copy large
   enough to read, so every invented character is legible; the same pack
   at natural product-shot distance degrades to texture.

Everything here is pure and offline — no network, no model calls — so it
is unit-testable and behaves identically on every brand.
"""

from __future__ import annotations

import logging
from io import BytesIO

import numpy as np
from PIL import Image

from shared.sanitize import sanitize_for_prompt

logger = logging.getLogger(__name__)


# --- reference preparation -------------------------------------------------

#: Per-channel tolerance (0-255) for treating a pixel as "same as the flat
#: catalogue background". Generous enough to absorb JPEG ringing around the
#: product edge without eating into soft drop shadows.
FLAT_BORDER_TOLERANCE = 14

#: Padding kept around the trimmed product, as a fraction of the crop's long
#: edge. Editors handle a product that breathes better than one jammed against
#: the reference edge.
TRIM_PADDING_RATIO = 0.03

#: Target short edge for the prepared reference. Below this the pack occupies
#: too few input tokens for its printed copy to survive re-synthesis.
REFERENCE_MIN_EDGE = 1024

#: Upper bound on the prepared reference's long edge. Beyond this the editor
#: downsamples anyway and we only pay upload cost.
REFERENCE_MAX_EDGE = 2048

#: A trimmed product smaller than this on its short edge is a thumbnail: its
#: lettering is not present in the source at all, so a generative swap can only
#: invent it. Callers should keep the clean unlabeled container instead.
MIN_SWAPPABLE_EDGE = 256


def flat_border_bbox(
    img: Image.Image, tolerance: int = FLAT_BORDER_TOLERANCE
) -> tuple[int, int, int, int] | None:
    """Return the bounding box of the non-background content in *img*.

    The background colour is taken as the median of the four corner pixels,
    which is what catalogue photos (white/grey sweep) always have. Returns
    ``None`` when there is nothing meaningful to trim — either the image is
    already tight (content reaches every edge) or it is effectively uniform.
    """
    rgb = img.convert("RGB")
    arr = np.asarray(rgb, dtype=np.int16)
    h, w = arr.shape[0], arr.shape[1]
    if h < 4 or w < 4:
        return None

    corners = np.stack(
        [arr[0, 0], arr[0, w - 1], arr[h - 1, 0], arr[h - 1, w - 1]]
    ).astype(np.int16)
    background = np.median(corners, axis=0)

    mask = np.abs(arr - background).max(axis=2) > tolerance
    if not mask.any():
        return None

    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    left, right = int(cols[0]), int(cols[-1]) + 1

    # Content already fills the frame — nothing to gain from cropping.
    if (right - left) >= w and (bottom - top) >= h:
        return None
    return left, top, right, bottom


def trim_flat_border(
    img: Image.Image,
    tolerance: int = FLAT_BORDER_TOLERANCE,
    padding_ratio: float = TRIM_PADDING_RATIO,
) -> Image.Image:
    """Crop the flat catalogue background away, keeping a small margin.

    Returns *img* unchanged when there is no flat border to remove.
    """
    box = flat_border_bbox(img, tolerance)
    if box is None:
        return img

    left, top, right, bottom = box
    pad = int(round(max(right - left, bottom - top) * max(0.0, padding_ratio)))
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(img.width, right + pad)
    bottom = min(img.height, bottom + pad)
    if right - left < 8 or bottom - top < 8:
        return img
    return img.crop((left, top, right, bottom))


def _scale_into_envelope(
    size: tuple[int, int],
    min_edge: int = REFERENCE_MIN_EDGE,
    max_edge: int = REFERENCE_MAX_EDGE,
) -> tuple[int, int]:
    """Aspect-preserving target size for the prepared reference.

    Grows the image until its SHORT edge reaches ``min_edge``, then clamps so
    the LONG edge never exceeds ``max_edge``. Never distorts the aspect ratio.
    """
    w, h = size
    if w <= 0 or h <= 0:
        return size

    scale = 1.0
    short, long_ = min(w, h), max(w, h)
    if short < min_edge:
        scale = min_edge / short
    if long_ * scale > max_edge:
        scale = max_edge / long_

    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return new_w, new_h


def reference_supports_swap(
    img: Image.Image, min_edge: int = MIN_SWAPPABLE_EDGE
) -> bool:
    """True when the trimmed product is large enough to be worth swapping in.

    A thumbnail-sized reference does not contain the pack's lettering, so the
    editor can only invent it. Callers should skip the swap and keep the clean
    unlabeled placeholder rather than publish a fabricated third-party pack.
    """
    trimmed = trim_flat_border(img)
    return min(trimmed.size) >= min_edge


def prepare_product_reference(
    raw: bytes,
    min_edge: int = REFERENCE_MIN_EDGE,
    max_edge: int = REFERENCE_MAX_EDGE,
) -> bytes:
    """Trim the flat border off a catalogue photo and rescale it.

    The editor tokenises its image inputs at a fixed grid, so a pack sitting in
    a sea of white background is described by far fewer tokens than the same
    pack filling the frame. Cropping and rescaling is the one deterministic
    lever we have on how much of the pack's printed copy the editor can
    actually see before it starts re-drawing it.

    Returns PNG bytes. Returns *raw* unchanged if it cannot be decoded.
    """
    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("prepare_product_reference: undecodable reference (%s)", exc)
        return raw

    original_size = img.size
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    img = trim_flat_border(img)
    target = _scale_into_envelope(img.size, min_edge=min_edge, max_edge=max_edge)
    if target != img.size:
        img = img.resize(target, Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="PNG")
    logger.info(
        "Prepared product reference: %s -> %s (trim+rescale)", original_size, img.size
    )
    return buf.getvalue()


# --- prompt contracts ------------------------------------------------------

#: A pack rendered taller than this fraction of the frame has body copy big
#: enough to read at feed size, which is exactly when invented lettering stops
#: being texture and becomes a brand-safety problem.
MAX_PACK_FRAME_HEIGHT_FRACTION = 0.45


def pack_framing_directive(
    max_height_fraction: float = MAX_PACK_FRAME_HEIGHT_FRACTION,
) -> str:
    """Framing cap for the placeholder container in the GENERATION prompt.

    The placeholder's on-canvas size decides how large the real pack's printed
    copy will be after the swap. Asking for a hero-scale, frame-filling
    container guarantees that any lettering the editor invents is legible.
    """
    pct = int(round(max_height_fraction * 100))
    return (
        f"Frame the container at natural product-shot distance: it must stay "
        f"under about {pct}% of the frame height and must never be a macro "
        f"close-up where its front panel or label fills the frame. Show the "
        f"container whole, at a distance where fine printing on it would read "
        f"as texture rather than as readable words. "
    )


def build_swap_instruction(
    product_name: str,
    aspect_hint: str = "",
    *,
    vendor_name: str = "",
) -> str:
    """Instruction for the generative editor performing the product swap.

    The old one-liner ("Replace the generic product ... keep everything else
    the same") left the pack's artwork entirely to the model's imagination.
    This states the contract the failures violated, item by item: copy the
    artwork, never re-letter it, never mirror it, never duplicate it, and
    degrade to texture rather than invent when the copy is too small.
    """
    name = sanitize_for_prompt(str(product_name or "").strip(), max_length=200) or "product"
    vendor = sanitize_for_prompt(str(vendor_name or "").strip(), max_length=200)
    owner = (
        f"The pack artwork belongs to {vendor}, a real third-party brand. "
        if vendor
        else "The pack artwork belongs to a real third-party brand. "
    )

    return (
        f"Replace ONLY the blank placeholder container in Image 1 with the real "
        f"product shown in Image 2 ('{name}'). Keep everything else in Image 1 "
        f"exactly the same and match its lighting, perspective, shadow and depth "
        f"of field.\n\n"
        f"PACK ARTWORK IS A COPY JOB, NOT A DRAWING JOB. {owner}"
        f"Reproduce its artwork exactly as it appears in Image 2 — the same "
        f"wordmark letterforms, the same colours, the same layout, the same "
        f"seals and certification marks.\n"
        f"- NEVER re-letter, re-typeset, translate, paraphrase, re-spell or "
        f"invent ANY word, number, weight, percentage, ingredient, claim, "
        f"certification, address or seal text. Every character on the pack must "
        f"come from Image 2.\n"
        f"- If a line of printed copy is too small to reproduce "
        f"character-for-character at this size, render it as soft out-of-focus "
        f"texture or leave that area clean. Garbled lettering on a real brand's "
        f"pack is worse than no lettering at all.\n"
        f"- Never mirror, flip or reverse the pack or any part of its artwork: "
        f"printed text must read left-to-right, never backwards.\n"
        f"- Show exactly as many packs as Image 1's placeholder shows (normally "
        f"one). Ignore duplicate packs, props, price flashes and background from "
        f"Image 2 — take only the product itself.\n"
        f"- Keep the pack at the size, angle and position the placeholder "
        f"occupies in Image 1. Do not zoom in on the label and do not make the "
        f"label the subject of the shot.\n"
        f"- Add no text, logo, badge, sticker or watermark anywhere else in the "
        f"scene.\n"
        f"{aspect_hint}"
    )
