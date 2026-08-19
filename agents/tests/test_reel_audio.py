"""Reel audio: measure it, bed it, normalize it — and never claim it.

Every reel shipped silent. forge/LTX renders no audio, the normalize pass
substituted anullsrc silence without saying so, and the video_jobs row wrote
`"audio": True` unconditionally, so nothing downstream could tell a reel with
a soundtrack from one without.
"""

import os

import pytest

from shared.config import (
    VIDEO_MUSIC_DUCKED_DB,
    VIDEO_MUSIC_SOLO_DB,
    VIDEO_SILENCE_PEAK_DB,
    VIDEO_TARGET_LUFS,
    VIDEO_TARGET_TRUE_PEAK_DB,
)
from workflows.video import nodes


class TestPeakMeasurement:
    def test_digital_silence_parses_as_minus_infinity(self):
        peak = nodes._peak_from_stderr(
            "[Parsed_ametadata_1 @ 0x1] lavfi.astats.Overall.Peak_level=-inf"
        )
        assert peak == float("-inf")
        assert not nodes._has_real_audio(peak)

    def test_a_real_track_is_kept(self):
        peak = nodes._peak_from_stderr(
            "lavfi.astats.Overall.Peak_level=-3.140000"
        )
        assert peak == pytest.approx(-3.14)
        assert nodes._has_real_audio(peak)

    def test_the_loudest_reported_peak_wins(self):
        # astats can print per-channel and overall entries; a quiet left
        # channel must not mask a loud right one.
        stderr = "\n".join((
            "lavfi.astats.Overall.Peak_level=-70.0",
            "lavfi.astats.Overall.Peak_level=-4.0",
        ))
        assert nodes._peak_from_stderr(stderr) == pytest.approx(-4.0)

    def test_encoder_noise_under_the_floor_is_still_silence(self):
        assert not nodes._has_real_audio(VIDEO_SILENCE_PEAK_DB - 0.1)
        assert nodes._has_real_audio(VIDEO_SILENCE_PEAK_DB + 0.1)

    def test_an_unmeasurable_track_is_treated_as_no_audio(self):
        # The safe direction: the pass lays a bed. Assuming real audio would
        # duck a bed under silence and ship a near-silent reel.
        assert nodes._peak_from_stderr("") is None
        assert not nodes._has_real_audio(None)

    def test_the_probe_decodes_no_video(self):
        cmd = nodes._astats_cmd("/tmp/reel.mp4")
        assert "-vn" in cmd
        assert cmd[-3:] == ["-f", "null", "-"]


class TestBedSelection:
    @pytest.fixture
    def library(self, tmp_path):
        (tmp_path / "upbeat").mkdir()
        for n in ("a.mp3", "b.mp3", "c.wav"):
            (tmp_path / "upbeat" / n).write_bytes(b"x")
        (tmp_path / "fallback.mp3").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        return str(tmp_path)

    def test_a_mood_folder_is_preferred_over_the_top_level(self, library):
        pick = nodes._pick_music_bed(library, ["upbeat"], "item-1")
        assert os.path.dirname(pick).endswith("upbeat")

    def test_an_unknown_mood_falls_back_to_the_top_level(self, library):
        pick = nodes._pick_music_bed(library, ["nonexistent-mood"], "item-1")
        assert os.path.basename(pick) == "fallback.mp3"

    def test_non_audio_files_are_never_picked(self, library):
        for seed in (f"item-{i}" for i in range(30)):
            pick = nodes._pick_music_bed(library, [], seed)
            assert pick.lower().endswith(nodes._AUDIO_EXTS)

    def test_the_same_item_always_gets_the_same_bed(self, library):
        # A re-render must not shuffle the soundtrack under a reviewer who
        # already approved the reel.
        picks = {nodes._pick_music_bed(library, ["upbeat"], "item-7")
                 for _ in range(5)}
        assert len(picks) == 1

    def test_different_items_spread_across_the_pool(self, library):
        picks = {
            nodes._pick_music_bed(library, ["upbeat"], f"item-{i}")
            for i in range(40)
        }
        assert len(picks) == 3, "the seed hash is not distributing"

    def test_an_empty_or_missing_library_returns_none(self, tmp_path):
        assert nodes._pick_music_bed(str(tmp_path), ["upbeat"], "i") is None
        assert nodes._pick_music_bed(
            str(tmp_path / "nope"), [], "i"
        ) is None
        assert nodes._pick_music_bed("", [], "i") is None

    def test_moods_are_slugged_and_ordered_most_specific_first(self):
        moods = nodes._music_moods(
            {"music_mood": "Warm & Uplifting", "mood": "calm"},
            {"brand_voice": {"music_mood": "calm"}},
        )
        assert moods == ["warm-uplifting", "calm"]

    def test_no_mood_anywhere_is_an_empty_list_not_a_crash(self):
        assert nodes._music_moods({}, {}) == []
        assert nodes._music_moods({"mood": "   "}, {"brand_voice": "a string"}) == []


class TestMixGraph:
    def test_video_is_stream_copied(self):
        # The burn already encoded the picture; re-encoding here would cost a
        # generation of quality for an audio change.
        cmd = nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, "/m.mp3", False)
        assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"

    def test_the_bed_loops_to_cover_a_longer_reel(self):
        cmd = nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, "/m.mp3", False)
        # A 20s track under a 30s reel would leave the last third silent.
        assert "-stream_loop" in cmd
        assert cmd[cmd.index("-stream_loop") + 1] == "-1"
        assert "atrim=0:30.000" in " ".join(cmd)

    def test_the_bed_ducks_under_real_diegetic_audio(self):
        graph = " ".join(
            nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, "/m.mp3", True)
        )
        assert f"volume={VIDEO_MUSIC_DUCKED_DB:.1f}dB" in graph
        assert "amix=inputs=2" in graph
        # duration=first keeps the reel's runtime authoritative.
        assert "duration=first" in graph
        # normalize=0: amix's default would pump the bed up whenever the
        # diegetic track goes quiet.
        assert "normalize=0" in graph

    def test_the_bed_comes_up_when_it_carries_the_reel_alone(self):
        graph = " ".join(
            nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, "/m.mp3", False)
        )
        assert f"volume={VIDEO_MUSIC_SOLO_DB:.1f}dB" in graph
        assert "amix" not in graph, "nothing to mix the bed with"
        assert VIDEO_MUSIC_SOLO_DB > VIDEO_MUSIC_DUCKED_DB

    def test_the_bed_fades_at_both_ends(self):
        graph = " ".join(
            nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, "/m.mp3", False)
        )
        assert "afade=t=in:st=0" in graph
        # The fade-out must land inside the reel, not past its end.
        assert f"afade=t=out:st={30.0 - nodes._MUSIC_FADE_OUT_S:.3f}" in graph

    def test_a_reel_shorter_than_the_fade_does_not_seek_negative(self):
        graph = " ".join(
            nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 0.5, "/m.mp3", False)
        )
        assert "afade=t=out:st=0.000" in graph
        assert "st=-" not in graph

    def test_every_path_runs_through_the_true_peak_limiter(self):
        for music, keep in (("/m.mp3", True), ("/m.mp3", False), (None, True)):
            graph = " ".join(
                nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, music, keep)
            )
            assert "alimiter=" in graph
            assert "volume=" in graph


class TestLoudnessConvergence:
    """loudnorm does not work on this material.

    Measured across the four delivered reels, its two-pass form landed at
    -11.5, -21.7, -18.2 and -20.4 LUFS against a -14.0 target, clipping twice.
    Its dynamic mode rides gain per frame, so an input range of 17-27 LU
    drifts it off target, and its warmup eats the correction on a 5s clip.
    A measured flat gain moves loudness by exactly what it applies.
    """

    SUMMARY = "\n".join((
        "[Parsed_ebur128_0 @ 0x1] t: 29.7 M: -30.5 S: -28.0 I: -19.0 LUFS",
        "[Parsed_ebur128_0 @ 0x1] Summary:",
        "  Integrated loudness:",
        "    I:         -19.9 LUFS",
        "    Threshold: -35.2 LUFS",
        "  Loudness range:",
        "    LRA:        20.3 LU",
        "  True peak:",
        "    Peak:       -2.4 dBFS",
    ))

    def test_the_summary_block_is_read_not_the_progress_lines(self):
        # ebur128 logs a running I: throughout; only the final summary is
        # the integrated measurement.
        assert nodes._parse_ebur128(self.SUMMARY) == (-19.9, -2.4, 20.3)

    def test_no_summary_is_unknown_not_on_target(self):
        assert nodes._parse_ebur128("") is None
        assert nodes._parse_ebur128("ffmpeg version 6.1") is None

    def test_the_measurement_pass_writes_nothing_and_decodes_no_video(self):
        cmd = nodes._audio_finish_cmd("/i.mp4", None, 30.0, "/m.mp3", True)
        assert cmd[-3:] == ["-f", "null", "-"]
        assert "ebur128=peak=true" in " ".join(cmd)
        assert "-vn" in cmd
        assert "-c:v" not in cmd and "0:v:0" not in cmd

    def test_the_measurement_covers_the_mix_and_the_limiter(self):
        # Measuring the source alone would aim the correction at a number
        # the delivered file never has: the bed adds loudness and the
        # limiter takes peaks back off.
        graph = " ".join(
            nodes._audio_finish_cmd("/i.mp4", None, 30.0, "/m.mp3", True)
        )
        assert "amix=inputs=2" in graph
        assert "alimiter=" in graph
        assert graph.index("alimiter=") < graph.index("ebur128=")

    def test_the_correction_is_the_distance_to_target(self):
        assert nodes._next_gain(0.0, -19.9) == pytest.approx(5.9)
        # Round two corrects the residual on top of what is already applied.
        assert nodes._next_gain(5.9, -14.7) == pytest.approx(6.6)

    def test_a_reel_already_on_target_is_left_alone(self):
        assert nodes._next_gain(0.0, VIDEO_TARGET_LUFS) == pytest.approx(0.0)

    def test_silence_does_not_ask_for_infinite_gain(self):
        assert nodes._next_gain(3.0, float("-inf")) == 3.0

    def test_gain_is_clamped_so_a_noise_floor_is_not_amplified(self):
        assert nodes._next_gain(0.0, -120.0) == nodes._MAX_MAKEUP_GAIN_DB
        assert nodes._next_gain(0.0, 40.0) == -nodes._MAX_MAKEUP_GAIN_DB

    def test_the_search_is_bounded(self):
        assert 2 <= nodes._MAX_GAIN_ROUNDS <= 6

    def test_the_gain_lands_in_the_filter_graph(self):
        graph = " ".join(nodes._audio_finish_cmd(
            "/i.mp4", "/o.mp4", 30.0, None, True, gain_db=6.6
        ))
        assert "volume=6.60dB" in graph


class TestTruePeakLimiter:
    """alimiter caps the SAMPLE peak; platforms measure the TRUE peak.

    Limiting at -1 dB delivered up to +1.2 dBTP on real reels, because
    inter-sample peaks sit above sample peaks and the AAC encode adds more.
    """

    def test_the_limiter_is_oversampled(self):
        chain = nodes._limiter_chain()
        assert f"aresample={nodes._LIMITER_OVERSAMPLE_HZ}" in chain
        assert chain.index("aresample=%d" % nodes._LIMITER_OVERSAMPLE_HZ) < \
            chain.index("alimiter=")
        # ...and comes back to the delivery rate afterwards.
        assert chain.endswith("aresample=48000")

    def test_the_oversample_rate_is_a_real_multiple_of_delivery(self):
        assert nodes._LIMITER_OVERSAMPLE_HZ % 48000 == 0
        assert nodes._LIMITER_OVERSAMPLE_HZ >= 4 * 48000

    def test_the_ceiling_leaves_headroom_under_the_platform_target(self):
        # -1.0 dB was not enough once inter-sample peaks and AAC were added.
        assert nodes._LIMITER_CEILING_DB < VIDEO_TARGET_TRUE_PEAK_DB
        assert nodes._LIMITER_CEILING_DB > -4.0, "any lower is just quiet"

    def test_the_limiter_does_not_apply_its_own_auto_level(self):
        # alimiter's level=enabled would re-normalize and undo the gain the
        # convergence loop just measured.
        assert "level=disabled" in nodes._limiter_chain()

    def test_with_no_bed_the_source_track_is_corrected_in_place(self):
        cmd = nodes._audio_finish_cmd(
            "/i.mp4", "/o.mp4", 30.0, None, True, gain_db=5.9
        )
        assert "-stream_loop" not in cmd
        assert "[0:a]volume=5.90dB" in " ".join(cmd)

    def test_the_delivered_track_matches_the_master_spec(self):
        cmd = nodes._audio_finish_cmd("/i.mp4", "/o.mp4", 30.0, "/m.mp3", False)
        assert "aresample=48000" in " ".join(cmd)
        for arg in nodes._MASTER_AUDIO_ARGS:
            assert arg in cmd


class TestHonestMetadata:
    def test_the_job_row_reports_the_measured_flag_not_a_constant(self):
        import inspect

        src = inspect.getsource(nodes.store_video)
        assert '"audio": True' not in src, (
            "video_jobs claimed audio unconditionally while reels were silent"
        )
        assert '"audio": bool(meta.get("audio"))' in src
