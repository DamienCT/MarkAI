"""Burned type must stay inside platform chrome and stay legible.

Measured from rendered reels:
  - \\an5-centred type at (540,1130) put a ~950px line out to x=1015, which is
    75px under the Reels action rail, and the 1015..1245 band is where a 9:16
    product shot puts the bottle and the faces. Lines sat on an olive-oil
    label and across a presenter's chest.
  - White fill with a 4px outline over a pale wall was barely readable:
    "Certified organic matters" measured 190,162,140 behind white glyphs.
  - The half-frame scrim that replaced the outline darkened the bottom 49% of
    the picture behind EVERY caption (163 → 87 mean luma and back at each
    boundary). The user reported it verbatim: "dark screen then light screen
    without overlay... its a mess". The backdrop is now a rounded card sized
    to the words — nothing outside the words' own footprint changes.
"""

import re

import pytest

from workflows.video import nodes

EVENTS = [
    {"text": "Certified organic matters", "style": "Overlay", "start": 1.0, "end": 5.0},
    {"text": "Shop pantry now", "style": "CTA", "start": 6.0, "end": 9.0},
]

HOOK_EVENTS = [
    {"text": "Dinner starts here", "style": "Hook", "start": 0.35, "end": 3.55},
]


@pytest.fixture
def doc():
    return nodes._build_overlay_ass(EVENTS, "#80c020")


class TestSafeArea:
    def test_body_type_is_bottom_left_anchored(self, doc):
        # Alignment 1 = bottom-left. Centre anchoring grows the block in BOTH
        # directions, so any added line walks it toward the chrome. The hook
        # is the deliberate exception: \an5 high-centre, far above the chrome.
        for style in ("Overlay", "CTA"):
            line = next(ln for ln in doc.splitlines() if ln.startswith(f"Style: {style},"))
            assert line.rstrip().split(",")[18] == "1", f"{style} is not \\an1"
        assert "\\an1" in doc

    def test_the_hook_is_high_centre_clear_of_product_and_chrome(self):
        doc = nodes._build_overlay_ass(HOOK_EVENTS, None)
        assert "\\an5" in doc
        cx, cy = nodes._HOOK_POS
        assert cx == 540
        # Below the top chrome, above where a 9:16 product shot centres the
        # bottle (~y960).
        assert nodes._SAFE_TOP < cy < 900

    def test_the_right_margin_clears_the_action_rail(self):
        assert 1080 - nodes._SAFE_RIGHT >= 180, (
            "the Reels/TikTok/Shorts action rail is up to 180px wide"
        )

    def test_the_bottom_margin_clears_the_caption_block(self):
        assert 1920 - nodes._SAFE_BOTTOM >= 480, (
            "caption + handle + audio row runs to ~483px on TikTok"
        )

    def test_margins_in_the_style_match_the_safe_constants(self, doc):
        line = next(ln for ln in doc.splitlines() if ln.startswith("Style: Overlay,"))
        fields = line.split(",")
        assert int(fields[19]) == nodes._SAFE_LEFT
        assert int(fields[20]) == 1080 - nodes._SAFE_RIGHT
        assert int(fields[21]) == 1920 - nodes._SAFE_BOTTOM

    def test_the_anchor_sits_on_the_safe_baseline(self, doc):
        # \move(x, y0, x, y1, ...) — the settled position is the second pair.
        # The card's own \move runs from (0,rise) to (0,0), so scan the TEXT
        # dialogues only.
        text_lines = [
            ln for ln in doc.splitlines()
            if ln.startswith("Dialogue:") and ",Card,," not in ln
        ]
        move = re.search(r"\\move\((\d+),(\d+),(\d+),(\d+),", text_lines[0])
        assert move, "no settle animation found"
        assert int(move.group(3)) == nodes._SAFE_LEFT
        assert int(move.group(4)) == nodes._SAFE_BOTTOM
        # and it travels upward, so it never dips into the bottom chrome
        assert int(move.group(2)) > int(move.group(4))


class TestCaptionCard:
    def test_every_beat_gets_a_card_under_it(self, doc):
        dialogues = [ln for ln in doc.splitlines() if ln.startswith("Dialogue:")]
        cards = [ln for ln in dialogues if ",Card,," in ln]
        assert len(cards) == len(EVENTS), "one card per beat"

    def test_the_card_is_on_the_layer_below_its_text(self, doc):
        dialogues = [ln for ln in doc.splitlines() if ln.startswith("Dialogue:")]
        for line in dialogues:
            layer = int(line.split(":", 1)[1].split(",", 1)[0])
            assert layer == (0 if ",Card,," in line else 1)

    def test_the_card_hugs_the_words_not_the_frame(self, doc):
        # The old scrim ran the full 1080px width from y=980 to the bottom of
        # the frame. A card is sized to its text: its drawing never spans the
        # full frame width and never reaches the frame bottom.
        for line in doc.splitlines():
            if ",Card,," not in line:
                continue
            xs = [int(m) for m in re.findall(r"[ml] (\d+) ", line)]
            ys = [int(m) for m in re.findall(r"[ml] \d+ (\d+)", line)]
            assert max(xs) - min(xs) < 1080, "card spans the full frame width"
            assert max(ys) < 1700, "card reaches into the bottom chrome"

    def test_the_card_is_translucent_not_opaque(self, doc):
        assert f"\\1a&H{nodes._CARD_ALPHA_HEX}&" in doc
        assert 0x20 < int(nodes._CARD_ALPHA_HEX, 16) < 0xC0

    def test_the_card_moves_and_fades_with_its_text(self, doc):
        # A backdrop on a different clock than its words is the choppiness
        # the scrim was rejected for.
        for line in doc.splitlines():
            if ",Card,," in line:
                assert f"\\fad({nodes._FADE_IN_MS},{nodes._FADE_OUT_MS})" in line
                assert "\\move(" in line

    def test_rounded_corners_are_real_beziers(self):
        path = nodes._rounded_rect_path(100, 200, 400, 120, 30)
        assert path.startswith("m 130 200 ")
        assert path.count(" b ") == 4, "four rounded corners"
        # The path never strays outside its own box.
        xs = [int(m) for m in re.findall(r"(?:^|\s)(\d+) \d+(?:\s|$)", path)]
        assert min(xs) >= 100 and max(xs) <= 500


class TestCardGeometry:
    def test_bottom_left_block_sits_above_its_anchor(self):
        x, y, w, h = nodes._card_geometry(
            "Certified organic,\\Nevery bottle", nodes._OVERLAY_FONT_SIZE,
            "bl", (nodes._OVERLAY_POS_X, nodes._OVERLAY_POS_Y),
        )
        assert x == nodes._OVERLAY_POS_X - nodes._CARD_PAD_X
        assert y + h == pytest.approx(nodes._OVERLAY_POS_Y + nodes._CARD_PAD_Y)
        line_h = int(round(nodes._OVERLAY_FONT_SIZE * nodes._LINE_HEIGHT_EM))
        assert h == 2 * line_h + 2 * nodes._CARD_PAD_Y

    def test_centered_block_straddles_its_anchor(self):
        cx, cy = nodes._HOOK_POS
        x, y, w, h = nodes._card_geometry(
            "Dinner starts here", nodes._HOOK_FONT_SIZE, "center", (cx, cy)
        )
        assert x < cx < x + w
        assert y < cy < y + h
        assert abs((x + w / 2) - cx) <= 1

    def test_width_tracks_the_widest_line(self):
        narrow = nodes._card_geometry("iii", 76, "bl", (80, 1420))
        wide = nodes._card_geometry("WWW", 76, "bl", (80, 1420))
        assert wide[2] > narrow[2]


class TestCTAContrast:
    def test_a_low_contrast_accent_is_rejected(self):
        # Mid-grey reads ~1.6:1 against the card's worst backdrop.
        assert nodes._cta_primary_colour("#555555") == "&H00FFFFFF"

    def test_no_accent_configured_falls_back_to_white(self):
        assert nodes._cta_primary_colour(None) == "&H00FFFFFF"
        assert nodes._cta_primary_colour("not-a-hex") == "&H00FFFFFF"

    def test_a_bright_accent_survives_on_the_dark_card(self):
        # Naturespan's lime was unreadable on the old mid-grey scrim backdrop
        # (2.1:1) but clears the floor against the near-black card (3.9:1) —
        # bright-on-dark is exactly what the card buys.
        assert nodes._cta_primary_colour("#80c020") != "&H00FFFFFF"

    def test_the_floor_is_wcag_large_text_and_achievable(self):
        from shared.image_processing import contrast_ratio, relative_luminance

        assert nodes._MIN_CTA_CONTRAST >= 3.0, "below the large-text standard"
        # The floor must also be reachable, or the check is "always white".
        ceiling = contrast_ratio(
            relative_luminance((255, 255, 255)),
            relative_luminance(nodes._CARD_WORST_BACKDROP),
        )
        assert nodes._MIN_CTA_CONTRAST < ceiling, (
            f"nothing can exceed {ceiling:.2f}:1 against the card, so this "
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
