"""The branded close.

Reels ended on whatever frame the last i2v landed on, with the CTA burned
over it. Every professionally cut product ad closes on the mark — and on a
reel of generated footage, the card is the only frame guaranteed to be
on-brand.

Everything measured here came off a rendered card:
  - The first version put the CTA in a BorderStyle 3 box, which libass draws
    per LINE: a two-line call to action came out as two differently sized
    rectangles in a ragged step.
  - The chip width estimate started at 0.56 em and drew a button nearly
    twice the width of its own label; the measured advance is 0.325.
  - A decorative rule under the lockup landed a second green line directly
    under a wordmark that already carries one.
"""

from workflows.video import nodes

PALETTE = {
    "accent": "#80c020",
    "primary": "#209030",
    "text_dark": "#26332a",
    "neutral_light": "#f4f7f1",
}
BRAND = {"color_palette": PALETTE, "logo_url": "http://backend/logo.png"}


class TestCardGround:
    def test_a_light_brand_neutral_carries_the_dark_mark(self):
        assert nodes._end_card_ground(BRAND) == "#f4f7f1"

    def test_a_neutral_too_dark_for_the_mark_is_rejected(self):
        dark = {"color_palette": {"neutral_light": "#304030",
                                  "text_dark": "#26332a"}}
        # #304030 against #26332a is nowhere near 4.5:1 — the card falls back
        # rather than shipping an unreadable wordmark.
        assert nodes._end_card_ground(dark) == nodes._DEFAULT_CARD_GROUND

    def test_a_brand_with_no_palette_still_gets_a_card(self):
        assert nodes._end_card_ground({}) == nodes._DEFAULT_CARD_GROUND
        assert nodes._end_card_ground(
            {"color_palette": "not json"}
        ) == nodes._DEFAULT_CARD_GROUND

    def test_a_json_string_palette_is_parsed(self):
        import json

        brand = {"color_palette": json.dumps(PALETTE)}
        assert nodes._end_card_ground(brand) == "#f4f7f1"

    def test_the_ground_actually_clears_the_contrast_floor(self):
        from shared.image_processing import contrast_ratio, relative_luminance

        ground = nodes._hex_to_rgb(nodes._end_card_ground(BRAND))
        ink = nodes._hex_to_rgb(PALETTE["text_dark"])
        assert contrast_ratio(
            relative_luminance(ground), relative_luminance(ink)
        ) >= nodes._MIN_END_CARD_CONTRAST


class TestHexParsing:
    def test_round_trip(self):
        assert nodes._hex_to_rgb("#80c020") == (128, 192, 32)
        assert nodes._hex_to_rgb("80C020") == (128, 192, 32)

    def test_junk_is_none(self):
        for junk in (None, "", "tomato", "#fff", "#gggggg", "#80c0201"):
            assert nodes._hex_to_rgb(junk) is None


class TestChipGeometry:
    def test_a_one_line_button_is_one_rectangle(self):
        doc = nodes._end_card_ass("Shop now", "#f4f7f1", "#80c020")
        drawings = [ln for ln in doc.splitlines() if "\\p1}" in ln]
        assert len(drawings) == 1, "one chip, whatever the line count"

    def test_a_two_line_button_is_still_one_rectangle(self):
        doc = nodes._end_card_ass(
            "Shop the whole certified organic range", "#f4f7f1", "#80c020"
        )
        drawings = [ln for ln in doc.splitlines() if "\\p1}" in ln]
        assert len(drawings) == 1, (
            "BorderStyle 3 boxed each line separately and stepped"
        )

    def test_the_chip_grows_with_the_line_count_not_the_word_count(self):
        one = nodes._end_card_chip_box("Shop now")
        two = nodes._end_card_chip_box("Shop the\\Npantry range")
        assert two[1] == one[1] + nodes._END_CARD_CHIP_LINE_H

    def test_the_chip_is_wider_than_its_label_but_not_absurdly(self):
        label = "Shop the pantry range"
        width, _ = nodes._end_card_chip_box(label)
        ink = len(label) * nodes._END_CARD_FONT_SIZE * nodes._END_CARD_CHAR_EM
        assert width > ink, "no padding at all"
        assert width < ink * 1.6, "the button dwarfs its own label"

    def test_a_very_long_cta_is_capped(self):
        width, _ = nodes._end_card_chip_box("x" * 200)
        assert width == nodes._END_CARD_CHIP_MAX_W
        assert width <= nodes._SAFE_RIGHT - nodes._SAFE_LEFT + 200

    def test_the_chip_stays_inside_the_frame(self):
        for cta in ("Go", "Shop the pantry range", "x" * 60):
            width, _ = nodes._end_card_chip_box(
                nodes._wrap_overlay_text(cta, nodes._END_CARD_CTA_WRAP)
            )
            assert 540 - width // 2 >= 0
            assert 540 + width // 2 <= 1080

    def test_the_measured_advance_is_used_not_the_first_guess(self):
        # 0.56 was a guess and drew a button ~1.7x its label.
        assert 0.30 <= nodes._END_CARD_CHAR_EM <= 0.40


class TestCardLayout:
    def test_the_lockup_is_centred_on_the_safe_band_not_the_frame(self):
        block_top = nodes._END_CARD_LOGO_Y
        _, chip_h = nodes._end_card_chip_box("Shop now")
        block_bottom = nodes._END_CARD_CTA_Y + chip_h // 2
        centre = (block_top + block_bottom) / 2
        safe_centre = (nodes._SAFE_TOP + nodes._SAFE_BOTTOM) / 2
        assert abs(centre - safe_centre) <= 60

    def test_nothing_lands_under_the_platform_chrome(self):
        _, chip_h = nodes._end_card_chip_box("Shop the pantry range")
        assert nodes._END_CARD_CTA_Y + chip_h // 2 <= nodes._SAFE_BOTTOM
        assert nodes._END_CARD_LOGO_Y >= nodes._SAFE_TOP

    def test_the_mark_clears_the_action_rail(self):
        assert 540 + nodes._END_CARD_LOGO_BOX_W // 2 <= nodes._SAFE_RIGHT + 60

    def test_no_decorative_rule_is_drawn(self):
        # The logo carries its own; a second one read as a mistake.
        cmd = nodes._end_card_cmd(
            "/o.mp4", "/c.ass", "/logo.png", "#f4f7f1", "/fonts"
        )
        assert "[rule]" not in " ".join(cmd)


class TestCardEncode:
    def _cmd(self, logo="/logo.png"):
        return nodes._end_card_cmd(
            "/o.mp4", "/c.ass", logo, "#f4f7f1", "/fonts"
        )

    def test_the_card_matches_the_concat_master_spec(self):
        cmd = self._cmd()
        for arg in nodes._MASTER_VIDEO_ARGS + nodes._MASTER_AUDIO_ARGS:
            assert arg in cmd
        joined = " ".join(cmd)
        assert "1080x1920" in joined
        assert "format=yuv420p" in joined
        assert "fps=30" in joined

    def test_the_card_carries_a_silent_track_so_concat_can_splice_it(self):
        joined = " ".join(self._cmd())
        assert "anullsrc" in joined
        # The music bed laid down afterwards covers the card.
        assert "1:a:0" in self._cmd()

    def test_the_mark_is_fitted_into_a_fixed_box(self):
        # Scaling to a width alone leaves everything below at an unknown y.
        joined = " ".join(self._cmd())
        assert "force_original_aspect_ratio=decrease" in joined
        assert f"pad={nodes._END_CARD_LOGO_BOX_W}:{nodes._END_CARD_LOGO_BOX_H}" \
            in joined

    def test_a_brand_with_no_logo_still_renders_a_card(self):
        cmd = self._cmd(logo=None)
        assert "[0:v]null[a]" in " ".join(cmd)
        assert cmd.count("-i") == 2  # colour + anullsrc, no logo input

    def test_the_card_is_exactly_its_declared_length(self):
        cmd = self._cmd()
        assert cmd[cmd.index("-t") + 1] == str(nodes._END_CARD_S)


class TestCtaOwnership:
    def test_the_cta_moves_off_the_footage_when_a_card_exists(self):
        import inspect

        src = inspect.getsource(nodes.render_video)
        # The burn is handed "" for the CTA when a card was built, so the
        # final beat keeps its own line and the ask lands on the mark.
        assert '"" if card_path else cta_text' in src

    def test_the_card_is_built_before_the_burn_on_both_paths(self):
        import inspect

        src = inspect.getsource(nodes.render_video)
        # Deciding afterwards would mean either a reel with no ask, or
        # burning the overlays twice to add one back — which double-darkens
        # every scrim. Both render paths build first.
        builds = [
            i for i in range(len(src))
            if src.startswith("_build_end_card(", i)
        ]
        burns = [
            i for i in range(len(src))
            if src.startswith("_burn_overlays(", i)
        ]
        assert len(builds) == 2, "both render paths must build a card"
        assert len(burns) == 2
        for build, burn in zip(builds, burns):
            assert build < burn

    def test_both_paths_attach_the_card_they_built(self):
        import inspect

        src = inspect.getsource(nodes.render_video)
        assert src.count("_attach_end_card(") == 2
