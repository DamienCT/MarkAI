"""The picture grade, calibrated against this app's own gold-standard stills.

"The videos are not great" stayed an impression for several cycles. It is now
a measurement, taken two ways with the same tool (ffmpeg signalstats):

  30 gpt-image-2 stills sampled from the gallery — the reference the operator
  named as the quality bar — measure, as medians:

      YLOW 60      YAVG 140      YHIGH 214      SATAVG 19.2

  A delivered 7-shot Naturespan reel, sampled once per second:

      YLOW 26      YAVG  91      YHIGH 194      SATAVG 10.4

The footage is about 35% darker than the stills and carries roughly half
their colour, and none of it clips — YHIGH never reaches even 235, and decays
to 139 across the closing shots as the i2v chain washes contrast out. The
headroom to fix it was simply unused.

Every number in this file is one of those measurements.
"""

import pytest

from workflows.video import nodes


# Gold standard: medians over 30 gpt-image-2 stills.
GOLD_YAVG = 140.0
GOLD_SATAVG = 19.2
GOLD_YHIGH = 214.0

# The delivered reel, per second. Opening and closing shown separately
# because the decay across the reel is the reason the grade is per shot.
REEL_OPENING = {"YAVG": 95.8, "YHIGH": 201.0, "YLOW": 32.0, "SATAVG": 11.0}
REEL_MIDDLE = {"YAVG": 91.3, "YHIGH": 193.0, "YLOW": 24.0, "SATAVG": 9.6}
REEL_CLOSING = {"YAVG": 80.8, "YHIGH": 139.0, "YLOW": 30.0, "SATAVG": 12.0}


class TestTheTargetsAreTheMeasurements:
    def test_the_luma_target_is_the_stills_median(self):
        assert nodes._GRADE_TARGET_YAVG == pytest.approx(GOLD_YAVG, abs=1.0)

    def test_the_saturation_target_is_the_stills_median(self):
        assert nodes._GRADE_TARGET_SATAVG == pytest.approx(GOLD_SATAVG, abs=1.0)

    def test_the_clipping_ceiling_sits_above_the_stills_highlights(self):
        # Grading a shot INTO the stills' highlight range must not be
        # mistaken for clipping, or the lift backs off on every shot.
        assert nodes._GRADE_MAX_YHIGH > GOLD_YHIGH


class TestGammaMath:
    @pytest.mark.parametrize("measured", (60.0, 80.8, 91.3, 120.0))
    def test_it_lands_the_mean_on_the_target(self, measured):
        g = nodes._gamma_for(measured, GOLD_YAVG)
        landed = 255.0 * (measured / 255.0) ** (1.0 / g)
        assert landed == pytest.approx(GOLD_YAVG, abs=0.5)

    def test_a_shot_already_on_target_needs_no_lift(self):
        assert nodes._gamma_for(GOLD_YAVG, GOLD_YAVG) == pytest.approx(1.0)

    def test_degenerate_inputs_are_a_no_op_not_a_crash(self):
        for bad in (0.0, -5.0, 255.0, 300.0):
            assert nodes._gamma_for(bad, GOLD_YAVG) == 1.0
            assert nodes._gamma_for(100.0, bad) == 1.0


def _apply(stats, p, key):
    """Where *key* lands after the black point and gamma this grade sets."""
    lifted = nodes._black_point(float(stats[key]), float(p.get("black") or 0.0))
    return 255.0 * (lifted / 255.0) ** (1.0 / p["gamma"])


class TestGradeParams:
    def test_the_measured_reel_is_lifted_toward_the_stills(self):
        p = nodes._grade_params(REEL_MIDDLE)
        assert p is not None
        assert _apply(REEL_MIDDLE, p, "YAVG") == pytest.approx(
            GOLD_YAVG, abs=2.0
        )

    def test_and_its_colour_is_brought_back(self):
        p = nodes._grade_params(REEL_MIDDLE)
        landed = REEL_MIDDLE["SATAVG"] * p["saturation"]
        assert landed == pytest.approx(GOLD_SATAVG, abs=1.0)

    def test_the_flattest_closing_shot_is_lifted_hardest(self):
        opening = nodes._grade_params(REEL_OPENING)
        closing = nodes._grade_params(REEL_CLOSING)
        assert closing["gamma"] > opening["gamma"], (
            "a global curve would leave the decayed shots flat — this is "
            "why the grade is per shot"
        )

    def test_a_shot_already_matching_the_stills_is_left_alone(self):
        on_target = {"YAVG": GOLD_YAVG, "YHIGH": GOLD_YHIGH,
                     "SATAVG": GOLD_SATAVG}
        assert nodes._grade_params(on_target) is None

    def test_a_brighter_than_gold_shot_is_never_darkened(self):
        # A high-key beat is a decision, not a defect.
        bright = {"YAVG": 190.0, "YHIGH": 240.0, "SATAVG": GOLD_SATAVG}
        p = nodes._grade_params(bright)
        assert p is None or p["gamma"] == 1.0

    def test_an_unmeasurable_shot_is_never_graded(self):
        # None means ffmpeg failed. Treating that as "black" would blow a
        # perfectly good shot out.
        assert nodes._grade_params(None) is None
        assert nodes._grade_params({}) is None
        assert nodes._grade_params({"YAVG": 0.0}) is None

    def test_a_nearly_black_shot_cannot_be_lifted_without_bound(self):
        p = nodes._grade_params({"YAVG": 4.0, "YHIGH": 20.0, "SATAVG": 1.0})
        assert p["gamma"] <= nodes._GRADE_MAX_GAMMA
        assert p["saturation"] <= nodes._GRADE_MAX_SATURATION

    def test_highlights_are_protected_from_clipping(self):
        # Dark overall but with a hot specular already near the top — the
        # oil-and-glass case. The lift must back off rather than burn it.
        hot = {"YAVG": 70.0, "YHIGH": 232.0, "YLOW": 20.0, "SATAVG": 12.0}
        p = nodes._grade_params(hot)
        assert _apply(hot, p, "YHIGH") <= nodes._GRADE_MAX_YHIGH

    def test_a_grey_shot_is_saturated_but_not_beyond_the_cap(self):
        p = nodes._grade_params({"YAVG": GOLD_YAVG, "YHIGH": GOLD_YHIGH,
                                 "SATAVG": 2.0})
        assert p["saturation"] == nodes._GRADE_MAX_SATURATION
        assert p["gamma"] == 1.0


class TestGradeChain:
    PARAMS = [
        {"gamma": 1.6, "saturation": 1.8},
        None,
        {"gamma": 1.2, "saturation": 1.1},
    ]
    DURATIONS = [5.0, 3.0, 4.0]

    def test_each_graded_shot_gets_its_own_time_window(self):
        chain = nodes._grade_chain(self.PARAMS, self.DURATIONS)
        assert chain.count("eq=") == 2
        # Shot 1 spans 0-5s, shot 3 spans 8-12s. Shot 2 is untouched.
        assert "between(t\\,0.000\\," in chain
        assert "between(t\\,8.000\\," in chain
        assert "between(t\\,5.000\\," not in chain

    def test_the_windows_do_not_overlap_on_the_boundary(self):
        chain = nodes._grade_chain(
            [{"gamma": 1.5, "saturation": 1.0}] * 2, [4.0, 4.0]
        )
        assert "between(t\\,0.000\\,3.999)" in chain
        assert "between(t\\,4.000\\,7.999)" in chain

    def test_the_expression_is_escaped_not_quoted(self):
        """Verified against ffmpeg 6, not inferred from the docs.

        `enable='between(t,0,3)'` is the form the ffmpeg docs show, but the
        docs are showing a SHELL command line: the shell consumes the quotes
        and the filtergraph parser then splits on the commas, failing with
        "No such filter: '0'". Passed as one argv element the quotes survive
        to the expression evaluator and break it there instead. Escaped
        commas with no quotes is the form that initialises.
        """
        chain = nodes._grade_chain(
            [{"gamma": 1.5, "saturation": 1.0}], [4.0]
        )
        assert "enable=between(" in chain
        assert "'" not in chain

    def test_nothing_to_grade_produces_no_filter(self):
        assert nodes._grade_chain([None, None], [4.0, 4.0]) == ""
        assert nodes._grade_chain([], []) == ""

    def test_a_short_params_list_never_indexes_off_the_end(self):
        # Defensive: a dropped shot must not raise mid-render.
        assert nodes._grade_chain([None], [4.0, 4.0, 4.0]) == ""


class TestItRidesAlongInTheBurn:
    def test_the_grade_runs_before_the_subtitles(self):
        cmd = nodes._burn_cmd("in.mp4", "ov.ass", "out.mp4",
                              grade="eq=gamma=1.5")
        vf = cmd[cmd.index("-vf") + 1]
        # Captions were designed at a chosen colour and contrast; lifting
        # them along with the footage would undo that design.
        assert vf.index("eq=gamma=1.5") < vf.index("ass=")

    def test_no_grade_leaves_the_filter_chain_as_it_was(self):
        cmd = nodes._burn_cmd("in.mp4", "ov.ass", "out.mp4")
        vf = cmd[cmd.index("-vf") + 1]
        assert vf.startswith("ass=")
        assert "eq=" not in vf

    def test_a_grade_with_no_subtitles_still_encodes(self):
        cmd = nodes._burn_cmd("in.mp4", None, "out.mp4", grade="eq=gamma=1.5")
        vf = cmd[cmd.index("-vf") + 1]
        assert vf == "eq=gamma=1.5,fps=30,format=yuv420p"

    def test_neither_still_produces_a_valid_chain(self):
        cmd = nodes._burn_cmd("in.mp4", None, "out.mp4")
        vf = cmd[cmd.index("-vf") + 1]
        assert vf == "fps=30,format=yuv420p"
        assert not vf.startswith(",")

    def test_the_master_spec_is_still_applied(self):
        cmd = nodes._burn_cmd("in.mp4", "ov.ass", "out.mp4",
                              grade="eq=gamma=1.5")
        assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy"
        assert "+faststart" in cmd


class TestPictureMeasurement:
    def test_it_parses_the_keys_it_needs(self):
        stderr = "\n".join([
            "lavfi.signalstats.YAVG=90.5",
            "lavfi.signalstats.YHIGH=194.0",
            "lavfi.signalstats.YLOW=26.0",
            "lavfi.signalstats.SATAVG=10.4",
            "lavfi.signalstats.YAVG=92.5",
            "lavfi.signalstats.YHIGH=196.0",
            "lavfi.signalstats.YLOW=28.0",
            "lavfi.signalstats.SATAVG=10.8",
        ])
        out = nodes._picture_from_stderr(stderr)
        assert out["YAVG"] == pytest.approx(91.5)
        assert out["SATAVG"] == pytest.approx(10.6)

    def test_nothing_parsed_is_unknown_not_black(self):
        assert nodes._picture_from_stderr("") is None
        assert nodes._picture_from_stderr("ffmpeg version 6.1") is None

    def test_the_analysis_pass_encodes_nothing(self):
        cmd = nodes._picture_cmd("/tmp/shot.mp4")
        assert cmd[-3:] == ["-f", "null", "-"]
        assert "-an" in cmd
        assert f"scale={nodes._GRADE_ANALYSIS_W}:-2" in " ".join(cmd)
        # tblend would turn this into a motion measurement, not a tone one.
        assert "tblend" not in " ".join(cmd)


class TestTheBlackPointStopsTheWash:
    """Gamma alone cannot land both the mean and the shadows.

    The first graded pass proved it on real footage: lifting the reel from
    YAVG 92.8 to 132.8 also dragged YLOW from 31.5 to 72.6 against the
    stills' 60. Thirteen points of raised black is what "washed out" looks
    like, and it was visible on the contact sheet. Subtracting a black point
    before the gamma gives a second control, and two controls land two
    targets.
    """

    REEL_BODY = {"YAVG": 92.8, "YHIGH": 186.5, "YLOW": 31.5, "SATAVG": 11.1}

    def test_all_three_tonal_landmarks_land_on_the_stills(self):
        p = nodes._grade_params(self.REEL_BODY)
        assert _apply(self.REEL_BODY, p, "YLOW") == pytest.approx(60.0, abs=2.0)
        assert _apply(self.REEL_BODY, p, "YAVG") == pytest.approx(140.0, abs=2.0)
        # The highlight lands for free — the same curve steepens the top.
        assert _apply(self.REEL_BODY, p, "YHIGH") == pytest.approx(
            GOLD_YHIGH, abs=4.0
        )

    def test_without_the_black_point_the_shadows_would_be_milky(self):
        """The measured regression, stated as the reason the solve exists."""
        p = nodes._grade_params(self.REEL_BODY)
        gamma_only = 255.0 * (self.REEL_BODY["YLOW"] / 255.0) ** (
            1.0 / p["gamma"]
        )
        assert gamma_only > 70.0, "this is the wash the black point removes"
        assert _apply(self.REEL_BODY, p, "YLOW") < gamma_only

    def test_a_shot_with_deep_blacks_already_is_barely_touched(self):
        # YLOW at 8 is a genuinely deep shadow; subtracting much would crush
        # detail that is really there.
        p = nodes._grade_params(
            {"YAVG": 95.0, "YHIGH": 190.0, "YLOW": 8.0, "SATAVG": 11.0}
        )
        assert p["black"] == pytest.approx(0.0, abs=0.01)

    def test_the_subtraction_is_bounded(self):
        p = nodes._grade_params(
            {"YAVG": 60.0, "YHIGH": 120.0, "YLOW": 55.0, "SATAVG": 8.0}
        )
        assert p["black"] <= nodes._GRADE_MAX_BLACK_POINT

    def test_the_black_point_maths_matches_the_filter(self):
        # colorlevels: out = (in/255 - rimin) / (1 - rimin)
        assert nodes._black_point(255.0, 0.0) == pytest.approx(255.0)
        assert nodes._black_point(0.0, 0.1) == 0.0
        assert nodes._black_point(25.5, 0.1) == pytest.approx(0.0)
        assert nodes._black_point(127.5, 0.1) == pytest.approx(
            255.0 * (0.5 - 0.1) / 0.9
        )

    def test_the_filter_puts_the_black_point_before_the_gamma(self):
        chain = nodes._grade_chain(
            [nodes._grade_params(self.REEL_BODY)], [5.0]
        )
        assert chain.index("colorlevels=") < chain.index("eq=")
        # Same window on both, or one of them would bleed into its neighbour.
        assert chain.count("enable=between(t\\,0.000\\,4.999)") == 2

    def test_all_three_channels_move_together(self):
        # A per-channel difference would tint the shadows.
        chain = nodes._grade_chain(
            [{"gamma": 1.5, "saturation": 1.2, "black": 0.06}], [4.0]
        )
        assert "rimin=0.0600" in chain
        assert "gimin=0.0600" in chain
        assert "bimin=0.0600" in chain

    def test_no_black_point_emits_no_colorlevels(self):
        chain = nodes._grade_chain(
            [{"gamma": 1.5, "saturation": 1.2, "black": 0.0}], [4.0]
        )
        assert "colorlevels" not in chain
        assert "eq=gamma=1.500" in chain


class TestTheTwoGoalsCompeteOnDarkFootage:
    """Subtracting a black point lowers the mean, which asks for more gamma.

    Past _GRADE_MAX_GAMMA there is none to give, so the shadow lands on
    target while the mean stays short. Measured on a live shot: at YAVG 81
    the solved black point costs about 13 points of mean the capped gamma
    cannot recover, where r=0 would have landed 141.6.

    The mean is the bigger defect — 35% off, against a shadow off by a fifth
    of that — so the black point is what gives way.
    """

    DARK = {"YAVG": 81.0, "YHIGH": 180.0, "YLOW": 22.0, "SATAVG": 15.8}

    def test_the_black_point_gives_way_so_the_mean_can_land(self):
        p = nodes._grade_params(self.DARK)
        assert p["gamma"] == pytest.approx(nodes._GRADE_MAX_GAMMA, abs=0.01)
        assert _apply(self.DARK, p, "YAVG") == pytest.approx(GOLD_YAVG, abs=2.0)

    def test_it_gives_back_only_what_it_has_to(self):
        p = nodes._grade_params(self.DARK)
        # Not all the way to zero — the shadow still lands close to the
        # stills rather than being abandoned.
        assert 0.0 < p["black"] < 0.05
        assert _apply(self.DARK, p, "YLOW") == pytest.approx(60.0, abs=8.0)

    def test_a_shot_that_does_not_hit_the_cap_keeps_its_full_black_point(self):
        mild = {"YAVG": 120.0, "YHIGH": 200.0, "YLOW": 45.0, "SATAVG": 16.0}
        p = nodes._grade_params(mild)
        assert p["gamma"] < nodes._GRADE_MAX_GAMMA
        assert _apply(mild, p, "YLOW") == pytest.approx(60.0, abs=2.0)
        assert _apply(mild, p, "YAVG") == pytest.approx(GOLD_YAVG, abs=2.0)

    def test_footage_too_dark_to_rescue_is_lifted_as_far_as_the_cap_allows(self):
        # Not "as far as it takes" — beyond the cap a lift stops being
        # exposure and starts being amplified noise.
        murk = {"YAVG": 60.0, "YHIGH": 150.0, "YLOW": 15.0, "SATAVG": 9.0}
        p = nodes._grade_params(murk)
        assert p["gamma"] == pytest.approx(nodes._GRADE_MAX_GAMMA, abs=0.01)
        assert p["black"] == 0.0
        landed = _apply(murk, p, "YAVG")
        assert GOLD_YAVG > landed > murk["YAVG"] * 1.9
