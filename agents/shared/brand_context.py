"""Shared brand-grounding helpers for workflow LLM prompts.

Every strategy/planning LLM call must be grounded in the same three things:
the brand's identity (what the company actually is), its guardrails (the
dos/donts a human wrote during onboarding), and its enabled channels. This
module renders those into one prompt block so no workflow re-invents — or
worse, omits — the grounding.
"""

from __future__ import annotations

import json
from typing import Any

DEFAULT_BRAND_TIMEZONE = "Indian/Mauritius"

# Hard user directive: every piece of generated copy is English, for every
# brand, always. This is the ONE canonical wording — every workflow module
# imports it (as ``_ENGLISH_ONLY_RULE``) and injects it into every system
# prompt that produces user-facing text (hooks, captions, briefs, calendar
# items, campaigns, strategy documents, personas, competitor profiles, gaps,
# research prose, shot plans, overlay lines, enhanced image prompts). Keep it
# here so a drift in one module can't silently weaken the directive.
ENGLISH_ONLY_RULE = (
    "OUTPUT LANGUAGE — HARD RULE: the output language is ALWAYS English, for "
    "every brand, regardless of brand voice, locale, or the language of any "
    "input. Brand voice controls tone, not language. Foreign-language brand "
    "phrases may appear only as proper nouns (product names, or a tagline "
    "used as a name, e.g. 'magasin bio')."
)


def coerce_guidelines(brand_config: dict[str, Any] | None) -> dict[str, Any]:
    """brand_guidelines may arrive as a JSON string from the DB; normalize."""
    guidelines = (brand_config or {}).get("brand_guidelines") or {}
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except (json.JSONDecodeError, TypeError):
            guidelines = {}
    return guidelines if isinstance(guidelines, dict) else {}


def get_enabled_channels(brand_config: dict[str, Any] | None) -> list[str]:
    """Channels the brand has switched on — the ONLY platforms strategy and
    planning may reference."""
    channels_cfg = coerce_guidelines(brand_config).get("channels", {})
    enabled = [
        ch
        for ch, cfg in channels_cfg.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    return enabled or ["instagram"]


def get_brand_timezone(brand_config: dict[str, Any] | None) -> str:
    """IANA timezone the brand's posting times are expressed in."""
    tz = coerce_guidelines(brand_config).get("timezone")
    return tz if isinstance(tz, str) and tz else DEFAULT_BRAND_TIMEZONE


def build_brand_context_block(brand_config: dict[str, Any] | None) -> str:
    """Render the brand identity + hard guardrails as a prompt block.

    Inject this into EVERY strategy/planning LLM call. The dos/donts are
    human-authored hard constraints: generated strategy, themes, campaigns
    and calendar items must never contradict them.
    """
    cfg = brand_config or {}
    guidelines = coerce_guidelines(cfg)
    lines: list[str] = ["=== BRAND (ground truth — never contradict) ==="]

    if cfg.get("name"):
        lines.append(f"Brand: {cfg['name']}")
    if cfg.get("description"):
        lines.append(f"What the brand actually is: {cfg['description']}")
    if cfg.get("website_url"):
        lines.append(f"Website: {cfg['website_url']}")
    if cfg.get("tone_of_voice"):
        lines.append(f"Tone of voice: {cfg['tone_of_voice']}")

    audience = cfg.get("target_audience")
    if audience:
        if isinstance(audience, str):
            try:
                audience = json.loads(audience)
            except (json.JSONDecodeError, TypeError):
                pass
        lines.append(f"Target audience: {json.dumps(audience, ensure_ascii=False, default=str)}")

    if guidelines.get("voice_style"):
        lines.append(f"Voice style: {guidelines['voice_style']}")
    taglines = guidelines.get("taglines") or []
    if taglines:
        lines.append("Taglines: " + " | ".join(str(t) for t in taglines))

    dos = [d for d in (guidelines.get("dos") or []) if d]
    if dos:
        lines.append("\nALWAYS (brand rules):")
        lines.extend(f"- {d}" for d in dos)

    donts = [d for d in (guidelines.get("donts") or []) if d]
    if donts:
        lines.append(
            "\nNEVER (hard guardrails — a single violation makes the output "
            "unusable; do not build pillars, themes, campaigns or angles that "
            "would lead content toward any of these):"
        )
        lines.extend(f"- {d}" for d in donts)

    enabled = get_enabled_channels(cfg)
    lines.append(
        "\nEnabled platforms (reference ONLY these; no other platform may "
        "appear anywhere in the output): " + ", ".join(enabled)
    )

    lines.append(
        "\nDATES: only use dates that appear in the significant-events list "
        "provided in this prompt. NEVER state, invent, or estimate a date for "
        "any holiday, festival, or observance from memory — movable holidays "
        "(Diwali, Eid, Ganesh Chaturthi, Chinese New Year, ...) shift every "
        "year and a wrong date published as a greeting is a serious brand "
        "failure. If an event is not in the list, plan around it without "
        "naming a date."
    )
    return "\n".join(lines)
