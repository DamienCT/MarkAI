"""An image prompt must not hand the model anything it can typeset.

Two independent bake-off runs found the same failure: strong open-weights models
read the app's marketing brief as a DESIGN brief and returned a finished poster
— fabricated wordmarks in the "reserved" logo corner, caption bars typesetting
the prompt's own Theme line and hex codes, solid colour panels taking half the
canvas. One model set a headline perfectly legibly, which is worse than gibberish
because competent fake client branding looks shippable.

gpt-image-2 ignored all of it, so it went unnoticed. Fixing prompt assembly alone
— same model, sampler, steps, cfg and seeds — moved one candidate from median
24.12/40 with a 50% publish rate to median 35.25/40 at 90%.

These tests pin the three rules that came out of that:
  1. no hex colour codes anywhere in an image prompt
  2. no brand NAME (it is a word; models render words)
  3. no logo/overlay/reserved vocabulary describing the composition
"""

import asyncio
import re

import pytest

from workflows.content import nodes

_HEX = re.compile(r"#[0-9a-fA-F]{3,6}")
# Words that describe the compositor's intent rather than the photograph.
_LAYOUT_INTENT = ("reserved for", "logo overlay", "text overlay")

BRAND = {
    "name": "Naturespan",
    "color_palette": {
        "primary": "#1F6B3B",
        "secondary": "#8CC63F",
        "accent": "#E8DCC8",
    },
    "brand_guidelines": {
        "visual_style": "clean, natural, documentary",
        "target_audience": "Mauritian families",
    },
}


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    """Capture the prompt generate_background actually sends.

    The assembly is inline in the node, so the honest way to test it is to run
    the real node with the image call stubbed — that way the test cannot drift
    from the string production sends.
    """
    seen = {"format": "lifestyle"}

    async def fake_generate_image(prompt, **kwargs):
        seen["prompt"] = prompt
        return "content-images/x/y/background.png"

    async def fake_step(*_a, **_k):
        return None

    # _decide_image_format() balances ad/lifestyle GLOBALLY from the database,
    # so the branch is not a property of the item. Drive it explicitly here or
    # the ad branch never gets exercised — and stub the run-step write, which
    # otherwise spends a connect timeout per call against a database the test
    # environment has no business reaching.
    async def fake_format():
        return seen["format"]

    monkeypatch.setattr(nodes, "generate_image", fake_generate_image)
    monkeypatch.setattr(nodes, "update_agent_run_step", fake_step)
    monkeypatch.setattr(nodes, "_decide_image_format", fake_format)
    _capture.seen = seen
    return seen


def _build(item, brand=None, image_format="lifestyle"):
    """Render an image prompt through the real assembly path."""
    _capture.seen["format"] = image_format
    state = {
        "brand": brand or BRAND,
        "calendar_item": item,
        "brand_id": "b" * 8,
    }
    result = asyncio.run(nodes.generate_background(state))
    assert result.get("generated_image"), "node did not reach the image call"
    return _capture.seen["prompt"]


@pytest.fixture
def items():
    base = {
        "channel": "instagram",
        "theme": "Indulgent Everyday Pairings & Social Treat Moments",
        "title": "Real brands, real proof on pack",
    }
    # (item, image_format) — the three assembly branches that differ: ad,
    # lifestyle-only, and the generic-placeholder branch used when a product
    # will be swapped in later.
    return {
        "ad": ({**base, "content_brief": "A sharing board."}, "ad"),
        "lifestyle": (
            {**base, "content_brief": "A family walking a coastal path.",
             "is_lifestyle_only": True},
            "lifestyle",
        ),
        "placeholder": ({**base, "content_brief": "A pantry shelf at home."},
                        "lifestyle"),
        "no_brief": ({**base}, "lifestyle"),
    }


class TestNoHexInImagePrompts:
    def test_every_branch_is_hex_free(self, items):
        for name, (item, fmt) in items.items():
            prompt = _build(item, image_format=fmt)
            found = _HEX.findall(prompt)
            assert not found, f"{name} branch leaked hex {found}"

    def test_palette_still_reaches_the_prompt_as_words(self, items):
        prompt = _build(*items["lifestyle"][:1], image_format="lifestyle").lower()
        assert "forest green" in prompt
        assert "sand" in prompt


class TestNoBrandNameInImagePrompts:
    def test_brand_name_absent_from_every_branch(self, items):
        for name, (item, fmt) in items.items():
            assert "Naturespan" not in _build(item, image_format=fmt), (
                f"{name} branch put the brand NAME in an image prompt — "
                "models typeset it as a wordmark"
            )

    def test_a_brand_named_like_a_common_word_still_absent(self, items):
        brand = {**BRAND, "name": "Harvest"}
        assert "Harvest" not in _build(items["lifestyle"][0], brand)


class TestNoLayoutIntentLanguage:
    def test_composition_never_names_a_logo_or_overlay(self, items):
        for name, (item, fmt) in items.items():
            low = _build(item, image_format=fmt).lower()
            for phrase in _LAYOUT_INTENT:
                assert phrase not in low, f"{name} branch still says {phrase!r}"

    def test_the_quiet_regions_are_still_requested(self, items):
        # The geometry the compositor depends on must survive the rewording.
        low = _build(items["lifestyle"][0], image_format="lifestyle").lower()
        assert "upper-right" in low and "lower-left" in low

    def test_poster_failure_mode_is_negatively_prompted(self, items):
        low = _build(items["lifestyle"][0], image_format="lifestyle").lower()
        for term in ("poster", "wordmark", "caption bar", "colour panel", "sidebar"):
            assert term in low, f"negative prompt does not mention {term!r}"


class TestThemeIsContextNotSubject:
    def test_theme_is_marked_as_context_and_never_bare(self, items):
        for name, (item, fmt) in items.items():
            prompt = _build(item, image_format=fmt)
            if "Indulgent Everyday Pairings" not in prompt:
                continue
            assert "Theme: Indulgent" not in prompt, (
                f"{name} branch passes the theme as a bare label to typeset"
            )
            assert "context" in prompt.lower()

    def test_missing_theme_emits_nothing(self, items):
        item = {k: v for k, v in items["lifestyle"][0].items() if k != "theme"}
        prompt = _build(item)
        assert "Campaign context" not in prompt
