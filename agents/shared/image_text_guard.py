"""Pre-publication guard against hallucinated text in generated images.

Generative image models invent lettering: a brand name on a jar the brief said
was unlabelled, garbled signage over a shopfront, misspelled words on a pouch.
A marketing agency cannot publish that, and neither negative prompting nor a
stronger CFG reliably suppresses it — the local-model bake-off's slot-1
candidate failed its publish gate on exactly this defect and re-running at a
higher CFG did not move it. So the defence lives here, in the app, which makes
it model-independent: it behaves the same for gpt-image, Gemini, or any local
model swapped in behind ``generate_image``.

Three pieces:

``inspect_image`` / ``detect_unintended_text``
    A vision call that reads every surface in the frame and reports the
    lettering that is *not* legitimate for this image. Legitimacy is
    caller-supplied via ``allowed_text``: a real product's own packaging or a
    storefront the brief asked for is fine, anything beyond that is not — and
    garbled, misspelled or invented lettering is a defect even where a real
    label legitimately belongs. With no ``allowed_text`` the frame must carry
    no readable lettering at all, which is what every prompt template in this
    repo already asks the image model for.

``strengthen_prompt``
    Builds the re-roll: the original prompt plus an escalating no-text
    instruction naming what was rejected, plus a variation seed so the model
    does not simply reproduce the previous frame.

``shared.llm.generate_image``
    Wires the two into a retry loop bounded by ``retry_cap()``, then returns
    the best attempt rather than failing the post.

Every rejection is emitted as one structured log record
(``image_text_guard.rejected``) carrying the model, attempt number and the
offending strings, so each model's trip rate is measurable from logs alone.

Fail-open by design: any error in the check itself — transport, unparseable
JSON, an image we cannot fetch — yields "not flagged", so image generation
never hard-depends on the guard. Same discipline as
``backend.app.api.v1.products._image_depicts_product``.
"""

from __future__ import annotations

import base64
import json
import logging
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

import httpx

from shared.config import settings
from shared.sanitize import sanitize_for_prompt

logger = logging.getLogger(__name__)


# Absolute ceiling on re-rolls regardless of configuration. Image generation is
# the expensive call in this loop, so this constant — not the env var — is what
# stops a fat-fingered IMAGE_TEXT_GUARD_MAX_RETRIES from multiplying spend.
MAX_RETRY_CAP = 3

# Strings a model returns to mean "nothing here"; never treated as a defect.
_PLACEHOLDER_ITEMS = {
    "",
    "-",
    "--",
    "n/a",
    "na",
    "no text",
    "no visible text",
    "none",
    "none visible",
    "not applicable",
    "null",
    "nothing",
}


# ── Shared httpx client (lazy singleton, mirrors shared.video) ──────────
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=settings.IMAGE_TEXT_GUARD_TIMEOUT_S,
            limits=httpx.Limits(max_connections=10),
        )
    return _http_client


# ── Configuration ───────────────────────────────────────────────────────


def guard_enabled() -> bool:
    """True when generated images should be text-checked before use."""
    return bool(settings.IMAGE_TEXT_GUARD_ENABLED)


def retry_cap() -> int:
    """How many re-rolls a flagged image may get, clamped to ``MAX_RETRY_CAP``."""
    try:
        configured = int(settings.IMAGE_TEXT_GUARD_MAX_RETRIES)
    except (TypeError, ValueError):
        configured = 0
    return max(0, min(configured, MAX_RETRY_CAP))


# ── Verdict ─────────────────────────────────────────────────────────────


@dataclass
class TextGuardVerdict:
    """Outcome of one text check.

    ``checked`` is False when the guard could not form an opinion (disabled,
    image unreadable, vision call failed). Such a verdict is never ``flagged``
    — that is the fail-open rule.
    """

    flagged: bool = False
    checked: bool = True
    reason: str = ""
    visible_text: list[str] = field(default_factory=list)
    unintended_text: list[str] = field(default_factory=list)
    gibberish_text: list[str] = field(default_factory=list)
    illegible_marks: list[str] = field(default_factory=list)

    @property
    def offending(self) -> list[str]:
        """Every string that made this frame unpublishable, de-duplicated."""
        seen: dict[str, None] = {}
        for item in [*self.gibberish_text, *self.unintended_text]:
            seen.setdefault(item, None)
        return list(seen)

    @property
    def malformed(self) -> list[str]:
        """Lettering that is garbled or unresolvable, whatever the allow-list.

        Distinct from ``offending``: a caller checking the output of a product
        SWAP wants this, not that. The swap legitimately reproduces the real
        pack's own small print, which is unlisted but faithful — judging it by
        the allow-list would reject a good swap. Invented or unresolvable
        letterforms are a defect no allow-list can excuse.
        """
        seen: dict[str, None] = {}
        for item in [*self.gibberish_text, *self.illegible_marks]:
            seen.setdefault(item, None)
        return list(seen)

    @property
    def severity(self) -> int:
        """Rough badness score — used to pick the least-bad attempt.

        A flagged frame always scores at least 1 so it can never tie with a
        clean one, even when the model flagged without listing the strings.
        """
        if not self.flagged:
            return 0
        return max(1, len(self.offending))


_UNAVAILABLE = "guard unavailable"


def _skipped(reason: str) -> TextGuardVerdict:
    return TextGuardVerdict(flagged=False, checked=False, reason=reason)


# ── Prompt ──────────────────────────────────────────────────────────────

_ALLOWED_NONE = (
    "NONE. This frame must contain no readable lettering anywhere. Any word, "
    "letter, number, label, sign, caption or price you can read is a defect."
)

_TEXT_GUARD_PROMPT = """You are the pre-publication QA gate for a marketing agency.

Generative image models hallucinate lettering — invented brand names on jars,
garbled shop signage, misspelled words on packaging. A client post can never
ship with that. Judge ONLY rendered text; ignore composition, lighting, styling
and subject matter.

TEXT THAT IS LEGITIMATE IN THIS IMAGE:
{allowed_block}

Inspect every surface that could carry lettering: packaging, jars, bottles,
tins, labels, shop signs, menu boards, posters, book covers, screens and phone
UI, clothing prints, badges, number plates, price tags, wall art.

For each piece of lettering you can read, decide:
  1. is it covered by the legitimate list above? (if that list says NONE, then
     nothing in the frame is legitimate)
  2. is it well-formed real language, or garbled, misspelled, invented or
     nonsense?

Garbled, misspelled, invented or malformed lettering is ALWAYS a defect — even
on a label that legitimately belongs there.

CRITICAL — PROMINENT text you cannot read is still text. A generated frame's
most common text defect is lettering that reads as writing at a glance but
resolves into no characters: a chalk board with strokes in the rhythm of words,
a jar label carrying a line of letter-like marks, a shelf tag with a
price-shaped smudge. A viewer reads these as words the brand did not write, so
they are defects, and you must report them EVEN THOUGH you cannot transcribe
them. Do not omit such a surface merely because you failed to resolve its
characters — say where it is instead.

Apply a PROMINENCE test before reporting one. Report it only if a viewer would
actually try to read it — that is, it is on the hero subject or product, OR in
the foreground, OR in sharp focus, OR large enough to draw the eye.

NOT a defect, and NOT to be reported:
- lettering deep in the background, small or soft, of the kind every real
  photograph of a shop, shelf, market or street contains. A real grocery
  photograph has dozens of unreadable labels at distance; that is what a
  photograph looks like, not a fault.
- a surface that is genuinely BLANK. An empty sign, an unlabelled jar or a
  plain box carries no lettering at all — never report blankness as marks.
- a pattern with no linguistic rhythm (fabric weave, foliage, wood grain,
  bokeh); a logo mark made of shapes rather than letterforms.

Judge each surface at the size and focus it actually appears at.

Answer STRICT JSON only:
{{"visible_text": ["<each distinct piece of lettering you CAN read, transcribed verbatim>"],
  "unintended_text": ["<the subset NOT covered by the legitimate list>"],
  "gibberish_text": ["<the subset that is garbled, misspelled, invented or nonsense>"],
  "illegible_text_marks": ["<each PROMINENT surface carrying letter-like marks you could NOT resolve, named by where it is, e.g. 'chalk board behind the counter', 'label on the left jar'. Omit distant/soft background lettering and anything genuinely blank.>"],
  "has_unintended_text": true|false,
  "reason": "<one short sentence>"}}"""


def _allowed_block(allowed_text: Sequence[str] | str | None) -> str:
    """Render the caller's whitelist into the prompt's legitimacy section."""
    if allowed_text is None:
        return _ALLOWED_NONE
    if isinstance(allowed_text, str):
        items = [allowed_text]
    else:
        items = list(allowed_text)

    cleaned = []
    for item in items:
        text = sanitize_for_prompt(str(item or "").strip(), max_length=200)
        if text and text.lower() not in _PLACEHOLDER_ITEMS:
            cleaned.append(text)
    if not cleaned:
        return _ALLOWED_NONE

    bullets = "\n".join(f"  - {text}" for text in cleaned[:30])
    return (
        "Only the following, and only where it naturally belongs (a real "
        "product's own packaging, a sign the brief asked for):\n"
        f"{bullets}\n"
        "Anything else you can read is a defect. Any of the above rendered "
        "misspelled or malformed is also a defect."
    )


def build_guard_prompt(allowed_text: Sequence[str] | str | None) -> str:
    """The full detector prompt for this image's legitimacy rules."""
    return _TEXT_GUARD_PROMPT.format(allowed_block=_allowed_block(allowed_text))


# ── Image loading ───────────────────────────────────────────────────────

_MAGIC = (
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF8", "image/gif"),
)


def sniff_content_type(data: bytes) -> str:
    """Best-effort content type from magic bytes; defaults to PNG."""
    for magic, content_type in _MAGIC:
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


async def load_image_bytes(image_ref: str) -> tuple[bytes, str] | None:
    """Resolve what ``generate_image`` returned into raw bytes.

    Handles the two shapes that function can produce — a ``data:`` URI
    (b64_json responses, every Gemini response) and an http(s) URL. Returns
    None for anything else or on any failure; the caller then fails open.
    """
    if not image_ref or not isinstance(image_ref, str):
        return None

    try:
        if image_ref.startswith("data:"):
            header, _, payload = image_ref.partition(",")
            if not payload:
                return None
            content_type = header[5:].split(";")[0] or "image/png"
            # validate=True so a corrupt payload raises instead of silently
            # decoding to a few stray bytes we would then "check".
            data = base64.b64decode(payload, validate=True)
            if not data:
                return None
            return data, (content_type or sniff_content_type(data))

        if image_ref.startswith("http://") or image_ref.startswith("https://"):
            client = _get_http_client()
            resp = await client.get(image_ref)
            resp.raise_for_status()
            data = resp.content
            content_type = (
                resp.headers.get("content-type", "").split(";")[0].strip()
                or sniff_content_type(data)
            )
            return data, content_type
    except Exception as exc:
        logger.warning("image_text_guard: could not load image bytes: %s", exc)
        return None

    return None


# ── Detection ───────────────────────────────────────────────────────────


def _clean_items(raw: object) -> list[str]:
    """Normalize one JSON list field into de-duplicated, meaningful strings."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = str(item or "").strip()
        if not text or text.lower() in _PLACEHOLDER_ITEMS:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:200])
    return out[:40]


def verdict_from_payload(payload: dict) -> TextGuardVerdict:
    """Turn the vision model's JSON into a pass/fail decision.

    The decision is made here, not by trusting the model's own boolean alone:
    a frame is rejected when it lists any unintended string OR any gibberish
    string OR any unresolvable letter-like marks OR it asserts
    ``has_unintended_text`` without listing them. Keeping the rule in code
    makes it deterministic and testable.

    ``illegible_text_marks`` carries the dominant defect class. A gate study
    over the local-model bake-off found every one of one candidate's five
    invented-text failures recorded as "none resolvable" — the model saw them
    and had nowhere to put them, so the gate passed all five. Un-transcribable
    lettering is exactly as unpublishable as lettering that reads cleanly.
    """
    if not isinstance(payload, dict):
        return _skipped("malformed verdict")

    visible = _clean_items(payload.get("visible_text"))
    unintended = _clean_items(payload.get("unintended_text"))
    gibberish = _clean_items(payload.get("gibberish_text"))
    illegible = _clean_items(payload.get("illegible_text_marks"))
    declared = bool(payload.get("has_unintended_text"))

    flagged = bool(unintended or gibberish or illegible or declared)
    reason = str(payload.get("reason") or "").strip()[:300]
    if flagged and not reason:
        reason = "unintended rendered text"
    if illegible and not (unintended or gibberish):
        # Name the surface — "unintended rendered text" with nothing to quote
        # reads like a false positive to whoever triages it.
        reason = f"unresolvable letter-like marks: {'; '.join(illegible[:3])}"[:300]

    return TextGuardVerdict(
        flagged=flagged,
        checked=True,
        reason=reason,
        visible_text=visible,
        # Marks nobody can transcribe are still unintended text; downstream
        # (strengthen_prompt, logging) reads this list, so they belong in it.
        unintended_text=unintended + illegible,
        gibberish_text=gibberish,
        illegible_marks=illegible,
    )


async def _guard_model(model: str | None) -> str:
    if model:
        return model
    configured = (settings.IMAGE_TEXT_GUARD_MODEL or "").strip()
    if configured:
        return configured
    from shared.llm import get_model_for_category  # lazy: avoids an import cycle

    return await get_model_for_category("vision")


async def detect_unintended_text(
    image_data: bytes,
    content_type: str = "image/png",
    allowed_text: Sequence[str] | str | None = None,
    *,
    model: str | None = None,
    label: str = "",
) -> TextGuardVerdict:
    """Vision-check one image for text the brief never asked for.

    ``allowed_text`` names what lettering is legitimate here — a real product's
    own packaging, a storefront the brief specified. ``None`` (the default)
    means no lettering at all is legitimate, which matches every image prompt
    this repo builds. Gibberish is a defect either way.

    Fails open: returns an unchecked, unflagged verdict on any error.
    """
    if not image_data:
        return _skipped("no image data")

    max_bytes = max(1, int(settings.IMAGE_TEXT_GUARD_MAX_IMAGE_MB)) * 1024 * 1024
    if len(image_data) > max_bytes:
        logger.warning(
            "image_text_guard: image too large to check (%d bytes > %d)",
            len(image_data),
            max_bytes,
        )
        return _skipped("image too large")

    try:
        guard_model = await _guard_model(model)
        b64 = base64.b64encode(image_data).decode()
        client = _get_http_client()
        resp = await client.post(
            f"{settings.LITELLM_BASE_URL.rstrip('/')}/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.LITELLM_MASTER_KEY}"},
            json={
                "model": guard_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": build_guard_prompt(allowed_text)},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": (
                                        f"data:{content_type or 'image/png'};base64,{b64}"
                                    )
                                },
                            },
                        ],
                    }
                ],
                # No temperature. This request used to pin it to 0, which the
                # default vision model rejects outright (HTTP 400, "Only the
                # default (1) value is supported"). It reached production only
                # because litellm's drop_params silently strips it — so the
                # determinism was never real, and pointing
                # IMAGE_TEXT_GUARD_MODEL straight at a provider, or turning
                # drop_params off, failed EVERY image open while the gate
                # still reported itself as enabled.
                "response_format": {"type": "json_object"},
            },
            timeout=settings.IMAGE_TEXT_GUARD_TIMEOUT_S,
        )
        resp.raise_for_status()
        payload = json.loads(resp.json()["choices"][0]["message"]["content"])
    except Exception as exc:
        logger.warning(
            "image_text_guard: text check failed for %s: %s", label or "image", exc
        )
        return _skipped(_UNAVAILABLE)

    return verdict_from_payload(payload)


async def inspect_image(
    image_ref: str,
    allowed_text: Sequence[str] | str | None = None,
    *,
    model: str | None = None,
    label: str = "",
) -> TextGuardVerdict:
    """``detect_unintended_text`` for whatever ``generate_image`` returned."""
    loaded = await load_image_bytes(image_ref)
    if loaded is None:
        return _skipped("image not retrievable")
    image_data, content_type = loaded
    return await detect_unintended_text(
        image_data, content_type, allowed_text, model=model, label=label
    )


# ── Re-roll ─────────────────────────────────────────────────────────────

_REROLL_BASE = (
    "ABSOLUTE REQUIREMENT — NO RENDERED TEXT. The previous render was rejected "
    "by the pre-publication text check{offending_clause}. Regenerate the same "
    "scene with every surface free of lettering: labels, packaging, jars, "
    "bottles, tins, signage, menu boards, posters, screens, clothing prints, "
    "badges and price tags must be BLANK — plain, unprinted, unmarked. Do not "
    "invent brand names, words, numbers, letterforms or symbols anywhere in "
    "the frame. Where a surface would normally carry a label, render it as a "
    "clean blank surface instead. "
)

_REROLL_ESCALATION = (
    "This has now failed more than once: remove printed-surface props "
    "altogether, or push them fully out of frame or far out of focus, rather "
    "than attempting to render them blank. "
)


def new_seed() -> int:
    """A fresh variation seed. Split out so tests can pin it."""
    return random.randint(1, 2**31 - 1)


def strengthen_prompt(
    prompt: str, verdict: TextGuardVerdict, attempt: int
) -> tuple[str, int]:
    """Build the re-roll prompt for a rejected frame.

    Returns ``(prompt, seed)``. The seed rides in the prompt as an explicit
    variation token rather than an API parameter: neither the OpenAI images
    endpoint nor the Gemini image API exposes a seed, so re-rolling is done by
    changing the prompt — which also carries the strengthened negative. A local
    backend that does take a seed can read it straight off this line.

    The offending strings come from an image the model drew, so they are
    untrusted input and go through ``sanitize_for_prompt`` before being quoted
    back at it.
    """
    offending = verdict.offending[:6]
    if offending:
        quoted = ", ".join(
            f'"{sanitize_for_prompt(text, max_length=80)}"' for text in offending
        )
        offending_clause = f" — it rendered {quoted}"
    else:
        offending_clause = ""

    seed = new_seed()
    escalation = _REROLL_ESCALATION if attempt >= 2 else ""
    return (
        f"{prompt}\n\n"
        f"{_REROLL_BASE.format(offending_clause=offending_clause)}"
        f"{escalation}"
        f"RENDER VARIATION SEED: {seed} — re-roll the composition, camera angle "
        f"and prop placement; do not repeat the previous framing.",
        seed,
    )


# ── Structured logging ──────────────────────────────────────────────────


def log_rejection(
    *,
    label: str,
    attempt: int,
    max_attempts: int,
    verdict: TextGuardVerdict,
    model: str = "",
    seed: int | None = None,
) -> None:
    """Emit one structured record per rejection.

    Fields are namespaced ``guard_*`` so they never collide with LogRecord
    attributes, and the same payload is embedded in the message so the trip
    rate is greppable even under the plain-text logging fallback.
    """
    payload = {
        "label": label,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "model": model,
        "seed": seed,
        "reason": verdict.reason,
        "unintended_text": verdict.unintended_text,
        "gibberish_text": verdict.gibberish_text,
        "severity": verdict.severity,
    }
    logger.warning(
        "image_text_guard.rejected %s",
        json.dumps(payload, default=str),
        extra={f"guard_{key}": value for key, value in payload.items()},
    )
