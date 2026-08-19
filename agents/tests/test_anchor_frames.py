"""Re-anchoring is the only thing in this pipeline that produces a cut.

Measured on a delivered 7-shot reel, ffmpeg scene score at every planned
shot boundary:

    5.0s  chain       0.000        13.0s  RE-ANCHOR   0.754
    8.0s  chain       0.194        25.0s  RE-ANCHOR   0.442
   17.0s  chain       0.147
   21.0s  chain       0.098

A chained shot starts from the previous shot's last frame, so it is
continuous with it by construction and there is no cut for a detector — or a
viewer — to see. At 5.0s the score is literally zero. Across the nine reels
in the bucket, eight had NO frame-to-frame change above the 0.3 detection
threshold anywhere: thirty-second reels with not one visible cut.

And the two cuts the ninth reel did have both landed on the same image.
Shots 1, 4 and 7 all started from the one keyframe and came out as the three
most similar pairs in the reel:

    shots 1&4  SSIM 0.750       every chained pair  <= 0.583
    shots 1&7       0.676
    shots 4&7       0.645

Across nine reels that one measured 0.467 mean internal SSIM against a
median of 0.258 — the second most repetitive of the set.

So the fix is not to remove the re-anchor cuts but to give each one somewhere
new to land. Every number in this file is one of those measurements.
"""

import pytest

from workflows.video import nodes


# Scene score at each boundary of the measured reel, by boundary type.
CHAINED_BOUNDARIES = (0.000, 0.194, 0.147, 0.098)
REANCHOR_BOUNDARIES = (0.754, 0.442)
#: ffmpeg's conventional cut threshold, and what the sweep across nine reels
#: used. Eight of the nine never reached it.
CUT_THRESHOLD = 0.3

# Mean internal SSIM, nine reels sampled every 2s.
POPULATION_MEDIAN_SSIM = 0.258
MEASURED_REEL_SSIM = 0.467
SHARED_ANCHOR_PAIRS = (0.750, 0.676, 0.645)
CHAINED_PAIR_CEILING = 0.583


class TestTheMeasurementThatMotivatesThis:
    def test_no_chained_boundary_reads_as_a_cut(self):
        assert max(CHAINED_BOUNDARIES) < CUT_THRESHOLD

    def test_every_re_anchor_does(self):
        assert min(REANCHOR_BOUNDARIES) > CUT_THRESHOLD

    def test_shared_anchor_pairs_are_more_alike_than_any_chained_pair(self):
        # This is what rules out "it is just that they are all pour shots":
        # the chained pairs include pour shots too and none reach 0.6.
        assert min(SHARED_ANCHOR_PAIRS) > CHAINED_PAIR_CEILING


class TestAnchorIndices:
    def test_the_opening_shot_always_gets_one(self):
        assert _first(nodes._anchor_indices(7)) == 0
        assert _first(nodes._anchor_indices(1)) == 0

    def test_they_land_exactly_on_the_re_anchor_points(self):
        # The chain re-anchors after _MAX_CHAIN_DEPTH hops, so with a cap of
        # 2 the shots that start fresh are 1, 4 and 7 — which is what the
        # measured reel did.
        assert nodes._anchor_indices(7, cap=2) == [0, 3, 6]

    def test_lowering_the_cap_buys_more_cuts(self):
        # The cap is the cut-rhythm dial: one image generation per cut.
        assert len(nodes._anchor_indices(7, cap=1)) > len(
            nodes._anchor_indices(7, cap=2)
        )
        assert nodes._anchor_indices(7, cap=1) == [0, 2, 4, 6]

    def test_a_cap_of_zero_gives_every_shot_its_own_frame(self):
        assert nodes._anchor_indices(4, cap=0, limit=8) == [0, 1, 2, 3]

    def test_the_count_is_bounded(self):
        # Each one is an image generation; a long plan must not fan out.
        got = nodes._anchor_indices(20, cap=0, limit=nodes._MAX_ANCHOR_FRAMES)
        assert len(got) == nodes._MAX_ANCHOR_FRAMES

    def test_an_empty_plan_asks_for_nothing(self):
        assert nodes._anchor_indices(0) == []

    def test_a_degenerate_cap_does_not_divide_by_zero(self):
        assert nodes._anchor_indices(3, cap=-5, limit=8) == [0, 1, 2]

    def test_never_more_anchors_than_shots(self):
        assert nodes._anchor_indices(2, cap=0, limit=8) == [0, 1]


def _first(xs):
    return xs[0] if xs else None


def _full_set(num):
    """One distinct frame per anchored shot, whatever the cap is set to."""
    return {i: b"ANCHOR%d" % i for i in nodes._anchor_indices(num)}


class TestTheRenderLoopCutsToTheFreshFrame:
    """A re-anchor prefers the frame generated FOR the shot it starts."""

    def _run(self, monkeypatch, anchors):
        import asyncio

        from tests.test_video_multishot import _Harness, _state
        from workflows.video.nodes import render_video

        _Harness(monkeypatch)
        st = _state([4] * 7)
        st["anchor_frames"] = anchors
        result = asyncio.run(render_video(st))
        assert result.get("status") != "failed", result
        return [e.get("anchor") for e in result["video_meta"]["ledger"]]

    def test_each_re_anchor_lands_on_its_own_frame(self, monkeypatch):
        got = self._run(monkeypatch, _full_set(7))
        assert got[0] == "keyframe"
        for i in nodes._anchor_indices(7)[1:]:
            assert got[i] == f"anchor#{i + 1}", got

    def test_the_reel_no_longer_cuts_back_to_the_opening_frame(self, monkeypatch):
        got = self._run(monkeypatch, _full_set(7))
        # Exactly one shot may start on the keyframe: the first.
        assert got.count("keyframe") == 1, got

    def test_a_missing_anchor_falls_back_rather_than_failing(self, monkeypatch):
        # One generation failed. The reel still renders, re-anchoring on the
        # opening frame the way it always used to.
        idx = nodes._anchor_indices(7)
        missing = idx[1]
        anchors = {i: b"A%d" % i for i in idx if i != missing}
        got = self._run(monkeypatch, anchors)
        assert got[missing] in ("keyframe", "anchor"), got
        assert got[idx[-1]] == f"anchor#{idx[-1] + 1}", got

    def test_no_anchor_frames_at_all_is_the_old_behaviour(self, monkeypatch):
        got = self._run(monkeypatch, {})
        assert got[0] == "keyframe"
        # Still capped, still re-anchoring — just with nowhere new to go.
        depths = [
            int(a.split("+")[1]) if a and a.startswith("chain+") else 0
            for a in got
        ]
        assert max(depths) <= nodes._MAX_CHAIN_DEPTH, got

    def test_the_chain_cap_still_holds_with_fresh_anchors(self, monkeypatch):
        # Cutting to a fresh frame resets depth to zero, so drift is bounded
        # at least as tightly as before — every anchor is generation 0.
        got = self._run(monkeypatch, {0: b"K", 3: b"A4", 6: b"A7"})
        depths = [
            int(a.split("+")[1]) if a and a.startswith("chain+") else 0
            for a in got
        ]
        assert max(depths) <= nodes._MAX_CHAIN_DEPTH, got


class TestAnchorsShareOneLook:
    """Seven prompts can produce seven different films — the opposite defect.

    The plan's own LOCKS lines pin palette, setting and product identity per
    shot. This pins what a plan does not talk about: camera, lens, colour
    temperature, grade, set dressing.
    """

    def test_the_look_rule_names_what_must_match(self):
        rule = nodes._ANCHOR_LOOK_RULE.lower()
        for term in ("camera", "lens", "colour temperature", "location"):
            assert term in rule, term

    def test_and_says_what_may_differ(self):
        # Without this it reads as "make the same picture again", which is
        # the repetition being fixed.
        assert "different MOMENT" in nodes._ANCHOR_LOOK_RULE


class TestMakeKeyframeGeneratesTheSet:
    """One generation takes ~103s measured, so they must run concurrently.

    Serially, a 7-shot reel at cap 2 would add five minutes to a six-minute
    render. Concurrently it adds one generation's wall clock.
    """

    def _state(self, n=7):
        return {
            "brand_id": "b",
            "calendar_item_id": "c",
            "calendar_item": {"channel": "instagram"},
            "shot_plan": {"shots": [
                {"index": i + 1, "scene": f"SCENE CONTEXT: beat {i + 1}\n"
                                          f"FIRST FRAME: frame {i + 1}"}
                for i in range(n)
            ]},
            "product_image": None,
            "is_lifestyle_only": True,
        }

    def _run(self, monkeypatch, *, fail_indices=()):
        import asyncio

        seen = {"prompts": [], "uploads": [], "concurrent": 0, "peak": 0}

        async def fake_generate(prompt, **kw):
            # The index is taken at CALL time, not after the await — these
            # run concurrently, so reading len() afterwards gives whatever
            # the last starter appended and every branch takes the same path.
            idx = len(seen["prompts"])
            seen["prompts"].append(prompt)
            seen["concurrent"] += 1
            seen["peak"] = max(seen["peak"], seen["concurrent"])
            await asyncio.sleep(0.01)
            seen["concurrent"] -= 1
            if idx in fail_indices:
                raise RuntimeError("generation failed")
            return "data:image/png;base64,aGk="

        async def fake_upload(bucket, obj, data, ctype):
            seen["uploads"].append(obj)

        async def noop(*a, **kw):
            return None

        async def fail(state, message):
            # Unstubbed, _fail writes to a database these tests do not have
            # and spends five seconds timing out on the connection.
            return {"status": "failed", "errors": [message]}

        monkeypatch.setattr(nodes, "generate_image", fake_generate)
        monkeypatch.setattr(nodes, "async_upload_file", fake_upload)
        monkeypatch.setattr(nodes, "update_agent_run_step", noop)
        monkeypatch.setattr(nodes, "_fail", fail)
        out = asyncio.run(nodes.make_keyframe(self._state()))
        return out, seen

    def test_one_anchor_per_re_anchor_point(self, monkeypatch):
        out, seen = self._run(monkeypatch)
        assert sorted(out["anchor_frames"]) == nodes._anchor_indices(7)

    def test_they_are_generated_concurrently(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        assert seen["peak"] > 1, (
            "anchors rendered one after another — at ~103s each that is five "
            "minutes added to a six-minute render"
        )

    def test_each_uses_its_own_shot_scene(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        # Each anchored shot's OWN first-frame line, not the opening one N
        # times over — which would rebuild the repetition in a new place.
        # _prompt_for extracts the scene's FIRST FRAME line, so that is what
        # reaches the model.
        for i in nodes._anchor_indices(7):
            assert any(f"frame {i + 1}" in p for p in seen["prompts"]), i + 1

    def test_every_anchor_carries_the_exposure_and_look_rules(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        for p in seen["prompts"]:
            assert "EXPOSURE" in p
            assert "CONSISTENT LOOK" in p

    def test_later_anchors_are_stored_for_review(self, monkeypatch):
        _, seen = self._run(monkeypatch)
        assert "b/c/keyframe.png" in seen["uploads"]
        for i in nodes._anchor_indices(7)[1:]:
            assert f"b/c/anchor_{i + 1:02d}.png" in seen["uploads"], i + 1

    def test_a_failed_later_anchor_does_not_fail_the_reel(self, monkeypatch):
        out, _ = self._run(monkeypatch, fail_indices=(1,))
        assert out["keyframe_bytes"] == b"hi"
        assert len(out["anchor_frames"]) == len(nodes._anchor_indices(7)) - 1

    def test_a_failed_opening_anchor_does(self, monkeypatch):
        # Without an opening frame there is nothing to fall back to, and the
        # old code path silently produced a t2v reel.
        out, _ = self._run(monkeypatch, fail_indices=(0,))
        assert out.get("status") == "failed"


class TestEveryAnchorGetsTheSwap:
    """Swapping only the first anchor ships a blank box as a hero.

    product_rule asks EVERY anchor for "a simple generic unlabeled product
    container (plain matte box or pouch with NO writing on it) ... completely
    blank — it will be digitally replaced later". When the swap ran on
    anchors[0] alone, the frames that start shots 4 and 7 kept that blank
    box — which is verbatim the defect make_keyframe already refuses to ship
    for shot 1: "a blank unbranded pouch becomes the hero of a 30s reel".
    """

    def _run(self, monkeypatch, *, refuse=()):
        import asyncio

        seen = {"swaps": []}

        async def fake_generate(prompt, **kw):
            n = len(seen["swaps"])  # unused, keeps signature honest
            return "data:image/png;base64,aGk="

        async def fake_swap(state, data):
            i = len(seen["swaps"])
            seen["swaps"].append(i)
            # Refusal is signalled by returning the SAME object.
            return data if i in refuse else b"SWAPPED%d" % i

        async def fake_swappable(url):
            return True

        async def noop(*a, **kw):
            return None

        async def fail(state, message):
            return {"status": "failed", "errors": [message]}

        monkeypatch.setattr(nodes, "generate_image", fake_generate)
        monkeypatch.setattr(nodes, "product_photo_is_swappable", fake_swappable)
        monkeypatch.setattr(nodes, "_replace_product_in_generated_image", fake_swap)
        monkeypatch.setattr(nodes, "async_upload_file", noop)
        monkeypatch.setattr(nodes, "update_agent_run_step", noop)
        monkeypatch.setattr(nodes, "_fail", fail)
        state = {
            "brand_id": "b",
            "calendar_item_id": "c",
            "calendar_item": {"channel": "instagram"},
            "shot_plan": {"shots": [
                {"index": i + 1, "scene": f"SCENE CONTEXT: beat {i + 1}"}
                for i in range(7)
            ]},
            "product_image": "products/b/pack.png",
            "is_lifestyle_only": False,
        }
        return asyncio.run(nodes.make_keyframe(state)), seen

    def test_the_swap_runs_once_per_anchor(self, monkeypatch):
        out, seen = self._run(monkeypatch)
        assert len(seen["swaps"]) == len(nodes._anchor_indices(7))

    def test_no_anchor_keeps_its_placeholder(self, monkeypatch):
        out, _ = self._run(monkeypatch)
        for idx, data in out["anchor_frames"].items():
            assert data.startswith(b"SWAPPED"), (idx, data)

    def test_a_later_refusal_drops_that_anchor_rather_than_shipping_it(
        self, monkeypatch
    ):
        # Better one repeated composition than one fabricated pack: the cut
        # falls back to the opening frame, which is real.
        out, _ = self._run(monkeypatch, refuse=(1,))
        assert 0 in out["anchor_frames"]
        assert len(out["anchor_frames"]) == len(nodes._anchor_indices(7)) - 1
        for data in out["anchor_frames"].values():
            assert data.startswith(b"SWAPPED")

    def test_a_refusal_on_the_opening_anchor_still_drops_the_whole_reel(
        self, monkeypatch
    ):
        out, _ = self._run(monkeypatch, refuse=(0,))
        assert out["keyframe_bytes"] is None
        assert out["keyframe_verified_pack"] is False


class TestThePlannerDoesNotContradictItself:
    """A rule and its verbatim contradiction in one call is not a rule.

    pack_block forbids the literal strings 'bottle whole and visible' and
    'product-shot distance'. The STORY ARC and SHORT-FORM DISCIPLINE blocks
    used to emit "held at natural product-shot distance" and "Show the
    product whole at natural product-shot distance" unconditionally — the
    second tripping both banned phrases at once. That is why the hero-pack
    beat survived every ban placed on it.
    """

    def _prompts(self, monkeypatch, *, verifiable):
        import asyncio

        seen = {}

        async def fake_chat(messages, **kw):
            seen["system"] = messages[0]["content"]
            seen["user"] = messages[1]["content"]
            raise RuntimeError("stop after capturing")

        async def noop(*a, **kw):
            return None

        async def fail(state, message):
            return {"status": "failed", "errors": [message]}

        monkeypatch.setattr(nodes, "chat_completion", fake_chat)
        monkeypatch.setattr(nodes, "update_agent_run_step", noop)
        monkeypatch.setattr(nodes, "_fail", fail)
        try:
            asyncio.run(nodes.plan_shots({
                "brand_id": "b", "calendar_item_id": "c", "run_id": "",
                "brand": {"name": "Naturespan"},
                "calendar_item": {"channel": "instagram"},
                "product": {"name": "Mild Olive Oil"},
                "product_pack_verifiable": verifiable,
            }))
        except Exception:
            pass
        return seen

    def test_an_unverifiable_pack_never_asks_for_product_shot_distance(
        self, monkeypatch
    ):
        seen = self._prompts(monkeypatch, verifiable=False)
        whole = seen["system"] + seen["user"]
        # The ban names this phrase; the instructions must not use it.
        assert whole.count("product-shot distance") == 1, (
            "the only mention left should be the one inside the ban itself"
        )

    def test_nor_for_the_product_whole(self, monkeypatch):
        seen = self._prompts(monkeypatch, verifiable=False)
        assert "Show the product whole" not in seen["system"]

    def test_the_reveal_beat_is_redirected_at_the_arc_level(self, monkeypatch):
        seen = self._prompts(monkeypatch, verifiable=False)
        assert "REVEAL — the product's CONTENT" in seen["system"]

    def test_a_verifiable_pack_keeps_the_hero_reveal(self, monkeypatch):
        seen = self._prompts(monkeypatch, verifiable=True)
        assert "hero framing" in seen["system"]
        assert "Show the product whole" in seen["system"]
        assert "PACKAGING — READ THIS" not in seen["user"]


class TestTheDialIsCoherentAcrossItsRange:
    """A limit below the shot count silently rebuilds the repetition.

    _anchor_indices truncates to the limit, and render_video falls back to
    the OPENING frame for any re-anchor with no frame of its own. So a limit
    of 4 at cap 0 gives anchors for shots 1-4 and sends shots 5, 6 and 7 back
    to shot 1's frame — which is the defect per-shot anchors exist to remove,
    reappearing at the setting meant to fix it hardest.
    """

    def test_the_limit_tracks_the_shot_cap(self):
        assert nodes._MAX_ANCHOR_FRAMES >= nodes.MAX_SHOTS

    @pytest.mark.parametrize("cap", (0, 1, 2))
    def test_every_shot_that_re_anchors_has_a_frame_of_its_own(self, cap):
        num = nodes.MAX_SHOTS
        idx = set(nodes._anchor_indices(num, cap=cap))
        # These are precisely the shots the render loop will re-anchor at.
        expected = set(range(0, num, cap + 1))
        assert idx == expected, (cap, sorted(idx), sorted(expected))

    def test_lowering_the_cap_never_reduces_the_cut_count(self):
        counts = [len(nodes._anchor_indices(7, cap=c)) for c in (2, 1, 0)]
        assert counts == sorted(counts), counts
