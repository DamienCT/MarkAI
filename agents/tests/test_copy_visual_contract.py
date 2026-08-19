"""Tests for the copy -> image contract (image defect class "other").

The production failure these lock down: ``generate_background``'s
``image_format == "ad"`` branch was the first ``if`` in the chain, so an ad
post's image prompt was built from ``calendar_items.theme`` alone — the brief
and the enhanced art-director prompt were both discarded. Roughly half of every
brand's posts take that branch (``_decide_image_format`` balances the mix
globally), so half of all posts were photographed from a five-word campaign
label.

Four confirmed occurrences, all ``text_style == 'headline'`` (= ad format):

  8513153e  "Friday board ready for sharing?"      brief asked for a sharing
            board with crisp toasts, olives and cheese; frame delivered
            chocolate chunks, truffles, cashews, almonds and pistachios
            beside Prosciutto di Parma — and no board.
  63dcde2c  "Weekend board, instantly inviting"    brief asked for a board with
            toasts, olives and nuts; frame delivered a matcha bowl, a bamboo
            tea mat and a cup of green tea.
  83ce6820  "Monday deserves espresso and chocolate"  brief named World
            Chocolate Day; frame delivered a bowl of greengages.
  1c5a938b  "First look at our organic shelves"    brief named six real
            supplier brands; frame delivered one jar on a rock.

Second cause in the same class: a brand's written ``donts`` reached every copy
prompt but no image prompt, so Naturespan's "NEVER use 'farm-to-table'" and
FancyFinds' "never place sweet fruit next to a savoury cured meat" governed the
words while the picture broke both.
"""

import asyncio
import json
import os
import sys

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.content.nodes as content_nodes
from shared.visual_brief import (
    brand_visual_rules,
    build_copy_contract_block,
    build_critic_contract_block,
    build_must_show_block,
    build_scene_block,
    build_time_of_day_directive,
    build_visual_guardrail_block,
    coerce_guidelines,
    extract_promised_props,
    extract_time_of_day,
    resolve_scene_text,
    strip_brief_tag,
)


# --------------------------------------------------------------------------
# The real briefs and headlines from the failing production items
# --------------------------------------------------------------------------

FRIDAY_BOARD_BRIEF = (
    "[lifestyle] Create a Friday evening grazing scene centered on Citterio, "
    "T.Fresco Proscuitto Parma, 70 g as the hero product, styled on a "
    "beautifully arranged sharing board with generic accompaniments like crisp "
    "toasts, olives, and cheese. Keep the mood premium yet effortless, "
    "capturing FancyFinds' hosting-led positioning and the feeling of "
    "belonging through an easy, social end-of-week unwind."
)
FRIDAY_BOARD_HEADLINE = "Friday board ready for sharing?"

WEEKEND_BOARD_BRIEF = (
    "[lifestyle] Create a relaxed weekend sharing board centered on Citterio, "
    "T.Fresco Proscuitto Parma, 70 g, styled for casual hosting with premium "
    "cured meats and generic pantry staples like crisp toasts, olives, and nuts."
)
WEEKEND_BOARD_HEADLINE = "Weekend board, instantly inviting"

CHOCOLATE_BRIEF = (
    "[lifestyle] Create a warm at-home coffee ritual post centered on "
    "Segafredo, Capsules Classico Espresso Alu, 10 x 5.1 g, showing how its "
    "rich espresso notes can elevate a chocolate-inspired sweet pairing for a "
    "premium week-start moment. Keep World Chocolate Day in view."
)
CHOCOLATE_HEADLINE = "Monday deserves espresso and chocolate"

FANCYFINDS_GUIDELINES = {
    "donts": [
        "Don't compare against or name competitors",
        "Never mix categories that would not naturally appear together "
        "(e.g. never place sweet fruit such as strawberries or grapes next to "
        "a savoury cured meat like ham)",
        "Don't promise specific prices or stock levels that can change",
    ],
    "dos": ["Lead with the hosting moment, not the distributor relationship"],
}

NATURESPAN_GUIDELINES = {
    "donts": [
        "NEVER use 'farm-to-table' (no confirmed local farm partnerships) — "
        "say '100% organic cafe-restaurant' instead",
        "NEVER claim the company or store itself is certified — only the "
        "products are",
    ]
}

# The two frames the audit called excellent. They must stay unconstrained:
# a fix that starts over-specifying good briefs is a regression.
GOOD_FAMILY_HEADLINE = "7 days to shop certified organic"
GOOD_FAMILY_BRIEF = (
    "Create a warm scene of a real Mauritian family by the lagoon under palms, "
    "no products in frame, natural daylight."
)
GOOD_PACK_HEADLINE = "Real brands, real proof on pack"
GOOD_PACK_BRIEF = (
    "Show a real Pranarom Arnica bottle standing on a stone plinth, with the "
    "certification mark on the pack clearly readable."
)


# --------------------------------------------------------------------------
# Scene resolution: the brief is the scene, the theme never is
# --------------------------------------------------------------------------


class TestSceneResolution:
    def test_routing_tag_is_stripped(self):
        assert strip_brief_tag("[lifestyle] Create a Friday evening scene").startswith(
            "Create a Friday"
        )
        assert strip_brief_tag("[announcement] Countdown reel").startswith("Countdown")

    def test_untagged_brief_survives_intact(self):
        assert strip_brief_tag(GOOD_PACK_BRIEF) == GOOD_PACK_BRIEF

    def test_enhanced_prompt_wins_over_brief(self):
        item = {"content_brief": FRIDAY_BOARD_BRIEF, "theme": "Indulgent Everyday"}
        assert resolve_scene_text(item, "A slate board under raking light") == (
            "A slate board under raking light"
        )

    def test_brief_is_used_when_there_is_no_enhanced_prompt(self):
        item = {"content_brief": FRIDAY_BOARD_BRIEF, "theme": "Indulgent Everyday"}
        scene = resolve_scene_text(item, None)
        assert "sharing board" in scene
        assert not scene.startswith("[lifestyle]")

    def test_description_is_the_last_resort(self):
        item = {"content_brief": "", "description": "A jar on a windowsill"}
        assert resolve_scene_text(item, None) == "A jar on a windowsill"

    def test_theme_is_never_promoted_to_a_scene(self):
        # This is the whole bug: "Indulgent Everyday Pairings & Social Treat
        # Moments" is a campaign label, and using it as a scene description is
        # what produced chocolate truffles beside Prosciutto di Parma.
        item = {"theme": "Indulgent Everyday Pairings & Social Treat Moments"}
        assert resolve_scene_text(item, None) == ""

    def test_scene_block_is_empty_without_a_scene(self):
        assert build_scene_block("") == ""
        assert build_scene_block("   ") == ""

    def test_scene_block_labels_the_scene(self):
        block = build_scene_block("A slate board")
        assert "SCENE" in block
        assert "A slate board" in block


# --------------------------------------------------------------------------
# Promised props: headline ∩ brief
# --------------------------------------------------------------------------


class TestPromisedProps:
    def test_friday_board_requires_a_board(self):
        props = extract_promised_props(
            FRIDAY_BOARD_HEADLINE, strip_brief_tag(FRIDAY_BOARD_BRIEF)
        )
        assert "board" in props

    def test_weekend_board_requires_a_board(self):
        props = extract_promised_props(
            WEEKEND_BOARD_HEADLINE, strip_brief_tag(WEEKEND_BOARD_BRIEF)
        )
        assert "board" in props

    def test_chocolate_post_requires_chocolate_and_espresso(self):
        props = extract_promised_props(
            CHOCOLATE_HEADLINE, strip_brief_tag(CHOCOLATE_BRIEF)
        )
        assert "chocolate" in props
        assert "espresso" in props

    def test_plural_headline_matches_singular_brief(self):
        props = extract_promised_props(
            "First look at our organic shelves",
            "A countdown showing the shelf edge of the new magasin bio, organic "
            "stock lined up.",
        )
        assert "shelves" in props

    def test_weekday_is_not_a_prop(self):
        # "Friday" is handled by the time-of-day directive; you cannot
        # photograph a weekday.
        props = extract_promised_props(
            FRIDAY_BOARD_HEADLINE, strip_brief_tag(FRIDAY_BOARD_BRIEF)
        )
        assert "friday" not in props

    def test_marketing_abstractions_are_not_props(self):
        props = extract_promised_props(
            "A premium moment, beautifully styled",
            "Create a premium moment beautifully styled for the brand.",
        )
        assert props == []

    def test_good_lifestyle_brief_is_left_unconstrained(self):
        # The audit called this frame excellent. Nothing in the headline is a
        # concrete prop the brief also named, so no MUST-SHOW is imposed.
        assert extract_promised_props(GOOD_FAMILY_HEADLINE, GOOD_FAMILY_BRIEF) == []

    def test_good_product_brief_keeps_its_real_subject(self):
        props = extract_promised_props(GOOD_PACK_HEADLINE, GOOD_PACK_BRIEF)
        assert "pack" in props

    def test_headline_only_words_are_not_promoted(self):
        # A word the brief never mentioned is often figurative; requiring it
        # would over-constrain the image model.
        props = extract_promised_props("Your organic table awaits", GOOD_FAMILY_BRIEF)
        assert "table" not in props

    def test_empty_inputs_are_safe(self):
        assert extract_promised_props("", "") == []
        assert extract_promised_props(None, None) == []

    def test_props_are_capped(self):
        headline = "board toasts olives cheese nuts grapes plates napkins linen"
        props = extract_promised_props(headline, headline, limit=3)
        assert len(props) == 3

    def test_must_show_block_is_empty_without_props(self):
        assert build_must_show_block([]) == ""
        assert build_must_show_block(None) == ""

    def test_must_show_block_names_every_prop(self):
        block = build_must_show_block(["board", "olives"])
        assert "MUST BE VISIBLE IN FRAME" in block
        assert "board" in block and "olives" in block


# --------------------------------------------------------------------------
# Time of day
# --------------------------------------------------------------------------


class TestTimeOfDay:
    def test_friday_night_is_night(self):
        # "Friday night, cup in hand" rendered in bright flat daylight.
        assert extract_time_of_day("Friday night, cup in hand") == "night"

    def test_dim_the_lights_is_night(self):
        assert extract_time_of_day("", "Dim the lights and pour a cup") == "night"

    def test_evening_brief_is_evening(self):
        assert extract_time_of_day("", "", "a Friday evening grazing scene") == "evening"

    def test_brunch_is_morning(self):
        assert extract_time_of_day("Brunch starts with the coffee") == "morning"

    def test_headline_outranks_the_brief(self):
        assert (
            extract_time_of_day("Friday night, cup in hand", "", "a bright brunch table")
            == "night"
        )

    def test_neutral_copy_has_no_time_constraint(self):
        assert extract_time_of_day(GOOD_PACK_HEADLINE, "", GOOD_PACK_BRIEF) is None

    def test_night_directive_forbids_daylight(self):
        directive = build_time_of_day_directive("night")
        assert "NIGHT" in directive
        assert "No daylight" in directive

    def test_unknown_key_yields_no_directive(self):
        assert build_time_of_day_directive(None) == ""
        assert build_time_of_day_directive("teatime") == ""


# --------------------------------------------------------------------------
# Brand guardrails reach the picture
# --------------------------------------------------------------------------


class TestVisualGuardrails:
    def test_guidelines_parse_from_a_json_string(self):
        brand = {"brand_guidelines": json.dumps(FANCYFINDS_GUIDELINES)}
        assert coerce_guidelines(brand)["donts"] == FANCYFINDS_GUIDELINES["donts"]

    def test_broken_guidelines_json_degrades_to_empty(self):
        assert coerce_guidelines({"brand_guidelines": "{not json"}) == {}
        assert coerce_guidelines({"brand_guidelines": None}) == {}
        assert coerce_guidelines(None) == {}

    def test_category_mixing_rule_reaches_the_image_prompt(self):
        block = build_visual_guardrail_block(
            {"brand_guidelines": FANCYFINDS_GUIDELINES}
        )
        assert "never place sweet fruit" in block
        assert "MUST NEVER APPEAR OR BE IMPLIED" in block

    def test_farm_to_table_rule_reaches_the_image_prompt(self):
        block = build_visual_guardrail_block(
            {"brand_guidelines": NATURESPAN_GUIDELINES}
        )
        assert "farm-to-table" in block

    def test_block_says_the_rules_govern_the_picture(self):
        block = build_visual_guardrail_block(
            {"brand_guidelines": NATURESPAN_GUIDELINES}
        )
        assert "GOVERN THE PICTURE" in block

    def test_dos_are_included_when_present(self):
        block = build_visual_guardrail_block(
            {"brand_guidelines": FANCYFINDS_GUIDELINES}
        )
        assert "hosting moment" in block

    def test_brand_without_guidelines_gets_no_block(self):
        assert build_visual_guardrail_block({}) == ""
        assert build_visual_guardrail_block({"brand_guidelines": {}}) == ""

    def test_rules_are_capped_and_trimmed(self):
        brand = {"brand_guidelines": {"donts": ["x" * 500] + [f"rule {i}" for i in range(40)]}}
        rules = brand_visual_rules(brand)
        assert len(rules) <= 14
        assert all(len(r) <= 220 for r in rules)

    def test_blank_rules_are_dropped(self):
        brand = {"brand_guidelines": {"donts": ["", "   ", None, "Real rule"]}}
        assert brand_visual_rules(brand) == ["Real rule"]


# --------------------------------------------------------------------------
# Composed contract
# --------------------------------------------------------------------------


class TestCopyContractBlock:
    def test_friday_board_contract_carries_prop_lighting_and_rules(self):
        block = build_copy_contract_block(
            headline=FRIDAY_BOARD_HEADLINE,
            caption="Add crisp toasts, olives, and cheese, then let the board do the hosting",
            scene_text=strip_brief_tag(FRIDAY_BOARD_BRIEF),
            brand={"brand_guidelines": FANCYFINDS_GUIDELINES},
        )
        assert "MUST BE VISIBLE IN FRAME: board" in block
        assert "EVENING" in block
        assert "never place sweet fruit" in block

    def test_studio_ad_drops_the_time_of_day_mandate(self):
        # A poster is lit for the product. "NOT flat even studio light" would
        # contradict the ad treatment's own "even commercial lighting".
        block = build_copy_contract_block(
            headline=FRIDAY_BOARD_HEADLINE,
            caption="",
            scene_text=strip_brief_tag(FRIDAY_BOARD_BRIEF),
            brand={"brand_guidelines": FANCYFINDS_GUIDELINES},
            apply_time_of_day=False,
        )
        assert "MUST BE VISIBLE IN FRAME: board" in block
        assert "TIME OF DAY" not in block

    def test_contract_is_empty_when_nothing_is_promised(self):
        assert (
            build_copy_contract_block(
                headline=GOOD_FAMILY_HEADLINE,
                caption="",
                scene_text=GOOD_FAMILY_BRIEF,
                brand={},
            )
            == ""
        )

    def test_contract_is_deterministic(self):
        kwargs = dict(
            headline=CHOCOLATE_HEADLINE,
            caption="Pair it with a square of dark chocolate",
            scene_text=strip_brief_tag(CHOCOLATE_BRIEF),
            brand={"brand_guidelines": FANCYFINDS_GUIDELINES},
        )
        assert build_copy_contract_block(**kwargs) == build_copy_contract_block(**kwargs)


class TestCriticContractBlock:
    def test_no_contract_leaves_the_critic_prompt_untouched(self):
        assert build_critic_contract_block("Any headline", [], []) == ""
        assert build_critic_contract_block("Any headline", None, None) == ""

    def test_critic_is_asked_about_the_named_props(self):
        block = build_critic_contract_block(
            FRIDAY_BOARD_HEADLINE, ["board"], FANCYFINDS_GUIDELINES["donts"]
        )
        assert "board" in block
        assert "missing_subjects" in block
        assert "violated_rules" in block

    def test_contract_does_not_touch_the_placement_verdict(self):
        block = build_critic_contract_block(FRIDAY_BOARD_HEADLINE, ["board"], [])
        assert "does NOT change 'ok'" in block


# --------------------------------------------------------------------------
# generate_background — the node that had the bug
# --------------------------------------------------------------------------


def _ad_state(brief: str, headline: str, guidelines: dict) -> dict:
    # No run_id on purpose: update_agent_run_step no-ops without one, keeping
    # the test fully offline.
    return {
        "brand_id": "brand-1",
        "calendar_item_id": "item-1",
        "brand": {
            "name": "FancyFinds",
            "color_palette": {"primary": "#2f4f2f"},
            "brand_guidelines": guidelines,
        },
        "calendar_item": {
            "channel": "facebook",
            "theme": "Indulgent Everyday Pairings & Social Treat Moments",
            "content_brief": brief,
        },
        "hook": headline,
        "caption": (
            "Add crisp toasts, olives, and cheese, then let the board do the hosting"
        ),
        "is_lifestyle_only": False,
        "product_image": "content-images/brand-1/product.png",
        "relevant_audience": {},
        "month_context": "",
        "enhanced_image_prompt": None,
    }


def _capture_prompt(monkeypatch, image_format: str) -> dict:
    """Patch out the network and record the prompt generate_background builds."""
    captured: dict = {}

    async def fake_generate_image(prompt, size=None, channel=None, **kwargs):
        captured["prompt"] = prompt
        captured["size"] = size
        return "content-images/brand-1/item-1/background.png"

    async def fake_decide_image_format():
        return image_format

    monkeypatch.setattr(content_nodes, "generate_image", fake_generate_image)
    monkeypatch.setattr(content_nodes, "_decide_image_format", fake_decide_image_format)
    return captured


class TestGenerateBackgroundCarriesTheBrief:
    def test_ad_post_prompt_contains_the_briefed_props(self, monkeypatch):
        # The regression: this branch used to send `theme` alone, so the image
        # model never heard the words "board", "toasts", "olives" or "cheese".
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        prompt = captured["prompt"]
        assert "sharing board" in prompt
        assert "crisp toasts" in prompt
        assert "olives" in prompt
        assert "cheese" in prompt

    def test_ad_post_prompt_states_the_scene_is_what_to_shoot(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        prompt = captured["prompt"]
        assert "SCENE" in prompt
        # The theme survives as context, demoted below the scene.
        assert "Indulgent Everyday Pairings" in prompt
        assert "context only" in prompt

    def test_ad_post_prompt_requires_the_promised_prop(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        assert "MUST BE VISIBLE IN FRAME: board" in captured["prompt"]

    def test_ad_post_prompt_carries_the_brand_dont(self, monkeypatch):
        # Chocolate truffles were staged directly beside Prosciutto di Parma.
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        assert "never place sweet fruit" in captured["prompt"]

    def test_ad_post_keeps_its_studio_advertisement_treatment(self, monkeypatch):
        # The fix must change the subject, not the look: "ad" still means a
        # clean studio poster with negative space for the big headline.
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        prompt = captured["prompt"]
        assert "PRODUCT ADVERTISEMENT" in prompt
        assert "negative space" in prompt

    def test_ad_post_without_a_brief_still_falls_back_to_the_theme(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "ad")
        state = _ad_state("", FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES)
        state["calendar_item"]["content_brief"] = ""
        asyncio.run(content_nodes.generate_background(state))
        prompt = captured["prompt"]
        # The theme still reaches the prompt when there is no brief — but never
        # as a bare "Theme: <label>." line. That form reads as a title to
        # typeset, and bake-off models duly rendered it into the frame as a
        # caption bar (see test_image_prompt_hygiene). It is now marked as
        # context with an explicit do-not-render instruction.
        assert "Indulgent Everyday Pairings" in prompt
        assert "Theme: Indulgent" not in prompt
        assert "do NOT render this as words" in prompt
        # Still distinguishable from the with-a-brief path, which additionally
        # says the scene above is what to shoot.
        assert "context only" not in prompt

    def test_chocolate_post_carries_chocolate_into_the_prompt(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(CHOCOLATE_BRIEF, CHOCOLATE_HEADLINE, FANCYFINDS_GUIDELINES)
            )
        )
        prompt = captured["prompt"]
        assert "chocolate-inspired" in prompt
        assert "MUST BE VISIBLE IN FRAME" in prompt
        assert "chocolate" in prompt.split("MUST BE VISIBLE IN FRAME")[1][:120]

    def test_ad_post_does_not_get_a_contradictory_lighting_mandate(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        assert "TIME OF DAY" not in captured["prompt"]

    def test_lifestyle_post_also_gets_the_contract(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "lifestyle")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(
                    FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
                )
            )
        )
        prompt = captured["prompt"]
        assert "sharing board" in prompt
        assert "never place sweet fruit" in prompt
        # The lifestyle branch is where "Friday night rendered in daylight"
        # happened, so it keeps the time-of-day mandate.
        assert "TIME OF DAY — EVENING" in prompt
        # ...without losing the documentary-photography rails.
        assert "REAL PHOTOGRAPH" in prompt

    def test_enhanced_prompt_branch_gets_the_contract(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "lifestyle")
        state = _ad_state(
            FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, FANCYFINDS_GUIDELINES
        )
        state["enhanced_image_prompt"] = (
            "A slate sharing board on weathered oak, raking evening light."
        )
        asyncio.run(content_nodes.generate_background(state))
        prompt = captured["prompt"]
        assert "slate sharing board" in prompt
        assert "MUST BE VISIBLE IN FRAME: board" in prompt

    def test_brand_without_guidelines_still_renders(self, monkeypatch):
        captured = _capture_prompt(monkeypatch, "ad")
        asyncio.run(
            content_nodes.generate_background(
                _ad_state(FRIDAY_BOARD_BRIEF, FRIDAY_BOARD_HEADLINE, {})
            )
        )
        prompt = captured["prompt"]
        assert "sharing board" in prompt
        assert "MUST NEVER APPEAR" not in prompt


# --------------------------------------------------------------------------
# review_branding — the critic now checks the contract it can check
# --------------------------------------------------------------------------


def _review_state(image_format: str) -> dict:
    return {
        "brand_id": "brand-1",
        "calendar_item_id": "item-1",
        "image_format": image_format,
        "branded_image": "content-images/brand-1/item-1/branded.png",
        "composed_image": "content-images/brand-1/item-1/composed.png",
        "brand": {
            "name": "FancyFinds",
            "brand_guidelines": {
                **FANCYFINDS_GUIDELINES,
                "logos": {"dark": {"url": "/logo-dark.png"}},
            },
        },
        "calendar_item": {"content_brief": FRIDAY_BOARD_BRIEF},
        "hook": FRIDAY_BOARD_HEADLINE,
        "enhanced_image_prompt": None,
    }


def _patch_review(monkeypatch, review: dict | None) -> dict:
    captured: dict = {}

    async def fake_download(bucket, obj):
        return b"\x89PNG-not-a-real-image"

    async def fake_vision(
        data, variants, *, headline="", required_props=None, forbidden_rules=None
    ):
        captured["headline"] = headline
        captured["required_props"] = required_props
        captured["forbidden_rules"] = forbidden_rules
        return None if review is None else dict(review)

    monkeypatch.setattr(content_nodes, "async_download_file", fake_download)
    monkeypatch.setattr(content_nodes, "_vision_review_branding", fake_vision)
    return captured


class TestReviewBrandingChecksTheContract:
    def test_ad_post_is_now_reviewed_against_its_headline(self, monkeypatch):
        # Every one of the four failures shipped with
        # branding_review == {"ok": true, "reason": "ad headline (AI-placed)"}
        # because the ad path returned before ever looking at the picture.
        captured = _patch_review(
            monkeypatch,
            {"ok": True, "reason": "fine", "missing_subjects": [], "violated_rules": []},
        )
        result = asyncio.run(content_nodes.review_branding(_review_state("ad")))
        assert captured["required_props"] == ["board"]
        assert any("sweet fruit" in r for r in captured["forbidden_rules"])
        assert result["branding_review"]["copy_contract_ok"] is True

    def test_ad_post_missing_prop_is_flagged(self, monkeypatch):
        _patch_review(
            monkeypatch,
            {
                "ok": True,
                "reason": "placement fine",
                "missing_subjects": ["board"],
                "violated_rules": [],
            },
        )
        review = asyncio.run(content_nodes.review_branding(_review_state("ad")))[
            "branding_review"
        ]
        assert review["copy_contract_ok"] is False
        assert review["missing_subjects"] == ["board"]
        assert "board" in review["reason"]

    def test_ad_post_rule_violation_is_flagged(self, monkeypatch):
        _patch_review(
            monkeypatch,
            {
                "ok": True,
                "reason": "placement fine",
                "missing_subjects": [],
                "violated_rules": ["chocolate staged beside cured ham"],
            },
        )
        review = asyncio.run(content_nodes.review_branding(_review_state("ad")))[
            "branding_review"
        ]
        assert review["copy_contract_ok"] is False
        assert "chocolate staged beside cured ham" in review["reason"]

    def test_ad_post_is_never_re_rendered(self, monkeypatch):
        # The big headline was placed by the AI planner; re-compositing the
        # glass card would clobber it. A contract breach reports, never repairs.
        _patch_review(
            monkeypatch,
            {
                "ok": False,
                "reason": "card over the pack",
                "new_text_anchor": "bottom-right",
                "missing_subjects": ["board"],
                "violated_rules": [],
            },
        )

        def explode(*args, **kwargs):
            raise AssertionError("ad post must not be re-composited")

        monkeypatch.setattr(content_nodes, "overlay_logo_and_text", explode)
        result = asyncio.run(content_nodes.review_branding(_review_state("ad")))
        assert result["branding_review"]["ok"] is True
        assert "branded_image" not in result

    def test_ad_post_without_a_contract_skips_the_vision_call(self, monkeypatch):
        called = {"n": 0}

        async def fake_vision(*args, **kwargs):
            called["n"] += 1
            return {"ok": True}

        monkeypatch.setattr(content_nodes, "_vision_review_branding", fake_vision)
        state = _review_state("ad")
        state["brand"]["brand_guidelines"] = {"logos": {}}
        state["calendar_item"] = {"content_brief": ""}
        state["hook"] = ""
        result = asyncio.run(content_nodes.review_branding(state))
        assert called["n"] == 0
        assert result["branding_review"] == {
            "ok": True,
            "reason": "ad headline (AI-placed)",
        }

    def test_lifestyle_post_keeps_its_placement_verdict(self, monkeypatch):
        # Strengthening the critic must not disturb the existing approve path.
        _patch_review(
            monkeypatch,
            {
                "ok": True,
                "reason": "card on wall, logo on sky",
                "missing_subjects": [],
                "violated_rules": [],
            },
        )
        review = asyncio.run(content_nodes.review_branding(_review_state("lifestyle")))[
            "branding_review"
        ]
        assert review["ok"] is True
        assert review["copy_contract_ok"] is True

    def test_vision_failure_still_approves(self, monkeypatch):
        _patch_review(monkeypatch, None)
        result = asyncio.run(content_nodes.review_branding(_review_state("lifestyle")))
        assert result["branding_review"] == {"ok": True}
