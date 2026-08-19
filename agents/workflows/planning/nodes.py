"""Calendar planning workflow nodes — real DB and LLM calls."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from shared.brand_context import (
    DEFAULT_BRAND_TIMEZONE,
    ENGLISH_ONLY_RULE as _ENGLISH_ONLY_RULE,
    build_brand_context_block,
    get_brand_timezone,
)
from shared.editorial import (
    BRIEF_STYLE_BLOCK,
    TEMPORAL_RULES_BLOCK,
    VARIETY_RULES_BLOCK,
    apply_temporal_guard,
    build_recent_usage_block,
    format_repetition_report,
    item_stats,
    item_title,
    repetition_report,
    scrub_brief_fields,
)
from shared.language_guard import (
    check_items as check_language,
    format_flags as format_language_flags,
)
from shared.llm import (
    chat_completion,
    generate_executive_summary_plain,
    parse_llm_json,
)
from shared.sanitize import sanitize_for_prompt, sanitize_json_for_prompt
from shared.tools.database import (
    delete_planned_calendar_items,
    get_brand,
    get_brand_config,
    get_events_for_research,
    get_latest_strategy,
    get_products,
    get_recent_calendar_items,
    store_calendar_items,
    store_strategy,
)

from workflows.planning.state import PlanningState

logger = logging.getLogger(__name__)

VALID_CHANNELS = {
    "instagram",
    "facebook",
    "linkedin",
    "youtube",
    "tiktok",
    "x",
    "website_blog",
    "teams",
}
VALID_CONTENT_TYPES = {
    "post",
    "story",
    "reel",
    "carousel",
    "article",
    "newsletter",
    "ad",
    "event",
    "other",
}

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Four-digit year inside a markdown header line ("### January 2027").
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# ── Campaign / strategy-document integrity ────────────────────────────
# A 12-month campaign set never fits in one 4096-token completion: the
# response is cut mid-value, strict JSON parsing fails, and the old
# fallback wrapped the raw truncated string as a single fake campaign
# ({"name": "General Campaign", "description": "<escaped JSON>"}). That
# is exactly what production stored — June/July campaigns lost silently
# and the artifact unparseable. Fix: generate one call per quarter, and
# NEVER turn an unparsed string into a campaign record.
_CAMPAIGN_CHUNK_MONTHS = 3
_CAMPAIGN_MAX_TOKENS = 8192
_CAMPAIGN_REQUIRED_FIELDS = ("name", "description", "start_date", "end_date")
_CAMPAIGN_RECOMMENDED_FIELDS = ("pillar", "platforms", "goal", "target_audience")

# The year-long strategy document shares the truncation risk (12 monthly
# sections + two tables + a per-channel cadence block routinely runs
# 8-14K tokens against a 16K cap, so December silently disappears). It is
# generated the same way: a shared header call plus one call per quarter.
_STRATEGY_DOC_MAX_TOKENS = 8192

# How many monthly sections may be missing from the assembled document before
# the run fails. The header check is a heuristic over markdown, so one miss is
# absorbed; beyond that a whole chunk call came back empty or off-format.
_MAX_MISSING_DOC_MONTHS = 1

# _ENGLISH_ONLY_RULE (imported above from shared.brand_context) is injected
# into every system prompt that produces user-facing text here: campaign
# names/descriptions, strategy documents, calendar titles, themes, briefs.


class CalendarItemValidator(BaseModel):
    """Validates LLM-generated calendar items before DB insert."""

    scheduled_date: str
    platform: str = "instagram"
    content_type: str = "post"
    campaign_name: Optional[str] = None
    theme: Optional[str] = None
    pillar: Optional[str] = None
    target_audience: Optional[str] = None
    weekly_sub_theme: Optional[str] = None
    content_brief: Optional[str] = None
    visual_direction: Optional[str] = None
    cta_type: Optional[str] = None
    product_name: Optional[str] = None
    product_id: Optional[str] = None
    product_sku: Optional[str] = None

    @field_validator("product_id", mode="before")
    @classmethod
    def coerce_product_id(cls, v: Any) -> Optional[str]:
        """Coerce UUID objects to strings."""
        if v is None:
            return None
        return str(v)

    @field_validator("scheduled_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v)
        except (ValueError, TypeError):
            # Try date-only format
            from datetime import date as _date

            _date.fromisoformat(v[:10])
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        v = v.lower().strip()
        channel_map = {"twitter": "x", "blog": "website_blog", "web": "website_blog"}
        v = channel_map.get(v, v)
        if v not in VALID_CHANNELS:
            v = "instagram"
        return v

    @field_validator("content_type")
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        v = v.lower().strip()
        return v if v in VALID_CONTENT_TYPES else "post"

    model_config = {"extra": "allow"}


def _format_events_for_prompt(events: list[dict[str, Any]]) -> str:
    """Render the events list as a compact markdown bullet list for LLM prompts."""
    if not events:
        return (
            "(no significant events registered — do not reference or date any "
            "holiday, festival, or observance)"
        )
    lines = []
    for ev in events:
        start = ev.get("start", "")
        end = ev.get("end")
        title = ev.get("title", "")
        category = ev.get("category") or "event"
        scope = ev.get("scope", "global")
        date_str = f"{start} → {end}" if end else start
        lines.append(f"- {date_str}: {title} ({category}, {scope})")
    return "\n".join(lines)


# ── Product catalog helpers (pure — unit tested) ─────────────────────

# Product names shown to the LLM per calendar batch. Large enough for real
# variety, small enough to fit the prompt budget alongside strategy/events —
# rendered as a plain "- name" list (not JSON), so 40 names cost roughly what
# 20 cost as escaped JSON and the block never truncates mid-token.
_PRODUCT_WINDOW = 40

# Tokens ignored when scoring token-overlap product matches (articles and
# connectors carry no product identity; EN + FR since catalogs are mixed).
# NOTE: the English article "the" is deliberately NOT a stopword here — name
# normalization strips accents, so French "thé" (tea) collapses to "the" and
# filtering it would erase the head noun of every tea product, making them
# unmatchable. Keeping "the" scoreable costs almost nothing (product names
# rarely carry the article) and keeps tea matching consistent.
_PRODUCT_MATCH_STOPWORDS = frozenset({
    "a", "an", "and", "or", "of", "for", "with", "in", "on", "to",
    "de", "la", "le", "les", "du", "des", "et", "en", "au", "aux",
})


def _catalog_sample(names: list[str], batch_idx: int, window: int = _PRODUCT_WINDOW) -> list[str]:
    """Deterministic rotating slice of the catalog for one batch prompt.

    Small catalogs (<= window) are always shown in full. Larger catalogs are
    windowed by index — each batch advances ``window`` positions and wraps —
    so different batches see different slices and coverage sweeps the whole
    catalog over the horizon. No randomness: re-plans reproduce the same
    slices.
    """
    if not names:
        return []
    n = len(names)
    if n <= window:
        return list(names)
    start = (batch_idx * window) % n
    return [names[(start + k) % n] for k in range(window)]


def _format_catalog_for_prompt(names: list[str], max_length: int = 4000) -> str:
    """Render a catalog slice as a plain newline-delimited "- name" list.

    Pure function. A JSON dump of the same names costs ~2x the tokens (quotes,
    commas, brackets, \\u escapes for accented names) and truncates mid-string,
    leaving the model a broken half-name to copy "VERBATIM". One name per line
    truncates cleanly at a line boundary instead.
    """
    lines: list[str] = []
    used = 0
    for name in names:
        cleaned = sanitize_for_prompt(str(name or "").strip(), max_length=200)
        cleaned = " ".join(cleaned.split())
        if not cleaned:
            continue
        line = f"- {cleaned}"
        if used + len(line) + 1 > max_length:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _normalize_product_name(name: Any) -> str:
    """Lowercase, replace punctuation with spaces, collapse whitespace."""
    text = str(name or "").lower()
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return " ".join(text.split())


def _significant_tokens(normalized: str) -> set[str]:
    """Tokens of a normalized name that carry product identity."""
    return {t for t in normalized.split() if t not in _PRODUCT_MATCH_STOPWORDS}


def _match_product(
    item_product_name: Any, products: list[dict[str, Any]]
) -> tuple[Optional[dict[str, Any]], str]:
    """Match an LLM-emitted product name against the catalog.

    Match order:
      1. exact normalized name;
      2. normalized containment either direction, at token boundaries
         (candidate closest in length to the query wins) — only for queries
         carrying >= 2 significant tokens;
      3. best token overlap — >= 60% of the shorter name's significant
         tokens, ties broken by most shared tokens then longest match.

    A query of a single significant token ("Huile", "Lavande", "Tea") is far
    too weak to bind: it is contained in — and overlaps 100% with — a long
    tail of unrelated catalog entries, so it would attach an arbitrary
    product to the calendar item. Such queries must match EXACTLY (step 1)
    or not at all.

    Returns ``(product_or_None, outcome)`` where outcome is one of
    "no_name", "exact", "containment", "token_overlap", "no_match".
    Never raises on empty catalogs or garbage names.
    """
    query = _normalize_product_name(item_product_name)
    if not query:
        return None, "no_name"

    normalized = [
        (p, _normalize_product_name(p.get("name")))
        for p in products
        if p.get("name")
    ]
    normalized = [(p, norm) for p, norm in normalized if norm]
    if not normalized:
        return None, "no_match"

    # 1. Exact normalized match
    for p, norm in normalized:
        if norm == query:
            return p, "exact"

    # Fuzzy matching (containment and token overlap) needs at least two
    # significant tokens of evidence — see the docstring.
    query_tokens = _significant_tokens(query)
    if len(query_tokens) < 2:
        return None, "no_match"

    # 2. Containment either direction (whole-token, so "tea" never matches
    # inside "steamer"). Prefer the candidate closest in length to the query.
    containment = [
        (p, norm)
        for p, norm in normalized
        if f" {query} " in f" {norm} " or f" {norm} " in f" {query} "
    ]
    if containment:
        best_p, _ = min(containment, key=lambda pn: abs(len(pn[1]) - len(query)))
        return best_p, "containment"

    # 3. Token-overlap best match
    best: Optional[dict[str, Any]] = None
    best_key = (0.0, 0, 0)
    for p, norm in normalized:
        cand_tokens = _significant_tokens(norm)
        if not cand_tokens:
            continue
        overlap = len(query_tokens & cand_tokens)
        ratio = overlap / min(len(query_tokens), len(cand_tokens))
        key = (ratio, overlap, len(norm))
        if ratio >= 0.6 and key > best_key:
            best, best_key = p, key
    if best is not None:
        return best, "token_overlap"
    return None, "no_match"


class CampaignIntegrityError(RuntimeError):
    """Raised when generated campaigns cannot be trusted as a stored artifact.

    Surfacing this fails the planning node loudly (status=failed + error)
    instead of persisting a corrupt campaigns payload the way the previous
    raw-string fallback did.
    """


def _add_months(value: date, months: int) -> date:
    """Shift a date by N months, clamping to the target month's last day."""
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    # Last day of the target month, computed without importing the stdlib
    # `calendar` module (this file's vocabulary is already full of "calendar").
    last = 31 if month == 12 else (date(year, month + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(value.day, last))


def _campaign_chunk_windows(
    start: date, end: date, months_per_chunk: int = _CAMPAIGN_CHUNK_MONTHS
) -> list[tuple[date, date]]:
    """Split ``[start, end)`` into consecutive windows of at most N months.

    Pure function. One LLM call per window keeps every response far below
    the token cap, so no single completion has to carry a year of campaigns.
    Short horizons (activation runs at 2 weeks) collapse to a single window.
    """
    months_per_chunk = max(1, int(months_per_chunk or 1))
    if end <= start:
        return [(start, end)]
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        nxt = min(_add_months(cursor, months_per_chunk), end)
        if nxt <= cursor:  # defensive: never spin on a non-advancing cursor
            nxt = end
        windows.append((cursor, nxt))
        cursor = nxt
    return windows


def _months_in_window(start: date, end: date) -> list[str]:
    """["September 2026", ...] for every month touched by ``[start, end]``.

    Both ends are INCLUSIVE — callers holding a half-open ``[start, end)``
    window pass ``end - 1 day``. Always yields at least the start month.
    """
    if end < start:
        end = start
    months: list[str] = []
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cursor <= last:
        months.append(f"{_MONTH_NAMES[cursor.month - 1]} {cursor.year}")
        cursor = _add_months(cursor, 1)
    return months


def _chunk_months(months: list[str], size: int = _CAMPAIGN_CHUNK_MONTHS) -> list[list[str]]:
    """Group month labels into consecutive chunks of at most ``size``.

    Used for the strategy document, whose sections must tile the horizon
    without overlap — date windows straddle month boundaries and would make
    the same month appear in two sections.
    """
    size = max(1, int(size or 1))
    return [months[i : i + size] for i in range(0, len(months), size)]


def _coerce_campaign_list(parsed: Any) -> Optional[list[dict[str, Any]]]:
    """Normalize a parsed LLM payload into a list of campaign dicts.

    Returns ``None`` when the payload is not campaign-shaped at all (parse
    failure, a bare string, a number) so the caller can trigger a repair
    pass. It NEVER wraps a raw string as a campaign — that fallback is what
    produced the corrupt single "General Campaign" record in production.
    """
    if isinstance(parsed, dict):
        # json_object mode can't return a top-level array, so the model wraps
        # it. Prefer a list-valued key (e.g. {"campaigns": [...]}); if it
        # instead returned one object per campaign ({"campaign_1": {...}}),
        # collect the dict values so we don't silently drop everything.
        listed = next((v for v in parsed.values() if isinstance(v, list)), None)
        parsed = (
            listed
            if listed is not None
            else [v for v in parsed.values() if isinstance(v, dict)]
        )
    if not isinstance(parsed, list):
        return None
    return [c for c in parsed if isinstance(c, dict)]


# A serialized object/array betrays itself with a quoted key followed by a
# value. Escaped forms (\"name\": ...) count — the production artifact stored
# the array escaped inside a description.
_JSON_KEY_RE = re.compile(r'\\?"\s*:\s*(?:\\?"|[\[{\d])')
_CAMPAIGN_KEY_RE = re.compile(
    r'\\?"(?:name|description|start_date|end_date|pillar|platforms)\\?"\s*:'
)


def _looks_like_embedded_json(value: Any) -> bool:
    """True when a campaign field holds a serialized JSON blob, not prose.

    The production corruption stored the entire campaign array as an escaped
    JSON string inside one campaign's ``description``; this catches that
    shape even when the blob is truncated and therefore unparseable.

    A leading bracket alone is NOT evidence — bracket-tagged prose
    ("[Launch] Celebrate the opening of our Curepipe store …") is a normal
    LLM output shape, and flagging it failed the whole planning run for a
    cosmetic quirk. Real JSON evidence is required on top of the bracket:
    the blob opens as an object/array of objects, or it carries a quoted
    key/value pair (campaign keys especially).
    """
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if len(stripped) < 120 or stripped[:1] not in ("{", "["):
        return False
    return (
        stripped[:2] in ('{"', '[{', '[[')
        or stripped[:3] in ('{\\"', '[\\"')
        or bool(_CAMPAIGN_KEY_RE.search(stripped))
        or bool(_JSON_KEY_RE.search(stripped))
    )


def _parse_campaign_date(value: Any) -> Optional[date]:
    """Parse a campaign date field to a ``date``; ``None`` when unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _min_expected_campaigns(scope_weeks: int) -> int:
    """Sane floor for how many campaigns a horizon must yield (~1 per 2 months)."""
    try:
        weeks = max(1, int(scope_weeks or 1))
    except (TypeError, ValueError):
        weeks = 1
    months = max(1, round(weeks / 4.345))
    return max(1, months // 2)


def _merge_campaign_chunks(
    chunks: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten per-window campaign lists, dropping duplicates by name.

    Windows are generated independently, so the same seasonal campaign can
    surface twice at a quarter boundary. First occurrence wins; the merged
    list is ordered chronologically by start_date, then by name. Campaigns
    without a parseable start_date sort last rather than being dropped —
    the validation gate is what rejects them.
    """
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in chunks:
        for campaign in chunk or []:
            if not isinstance(campaign, dict):
                continue
            key = " ".join(str(campaign.get("name") or "").lower().split())
            if key:
                if key in seen:
                    continue
                seen.add(key)
            merged.append(campaign)
    merged.sort(
        key=lambda c: (
            str(_parse_campaign_date(c.get("start_date")) or "9999-12-31"),
            str(c.get("name") or ""),
        )
    )
    return merged


def _partition_campaigns(
    campaigns: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Split a merged campaign list into keepers and discards (availability gate).

    Runs BEFORE :func:`_validate_campaigns`. One malformed entry among a
    year's campaigns is an LLM quirk, not corruption: dropping it keeps the
    brand's campaigns, strategy document and calendar, where failing the node
    left the brand with nothing at all. Discarded here: entries that are not
    objects, entries missing a required field, and entries whose dates do not
    parse or run backwards. Everything that survives still faces the
    fail-closed gate (embedded-JSON blobs, count floor, JSON round-trip),
    which is what actually guards against a corrupt payload.

    Returns ``(kept, reasons)`` — one human-readable reason per discard.
    """
    if not isinstance(campaigns, list):
        return [], [f"campaigns is {type(campaigns).__name__}, expected a list"]

    kept: list[dict[str, Any]] = []
    reasons: list[str] = []
    for idx, campaign in enumerate(campaigns):
        if not isinstance(campaign, dict):
            reasons.append(
                f"campaign[{idx}] is {type(campaign).__name__}, expected an object"
            )
            continue
        name = str(campaign.get("name") or "").strip()
        label = f"campaign[{idx}] {name or '<unnamed>'}"

        missing = [
            f
            for f in _CAMPAIGN_REQUIRED_FIELDS
            if not str(campaign.get(f) or "").strip()
        ]
        if missing:
            reasons.append(f"{label}: missing required field(s) {', '.join(missing)}")
            continue

        starts = _parse_campaign_date(campaign.get("start_date"))
        ends = _parse_campaign_date(campaign.get("end_date"))
        if starts is None or ends is None:
            field = "start_date" if starts is None else "end_date"
            reasons.append(f"{label}: unparseable {field} {campaign.get(field)!r}")
            continue
        if ends < starts:
            reasons.append(f"{label}: end_date {ends} precedes start_date {starts}")
            continue

        kept.append(campaign)
    return kept, reasons


def _validate_campaigns(
    campaigns: Any,
    *,
    window_start: Optional[date] = None,
    window_end: Optional[date] = None,
    min_expected: int = 1,
) -> tuple[list[str], dict[str, int]]:
    """Integrity gate run after the campaign chunks are merged and partitioned.

    Returns ``(problems, campaigns_per_month)``. An empty problems list means
    the artifact is safe to persist. Checks: shape, required fields, no
    embedded-JSON blobs masquerading as prose, parseable and ordered dates,
    a sane minimum count for the scope, and a clean json.dumps/loads
    round-trip (storage serializes this payload verbatim).

    Callers run :func:`_partition_campaigns` first, so the per-field checks
    here are a belt-and-braces double check on survivors; what makes this
    gate fail a real run is a corrupt payload (embedded JSON, no round-trip)
    or too few campaigns left to be a plan at all.
    """
    problems: list[str] = []
    per_month: dict[str, int] = {}

    if not isinstance(campaigns, list):
        return (
            [f"campaigns is {type(campaigns).__name__}, expected a list"],
            per_month,
        )

    for idx, campaign in enumerate(campaigns):
        if not isinstance(campaign, dict):
            problems.append(
                f"campaign[{idx}] is {type(campaign).__name__}, expected an object"
            )
            continue
        name = str(campaign.get("name") or "").strip()
        label = f"campaign[{idx}] {name or '<unnamed>'}"

        missing = [
            f
            for f in _CAMPAIGN_REQUIRED_FIELDS
            if not str(campaign.get(f) or "").strip()
        ]
        if missing:
            problems.append(f"{label}: missing required field(s) {', '.join(missing)}")

        for field in ("name", "description"):
            if _looks_like_embedded_json(campaign.get(field)):
                problems.append(
                    f"{label}: {field} holds an embedded JSON blob, not prose "
                    "(raw LLM output persisted as a campaign)"
                )

        raw_start, raw_end = campaign.get("start_date"), campaign.get("end_date")
        starts, ends = _parse_campaign_date(raw_start), _parse_campaign_date(raw_end)
        # Blank/absent dates are already reported as missing required fields —
        # only a non-empty value that refuses to parse is an "unparseable" one.
        if str(raw_start or "").strip() and starts is None:
            problems.append(f"{label}: unparseable start_date {raw_start!r}")
        if str(raw_end or "").strip() and ends is None:
            problems.append(f"{label}: unparseable end_date {raw_end!r}")
        if starts and ends and ends < starts:
            problems.append(f"{label}: end_date {ends} precedes start_date {starts}")

        if starts:
            key = starts.strftime("%Y-%m")
            per_month[key] = per_month.get(key, 0) + 1
            if window_start and window_end and not (window_start <= starts <= window_end):
                # Out-of-window is odd but not corrupt — warn, don't fail.
                logger.warning(
                    "%s starts %s outside the planning window %s..%s",
                    label, starts, window_start, window_end,
                )

        soft_missing = [
            f
            for f in _CAMPAIGN_RECOMMENDED_FIELDS
            if not campaign.get(f)
        ]
        if soft_missing:
            logger.warning("%s: missing recommended field(s) %s", label, soft_missing)

    if len(campaigns) < min_expected:
        problems.append(
            f"only {len(campaigns)} campaign(s) generated, expected at least "
            f"{min_expected} for this scope"
        )

    # The payload is stored via json.dumps — prove it survives the round-trip
    # before anything persists it.
    try:
        if json.loads(json.dumps(campaigns)) != campaigns:
            problems.append("campaigns do not round-trip through json.dumps/loads")
    except (TypeError, ValueError) as exc:
        problems.append(f"campaigns are not JSON-serializable: {exc}")

    return problems, per_month


def _missing_document_months(document: str, months: list[str]) -> list[str]:
    """Months from ``months`` that have no markdown header in the document.

    Only header lines count: a month named in passing inside a table cell is
    not a monthly section, and the point of this check is to catch sections
    lost to a truncated completion. The year is matched when the header
    carries one, so "### January 2027" is not mistaken for January 2026.

    Headers are consumed as they match. A 52-week horizon spans 13 months, so
    the same month name appears twice; a yearless "### January" is evidence of
    ONE January section, not both, and must not mark the second one present.
    """
    headers = [
        ln.strip().lstrip("#").strip().lower()
        for ln in (document or "").splitlines()
        if ln.strip().startswith("#")
    ]
    if not headers:
        return list(months)

    used: set[int] = set()

    def _claim(predicate) -> bool:
        idx = next(
            (i for i, h in enumerate(headers) if i not in used and predicate(h)),
            None,
        )
        if idx is None:
            return False
        used.add(idx)
        return True

    # Pass 1: headers naming the year are unambiguous, so they are matched
    # first and cannot be stolen by a yearless header of the same month.
    pending: list[str] = []
    for label in months:
        parts = label.split()
        month_name = parts[0].lower()
        year = parts[1] if len(parts) > 1 else ""
        if not (year and _claim(lambda h: month_name in h and year in h)):
            pending.append(label)

    # Pass 2: a yearless header satisfies exactly one occurrence of its month.
    missing: list[str] = []
    for label in pending:
        month_name = label.split()[0].lower()
        if not _claim(
            lambda h: month_name in h and not any(ch.isdigit() for ch in h)
        ):
            missing.append(label)
    return missing


async def load_strategy(state: PlanningState) -> dict[str, Any]:
    """Load the latest approved strategy and enabled channels from the database."""
    brand_id = state["brand_id"]
    strategy = await get_latest_strategy(brand_id)
    if not strategy:
        return {
            "errors": [*(state.get("errors") or []), "No strategy found"],
            "status": "failed",
        }

    # Load enabled channels from brand config
    brand_config = await get_brand_config(brand_id)
    guidelines = (brand_config or {}).get("brand_guidelines", {})
    # brand_guidelines may be stored as a JSON string
    if isinstance(guidelines, str):
        try:
            guidelines = json.loads(guidelines)
        except (json.JSONDecodeError, TypeError):
            guidelines = {}
    if not isinstance(guidelines, dict):
        guidelines = {}
    overrides = guidelines.get("overrides") or {}
    channels_cfg = guidelines.get("channels", {})
    enabled_channels = [
        ch
        for ch, cfg in channels_cfg.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    if not enabled_channels:
        enabled_channels = ["instagram"]  # fallback
    logger.info("Enabled channels for brand %s: %s", brand_id, enabled_channels)

    strategy_data = strategy.get("output_payload", strategy)
    if isinstance(strategy_data, str):
        try:
            strategy_data = json.loads(strategy_data)
        except (json.JSONDecodeError, TypeError):
            strategy_data = {}

    # ── Apply "Edit Documents" overrides with PRIORITY over the auto strategy ──
    # Cadence override: per-channel posts_per_week / best_days set by the user
    # win over what the strategy generated. Stored in brand_guidelines.overrides.
    if isinstance(strategy_data, dict) and isinstance(overrides, dict) and overrides.get("cadence"):
        merged_cadence = dict(strategy_data.get("cadence") or {})
        for ch, cfg in overrides["cadence"].items():
            base = dict(merged_cadence.get(ch)) if isinstance(merged_cadence.get(ch), dict) else {}
            if isinstance(cfg, dict):
                base.update(cfg)
                merged_cadence[ch] = base
        strategy_data["cadence"] = merged_cadence
        logger.info(
            "Applied cadence override for brand %s: %s",
            brand_id, list(overrides["cadence"].keys()),
        )
    # Content pillars / target audiences overrides (used downstream for rotation).
    if isinstance(strategy_data, dict) and isinstance(overrides, dict):
        if overrides.get("content_pillars"):
            strategy_data["content_pillars"] = [
                {"name": p} if isinstance(p, str) else p
                for p in overrides["content_pillars"]
            ]
        if overrides.get("target_audiences"):
            strategy_data["target_audiences"] = overrides["target_audiences"]
        # Positioning / monthly themes overrides flow to the campaign LLM via
        # the strategy blob (see _generate_campaigns_inner prompt). Positioning
        # is merged into value_proposition so the other sub-fields survive.
        if overrides.get("positioning"):
            pos = strategy_data.get("positioning")
            if isinstance(pos, dict):
                pos = dict(pos)
                pos["value_proposition"] = overrides["positioning"]
                strategy_data["positioning"] = pos
            else:
                strategy_data["positioning"] = overrides["positioning"]
        if overrides.get("monthly_themes"):
            strategy_data["monthly_themes"] = overrides["monthly_themes"]

    # Load existing calendar items for deduplication context
    try:
        existing_items = await get_recent_calendar_items(brand_id, days=90)
    except Exception as exc:
        logger.warning(
            "Failed to load existing calendar items for brand %s: %s", brand_id, exc
        )
        existing_items = []

    # Load significant events (global + brand-scoped) so downstream nodes can
    # anchor the strategy document and calendar items to real dates.
    try:
        events = await get_events_for_research(brand_id, months_ahead=12)
    except Exception as exc:
        logger.warning("Failed to load events for brand %s: %s", brand_id, exc)
        events = []
    logger.info("Loaded %d events for planning brand %s", len(events), brand_id)

    return {
        "strategy": strategy_data,
        "enabled_channels": enabled_channels,
        "existing_items": existing_items,
        "events": events,
        # Brand identity + hard guardrails — injected into every planning LLM
        # prompt so generated campaigns/items stay grounded in the real brand.
        "brand_context": build_brand_context_block(brand_config),
        # IANA tz the brand's "best times" are expressed in (store_calendar
        # converts brand-local wall times to UTC at insert time).
        "brand_timezone": get_brand_timezone(brand_config),
        # Edit Documents override; defaults to mixed (posts + reels).
        "content_format": (overrides.get("content_format") if isinstance(overrides, dict) else None) or "mixed",
        "campaign_overrides": (overrides.get("campaigns") if isinstance(overrides, dict) else None) or [],
        "removed_campaigns": (overrides.get("removed_campaigns") if isinstance(overrides, dict) else None) or [],
    }


async def _campaigns_from_prompt(
    prompt: list[dict[str, str]], *, label: str
) -> list[dict[str, Any]]:
    """Run one campaign-generation call, with a single JSON-repair retry.

    Raises ``CampaignIntegrityError`` when the model never returns parseable
    JSON. A raw unparsed string is NEVER converted into a campaign record —
    that fallback is what stored a year of campaigns as one escaped blob.
    """
    result = await chat_completion(
        prompt,
        temperature=0.5,
        max_tokens=_CAMPAIGN_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    campaigns = _coerce_campaign_list(parse_llm_json(result, fallback=None))
    if campaigns is not None:
        return campaigns

    logger.warning(
        "%s: campaign JSON unparseable (%d chars) — retrying with a repair prompt",
        label,
        len(result),
    )
    repair_prompt = [
        {
            "role": "system",
            "content": (
                "You repair malformed JSON. The input below came from a campaign "
                "planner and is invalid — most likely truncated mid-value. Return "
                'ONLY a valid JSON object of the form {"campaigns": [...]} holding '
                "the campaigns that are COMPLETE in the input. Drop any trailing "
                "campaign whose fields were cut off. Do not invent campaigns, do "
                "not add commentary, and keep every intact field value verbatim."
            ),
        },
        {"role": "user", "content": sanitize_for_prompt(str(result), max_length=12000)},
    ]
    repaired = await chat_completion(
        repair_prompt,
        temperature=0.0,
        max_tokens=_CAMPAIGN_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    campaigns = _coerce_campaign_list(parse_llm_json(repaired, fallback=None))
    if campaigns is None:
        raise CampaignIntegrityError(
            f"{label}: campaign JSON still unparseable after the repair retry "
            f"(original {len(result)} chars, repair {len(repaired)} chars) — "
            "refusing to persist raw LLM output as a campaign"
        )
    logger.info("%s: repair retry recovered %d campaign(s)", label, len(campaigns))
    return campaigns


async def generate_campaigns(state: PlanningState) -> dict[str, Any]:
    """Generate campaign plans from the strategy using LLM, plus a year-long strategy document."""
    try:
        return await _generate_campaigns_inner(state)
    except Exception as exc:
        logger.error("generate_campaigns failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_campaigns failed: {exc}",
            ],
        }


async def _generate_campaigns_inner(state: PlanningState) -> dict[str, Any]:
    brand_id = state["brand_id"]
    strategy = state.get("strategy", {})
    # Coerced the same way generate_calendar/store_calendar do, so the
    # campaign horizon can never disagree with the calendar horizon.
    scope_weeks = max(1, int(state.get("scope_weeks", 52) or 52))
    enabled_channels = state.get("enabled_channels", ["instagram"])
    events = state.get("events", [])
    events_block = _format_events_for_prompt(events)
    brand_context = state.get("brand_context", "")
    horizon_start = datetime.now(timezone.utc).date()
    horizon_end = horizon_start + timedelta(weeks=scope_weeks)
    start_date = horizon_start.isoformat()
    end_date = horizon_end.isoformat()

    # Load brand info for strategy document (get_brand returns name, etc.)
    brand = await get_brand(brand_id) or {}

    # Load products for product-aware campaign planning
    try:
        products = await get_products(brand_id)
    except Exception as exc:
        logger.warning("Failed to load products for brand %s: %s", brand_id, exc)
        products = []
    product_summary = sanitize_json_for_prompt(
        [
            {
                "name": p.get("name"),
                "category": p.get("category"),
                "vendor": p.get("vendor"),
                "description": (p.get("description") or "")[:200],
            }
            for p in products[:50]
        ],
        max_length=3000,
    )

    channels_str = ", ".join(enabled_channels)

    # ── Edit Documents campaign overrides ─────────────────────────────────
    # User-curated campaigns MUST be included (enriched with full structure);
    # removed campaign names MUST NOT reappear.
    campaign_overrides = state.get("campaign_overrides") or []
    removed_campaigns = state.get("removed_campaigns") or []
    constraints = ""
    if campaign_overrides:
        must_include = "; ".join(
            f"{c.get('name', '')}" + (f" — {c.get('description', '')}" if c.get("description") else "")
            for c in campaign_overrides if isinstance(c, dict) and c.get("name")
        )
        if must_include:
            constraints += (
                " You MUST include these user-defined campaigns, enriching each with the full "
                f"structure (use the given name/description verbatim as the basis): {must_include}."
                " Include each one only in the window where its timing belongs — another"
                " window's call covers the rest."
            )
    if removed_campaigns:
        constraints += (
            " You MUST NOT generate any campaign matching these removed names: "
            f"{', '.join(removed_campaigns)}."
        )

    # ── Chunked campaign generation ────────────────────────────────────────
    # One LLM call per quarter (or fewer for short horizons). A single call
    # asked to carry a whole year overruns the token cap and comes back cut
    # mid-value; chunking keeps every response comfortably inside it.
    campaign_user_msg = (
        f"{brand_context}\n\n"
        f"Strategy:\n{sanitize_json_for_prompt(strategy, max_length=8000)}\n\n"
        f"Significant Events Calendar (anchor campaigns to these dates where relevant):\n"
        f"{events_block}\n\n"
        f"Available Products:\n{product_summary}"
    )
    windows = _campaign_chunk_windows(horizon_start, horizon_end)

    def _campaign_prompt(
        win_start: date, win_end: date, idx: int, total: int
    ) -> list[dict[str, str]]:
        if total > 1:
            # The window is half-open [start, end); the prompt reads
            # inclusive, so hand the model the last covered day. Without
            # this, two consecutive windows both claim the boundary day and
            # two differently-named campaigns can start on it.
            win_last = max(win_start, win_end - timedelta(days=1))
            scope_rule = (
                f"This is window {idx} of {total} in a {scope_weeks}-week plan "
                f"running {start_date} to {end_date}. Generate campaigns ONLY for "
                f"{win_start.isoformat()} to {win_last.isoformat()} — every "
                "campaign's start_date MUST fall inside that window. The other "
                "windows are handled by separate calls: do not plan for them and "
                "do not repeat their campaigns."
            )
        else:
            scope_rule = (
                f"Generate campaigns for the period {start_date} to {end_date} "
                f"({scope_weeks} weeks)."
            )
        return [
            {
                "role": "system",
                "content": (
                    f"{_ENGLISH_ONLY_RULE}\n\n"
                    "You are a campaign planner. Based on the brand's target market and strategy, generate specific campaigns. "
                    f"{scope_rule} "
                    f"Generate content ONLY for these platforms: {channels_str}. "
                    "Do NOT generate content for any other platforms. "
                    "Each campaign MUST have: name, description, start_date "
                    "(YYYY-MM-DD), end_date (YYYY-MM-DD), pillar, platforms, goal, kpis, "
                    "target_metrics (object with reach, engagement_rate targets), "
                    "creative_direction (2-3 sentences describing the visual/tonal approach), "
                    "content_format_mix (object with content_type percentages e.g. {reel: 40, carousel: 30, static: 20, story: 10}), "
                    "target_audience (primary persona name from strategy). "
                    "Return a JSON object with a single key \"campaigns\" whose value is an array of the campaign objects. "
                    "Keep descriptions to 2-4 sentences so the response is never truncated."
                    + constraints
                ),
            },
            {"role": "user", "content": campaign_user_msg},
        ]

    # return_exceptions so a failing window doesn't leave its siblings'
    # results (or exceptions) unretrieved; the first failure is re-raised
    # once every window has settled.
    campaign_chunks = await asyncio.gather(
        *[
            _campaigns_from_prompt(
                _campaign_prompt(win_start, win_end, idx + 1, len(windows)),
                label=f"campaigns[{win_start.isoformat()}..{win_end.isoformat()}]",
            )
            for idx, (win_start, win_end) in enumerate(windows)
        ],
        return_exceptions=True,
    )
    for chunk in campaign_chunks:
        if isinstance(chunk, BaseException):
            raise chunk
    campaigns = _merge_campaign_chunks(list(campaign_chunks))

    # Safety net: drop any campaign whose name the user removed (LLM may ignore).
    if removed_campaigns:
        _removed_lc = {n.strip().lower() for n in removed_campaigns if isinstance(n, str)}
        campaigns = [
            c for c in campaigns
            if (c.get("name") or "").strip().lower() not in _removed_lc
        ]

    # Report (don't fail on) user-curated campaigns the model never produced —
    # it enriches names, so exact-match absence is a smell, not corruption.
    if campaign_overrides:
        _generated_lc = {(c.get("name") or "").strip().lower() for c in campaigns}
        dropped = [
            c.get("name")
            for c in campaign_overrides
            if isinstance(c, dict)
            and c.get("name")
            and str(c["name"]).strip().lower() not in _generated_lc
        ]
        if dropped:
            logger.warning(
                "Brand %s: user-defined campaigns absent by exact name from the "
                "generated set (may have been renamed): %s",
                brand_id, dropped,
            )

    # ── Availability gate: drop the defective, keep the plan ───────────────
    # A single campaign with a missing/reversed/unparseable date is an LLM
    # quirk. Failing the node for it costs the brand its campaigns, strategy
    # document AND calendar (the graph routes straight to END), so those
    # entries are discarded and logged instead.
    campaigns, dropped_campaigns = _partition_campaigns(campaigns)
    for reason in dropped_campaigns:
        logger.warning("CAMPAIGN_DROPPED brand=%s: %s", brand_id, reason)

    # ── Validation gate ────────────────────────────────────────────────────
    # Nothing corrupt reaches storage: required fields present, dates parse
    # and are ordered, a sane count for the scope, and a clean JSON
    # round-trip. Failing here fails the node (status=failed + error).
    min_expected = _min_expected_campaigns(scope_weeks)
    problems, per_month = _validate_campaigns(
        campaigns,
        window_start=horizon_start,
        window_end=horizon_end,
        min_expected=min_expected,
    )
    logger.info(
        "CAMPAIGNS brand=%s total=%d dropped=%d windows=%d min_expected=%d per_month: %s",
        brand_id,
        len(campaigns),
        len(dropped_campaigns),
        len(windows),
        min_expected,
        ", ".join(f"{m}={n}" for m, n in sorted(per_month.items())) or "(none dated)",
    )
    if problems:
        for problem in problems:
            logger.error("CAMPAIGN_INVALID brand=%s: %s", brand_id, problem)
        raise CampaignIntegrityError(
            f"campaign validation failed for brand {brand_id} "
            f"({len(problems)} problem(s)): " + "; ".join(problems[:8])
        )

    # ── Content calendar strategy document (chunked like campaigns) ────────
    # A 12-month document (12 monthly sections + two tables + a per-channel
    # cadence block) routinely runs 8-14K tokens against a 16K cap, so the
    # tail months silently disappeared. Generated as a header section plus
    # one section per window instead, each far below the cap.
    doc_user_msg = (
        f"{brand_context}\n\n"
        f"Brand: {sanitize_for_prompt(brand.get('name', '') or '')}\n"
        f"Positioning: {sanitize_json_for_prompt(strategy.get('positioning', {}), max_length=3000)}\n"
        f"Pillars: {sanitize_json_for_prompt(strategy.get('pillars', []), max_length=3000)}\n"
        f"Audiences: {sanitize_json_for_prompt(strategy.get('audiences', []), max_length=3000)}\n"
        f"Cadence: {sanitize_json_for_prompt(strategy.get('cadence', {}), max_length=3000)}\n"
        f"Themes: {sanitize_json_for_prompt(strategy.get('themes', []), max_length=3000)}\n"
        f"Enabled Channels: {channels_str}\n\n"
        f"Significant Events Calendar (the ONLY dates you may cite — include EVERY one):\n"
        f"{events_block}"
    )
    doc_common_rules = (
        f"{_ENGLISH_ONLY_RULE}\n\n"
        "You are a senior content strategist writing ONE section of a brand's "
        "Content Calendar Strategy Document. That document is the reference "
        "guide for daily content generation.\n\n"
        "FORMATTING REQUIREMENTS (strict):\n"
        "- Use '## ' for major section headers\n"
        "- Use '### ' for month headers, always with the year (e.g., '### January 2027')\n"
        "- Use bullet lists (- ) for key points\n"
        "- Use **bold** for emphasis on key terms\n\n"
        "EVENTS CALENDAR INTEGRATION (CRITICAL):\n"
        "- The user message includes a 'Significant Events Calendar' — these are the ONLY event dates you may cite.\n"
        "- Date-range events (e.g. 2026-05-11 → 2026-05-27) are multi-day campaigns; plan a sustained content arc across the range.\n"
        "- Do NOT invent or cite events that are not in that list.\n"
        "- If the list is empty, say so rather than inventing dates.\n\n"
        "Write ONLY the section you are asked for — other sections are written "
        "by separate calls and concatenated with yours. Do not repeat them and "
        "do not add a closing summary.\n\n"
    )
    # horizon_end is exclusive; the last covered day is the day before it.
    horizon_months = _months_in_window(horizon_start, horizon_end - timedelta(days=1))
    months_csv = ", ".join(horizon_months)

    header_prompt = [
        {
            "role": "system",
            "content": (
                doc_common_rules
                + "YOUR SECTION — the opening of the document:\n"
                "1. An executive summary paragraph (no header).\n"
                "2. '## Yearly Overview' — a markdown table with columns: "
                "Month | Theme | Key Dates | Content Focus | Pillar Rotation. "
                "One row per month listed by the user, in order. EVERY event "
                "from the Significant Events Calendar must appear in the "
                "'Key Dates' cell of its month's row.\n"
                "3. '## Content Mix by Platform' — a markdown table of content "
                "mix ratios per enabled platform.\n"
                "4. '## Channel Posting Cadence' — REQUIRED, with this exact format. "
                "For EACH enabled channel:\n"
                "### [Channel Name]\n"
                "- Weekly cadence: [N] posts per week\n"
                "- Best days: [day1], [day2], [day3]\n"
                "- Best times: [HH:MM], [HH:MM], [HH:MM]\n"
                "- Primary role: [one sentence]\n"
                "- Best formats: [format1], [format2]\n"
                "This section is critical — the content calendar generator reads "
                "these exact numbers.\n"
                "Do NOT write the per-month detail sections; later sections cover those."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{doc_user_msg}\n\n"
                f"Months to cover, in order: {months_csv}\n\n"
                "Write the opening sections of the content calendar strategy document."
            ),
        },
    ]

    def _doc_window_prompt(win_months: list[str]) -> list[dict[str, str]]:
        win_csv = ", ".join(win_months)
        return [
            {
                "role": "system",
                "content": (
                    doc_common_rules
                    + f"YOUR SECTION — the monthly detail for {win_csv}.\n"
                    "Write one '### <Month> <Year>' subsection per month listed "
                    "above, in order, and nothing else above them — no wrapper "
                    "header (a month name in a wrapper header would confuse the "
                    "generator that slices this document by month). Each "
                    "subsection covers:\n"
                    "- Monthly theme with strategic rationale\n"
                    "- Seasonal hooks and every event from the events calendar that falls in that month\n"
                    "- Content pillar rotation for the month\n"
                    "- Strategic rationale for content sequencing\n"
                    "End with a '---' horizontal rule.\n"
                    "Do NOT write an executive summary, the yearly overview table, "
                    "the content mix table, or the channel cadence section."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{doc_user_msg}\n\n"
                    f"Months to cover, in order: {win_csv}\n\n"
                    "Write the monthly detail sections for exactly those months."
                ),
            },
        ]

    # Section windows tile the horizon by calendar month (not by the campaign
    # date windows, which straddle month boundaries and would emit the same
    # month twice).
    doc_month_chunks = _chunk_months(horizon_months)
    # return_exceptions mirrors the campaign gather: one failing section must
    # not leave its siblings' exceptions unretrieved ("Task exception was
    # never retrieved" noise on an already-failing run). The first failure is
    # re-raised once every section has settled.
    doc_sections = await asyncio.gather(
        *[
            chat_completion(
                prompt, temperature=0.6, max_tokens=_STRATEGY_DOC_MAX_TOKENS
            )
            for prompt in [
                header_prompt,
                *[_doc_window_prompt(chunk) for chunk in doc_month_chunks],
            ]
        ],
        return_exceptions=True,
    )
    for section in doc_sections:
        if isinstance(section, BaseException):
            raise section
    strategy_document = "\n\n".join(
        str(section).strip() for section in doc_sections if str(section).strip()
    )

    missing_months = _missing_document_months(strategy_document, horizon_months)
    logger.info(
        "STRATEGY_DOC brand=%s chars=%d sections=%d months=%d missing=%s",
        brand_id,
        len(strategy_document),
        len(doc_sections),
        len(horizon_months),
        missing_months or "none",
    )
    # Chunking guarantees one call per quarter, so a missing month means a
    # section really was lost — not that a single call ran out of tokens.
    # The old `> len(horizon_months) // 2` threshold let 6 of 13 months
    # vanish behind a log line, which is the very defect chunking fixed. One
    # miss is tolerated (the header check is a heuristic on markdown text);
    # two is a lost section.
    if not strategy_document or len(missing_months) > _MAX_MISSING_DOC_MONTHS:
        raise CampaignIntegrityError(
            f"strategy document incomplete for brand {brand_id}: "
            f"{len(strategy_document)} chars, missing monthly sections for "
            f"{missing_months or '(document empty)'}"
        )
    if missing_months:
        logger.error(
            "STRATEGY_DOC_GAPS brand=%s missing monthly sections: %s",
            brand_id,
            missing_months,
        )

    return {"campaigns": campaigns, "strategy_document": strategy_document}


# ── Calendar batch scheduling (pure — unit tested) ───────────────────

# Concurrent calendar LLM calls. 8 avoids rate-limit spikes while keeping a
# full-year run at ~5 min wall clock.
_BATCH_CONCURRENCY = 8

# How many distinct titles / statistics of the run so far are replayed into
# each batch prompt. Capped so the block stays a few hundred tokens even at
# week 50 of a 52-week horizon.
_RECENT_TITLES_CAP = 40
_RECENT_STATS_CAP = 15

# Upper bound on wave size. Batches inside one wave cannot see each other, so
# the wave width IS the blind spot of the repetition damping. VARIETY_RULES
# mandates "any single statistic at most once in any rolling 4-week window";
# a 12-week wave meant the mechanism structurally could not enforce its own
# headline rule. Capped at the rule's window so prompt and mechanism agree.
_MAX_WAVE_WINDOWS = 4


def _wave_size(
    n_channels: int,
    concurrency: int = _BATCH_CONCURRENCY,
    max_windows: int = _MAX_WAVE_WINDOWS,
) -> int:
    """Number of week-windows generated per wave.

    Batches must run in waves (not one flat gather) for repetition damping to
    work at all: a batch can only be told which titles/stats are already
    taken if the batches that produced them have finished. Waves are the
    cheapest ordering that preserves throughput — pick a size whose
    ``windows x channels`` task count is about three full rounds of the
    semaphore, so every wave saturates the LLM pool and the whole run costs
    roughly one extra round rather than serializing.

    ``max_windows`` then clamps that to the variety rule's own 4-week window
    (see ``_MAX_WAVE_WINDOWS``): a wave wider than the rule it enforces
    cannot enforce it. Multi-channel brands still fill the pool (3 channels
    x 4 windows = 12 tasks); a single-channel brand trades a little
    parallelism for a damping signal that matches the prompt.
    """
    channels = max(1, int(n_channels or 1))
    target_tasks = max(1, int(concurrency)) * 3
    windows = -(-target_tasks // channels)  # ceil division
    return max(1, min(int(max_windows), windows))


async def generate_calendar(state: PlanningState) -> dict[str, Any]:
    """Generate individual calendar items from campaigns, incorporating product awareness."""
    try:
        return await _generate_calendar_inner(state)
    except Exception as exc:
        logger.error("generate_calendar failed: %s", exc)
        return {
            "status": "failed",
            "errors": [
                *(state.get("errors") or []),
                f"generate_calendar failed: {exc}",
            ],
        }


async def _generate_calendar_inner(state: PlanningState) -> dict[str, Any]:
    brand_id = state["brand_id"]
    campaigns = state.get("campaigns", [])
    strategy = state.get("strategy", {})
    strategy_document = state.get("strategy_document", "")
    enabled_channels = state.get("enabled_channels", ["instagram"])
    existing_items = state.get("existing_items", [])
    events = state.get("events", [])
    brand_context = state.get("brand_context", "")

    # Brand tz for rendering stored UTC timestamps as brand-local dates in the
    # dedup hint (a 20:00-local post is stored as 16:00Z; naive [:10] slicing
    # would list 00:00–04:00 brand-local posts under the previous day).
    try:
        from zoneinfo import ZoneInfo

        brand_tz = ZoneInfo(state.get("brand_timezone") or DEFAULT_BRAND_TIMEZONE)
    except Exception:
        brand_tz = timezone.utc

    def _local_date(value: Any) -> str:
        """Render a stored scheduled timestamp as a brand-local YYYY-MM-DD."""
        dt = value
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt)
            except ValueError:
                return dt[:10]
        if not isinstance(dt, datetime):
            return str(dt or "")[:10]
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(brand_tz).strftime("%Y-%m-%d")

    # Content format (Edit Documents override). "mixed" = posts + reels
    # (default); "posts_only" = single-image posts everywhere. The final
    # item_type layout is assigned deterministically in store_calendar.
    content_format = state.get("content_format", "mixed")
    if content_format == "mixed":
        _ctype_rule = (
            '- Vary content types: mostly "post" (single image), some "reel" '
            "(short vertical video)\n"
        )
        _ctype_field = 'content_type (post/reel), '
    else:
        _ctype_rule = (
            '- content_type MUST be "post" for EVERY item — single-image posts only '
            "(NO reels, carousels, stories, videos, or articles)\n"
        )
        _ctype_field = 'content_type (always "post"), '

    # Calendar items cover the full year (Jan 1 → Dec 31). The batch loop
    # runs all week×channel combinations in parallel (semaphore=8) so the
    # full-year run completes in ~5 min instead of the old ~36 min sequential.
    now = datetime.now(timezone.utc)
    scope_weeks = max(1, int(state.get("scope_weeks", 52) or 52))
    start_date_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_date_dt = start_date_dt + timedelta(weeks=scope_weeks)

    # Targeted re-plan (Edit Documents "Apply"): regenerate ONLY the calendar
    # months the user changed. "YYYY-MM" strings → {(year, month)}. Empty set =
    # full horizon (legacy behavior). Only target/purge these months.
    target_months: set[tuple[int, int]] = set()
    for m in state.get("target_months") or []:
        try:
            y, mo = str(m).split("-")[:2]
            target_months.add((int(y), int(mo)))
        except (ValueError, TypeError):
            continue
    if target_months:
        logger.info("Targeted re-plan for brand %s — months=%s", brand_id, sorted(target_months))

    # Build cadence string from strategy so the LLM respects weekly post counts.
    # Try structured cadence data first, then fall back to extracting from strategy document.
    cadence = strategy.get("cadence", {})
    cadence_lines = []
    for ch in enabled_channels:
        ch_cadence = cadence.get(ch, {}) if isinstance(cadence, dict) else {}
        if isinstance(ch_cadence, dict):
            posts_per_week = ch_cadence.get("posts_per_week", ch_cadence.get("frequency", ""))
        elif isinstance(ch_cadence, (int, float)):
            posts_per_week = ch_cadence
        else:
            posts_per_week = str(ch_cadence) if ch_cadence else ""
        if posts_per_week:
            cadence_lines.append(f"- {ch}: {posts_per_week} posts per week")

    # If structured cadence is incomplete, extract from strategy document text
    if len(cadence_lines) < len(enabled_channels) and strategy_document:
        import re as _re
        for ch in enabled_channels:
            if any(ch in line for line in cadence_lines):
                continue  # Already have this channel
            # Search for patterns like "Instagram\n5 posts per week" or "instagram: 3 posts/week"
            pattern = _re.compile(
                rf"{ch}[:\s\n]*(\d+)\s*posts?\s*(?:per|/)\s*week",
                _re.IGNORECASE,
            )
            match = pattern.search(strategy_document)
            if match:
                cadence_lines.append(f"- {ch}: {match.group(1)} posts per week")
            else:
                cadence_lines.append(f"- {ch}: 3 posts per week")  # Safe default

    cadence_instruction = "\n".join(cadence_lines) if cadence_lines else "3 posts per week per channel."

    # Load real products ONCE per planning run for product-aware planning.
    # Keep the FULL catalog — each batch is shown a deterministic rotating
    # window of names (_catalog_sample) so coverage sweeps the whole catalog
    # over the horizon instead of repeating only the first few products.
    products = await get_products(brand_id)
    catalog_names = [str(p["name"]).strip() for p in products if p.get("name")]

    channels_str = ", ".join(enabled_channels)

    def _extract_month_strategy(month_label: str) -> str:
        """Extract the relevant month/quarter section from the strategy document.

        ``month_label`` is a '%B %Y' label ("August 2026"). The year is
        load-bearing: a 52-week horizon spans 13 months, so one month name
        appears twice and a bare-name match spliced BOTH years' sections into
        every batch prompt for that month.

        Searches for the month in any header format (##, ###, **, bold, etc.)
        and captures everything until the next month header — including a
        header for the SAME month in a different year. Also captures the
        quarter section and channel strategy guidance.
        """
        if not strategy_document:
            return ""

        parts = month_label.split()
        month_name = parts[0]
        year = parts[1] if len(parts) > 1 else ""

        all_months = _MONTH_NAMES
        month_idx = next((i for i, m in enumerate(all_months) if m.lower() == month_name.lower()), -1)
        quarter = f"Q{(month_idx // 3) + 1}" if month_idx >= 0 else ""

        def _is_our_month(stripped: str, name: str) -> bool:
            """True when the line names ``name`` and not some OTHER year."""
            if name.lower() not in stripped:
                return False
            if not year:
                return True
            years = _YEAR_RE.findall(stripped)
            return not years or year in years

        lines = strategy_document.split("\n")
        result_lines: list[str] = []
        capturing = False

        for line in lines:
            stripped = line.strip().lower()

            # Start capturing if line contains this month's name or quarter
            if not capturing:
                if _is_our_month(stripped, month_name) or (quarter and quarter.lower() in stripped and "strategy" in stripped):
                    capturing = True
                    result_lines.append(line)
                    continue
            else:
                # Stop when we hit a DIFFERENT month's header — a different
                # month name, or our own month name under another year.
                is_next_month = False
                for m in all_months:
                    if m.lower() not in stripped:
                        continue
                    if not any(stripped.startswith(p) for p in ("#", "**")):
                        continue
                    if m.lower() == month_name.lower() and _is_our_month(stripped, m):
                        continue
                    is_next_month = True
                    break
                # Also stop at next quarter header (unless it's our quarter)
                if not is_next_month and "q" in stripped and "strategy" in stripped:
                    for q in ["q1", "q2", "q3", "q4"]:
                        if q in stripped and q != quarter.lower():
                            is_next_month = True
                            break
                if is_next_month:
                    capturing = False
                    continue
                result_lines.append(line)

        extracted = "\n".join(result_lines).strip()

        # Also extract channel strategy section (posting frequency, best times)
        channel_section: list[str] = []
        capturing_channels = False
        for line in lines:
            stripped = line.strip().lower()
            if "channel strategy" in stripped or "publishing structure" in stripped or "posting frequency" in stripped:
                capturing_channels = True
                channel_section.append(line)
                continue
            if capturing_channels:
                if stripped.startswith("#") and "channel" not in stripped and "publishing" not in stripped:
                    break
                channel_section.append(line)

        channel_text = "\n".join(channel_section).strip()

        # Combine month section + channel guidance
        parts = []
        if extracted:
            parts.append(extracted)
        if channel_text:
            parts.append(f"\nCHANNEL STRATEGY & POSTING SCHEDULE:\n{channel_text}")

        if parts:
            return "\n\n".join(parts)

        # Fallback: return first 4000 chars (executive summary + overview)
        return strategy_document[:4000]

    # ── Build per-channel cadence lookup ──────────────────────────────
    # Primary source: structured cadence from strategy state (populated by plan_cadence node)
    # Fallback: regex extraction from strategy document text
    import re as _re

    channel_cadence: dict[str, int] = {}
    channel_best_days: dict[str, str] = {}
    channel_best_times: dict[str, str] = {}

    for ch in enabled_channels:
        posts = 3  # safe default
        best_days = ""
        best_times = ""

        # Try structured cadence first (from strategy state)
        ch_cad = cadence.get(ch, {}) if isinstance(cadence, dict) else {}
        if isinstance(ch_cad, dict):
            if ch_cad.get("posts_per_week"):
                posts = int(ch_cad["posts_per_week"])
            if ch_cad.get("best_days"):
                days = ch_cad["best_days"]
                best_days = ", ".join(days) if isinstance(days, list) else str(days)
            if ch_cad.get("best_times"):
                times = ch_cad["best_times"]
                best_times = ", ".join(times) if isinstance(times, list) else str(times)

        # Fallback: extract from strategy document text
        if posts == 3 and strategy_document:
            # Match "### Instagram\n- Weekly cadence: 5 posts per week" or "Instagram\n5 posts per week"
            patterns = [
                rf"###?\s*{ch}[\s\S]*?(?:weekly\s*cadence|cadence)[:\s]*(\d+)\s*posts",
                rf"###?\s*{ch}[\s\S]*?(\d+)\s*posts?\s*(?:per|/)\s*week",
                rf"{ch}\s*\n[^#]*?(\d+)\s*posts?\s*(?:per|/)\s*week",
            ]
            for pattern in patterns:
                m = _re.search(pattern, strategy_document, _re.IGNORECASE)
                if m:
                    posts = int(m.group(1))
                    break

        if not best_days and strategy_document:
            days_m = _re.search(rf"###?\s*{ch}[\s\S]*?best\s*days?[:\s]*([^\n]+)", strategy_document, _re.IGNORECASE)
            if days_m:
                best_days = days_m.group(1).strip()

        if not best_times and strategy_document:
            times_m = _re.search(rf"###?\s*{ch}[\s\S]*?best\s*times?[:\s]*([^\n]+)", strategy_document, _re.IGNORECASE)
            if times_m:
                best_times = times_m.group(1).strip()

        channel_cadence[ch] = posts
        if best_days:
            channel_best_days[ch] = best_days
        if best_times:
            channel_best_times[ch] = best_times

    logger.info("PROMPT_DEBUG channel_cadence: %s", channel_cadence)
    logger.info("PROMPT_DEBUG channel_best_days: %s", channel_best_days)
    logger.info("PROMPT_DEBUG channel_best_times: %s", channel_best_times)

    # ── Extract weekly pillar rotation from strategy ────────────────
    pillar_rotation = ""
    if strategy_document:
        rot_match = _re.search(
            r"(?:weekly\s*pillar\s*rotation|recommended\s*weekly.*rotation)[:\s]*\n((?:.*\n)*?)(?:\n\n|\Z)",
            strategy_document,
            _re.IGNORECASE,
        )
        if rot_match:
            pillar_rotation = rot_match.group(1).strip()

    # ── Generate per-channel per-week (parallel) ───────────────
    all_items: list[dict[str, Any]] = []
    batch_size_days = 7
    expected_total = 0
    channel_counts: dict[str, int] = {ch: 0 for ch in enabled_channels}

    # Pre-build all (batch_start, batch_end) windows for the full year
    batch_windows: list[tuple[datetime, datetime]] = []
    cur = start_date_dt
    while cur < end_date_dt:
        bend = min(cur + timedelta(days=batch_size_days), end_date_dt)
        batch_windows.append((cur, bend))
        cur = bend

    # Targeted re-plan: keep only windows overlapping a target month (a 7-day
    # window spans at most two months — check both ends).
    if target_months:
        batch_windows = [
            (s, e)
            for (s, e) in batch_windows
            if (s.year, s.month) in target_months
            or ((e - timedelta(days=1)).year, (e - timedelta(days=1)).month) in target_months
        ]

    for _ in batch_windows:
        for ch in enabled_channels:
            expected_total += channel_cadence.get(ch, 3)

    # Semaphore caps concurrent LLM calls — 8 at a time avoids rate-limit
    # spikes while keeping wall-clock time to ~5 min for a full year.
    _sem = asyncio.Semaphore(_BATCH_CONCURRENCY)

    # Repetition damping: every batch is told which titles/angles and which
    # statistics earlier batches on the SAME channel already spent. That needs
    # ordering, so windows run in waves (see the wave loop below) instead of
    # one flat gather — waves stay fully parallel internally.
    recent_titles: dict[str, list[str]] = {ch: [] for ch in enabled_channels}
    recent_stats: dict[str, list[str]] = {ch: [] for ch in enabled_channels}

    async def _run_batch(
        batch_idx: int,
        batch_start: datetime,
        batch_end: datetime,
        channel: str,
        recent_block: str = "",
    ) -> list[dict]:
        async with _sem:
            b_start_str = batch_start.strftime("%Y-%m-%d")
            b_last_day = batch_end - timedelta(days=1)
            b_end_str = b_last_day.strftime("%Y-%m-%d")
            # Year-qualified: the horizon spans 13 months, so "August" alone
            # would pull BOTH Augusts' sections out of the strategy document.
            b_month = batch_start.strftime("%B %Y")
            month_strategy = _extract_month_strategy(b_month)
            posts_needed = channel_cadence.get(channel, 3)
            best_days = channel_best_days.get(channel, "")
            best_times = channel_best_times.get(channel, "")

            # Rotating product window: each batch sees a different slice of the
            # catalog (advancing by batch_idx, deterministic — no random).
            # Over all week×channel batches this sweeps the full catalog, so
            # the planner isn't stuck on the first products it ever saw.
            batch_products = _catalog_sample(catalog_names, batch_idx)

            # Dedup from DB-existing items only (no cross-batch deps in parallel mode)
            ch_existing = [
                i for i in existing_items
                if (i.get("platform") or i.get("channel", "")) == channel
            ]
            dedup_lines = [
                f"{_local_date(i.get('scheduled_at') or i.get('scheduled_date'))} | "
                f"{i.get('pillar', '')} | {i.get('theme') or i.get('title', '')} | "
                f"{i.get('weekly_sub_theme', '')}"
                for i in ch_existing[-30:]
            ]
            dedup = (
                f"ALREADY SCHEDULED {channel.upper()} CONTENT (do NOT repeat these):\n"
                + "\n".join(dedup_lines) + "\n\n"
            ) if dedup_lines else ""

            week_events = [
                ev for ev in events
                if ev.get("start") and (ev.get("end") or ev["start"]) >= b_start_str
                and ev["start"] <= b_end_str
            ]
            week_events_block = (
                _format_events_for_prompt(week_events)
                if week_events
                else "(no significant events this week — schedule regular content only)"
            )

            prompt = [
                {
                    "role": "system",
                    "content": (
                        f"{_ENGLISH_ONLY_RULE}\n\n"
                        "You are a content calendar planner.\n\n"
                        f"Generate EXACTLY {posts_needed} posts for {channel.upper()} "
                        f"for the week of {b_start_str} through {b_end_str}.\n\n"
                        "IMPORTANT: You MUST return a JSON array with the items. "
                        "Do NOT return error messages, questions, or clarification requests. "
                        "Use the information provided and make reasonable assumptions for anything missing.\n\n"
                        f"POSTING SCHEDULE:\n"
                        f"- Posts this week: {posts_needed}\n"
                        f"- Best days: {best_days or 'spread evenly across the week'}\n"
                        f"- Best times: {best_times or '07:00, 13:00, 20:00'}\n"
                        f"- Assign each post a specific date and time from the best days/times\n\n"
                        + (f"WEEKLY PILLAR ROTATION:\n{pillar_rotation}\n\n" if pillar_rotation else "")
                        + "RULES:\n"
                        "- Each item MUST have a UNIQUE weekly_sub_theme\n"
                        "- Do NOT repeat any theme from the ALREADY SCHEDULED list\n"
                        + _ctype_rule
                        + "- Each content_brief must describe a DISTINCT topic\n"
                        "- Every item's theme/content_brief must be SPECIFIC to this "
                        "brand — its actual products, certifications, suppliers, and "
                        "shop (see the BRAND block in the user message) — NOT generic "
                        "wellness/lifestyle filler that could fit any brand\n"
                        "- NEVER violate the brand's NEVER-guardrails: no item may "
                        "reference, script, or imply anything those guardrails forbid\n\n"
                        + TEMPORAL_RULES_BLOCK
                        + VARIETY_RULES_BLOCK
                        + BRIEF_STYLE_BLOCK
                        + (
                            "PRODUCT RULES:\n"
                            "- Product-focused items — roughly HALF of the posts and "
                            "ALL reels — MUST include a \"product_name\" copied "
                            "VERBATIM from the PRODUCT CATALOG list in the user "
                            "message (exact spelling, no paraphrasing, no invented "
                            "products)\n"
                            "- Lifestyle/education items may set product_name to "
                            "null\n\n"
                            if batch_products
                            else ""
                        )
                        + "EVENT DATE RULES:\n"
                        "- If the strategy mentions a specific event with a date (e.g., 'World Cancer Day (Feb 4)'), "
                        "content referencing that event should ONLY be scheduled on the event date itself or the day before/after\n"
                        "- Do NOT spread event-specific content across the entire week or month\n"
                        "- Weeks that do not contain an event date should focus on the month's general theme, "
                        "pillar rotation, and educational content — NOT reference the event\n"
                        "- An event post replaces one of the week's regular posts on that specific day\n\n"
                        "Each item MUST include ALL fields: "
                        "campaign_name, scheduled_date (YYYY-MM-DD), "
                        "scheduled_time (HH:MM 24h format), "
                        f"platform (always \"{channel}\"), "
                        + _ctype_field
                        + "pillar, theme, weekly_sub_theme, target_audience, "
                        "content_brief (2-3 sentences), "
                        "product_name (copied VERBATIM from the PRODUCT CATALOG, "
                        "or null for lifestyle/education items), "
                        "visual_direction (1 sentence), "
                        "cta_type (shop/learn/engage/share).\n"
                        "Return a JSON array."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{brand_context}\n\n"
                        f"{dedup}"
                        f"{recent_block}"
                        f"Campaigns:\n{sanitize_json_for_prompt(campaigns, max_length=2000)}\n\n"
                        f"SIGNIFICANT EVENTS THIS WEEK (schedule on the event date, do NOT invent others):\n"
                        f"{week_events_block}\n\n"
                        f"STRATEGY FOR {b_month.upper()} ({channel.upper()}):\n"
                        f"{sanitize_for_prompt(month_strategy, max_length=5000)}\n\n"
                        + (
                            "PRODUCT CATALOG (copy names VERBATIM into product_name):\n"
                            f"{_format_catalog_for_prompt(batch_products)}"
                            if batch_products
                            else "PRODUCT CATALOG: (no products synced — set product_name to null)"
                        )
                    ),
                },
            ]

            logger.info(
                "PROMPT_DEBUG batch=%d channel=%s week=%s→%s posts_needed=%d",
                batch_idx, channel, b_start_str, b_end_str, posts_needed,
            )

            try:
                result = await chat_completion(prompt, temperature=0.5, max_tokens=4096)
                logger.info(
                    "RESPONSE_DEBUG batch=%d channel=%s response_chars=%d preview=%s",
                    batch_idx, channel, len(result), result[:300],
                )

                batch_items = parse_llm_json(result, fallback=[])
                if isinstance(batch_items, dict):
                    if "scheduled_date" in batch_items or "platform" in batch_items:
                        batch_items = [batch_items]
                    else:
                        batch_items = next(
                            (v for v in batch_items.values() if isinstance(v, list)), []
                        )

                for item in batch_items:
                    item["platform"] = channel

                items_got = len(batch_items)

                if items_got < posts_needed and items_got > 0:
                    missing = posts_needed - items_got
                    logger.warning(
                        "RETRY batch=%d channel=%s: got %d/%d, retrying for %d more",
                        batch_idx, channel, items_got, posts_needed, missing,
                    )
                    used_dates = [i.get("scheduled_date", "") for i in batch_items]
                    retry_prompt = [
                        {
                            "role": "system",
                            "content": (
                                f"Generate EXACTLY {missing} more {channel.upper()} posts "
                                f"for {b_start_str} through {b_end_str}. "
                                f"Do NOT use these dates (already taken): {', '.join(used_dates)}. "
                                f"Best days: {best_days or 'any remaining day'}. "
                                f"Best times: {best_times or '07:00, 13:00, 20:00'}. "
                                "Return a JSON array. Same fields as before. "
                                f"{_ENGLISH_ONLY_RULE}"
                            ),
                        },
                        {"role": "user", "content": prompt[1]["content"]},
                    ]
                    try:
                        retry_result = await chat_completion(retry_prompt, temperature=0.5, max_tokens=4096)
                        retry_items = parse_llm_json(retry_result, fallback=[])
                        if isinstance(retry_items, dict):
                            retry_items = next((v for v in retry_items.values() if isinstance(v, list)), [])
                        for item in retry_items:
                            item["platform"] = channel
                        batch_items.extend(retry_items)
                        logger.info("RETRY got %d more items for %s", len(retry_items), channel)
                    except Exception as retry_exc:
                        logger.warning("RETRY failed for %s: %s", channel, retry_exc)

                if not batch_items:
                    logger.warning(
                        "BATCH_ZERO batch=%d channel=%s produced 0 items — response: %s",
                        batch_idx, channel, result[:500],
                    )
                else:
                    logger.info("BATCH_OK batch=%d channel=%s produced %d items", batch_idx, channel, len(batch_items))

                return batch_items

            except Exception as batch_exc:
                logger.error("BATCH_FAIL batch=%d channel=%s: %s", batch_idx, channel, batch_exc)
                return []

    # Launch batch×channel tasks in waves. Every wave is a full concurrent
    # gather (same semaphore, same throughput); the only thing the wave
    # boundary buys is that wave N+1's prompts can list the titles and
    # statistics waves 1..N already spent on that channel, which is what
    # damps the year-long repetition. Ordering costs ~1 extra concurrency
    # round per run, not a serialization — see _wave_size.
    wave_size = _wave_size(len(enabled_channels))
    indexed_windows = list(enumerate(batch_windows))
    for wave_start in range(0, len(indexed_windows), wave_size):
        wave = indexed_windows[wave_start:wave_start + wave_size]
        recent_blocks = {
            ch: build_recent_usage_block(
                recent_titles[ch],
                recent_stats[ch],
                channel=ch,
                max_titles=_RECENT_TITLES_CAP,
                max_stats=_RECENT_STATS_CAP,
            )
            for ch in enabled_channels
        }
        tasks = [
            _run_batch(
                idx * len(enabled_channels) + ch_idx,
                bs, be, ch, recent_blocks.get(ch, ""),
            )
            for idx, (bs, be) in wave
            for ch_idx, ch in enumerate(enabled_channels)
        ]
        wave_results = await asyncio.gather(*tasks)
        for r in wave_results:
            all_items.extend(r)
            for item in r:
                ch = item.get("platform", "")
                if ch in channel_counts:
                    channel_counts[ch] += 1
                if ch in recent_titles:
                    title = item_title(item)
                    if title:
                        recent_titles[ch].append(title)
                    sub = str(item.get("weekly_sub_theme") or "").strip()
                    if sub:
                        recent_titles[ch].append(sub)
                    recent_stats[ch].extend(item_stats(item))
        # Bound the carried context so late waves don't blow the prompt
        # budget on a 52-week horizon.
        for ch in enabled_channels:
            recent_titles[ch] = recent_titles[ch][-(_RECENT_TITLES_CAP * 2):]
            recent_stats[ch] = recent_stats[ch][-(_RECENT_STATS_CAP * 2):]

    # ── Batch summary ─────────────────────────────────────────────
    logger.info(
        "BATCH_SUMMARY total=%d expected=%d (%.0f%%) waves=%d. Per channel: %s",
        len(all_items),
        expected_total,
        (len(all_items) / expected_total * 100) if expected_total else 0,
        -(-len(batch_windows) // wave_size) if batch_windows else 0,
        ", ".join(f"{ch}={cnt}" for ch, cnt in channel_counts.items()),
    )

    # ── Post-generation deterministic passes ──────────────────────
    # The LLM sees one week at a time; these run over the whole horizon and
    # are the only thing that can catch cross-item defects. None of them
    # drops an item — a hole in the published cadence is worse than a flawed
    # line, and the warnings below tell the QA loop exactly what to inspect.
    _apply_post_generation_checks(
        brand_id, all_items, events, catalog_names=catalog_names
    )

    return {"calendar_items": all_items}


def _proper_nouns(catalog_names: Sequence[str]) -> list[str]:
    """Names the language guard must not read as French.

    Product names are stored "Supplier, Product, Size", so both the whole name
    and its leading supplier segment are names in their own right — copy says
    "Moulin des Moines cereals" far more often than it quotes the full SKU.
    """
    names: list[str] = []
    for name in catalog_names:
        text = str(name).strip()
        if not text:
            continue
        names.append(text)
        head = text.split(",")[0].strip()
        if head and head != text:
            names.append(head)
    return names


def _apply_post_generation_checks(
    brand_id: str,
    items: list[dict[str, Any]],
    events: list[dict[str, Any]],
    catalog_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Temporal guard + brief hygiene + repetition measurement over one run.

    Rewrites ``items`` in place and logs what it changed. Returns the
    repetition report so callers (and tests) can assert on it.
    """
    # 1. Temporal guard — anticipatory framing about an event that has
    #    already happened by the item's own publish date is factually false.
    try:
        stale = apply_temporal_guard(items, events)
    except Exception as exc:  # never let a guard sink a whole plan
        logger.warning("TEMPORAL_GUARD failed for brand %s: %s", brand_id, exc)
        stale = []
    if stale:
        logger.warning(
            "TEMPORAL_GUARD brand=%s de-anticipated %d/%d items (post-event "
            "countdown language). Affected: %s",
            brand_id,
            len(stale),
            len(items),
            "; ".join(
                f"{f['scheduled_date']} {f['title']!r} "
                f"[{','.join(f['markers'])}] after {'/'.join(f['events'])}"
                for f in stale[:20]
            ),
        )

    # 2. Brief hygiene — content_brief is creative direction, not commentary
    #    about a post.
    scrubbed = 0
    try:
        for item in items:
            if isinstance(item, dict) and scrub_brief_fields(item):
                scrubbed += 1
    except Exception as exc:
        logger.warning("BRIEF_SCRUB failed for brand %s: %s", brand_id, exc)
    if scrubbed:
        logger.info(
            "BRIEF_SCRUB brand=%s stripped generator meta-language from "
            "%d/%d briefs",
            brand_id,
            scrubbed,
            len(items),
        )

    # 3. Language — ENGLISH_ONLY_RULE is a prompt directive, and on 2026-08-18
    #    it let five French items through; one was mid-render before anyone
    #    noticed. Nothing is rewritten: a machine translation of marketing copy
    #    is worse than the writer's English and would hide that the generator
    #    misbehaved. The warning names the items to reissue.
    try:
        foreign = check_language(items, allow=_proper_nouns(catalog_names))
    except Exception as exc:
        logger.warning("LANGUAGE_GUARD failed for brand %s: %s", brand_id, exc)
        foreign = []
    if foreign:
        logger.warning(
            "LANGUAGE_GUARD brand=%s %d/%d items are not in English "
            "(ENGLISH_ONLY_RULE ignored). Affected: %s",
            brand_id,
            len(foreign),
            len(items),
            format_language_flags(foreign),
        )

    # 4. Repetition measurement — log only, never rejects. These counters are
    #    the QA loop's yardstick cycle over cycle.
    try:
        report = repetition_report(items)
    except Exception as exc:
        logger.warning("REPETITION_REPORT failed for brand %s: %s", brand_id, exc)
        return {}
    logger.info(
        "REPETITION_REPORT brand=%s %s", brand_id, format_repetition_report(report)
    )
    return report


async def assign_products(state: PlanningState) -> dict[str, Any]:
    """Match calendar items to real products from the database."""
    try:
        brand_id = state["brand_id"]
        items = state.get("calendar_items", [])
        try:
            products = await get_products(brand_id)
        except Exception as exc:
            logger.warning("Failed to load products for brand %s: %s", brand_id, exc)
            products = []

        outcome_counts: dict[str, int] = {}
        updated_items = []
        for item in items:
            product, outcome = _match_product(item.get("product_name"), products)
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            if product is not None:
                item["product_id"] = product.get("id")
                item["product_sku"] = product.get("sku")
            updated_items.append(item)

        logger.info(
            "assign_products brand=%s items=%d catalog=%d outcomes: %s",
            brand_id,
            len(items),
            len(products),
            ", ".join(f"{k}={v}" for k, v in sorted(outcome_counts.items())) or "none",
        )
        return {"calendar_items": updated_items}
    except Exception as exc:
        logger.error("assign_products failed: %s", exc)
        return {
            "status": "failed",
            "errors": [*(state.get("errors") or []), f"assign_products failed: {exc}"],
        }


# Channels that get deterministic reel slots when content_format == "mixed".
_REEL_MIX_CHANNELS = frozenset({"instagram", "facebook"})
# Which slot in each channel-week becomes a reel (index % 4 == _REEL_SLOT).
_REEL_SLOT = 2


def _assign_item_types(db_items: list[dict[str, Any]], content_format: str) -> None:
    """Deterministically assign content_type before insert (video pipeline).

    - youtube is video-only: every item becomes a 'reel' regardless of format;
    - "mixed" brands: every 4th instagram/facebook item per channel-week is a
      'reel' (index % 4 == _REEL_SLOT — no randomness, so re-plans reproduce
      the same layout), everything else is a 'post';
    - "posts_only" brands keep single-image 'post' everywhere else.
    """

    def _week_key(item: dict[str, Any]) -> tuple[int, int]:
        sa = item.get("scheduled_at")
        if not isinstance(sa, datetime):
            try:
                sa = datetime.strptime(str(sa)[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                return (0, 0)
        iso = sa.isocalendar()
        return (iso[0], iso[1])

    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for item in db_items:
        channel = item.get("channel", "")
        if channel == "youtube":
            item["content_type"] = "reel"
        elif content_format == "mixed" and channel in _REEL_MIX_CHANNELS:
            buckets.setdefault((channel, *_week_key(item)), []).append(item)
        else:
            item["content_type"] = "post"

    for bucket in buckets.values():
        bucket.sort(key=lambda it: str(it.get("scheduled_at")))
        for idx, item in enumerate(bucket):
            item["content_type"] = "reel" if idx % 4 == _REEL_SLOT else "post"


async def store_calendar(state: PlanningState) -> dict[str, Any]:
    """Persist calendar items and strategy document to the database."""
    brand_id = state["brand_id"]
    items = state.get("calendar_items", [])
    strategy_document = state.get("strategy_document", "")
    enabled_channels = state.get("enabled_channels", [])
    # Targeted re-plan: limit storing/purging to specific months when provided.
    target_months: set[tuple[int, int]] = set()
    for m in state.get("target_months") or []:
        try:
            y, mo = str(m).split("-")[:2]
            target_months.add((int(y), int(mo)))
        except (ValueError, TypeError):
            continue
    # Brand timezone: upstream prompts express "best times" as brand-local
    # wall times, so parsed datetimes stay NAIVE here and store_calendar_items
    # localizes them to this tz before converting to UTC for storage.
    tz_name = state.get("brand_timezone") or DEFAULT_BRAND_TIMEZONE
    try:
        from zoneinfo import ZoneInfo

        brand_tz = ZoneInfo(tz_name)
    except Exception as tz_exc:
        logger.warning(
            "Unknown brand timezone %r (%s) — falling back to UTC", tz_name, tz_exc
        )
        brand_tz = timezone.utc
    # Store calendar items only up to the planning horizon (scope_weeks),
    # mirroring what generate_calendar_items emitted above. Items beyond the
    # horizon get skipped by store_calendar_items via max_date. Derived from
    # brand-local "now" so the horizon and purge windows line up with the
    # UTC-shifted rows store_calendar_items writes (and now.year below is the
    # brand-local year, not the UTC one, around New Year's Eve).
    now = datetime.now(brand_tz)
    scope_weeks = max(1, int(state.get("scope_weeks", 52) or 52))
    max_date = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(weeks=scope_weeks, days=1)  # +1 day cushion for end-of-window items
        - timedelta(seconds=1)
    )

    db_items = []
    skipped = 0
    for item in items:
        # Validate with Pydantic before DB insert
        try:
            validated = CalendarItemValidator(**item)
        except Exception as ve:
            logger.warning(
                "Skipping invalid calendar item: %s — %s", item.get("theme", ""), ve
            )
            skipped += 1
            continue
        # Combine scheduled_date + scheduled_time into a full datetime.
        # validated.scheduled_date is a string like "2026-01-01". Kept NAIVE
        # on purpose: these are brand-local wall times ("best times" from the
        # strategy) — store_calendar_items localizes them via tz_name and
        # converts to UTC. Stamping tzinfo=UTC here shifted every post by the
        # brand's UTC offset (20:00 local stored as 20:00 UTC = midnight MU).
        scheduled_time_str = item.get("scheduled_time", "")
        try:
            date_str = str(validated.scheduled_date)[:10]
            if scheduled_time_str:
                time_str = scheduled_time_str.strip()[:5]  # "18:00"
                scheduled_dt = datetime.strptime(
                    f"{date_str} {time_str}", "%Y-%m-%d %H:%M"
                )
            else:
                scheduled_dt = datetime.strptime(date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            # Fallback: use the raw string (store_calendar_items handles parsing)
            scheduled_dt = validated.scheduled_date

        db_items.append(
            {
                "brand_id": brand_id,
                "campaign_id": None,
                "title": validated.theme or validated.campaign_name or "",
                "description": validated.content_brief or item.get("brief", ""),
                "channel": validated.platform,
                "scheduled_at": scheduled_dt,
                "content_type": validated.content_type,
                "product_id": validated.product_id,
                "theme": validated.theme,
                "pillar": validated.pillar,
                "target_audience": validated.target_audience,
                "weekly_sub_theme": validated.weekly_sub_theme,
                "content_brief": validated.content_brief,
                "visual_direction": validated.visual_direction,
                "cta_type": validated.cta_type,
                "status": "planned",
            }
        )
    if skipped:
        logger.warning(
            "Skipped %d invalid calendar items for brand %s", skipped, brand_id
        )

    # Targeted re-plan: drop any stray item that landed outside the target
    # months (e.g. a 7-day batch window straddling a month boundary).
    if target_months:
        def _item_ym(it):
            sa = it.get("scheduled_at")
            if isinstance(sa, datetime):
                return (sa.year, sa.month)
            try:
                y, mo = str(sa)[:7].split("-")
                return (int(y), int(mo))
            except (ValueError, TypeError):
                return None
        db_items = [it for it in db_items if _item_ym(it) in target_months]

    # Deterministic post/reel layout (applied after month filtering so slot
    # indices are stable for the exact set of items being stored).
    _assign_item_types(db_items, state.get("content_format", "mixed"))

    # Purge stale 'planned' items so reruns don't stack duplicates. Non-'planned'
    # rows are preserved — once an item moves into generation or publishing the
    # user has effectively taken ownership. Targeted re-plan purges ONLY the
    # changed months; full re-plan purges the whole year-to-horizon window.
    try:
        if target_months:
            # Month boundaries in the BRAND timezone — stored rows are UTC
            # conversions of brand-local wall times, so a brand-local month
            # spills past the UTC month boundary by the brand's UTC offset.
            deleted = 0
            for (y, mo) in sorted(target_months):
                m_start = datetime(y, mo, 1, tzinfo=brand_tz)
                if mo == 12:
                    m_end = datetime(y + 1, 1, 1, tzinfo=brand_tz) - timedelta(seconds=1)
                else:
                    m_end = datetime(y, mo + 1, 1, tzinfo=brand_tz) - timedelta(seconds=1)
                deleted += await delete_planned_calendar_items(brand_id, m_start, m_end)
        else:
            planning_start = datetime(now.year, 1, 1, tzinfo=brand_tz)
            deleted = await delete_planned_calendar_items(
                brand_id, planning_start, max_date
            )
        if deleted:
            logger.info(
                "Purged %d stale planned calendar items for brand %s before insert",
                deleted,
                brand_id,
            )
    except Exception as exc:
        logger.warning(
            "Failed to purge stale planned items for brand %s (continuing): %s",
            brand_id,
            exc,
        )

    ids = await store_calendar_items(
        db_items, max_date=max_date, enabled_channels=enabled_channels, tz_name=tz_name
    )
    logger.info("Stored %d calendar items for brand %s", len(ids), brand_id)

    # Plain-English summary of the marketing plan (planning report) for
    # non-marketing readers (IT/finance). Best-effort, empty on failure.
    planning_summary_plain = await generate_executive_summary_plain(
        "planning",
        {
            "campaigns": state.get("campaigns", []),
            "calendar_items_count": len(ids),
            "enabled_channels": enabled_channels,
        },
    )

    # Persist year-long strategy document as an agent_run artifact
    if strategy_document:
        try:
            # Separate plain-English summary for the content-calendar report.
            calendar_summary_plain = await generate_executive_summary_plain(
                "content_calendar",
                {
                    "strategy_document": strategy_document[:8000],
                    "enabled_channels": enabled_channels,
                },
            )
            cc_run_id = await store_strategy(
                brand_id,
                {
                    "type": "content_calendar_strategy",
                    "strategy_document": strategy_document,
                    "enabled_channels": enabled_channels,
                    "executive_summary_plain": calendar_summary_plain,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                },
                agent_type="content_calendar",
            )
            logger.info("Stored year-long strategy document for brand %s", brand_id)

            # Notify brand owner that the Content Calendar Strategy is ready.
            # (The worker hook covers research/strategy/planning, but not
            # content_calendar — it's stored inline here, never traverses
            # complete_agent_run via the worker.)
            try:
                from shared.tools.database import create_notification, execute_query

                rows = await execute_query(
                    "SELECT name, created_by FROM brands WHERE id = :bid",
                    {"bid": brand_id},
                )
                if rows and rows[0].get("created_by"):
                    await create_notification(
                        user_id=str(rows[0]["created_by"]),
                        notification_type="context_ready",
                        title=(
                            f"Content Calendar Strategy ready — "
                            f"{rows[0].get('name') or 'your brand'}"
                        ),
                        body="Click to review and approve.",
                        reference_type="agent_run",
                        reference_id=str(cc_run_id) if cc_run_id else None,
                    )
            except Exception as notif_exc:
                logger.debug("content_calendar notification skipped: %s", notif_exc)
        except Exception:
            logger.exception("Failed to store strategy document for brand %s", brand_id)

    return {
        "status": "completed",
        "calendar_item_ids": ids,
        "executive_summary_plain": planning_summary_plain,
    }
