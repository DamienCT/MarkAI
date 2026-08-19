"""Chain depth and motion checks — the two render defects nothing measured.

Both were found by looking at rendered reels:

  - Every shot chained i2v off the previous shot's last frame, so shot 8 sat
    seven generations downstream of the branded keyframe. Across one reel the
    pack name degraded KAOKA -> KOOKA -> ҠӒOKA and the frame went soft.
  - A shot can come back as its own input image held for five seconds. That
    passes every structural check the pipeline had (codec, duration, byte
    count) and is unmistakable on screen.

The motion thresholds here are calibrated against measured footage, listed in
the constants' comment. The numbers in this file are those measurements.
"""

import pytest

from workflows.video import nodes


# Measured per 5s window on four rendered reels.
CONTROL_HELD_STILL = 0.001
SLOWEST_REAL_BEAT = 0.53      # hand breaking chocolate over a bowl
ORDINARY_BEATS = (1.19, 1.44, 1.73, 2.75, 3.47, 5.33)
FASTEST_REAL_MOVE = 9.29      # dolly through a shop interior


class TestMotionThresholds:
    def test_a_held_still_frame_is_flagged(self):
        assert nodes._motion_verdict(CONTROL_HELD_STILL) == "static"

    @pytest.mark.parametrize("score", (SLOWEST_REAL_BEAT, *ORDINARY_BEATS,
                                       FASTEST_REAL_MOVE))
    def test_every_real_beat_passes(self, score):
        # A false positive costs a provider call and replaces a good take.
        assert nodes._motion_verdict(score) is None

    def test_the_floor_sits_between_the_control_and_real_footage(self):
        assert CONTROL_HELD_STILL < nodes._MIN_MOTION_YAVG < SLOWEST_REAL_BEAT

    def test_the_floor_keeps_headroom_under_the_slowest_real_beat(self):
        # Tightening it to within a hair of 0.53 would start re-rendering
        # quiet product beats, which are the ones worth keeping.
        assert nodes._MIN_MOTION_YAVG <= SLOWEST_REAL_BEAT / 2

    def test_the_ceiling_clears_the_fastest_real_move(self):
        assert nodes._MAX_MOTION_YAVG > FASTEST_REAL_MOVE * 2

    def test_an_unmeasurable_shot_is_never_flagged(self):
        # None means ffmpeg was unavailable or the filter failed. Treating
        # that as "static" would re-render good shots on a tooling problem.
        assert nodes._motion_verdict(None) is None


class TestMotionParsing:
    def test_mean_of_the_printed_frames(self):
        stderr = "\n".join(
            f"[Parsed_metadata_3 @ 0x1] lavfi.signalstats.YAVG={v}"
            for v in ("0.000", "2.000", "4.000", "6.000")
        )
        # The first tblend frame compares frame 1 to itself and is dropped.
        assert nodes._motion_from_stderr(stderr) == pytest.approx(4.0)

    def test_a_single_frame_survives_the_drop(self):
        assert nodes._motion_from_stderr(
            "lavfi.signalstats.YAVG=3.500"
        ) == pytest.approx(3.5)

    def test_no_frames_parsed_is_unknown_not_zero(self):
        assert nodes._motion_from_stderr("") is None
        assert nodes._motion_from_stderr("ffmpeg version 6.1") is None

    def test_the_filter_chain_analyses_small_and_encodes_nothing(self):
        cmd = nodes._motion_cmd("/tmp/shot.mp4")
        joined = " ".join(cmd)
        assert f"scale={nodes._MOTION_ANALYSIS_W}:-2" in joined
        assert "tblend=all_mode=difference" in joined
        assert "metadata=print:key=lavfi.signalstats.YAVG" in joined
        # -f null with no encoder: this pass must never write a file.
        assert cmd[-3:] == ["-f", "null", "-"]
        assert "-an" in cmd


class TestChainDepthCap:
    def test_the_cap_bounds_generational_drift(self):
        # 1 would forbid chaining outright and lose all shot-to-shot
        # continuity; 4+ is the depth the pack name was already mutating at.
        assert 2 <= nodes._MAX_CHAIN_DEPTH <= 3

    def test_retries_cannot_double_the_render_bill(self):
        assert nodes._MAX_MOTION_RETRIES < nodes.MAX_SHOTS / 2


class TestChainCapWithoutAKeyframe:
    """The cap was gated on the keyframe, so it never fired without one.

    make_keyframe drops the keyframe and falls back to t2v whenever the
    product swap did not fire. A live reel rendered that way and shot 4 came
    back "from chain+3" — the chain ran unbounded on exactly the reel where
    drift is worst, because re-anchoring had nothing to return to.
    """

    def test_a_no_keyframe_reel_still_caps_its_chain(self, monkeypatch):
        import asyncio
        import sys
        import os

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from tests.test_video_multishot import _Harness, _state
        from workflows.video.nodes import render_video

        h = _Harness(monkeypatch)
        result = asyncio.run(render_video(_state([4] * 6, keyframe=None)))

        assert result.get("status") != "failed"
        anchors = [
            entry.get("anchor")
            for entry in result["video_meta"]["ledger"]
        ]
        # Shot 1 is genuinely text-to-video: nothing to anchor on yet.
        assert anchors[0] == "t2v"
        # Every later shot must be within the cap of the adopted anchor.
        depths = [
            int(a.split("+")[1]) if a and a.startswith("chain+") else 0
            for a in anchors
        ]
        assert max(depths) <= nodes._MAX_CHAIN_DEPTH, anchors
        assert "anchor" in anchors, (
            f"the reel never re-anchored: {anchors}"
        )

    def test_shot_one_is_not_labelled_as_having_a_keyframe(self, monkeypatch):
        import asyncio

        from tests.test_video_multishot import _Harness, _state
        from workflows.video.nodes import render_video

        h = _Harness(monkeypatch)
        result = asyncio.run(render_video(_state([4] * 4, keyframe=None)))
        anchors = [e.get("anchor") for e in result["video_meta"]["ledger"]]
        assert anchors[0] != "keyframe", (
            "the label claimed an anchor that did not exist"
        )

    def test_a_keyframe_reel_still_returns_to_the_keyframe(self, monkeypatch):
        import asyncio

        from tests.test_video_multishot import _Harness, _state
        from workflows.video.nodes import render_video

        h = _Harness(monkeypatch)
        result = asyncio.run(render_video(_state([4] * 6)))
        anchors = [e.get("anchor") for e in result["video_meta"]["ledger"]]
        assert anchors[0] == "keyframe"
        assert "keyframe" in anchors[1:], anchors
