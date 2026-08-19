"""Catch non-English copy that the ENGLISH_ONLY_RULE prompt let through.

The rule in :mod:`shared.brand_context` is injected into every prompt that
produces user-facing text, and it mostly holds. It failed on 2026-08-18: a
Naturespan plan shipped five items whose titles read "Du bio vérifiable,
enfin", "J-1: du bio vérifié", "Back to School (Rentrée 2027)". One of them
reached the renderer and would have burned French captions into a reel.

The rule's own escape hatch caused it. It permitted foreign phrases "as proper
nouns (e.g. 'magasin bio')", and the model generalised that licence from names
to ordinary nouns — goûter, rentrée, produits certifiés — and from there to
whole titles. Prompt wording is now tighter, but a directive that has failed
once needs something deterministic behind it, so this module measures the
output instead of asking again.

Detection is deliberately French-weighted. Every brand in this system sells in
Mauritius, so French is the language that leaks; a general language classifier
would cost a dependency and a model load to catch a failure mode with a
seventy-word vocabulary.

Two rules, both needed:

* a marker word — a French word with no English homograph. "pour", "son",
  "pain", "chat", "coin", "car", "or", "sale" and "the" are deliberately NOT
  markers: they are ordinary English words and would flag half the catalogue.
* an accented letter outside the loanword allowlist. English has naturalised
  café, cliché, résumé and a handful of others; "vérifiable" it has not.

Names are removed before either rule runs. "Moulin des Moines" and "Autour du
Riz" are supplier brands that must survive — they are what the copy is FOR —
so callers pass the names they know about and the guard scores what is left.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

# French words with no English homograph. Anything ambiguous is left out on
# purpose — a false positive here means a QA warning against clean English
# copy, which trains the reader to ignore the warning.
_MARKERS = frozenset(
    """
    du des une aux nos vos votre notre avec sans chez dans cette ces
    leur leurs très déjà enfin ainsi aussi toujours jamais plutôt
    quelques chaque autour moins mieux depuis selon
    vous nous ils elles sont êtes avez avons soyez
    rendez demain matin soir semaine mois année années maintenant
    bientôt prochain prochaine toutes
    magasin goûter gouter rentrée rentree épicerie epicerie boulangerie
    marché marche santé sante beauté beaute famille enfants maison
    quotidien savoureux naturel naturelle nouvelle
    livraison gratuit offre ouvre ouverture meilleur meilleure
    produits certifié certifiée certifiés certifiées
    vérifié vérifiée vérifiés vérifiable verifie
    bienvenue découvrir decouvrir profitez retrouvez
    """.split()
)

# Words that LOOK French and are ordinary English. Listing them is not
# decorative: an earlier revision had "cuisine", "boutique", "gourmand",
# "pendant", "certifies" and "verifiable" as markers, which flags a food and
# retail brand's clean English copy several times a week. A guard nobody
# trusts is a guard nobody reads, so accented French keeps these words'
# accented forms as markers while the bare spellings stay out.
_ENGLISH_LOOKALIKES = frozenset(
    "cuisine boutique gourmand pendant certifies verifiable ensemble tout "
    "tous pour son pain chat coin car sale ton".split()
)
assert not (_MARKERS & _ENGLISH_LOOKALIKES), "a marker is an ordinary English word"

# Contractions are a strong signal and survive tokenisation badly, so they are
# matched as substrings rather than as words.
_CONTRACTIONS = ("c'est", "n'est", "qu'il", "qu'elle", "d'un", "d'une", "aujourd'hui")

# Accented spellings English has naturalised. Compared without their accents so
# "cafe" and "café" are one entry.
_LOANWORDS = frozenset(
    """
    cafe cafes cliche cliches resume resumes decor naive naivete
    entree entrees fiance fiancee protege souffle saute sauteed
    creme brulee puree purees flambe consomme
    """.split()
)

_ACCENTED = re.compile(r"[àâäçéèêëîïôöùûüÿœæ]", re.IGNORECASE)
_WORD = re.compile(r"[0-9a-zÀ-ſ]+(?:'[a-zÀ-ſ]+)?", re.IGNORECASE)


def _strip_accents(word: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", word) if not unicodedata.combining(c)
    )


def _mask_names(text: str, names: Iterable[str]) -> str:
    """Blank out known proper nouns so their French words don't score.

    Longest first: "Le Pain des Fleurs" has to be removed before a shorter
    entry can eat part of it and leave "des" stranded in the remainder.
    """
    masked = text
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=len, reverse=True):
        masked = re.sub(re.escape(name), " ", masked, flags=re.IGNORECASE)
    return masked


def detect_non_english(text: str, *, allow: Iterable[str] = ()) -> list[str]:
    """Return the non-English markers in ``text``; empty means it reads English.

    ``allow`` holds proper nouns — brand, supplier and product names — that are
    permitted to stay French. They are removed before scoring.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    body = _mask_names(text, allow)
    low = body.lower()

    found: list[str] = []
    found.extend(c for c in _CONTRACTIONS if c in low)
    for raw in _WORD.findall(body):
        word = raw.lower()
        if word in _MARKERS:
            found.append(word)
        elif _ACCENTED.search(word) and _strip_accents(word) not in _LOANWORDS:
            found.append(word)
    # Stable order, no repeats — this string goes into a log line a human reads.
    seen: dict[str, None] = {}
    for f in found:
        seen.setdefault(f, None)
    return list(seen)


def check_items(
    items: Sequence[dict[str, Any]],
    *,
    allow: Iterable[str] = (),
    fields: Sequence[str] = ("title", "theme", "content_brief"),
) -> list[dict[str, Any]]:
    """Flag every item carrying non-English copy in ``fields``.

    Returns one record per affected item: its index, title, and the markers
    found per field. Nothing is rewritten — machine-translating marketing copy
    would produce worse English than the writer would, and a silent rewrite
    hides that the generator misbehaved. The caller logs this so the QA loop
    can see exactly which items to reissue.
    """
    allow = list(allow)
    flagged: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        per_field = {
            field: markers
            for field in fields
            if (markers := detect_non_english(item.get(field, ""), allow=allow))
        }
        if per_field:
            flagged.append(
                {
                    "index": index,
                    "title": str(item.get("title", ""))[:80],
                    "fields": per_field,
                }
            )
    return flagged


def format_flags(flagged: Sequence[dict[str, Any]], limit: int = 20) -> str:
    """One-line-per-item summary for the planning log."""
    parts = []
    for f in flagged[:limit]:
        detail = "; ".join(
            f"{field}[{','.join(markers[:6])}]" for field, markers in f["fields"].items()
        )
        parts.append(f"{f['title']!r} {detail}")
    if len(flagged) > limit:
        parts.append(f"(+{len(flagged) - limit} more)")
    return " | ".join(parts)
