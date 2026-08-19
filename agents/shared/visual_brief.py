"""Deterministic copy -> image contract.

Why this module exists
----------------------
``generate_background`` used to build the image prompt from data that had
almost nothing to do with the copy printed on top of the finished post. In
particular the ``image_format == "ad"`` branch (roughly half of every brand's
posts, chosen by ``_decide_image_format``) took the first ``if`` and therefore
discarded BOTH the ``enhanced_image_prompt`` produced by the art-director node
AND the ``content_brief`` written by the planner. All the image model ever saw
was ``calendar_items.theme`` — a five-word category label such as "Indulgent
Everyday Pairings & Social Treat Moments".

The result is free association: a brief that literally said "styled on a
beautifully arranged sharing board with generic accompaniments like crisp
toasts, olives, and cheese" produced a frame with chocolate truffles, cashews
and no board, under a headline reading "Friday board ready for sharing?".

Nothing here calls an LLM. These are pure functions so the contract that binds
the copy to the picture is testable and identical for every brand.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

__all__ = [
    "strip_brief_tag",
    "resolve_scene_text",
    "build_scene_block",
    "extract_promised_props",
    "build_must_show_block",
    "extract_time_of_day",
    "build_time_of_day_directive",
    "coerce_guidelines",
    "brand_visual_rules",
    "build_visual_guardrail_block",
    "build_copy_contract_block",
    "build_critic_contract_block",
]


# ---------------------------------------------------------------------------
# Scene source resolution
# ---------------------------------------------------------------------------

# Planner briefs are prefixed with a format tag, e.g. "[lifestyle] Create a
# Friday evening grazing scene ...". The tag is routing metadata, not scene
# description, so it never belongs in an image prompt.
_BRIEF_TAG_RE = re.compile(r"^\s*\[[A-Za-z0-9_ /-]{2,40}\]\s*")


def strip_brief_tag(text: Any) -> str:
    """Remove a leading ``[lifestyle]`` / ``[announcement]`` routing tag."""
    return _BRIEF_TAG_RE.sub("", str(text or "")).strip()


def resolve_scene_text(
    calendar_item: dict[str, Any] | None,
    enhanced_prompt: str | None = None,
) -> str:
    """Return the best available scene description for the image model.

    Priority: the art-director's enhanced prompt, then the planner's
    ``content_brief``, then ``description``. ``theme`` is deliberately NOT a
    fallback — a theme is a campaign label, not a scene, and using it as one
    is the bug this module exists to prevent.
    """
    if enhanced_prompt and str(enhanced_prompt).strip():
        return str(enhanced_prompt).strip()
    item = calendar_item or {}
    for field in ("content_brief", "description"):
        value = strip_brief_tag(item.get(field))
        if value:
            return value
    return ""


def build_scene_block(scene_text: str) -> str:
    """Render the scene description as a labelled prompt block (or "")."""
    scene_text = (scene_text or "").strip()
    if not scene_text:
        return ""
    return f"SCENE (this is the picture — follow it literally):\n{scene_text}\n\n"


# ---------------------------------------------------------------------------
# Promised props: what the headline and the brief both committed to
# ---------------------------------------------------------------------------

# Function words plus the marketing abstractions that survive tokenisation but
# cannot be photographed ("premium moment", "quality feel"). Keeping this list
# aggressive is deliberate: a MUST-SHOW line is only useful if every entry is
# something a photographer could actually place in frame.
_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does doing done for
    from had has have having her here hers him his how i if in into is it its me
    my nor not of off on once only or our ours out over own same she should so
    some such than that the their theirs them then there these they this those
    through to too under until up very was we were what when where which while
    who whom why will with would you your yours
    also always ever every just made make makes making more most much never new
    now really still take takes their there ways well what yes
    """.split()
)

_ABSTRACT_WORDS = frozenset(
    """
    aesthetic ambience ambiance approachable authentic beautiful beautifully
    brand brands calm care casual clean clear comfort content countdown craft
    creative day days deserves detail details easy effortless elegant elevated
    energy essence experience feel feeling feels first focus fresh friendly
    good great hero hosting idea ideas image indulgence indulgent inviting
    journey joy joyful keep key life lifestyle like look looks love luxury
    minimal mood moment moments natural offer offers photo picture positioning
    post posts premium promise proof quality real refined relaxed reset ritual
    rituals scene sense sharing shot simple slow social soft standards start
    starts story style styled stylish subtle sweet time tone treat trust
    unwind vibe view visual warm way welcoming
    """.split()
)

# Weekday / season / clock words are handled by the time-of-day directive, not
# by MUST-SHOW ("board" is a prop, "Friday" is not).
_TEMPORAL_WORDS = frozenset(
    """
    monday tuesday wednesday thursday friday saturday sunday
    morning mornings afternoon afternoons evening evenings night nights
    noon midnight today tomorrow tonight dusk dawn sunset sunrise twilight
    weekend weekends week weeks month months year years
    spring summer autumn fall winter season seasonal daily weekly monthly
    """.split()
)

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")


def _singular(word: str) -> str:
    """Crude but stable singulariser — enough to match shelves/shelf, olives."""
    w = word.lower().strip("'-")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ves"):
        return w[:-3] + "f"
    if len(w) > 4 and w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _content_words(text: str) -> dict[str, str]:
    """Map singularised content word -> first surface form seen."""
    out: dict[str, str] = {}
    for match in _WORD_RE.finditer(str(text or "")):
        surface = match.group(0)
        low = surface.lower()
        if low in _STOPWORDS or low in _ABSTRACT_WORDS or low in _TEMPORAL_WORDS:
            continue
        stem = _singular(low)
        if len(stem) < 3:
            continue
        if stem in _STOPWORDS or stem in _ABSTRACT_WORDS or stem in _TEMPORAL_WORDS:
            continue
        out.setdefault(stem, low)
    return out


def extract_promised_props(
    headline: str,
    scene_text: str,
    limit: int = 8,
) -> list[str]:
    """Words the headline and the scene brief BOTH commit to.

    A concrete noun that the copywriter put in the headline *and* the planner
    put in the brief is as close to a hard visual requirement as the pipeline
    can derive without a parser: "Friday board ready for sharing?" over a brief
    that says "arranged sharing board" yields ``["board"]``.

    Agreement is the filter that keeps this precise. A word only in the brief
    already reaches the model inside the SCENE block, and a word only in the
    headline is often figurative, so neither is promoted to MUST-SHOW.
    """
    head = _content_words(headline)
    if not head:
        return []
    scene = _content_words(scene_text)
    props = [surface for stem, surface in head.items() if stem in scene]
    # Stable, readable order: as they appear in the headline.
    order = {}
    for idx, match in enumerate(_WORD_RE.finditer(str(headline or ""))):
        order.setdefault(match.group(0).lower(), idx)
    props.sort(key=lambda w: order.get(w, 10_000))
    return props[: max(0, limit)]


def build_must_show_block(props: Iterable[str]) -> str:
    """Render promised props as a hard requirement (or "" when there are none)."""
    items = [str(p).strip() for p in (props or []) if str(p).strip()]
    if not items:
        return ""
    joined = ", ".join(items)
    return (
        f"MUST BE VISIBLE IN FRAME: {joined}. "
        f"The finished post prints a headline naming these — if any one of them "
        f"is missing the picture contradicts its own caption. Do not substitute "
        f"a loosely related prop. "
    )


# ---------------------------------------------------------------------------
# Time of day
# ---------------------------------------------------------------------------

# Ordered most-specific first; the first hit wins.
_TIME_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:midnight|late[- ]night|after[- ]dark|nightcap|nightly)\b", re.I), "night"),
    (re.compile(r"\b(?:dim the lights|candle-?lit|by candlelight|lamplight)\b", re.I), "night"),
    (re.compile(r"\b(?:tonight|nights?)\b", re.I), "night"),
    (re.compile(r"\b(?:evenings?|sunset|dusk|twilight|apero|ap[ée]ro|aperitivo)\b", re.I), "evening"),
    (re.compile(r"\b(?:sunrise|dawn|daybreak|early morning|breakfast|brunch|mornings?)\b", re.I), "morning"),
    (re.compile(r"\b(?:midday|noon|lunchtime|lunch|afternoons?)\b", re.I), "afternoon"),
)

_TIME_DIRECTIVES: dict[str, str] = {
    "night": (
        "TIME OF DAY — NIGHT (non-negotiable): the scene is shot after dark. "
        "No daylight, no sunlit windows, no bright flat ambient light. Warm "
        "low-key artificial light (lamp, candle, pendant) as the key source, "
        "deep falloff into shadow, dark surroundings, visible warm highlights. "
    ),
    "evening": (
        "TIME OF DAY — EVENING (non-negotiable): the scene is shot late in the "
        "day. Low warm golden light raking in from one side or warm indoor "
        "lamplight, long soft shadows, dimmer surroundings. NOT bright midday "
        "daylight, NOT flat even studio light. "
    ),
    "morning": (
        "TIME OF DAY — MORNING (non-negotiable): soft cool early daylight, low "
        "sun angle, long gentle shadows, fresh bright-but-not-harsh ambience. "
    ),
    "afternoon": (
        "TIME OF DAY — AFTERNOON (non-negotiable): bright natural daylight with "
        "a high sun angle and short defined shadows. "
    ),
}


def extract_time_of_day(*texts: str) -> str | None:
    """Return "night" | "evening" | "morning" | "afternoon" | None.

    Earlier texts win, so callers should pass the headline before the caption
    before the brief: the headline is what the reader sees printed on the
    picture, so it is the strongest promise.
    """
    for text in texts:
        blob = str(text or "")
        if not blob.strip():
            continue
        for pattern, key in _TIME_RULES:
            if pattern.search(blob):
                return key
    return None


def build_time_of_day_directive(time_key: str | None) -> str:
    """Render the lighting directive for a time-of-day key (or "")."""
    return _TIME_DIRECTIVES.get(str(time_key or ""), "")


# ---------------------------------------------------------------------------
# Brand guardrails, applied to the picture and not only to the words
# ---------------------------------------------------------------------------

_MAX_RULES = 14
_MAX_RULE_CHARS = 220


def coerce_guidelines(brand: dict[str, Any] | None) -> dict[str, Any]:
    """``brand_guidelines`` may arrive as a JSON string; normalise to dict."""
    guidelines = (brand or {}).get("brand_guidelines") or {}
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except (json.JSONDecodeError, TypeError, ValueError):
            guidelines = {}
    return guidelines if isinstance(guidelines, dict) else {}


def _clean_rules(raw: Any) -> list[str]:
    rules: list[str] = []
    for entry in raw or []:
        text = " ".join(str(entry or "").split())
        if not text:
            continue
        rules.append(text[:_MAX_RULE_CHARS])
        if len(rules) >= _MAX_RULES:
            break
    return rules


def brand_visual_rules(brand: dict[str, Any] | None) -> list[str]:
    """The brand's written "never do this" list, cleaned and capped."""
    return _clean_rules(coerce_guidelines(brand).get("donts"))


def build_visual_guardrail_block(brand: dict[str, Any] | None) -> str:
    """Render the brand's written dos/donts as image-model constraints.

    These rules already exist as structured brand data and are already fed to
    every copy prompt — they were simply never plumbed into the image path. So
    Naturespan's "NEVER use 'farm-to-table'" governed the caption while the
    picture put a grower in an apron in a cultivated field, and FancyFinds'
    "never place sweet fruit next to a savoury cured meat" governed the caption
    while the picture staged chocolate beside Prosciutto di Parma.
    """
    guidelines = coerce_guidelines(brand)
    donts = _clean_rules(guidelines.get("donts"))
    dos = _clean_rules(guidelines.get("dos"))
    if not donts and not dos:
        return ""

    parts = [
        "BRAND RULES — THESE GOVERN THE PICTURE, NOT JUST THE WORDS. "
        "A claim the brand may not make in writing must not be asserted "
        "visually either: do not stage, cast, or dress the scene in a way "
        "that implies a forbidden claim.\n"
    ]
    if donts:
        parts.append(
            "MUST NEVER APPEAR OR BE IMPLIED:\n"
            + "\n".join(f"  - {rule}" for rule in donts)
        )
    if dos:
        parts.append(
            "SHOULD BE REFLECTED IN THE STAGING:\n"
            + "\n".join(f"  - {rule}" for rule in dos)
        )
    return "\n".join(parts) + "\n\n"


# ---------------------------------------------------------------------------
# Composed block
# ---------------------------------------------------------------------------


def build_copy_contract_block(
    *,
    headline: str = "",
    caption: str = "",
    scene_text: str = "",
    brand: dict[str, Any] | None = None,
    apply_time_of_day: bool = True,
) -> str:
    """Everything the picture owes the copy, as one prompt block.

    Deterministic: same inputs always produce the same block, so the contract
    can be asserted in tests instead of hoped for in an LLM.

    ``apply_time_of_day`` is False for studio-advertisement renders: a poster
    is lit for the product, not for the hour, and "NOT flat even studio light"
    would contradict the studio treatment in the same prompt.
    """
    props = extract_promised_props(headline, scene_text)
    time_directive = ""
    if apply_time_of_day:
        time_directive = build_time_of_day_directive(
            extract_time_of_day(headline, caption, scene_text)
        )
    return "".join(
        (
            build_must_show_block(props),
            time_directive,
            build_visual_guardrail_block(brand),
        )
    )


def build_critic_contract_block(
    headline: str,
    required_props: Iterable[str] | None,
    forbidden_rules: Iterable[str] | None,
) -> str:
    """The same contract, phrased for the vision critic that inspects the render.

    Returns "" when there is nothing to check, so callers can leave the
    existing placement-only review untouched for items with no contract.
    """
    props = [str(p).strip() for p in (required_props or []) if str(p).strip()]
    rules = [str(r).strip() for r in (forbidden_rules or []) if str(r).strip()]
    headline = " ".join(str(headline or "").split())
    if not props and not rules:
        return ""

    lines = [
        "\n\nSECOND JOB — COPY CONTRACT. Independently of placement, check "
        "whether the picture actually depicts what the post says. This does "
        "NOT change 'ok' (which is about placement only); report it in the "
        "dedicated fields below.",
    ]
    if headline:
        lines.append(f'Headline printed on this post: "{headline[:200]}"')
    if props:
        lines.append(
            "These must be physically present and identifiable in the frame — "
            "list in missing_subjects any that are absent, and do not count a "
            "loosely related substitute as present: " + ", ".join(props)
        )
    if rules:
        lines.append(
            "These brand rules govern the picture as well as the words. List "
            "in violated_rules any the staging, casting or props break:\n"
            + "\n".join(f"  - {rule}" for rule in rules)
        )
    lines.append(
        'Add to the JSON: "missing_subjects": [], "violated_rules": [] '
        "(empty arrays when the picture honours the contract)."
    )
    return "\n".join(lines)
