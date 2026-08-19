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


def _stub_delabel(monkeypatch):
    """Keep the scene rewrite off the network in render tests.

    It runs on every keyframeless reel and would otherwise make a real
    chat_completion call — slow, non-hermetic, and passing only because the
    failure path falls back to the original scenes.
    """
    async def _passthrough(shots):
        return shots, True

    monkeypatch.setattr(nodes, "_delabel_shot_scenes", _passthrough)


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
        _stub_delabel(monkeypatch)
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
        _stub_delabel(monkeypatch)
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


class TestUnverifiedPackLettering:
    """With no verified pack, every label the model draws is invented.

    A rendered reel carried "FIIRE CMIS", "THETE CCRE MAITENE OL" and "TWTL
    CCRE PAILSNEWE" across seven shots of olive-oil bottles. The swap had
    correctly refused (the reference was a wide banner with a small product),
    so make_keyframe fell back to t2v and nothing anchored the pack — the
    model drew a label from nothing.

    The existing plan-prompt rule does not cover this. The model OBEYED it —
    the bottles sit at natural product-shot distance, the label is not the
    subject — and the copy is still legible enough to read as nonsense.
    """

    def test_the_directive_is_absent_when_a_pack_is_verified(self):
        prompt = nodes._build_shot_prompt(
            {"scene": "SCENE CONTEXT: a kitchen"}, 0, 6
        )
        assert "PACKAGING (hard constraint" not in prompt

    def test_every_shot_carries_it_when_no_pack_is_verified(self):
        for i in range(6):
            prompt = nodes._build_shot_prompt(
                {"scene": "SCENE CONTEXT: a kitchen"}, i, 6,
                unverified_pack=True,
            )
            assert "PACKAGING (hard constraint" in prompt, i

    def test_it_forbids_resolving_copy_not_merely_close_ups(self):
        text = nodes._UNVERIFIED_PACK_DIRECTIVE
        # The old rule only banned label CLOSE-UPS, which the model honoured
        # while still rendering readable gibberish at mid distance.
        assert "readable printed copy" in text
        assert "invent" in text
        # And it must say what correct output looks like, or the model has
        # only a prohibition to satisfy.
        assert "Unreadable packaging is correct" in text

    def test_the_single_call_path_carries_it_too(self):
        plan = {"shots": [{"index": 1, "duration_s": 5.0, "scene": "x"}]}
        assert "PACKAGING (hard constraint" not in nodes._build_video_prompt(plan)
        assert "PACKAGING (hard constraint" in nodes._build_video_prompt(
            plan, unverified_pack=True
        )

    def test_both_paths_derive_the_flag_from_pack_provenance(self):
        """Not from whether a keyframe exists.

        make_keyframe used to answer both questions at once: it discarded the
        frame whenever the swap did not fire, so "no keyframe" meant "no real
        pack". It now keeps a deliberately unreadable frame instead — which is
        a better anchor — so a keyframe can exist with no verified pack behind
        it. Reading the bytes would silently switch the directive OFF for
        exactly the reels that need it.
        """
        import inspect

        src = inspect.getsource(nodes.render_video)
        assert 'unverified_pack = not state.get("keyframe_verified_pack")' in src
        assert 'unverified_pack=not state.get("keyframe_verified_pack")' in src
        # The bytes must not be what decides it, in either path.
        assert "unverified_pack = not keyframe" not in src
        assert "unverified_pack=not keyframe" not in src


class TestScenesAreRewrittenNotJustWarnedAbout:
    """The directive alone did not work, and a rendered reel proved it.

    With _UNVERIFIED_PACK_DIRECTIVE appended to every shot prompt, the reel
    still came back reading "FIRLINIE ORIE OIL", "FIRIE NOSI" and "2HE G OIL"
    on the hero bottle. The shot plan was still describing a hero pack with
    its label to camera, and a negation appended after a scene loses to the
    scene — the scene is what the model is being asked to make.
    """

    SHOTS = [
        {"index": 1, "duration_s": 4.0,
         "scene": "SCENE CONTEXT: hero bottle, label square to camera"},
        {"index": 2, "duration_s": 4.0,
         "scene": "SCENE CONTEXT: macro on the printed label"},
    ]

    def _stub(self, monkeypatch, payload):
        async def fake(messages, **kw):
            self.system = messages[0]["content"]
            return payload

        monkeypatch.setattr(nodes, "chat_completion", fake)

    def test_the_revision_replaces_the_scenes(self, monkeypatch):
        import asyncio
        import json

        self._stub(monkeypatch, json.dumps({"shots": [
            {"index": 1, "scene": "SCENE CONTEXT: the pour onto warm bread"},
            {"index": 2, "scene": "SCENE CONTEXT: hands at a shared table"},
        ]}))
        out, rewritten = asyncio.run(nodes._delabel_shot_scenes(self.SHOTS))
        assert rewritten is True
        assert "pour onto warm bread" in out[0]["scene"]
        assert "hands at a shared table" in out[1]["scene"]
        # Everything else about the beat survives.
        assert out[0]["duration_s"] == 4.0
        assert out[0]["index"] == 1

    def test_it_asks_for_the_same_beat_not_a_new_plan(self, monkeypatch):
        import asyncio
        import json

        self._stub(monkeypatch, json.dumps({"shots": [
            {"index": 1, "scene": "x"}, {"index": 2, "scene": "y"},
        ]}))
        asyncio.run(nodes._delabel_shot_scenes(self.SHOTS))
        assert "SAME beat" in self.system
        assert "NO PRODUCT LABEL IN THIS REEL MAY BE LEGIBLE" in self.system
        # And it must say what to shoot INSTEAD, not only what to avoid.
        assert "product IN USE" in self.system

    def test_a_failed_revision_keeps_the_original_scenes(self, monkeypatch):
        import asyncio

        async def boom(messages, **kw):
            raise RuntimeError("model unavailable")

        monkeypatch.setattr(nodes, "chat_completion", boom)
        out, rewritten = asyncio.run(nodes._delabel_shot_scenes(self.SHOTS))
        assert rewritten is False
        assert out == self.SHOTS, "a failed rewrite must not lose the plan"

    def test_an_unusable_revision_keeps_the_original_scenes(self, monkeypatch):
        import asyncio
        import json

        for payload in ('{"shots": []}', "not json", json.dumps({"shots": [
            {"index": 99, "scene": "wrong index"}
        ]})):
            self._stub(monkeypatch, payload)
            out, rewritten = asyncio.run(
                nodes._delabel_shot_scenes(self.SHOTS)
            )
            assert rewritten is False, payload
            assert out == self.SHOTS

    def test_a_partial_revision_keeps_the_shots_it_missed(self, monkeypatch):
        import asyncio
        import json

        self._stub(monkeypatch, json.dumps({"shots": [
            {"index": 1, "scene": "SCENE CONTEXT: the pour"},
        ]}))
        out, rewritten = asyncio.run(nodes._delabel_shot_scenes(self.SHOTS))
        assert rewritten is True
        assert out[0]["scene"] == "SCENE CONTEXT: the pour"
        assert out[1] == self.SHOTS[1]

    def test_it_only_runs_when_no_pack_is_verified(self):
        import inspect

        src = inspect.getsource(nodes.render_video)
        head = src[:src.index("_delabel_shot_scenes")]
        assert "if unverified_pack:" in head

    def test_an_empty_plan_is_not_sent_to_the_model(self, monkeypatch):
        import asyncio

        async def boom(messages, **kw):
            raise AssertionError("should not be called")

        monkeypatch.setattr(nodes, "chat_completion", boom)
        assert asyncio.run(nodes._delabel_shot_scenes([])) == ([], False)


class TestKeyframeSwapPreCheck:
    """Ask whether the swap CAN work before paying to find out that it can't.

    Measured on a live Naturespan reel: the pipeline generated a 1024x1792
    frame whose hero was a blank placeholder container, ran the swap against
    the product's only gallery photo — a 1200x630 share banner — watched it
    refuse, and discarded the frame. That cost one image generation and about
    two minutes, and left the reel with no anchor at all, so shot 1 rendered
    t2v and every later shot chained off it.

    One HTTP fetch answers the same question first.
    """

    def _state(self):
        return {
            "brand_id": "b",
            "calendar_item_id": "c",
            "calendar_item": {"channel": "instagram"},
            "shot_plan": {"shots": [{"index": 1, "scene": "SCENE: a kitchen"}]},
            "product_image": "products/b/banner.png",
            "is_lifestyle_only": False,
        }

    def _run(self, monkeypatch, *, swappable):
        import asyncio

        captured = {}

        async def fake_swappable(url):
            captured["asked"] = url
            return swappable

        async def fake_generate(prompt, **kw):
            captured["prompt"] = prompt
            return "data:image/png;base64,aGk="

        async def fake_swap(state, data):
            captured["swap_ran"] = True
            return data  # refuses — returns the same object

        async def noop(*a, **kw):
            return None

        monkeypatch.setattr(nodes, "product_photo_is_swappable", fake_swappable)
        monkeypatch.setattr(nodes, "generate_image", fake_generate)
        monkeypatch.setattr(nodes, "_replace_product_in_generated_image", fake_swap)
        monkeypatch.setattr(nodes, "async_upload_file", noop)
        monkeypatch.setattr(nodes, "update_agent_run_step", noop)
        return asyncio.run(nodes.make_keyframe(self._state())), captured

    def test_an_unswappable_photo_never_reaches_the_swap(self, monkeypatch):
        out, cap = self._run(monkeypatch, swappable=False)
        assert cap["asked"] == "products/b/banner.png"
        assert "swap_ran" not in cap

    def test_and_the_frame_is_kept_as_an_anchor(self, monkeypatch):
        out, _ = self._run(monkeypatch, swappable=False)
        assert out["keyframe_bytes"] == b"hi"
        assert out["keyframe_object"] == "b/c/keyframe.png"
        # Kept, but honest about what it shows.
        assert out["keyframe_verified_pack"] is False

    def test_it_asks_for_unreadable_packaging_not_a_blank_placeholder(
        self, monkeypatch
    ):
        _, cap = self._run(monkeypatch, swappable=False)
        prompt = cap["prompt"]
        assert "completely blank" not in prompt
        assert "digitally replaced later" not in prompt
        assert "PACKAGING (hard constraint" in prompt

    def test_a_swappable_photo_still_takes_the_placeholder_path(self, monkeypatch):
        out, cap = self._run(monkeypatch, swappable=True)
        assert cap["swap_ran"] is True
        assert "completely blank" in cap["prompt"]
        assert "PACKAGING (hard constraint" not in cap["prompt"]
        # The swap refused in this stub, so the placeholder frame is dropped.
        assert out["keyframe_bytes"] is None
        assert out["keyframe_verified_pack"] is False

    def test_a_lifestyle_reel_asks_nothing_and_shows_no_product(self, monkeypatch):
        import asyncio

        captured = {}

        async def boom(url):
            raise AssertionError("no product photo to check")

        async def fake_generate(prompt, **kw):
            captured["prompt"] = prompt
            return "data:image/png;base64,aGk="

        async def noop(*a, **kw):
            return None

        monkeypatch.setattr(nodes, "product_photo_is_swappable", boom)
        monkeypatch.setattr(nodes, "generate_image", fake_generate)
        monkeypatch.setattr(nodes, "async_upload_file", noop)
        monkeypatch.setattr(nodes, "update_agent_run_step", noop)
        state = self._state() | {"is_lifestyle_only": True}
        out = asyncio.run(nodes.make_keyframe(state))
        assert "Do NOT include any products" in captured["prompt"]
        assert out["keyframe_verified_pack"] is False


class TestAKeptKeyframeDoesNotSilenceTheDirective:
    """The regression the pre-check could have introduced.

    render_video read `not keyframe`, which worked only because the two facts
    were fused: no keyframe meant no verified pack. Keeping an unreadable-pack
    keyframe as an anchor separates them, and reading the bytes would switch
    the directive OFF for exactly the reels that need it most.
    """

    def _anchored_but_unverified(self, monkeypatch):
        import asyncio

        from tests.test_video_multishot import _Harness, _state
        from workflows.video.nodes import render_video

        h = _Harness(monkeypatch)
        seen = {}

        async def spy(shots):
            seen["ran"] = True
            return shots, True

        monkeypatch.setattr(nodes, "_delabel_shot_scenes", spy)
        result = asyncio.run(
            render_video(_state([4] * 5, verified_pack=False))
        )
        return result, seen

    def test_the_scenes_are_still_rewritten(self, monkeypatch):
        _, seen = self._anchored_but_unverified(monkeypatch)
        assert seen.get("ran") is True

    def test_and_every_shot_prompt_still_carries_the_directive(self, monkeypatch):
        result, _ = self._anchored_but_unverified(monkeypatch)
        assert result["video_meta"]["unverified_pack"] is True
        assert result["video_prompt"].count("PACKAGING (hard constraint") == 5

    def test_the_anchor_is_used_all_the_same(self, monkeypatch):
        result, _ = self._anchored_but_unverified(monkeypatch)
        anchors = [e.get("anchor") for e in result["video_meta"]["ledger"]]
        # The frame is unverified, not useless: shot 1 still starts from it
        # rather than falling back to t2v.
        assert anchors[0] == "keyframe", anchors

    def test_a_verified_reel_is_left_alone(self, monkeypatch):
        import asyncio

        from tests.test_video_multishot import _Harness, _state
        from workflows.video.nodes import render_video

        h = _Harness(monkeypatch)

        async def boom(shots):
            raise AssertionError("the pack is verified — nothing to delabel")

        monkeypatch.setattr(nodes, "_delabel_shot_scenes", boom)
        result = asyncio.run(render_video(_state([4] * 5)))
        assert result["video_meta"]["unverified_pack"] is False
        assert "PACKAGING (hard constraint" not in result["video_prompt"]
