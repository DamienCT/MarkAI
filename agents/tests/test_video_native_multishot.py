"""Native multishot render branch — ONE forge call for the whole reel.

Covers: the plan's per-shot prose field (label stripping, scene fallback,
supplier scrub, language guard), the fitted-plan → segments[] mapping,
capability/setting/tier gating, fallback on 422/failure and on the whole-reel
motion floor after one seed-bumped retry, single-uniform-grade behaviour,
caption realignment when scdet finds no cuts (the NORMAL case — the model
renders cross-dissolves), the synthesized ledger/meta shape, provider
routing (fal/veo refuse segments; forge carries the multishot contract),
and make_keyframe skipping mid-reel anchors on the native branch.
"""

import asyncio
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shared.video as shared_video
import workflows.video.nodes as video_nodes
from shared.video import (
    FalProvider,
    ForgeProvider,
    ProviderUnavailableError,
    VeoProvider,
    VideoRequest,
    VideoResult,
)

# Bound at import time, BEFORE the conftest fixture rebinds the module
# attribute to the always-False stub — these tests probe the real function.
_real_forge_probe = shared_video.forge_supports_multishot

from tests.test_video_multishot import _conformant_info, _Harness, _state
from tests.test_video_providers import FakeClient, FakeResponse
from workflows.video.nodes import (
    _build_segment_prompt,
    _clean_shot_prose,
    _detect_cuts,
    _dissolve_safe_windows,
    _normalize_shot_plan,
    _prose_from_scene,
    _snap_windows_to_cuts,
    _uniform_grade_chain,
    render_video,
)


# ── Prose: the native branch's per-shot prompt field ───────────────────────


class TestProseNormalization:
    def test_labels_and_timestamps_are_stripped(self):
        assert _clean_shot_prose("Shot 3: A hand pours oil.") == "A hand pours oil."
        assert _clean_shot_prose("SCENE 2 — The jar gleams.") == "The jar gleams."
        assert _clean_shot_prose("3. The pour lands.") == "The pour lands."
        assert _clean_shot_prose("[0:12] Steam rises.") == "Steam rises."
        # Stacked regressions wear two coats — both come off.
        assert (
            _clean_shot_prose("Shot 1: [0:00-0:05] The kitchen wakes.")
            == "The kitchen wakes."
        )

    def test_prose_that_needs_nothing_is_untouched(self):
        text = "A hand lifts the jar; the ambience continues across the cut."
        assert _clean_shot_prose(text) == text

    def test_numbers_that_are_content_survive(self):
        # "3.5" must not lose its integer half to the enumeration stripper,
        # and "Scene-setting" must not lose its first word to the label one.
        assert (
            _clean_shot_prose("3.5 litres pour into the pan.")
            == "3.5 litres pour into the pan."
        )
        assert (
            _clean_shot_prose("Scene-setting sunlight fills the room.")
            == "Scene-setting sunlight fills the room."
        )

    def test_absent_prose_becomes_empty(self):
        assert _clean_shot_prose(None) == ""
        assert _clean_shot_prose("   ") == ""

    def test_scene_fallback_joins_context_and_first_frame(self):
        scene = (
            "SCENE CONTEXT: a sunlit kitchen\n"
            "FIRST FRAME: the jar centred on the counter\n"
            "CAMERA/OPTICS: 35mm\nLIGHTING: soft\nAUDIO: hum\n"
            "STYLE: warm\nLOCKS: jar identity"
        )
        assert _prose_from_scene(scene) == (
            "a sunlit kitchen. the jar centred on the counter."
        )

    def test_free_text_scene_collapses_to_one_line(self):
        assert _prose_from_scene("just  a\nplain scene") == "just a plain scene"

    def test_normalize_cleans_given_prose(self):
        plan = {
            "shots": [
                {
                    "index": 1,
                    "duration_s": 3,
                    "scene": "SCENE CONTEXT: kitchen\nFIRST FRAME: jar",
                    "prose": "Shot 1: The jar gleams on the counter.",
                }
            ]
        }
        out = _normalize_shot_plan(plan)
        assert out["shots"][0]["prose"] == "The jar gleams on the counter."
        # The structured scene block is kept unchanged for the fallback path.
        assert out["shots"][0]["scene"].startswith("SCENE CONTEXT: kitchen")

    def test_normalize_fills_missing_prose_from_the_scene(self):
        plan = {
            "shots": [
                {
                    "index": 1,
                    "duration_s": 3,
                    "scene": "SCENE CONTEXT: kitchen\nFIRST FRAME: the jar centred",
                }
            ]
        }
        out = _normalize_shot_plan(plan)
        assert out["shots"][0]["prose"] == "kitchen. the jar centred."

    def test_supplier_scrub_reaches_prose(self):
        from shared.suppliers import scrub_content_payload

        plan = _normalize_shot_plan(
            {
                "shots": [
                    {
                        "index": 1,
                        "duration_s": 3,
                        "scene": "SCENE CONTEXT: kitchen",
                        "prose": "Acme Foods olive oil pours over warm bread.",
                    }
                ],
                "cta": "Shop now",
            }
        )
        scrubbed, hits = scrub_content_payload(plan, ["Acme Foods"])
        assert "Acme Foods" not in scrubbed["shots"][0]["prose"]
        assert hits

    def test_language_guard_reads_prose(self):
        plan = {
            "hook_line": "",
            "caption": "",
            "cta": "",
            "shots": [
                {
                    "overlay_text": "",
                    "prose": "Une main verse l'huile dans la poêle.",
                }
            ],
        }
        flags = video_nodes._plan_language_flags(plan, [])
        assert "shots[0].prose" in flags

    def test_the_plan_prompt_asks_for_prose(self):
        # The instruction block plan_shots sends: flowing paragraph,
        # identity tags each shot, diegetic continuity clause, no labels.
        import inspect

        src = inspect.getsource(video_nodes.plan_shots)
        assert '"prose"' in src
        assert "the ambience continues across the" in src
        assert "NO shot numbers, NO timestamps, NO labels" in src

    def test_delabel_rewrite_covers_prose(self, monkeypatch):
        # The unverified-pack rewrite must revise prose with the scene — and
        # when the revision loses the prose, it is mechanically rebuilt from
        # the REVISED scene, never left pointing at the readable pack.
        import json

        async def fake_chat(messages, **kw):
            return json.dumps(
                {
                    "shots": [
                        {
                            "index": 1,
                            "scene": "SCENE CONTEXT: pour only\nFIRST FRAME: the pour",
                            "prose": "Shot 1: Oil pours, label unseen.",
                        },
                        {
                            "index": 2,
                            "scene": "SCENE CONTEXT: hands\nFIRST FRAME: hands knead",
                        },
                    ]
                }
            )

        monkeypatch.setattr(video_nodes, "chat_completion", fake_chat)
        shots = [
            {"index": 1, "scene": "old hero bottle", "prose": "A hero bottle."},
            {"index": 2, "scene": "old label", "prose": "A label close-up."},
        ]
        out, rewritten = asyncio.run(video_nodes._delabel_shot_scenes(shots))
        assert rewritten is True
        assert out[0]["prose"] == "Oil pours, label unseen."
        assert out[1]["prose"] == "hands. hands knead."


class TestScrubNameFromProse:
    """The product name is a supplier mention AND label-bait: a measured reel
    shipped every shot leading with 'Emile Noel Mild Olive Oil, a golden
    olive oil in a dark glass bottle, ...' despite the delabel instruction.
    Deleting the name leaves the appositive description as the subject."""

    def test_full_name_and_head_are_deleted_comma_insensitively(self):
        prose = (
            "Emile Noel Mild Olive Oil, a golden olive oil in a dark glass "
            "bottle, pours in a smooth ribbon into a warm pan. Later Emile "
            "Noel rests on the counter."
        )
        out = video_nodes._scrub_name_from_prose(
            prose, "Emile Noel, Mild Olive Oil, 690g"
        )
        assert "Emile" not in out and "Noel" not in out
        assert out.startswith("A golden olive oil in a dark glass bottle")
        assert "pours in a smooth ribbon" in out
        # The second sentence lost its subject to the head-deletion but is
        # tidied and recapitalized, never left starting with punctuation.
        assert ". Later" in out

    def test_middle_segment_alone_survives(self):
        # "apricot jam" is legitimate description — only the full sequence
        # and the manufacturer head are the printed name.
        prose = "A jar of apricot jam glows in the light."
        out = video_nodes._scrub_name_from_prose(
            prose, "Coteaux Nantais, Apricot Jam, 690g"
        )
        assert out == prose

    def test_scrub_that_would_empty_returns_original(self):
        out = video_nodes._scrub_name_from_prose("Emile Noel", "Emile Noel")
        assert out == "Emile Noel"

    def test_no_name_or_no_prose_is_identity(self):
        assert video_nodes._scrub_name_from_prose("", "X Brand") == ""
        assert video_nodes._scrub_name_from_prose("Some prose.", "") == "Some prose."

    def test_word_boundaries_protect_longer_words(self):
        # Adversarial-review repros: without \b, "Bio" hollowed "biodynamic"
        # into "dynamic" and "Emile Noel" ate the front of "Emile Noelle".
        out = video_nodes._scrub_name_from_prose(
            "A biodynamic orchard at dawn.", "Bio, Almond Butter, 250g"
        )
        assert out == "A biodynamic orchard at dawn."
        out = video_nodes._scrub_name_from_prose(
            "Emile Noelle walks past golden fields.",
            "Emile Noel, Mild Olive Oil, 690g",
        )
        assert out == "Emile Noelle walks past golden fields."


class TestSegmentPrompt:
    def test_prose_is_the_prompt_with_no_chained_furniture(self):
        shot = {
            "scene": "SCENE CONTEXT: kitchen",
            "prose": "A hand pours; the ambience continues across the cut.",
        }
        prompt = _build_segment_prompt(shot)
        assert prompt == shot["prose"]
        assert "SHOT" not in prompt and "CONTINUITY" not in prompt

    def test_scene_fallback_for_pre_prose_plans(self):
        prompt = _build_segment_prompt(
            {"scene": "SCENE CONTEXT: a mill\nFIRST FRAME: stone wheels"}
        )
        assert prompt == "a mill. stone wheels."

    def test_unverified_pack_directive_rides_the_first_segment(self):
        prompt = _build_segment_prompt({"prose": "A jar."}, unverified_pack=True)
        assert prompt.startswith("A jar.")
        assert video_nodes._UNVERIFIED_PACK_DIRECTIVE in prompt

    def test_later_segments_get_the_one_line_reminder_not_the_block(self):
        # Five copies of the 120-word block outweighed the story (v8 staged
        # a four-bottle tableau at the first seam) — segments after the first
        # keep the constraint as one sentence.
        prompt = _build_segment_prompt(
            {"prose": "A jar."}, unverified_pack=True, full_pack_directive=False
        )
        assert prompt.startswith("A jar.")
        assert video_nodes._UNVERIFIED_PACK_DIRECTIVE not in prompt
        assert video_nodes._PACK_REMINDER in prompt

    def test_verified_pack_gets_neither_block_nor_reminder(self):
        prompt = _build_segment_prompt(
            {"prose": "A jar."}, unverified_pack=False, full_pack_directive=False
        )
        assert prompt == "A jar."


# ── Cut detection and caption-window realignment (pure) ────────────────────


class TestCutSnapping:
    def test_no_cuts_is_the_normal_case_not_an_error(self):
        # The model renders cross-dissolves: measured, no frame pair above a
        # 0.04 scene score across three distinct scenes. Empty scdet output
        # keeps the planned windows exactly.
        durations, confirmed = _snap_windows_to_cuts([5.0] * 6, [])
        assert durations == [5.0] * 6
        assert confirmed == set()
        durations, confirmed = _snap_windows_to_cuts([5.0] * 6, None)
        assert durations == [5.0] * 6
        assert confirmed == set()

    def test_a_cut_near_a_boundary_snaps_it(self):
        durations, confirmed = _snap_windows_to_cuts([5.0, 5.0, 5.0], [5.6])
        assert durations == [5.6, 4.4, 5.0]
        assert confirmed == {1}
        assert sum(durations) == pytest.approx(15.0)

    def test_a_far_cut_is_ignored(self):
        durations, confirmed = _snap_windows_to_cuts([5.0, 5.0, 5.0], [7.5])
        assert durations == [5.0, 5.0, 5.0]
        assert confirmed == set()

    def test_a_snap_never_folds_a_window_away(self):
        durations, confirmed = _snap_windows_to_cuts([1.0, 5.0], [0.3])
        assert durations == [1.0, 5.0]
        assert confirmed == set()


class TestDissolveNudge:
    def test_unconfirmed_boundaries_are_nudged_into_the_shot(self):
        out = _dissolve_safe_windows([5.0, 5.0, 5.0], set())
        assert out == [5.35, 5.0, 4.65]
        assert sum(out) == pytest.approx(15.0)

    def test_confirmed_boundaries_are_left_alone(self):
        # A confirmed boundary is a real cut — captions may enter on it,
        # exactly as on the chained path.
        assert _dissolve_safe_windows([5.0, 5.0, 5.0], {1, 2}) == [5.0, 5.0, 5.0]

    def test_short_windows_are_never_drained(self):
        assert _dissolve_safe_windows([5.0, 2.0], set()) == [5.0, 2.0]


class TestDetectCuts:
    def _run(self, monkeypatch, stderr, returncode=0):
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: True)
        monkeypatch.setattr(
            video_nodes,
            "_run_ffmpeg",
            lambda args, timeout=300: subprocess.CompletedProcess(
                args=args, returncode=returncode, stdout=b"", stderr=stderr
            ),
        )
        return _detect_cuts("reel.mp4")

    def test_empty_output_is_an_empty_list_not_none(self, monkeypatch):
        assert self._run(monkeypatch, b"") == []

    def test_survivor_frames_become_cut_timestamps(self, monkeypatch):
        stderr = (
            b"[Parsed_metadata_2 @ 0x1] frame:0 pts:0 pts_time:0.0333\n"
            b"[Parsed_metadata_2 @ 0x1] lavfi.scene_score=0.436\n"
            b"[Parsed_metadata_2 @ 0x1] frame:150 pts:76800 pts_time:5.4\n"
            b"[Parsed_metadata_2 @ 0x1] lavfi.scene_score=0.61\n"
            b"[Parsed_metadata_2 @ 0x1] frame:151 pts:77312 pts_time:5.43\n"
            b"[Parsed_metadata_2 @ 0x1] lavfi.scene_score=0.31\n"
        )
        # The stream's first frame is not a cut, and one cut smeared across
        # adjacent frames collapses to a single timestamp.
        assert self._run(monkeypatch, stderr) == [5.4]

    def test_ffmpeg_failure_returns_none(self, monkeypatch):
        assert self._run(monkeypatch, b"", returncode=1) is None


# ── Orchestration: the native branch inside render_video ───────────────────


class _NativeHarness(_Harness):
    """_Harness with a forge that advertises native multishot."""

    def __init__(self, monkeypatch, *, capable=True, multishot_fail=None,
                 passes=None, **kw):
        super().__init__(monkeypatch, **kw)
        self.capable = capable
        self.multishot_fail = multishot_fail
        self.passes = passes
        self.native_requests = []

        async def _probe():
            return self.capable

        # Opt back IN over the conftest default, which pins the probe to
        # False so no pre-native test ever routes through a live forge.
        monkeypatch.setattr(shared_video, "forge_supports_multishot", _probe)

    async def _fake_generate_video(self, req, progress_cb=None):
        if req.segments is None:
            return await super()._fake_generate_video(req, progress_cb)
        self.native_requests.append(req)
        if self.multishot_fail:
            exc = RuntimeError(self.multishot_fail)
            exc.ledger = [
                {
                    "event": "failed",
                    "provider": "forge",
                    "detail": self.multishot_fail,
                }
            ]
            raise exc
        if progress_cb is not None:
            await progress_cb(50, "forge:running")
            await progress_cb(100, "forge:succeeded")
        return VideoResult(
            provider="forge",
            model="video-forge",
            video_bytes=b"NATIVE-REEL",
            duration_s=req.duration_s,
            width=1080,
            height=1920,
            cost_usd=0.0,
            ledger=[{"event": "succeeded", "provider": "forge"}],
            passes=self.passes,
        )

    def _fake_probe(self, path):
        name = os.path.basename(path)
        if name.startswith("reel_ms_"):
            dur = (
                self.native_requests[-1].duration_s
                if self.native_requests
                else 30.0
            )
            return _conformant_info(dur)
        return super()._fake_probe(path)


class TestNativeMultishotRender:
    def test_whole_reel_renders_in_one_native_call(self, monkeypatch):
        h = _NativeHarness(monkeypatch)
        state = _state([4] * 6)
        for i, shot in enumerate(state["shot_plan"]["shots"]):
            shot["prose"] = (
                f"A hand lifts the green jar in the sunlit kitchen, beat "
                f"{i + 1} unfolding; the ambience continues across the cut."
            )
        result = asyncio.run(render_video(state))

        assert result.get("status") != "failed"
        # ONE provider call replaced the six-call chained loop.
        assert len(h.native_requests) == 1
        assert h.requests == []
        req = h.native_requests[0]
        assert req.mode == "multishot"
        assert req.image_bytes == b"KEYFRAME"
        assert req.seed is not None
        assert req.idempotency_key.endswith(":ms")
        # segments[] mapping from the fitted plan: prose prompt + fitted
        # duration per segment, the sum carried on the request itself.
        assert [s["duration_s"] for s in req.segments] == [5.0] * 6
        assert req.duration_s == pytest.approx(30.0)
        for i, seg in enumerate(req.segments):
            assert seg["prompt"].startswith("A hand lifts the green jar")
            assert f"beat {i + 1}" in seg["prompt"]
            assert "SHOT" not in seg["prompt"]
        # The stored prompt is the joined prose, not the chained frame.
        assert "=== SHOT BREAK ===" not in result["video_prompt"]
        assert "A hand lifts the green jar" in result["video_prompt"]

        meta = result["video_meta"]
        assert meta["render_mode"] == "native_multishot"
        assert meta["provider"] == "forge"
        assert meta["model"] == "video-forge"
        assert meta["shot_count"] == 6
        assert meta["native_attempts"] == 1
        assert meta["concat_mode"] == "none"
        assert meta["normalized_shots"] == []
        assert meta["requested_total_s"] == pytest.approx(30.0)
        assert meta["duration_s"] == pytest.approx(
            30.0 + video_nodes._END_CARD_S
        )
        assert "multishot_fallback" not in meta
        # Ledger: ONE whole-reel entry in the same array-of-entries shape.
        assert [e["shot"] for e in meta["ledger"]] == [0]
        assert meta["ledger"][0]["render_mode"] == "native_multishot"
        assert meta["ledger"][0]["ledger"] == [
            {"event": "succeeded", "provider": "forge"}
        ]
        # Synthesized per-shot metas keep the chained shape for the
        # generation_ledger consumers and the WorkingStageTracker.
        shots_meta = meta["shots"]
        assert len(shots_meta) == 6
        assert all(m["anchor"] == "multishot" for m in shots_meta)
        assert [m["requested_s"] for m in shots_meta] == [5.0] * 6
        assert [m["rendered_s"] for m in shots_meta] == [5.0] * 6
        assert all(m["provider"] == "forge" for m in shots_meta)
        assert meta["end_card"] == "ok"

    def test_same_plan_same_key_across_deliveries(self, monkeypatch):
        # Redelivery dedup: the delabel LLM's variance must stay OUT of the
        # key (it runs after the digest), so two runs of the identical state
        # ask the provider under the identical key.
        h = _NativeHarness(monkeypatch)

        async def passthrough(shots):
            return shots, True

        monkeypatch.setattr(video_nodes, "_delabel_shot_scenes", passthrough)
        asyncio.run(render_video(_state([4] * 6, verified_pack=False)))
        first = h.native_requests[-1].idempotency_key
        asyncio.run(render_video(_state([4] * 6, verified_pack=False)))
        assert h.native_requests[-1].idempotency_key == first

    def test_prompt_machinery_change_changes_the_key(self, monkeypatch):
        # The v9-that-was-v8 incident (2026-08-20): the packaging-block fix
        # shipped, the plan LLM reproduced the identical plan, and the forge
        # answered the "new" render with the previous reel from cache —
        # because the key digested only the plan, never the built prompts.
        h = _NativeHarness(monkeypatch)

        async def passthrough(shots):
            return shots, True

        monkeypatch.setattr(video_nodes, "_delabel_shot_scenes", passthrough)
        asyncio.run(render_video(_state([4] * 6, verified_pack=False)))
        first = h.native_requests[-1].idempotency_key
        monkeypatch.setattr(
            video_nodes,
            "_UNVERIFIED_PACK_DIRECTIVE",
            "PACKAGING vNEXT: nothing readable anywhere.",
        )
        asyncio.run(render_video(_state([4] * 6, verified_pack=False)))
        assert h.native_requests[-1].idempotency_key != first

    def test_forge_output_passes_are_carried_into_meta(self, monkeypatch):
        h = _NativeHarness(
            monkeypatch,
            passes=[
                {"frames": 361, "seconds": 15.0},
                {"frames": 360, "seconds": 15.0},
            ],
        )
        result = asyncio.run(render_video(_state([4] * 6)))
        assert result.get("status") != "failed"
        assert result["video_meta"]["passes"] == h.passes

    def test_per_window_motion_is_ledger_only(self, monkeypatch):
        # Dissolve zones sit inside the planned windows and read as low
        # motion — window numbers under the floor are diagnostics, never a
        # retry trigger. Only the whole-file verdict retries.
        h = _NativeHarness(monkeypatch)
        calls = []

        def fake_window(path, start, dur):
            calls.append((round(start, 2), round(dur, 2)))
            return 0.05  # under _MIN_MOTION_YAVG — must NOT cause a retry

        monkeypatch.setattr(video_nodes, "_measure_window_motion", fake_window)
        result = asyncio.run(render_video(_state([4] * 6)))

        assert result.get("status") != "failed"
        assert len(h.native_requests) == 1  # no retry
        assert calls == [
            (0.0, 5.0), (5.0, 5.0), (10.0, 5.0),
            (15.0, 5.0), (20.0, 5.0), (25.0, 5.0),
        ]
        meta = result["video_meta"]
        assert [m["motion"] for m in meta["shots"]] == [0.05] * 6


class TestNativeGating:
    def test_health_without_multishot_uses_the_chained_path(self, monkeypatch):
        h = _NativeHarness(monkeypatch, capable=False)
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        assert h.native_requests == []
        assert len(h.requests) == 5
        meta = result["video_meta"]
        assert "render_mode" not in meta
        # Never attempted — no fallback record either.
        assert "multishot_fallback" not in meta

    def test_setting_off_never_probes_or_renders_native(self, monkeypatch):
        h = _Harness(monkeypatch)

        async def _boom():
            raise AssertionError("the probe must not run with the setting off")

        monkeypatch.setattr(shared_video, "forge_supports_multishot", _boom)
        monkeypatch.setattr(
            video_nodes._config_settings, "VIDEO_NATIVE_MULTISHOT", False
        )
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        assert len(h.requests) == 5
        assert all(r.segments is None for r in h.requests)

    def test_hero_tier_always_takes_the_existing_path(self, monkeypatch):
        h = _NativeHarness(
            monkeypatch, providers={i: "veo" for i in range(1, 7)}
        )
        result = asyncio.run(
            render_video(_state([5] * 6, quality_tier="hero"))
        )

        assert result.get("status") != "failed"
        assert h.native_requests == []
        assert len(h.requests) == 6
        assert result["video_meta"]["hero_grid_fit"] is True

    def test_make_keyframes_probe_answer_is_reused_not_reprobed(
        self, monkeypatch
    ):
        h = _NativeHarness(monkeypatch)

        async def _boom():
            raise AssertionError("render_video must reuse the state's answer")

        monkeypatch.setattr(shared_video, "forge_supports_multishot", _boom)
        state = _state([4] * 6)
        state["native_multishot_capable"] = True
        result = asyncio.run(render_video(state))

        assert result.get("status") != "failed"
        assert len(h.native_requests) == 1

    def test_a_cached_no_from_make_keyframe_stays_chained(self, monkeypatch):
        h = _NativeHarness(monkeypatch)  # probe would say yes...
        state = _state([4] * 5)
        state["native_multishot_capable"] = False  # ...but the run said no
        result = asyncio.run(render_video(state))

        assert result.get("status") != "failed"
        assert h.native_requests == []
        assert len(h.requests) == 5


class TestNativeFallback:
    def test_422_falls_back_to_the_chained_loop(self, monkeypatch):
        h = _NativeHarness(
            monkeypatch,
            multishot_fail=(
                "All video providers failed for quality_tier='standard': "
                "forge: HTTP 422 Unprocessable Entity"
            ),
        )
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        # Native attempted once, then the chained loop rendered the reel —
        # in the SAME run, keyframe still in hand.
        assert len(h.native_requests) == 1
        assert len(h.requests) == 5
        assert h.requests[0].image_bytes == b"KEYFRAME"
        meta = result["video_meta"]
        assert "render_mode" not in meta
        assert "422" in meta["multishot_fallback"]
        # The failed attempt's provenance leads the same ledger array.
        assert [e["shot"] for e in meta["ledger"]] == [0, 1, 2, 3, 4, 5]
        assert meta["ledger"][0]["status"] == "native_multishot_fallback"
        assert meta["ledger"][0]["ledger"] == [
            {
                "event": "failed",
                "provider": "forge",
                "detail": h.multishot_fail,
            }
        ]
        # The chained reel still delivered at full length.
        assert meta["duration_s"] == pytest.approx(
            25.0 + video_nodes._END_CARD_S
        )

    def test_motion_floor_buys_one_seed_bumped_retry_then_falls_back(
        self, monkeypatch
    ):
        h = _NativeHarness(monkeypatch)

        def fake_motion(path):
            if os.path.basename(path).startswith("reel_ms_"):
                return 0.05  # under the floor: a frozen native reel
            return 2.0  # chained shots are healthy

        monkeypatch.setattr(video_nodes, "_measure_motion", fake_motion)
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        # Exactly ONE seed-bumped native retry, then the chained loop.
        assert len(h.native_requests) == 2
        first, second = h.native_requests
        assert second.seed == first.seed + 1
        assert first.idempotency_key.endswith(":ms")
        assert second.idempotency_key.endswith(":ms:r2")
        assert len(h.requests) == 5
        meta = result["video_meta"]
        assert "static" in meta["multishot_fallback"]
        assert meta["ledger"][0]["status"] == "native_multishot_fallback"

    def test_a_healthy_retry_ships_the_native_reel(self, monkeypatch):
        h = _NativeHarness(monkeypatch)
        reel_measures = []

        def fake_motion(path):
            if os.path.basename(path).startswith("reel_ms_"):
                reel_measures.append(path)
                return 0.05 if len(reel_measures) == 1 else 2.0
            return 2.0

        monkeypatch.setattr(video_nodes, "_measure_motion", fake_motion)
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        assert len(h.native_requests) == 2
        assert h.requests == []
        meta = result["video_meta"]
        assert meta["render_mode"] == "native_multishot"
        assert meta["native_attempts"] == 2


class TestNativeGradeAndCaptions:
    def _spy_burn(self, monkeypatch):
        seen = {}

        async def spy(video_bytes, shots, cta, brand, durations=None,
                      grade_params=None, uniform_grade=None):
            seen["durations"] = durations
            seen["grade_params"] = grade_params
            seen["uniform_grade"] = uniform_grade
            return video_bytes, {"overlay_burn": "ok"}

        monkeypatch.setattr(video_nodes, "_burn_overlays", spy)
        return seen

    def test_one_measurement_one_uniform_grade_never_per_shot(
        self, monkeypatch
    ):
        h = _NativeHarness(monkeypatch)
        seen = self._spy_burn(monkeypatch)
        measured = []

        def fake_picture(path):
            measured.append(path)
            return {"YAVG": 90.0, "YHIGH": 200.0, "YLOW": 30.0, "SATAVG": 10.0}

        monkeypatch.setattr(video_nodes, "_measure_picture", fake_picture)
        result = asyncio.run(render_video(_state([4] * 6)))

        assert result.get("status") != "failed"
        # ONE measurement, on the whole file.
        assert len(measured) == 1
        assert os.path.basename(measured[0]).startswith("reel_ms_")
        # ONE uniform grade — never the per-shot list.
        assert seen["grade_params"] is None
        assert seen["uniform_grade"] is not None
        assert seen["uniform_grade"]["gamma"] > 1.0
        assert result["video_meta"]["grade"] == seen["uniform_grade"]

    def test_uniform_grade_chain_is_ungated(self):
        chain = _uniform_grade_chain(
            {"gamma": 1.5, "saturation": 1.2, "black": 0.06}
        )
        assert "enable=" not in chain
        assert chain.index("colorlevels") < chain.index("eq=gamma")
        assert _uniform_grade_chain(None) == ""

    def test_no_cuts_detected_keeps_planned_caption_windows(self, monkeypatch):
        # The model renders cross-dissolves, so scdet finding NOTHING is the
        # normal case: planned windows stand, nudged off the dissolve
        # boundaries for caption entry only.
        h = _NativeHarness(monkeypatch)
        seen = self._spy_burn(monkeypatch)
        monkeypatch.setattr(video_nodes, "_detect_cuts", lambda path: [])
        result = asyncio.run(render_video(_state([4] * 6)))

        assert result.get("status") != "failed"
        durations = seen["durations"]
        assert sum(durations) == pytest.approx(30.0, abs=0.05)
        assert durations == _dissolve_safe_windows([5.0] * 6, set())
        meta = result["video_meta"]
        # The ledger keeps the UN-nudged planned windows — nothing about the
        # render moved.
        assert [m["rendered_s"] for m in meta["shots"]] == [5.0] * 6
        assert "detected_cuts" not in meta

    def test_a_detected_cut_snaps_its_boundary(self, monkeypatch):
        h = _NativeHarness(monkeypatch)
        seen = self._spy_burn(monkeypatch)
        monkeypatch.setattr(video_nodes, "_detect_cuts", lambda path: [5.4])
        result = asyncio.run(render_video(_state([4] * 6)))

        assert result.get("status") != "failed"
        durations = seen["durations"]
        # Shot 2's caption window starts on the REAL cut at 5.4s.
        assert durations[0] == pytest.approx(5.4)
        assert sum(durations) == pytest.approx(30.0, abs=0.05)
        meta = result["video_meta"]
        assert meta["detected_cuts"] == [5.4]
        assert meta["shots"][0]["rendered_s"] == pytest.approx(5.4)
        assert meta["shots"][1]["rendered_s"] == pytest.approx(4.6)


# ── Provider routing and the capability probe (shared/video.py) ────────────


class TestProviderRouting:
    def test_fal_refuses_segmented_requests(self):
        req = VideoRequest(
            prompt="p", segments=[{"prompt": "a", "duration_s": 3.0}]
        )
        with pytest.raises(ProviderUnavailableError):
            asyncio.run(FalProvider().available(req, []))

    def test_veo_refuses_segmented_requests(self):
        req = VideoRequest(
            prompt="p", segments=[{"prompt": "a", "duration_s": 3.0}]
        )
        with pytest.raises(ProviderUnavailableError):
            asyncio.run(VeoProvider().available(req, []))

    def test_forge_submit_carries_the_multishot_contract(self, monkeypatch):
        fake = FakeClient(
            [("POST", "/v1/jobs", FakeResponse(202, {"job_id": "j1"}))]
        )
        monkeypatch.setattr(shared_video, "_get_http_client", lambda: fake)
        req = VideoRequest(
            prompt="joined prose",
            mode="multishot",
            image_bytes=b"\x89PNG\r\n\x1a\npix",
            duration_s=30.0,
            seed=7,
            idempotency_key="k:ms",
            segments=[{"prompt": "a", "duration_s": 3.0}],
        )
        job = asyncio.run(ForgeProvider().submit(req, []))
        assert job == "j1"
        payload = fake.calls[0][2]["json"]
        assert payload["mode"] == "multishot"
        assert payload["segments"] == [{"prompt": "a", "duration_s": 3.0}]
        assert payload["duration_s"] == 30.0
        assert payload["seed"] == 7
        assert "image_b64" in payload

    def test_plain_requests_send_no_segments_key(self, monkeypatch):
        fake = FakeClient(
            [("POST", "/v1/jobs", FakeResponse(202, {"job_id": "j1"}))]
        )
        monkeypatch.setattr(shared_video, "_get_http_client", lambda: fake)
        req = VideoRequest(prompt="one clip", mode="i2v", image_bytes=b"img")
        asyncio.run(ForgeProvider().submit(req, []))
        assert "segments" not in fake.calls[0][2]["json"]


class TestCapabilityProbe:
    def _probe(self, monkeypatch, handler):
        fake = FakeClient([("GET", "/health", handler)])
        monkeypatch.setattr(shared_video, "_get_http_client", lambda: fake)
        return asyncio.run(_real_forge_probe())

    def test_multishot_in_modes_means_capable(self, monkeypatch):
        assert (
            self._probe(
                monkeypatch,
                FakeResponse(
                    200, {"status": "ok", "modes": ["i2v", "t2v", "multishot"]}
                ),
            )
            is True
        )

    def test_a_health_without_modes_is_an_old_forge(self, monkeypatch):
        # Absent field = no support: that forge would 422 the mode literal.
        assert (
            self._probe(monkeypatch, FakeResponse(200, {"status": "ok"}))
            is False
        )

    def test_an_unreachable_forge_is_not_capable(self, monkeypatch):
        def _boom(url, kwargs):
            raise ConnectionError("refused")

        assert self._probe(monkeypatch, _boom) is False


# ── make_keyframe on the native branch ─────────────────────────────────────


class TestMakeKeyframeNativeBranch:
    def _state(self, n=7):
        return {
            "brand_id": "b",
            "calendar_item_id": "c",
            "calendar_item": {"channel": "instagram"},
            "shot_plan": {
                "shots": [
                    {
                        "index": i + 1,
                        "scene": (
                            f"SCENE CONTEXT: beat {i + 1}\n"
                            f"FIRST FRAME: frame {i + 1}"
                        ),
                    }
                    for i in range(n)
                ]
            },
            "product_image": None,
            "is_lifestyle_only": True,
        }

    def _run(self, monkeypatch, state, *, probe):
        seen = {"prompts": [], "uploads": []}

        async def fake_generate(prompt, **kw):
            seen["prompts"].append(prompt)
            return "data:image/png;base64,aGk="

        async def fake_upload(bucket, obj, data, ctype):
            seen["uploads"].append(obj)

        async def noop(*a, **kw):
            return None

        async def fail(st, message):
            return {"status": "failed", "errors": [message]}

        monkeypatch.setattr(video_nodes, "generate_image", fake_generate)
        monkeypatch.setattr(video_nodes, "async_upload_file", fake_upload)
        monkeypatch.setattr(video_nodes, "update_agent_run_step", noop)
        monkeypatch.setattr(video_nodes, "_fail", fail)
        monkeypatch.setattr(shared_video, "forge_supports_multishot", probe)
        return asyncio.run(video_nodes.make_keyframe(state)), seen

    @staticmethod
    async def _yes():
        return True

    @staticmethod
    async def _no():
        return False

    @staticmethod
    async def _boom():
        raise AssertionError("the probe must not run here")

    def test_native_branch_buys_only_the_opening_keyframe(self, monkeypatch):
        out, seen = self._run(monkeypatch, self._state(), probe=self._yes)
        # One generation, one upload: mid-reel anchors are never consumed by
        # the native render, so they are never bought.
        assert len(seen["prompts"]) == 1
        assert sorted(out["anchor_frames"]) == [0]
        assert seen["uploads"] == ["b/c/keyframe.png"]
        assert out["native_multishot_capable"] is True

    def test_without_the_capability_the_anchor_set_is_unchanged(
        self, monkeypatch
    ):
        out, _ = self._run(monkeypatch, self._state(), probe=self._no)
        assert sorted(out["anchor_frames"]) == video_nodes._anchor_indices(7)
        assert out["native_multishot_capable"] is False

    def test_hero_tier_never_probes(self, monkeypatch):
        state = {**self._state(), "quality_tier": "hero"}
        out, _ = self._run(monkeypatch, state, probe=self._boom)
        assert sorted(out["anchor_frames"]) == video_nodes._anchor_indices(7)
        assert out["native_multishot_capable"] is False

    def test_setting_off_never_probes(self, monkeypatch):
        monkeypatch.setattr(
            video_nodes._config_settings, "VIDEO_NATIVE_MULTISHOT", False
        )
        out, _ = self._run(monkeypatch, self._state(), probe=self._boom)
        assert sorted(out["anchor_frames"]) == video_nodes._anchor_indices(7)
        assert out["native_multishot_capable"] is False


class TestReelLabelGuard:
    """A rendered reel shipped a hero bottle wearing a full pseudo-label —
    prompt-side mitigation is documented as insufficient, so the native
    branch gained the same reject-and-reroll defence the image path has."""

    def test_guard_unit_flags_lettering_frames(self, monkeypatch):
        from shared import image_text_guard as itg
        from shared.image_text_guard import TextGuardVerdict

        monkeypatch.setattr(itg, "guard_enabled", lambda: True)
        monkeypatch.setattr(
            video_nodes, "_frame_jpeg_at", lambda path, t: b"jpeg"
        )

        async def fake_detect(data, content_type, allowed, *, label=""):
            # Flag only the second sampled frame.
            if label.startswith("reel@6"):
                return TextGuardVerdict(
                    flagged=True, unintended_text=["FNILLE EIL NOIL"]
                )
            return TextGuardVerdict(flagged=False)

        monkeypatch.setattr(itg, "detect_unintended_text", fake_detect)
        out = asyncio.run(
            video_nodes._reel_label_guard("reel.mp4", [4.0, 4.0, 4.0])
        )
        assert out["checked"] and out["flagged"]
        assert out["frames_checked"] == 3
        assert out["flags"] == [{"t": 6.0, "text": ["FNILLE EIL NOIL"]}]
        assert out["soft"] == []

    def test_illegible_marks_alone_are_soft_not_flagged(self, monkeypatch):
        """Unreadable label areas are what the packaging lock ASKS for — they
        must never spend the seed-bumped retry a garbled string deserves."""
        from shared import image_text_guard as itg
        from shared.image_text_guard import TextGuardVerdict

        monkeypatch.setattr(itg, "guard_enabled", lambda: True)
        monkeypatch.setattr(
            video_nodes, "_frame_jpeg_at", lambda path, t: b"jpeg"
        )

        async def fake_detect(data, content_type, allowed, *, label=""):
            if label.startswith("reel@2"):
                # Embossed neck marks: flagged by the vision model, but with
                # no readable/garbled string — soft tier.
                return TextGuardVerdict(
                    flagged=True, illegible_marks=["embossed marks on neck"]
                )
            if label.startswith("reel@6"):
                # Garbled string → hard, even alongside illegible marks.
                return TextGuardVerdict(
                    flagged=True,
                    gibberish_text=["Elano OLI"],
                    illegible_marks=["soft label area"],
                )
            if label.startswith("reel@10"):
                # Flagged with NOTHING listed: ambiguous, stays hard.
                return TextGuardVerdict(flagged=True)
            return TextGuardVerdict(flagged=False)

        monkeypatch.setattr(itg, "detect_unintended_text", fake_detect)
        out = asyncio.run(
            video_nodes._reel_label_guard("reel.mp4", [4.0] * 4)
        )
        assert out["flagged"] is True
        assert [f["t"] for f in out["flags"]] == [6.0, 10.0]
        assert out["soft"] == [{"t": 2.0, "marks": ["embossed marks on neck"]}]

    def test_only_soft_marks_never_flag_the_reel(self, monkeypatch):
        from shared import image_text_guard as itg
        from shared.image_text_guard import TextGuardVerdict

        monkeypatch.setattr(itg, "guard_enabled", lambda: True)
        monkeypatch.setattr(
            video_nodes, "_frame_jpeg_at", lambda path, t: b"jpeg"
        )

        async def fake_detect(data, content_type, allowed, *, label=""):
            return TextGuardVerdict(
                flagged=True, illegible_marks=["blurred label band"]
            )

        monkeypatch.setattr(itg, "detect_unintended_text", fake_detect)
        out = asyncio.run(video_nodes._reel_label_guard("reel.mp4", [4.0, 4.0]))
        assert out["flagged"] is False
        assert out["flags"] == []
        assert len(out["soft"]) == 2

    def test_guard_disabled_fails_open(self, monkeypatch):
        from shared import image_text_guard as itg

        monkeypatch.setattr(itg, "guard_enabled", lambda: False)
        out = asyncio.run(video_nodes._reel_label_guard("reel.mp4", [4.0]))
        assert out == {"checked": False, "flagged": False, "reason": "disabled"}

    def test_flagged_reel_buys_one_seed_bumped_retry(self, monkeypatch):
        h = _NativeHarness(monkeypatch)
        calls = []

        async def fake_guard(path, durations):
            calls.append(path)
            if len(calls) == 1:
                return {
                    "checked": True, "frames_checked": 7, "flagged": True,
                    "flags": [{"t": 15.0, "text": ["ENILLE MID OIL"]}],
                }
            return {"checked": True, "frames_checked": 7, "flagged": False,
                    "flags": []}

        monkeypatch.setattr(video_nodes, "_reel_label_guard", fake_guard)
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        assert len(h.native_requests) == 2
        assert h.native_requests[1].seed == h.native_requests[0].seed + 1
        assert h.requests == []  # never fell back to the chained loop
        meta = result["video_meta"]
        assert meta["render_mode"] == "native_multishot"
        reel_entry = next(e for e in meta["ledger"] if "label_guard" in e)
        assert reel_entry["label_guard"]["flagged"] is False

    def test_still_flagged_reel_ships_with_flags_in_meta(self, monkeypatch):
        h = _NativeHarness(monkeypatch)

        async def fake_guard(path, durations):
            return {
                "checked": True, "frames_checked": 7, "flagged": True,
                "flags": [{"t": 15.0, "text": ["ENILLE MID OIL"]}],
            }

        monkeypatch.setattr(video_nodes, "_reel_label_guard", fake_guard)
        result = asyncio.run(render_video(_state([4] * 5)))

        assert result.get("status") != "failed"
        # Retried once, then shipped anyway — a chained fallback would cost
        # 7 renders and carries the same lettering exposure.
        assert len(h.native_requests) == 2
        assert h.requests == []
        meta = result["video_meta"]
        assert meta["render_mode"] == "native_multishot"
        reel_entry = next(e for e in meta["ledger"] if "label_guard" in e)
        assert reel_entry["label_guard"]["flagged"] is True
        assert reel_entry["label_guard"]["flags"][0]["t"] == 15.0
