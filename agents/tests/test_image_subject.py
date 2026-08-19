"""Tests for the image subject floor (empty_frame defect class).

Five Naturespan posts shipped a picture with nothing in it — a pale green wall
and a plank, a bare grey-green wall with palm fronds, two garden doors standing
open in an empty room. Every one of them was an ``image_format == "ad"`` post on
a calendar item with no ``product_ids``, the single combination whose prompt
asked for "lots of negative space" and then closed with "Do NOT include any
products. Focus on a clean branded backdrop."

The briefs below are the production rows verbatim, so the extraction assertions
are against real planner output rather than invented copy. The good cases from
the same brand — the family on the lagoon path and the Pranarom Arnica bottle on
a stone plinth — are asserted alongside them: whatever the floor does, it must
not change what those two ask for.
"""

import asyncio
import os
import sys

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.content.nodes as content_nodes
from shared.image_subject import (
    SUBJECT_LEXICON,
    build_art_direction_block,
    build_still_frame_directive,
    build_subject_floor_block,
    extract_subject_terms,
    is_motion_brief,
)

# ---------------------------------------------------------------------------
# Production rows — the five confirmed empty frames
# ---------------------------------------------------------------------------

EMPTY_FRAME_ITEMS: dict[str, dict[str, str]] = {
    "one_week_to_shop": {
        "title": "One week to shop with ease",
        "content_brief": (
            "[announcement] Create a calm, practical reel that builds anticipation for "
            "Naturespan’s upcoming magasin bio and épicerie bio premium experience, "
            "with organized curated shelves, clear category navigation, and a reassuring "
            "walkthrough that shows how the current food truck, the online shop, and the "
            "soon-to-open boutiques connect seamlessly. Include Grand Baie as a 100% "
            "organic cafe-restaurant in the visual story, and keep the feel "
            "premium-but-warm, clear, and opening-momentum focused."
        ),
        "visual_direction": (
            "Fast but polished montage of shelf details, signage mockups, food truck "
            "footage and a closing countdown card reading J-7."
        ),
        "theme": "Countdown preview of the upcoming magasin bio experience",
    },
    "start_online": {
        "title": "Start online, visit us from September 1",
        "content_brief": (
            "Create a calm, premium announcement reel that maps the full Naturespan "
            "ecosystem for countdown week: show the food truck already operating, the "
            "shop.naturespan.mu next-day delivery option with the Rs 2,000 minimum order, "
            "and the Grand Baie and Tamarin magasins bio opening on September 1. Frame it "
            "around practical convenience built on certified trust, so families can "
            "clearly see where to start online before visiting in person."
        ),
        "visual_direction": (
            "Fast, polished sequence moving from food truck to online shop interface to "
            "upcoming store signage."
        ),
        "theme": "How to shop before opening day",
    },
    "proof_first": {
        "title": "Proof first, before we open",
        "content_brief": (
            "[announcement] Announce Naturespan’s opening with a calm, proof-led "
            "message that positions the store as Mauritius’ certification-first organic "
            "destination. Emphasize 20+ ans d'expertise bio, ACCORD BIO backing, and a "
            "curated assortment drawn from 17,000+ references, with a visual cue of a "
            "premium magasin bio shelf and certification labels to show that every item "
            "stocked is selected for verifiable proof before opening day."
        ),
        "visual_direction": (
            "Clean editorial-style graphic or shelf image featuring certification marks, "
            "curated product rows, and understated sourcing callouts."
        ),
        "theme": "Why Naturespan's sourcing network matters before opening day",
    },
    "seven_days_clarity": {
        "title": "7 days to certified organic clarity",
        "content_brief": (
            "Create a short vertical announcement video building anticipation for the "
            "September 1 openings in Grand Baie and Tamarin, showing calm, premium magasin "
            "bio spaces and what shoppers can expect on their first visit. Keep the focus "
            "on certified-organic clarity: visible shelves of produits certifiés AB & "
            "Ecocert / Eurofeuille, the promise of 2,600+ certified products, and the "
            "reassurance of 20+ ans d'expertise bio through ACCORD BIO."
        ),
        "visual_direction": (
            "Bright, premium reel with exterior tease, shelf close-ups, and visible "
            "certification marks on-pack."
        ),
        "theme": "Countdown to the opening with a first look at the future magasin bio",
    },
    "two_new_doors": {
        "title": "Two new organic doors, clearly certified",
        "content_brief": (
            "[announcement] Create a calm opening-day reel for the new magasin bio "
            "locations in Grand Baie and Tamarin, showing a premium in-store walkthrough "
            "of the shelves, signage, and certified-organic details. Keep the focus on "
            "Naturespan’s proof points — 2,600+ certified products, around 140 "
            "brands, and 20+ ans d'expertise bio via ACCORD BIO — with close-ups of "
            "AB, Ecocert, and Eurofeuille labels so shoppers can immediately see why the "
            "bio claim is verifiable."
        ),
        "visual_direction": (
            "Bright opening-morning footage with exterior arrival shots, shelf details, "
            "and certification marks visible on pack."
        ),
        "theme": "Opening day: two new magasin bio doors open",
    },
}

# The two frames the reviewer called excellent, from the same calendar.
GOOD_FAMILY_BRIEF = (
    "Show a real Mauritian family walking a lagoon path with palms, carrying a woven "
    "basket of everyday organic groceries, relaxed and unposed, seven days before the "
    "shop opens."
)
GOOD_FAMILY_DIRECTION = "Warm outdoor lifestyle photograph, family in frame, natural light."

GOOD_PRODUCT_BRIEF = (
    "Hero a single real supplier bottle on a stone plinth against a soft studio wall so "
    "the pack and its own printed label carry the proof claim."
)
GOOD_PRODUCT_DIRECTION = "Studio product shot, one bottle, clean plinth, soft backdrop."


# ---------------------------------------------------------------------------
# Motion-brief detection
# ---------------------------------------------------------------------------


class TestIsMotionBrief:
    @pytest.mark.parametrize(
        "key", ["one_week_to_shop", "start_online", "seven_days_clarity", "two_new_doors"]
    )
    def test_reel_briefs_and_directions_are_detected(self, key):
        """Four of the five are reel scripts handed to a still-image model."""
        item = EMPTY_FRAME_ITEMS[key]
        assert is_motion_brief(item["content_brief"], item["visual_direction"]) is True

    def test_proof_first_is_a_still_brief_and_is_left_alone(self):
        """The fifth is not a shot list — its brief asks for an editorial shelf
        image and its direction says 'shelf image'. It failed purely because the
        ad branch dropped the brief, so it must not be flattened as a reel."""
        item = EMPTY_FRAME_ITEMS["proof_first"]
        assert is_motion_brief(item["content_brief"], item["visual_direction"]) is False

    def test_good_still_briefs_are_not_motion(self):
        assert is_motion_brief(GOOD_FAMILY_BRIEF, GOOD_FAMILY_DIRECTION) is False
        assert is_motion_brief(GOOD_PRODUCT_BRIEF, GOOD_PRODUCT_DIRECTION) is False

    def test_camera_metadata_is_not_mistaken_for_motion(self):
        """The realism directive says "Shot on Sony A7R IV" — singular "shot"
        must never trip the flattener."""
        assert is_motion_brief("Shot on Sony A7R IV with an 85mm f/1.8 prime lens.") is False

    def test_empty_input(self):
        assert is_motion_brief("", "", None or "") is False

    def test_directive_only_emitted_for_motion(self):
        assert build_still_frame_directive(GOOD_FAMILY_BRIEF) == ""
        directive = build_still_frame_directive(
            EMPTY_FRAME_ITEMS["one_week_to_shop"]["visual_direction"]
        )
        assert "ONE still photograph" in directive
        assert "establishing plate" in directive


# ---------------------------------------------------------------------------
# Subject extraction
# ---------------------------------------------------------------------------


def _subjects(key: str, **kwargs) -> list[str]:
    item = EMPTY_FRAME_ITEMS[key]
    return extract_subject_terms(
        item["content_brief"], item["visual_direction"], item["title"], **kwargs
    )


class TestExtractSubjectTerms:
    @pytest.mark.parametrize("key", sorted(EMPTY_FRAME_ITEMS))
    def test_every_empty_frame_brief_names_something_photographable(self, key):
        """Each of the five briefs describes real subjects. The generator simply
        never asked for them."""
        assert _subjects(key), f"{key} yielded no subject"

    def test_proof_first_asks_for_the_shelf_and_the_pack(self):
        """The audit's complaint was 'no pack, no shelf, no product'. All three
        are in the brief."""
        joined = " ".join(_subjects("proof_first"))
        assert "shelf" in joined
        assert "packs" in joined or "product" in joined

    def test_two_new_doors_asks_for_store_and_shelf_not_doors(self):
        """The metaphor rendered literally. 'door' is deliberately absent from
        the lexicon so it can never be promoted to a subject."""
        joined = " ".join(_subjects("two_new_doors"))
        assert "store" in joined
        assert "shelf" in joined
        assert "door" not in joined

    def test_one_week_picks_up_the_storefront_and_shelves(self):
        joined = " ".join(_subjects("one_week_to_shop"))
        assert "shop front" in joined or "store" in joined
        assert "shelf" in joined

    def test_ordering_is_deterministic_and_capped(self):
        first = _subjects("one_week_to_shop")
        assert first == _subjects("one_week_to_shop")
        assert len(first) <= 3
        assert len(extract_subject_terms(
            EMPTY_FRAME_ITEMS["one_week_to_shop"]["content_brief"], limit=1
        )) == 1

    def test_accented_french_brief_terms_match(self):
        """Planner briefs mix in 'épicerie', 'produits certifiés', 'magasins'."""
        assert extract_subject_terms("Notre épicerie bio et son café")

    def test_good_family_brief_yields_a_person(self):
        joined = " ".join(extract_subject_terms(GOOD_FAMILY_BRIEF, GOOD_FAMILY_DIRECTION))
        assert "person" in joined

    def test_good_product_brief_yields_the_product(self):
        joined = " ".join(extract_subject_terms(GOOD_PRODUCT_BRIEF, GOOD_PRODUCT_DIRECTION))
        assert "product" in joined

    def test_placeholder_posts_do_not_repeat_the_product_line(self):
        """When a blank container is already being staged for the Gemini swap,
        naming 'the product itself' again just fights the placeholder wording."""
        joined = " ".join(
            extract_subject_terms(GOOD_PRODUCT_BRIEF, has_product_placeholder=True)
        )
        assert "the product itself" not in joined

    def test_brief_with_nothing_photographable_returns_empty(self):
        assert extract_subject_terms("Premium quality and trust you can feel.") == []

    @pytest.mark.parametrize(
        "prose",
        [
            "2,600+ certified choices you can verify.",          # "can" != a tin
            "A leafy branch against the wall.",                  # != a retail branch
            "In order to keep the tone calm and on site.",       # != a device shot
            "Go to market with a clear promise.",                # != a market stall
        ],
    )
    def test_common_prose_words_are_not_mistaken_for_subjects(self, prose):
        """Trigger tokens that double as ordinary English pulled a subject out
        of copy that describes nothing — a floor naming the wrong thing is
        worse than one naming nothing."""
        assert extract_subject_terms(prose) == []

    def test_lexicon_trigger_sets_are_disjoint(self):
        """Overlapping triggers would make the score order ambiguous."""
        seen: set[str] = set()
        for _key, _phrase, triggers in SUBJECT_LEXICON:
            assert not (seen & triggers), sorted(seen & triggers)
            seen |= triggers


# ---------------------------------------------------------------------------
# The floor block itself
# ---------------------------------------------------------------------------


class TestSubjectFloorBlock:
    def test_floor_is_unconditional(self):
        """Even with no nameable subject the frame may not come back empty."""
        block = build_subject_floor_block([])
        assert "SUBJECT FLOOR" in block
        assert "empty wall" in block
        assert "FAILED image" in block

    def test_named_subjects_are_listed_in_order(self):
        block = build_subject_floor_block(["a stocked retail shelf", "the shop front"])
        assert block.index("a stocked retail shelf") < block.index("the shop front")

    def test_bans_every_observed_empty_frame_shape(self):
        block = build_subject_floor_block([])
        for shape in ("empty wall", "bare table", "plain colour or gradient",
                      "open doorway", "foliage"):
            assert shape in block, shape

    def test_bans_literal_metaphor_staging(self):
        assert "Figures of speech" in build_subject_floor_block([])

    def test_keeps_the_anti_fabrication_rule(self):
        """The line this floor replaced ("Do NOT include any products") existed
        to stop invented packaging. That intent must survive."""
        block = build_subject_floor_block([])
        assert "Do NOT invent branded packaging" in block
        assert "readable brand names" in block

    def test_placeholder_variant_keeps_the_container_as_hero(self):
        block = build_subject_floor_block([], has_product_placeholder=True)
        assert "unlabeled product container" in block
        assert "hero" in block

    def test_tolerates_none_and_blank_entries(self):
        assert build_subject_floor_block(None)
        assert "  " not in build_subject_floor_block(["", "   "]).replace("\n", "")


class TestArtDirectionBlock:
    def test_planner_direction_is_rendered(self):
        block = build_art_direction_block(
            EMPTY_FRAME_ITEMS["seven_days_clarity"]["visual_direction"]
        )
        assert "ART DIRECTION" in block
        assert "shelf close-ups" in block

    def test_blank_direction_yields_nothing(self):
        assert build_art_direction_block("") == ""
        assert build_art_direction_block(None) == ""
        assert build_art_direction_block("   ") == ""

    def test_long_direction_is_truncated(self):
        assert len(build_art_direction_block("shelf " * 500, max_chars=80)) < 160


# ---------------------------------------------------------------------------
# generate_background: the regression the five posts actually hit
# ---------------------------------------------------------------------------


def _state(item: dict, *, hook: str = "", with_product: bool = False) -> dict:
    return {
        "run_id": "",
        "brand_id": "8d0fb129-4797-4003-8457-edbd20f9dfcd",
        "calendar_item_id": "0c3d71d9-90a5-4883-844c-941209199573",
        "brand": {"name": "Naturespan", "color_palette": {}, "brand_guidelines": {}},
        "calendar_item": {"channel": "instagram", **item},
        "is_lifestyle_only": not with_product,
        "product_image": "https://example.invalid/pack.png" if with_product else None,
        "relevant_audience": {},
        "month_context": "",
        "enhanced_image_prompt": None,
        "hook": hook,
        "caption": "",
    }


def _prompt_for(monkeypatch, state: dict, image_format: str) -> str:
    """Run generate_background with all IO stubbed and return the built prompt."""
    captured: dict[str, str] = {}

    async def _fake_generate_image(prompt, **kwargs):
        captured["prompt"] = prompt
        return "https://example.invalid/generated.png"

    async def _noop(*args, **kwargs):
        return None

    async def _fake_format():
        return image_format

    monkeypatch.setattr(content_nodes, "generate_image", _fake_generate_image)
    monkeypatch.setattr(content_nodes, "update_agent_run_step", _noop)
    monkeypatch.setattr(content_nodes, "_decide_image_format", _fake_format)

    asyncio.run(content_nodes.generate_background(state))
    return captured["prompt"]


class TestGenerateBackgroundSubjectFloor:
    def test_ad_post_without_a_product_no_longer_asks_for_an_empty_backdrop(
        self, monkeypatch
    ):
        """The exact defect: ad format + no product_ids used to end the prompt on
        'Do NOT include any products. Focus on a clean branded backdrop.'"""
        item = EMPTY_FRAME_ITEMS["proof_first"]
        prompt = _prompt_for(
            monkeypatch, _state(item, hook=item["title"]), "ad"
        )
        assert "clean branded backdrop" not in prompt
        assert "Do NOT include any products" not in prompt

    @pytest.mark.parametrize("key", sorted(EMPTY_FRAME_ITEMS))
    def test_every_empty_frame_case_now_carries_a_subject_floor(self, monkeypatch, key):
        item = EMPTY_FRAME_ITEMS[key]
        prompt = _prompt_for(monkeypatch, _state(item, hook=item["title"]), "ad")
        assert "SUBJECT FLOOR" in prompt
        assert "FAILED image" in prompt

    @pytest.mark.parametrize("key", sorted(EMPTY_FRAME_ITEMS))
    def test_planner_visual_direction_reaches_the_image_model(self, monkeypatch, key):
        """It was written on every row and read by nothing."""
        item = EMPTY_FRAME_ITEMS[key]
        prompt = _prompt_for(monkeypatch, _state(item, hook=item["title"]), "ad")
        assert "ART DIRECTION" in prompt
        assert item["visual_direction"].split(",")[0][:30] in prompt

    def test_reel_brief_is_flattened_to_one_frame(self, monkeypatch):
        item = EMPTY_FRAME_ITEMS["one_week_to_shop"]
        prompt = _prompt_for(monkeypatch, _state(item, hook=item["title"]), "ad")
        assert "SINGLE FRAME" in prompt

    def test_lifestyle_branch_keeps_its_floor_and_loses_the_blanket_product_ban(
        self, monkeypatch
    ):
        item = EMPTY_FRAME_ITEMS["seven_days_clarity"]
        prompt = _prompt_for(monkeypatch, _state(item, hook=item["title"]), "lifestyle")
        assert "SUBJECT FLOOR" in prompt
        assert "Do NOT include any products" not in prompt
        # the narrower rule that replaced it must still be there
        assert "Do NOT invent branded packaging" in prompt

    def test_good_lifestyle_case_still_asks_for_the_family(self, monkeypatch):
        """The lagoon-path family frame was called excellent — the floor must
        reinforce it, not redirect it."""
        prompt = _prompt_for(
            monkeypatch,
            _state(
                {
                    "content_brief": GOOD_FAMILY_BRIEF,
                    "visual_direction": GOOD_FAMILY_DIRECTION,
                    "theme": "Countdown week",
                },
                hook="7 days to shop certified organic",
            ),
            "lifestyle",
        )
        assert "a real person handling" in prompt
        assert "SINGLE FRAME" not in prompt  # not a reel brief

    def test_good_product_ad_still_heroes_the_placeholder_container(self, monkeypatch):
        """The Pranarom bottle path: the blank container stays the hero and the
        pack-framing rules are untouched."""
        prompt = _prompt_for(
            monkeypatch,
            _state(
                {
                    "content_brief": GOOD_PRODUCT_BRIEF,
                    "visual_direction": GOOD_PRODUCT_DIRECTION,
                    "theme": "Real brands, real proof",
                },
                hook="Real brands, real proof on pack",
                with_product=True,
            ),
            "ad",
        )
        assert "unlabeled product container" in prompt
        assert "completely blank" in prompt
        assert "SUBJECT FLOOR" in prompt
        assert "hero" in prompt

    def test_item_without_visual_direction_still_builds(self, monkeypatch):
        prompt = _prompt_for(
            monkeypatch,
            _state({"content_brief": "A crate of mangoes on a market table."}),
            "ad",
        )
        assert "ART DIRECTION" not in prompt
        assert "SUBJECT FLOOR" in prompt
