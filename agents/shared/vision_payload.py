"""Payload budget for images sent to vision models.

Every vision check in this repo — the placement planner, the branding
review, the hallucinated-text guard — base64-encodes an image straight into
the request body. The generators hand back multi-MB originals (1024-1536px
PNGs), vision calls are priced by resolution, and a single post triggers
3-6 of them, so shipping originals pays the full-resolution bill on every
check, forever. None of these verdicts needs detail above ~768px: the video
reel guard already samples its frames at that size (ffmpeg ``scale=768:-2``,
JPEG) and its verdicts hold, so stills get the same budget here.

Fail-open on purpose: every caller is an advisory check that itself fails
open, so an undecodable image comes back untouched rather than raising —
the caller's own size gate (or the provider) deals with it from there.
"""

from __future__ import annotations

import logging
from io import BytesIO

from PIL import Image

logger = logging.getLogger(__name__)

#: Long-edge pixel budget for any image sent to a vision model. Mirrors the
#: video reel guard's ffmpeg ``scale=768:-2`` frame extraction.
VISION_LONG_EDGE = 768

#: JPEG quality of the re-encode — visually clean for a QA/placement read,
#: and a 768px frame lands well under 200 KB.
VISION_JPEG_QUALITY = 85

#: An image already inside the pixel budget is still re-encoded when its file
#: is heavier than this: a 768px PNG can run ~1 MB, a tenth of that as JPEG.
_PASSTHROUGH_MAX_BYTES = 300 * 1024


def downscale_for_vision(
    data: bytes, content_type: str = "image/png"
) -> tuple[bytes, str]:
    """Bound *data* to the vision payload budget; returns ``(bytes, mime)``.

    Re-encodes to JPEG at ``VISION_LONG_EDGE`` max on the long edge,
    preserving aspect. A source already inside both the pixel and byte
    budgets passes through untouched — the dimension probe reads only the
    header, so the cheap path never decodes pixels. Any failure returns the
    original bytes unchanged (fail open).
    """
    if not data:
        return data, content_type

    try:
        src = Image.open(BytesIO(data))
        width, height = src.size  # header only — no pixel decode yet
        if (
            max(width, height) <= VISION_LONG_EDGE
            and len(data) <= _PASSTHROUGH_MAX_BYTES
        ):
            return data, Image.MIME.get(src.format or "", content_type)

        # thumbnail() preserves aspect and never upscales.
        src.thumbnail((VISION_LONG_EDGE, VISION_LONG_EDGE), Image.LANCZOS)
        if src.mode in ("RGBA", "LA") or (
            src.mode == "P" and "transparency" in src.info
        ):
            # JPEG has no alpha — flatten onto white, not onto black, so a
            # transparent background reads as paper rather than as a void.
            rgba = src.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.split()[3])
            src = flat
        else:
            src = src.convert("RGB")
        buf = BytesIO()
        src.save(buf, format="JPEG", quality=VISION_JPEG_QUALITY, optimize=True)
        out = buf.getvalue()
    except Exception as exc:
        logger.warning("vision_payload: downscale failed, sending original: %s", exc)
        return data, content_type

    # A source that only tripped the byte ceiling can, rarely, re-encode
    # larger (an already-tight small JPEG). Only then does the original win —
    # when the dimensions shrank, the smaller pixel bill wins regardless.
    if max(width, height) <= VISION_LONG_EDGE and len(out) >= len(data):
        return data, content_type
    return out, "image/jpeg"
