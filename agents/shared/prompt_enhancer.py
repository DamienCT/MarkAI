"""Image prompt enhancement.

Transforms a casual user brief (e.g. "promote the ring conne 3.5") into an
expert photographic prompt for downstream image generation models.

The enhancer is intentionally a thin wrapper around ``chat_completion`` so
the active prompt model can be swapped without touching call sites. A short
brief is run through the LLM; a long/expert-looking brief is returned
unchanged (the user clearly knows what they want).
"""

from __future__ import annotations

import logging

from shared.brand_context import ENGLISH_ONLY_RULE as _ENGLISH_ONLY_RULE
from shared.llm import chat_completion
from shared.sanitize import sanitize_for_prompt

logger = logging.getLogger(__name__)


# Briefs shorter than this (word count) are treated as casual user input and
# expanded by the LLM. Longer briefs are assumed to be expert-written and are
# passed through verbatim (after sanitization).
SHORT_BRIEF_WORD_LIMIT = 50


_ENHANCER_SYSTEM_PROMPT = (
    f"{_ENGLISH_ONLY_RULE}\n\n"
    "You are an expert commercial photography art director. "
    "Your job is to transform a short marketing brief into a detailed, "
    "production-ready prompt for a text-to-image model (gpt-image / DALL-E class). "
    "\n\n"
    "RULES:\n"
    "- Output ONLY the final image prompt. No preamble, no explanations, no quotes.\n"
    "- Stay strictly within commercial / documentary photography. Never propose "
    "  illustration, 3D, anime, cartoon, vector, painterly or game-render styles.\n"
    "- Match the user's intent: promotional product hero, lifestyle scene, "
    "  macro detail, retail context, or editorial/informational — pick whichever "
    "  best fits the brief.\n"
    "- Describe in concrete photographic terms: subject, environment, composition, "
    "  lighting, camera/lens, materials, mood, color palette guidance.\n"
    "- Keep the prompt between 200 and 450 words. Dense, factual, no fluff.\n"
    "- Reserve the top-right corner for a logo overlay (open sky, soft blur, or "
    "  monotone surface) and leave the bottom-left somewhat open for text overlay.\n"
    "- Never invent product packaging, never include text/letters/numbers in the "
    "  image, never add logos or watermarks.\n"
)


def _build_user_message(
    *,
    brief: str,
    brand_name: str,
    product_name: str,
    product_description: str,
    channel: str,
    theme: str,
    audience: str,
    audience_tone: str,
    brand_colors: dict,
    visual_style: str,
    has_product_image: bool,
    is_lifestyle_only: bool,
) -> str:
    """Compose the user-side context block fed to the enhancer."""
    primary = brand_colors.get("primary", "") if isinstance(brand_colors, dict) else ""
    secondary = (
        brand_colors.get("secondary", "") if isinstance(brand_colors, dict) else ""
    )
    accent = brand_colors.get("accent", "") if isinstance(brand_colors, dict) else ""

    if is_lifestyle_only or not has_product_image:
        product_directive = (
            "No product visible in the scene — focus entirely on the lifestyle, "
            "environment, and human/emotional context that supports the brief."
        )
    else:
        product_directive = (
            "Include a generic unlabeled neutral product container (matte plastic "
            "or paperboard, slight wear, natural shadows, completely blank — NO "
            "writing on it) placed naturally in the scene. The container will be "
            "digitally replaced later with the real product photo."
        )

    return (
        f"USER BRIEF (this is what the campaign is about):\n"
        f"{sanitize_for_prompt(brief)}\n\n"
        f"BRAND CONTEXT:\n"
        f"  Brand: {sanitize_for_prompt(brand_name)}\n"
        f"  Product: {sanitize_for_prompt(product_name) or 'N/A'}\n"
        f"  Product description: {sanitize_for_prompt(product_description) or 'N/A'}\n"
        f"  Visual style preference: {sanitize_for_prompt(str(visual_style))}\n"
        f"  Brand colors: primary {primary}, secondary {secondary}, accent {accent}\n\n"
        f"DELIVERY CONTEXT:\n"
        f"  Channel: {sanitize_for_prompt(channel) or 'instagram'}\n"
        f"  Theme: {sanitize_for_prompt(theme) or 'N/A'}\n"
        f"  Target audience: {sanitize_for_prompt(audience) or 'N/A'}\n"
        f"  Audience tone: {sanitize_for_prompt(audience_tone) or 'aspirational'}\n\n"
        f"PRODUCT PRESENCE:\n  {product_directive}\n\n"
        f"Now produce the final image prompt."
    )


def is_short_brief(brief: str) -> bool:
    """Return True if the brief is short enough to benefit from enhancement."""
    if not brief or not brief.strip():
        return False
    return len(brief.split()) < SHORT_BRIEF_WORD_LIMIT


async def enhance_image_prompt(
    *,
    brief: str,
    brand_name: str = "",
    product_name: str = "",
    product_description: str = "",
    channel: str = "",
    theme: str = "",
    audience: str = "",
    audience_tone: str = "",
    brand_colors: dict | None = None,
    visual_style: str = "",
    has_product_image: bool = False,
    is_lifestyle_only: bool = True,
) -> str | None:
    """Expand a short user brief into an expert photographic prompt.

    Returns the enhanced prompt text, or ``None`` if enhancement is not
    applicable (empty brief, long brief, or LLM failure). Callers should
    fall back to their existing prompt-building logic when ``None`` is
    returned.
    """
    if not brief or not brief.strip():
        return None

    if not is_short_brief(brief):
        logger.info(
            "Brief is %d words — skipping enhancement (pass-through)",
            len(brief.split()),
        )
        return None

    user_message = _build_user_message(
        brief=brief,
        brand_name=brand_name,
        product_name=product_name,
        product_description=product_description,
        channel=channel,
        theme=theme,
        audience=audience,
        audience_tone=audience_tone,
        brand_colors=brand_colors or {},
        visual_style=visual_style,
        has_product_image=has_product_image,
        is_lifestyle_only=is_lifestyle_only,
    )

    messages = [
        {"role": "system", "content": _ENHANCER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        result = await chat_completion(
            messages,
            category="text-fast",
            temperature=0.6,
            max_tokens=1024,
        )
        enhanced = str(result).strip().strip('"').strip("`")
        if not enhanced:
            logger.warning("Enhancer returned empty content — falling back")
            return None
        logger.info(
            "Enhanced image prompt: %d → %d words",
            len(brief.split()),
            len(enhanced.split()),
        )
        return enhanced
    except Exception as exc:
        logger.warning("Image prompt enhancement failed: %s — falling back", exc)
        return None
