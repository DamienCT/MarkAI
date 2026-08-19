"""Suppliers never surface in anything a customer sees.

Hard user directive (2026-08-19): no supplier, vendor, wholesaler, purchasing
group, or sourcing partner is ever named in any post, image, video, caption,
tag, or overlay — for any company, any brand. The directive exists because it
was violated: a Naturespan post shipped to review reading "sourced through
ACCORD BIO" in every platform caption, with "ACCORD BIO" in the tag list, and
the brand's own onboarding data was the source — its proof points literally
instructed the model to cite the purchasing group.

Two leak paths, so two defences:

* PROMPT SIDE — supplier names are removed from brand context before any LLM
  sees it (:func:`scrub_brand_dict`). A model cannot leak a name it was never
  given. This is the load-bearing defence.
* OUTPUT SIDE — finished copy is scrubbed again (:func:`strip_supplier_mentions`,
  :func:`filter_tags`) because models occasionally know a distributor from
  pretraining, and because content generated before this module existed is
  still in review.

What counts as a supplier: every distinct ``products.vendor_name`` for the
brand, plus any names a human lists in ``brand_guidelines.suppliers_never_mention``
(that is where purchasing groups like ACCORD BIO live — they are nobody's
vendor_name, they only exist in brand prose).

What does NOT count: the brand printed on the featured product's own pack.
"Coteaux Nantais Apricot Jam" cannot be sold without saying Coteaux Nantais,
and the customer can read the jar. Callers pass the featured product's own
terms via ``keep`` (:func:`product_own_terms`) so a vendor that is also the
manufacturer on the pack (Moulin des Moines, Pranarom) survives exactly when
it is the product being shown, and never as a sourcing credit.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

# Injected into system prompts alongside ENGLISH_ONLY_RULE. Kept here so the
# wording cannot drift per-module.
SUPPLIER_SILENCE_RULE = (
    "SUPPLIERS — HARD RULE: never name, credit, or allude to any supplier, "
    "vendor, wholesaler, importer, purchasing group, or sourcing partner, in "
    "any output, for any brand. Products are presented as the brand's own "
    "offering. The brand printed on the product's own pack may be named — "
    "the customer can read it — but who the company buys from is "
    "confidential. If sourcing must be described, write 'carefully sourced' "
    "or 'our certified sourcing network', never a company name."
)

# Corporate suffixes that vary between the vendor record and prose usage:
# "Segafredo Zanetti S.P.A" must also match "Segafredo Zanetti".
_CORP_SUFFIX = re.compile(
    r"\s+(s\.?p\.?a\.?|s\.?a\.?(?:r\.?l\.?)?|s\.?a\.?s\.?|ltd\.?|ltee|ltée|"
    r"gmbh|inc\.?|co\.?|llc|plc|bv|nv)\s*$",
    re.IGNORECASE,
)

_WS = re.compile(r"\s+")

# The stand-in for a supplier name inside PROMPT context. Grammar survives
# most sentence shapes ("via the X purchasing group" → "via the our sourcing
# network purchasing group" would not, so the article is eaten too).
_CONTEXT_REPLACEMENT = "our sourcing network"

# vendor lists change on BC sync; a 10-minute cache keeps this to one query
# per brand per worker rather than one per node call.
_CACHE_TTL_S = 600.0
_cache: dict[str, tuple[float, list[str]]] = {}


def _canon(name: str) -> str:
    """Lowercase, suffix-free, space-collapsed form used for comparisons."""
    s = _WS.sub(" ", str(name or "").strip())
    s = _CORP_SUFFIX.sub("", s)
    return s.strip().lower()


def _squash(name: str) -> str:
    """Comparison form with everything but letters/digits removed.

    Hashtags arrive as "AccordBio"; the vendor record says "ACCORD BIO".
    Both squash to "accordbio".
    """
    return re.sub(r"[^a-z0-9]", "", _canon(name))


def config_supplier_names(brand_config: dict[str, Any] | None) -> list[str]:
    """Names a human listed under brand_guidelines.suppliers_never_mention."""
    from shared.brand_context import coerce_guidelines

    raw = coerce_guidelines(brand_config).get("suppliers_never_mention") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(n).strip() for n in raw if str(n).strip()]


async def supplier_terms_for_brand(
    brand_id: str, brand_config: dict[str, Any] | None = None
) -> list[str]:
    """Every name that must never surface for this brand, longest first.

    Union of the brand's distinct product vendor names and the configured
    list. Returns [] on any failure — a missing guard list must not take the
    content pipeline down; the prompt-side rule still applies.
    """
    now = time.monotonic()
    hit = _cache.get(str(brand_id))
    vendors: list[str] | None = None
    if hit and now - hit[0] < _CACHE_TTL_S:
        vendors = hit[1]
    if vendors is None:
        try:
            from shared.tools.database import execute_query

            rows = await execute_query(
                "SELECT DISTINCT vendor_name FROM products "
                "WHERE brand_id = :brand_id AND vendor_name IS NOT NULL "
                "AND vendor_name != ''",
                {"brand_id": str(brand_id)},
            )
            vendors = [str(r["vendor_name"]).strip() for r in rows if r.get("vendor_name")]
            _cache[str(brand_id)] = (now, vendors)
        except Exception:
            logger.warning("supplier list query failed for %s", brand_id, exc_info=True)
            vendors = hit[1] if hit else []

    merged: dict[str, str] = {}
    for name in [*vendors, *config_supplier_names(brand_config)]:
        canon = _canon(name)
        if len(canon) >= 3:  # one- and two-letter "names" would shred prose
            merged.setdefault(canon, name)
    return sorted(merged.values(), key=len, reverse=True)


def _term_pattern(term: str) -> re.Pattern:
    """Word-bounded, case-insensitive, suffix-tolerant match for one name."""
    core = re.escape(_canon(term)).replace(r"\ ", r"[\s\-]+")
    return re.compile(
        rf"\b{core}(\s+(s\.?p\.?a\.?|s\.?a\.?(?:r\.?l\.?)?|ltd\.?|gmbh|inc\.?))?\b",
        re.IGNORECASE,
    )


def product_own_terms(product_name: str) -> frozenset[str]:
    """The featured product's own brand — the one name that may be shown.

    BC item names lead with the manufacturer: "Coteaux Nantais, Apricot Jam,
    690g". That leading segment is on the pack in the photo; suppressing it
    would forbid naming the product being sold.
    """
    head = str(product_name or "").split(",")[0].strip()
    return frozenset({_canon(head)} if len(_canon(head)) >= 3 else ())


def pack_owner(product_name: str) -> str:
    """Who the pack artwork belongs to, derived from the item name itself.

    Replaces the old habit of passing ``products.vendor_name`` to the swap
    instruction — the vendor is who the company BUYS from (a supplier, often
    not the name on the pack at all), and supplier names do not belong in
    prompts.
    """
    return str(product_name or "").split(",")[0].strip()


def scrub_brand_dict(
    cfg: dict[str, Any] | None, terms: Iterable[str]
) -> dict[str, Any] | None:
    """Deep-copied brand config with supplier names neutralised in all prose.

    Runs over every string field, including nested guidelines (description,
    dos, donts, taglines, voice_style, tone_of_voice). Non-string values and
    structure are untouched; keys are never renamed.
    """
    patterns = [_term_pattern(t) for t in terms if _canon(t)]
    if cfg is None or not patterns:
        return cfg

    # The guard's own configuration must survive its own scrub — these keys
    # hold the supplier names ON PURPOSE and are never rendered into prompts.
    _self_keys = {"suppliers_never_mention", "sub_brand_voices", "vendor_logos"}

    def _clean(value: Any) -> Any:
        if isinstance(value, str):
            out = value
            for pat in patterns:
                # Eat a preceding article so "via the ACCORD BIO purchasing
                # group" reads "via our sourcing network purchasing group".
                out = re.sub(
                    rf"\b(the\s+)?{pat.pattern}",
                    _CONTEXT_REPLACEMENT,
                    out,
                    flags=re.IGNORECASE,
                )
            return out
        if isinstance(value, dict):
            return {
                k: (v if k in _self_keys else _clean(v)) for k, v in value.items()
            }
        if isinstance(value, list):
            return [_clean(v) for v in value]
        return value

    return _clean(cfg)


def strip_supplier_mentions(
    text: str, terms: Iterable[str], keep: Iterable[str] = ()
) -> tuple[str, list[str]]:
    """Remove supplier references from finished copy; return (clean, hits).

    Surgical by preference: inside an affected sentence the comma-delimited
    clause carrying the name is dropped first ("…certified products, sourced
    with ACCORD BIO." → "…certified products."); the whole sentence goes only
    when the remainder would be a stub. Blank result never happens — a text
    that is nothing but supplier mentions returns "" and the caller decides.
    """
    if not isinstance(text, str) or not text.strip():
        return text if isinstance(text, str) else "", []
    kept = {_canon(k) for k in keep}
    live = [(t, _term_pattern(t)) for t in terms if _canon(t) and _canon(t) not in kept]
    # Untouched text comes back byte-identical — paragraph breaks and spacing
    # survive unless a supplier actually appears.
    if not live or not any(pat.search(text) for _, pat in live):
        return text, []

    hits: list[str] = []

    def _clean_sentence(sentence: str) -> str | None:
        matched = [t for t, pat in live if pat.search(sentence)]
        if not matched:
            return sentence
        hits.extend(matched)
        # Drop only the clauses that carry a name.
        clauses = re.split(r"([,;:])", sentence)
        kept_parts: list[str] = []
        for part in clauses:
            if part in ",;:":
                kept_parts.append(part)
                continue
            if any(pat.search(part) for _, pat in live):
                # Remove the delimiter that introduced this clause.
                if kept_parts and kept_parts[-1] in ",;:":
                    kept_parts.pop()
                continue
            kept_parts.append(part)
        remainder = "".join(kept_parts).strip(" ,;:")
        if len(re.findall(r"\w+", remainder)) < 3:
            return None  # the sentence existed to credit the supplier
        if not re.search(r"[.!?]$", remainder):
            end = re.search(r"([.!?])\s*$", sentence)
            if end:
                remainder += end.group(1)
        return remainder

    out_lines: list[str] = []
    for line in text.split("\n"):
        if not any(pat.search(line) for _, pat in live):
            out_lines.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept_sentences = [s for s in map(_clean_sentence, sentences) if s]
        cleaned = re.sub(r"[ \t]{2,}", " ", " ".join(kept_sentences)).strip()
        out_lines.append(cleaned)

    clean = "\n".join(out_lines)
    # A line reduced to nothing collapses its blank; three+ newlines never.
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    # De-dup while keeping order, for the log line.
    seen: dict[str, None] = {}
    for h in hits:
        seen.setdefault(h, None)
    return clean, list(seen)


_TAG_LIST_KEYS = frozenset({"tags", "hashtags"})


def scrub_content_payload(
    payload: Any, terms: Iterable[str], keep: Iterable[str] = ()
) -> tuple[Any, list[str]]:
    """Deep scrub of a finished content structure (captions, platform dicts).

    Strings go through :func:`strip_supplier_mentions`; lists under tag-ish
    keys go through :func:`filter_tags` (whole entry dropped); other lists and
    dicts recurse. Returns (scrubbed, hits) where hits is every supplier name
    or dropped tag encountered, for the log line.
    """
    terms = list(terms)
    keep = list(keep)
    hits: list[str] = []

    def _walk(value: Any, key: str = "") -> Any:
        if isinstance(value, str):
            clean, found = strip_supplier_mentions(value, terms, keep=keep)
            hits.extend(found)
            return clean
        if isinstance(value, dict):
            return {k: _walk(v, str(k)) for k, v in value.items()}
        if isinstance(value, list):
            if key.lower() in _TAG_LIST_KEYS and all(
                isinstance(v, str) for v in value
            ):
                kept_tags, dropped = filter_tags(value, terms, keep=keep)
                hits.extend(dropped)
                return kept_tags
            return [_walk(v, key) for v in value]
        return value

    out = _walk(payload)
    seen: dict[str, None] = {}
    for h in hits:
        seen.setdefault(h, None)
    return out, list(seen)


def filter_tags(
    tags: Iterable[str], terms: Iterable[str], keep: Iterable[str] = ()
) -> tuple[list[str], list[str]]:
    """Tag/hashtag lists with supplier-bearing entries removed entirely.

    Matching is squashed ("AccordBio" ~ "ACCORD BIO") because hashtags carry
    no word boundaries. A tag is never rewritten — a hashtag minus its brand
    is noise — it is dropped.
    """
    kept_terms = {_squash(k) for k in keep}
    live = [
        _squash(t) for t in terms if _squash(t) and _squash(t) not in kept_terms
    ]
    if not live:
        return [str(t) for t in tags], []
    out: list[str] = []
    dropped: list[str] = []
    for tag in tags:
        squashed = _squash(str(tag))
        if any(term in squashed for term in live):
            dropped.append(str(tag))
        else:
            out.append(str(tag))
    return out, dropped
