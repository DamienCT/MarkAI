"""Deterministic editorial guards for generated calendar and content copy.

Pure, side-effect-free helpers shared by the planning and content workflows.
A per-item prompt cannot see the other 623 items of a year plan, so three
failure modes only surface at scale — and only a deterministic pass over the
whole run reliably catches them:

1. **Stale anticipation** — an item scheduled AFTER an event still frames it
   as upcoming ("the upcoming magasin bio", "countdown", "J-7"). The claim is
   false on the day it publishes. 19 of 624 items in the first production
   calendar were wrong this way.
2. **Repetition** — one statistic ("+69% antioxidants") recycled 28x across a
   year, the same six proof points mandated daily, 18 theme titles spread
   over 350 items.
3. **Meta-language in briefs** — ``content_brief`` written as commentary
   *about* a post ("This post should…", "Focus on…") instead of the creative
   direction a writer can act on. 106 of 624 briefs leaked it.

Nothing here drops an item or fails a run: the temporal guard rewrites and
warns, the repetition check only measures. Deterministic on purpose, so the
upgrade/QA loop can compare the same numbers cycle over cycle.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

# ── Text normalization (matching only — never used to rewrite copy) ───

# Articles/connectors carry no event identity. EN + FR: event titles and item
# copy are both mixed-language in practice (Mauritian brands).
_STOPWORDS = frozenset({
    "a", "an", "and", "or", "of", "for", "with", "in", "on", "to", "the",
    "at", "by", "from", "is", "it", "its", "our", "your", "this", "that",
    "de", "la", "le", "les", "du", "des", "et", "en", "au", "aux", "un",
    "une", "sur", "pour", "avec", "nos", "notre",
})


def _fold(value: Any) -> str:
    """Lowercase, strip accents, turn punctuation into spaces.

    Used ONLY for token comparison. Rewrites always operate on the original
    string so accents (re-added to the brand guidelines in cycle 2) survive.
    """
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = stripped.lower()
    return "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in lowered)


def _tokens(value: Any) -> set[str]:
    """Identity-carrying tokens of a string (folded, stopwords removed)."""
    return {t for t in _fold(value).split() if len(t) > 1 and t not in _STOPWORDS}


def _as_date(value: Any) -> Optional[date]:
    """Best-effort date from a date, datetime, or ``YYYY-MM-DD...`` string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _tidy(text: str) -> str:
    """Repair spacing/punctuation left behind after a phrase is removed."""
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\s+([,.;:!?%…])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)
    text = re.sub(r"([,;:])\s*([,.;:])", r"\2", text)
    text = re.sub(r"\n[^\S\n]*\n[^\S\n]*\n+", "\n\n", text)
    text = re.sub(r"^[\s\-–—:,;]+", "", text)
    text = re.sub(r"[\s\-–—:,;]+$", "", text)
    return text.strip()


def _capitalize_first(text: str) -> str:
    """Upper-case the first alphabetic character, leaving the rest alone."""
    for idx, ch in enumerate(text):
        if ch.isalpha():
            return text[:idx] + ch.upper() + text[idx + 1:]
    return text


def _match_leading_case(original: str, rewritten: str) -> str:
    """Restore the original's leading capital after a lowercase substitution."""
    lead = next((ch for ch in original if ch.isalpha()), "")
    if not lead.isupper():
        return rewritten
    return _capitalize_first(rewritten)


# ── 1. Temporal guard: anticipatory language about a past event ───────

# (label, pattern, replacement). ORDER MATTERS: the most specific phrasing
# must fire before the bare keyword, so "countdown to X" becomes
# "celebrating X" rather than "celebration to X". Replacements are chosen to
# read as post-event copy — the guard de-anticipates, it never deletes the
# item (a dropped item leaves a hole in the published cadence).
_ANTICIPATORY_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # "J-7", "J - 3" — the French countdown shorthand the LLM likes.
    ("j-countdown", re.compile(r"\bj\s*[-–—−]\s*\d+\b", re.I), ""),
    ("countdown", re.compile(
        r"\bcountdowns?\s+(?:to|until|till|towards?)\b", re.I), "celebrating"),
    ("countdown", re.compile(
        r"\bcomptes?\s+[àa]\s+rebours\b", re.I), "celebration"),
    ("countdown", re.compile(r"\bcountdowns?\b", re.I), "celebration"),
    ("upcoming", re.compile(r"\b(the|our|this|a)\s+upcoming\b", re.I), r"\1"),
    ("upcoming", re.compile(r"\bupcoming\b", re.I), ""),
    ("opening soon", re.compile(r"\bopening\s+soon\b", re.I), "now open"),
    ("opening soon", re.compile(r"\bsoon\s+to\s+open\b", re.I), "now open"),
    ("opening soon", re.compile(r"\bopens\s+soon\b", re.I), "is open now"),
    ("opening soon", re.compile(r"\bwill\s+(?:soon\s+)?open\b", re.I), "is open"),
    ("coming soon", re.compile(
        r"\b(?:coming|arriving|launching|landing)\s+soon\b", re.I), "now here"),
    ("coming soon", re.compile(r"\bprochainement\b", re.I), ""),
    ("coming soon", re.compile(r"\bbient[ôo]t\b", re.I), "maintenant"),
    ("coming soon", re.compile(r"\b[àa]\s+venir\b", re.I), ""),
    ("get ready for", re.compile(
        r"\b(?:get|gear)\s+ready\s+for\b", re.I), "enjoy"),
    ("get ready", re.compile(r"\b(?:get|gear)\s+ready\b", re.I), ""),
    ("build anticipation", re.compile(
        r"\bbuild(?:ing|s)?\s+(?:up\s+|the\s+)?anticipation\b", re.I),
        "celebrate the moment"),
    ("anticipation", re.compile(r"\banticipation\b", re.I), "excitement"),
    ("days to go", re.compile(
        r"\b\d+\s+(?:more\s+)?days?\s+(?:to\s+go|left|until|before|away)\b",
        re.I), ""),
    ("save the date", re.compile(
        r"\bsave\s+the\s+dates?\b", re.I), "mark the moment"),
    ("almost here", re.compile(r"\balmost\s+here\b", re.I), "here"),
)

# Item fields the temporal scrub rewrites. ``campaign_name`` is deliberately
# NOT rewritten — it is the grouping key across many items, and rewriting it
# per-item would split one campaign into several. It still counts as evidence
# when deciding which event an item refers to.
ANTICIPATORY_SCRUB_FIELDS: tuple[str, ...] = (
    "theme",
    "title",
    "weekly_sub_theme",
    "content_brief",
    "description",
    "visual_direction",
)
_EVENT_EVIDENCE_FIELDS: tuple[str, ...] = ANTICIPATORY_SCRUB_FIELDS + (
    "campaign_name",
    "pillar",
)


def find_anticipatory_markers(text: Any) -> list[str]:
    """Anticipatory/countdown markers present in ``text``.

    Returns de-duplicated labels in rule order. Presence alone is NOT a
    defect: anticipation is correct while the event is still ahead. Pair with
    :func:`find_stale_anticipation` to judge it against a scheduled date.
    """
    hay = str(text or "")
    if not hay.strip():
        return []
    found: list[str] = []
    for label, pattern, _repl in _ANTICIPATORY_RULES:
        if label not in found and pattern.search(hay):
            found.append(label)
    return found


def scrub_anticipatory_language(text: Any) -> tuple[str, list[str]]:
    """Rewrite anticipatory phrasing into post-event phrasing.

    Returns ``(rewritten, markers)``. ``markers`` is empty and the string is
    returned untouched when nothing matched. If the rewrite would leave the
    field empty the original is kept — a blank title is worse than a stale one
    and the caller still gets the markers to log.
    """
    original = str(text or "")
    if not original.strip():
        return original, []
    out = original
    found: list[str] = []
    for label, pattern, repl in _ANTICIPATORY_RULES:
        out, hits = pattern.subn(repl, out)
        if hits and label not in found:
            found.append(label)
    if not found:
        return original, []
    out = _tidy(out)
    if not out.strip():
        return original, found
    return _match_leading_case(original, out), found


def build_event_index(
    events: Optional[Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    """Precompute per-event matching tokens, distinctive tokens, and date.

    An event is identified in free text by its title tokens, widened with the
    opening of its description — the production defect said "the upcoming
    magasin bio" and never named the event's title, so title-only matching
    would have missed it entirely.

    Widening alone would over-match ("day", "week", "national", "opening"
    recur across a whole holiday calendar), so each event also gets a
    *distinctive* subset: tokens that occur in at most ``max(1, n // 10)`` of
    the events. A match must include at least one of those.
    """
    entries: list[dict[str, Any]] = []
    for ev in events or []:
        if not isinstance(ev, Mapping):
            continue
        title_tokens = _tokens(ev.get("title"))
        tokens = title_tokens | _tokens(str(ev.get("description") or "")[:200])
        if not tokens:
            continue
        entries.append({
            "event": ev,
            "title": str(ev.get("title") or ""),
            "title_tokens": title_tokens or tokens,
            "tokens": tokens,
            "date": _as_date(ev.get("end")) or _as_date(ev.get("start")),
        })
    df: Counter[str] = Counter()
    for entry in entries:
        df.update(entry["tokens"])
    threshold = max(1, len(entries) // 10)
    for entry in entries:
        entry["distinctive"] = {t for t in entry["tokens"] if df[t] <= threshold}
    return entries


def _event_hits(entry: Mapping[str, Any], hay: set[str]) -> set[str]:
    """Tokens shared by one indexed event and a bag of text tokens.

    Empty when the overlap is too weak to bind the event. Two conditions:
    at least one *distinctive* token must be shared (a lone "day"/"week"/
    "opening" identifies nothing), and the number of shared tokens must reach
    the event's own title length capped at two. Keying the bar to the TITLE
    rather than to the title+description union matters: a one-word event
    ("Diwali") would otherwise become harder to match the moment someone
    wrote it a description.
    """
    hits = entry["tokens"] & hay
    if not hits or not (hits & entry["distinctive"]):
        return set()
    if len(hits) < min(2, len(entry["title_tokens"])):
        return set()
    return hits


def find_referenced_events(
    text: Any,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    index: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[Mapping[str, Any]]:
    """Events that ``text`` appears to talk about."""
    entries = list(index) if index is not None else build_event_index(events)
    hay = _tokens(text)
    if not hay or not entries:
        return []
    return [entry["event"] for entry in entries if _event_hits(entry, hay)]


def find_stale_anticipation(
    text: Any,
    scheduled_date: Any,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    index: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Anticipatory phrasing about an event that already happened.

    Returns one record per referenced event whose date is strictly before
    ``scheduled_date``. Empty when the text has no anticipatory marker, when
    no listed event is referenced, when the date is unparseable, or when every
    referenced event is still ahead on that date (anticipation is then true).

    Date-range events are judged on their END date, so an item inside a
    declared countdown week keeps its countdown framing.
    """
    markers = find_anticipatory_markers(text)
    if not markers:
        return []
    when = _as_date(scheduled_date)
    if when is None:
        return []
    entries = list(index) if index is not None else build_event_index(events)
    hay = _tokens(text)
    stale: list[dict[str, Any]] = []
    for entry in entries:
        if not _event_hits(entry, hay):
            continue
        ev_date = entry["date"]
        if ev_date is None or when <= ev_date:
            continue
        stale.append({
            "event": entry["title"],
            "event_date": ev_date.isoformat(),
            "scheduled_date": when.isoformat(),
            "markers": markers,
        })
    return stale


def _item_text(item: Mapping[str, Any], fields: Iterable[str]) -> str:
    return "\n".join(str(item.get(f) or "") for f in fields)


def _future_events_in(
    value: Any, entries: Sequence[Mapping[str, Any]], when: date
) -> list[str]:
    """Titles of indexed events THIS field references that are still ahead.

    "Ahead" matches :func:`find_stale_anticipation`: an event on the item's own
    scheduled date is not past, so anticipation about it is still defensible.
    """
    hay = _tokens(value)
    if not hay:
        return []
    ahead: list[str] = []
    for entry in entries:
        ev_date = entry["date"]
        if ev_date is None or ev_date < when:
            continue
        if _event_hits(entry, hay):
            ahead.append(entry["title"])
    return ahead


def deanticipate_item(
    item: dict[str, Any],
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    index: Optional[Sequence[Mapping[str, Any]]] = None,
    date_keys: Sequence[str] = ("scheduled_date", "scheduled_at"),
) -> Optional[dict[str, Any]]:
    """De-anticipate one calendar item in place.

    Returns a finding dict when the item asserted something false for its own
    publish date, else ``None``. The item is rewritten, never dropped.

    The stale/not-stale decision is made on the item's combined evidence
    (``campaign_name`` included — it is often the only place the event is
    named), but the REWRITE is decided per field. Campaign names in this
    codebase are routinely event-named, so an item under "Curepipe Opening
    follow-up" whose theme is "Countdown to Mauritius Independence Day" would
    otherwise have its still-true countdown rewritten because a *different*,
    already-past event was referenced elsewhere on the item. A field that
    names an event still ahead on publish day is left alone and reported in
    ``fields_kept``.
    """
    scheduled = next(
        (item.get(k) for k in date_keys if item.get(k) is not None), None
    )
    entries = list(index) if index is not None else build_event_index(events)
    evidence = _item_text(item, _EVENT_EVIDENCE_FIELDS)
    stale = find_stale_anticipation(evidence, scheduled, index=entries)
    if not stale:
        return None
    when = _as_date(scheduled)  # non-None: find_stale_anticipation matched

    changed: list[str] = []
    kept: list[str] = []
    markers: list[str] = []
    for field in ANTICIPATORY_SCRUB_FIELDS:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        ahead = _future_events_in(value, entries, when)
        if ahead:
            # This field's anticipation is TRUE on publish day — rewriting it
            # would turn correct copy into incorrect copy.
            kept.append(field)
            continue
        rewritten, found = scrub_anticipatory_language(value)
        for label in found:
            if label not in markers:
                markers.append(label)
        if rewritten != value:
            item[field] = rewritten
            changed.append(field)

    return {
        "scheduled_date": stale[0]["scheduled_date"],
        "title": str(item.get("theme") or item.get("title") or "")[:120],
        "events": [s["event"] for s in stale],
        "event_dates": [s["event_date"] for s in stale],
        "markers": markers or stale[0]["markers"],
        "fields_rewritten": changed,
        "fields_kept": kept,
    }


def apply_temporal_guard(
    items: Sequence[dict[str, Any]],
    events: Optional[Sequence[Mapping[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Run :func:`deanticipate_item` over a whole generated calendar."""
    index = build_event_index(events)
    if not index:
        return []
    findings: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        finding = deanticipate_item(item, index=index)
        if finding:
            findings.append(finding)
    return findings


# ── 2. Repetition damping ────────────────────────────────────────────

# Statistic shapes worth policing. Mass/volume units (500g, 250ml) are
# deliberately excluded: they are product pack sizes, not claims, and they
# would swamp the signal we actually care about ("+69%", "3x more", "20+
# years") in every report.
_STAT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[+\-−]?\s*\d+(?:[.,]\d+)?\s*%"),
    re.compile(r"\b\d+(?:[.,]\d+)?\s*x\b", re.I),
    re.compile(
        r"\b\d+(?:[.,]\d+)?\s+times?\s+"
        r"(?:more|less|higher|lower|faster|stronger|richer|longer)\b", re.I),
    re.compile(r"\b\d+\s*\+?\s*(?:years?|ans)\b", re.I),
)

# Fields whose copy is scanned for repeated statistics.
STAT_SCAN_FIELDS: tuple[str, ...] = (
    "theme",
    "title",
    "weekly_sub_theme",
    "content_brief",
    "description",
)


def normalize_stat(raw: Any) -> str:
    """Canonical form of a statistic so "+69 %" and "69%" count as one."""
    text = str(raw or "").strip().lower()
    text = text.replace("−", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = re.sub(r"\s*([%x+])\s*", r"\1", text)
    text = text.lstrip("+").strip()
    return text


def extract_stats(text: Any) -> list[str]:
    """Normalized statistics mentioned in ``text`` (order preserved)."""
    hay = str(text or "")
    if not hay.strip():
        return []
    out: list[str] = []
    for pattern in _STAT_PATTERNS:
        for match in pattern.finditer(hay):
            stat = normalize_stat(match.group(0))
            if stat and stat not in out:
                out.append(stat)
    return out


def item_title(item: Mapping[str, Any]) -> str:
    """The headline a calendar item is stored under (see store_calendar)."""
    for key in ("theme", "title", "campaign_name"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def item_stats(
    item: Mapping[str, Any], fields: Sequence[str] = STAT_SCAN_FIELDS
) -> list[str]:
    """Normalized statistics quoted anywhere in one calendar item."""
    return extract_stats(_item_text(item, fields))


def dedupe_recent(values: Iterable[Any], cap: int) -> list[str]:
    """Last ``cap`` distinct non-empty values, most recent occurrence wins."""
    seen: dict[str, None] = {}
    for value in values:
        text = " ".join(str(value or "").split())
        if not text:
            continue
        seen.pop(text, None)
        seen[text] = None
    return list(seen)[-cap:] if cap > 0 else []


def build_recent_usage_block(
    titles: Sequence[str],
    stats: Sequence[str],
    *,
    channel: str = "",
    max_titles: int = 40,
    max_stats: int = 15,
) -> str:
    """Prompt block listing what earlier batches of this run already used.

    Empty string on the first wave (nothing generated yet) so the prompt does
    not carry a dangling "(none)" section.
    """
    recent_titles = dedupe_recent(titles, max_titles)
    recent_stats = dedupe_recent(stats, max_stats)
    if not recent_titles and not recent_stats:
        return ""
    label = f" ON {channel.upper()}" if channel else ""
    lines = [
        f"ALREADY USED EARLIER IN THIS PLAN{label} — do NOT reuse or re-word:"
    ]
    if recent_titles:
        lines.append("Titles/angles already taken:")
        lines.extend(f"- {t}" for t in recent_titles)
    if recent_stats:
        lines.append(
            "Statistics/proof points already used (pick DIFFERENT verified "
            "facts this week):"
        )
        lines.extend(f"- {s}" for s in recent_stats)
    return "\n".join(lines) + "\n\n"


def stat_window_violations(
    items: Sequence[Mapping[str, Any]],
    *,
    window_days: int = 28,
    max_per_window: int = 1,
    date_keys: Sequence[str] = ("scheduled_date", "scheduled_at"),
) -> list[dict[str, Any]]:
    """Statistics used more than ``max_per_window`` times in a rolling window.

    Mirrors the prompt rule ("any single statistic at most once per rolling
    4-week window") so the QA loop can measure whether the rule is landing.
    Reports the worst window per statistic, worst first. Log-only.
    """
    by_stat: dict[str, list[date]] = {}
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        when = next(
            (_as_date(item.get(k)) for k in date_keys if item.get(k) is not None),
            None,
        )
        if when is None:
            continue
        for stat in item_stats(item):
            by_stat.setdefault(stat, []).append(when)

    violations: list[dict[str, Any]] = []
    for stat, dates in by_stat.items():
        dates.sort()
        best_count, best_start, best_dates = 0, None, []
        left = 0
        for right in range(len(dates)):
            while (dates[right] - dates[left]).days >= window_days:
                left += 1
            count = right - left + 1
            if count > best_count:
                best_count = count
                best_start = dates[left]
                best_dates = dates[left:right + 1]
        if best_count > max_per_window and best_start is not None:
            violations.append({
                "stat": stat,
                "count": best_count,
                "window_start": best_start.isoformat(),
                "total": len(dates),
                "dates": [d.isoformat() for d in best_dates],
            })
    violations.sort(key=lambda v: (-v["count"], -v["total"], v["stat"]))
    return violations


def repetition_report(
    items: Sequence[Mapping[str, Any]],
    *,
    top_n: int = 10,
    window_days: int = 28,
    max_per_window: int = 1,
) -> dict[str, Any]:
    """Measure title/statistic repetition across one planning run.

    Pure and log-only — it never mutates or rejects items. The numbers are the
    QA loop's yardstick: 18 titles over 350 items and one stat 28x/year is the
    baseline this cycle is trying to move.
    """
    titles = [item_title(i) for i in items or [] if isinstance(i, Mapping)]
    titles = [t for t in titles if t]
    title_counts = Counter(" ".join(t.split()).lower() for t in titles)
    canonical: dict[str, str] = {}
    for title in titles:
        canonical.setdefault(" ".join(title.split()).lower(), title)

    stat_counts: Counter[str] = Counter()
    for item in items or []:
        if isinstance(item, Mapping):
            stat_counts.update(item_stats(item))

    return {
        "items": len([i for i in items or [] if isinstance(i, Mapping)]),
        "titles": len(titles),
        "unique_titles": len(title_counts),
        "top_titles": [
            {"title": canonical.get(key, key), "count": count}
            for key, count in title_counts.most_common(top_n)
            if count > 1
        ],
        "unique_stats": len(stat_counts),
        "top_stats": [
            {"stat": stat, "count": count}
            for stat, count in stat_counts.most_common(top_n)
            if count > 1
        ],
        "stat_window_violations": stat_window_violations(
            items,
            window_days=window_days,
            max_per_window=max_per_window,
        )[:top_n],
    }


def format_repetition_report(report: Mapping[str, Any]) -> str:
    """One-line human-readable digest of :func:`repetition_report`."""
    top_titles = ", ".join(
        f"{t['title'][:48]!r}x{t['count']}" for t in report.get("top_titles", [])[:5]
    ) or "none"
    top_stats = ", ".join(
        f"{s['stat']}x{s['count']}" for s in report.get("top_stats", [])[:5]
    ) or "none"
    violations = ", ".join(
        f"{v['stat']}x{v['count']}@{v['window_start']}"
        for v in report.get("stat_window_violations", [])[:5]
    ) or "none"
    return (
        f"items={report.get('items', 0)} "
        f"unique_titles={report.get('unique_titles', 0)}/{report.get('titles', 0)} "
        f"unique_stats={report.get('unique_stats', 0)} | "
        f"repeated_titles: {top_titles} | repeated_stats: {top_stats} | "
        f"4w_window_violations: {violations}"
    )


# ── 3. Brief hygiene ─────────────────────────────────────────────────

# Leading phrases that turn a creative direction into commentary ABOUT a
# post. Anchored at the start of a sentence only: "focuses on" mid-sentence
# is ordinary prose, "Focus on ..." opening a brief is generator meta-talk.
_BRIEF_META_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("goal-of-this-post", re.compile(
        r"^(?:the\s+)?(?:goal|objective|aim|purpose|idea|angle)\s+"
        r"(?:of\s+this\s+\w+\s+|here\s+)?is\s+to\s+", re.I)),
    ("this-post-should", re.compile(
        r"^this\s+(?:post|caption|item|piece|reel|carousel|story|video|"
        r"content|copy)\s+(?:should|will|must|needs?\s+to|has\s+to|"
        r"is\s+(?:meant|designed|intended)\s+to|aims?\s+to)\s+", re.I)),
    ("this-post-explains", re.compile(
        r"^this\s+(?:post|caption|item|piece|reel|carousel|story|video|"
        r"content|copy)\s+(?:explains?|describes?|highlights?|showcases?|"
        r"shows?|tells?|covers?|features?|focuses\s+on|celebrates?)\s+"
        r"(?:how|that|why|what|the\s+way)?\s*", re.I)),
    ("the-caption-explains", re.compile(
        r"^the\s+(?:caption|copy|post|text|brief|content)\s+"
        r"(?:should|will|must|explains?|describes?|highlights?|showcases?|"
        r"shows?|tells?)\s+(?:how|that|why|what)?\s*", re.I)),
    ("we-should", re.compile(
        r"^(?:we|you)\s+(?:should|will|want\s+to|need\s+to|are\s+going\s+to)\s+",
        re.I)),
    ("focus-on", re.compile(r"^focus(?:es|ing)?\s+on\s+", re.I)),
    ("in-this-post", re.compile(
        r"^in\s+this\s+(?:post|caption|piece|reel|video|content)\s*,?\s*", re.I)),
    ("use-this-post-to", re.compile(
        r"^use\s+this\s+(?:post|item|caption|reel)\s+to\s+", re.I)),
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def find_brief_meta_phrases(text: Any) -> list[str]:
    """Labels of generator meta-language opening any sentence of ``text``."""
    hay = str(text or "").strip()
    if not hay:
        return []
    found: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(hay):
        remainder = sentence.lstrip()
        for _ in range(3):
            for label, pattern in _BRIEF_META_RULES:
                stripped = pattern.sub("", remainder, count=1)
                if stripped != remainder:
                    if label not in found:
                        found.append(label)
                    remainder = stripped.lstrip()
                    break
            else:
                break
    return found


def scrub_brief_meta(text: Any) -> str:
    """Strip generator meta-language from the front of each brief sentence.

    "This post should highlight the antioxidant content." becomes "Highlight
    the antioxidant content." — the substance survives, the commentary about
    a post does not. Returns the original when the scrub would empty the
    brief (an empty brief makes the content workflow refuse the item).
    """
    original = str(text or "")
    if not original.strip():
        return original

    rebuilt: list[str] = []
    changed = False
    for sentence in _SENTENCE_SPLIT.split(original):
        remainder = sentence.strip()
        if not remainder:
            continue
        for _ in range(3):
            for _label, pattern in _BRIEF_META_RULES:
                stripped = pattern.sub("", remainder, count=1)
                if stripped != remainder:
                    remainder = stripped.lstrip()
                    changed = True
                    break
            else:
                break
        remainder = remainder.strip()
        if remainder:
            rebuilt.append(_capitalize_first(remainder))

    if not changed:
        return original
    out = _tidy(" ".join(rebuilt))
    return out if out.strip() else original


def scrub_brief_fields(
    item: dict[str, Any], fields: Sequence[str] = ("content_brief", "description")
) -> list[str]:
    """Apply :func:`scrub_brief_meta` in place; return the fields it changed."""
    changed: list[str] = []
    for field in fields:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        cleaned = scrub_brief_meta(value)
        if cleaned != value:
            item[field] = cleaned
            changed.append(field)
    return changed


# ── Prompt blocks (shared wording, so planning and content can't drift) ──

TEMPORAL_RULES_BLOCK = (
    "TEMPORAL RULES (an item is published ON its scheduled_date — write from "
    "that day's standpoint, not from today):\n"
    "- NEVER use anticipatory or countdown framing about an event whose date "
    "is BEFORE the item's own scheduled_date. Words like 'countdown', "
    "'upcoming', 'coming soon', 'J-7', 'opening soon', 'get ready for', "
    "'save the date', 'build anticipation' are valid ONLY while the event is "
    "still in the future on that item's scheduled_date.\n"
    "- Calling a store that already opened 'the upcoming shop' is FALSE on "
    "the day it publishes. This is the single worst failure mode of this "
    "generator — 19 items shipped that way in the last plan.\n"
    "- On the event date write in the present ('we open today', 'now open'); "
    "after it write in the present or past ('our first week', 'since we "
    "opened'); for the same date in a later year use anniversary framing, "
    "never countdown framing.\n\n"
)

VARIETY_RULES_BLOCK = (
    "VARIETY RULES (this plan spans a whole year — repetition is the top "
    "reader complaint):\n"
    "- Do NOT reuse any title/theme listed as already used, and do not "
    "re-word one into a near-duplicate.\n"
    "- Any single statistic or proof point (e.g. '+69% antioxidants') may "
    "appear AT MOST ONCE in any rolling 4-week window. If it is already "
    "listed as used, choose a different verified fact this week.\n"
    "- Do not lead two consecutive weeks with the same proof point; rotate "
    "the angle (origin story, supplier, usage, seasonality, certification).\n\n"
)

BRIEF_STYLE_BLOCK = (
    "CONTENT BRIEF STYLE:\n"
    "- content_brief is CREATIVE DIRECTION for the writer, not commentary "
    "ABOUT a post. Write the substance: the specific angle, the concrete "
    "detail, the one fact to land.\n"
    "- NEVER open with generator meta-language: 'This post should...', 'The "
    "caption explains how...', 'Focus on...', 'The goal of this post is...', "
    "'In this post...', 'We will...'. Start with the subject itself.\n"
    "- Bad: 'This post should highlight the antioxidant content of the "
    "moringa powder.' Good: 'Moringa leaf powder keeps more antioxidants "
    "than the fresh leaf — show the scoop against a dark bowl and name the "
    "number once.'\n\n"
)


def build_temporal_block(
    scheduled_date: Any,
    events: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    max_events: int = 12,
) -> str:
    """Per-item temporal context: what is past vs future on publish day.

    Used by the content workflow, where each run writes exactly one post and
    the whole-calendar guard does not apply. Empty string when the date or
    the events list is unusable, so callers can concatenate unconditionally.
    """
    when = _as_date(scheduled_date)
    if when is None or not events:
        return ""
    past: list[str] = []
    future: list[str] = []
    for ev in events:
        if not isinstance(ev, Mapping):
            continue
        title = str(ev.get("title") or "").strip()
        ev_date = _as_date(ev.get("end")) or _as_date(ev.get("start"))
        if not title or ev_date is None:
            continue
        line = f"- {ev_date.isoformat()}: {title}"
        (past if ev_date < when else future).append(line)
    if not past and not future:
        return ""
    lines = [
        f"TEMPORAL CONTEXT — this post publishes on {when.isoformat()}. "
        "Write from that day, not from today."
    ]
    if past:
        lines.append(
            "Already happened by then (speak in the present or past tense — "
            "NEVER 'upcoming', 'coming soon', 'countdown', 'get ready for'):"
        )
        lines.extend(past[-max_events:])
    if future:
        lines.append("Still ahead on that day (anticipation is allowed):")
        lines.extend(future[:max_events])
    return "\n".join(lines) + "\n\n"
