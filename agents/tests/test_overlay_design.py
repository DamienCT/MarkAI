"""Burned type must stay inside platform chrome and stay legible.

Measured from rendered reels:
  - \\an5-centred type at (540,1130) put a ~950px line out to x=1015, which is
    75px under the Reels action rail, and the 1015..1245 band is where a 9:16
    product shot puts the bottle and the faces. Lines sat on an olive-oil
    label and across a presenter's chest.
  - White fill with a 4px outline over a pale wall was barely readable:
    "Certified organic matters" measured 190,162,140 behind white glyphs.
  - The CTA was painted in the raw brand accent. Naturespan's is a saturated
    lime that shipped as bright green letters over a warm brown dinner scene.
"""

import re

import pytest

from workflows.video import nodes

EVENTS = [
    {"text": "Certified organic matters", "style": "Overlay", "start": 1.0, "end": 5.0},
    {"text": "Shop pantry now", "style": "CTA", "start": 6.0, "end": 9.0},
]


@pytest.fixture
def doc():
    return nodes._build_overlay_ass(EVENTS, "#80c020")


class TestSafeArea:
    def test_type_is_bottom_left_anchored_not_centred(self, doc):
        # Alignment 1 = bottom-left. Centre anchoring grows the block in BOTH
        # directions, so any added line walks it toward the chrome.
        for style in ("Overlay", "CTA"):
            line = next(l for l in doc.splitlines() if l.startswith(f"Style: {style},"))
            assert line.rstrip().split(",")[18] == "1", f"{style} is not \\an1"
        assert "\\an1" in doc and "\\an5" not in doc

    def test_the_right_margin_clears_the_action_rail(self):
        assert 1080 - nodes._SAFE_RIGHT >= 180, (
            "the Reels/TikTok/Shorts action rail is up to 180px wide"
        )

    def test_the_bottom_margin_clears_the_caption_block(self):
        assert 1920 - nodes._SAFE_BOTTOM >= 480, (
            "caption + handle + audio row runs to ~483px on TikTok"
        )

    def test_margins_in_the_style_match_the_safe_constants(self, doc):
        line = next(l for l in doc.splitlines() if l.startswith("Style: Overlay,"))
        fields = line.split(",")
        assert int(fields[19]) == nodes._SAFE_LEFT
        assert int(fields[20]) == 1080 - nodes._SAFE_RIGHT
        assert int(fields[21]) == 1920 - nodes._SAFE_BOTTOM

    def test_the_anchor_sits_on_the_safe_baseline(self, doc):
        # \move(x, y0, x, y1, ...) — the settled position is the second pair.
        move = re.search(r"\\move\((\d+),(\d+),(\d+),(\d+),", doc)
        assert move, "no settle animation found"
        assert int(move.group(3)) == nodes._SAFE_LEFT
        assert int(move.group(4)) == nodes._SAFE_BOTTOM
        # and it travels upward, so it never dips into the bottom chrome
        assert int(move.group(2)) > int(move.group(4))


class TestScrim:
    def test_every_line_gets_a_plate_under_it(self, doc):
        dialogues = [l for l in doc.splitlines() if l.startswith("Dialogue:")]
        scrims = [l for l in dialogues if ",Scrim,," in l]
        assert len(scrims) == len(EVENTS), "one plate per line"

    def test_the_plate_is_emitted_before_its_text(self, doc):
        """libass draws same-layer events in file order."""
        dialogues = [l for l in doc.splitlines() if l.startswith("Dialogue:")]
        for i, line in enumerate(dialogues):
            if ",Scrim,," in line:
                assert i + 1 < len(dialogues) and ",Scrim,," not in dialogues[i + 1]

    def test_the_plate_covers_the_type_band(self, doc):
        draw = re.search(r"\\p1\}m 0 (\d+) l 1080 \1 1080 1920 0 1920", doc)
        assert draw, "scrim drawing missing or malformed"
        assert int(draw.group(1)) <= nodes._SAFE_BOTTOM, (
            "the plate must start above the text baseline"
        )

    def test_the_plate_is_translucent_and_feathered(self, doc):
        assert "\\1a&H%s&" % nodes._SCRIM_ALPHA_HEX in doc
        assert "\\blur" in doc, "a hard rectangle reads as a lower-third bar"

    def test_the_plate_is_not_opaque(self):
        # 0x00 would be fully opaque and hide the footage entirely.
        assert 0x30 < int(nodes._SCRIM_ALPHA_HEX, 16) < 0xC0


class TestCTAContrast:
    def test_a_saturated_accent_is_rejected(self):
        # Naturespan's lime measures ~2.1:1 against the scrim's worst backdrop.
        assert nodes._cta_primary_colour("#80c020") == "&H00FFFFFF"

    def test_no_accent_configured_falls_back_to_white(self):
        assert nodes._cta_primary_colour(None) == "&H00FFFFFF"
        assert nodes._cta_primary_colour("not-a-hex") == "&H00FFFFFF"

    def test_a_light_accent_survives(self):
        # Pale yellow clears the floor against a mid-grey backdrop.
        assert nodes._cta_primary_colour("#FFF8B0") != "&H00FFFFFF"

    def test_the_floor_is_wcag_large_text_and_achievable(self):
        from shared.image_processing import contrast_ratio, relative_luminance

        assert nodes._MIN_CTA_CONTRAST >= 3.0, "below the large-text standard"
        # The floor must also be reachable, or the check is "always white".
        ceiling = contrast_ratio(
            relative_luminance((255, 255, 255)),
            relative_luminance(nodes._SCRIM_WORST_BACKDROP),
        )
        assert nodes._MIN_CTA_CONTRAST < ceiling, (
            f"nothing can exceed {ceiling:.2f}:1 against the scrim, so this "
            "floor would reject every colour including near-white"
        )


class TestFullLineSurvives:
    def test_the_line_that_lost_pour_is_whole_in_the_document(self):
        doc = nodes._build_overlay_ass(
            [{"text": "Dinner starts with a clean pour", "style": "Overlay",
              "start": 0.4, "end": 4.6}],
            "#80c020",
        )
        text = doc.split(",Overlay,,0,0,0,,")[1]
        assert "pour" in text
