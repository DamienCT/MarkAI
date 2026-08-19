"""Deterministic subject floor for the still-image prompt.

Why this module exists
----------------------
``shared.visual_brief`` binds the picture to the *words* printed on it: the
SCENE comes from the brief, MUST-SHOW props come from words the headline and
the brief both commit to. What it cannot express is the weaker, more basic
requirement that the frame contain *anything at all*.

Five posts on the Naturespan launch calendar satisfied every existing check and
still shipped an empty picture — a pale wall and a plank, a bare grey-green
wall with palm fronds, two garden doors standing open in an empty room. All
five share one signature: ``image_format == "ad"`` (chosen for ~half of all
posts by ``_decide_image_format``) combined with a calendar item that has no
``product_ids``. That combination took the ad branch's ``else`` arm, which
asked for a "premium minimal background ... lots of negative space" and then
closed with the literal instruction:

    "Do NOT include any products. Focus on a clean branded backdrop."

An item with no product has nothing else to show, so "clean branded backdrop"
is the whole picture. In the review queue that combination occurred exactly
five times and produced exactly the five reported defects — no other post of
that brand hit it, and no post that hit it escaped.

Two behaviours make it worse and are handled here too:

* **Shot-list briefs.** Most planner briefs are written for a reel ("montage of
  shelf details, signage mockups, food truck footage and a closing countdown
  card reading J-7"). A still-image model cannot render a montage, so it
  renders the *mood* of one — an establishing plate with every concrete subject
  in the shot list dropped.

* **Headline metaphors staged literally.** "Two new organic doors, clearly
  certified" meant two new stores. The image model photographed two doors.

Nothing here calls an LLM or the network. The lexicon is generic commercial
photography vocabulary — shelves, storefronts, packs, people, produce — so a
brand onboarded tomorrow gets the same floor without anyone writing rules for
it.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "is_motion_brief",
    "build_still_frame_directive",
    "extract_subject_terms",
    "build_subject_floor_block",
    "build_art_direction_block",
    "SUBJECT_LEXICON",
]


# ---------------------------------------------------------------------------
# Text folding
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _fold(text: str) -> str:
    """Lowercase and strip accents so ``café`` / ``certifiés`` match plainly.

    Planner briefs mix English and French ("magasin bio", "produits certifiés",
    "épicerie"), so the lexicon below is written in unaccented ASCII and every
    input is folded to match it.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.lower()


def _tokens(*texts: str) -> set[str]:
    """Union of the word tokens across every supplied text."""
    out: set[str] = set()
    for text in texts:
        out.update(_TOKEN_RE.findall(_fold(text)))
    return out


# ---------------------------------------------------------------------------
# Motion briefs: shot lists handed to a still-image model
# ---------------------------------------------------------------------------

# Words that only make sense for footage. Singular "shot" is deliberately
# absent — the realism directive in the prompt says "Shot on Sony A7R IV".
_MOTION_TOKENS = frozenset(
    """
    reel reels video videos montage montages sequence sequences footage clip
    clips walkthrough walkthroughs broll timelapse cutaway cutaways transitions
    transition shots scenes pacing voiceover soundtrack subtitles
    """.split()
)

_MOTION_PHRASES = (
    "closing card",
    "end card",
    "opening shot",
    "final frame",
    "on-screen text",
    "cuts to",
    "b-roll",
)

STILL_FRAME_DIRECTIVE = (
    "SINGLE FRAME — the brief above was written for a video. This is ONE still "
    "photograph. Choose the single most concrete, subject-forward moment the "
    "brief describes and shoot only that moment, fully staged. Sequences, "
    "montages, transitions, walkthroughs, B-roll, on-screen text and closing "
    "cards cannot exist in a still frame: do NOT gesture at them with an empty "
    "establishing plate. "
)


def is_motion_brief(*texts: str) -> bool:
    """True when any supplied text was written as a shot list for footage."""
    tokens = _tokens(*texts)
    if tokens & _MOTION_TOKENS:
        return True
    blob = " ".join(_fold(t) for t in texts)
    return any(phrase in blob for phrase in _MOTION_PHRASES)


def build_still_frame_directive(*texts: str) -> str:
    """Render the single-frame directive, or "" for a brief already written
    as a still."""
    return STILL_FRAME_DIRECTIVE if is_motion_brief(*texts) else ""


# ---------------------------------------------------------------------------
# Subject lexicon
# ---------------------------------------------------------------------------

# (key, what to shoot, trigger tokens). Ordered by how strongly the subject
# carries a commercial frame on its own — a pack in focus beats a storefront
# beats a mood. Trigger sets are disjoint so scoring is unambiguous.
#
# Only physically photographable things belong here. Certification marks,
# "proof" and "quality" are deliberately absent: they are attributes of a
# subject, they collide with the prompt's standing ban on rendering legible
# text, and requiring one on its own is how you get a wall with a leaf on it.
SUBJECT_LEXICON: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "product",
        "the product itself — real packs, bottles or jars, in focus in the foreground",
        frozenset(
            """
            product products pack packs packaging packshot bottle bottles jar
            jars tube tubes box boxes pouch pouches carton cartons cans
            sachet sachets sku skus reference references
            """.split()
            # "can" (the modal verb) is deliberately absent — "2,600+ certified
            # choices you can verify" is not a brief for a tin.
        ),
    ),
    (
        "person",
        "a real person handling, choosing, carrying or using it",
        frozenset(
            """
            people person persons family families shopper shoppers customer
            customers client clients staff team seller sellers child children
            kid kids hand hands guest guests visitor visitors member members
            mother father parent parents neighbour neighbours
            """.split()
        ),
    ),
    (
        "shelf",
        "a stocked retail shelf with the packs facing the camera",
        frozenset(
            """
            shelf shelves aisle aisles rayon rayons display displays rack racks
            shelving stocked assortment curated basket baskets trolley
            """.split()
        ),
    ),
    (
        "storefront",
        "the shop front or the inside of the store, with its fittings and signage",
        frozenset(
            """
            store stores shop shops storefront shopfront boutique boutiques
            magasin magasins epicerie epiceries outlet outlets
            premises entrance facade signage interior counter
            """.split()
            # "branch" is absent: in these briefs it is far more often a leafy
            # branch than a retail one.
        ),
    ),
    (
        "vehicle",
        "the food truck, van or market stall itself, open and in service",
        frozenset(
            """
            truck trucks van vans kiosk kiosks stall stalls cart carts trailer
            trailers
            """.split()
        ),
    ),
    (
        "table",
        "prepared food or drink served on a real table",
        frozenset(
            """
            cafe cafes restaurant restaurants menu menus dish dishes meal meals
            plate plates coffee drink drinks table tables kitchen recipe
            recipes tasting bowl bowls cup cups breakfast lunch dinner
            """.split()
        ),
    ),
    (
        "produce",
        "fresh produce or raw ingredients arranged in the scene",
        frozenset(
            """
            produce fruit fruits vegetable vegetables ingredient ingredients
            harvest farm farms grain grains herb herbs greens salad
            """.split()
        ),
    ),
    (
        "screen",
        "a phone or laptop screen held or used in a real setting",
        frozenset(
            """
            online website app apps screen screens laptop phone smartphone
            tablet delivery ecommerce checkout
            """.split()
            # "order" and "site" are absent: "in order to", "order of
            # preference" and "on site" are ordinary prose, not a device shot.
        ),
    ),
)

# Subject keys whose canonical phrase is redundant when the pipeline is already
# staging a blank placeholder container for Gemini to swap out.
_PLACEHOLDER_REDUNDANT = frozenset({"product"})


def extract_subject_terms(
    *texts: str,
    limit: int = 3,
    has_product_placeholder: bool = False,
) -> list[str]:
    """Concrete things to photograph, named by the brief itself.

    Scores every lexicon entry by how many of its trigger tokens appear across
    ``texts`` and returns the best ``limit`` canonical phrases, strongest first
    and ties broken by lexicon order so the result is stable for a given brief.

    Returns ``[]`` when the brief names nothing photographable — the caller
    still emits a floor, it just cannot name a subject.
    """
    tokens = _tokens(*texts)
    if not tokens:
        return []

    scored: list[tuple[int, int, str]] = []
    for index, (key, phrase, triggers) in enumerate(SUBJECT_LEXICON):
        if has_product_placeholder and key in _PLACEHOLDER_REDUNDANT:
            continue
        hits = len(tokens & triggers)
        if hits:
            scored.append((-hits, index, phrase))

    scored.sort()
    return [phrase for _, _, phrase in scored[: max(0, limit)]]


# ---------------------------------------------------------------------------
# Prompt blocks
# ---------------------------------------------------------------------------

# Named because the model reliably reaches for one of them when the brief gives
# it nothing to place: they are the five empty frames this module exists to
# stop, described back to it as failures.
_EMPTY_FRAME_BAN = (
    "A frame whose only contents are an empty wall, a bare table, plinth, "
    "counter or floor, a plain colour or gradient, an open doorway, or loose "
    "foliage, plants and props is a FAILED image — do not produce one. "
)

_METAPHOR_BAN = (
    "Read the brief as a description of a real place. Figures of speech and "
    "wordplay in the headline must NEVER be staged as literal objects — "
    "\"two new doors\" means two new stores, not two doors. "
)

_NO_FABRICATED_BRANDING = (
    "Do NOT invent branded packaging, readable brand names, slogans or logos on "
    "anything in frame — printing on packs must stay soft and out of focus. "
)


def build_subject_floor_block(
    subjects: list[str] | tuple[str, ...] | None,
    *,
    has_product_placeholder: bool = False,
) -> str:
    """Render the non-negotiable "something must be in this picture" block.

    Always returns a non-empty string: the floor is unconditional, and the
    named subjects only sharpen it.
    """
    if has_product_placeholder:
        lead = (
            "SUBJECT FLOOR — the unlabeled product container described above is "
            "the hero: fully in frame, in focus, and unmistakably the thing "
            "being photographed. "
        )
    else:
        lead = (
            "SUBJECT FLOOR — this is a marketing photograph, not a backdrop "
            "plate. At least one concrete, identifiable subject must be "
            "present, in focus, and large enough to read at a glance on a "
            "phone. "
        )

    items = [str(s).strip() for s in (subjects or []) if str(s).strip()]
    if items:
        want = "Stage, in order of preference: " + "; ".join(items) + ". "
    else:
        want = "Stage the people, place or object the brief is literally about. "

    return lead + want + _EMPTY_FRAME_BAN + _METAPHOR_BAN + _NO_FABRICATED_BRANDING


def build_art_direction_block(visual_direction: str | None, max_chars: int = 400) -> str:
    """Render the planner's per-item ``visual_direction`` (or "").

    The planning agent writes one sentence of art direction for every calendar
    item and stores it on the row. Until now the content workflow never read
    the column, so the most concrete visual instruction in the whole record —
    "shelf close-ups, and visible certification marks on-pack" — was thrown
    away while the image model was handed a campaign theme instead.
    """
    text = " ".join(str(visual_direction or "").split())
    if not text:
        return ""
    return f"ART DIRECTION (from the campaign plan): {text[:max_chars]}\n\n"
