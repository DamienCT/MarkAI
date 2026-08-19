"""Tests for the multi-shot reel render — duration fitting, progress mapping,
concat-list/command building, conformance checks, and the render_video
orchestration with generate_video and ffmpeg fully mocked."""

import asyncio
import os
import re
import subprocess
import sys

import pytest

# Add the agents directory to the path so workflows/shared can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shared.video as shared_video
import workflows.video.nodes as video_nodes
from shared.video import VideoResult
from workflows.video.nodes import (
    MAX_SHOT_RENDER_S,
    MIN_RENDER_SHOTS,
    MIN_SHOT_RENDER_S,
    TARGET_MAX_TOTAL_S,
    TARGET_MIN_TOTAL_S,
    TARGET_TOTAL_S,
    _allocate_durations,
    _build_concat_list,
    _build_shot_prompt,
    _concat_copy_cmd,
    _concat_reencode_cmd,
    _fit_hero_durations,
    _fit_shot_durations,
    _is_master_conformant,
    _map_shot_progress,
    _normalize_cmd,
    _split_to_min_shots,
    render_video,
)


def _shots(durations):
    return [
        {"index": i + 1, "duration_s": d, "scene": f"SCENE CONTEXT: beat {i + 1}"}
        for i, d in enumerate(durations)
    ]


class TestFitShotDurations:
    def test_clamps_into_render_range(self):
        fitted, dropped = _fit_shot_durations(_shots([1.0, 8.0, 4.0, 4.0, 4.0]))
        assert dropped == []
        assert all(
            MIN_SHOT_RENDER_S <= s["duration_s"] <= MAX_SHOT_RENDER_S for s in fitted
        )
        assert fitted[0]["duration_s"] >= MIN_SHOT_RENDER_S
        assert fitted[1]["duration_s"] == MAX_SHOT_RENDER_S

    def test_stretches_short_plans_toward_five_seconds(self):
        # 4 shots x 3s = 12s → stretch to 4 x 5s = 20s (their ceiling, and
        # exactly the master-spec floor — the 30s target is out of reach)
        fitted, _ = _fit_shot_durations(_shots([3, 3, 3, 3]))
        assert sum(s["duration_s"] for s in fitted) == pytest.approx(
            TARGET_MIN_TOTAL_S, abs=0.1
        )
        assert all(s["duration_s"] == MAX_SHOT_RENDER_S for s in fitted)

    @pytest.mark.parametrize("count", [6, 7, 8, 9, 10])
    def test_six_to_ten_shot_plans_land_on_the_thirty_second_target(self, count):
        # The whole point of the fitter: 6-8 beats (what plan_shots asks for)
        # must realise ~30s, not merely "somewhere inside 20-35".
        fitted, dropped = _fit_shot_durations(_shots([3] * count))
        assert dropped == []
        assert len(fitted) == count
        total = sum(s["duration_s"] for s in fitted)
        assert total == pytest.approx(TARGET_TOTAL_S, abs=0.05)
        assert all(
            MIN_SHOT_RENDER_S <= s["duration_s"] <= MAX_SHOT_RENDER_S
            for s in fitted
        )

    def test_target_is_hit_whatever_the_planned_weights(self):
        # Uneven beat weights still sum to the target; the heavier beats just
        # get the longer clips.
        fitted, _ = _fit_shot_durations(_shots([5, 3, 4, 3, 5, 4, 3]))
        total = sum(s["duration_s"] for s in fitted)
        assert total == pytest.approx(TARGET_TOTAL_S, abs=0.05)
        assert fitted[0]["duration_s"] > fitted[1]["duration_s"]

    def test_short_plan_is_best_effort_under_target(self):
        # 3 shots cap out at 15s — under target but nothing to drop or add
        fitted, dropped = _fit_shot_durations(_shots([2, 2, 2]))
        assert dropped == []
        assert sum(s["duration_s"] for s in fitted) == pytest.approx(15.0)

    def test_eight_shot_plan_keeps_every_beat(self):
        # 8 x 5s clamps to 40s, but 8 x 3s = 24s fits the ceiling — so the
        # target is distributed instead of beats being thrown away.
        fitted, dropped = _fit_shot_durations(_shots([5] * 8))
        assert dropped == []
        assert [s["index"] for s in fitted] == [1, 2, 3, 4, 5, 6, 7, 8]
        assert sum(s["duration_s"] for s in fitted) == pytest.approx(
            TARGET_TOTAL_S, abs=0.05
        )
        assert all(s["duration_s"] == pytest.approx(3.75) for s in fitted)

    def test_hard_ceiling_is_never_exceeded(self):
        # Only a plan too long to fit even at MIN_SHOT_RENDER_S loses beats.
        for count in range(4, 20):
            fitted, dropped = _fit_shot_durations(_shots([5] * count))
            total = sum(s["duration_s"] for s in fitted)
            assert total <= TARGET_MAX_TOTAL_S + 0.01, count
            assert len(fitted) + len(dropped) == count
            if count * MIN_SHOT_RENDER_S <= TARGET_MAX_TOTAL_S:
                assert dropped == [], count

    def test_drop_never_leaves_total_under_target(self):
        # 12 x 3s = 36s → drop one → 33s, still >= 20s
        fitted, dropped = _fit_shot_durations(_shots([3] * 12))
        assert len(dropped) == 1
        total = sum(s["duration_s"] for s in fitted)
        assert TARGET_MIN_TOTAL_S <= total <= TARGET_MAX_TOTAL_S

    def test_single_shot_never_dropped(self):
        fitted, dropped = _fit_shot_durations(_shots([9.0]))
        assert dropped == []
        assert len(fitted) == 1
        assert fitted[0]["duration_s"] == MAX_SHOT_RENDER_S

    def test_inputs_not_mutated(self):
        shots = _shots([1.0, 2.0])
        _fit_shot_durations(shots)
        assert shots[0]["duration_s"] == 1.0


class TestAllocateDurations:
    def test_splits_target_proportionally(self):
        out = _allocate_durations([2.0, 1.0, 1.0], 30.0, 3.0, 20.0)
        assert sum(out) == pytest.approx(30.0)
        assert out == [15.0, 7.5, 7.5]

    def test_pins_at_bounds_and_reshares_the_rest(self):
        # The 10x weight cannot take more than hi=5 — the surplus goes back
        # to the other two, which then also hit their ceiling.
        out = _allocate_durations([10.0, 1.0, 1.0], 15.0, 3.0, 5.0)
        assert out == [5.0, 5.0, 5.0]

    def test_target_clamped_into_the_reachable_band(self):
        assert sum(_allocate_durations([1] * 4, 30.0, 3.0, 5.0)) == pytest.approx(20.0)
        assert sum(_allocate_durations([1] * 12, 30.0, 3.0, 5.0)) == pytest.approx(36.0)

    def test_sums_exactly_despite_rounding(self):
        for count in range(1, 12):
            out = _allocate_durations([1.0] * count, 30.0, 3.0, 5.0)
            expected = min(max(30.0, count * 3.0), count * 5.0)
            assert sum(out) == pytest.approx(expected, abs=0.01), count

    def test_zero_weights_and_empty(self):
        assert _allocate_durations([], 30.0, 3.0, 5.0) == []
        out = _allocate_durations([0, 0, 0, 0, 0, 0], 30.0, 3.0, 5.0)
        assert out == [5.0] * 6


class TestSplitToMinShots:
    def test_short_plans_are_split_to_the_floor(self):
        for n in (1, 2, 3):
            out = _split_to_min_shots(_shots([5.0] * n))
            assert len(out) == MIN_RENDER_SHOTS

    def test_four_or_more_shots_untouched(self):
        shots = _shots([4, 4, 4, 4])
        assert _split_to_min_shots(shots) == shots

    def test_second_half_is_marked_as_continuation(self):
        out = _split_to_min_shots(_shots([5.0, 4.0, 4.0]))
        # The longest beat (shot 1) was split; the second half carries the
        # continuation marker and points back at the plan index.
        assert "CONTINUATION" in out[1]["scene"]
        assert out[1]["split_from"] == out[0]["index"] == 1

    def test_split_then_refit_reaches_target_floor(self):
        # 3 x 5s = 15s (< 20s floor) → split + refit → 4 x 5s = 20s
        out = _split_to_min_shots(_shots([5.0, 5.0, 5.0]))
        fitted, dropped = _fit_shot_durations(out)
        assert dropped == []
        assert sum(s["duration_s"] for s in fitted) >= TARGET_MIN_TOTAL_S

    def test_inputs_not_mutated(self):
        shots = _shots([5.0])
        _split_to_min_shots(shots)
        assert len(shots) == 1
        assert "CONTINUATION" not in shots[0]["scene"]


class TestFitHeroDurations:
    def test_only_grid_values_are_requested(self):
        # Veo bills the snapped value, so every request must already sit on
        # the {4, 6} grid — requested == snapped == billed.
        fitted, dropped = _fit_hero_durations(_shots([5.0, 4.0, 3.0, 4.6]))
        assert dropped == []
        assert all(s["duration_s"] in (4.0, 6.0) for s in fitted)
        # 4 shots cap at 4 x 6s = 24s — the closest the grid gets to 30s.
        assert sum(s["duration_s"] for s in fitted) == 24.0

    @pytest.mark.parametrize(
        "count,expected", [(5, 30.0), (6, 30.0), (7, 30.0), (8, 32.0)]
    )
    def test_grid_totals_track_the_target(self, count, expected):
        fitted, dropped = _fit_hero_durations(_shots([4.0] * count))
        assert dropped == []
        total = sum(s["duration_s"] for s in fitted)
        assert total == expected
        assert total <= TARGET_MAX_TOTAL_S
        assert abs(total - TARGET_TOTAL_S) <= 2.0

    def test_six_five_second_shots_stay_under_ceiling(self):
        # 6 x 5s would bill 36s on Veo's grid — half the shots take 4s → 30s.
        fitted, _ = _fit_hero_durations(_shots([5.0] * 6))
        total = sum(s["duration_s"] for s in fitted)
        assert total <= TARGET_MAX_TOTAL_S
        assert all(s["duration_s"] in (4.0, 6.0) for s in fitted)
        # The 6s slots go to the highest-priority beats (plan order on ties).
        assert fitted[0]["duration_s"] == 6.0
        assert fitted[-1]["duration_s"] == 4.0

    def test_over_long_plans_drop_trailing_shots(self):
        # 12 shots cannot fit the 35s ceiling even at 4s each.
        fitted, dropped = _fit_hero_durations(_shots([4.0] * 12))
        assert len(fitted) == 8
        assert [s["index"] for s in dropped] == [9, 10, 11, 12]
        assert sum(s["duration_s"] for s in fitted) <= TARGET_MAX_TOTAL_S

    def test_inputs_not_mutated(self):
        shots = _shots([5.0, 5.0])
        _fit_hero_durations(shots)
        assert all(s["duration_s"] == 5.0 for s in shots)


class TestVideoWorkflowBudget:
    """The workflow timeout must cover MAX_SHOTS sequential renders."""

    def test_budget_covers_every_shot_plus_finishing(self):
        from shared.config import (
            VIDEO_FINISHING_BUDGET_S,
            VIDEO_MAX_REEL_SHOTS,
            settings,
            video_workflow_timeout_s,
        )

        per_shot = settings.VIDEO_RENDER_TIMEOUT_S
        budget = video_workflow_timeout_s(600)
        assert budget >= VIDEO_MAX_REEL_SHOTS * per_shot + VIDEO_FINISHING_BUDGET_S
        # The reel's shot cap and the budget's shot cap are the same number.
        assert VIDEO_MAX_REEL_SHOTS == video_nodes.MAX_SHOTS

    def test_single_call_cascade_floor_is_kept(self):
        from shared.config import settings, video_workflow_timeout_s

        # The legacy path walks up to 3 providers inside ONE render call.
        assert video_workflow_timeout_s(0) >= 3 * settings.VIDEO_RENDER_TIMEOUT_S

    def test_never_shorter_than_the_generic_workflow_timeout(self):
        from shared.config import video_workflow_timeout_s

        assert video_workflow_timeout_s(10**6) == 10**6

    def test_nats_ack_wait_outlives_the_workflow_budget(self):
        # JetStream must never redeliver a message while its reel is still
        # rendering — ack_wait is derived from the SAME helper plus a buffer.
        import shared.nats_consumer as nats_consumer
        from shared.config import video_workflow_timeout_s

        assert nats_consumer.VIDEO_ACK_WAIT_SECONDS > video_workflow_timeout_s(
            nats_consumer.WORKFLOW_TIMEOUT_SECONDS
        )

    def test_only_the_video_subject_carries_the_long_ack_wait(self):
        # A planning/content message must not sit unredelivered for the reel
        # budget (~hours) when a worker dies mid-job.
        import shared.nats_consumer as nats_consumer

        assert (
            nats_consumer.ACK_WAIT_SECONDS
            == nats_consumer.WORKFLOW_TIMEOUT_SECONDS + 120
        )
        assert nats_consumer.ACK_WAIT_SECONDS < nats_consumer.VIDEO_ACK_WAIT_SECONDS

        import worker

        by_subject = {s: wait for s, _d, _st, wait in worker.SUBSCRIPTIONS}
        assert by_subject["video.render"] == nats_consumer.VIDEO_ACK_WAIT_SECONDS
        assert all(
            wait is None for subj, wait in by_subject.items() if subj != "video.render"
        )

    def test_per_shot_render_is_bounded_so_the_budget_is_a_real_bound(self):
        # shared.video gives EVERY provider in the cascade its own
        # VIDEO_RENDER_TIMEOUT_S deadline, so the shots x T budget only holds
        # because render_video wraps each shot in its own wait_for.
        import inspect

        src = inspect.getsource(video_nodes.render_video)
        assert "asyncio.wait_for(" in src
        assert "VIDEO_RENDER_TIMEOUT_S" in src

    def test_finishing_budget_covers_the_ffmpeg_passes_it_names(self):
        from shared.config import (
            VIDEO_AUDIO_TIMEOUT_S,
            VIDEO_BURN_TIMEOUT_S,
            VIDEO_CONCAT_TIMEOUT_S,
            VIDEO_FINISHING_BUDGET_S,
            VIDEO_MAX_REEL_SHOTS,
            VIDEO_NORMALIZE_TIMEOUT_S,
        )

        # Worst case: every clip is non-forge and needs its own normalize pass,
        # then concat, then the overlay burn, then the audio finishing pass.
        assert VIDEO_FINISHING_BUDGET_S == (
            VIDEO_MAX_REEL_SHOTS * VIDEO_NORMALIZE_TIMEOUT_S
            + VIDEO_CONCAT_TIMEOUT_S
            + VIDEO_BURN_TIMEOUT_S
            + VIDEO_AUDIO_TIMEOUT_S
        )


class TestMapShotProgress:
    def test_single_shot_is_identity(self):
        assert _map_shot_progress(0, 1, 42) == 42

    def test_windows_are_proportional_and_monotonic(self):
        values = []
        for shot in range(5):
            for pct in (0, 50, 100):
                values.append(_map_shot_progress(shot, 5, pct))
        assert values == sorted(values)
        assert values[0] == 0
        assert values[-1] <= video_nodes._CONCAT_PROGRESS_START

    def test_out_of_range_percent_is_clamped(self):
        assert _map_shot_progress(0, 4, -10) == 0
        assert _map_shot_progress(3, 4, 250) <= video_nodes._CONCAT_PROGRESS_START


class TestConcatBuilders:
    def test_concat_list_format_and_quote_escaping(self):
        content = _build_concat_list(["/tmp/a.mp4", "/tmp/it's.mp4"])
        lines = content.strip().split("\n")
        assert lines[0] == "file '/tmp/a.mp4'"
        assert "'\\''" in lines[1]

    def test_concat_copy_cmd_is_stream_copy(self):
        cmd = _concat_copy_cmd("list.txt", "final.mp4")
        assert cmd[-1] == "final.mp4"
        assert "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
        assert "concat" in cmd

    def test_concat_reencode_cmd_targets_master_spec(self):
        cmd = _concat_reencode_cmd(["a.mp4", "b.mp4"], "final.mp4")
        assert cmd[-1] == "final.mp4"
        assert cmd.count("-i") == 2
        joined = " ".join(cmd)
        assert "concat=n=2:v=1:a=1" in joined
        assert "-crf 19" in joined
        assert "scale=1080:1920" in joined
        assert "-ar 48000" in joined

    def test_normalize_cmd_adds_silence_when_no_audio(self):
        with_audio = " ".join(_normalize_cmd("in.mp4", "out.mp4", True))
        without_audio = " ".join(_normalize_cmd("in.mp4", "out.mp4", False))
        assert "anullsrc" not in with_audio
        assert "anullsrc" in without_audio
        for cmd in (with_audio, without_audio):
            assert "-crf 19" in cmd
            assert "fps=30" in cmd
            assert "-ar 48000" in cmd
        assert _normalize_cmd("in.mp4", "out.mp4", True)[-1] == "out.mp4"

    def test_normalize_cmd_real_audio_keeps_video_length_authoritative(self):
        # Real audio + known duration: apad + -t, never -shortest (which
        # would truncate the VIDEO to a slightly-short audio track).
        cmd = _normalize_cmd("in.mp4", "out.mp4", True, 4.2)
        joined = " ".join(cmd)
        assert "-shortest" not in joined
        assert "apad" in joined
        assert "-t 4.200" in joined
        assert cmd[-1] == "out.mp4"

    def test_normalize_cmd_shortest_only_without_duration_or_audio(self):
        # anullsrc silence is infinite — -shortest is the stop condition.
        assert "-shortest" in _normalize_cmd("in.mp4", "out.mp4", False, 4.2)
        # Real audio but no probed duration: fall back to -shortest rather
        # than an unbounded apad.
        assert "-shortest" in _normalize_cmd("in.mp4", "out.mp4", True, None)


def _conformant_info(duration):
    return {
        "duration": duration,
        "video": {
            "codec": "h264",
            "width": 1080,
            "height": 1920,
            "pix_fmt": "yuv420p",
            "fps": "30/1",
        },
        "audio": {"codec": "aac", "sample_rate": 48000},
    }


class TestMasterConformance:
    def test_conformant(self):
        assert _is_master_conformant(_conformant_info(4.0)) is True

    def test_none_and_missing_video(self):
        assert _is_master_conformant(None) is False
        assert _is_master_conformant({"duration": 4.0, "video": None}) is False

    def test_wrong_sample_rate_or_missing_audio(self):
        info = _conformant_info(4.0)
        info["audio"]["sample_rate"] = 44100
        assert _is_master_conformant(info) is False
        info["audio"] = None
        assert _is_master_conformant(info) is False

    def test_wrong_fps_or_size(self):
        info = _conformant_info(4.0)
        info["video"]["fps"] = "24/1"
        assert _is_master_conformant(info) is False
        info = _conformant_info(4.0)
        info["video"]["width"] = 720
        assert _is_master_conformant(info) is False


class TestShotPrompt:
    def test_first_shot_has_no_continuity_block(self):
        prompt = _build_shot_prompt({"scene": "SCENE CONTEXT: open"}, 0, 5)
        assert "SHOT 1 of 5" in prompt
        assert "CONTINUITY" not in prompt
        assert "9:16" in prompt

    def test_chained_shot_carries_change_one_thing(self):
        prompt = _build_shot_prompt({"scene": "SCENE CONTEXT: mid"}, 2, 5)
        assert "CONTINUITY" in prompt
        assert "changing exactly one thing" in prompt

    def test_last_shot_loops_back(self):
        prompt = _build_shot_prompt({"scene": "SCENE CONTEXT: end"}, 4, 5)
        assert "loops cleanly" in prompt


# ── render_video orchestration (generate_video + ffmpeg mocked) ────────────


def _plan(durations):
    return {
        "hook_line": "hook",
        "shots": _shots(durations),
        "caption": "cap",
        "hashtags": [],
        "cta": "go",
    }


def _state(durations, keyframe=b"KEYFRAME", quality_tier="standard"):
    # No run_id on purpose: update_agent_run_step no-ops without one.
    return {
        "brand_id": "brand-1",
        "calendar_item_id": "item-1",
        "shot_plan": _plan(durations),
        "keyframe_bytes": keyframe,
        "quality_tier": quality_tier,
    }


class _Harness:
    """Wires fake generate_video / ffmpeg / probe into video_nodes."""

    def __init__(self, monkeypatch, providers=None, costs=None, fail_at=None):
        self.requests = []
        self.progress = []
        self.ffmpeg_calls = []
        self.updates = []
        self.providers = providers or {}
        self.costs = costs or {}
        self.fail_at = fail_at
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: True)
        monkeypatch.setattr(video_nodes, "_ffprobe_ok", lambda: True)
        monkeypatch.setattr(video_nodes, "_run_ffmpeg", self._fake_run_ffmpeg)
        monkeypatch.setattr(video_nodes, "_probe_shot", self._fake_probe)
        monkeypatch.setattr(video_nodes, "execute_update", self._fake_execute_update)
        monkeypatch.setattr(shared_video, "generate_video", self._fake_generate_video)

    async def _fake_execute_update(self, query, params=None):
        self.updates.append((query, params))
        if params and "patch" in (params or {}):
            self.progress.append(params["patch"])
        return 1

    async def _fake_generate_video(self, req, progress_cb=None):
        call_no = len(self.requests) + 1
        self.requests.append(req)
        if self.fail_at == call_no:
            exc = RuntimeError("all providers failed")
            exc.ledger = [{"event": "failed", "provider": "forge"}]
            raise exc
        if progress_cb is not None:
            await progress_cb(50, "forge:running")
            await progress_cb(100, "forge:succeeded")
        provider = self.providers.get(call_no, "forge")
        return VideoResult(
            provider=provider,
            model="video-forge" if provider == "forge" else "fal-model",
            video_bytes=f"CLIP{call_no}".encode(),
            duration_s=req.duration_s,
            width=1080,
            height=1920,
            cost_usd=self.costs.get(call_no, 0.0),
            ledger=[{"event": "succeeded", "provider": provider}],
        )

    def _fake_run_ffmpeg(self, args, timeout=300):
        self.ffmpeg_calls.append(args)
        out_path = args[-1]
        if out_path.endswith(".png"):
            data = b"PNGFRAME"
        else:
            data = b"CONCAT-FINAL"
        with open(out_path, "wb") as fh:
            fh.write(data)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b"", stderr=b"")

    def _fake_probe(self, path):
        name = os.path.basename(path)
        if name == "final.mp4":
            return _conformant_info(sum(r.duration_s for r in self.requests))
        # Per-shot files probe as master-conformant with the requested length.
        match = re.search(r"_(\d+)\.mp4$", name)
        idx = int(match.group(1)) if match else 1
        return _conformant_info(self.requests[idx - 1].duration_s)


class TestRenderVideoMultiShot:
    def test_five_shots_chained_and_concatenated(self, monkeypatch):
        h = _Harness(monkeypatch)
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result.get("status") != "failed"
        # One provider call per shot
        assert len(h.requests) == 5
        # Shot 1 starts from the keyframe; later shots chain from the previous
        # shot's extracted last frame, but only _MAX_CHAIN_DEPTH hops before
        # re-anchoring — nothing is rendered further downstream than that.
        assert h.requests[0].mode == "i2v"
        assert h.requests[0].image_bytes == b"KEYFRAME"
        assert all(r.mode == "i2v" for r in h.requests)
        sources = [r.image_bytes for r in h.requests]
        assert sources == [
            b"KEYFRAME",  # depth 0
            b"PNGFRAME",  # depth 1
            b"PNGFRAME",  # depth 2 — the cap
            b"KEYFRAME",  # re-anchored
            b"PNGFRAME",  # depth 1 again
        ]
        # Per-shot idempotency keys are distinct
        keys = [r.idempotency_key for r in h.requests]
        assert len(set(keys)) == 5
        assert all(k.endswith(f":s{i + 1}") for i, k in enumerate(keys))
        # Fitted durations forwarded per shot — 5 shots cap at 5 x 5s = 25s,
        # the closest they can get to the 30s target.
        assert all(r.duration_s == MAX_SHOT_RENDER_S for r in h.requests)
        # A re-anchored shot needs no last frame from its predecessor, so the
        # extraction count drops with the re-anchors.
        png_calls = [c for c in h.ffmpeg_calls if c[-1].endswith(".png")]
        mp4_calls = [c for c in h.ffmpeg_calls if c[-1].endswith("final.mp4")]
        assert len(png_calls) == 3
        assert len(mp4_calls) == 1
        assert "copy" in mp4_calls[0]
        # Final bytes come from the concat output
        assert result["video_bytes"] == b"CONCAT-FINAL"
        meta = result["video_meta"]
        assert meta["provider"] == "forge"
        assert meta["shot_count"] == 5
        assert meta["concat_mode"] == "copy"
        # Delivered length is footage plus the branded end card.
        assert meta["duration_s"] == pytest.approx(25.0 + video_nodes._END_CARD_S)
        assert meta["requested_total_s"] == pytest.approx(25.0)
        assert meta["cost_usd"] == 0.0
        # Per-shot ledger array preserved for video_jobs.generation_ledger
        assert [entry["shot"] for entry in meta["ledger"]] == [1, 2, 3, 4, 5]
        assert all("ledger" in entry for entry in meta["ledger"])

    def test_non_forge_shot_is_normalized_and_costs_summed(self, monkeypatch):
        h = _Harness(monkeypatch, providers={2: "fal"}, costs={2: 0.5})
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result.get("status") != "failed"
        meta = result["video_meta"]
        # fal output is never master-encoded agents-side → normalize pass ran
        norm_calls = [c for c in h.ffmpeg_calls if "norm_02.mp4" in c[-1]]
        assert len(norm_calls) == 1
        assert "-crf" in norm_calls[0]
        assert meta["normalized_shots"] == [2]
        assert meta["provider"] == "forge+fal"
        assert meta["cost_usd"] == pytest.approx(0.5)
        # Mixed encode sources (forge master + local normalize) must NEVER
        # stream-copy — parameter-set mismatches splice silently.
        assert meta["concat_mode"] == "reencode"
        concat_calls = [c for c in h.ffmpeg_calls if c[-1].endswith("final.mp4")]
        assert len(concat_calls) == 1
        assert "-filter_complex" in concat_calls[0]
        assert "copy" not in concat_calls[0]

    def test_all_normalized_shots_may_stream_copy(self, monkeypatch):
        # Every clip re-encoded by the same local ffmpeg pass → one encoder
        # → the lossless concat-demuxer copy path is safe again.
        h = _Harness(monkeypatch, providers={i: "fal" for i in range(1, 6)})
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result.get("status") != "failed"
        meta = result["video_meta"]
        assert meta["normalized_shots"] == [1, 2, 3, 4, 5]
        assert meta["concat_mode"] == "copy"

    def test_normalize_passes_probed_duration_for_real_audio(self, monkeypatch):
        # The fal shot probes with audio → its normalize command must use
        # apad + -t (video length authoritative), not -shortest.
        h = _Harness(monkeypatch, providers={2: "fal"})
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result.get("status") != "failed"
        norm_call = next(c for c in h.ffmpeg_calls if "norm_02.mp4" in c[-1])
        assert "-shortest" not in norm_call
        assert "apad" in " ".join(norm_call)
        assert "-t" in norm_call

    def test_shot_failure_fails_whole_item_with_ledger(self, monkeypatch):
        h = _Harness(monkeypatch, fail_at=2, costs={1: 0.75})
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result["status"] == "failed"
        assert any("shot 2/5" in e for e in result["errors"])
        assert result["video_bytes"] is None
        # Only shots 1-2 were attempted
        assert len(h.requests) == 2
        # Partial spend on paid shots before the failure lands in the failed
        # video_jobs row's cost_usd column, not only inside the ledger blob.
        job_inserts = [p for q, p in h.updates if "INSERT INTO video_jobs" in q]
        assert len(job_inserts) == 1
        assert job_inserts[0]["cost_usd"] == pytest.approx(0.75)

    def test_short_plans_are_split_to_reach_the_20s_floor(self, monkeypatch):
        # 1-3 usable shots can never reach the 20s master-spec minimum
        # (N x 5s) — the longest beats are split before rendering.
        for durations in ([4.0], [5.0, 5.0], [5.0, 5.0, 5.0]):
            h = _Harness(monkeypatch)
            result = asyncio.run(render_video(_state(durations)))

            assert result.get("status") != "failed"
            assert len(h.requests) == MIN_RENDER_SHOTS
            assert (
                sum(r.duration_s for r in h.requests) >= TARGET_MIN_TOTAL_S
            )
            meta = result["video_meta"]
            assert meta["shot_count"] == MIN_RENDER_SHOTS
            assert meta["split_to_min_shots"] is True
            assert meta["duration_s"] >= TARGET_MIN_TOTAL_S
            # Chained i2v carries the beat across the split halves, until the
            # depth cap cuts back to the keyframe.
            assert [r.image_bytes for r in h.requests] == [
                b"KEYFRAME", b"PNGFRAME", b"PNGFRAME", b"KEYFRAME",
            ]

    @pytest.mark.parametrize("count", [6, 7, 8])
    def test_six_to_eight_shot_plans_render_a_thirty_second_reel(
        self, monkeypatch, count
    ):
        # The user-facing contract: a normal plan (6-8 beats) comes out at
        # ~30s, every shot inside the renderable 3-5s band.
        h = _Harness(monkeypatch)
        state = _state([4] * count)
        for i, shot in enumerate(state["shot_plan"]["shots"]):
            shot["overlay_text"] = f"Beat {i + 1}"
        result = asyncio.run(render_video(state))

        assert result.get("status") != "failed"
        assert len(h.requests) == count
        requested = [r.duration_s for r in h.requests]
        assert all(MIN_SHOT_RENDER_S <= d <= MAX_SHOT_RENDER_S for d in requested)
        assert sum(requested) == pytest.approx(TARGET_TOTAL_S, abs=0.05)
        meta = result["video_meta"]
        assert meta["shot_count"] == count
        assert meta["dropped_shots"] == []
        assert meta["requested_total_s"] == pytest.approx(TARGET_TOTAL_S, abs=0.05)
        # The footage lands on target; the end card ships on top of it.
        assert meta["duration_s"] == pytest.approx(
            TARGET_TOTAL_S + video_nodes._END_CARD_S, abs=0.05
        )
        # Every beat still gets its own on-screen line at a readable
        # length. The CTA is no longer among them - it moved to the card -
        # so the count is one line per beat rather than beats-minus-one.
        assert meta["overlay_lines"] == count
        assert meta["end_card"] == "ok"

    def test_four_shot_plan_still_renders_a_valid_shorter_reel(self, monkeypatch):
        # An under-length plan is never padded with fabricated beats: it
        # renders 4 x 5s = 20s, the master-spec floor, and still burns text.
        h = _Harness(monkeypatch)
        state = _state([3, 3, 3, 3])
        for i, shot in enumerate(state["shot_plan"]["shots"]):
            shot["overlay_text"] = f"Beat {i + 1}"
        result = asyncio.run(render_video(state))

        assert result.get("status") != "failed"
        assert len(h.requests) == 4
        assert all(r.duration_s == MAX_SHOT_RENDER_S for r in h.requests)
        meta = result["video_meta"]
        assert meta["shot_count"] == 4
        assert "split_to_min_shots" not in meta
        assert meta["duration_s"] == pytest.approx(
            TARGET_MIN_TOTAL_S + video_nodes._END_CARD_S
        )
        assert TARGET_MIN_TOTAL_S <= meta["duration_s"] <= TARGET_MAX_TOTAL_S
        assert meta["overlay_burn"] == "ok"

    def test_over_long_plan_stays_under_the_hard_ceiling(self, monkeypatch):
        # 13 beats cannot fit 35s even at 3s each — the trailing beats are
        # dropped and recorded, and the reel stays legal.
        h = _Harness(monkeypatch)
        result = asyncio.run(render_video(_state([4] * 13)))

        assert result.get("status") != "failed"
        total = sum(r.duration_s for r in h.requests)
        assert total <= TARGET_MAX_TOTAL_S
        meta = result["video_meta"]
        assert meta["dropped_shots"] == [12, 13]
        assert meta["shot_count"] == len(h.requests) == 11

    def test_hero_tier_fits_veo_grid_and_stays_under_ceiling(self, monkeypatch):
        # 6 x 5s shots would snap+bill to 36s on Veo — over the 35s spec.
        h = _Harness(monkeypatch, providers={i: "veo" for i in range(1, 7)})
        result = asyncio.run(
            render_video(_state([5, 5, 5, 5, 5, 5], quality_tier="hero"))
        )

        assert result.get("status") != "failed"
        requested = [r.duration_s for r in h.requests]
        assert all(d in (4.0, 6.0) for d in requested)
        assert TARGET_MIN_TOTAL_S <= sum(requested) <= TARGET_MAX_TOTAL_S
        assert result["video_meta"]["hero_grid_fit"] is True

    def test_ffmpeg_missing_degrades_to_single_call(self, monkeypatch):
        h = _Harness(monkeypatch)
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: False)
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result.get("status") != "failed"
        assert len(h.requests) == 1
        assert (
            result["video_meta"]["multi_shot_fallback"]
            == "ffmpeg/ffprobe unavailable"
        )
        assert "CUT TO:" in result["video_prompt"]
        # Legacy flat ledger (not the per-shot array) and single-call meta
        meta = result["video_meta"]
        assert meta["ledger"] == [{"event": "succeeded", "provider": "forge"}]
        assert "concat_mode" not in meta
        assert result["video_bytes"] == b"CLIP1"

    def test_ffprobe_missing_also_degrades_to_single_call(self, monkeypatch):
        # ffmpeg alone is not enough: without ffprobe every clip would look
        # audio-less and real diegetic audio would be replaced with silence.
        h = _Harness(monkeypatch)
        monkeypatch.setattr(video_nodes, "_ffprobe_ok", lambda: False)
        result = asyncio.run(render_video(_state([4, 4, 4, 4, 4])))

        assert result.get("status") != "failed"
        assert len(h.requests) == 1
        assert (
            result["video_meta"]["multi_shot_fallback"]
            == "ffmpeg/ffprobe unavailable"
        )

    @pytest.mark.parametrize("count", [5, 8])
    def test_progress_is_monotonic_across_shots(self, monkeypatch, count):
        h = _Harness(monkeypatch)
        result = asyncio.run(render_video(_state([4] * count)))
        assert result.get("status") != "failed"

        import json as _json

        percents = [
            _json.loads(p)["video_progress"]["percent"] for p in h.progress
        ]
        assert percents == sorted(percents)
        assert percents[-1] == 100
        # Every shot owns a distinct, non-empty slice of the 0..95 window.
        stages = [
            _json.loads(p)["video_progress"]["stage"] for p in h.progress
        ]
        assert sum(1 for s in stages if s.startswith(f"shot {count}/")) >= 1
