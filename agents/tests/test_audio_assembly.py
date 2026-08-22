"""The reel's audio is one level-matched timeline, not seven cold restarts.

Measured on the delivered reel the user rejected: RMS stepped up to +15.9 dB
in half a second at shot joins (each shot's LTX ambience began at whatever
level the model gave it), and the end card dropped -54.9 dB to digital
silence. The user heard the joins as "music restarting every time a new
caption appears" — the seams coincided with the old per-shot captions.
"""

import asyncio
import subprocess

import workflows.video.nodes as nodes
from workflows.video.nodes import (
    _MAX_SHOT_MATCH_DB,
    _assemble_audio,
    _assemble_audio_cmd,
    _diegetic_gains,
)


class TestDiegeticGains:
    def test_shots_are_matched_to_the_median_not_a_fixed_target(self):
        gains = _diegetic_gains([-20.0, -30.0, -25.0])
        # Median is -25: the loud shot comes down, the quiet one comes up.
        assert gains == [-5.0, 5.0, 0.0]

    def test_correction_is_capped_both_ways(self):
        gains = _diegetic_gains([-10.0, -60.0, -25.0])
        assert gains[0] == -_MAX_SHOT_MATCH_DB
        assert gains[1] == _MAX_SHOT_MATCH_DB

    def test_silent_and_unmeasurable_shots_are_left_alone(self):
        # +40 dB of "correction" on a noise floor is amplified hiss.
        gains = _diegetic_gains([-20.0, None, float("-inf"), -22.0])
        assert gains[1] == 0.0
        assert gains[2] == 0.0

    def test_all_unmeasurable_is_all_zero(self):
        assert _diegetic_gains([None, float("-inf")]) == [0.0, 0.0]


class TestAssembleAudioCmd:
    def _cmd(self, end_card_s=2.4):
        return _assemble_audio_cmd(
            "/tmp/master.mp4",
            ["/tmp/s1.mp4", "/tmp/s2.mp4", "/tmp/s3.mp4"],
            [5.0, 4.0, 5.0],
            [1.5, -2.0, 0.0],
            end_card_s,
            14.0 + end_card_s,
            "/tmp/out.mp4",
        )

    def test_video_is_stream_copied_never_reencoded(self):
        cmd = self._cmd()
        joined = " ".join(cmd)
        assert "-c:v copy" in joined
        assert "-map 0:v:0" in joined

    def test_each_shot_is_leveled_faded_and_placed(self):
        graph = self._cmd()[self._cmd().index("-filter_complex") + 1]
        assert "[1:a]volume=1.50dB" in graph
        assert "[2:a]volume=-2.00dB" in graph
        # Seam fades at both ends of every clip.
        assert graph.count("afade=t=in:st=0:d=0.06") == 3
        # Placement on the single timeline: shot 2 starts at 5s, shot 3 at 9s.
        assert "adelay=5000:all=1" in graph
        assert "adelay=9000:all=1" in graph

    def test_no_acrossfade_anywhere(self):
        # acrossfade SHORTENS the timeline and desyncs from hard-cut video.
        assert "acrossfade" not in " ".join(self._cmd())

    def test_the_sum_is_unnormalized_and_padded_to_length(self):
        graph = self._cmd()[self._cmd().index("-filter_complex") + 1]
        assert "normalize=0" in graph
        assert "apad=whole_dur=16.400" in graph

    def test_end_card_gets_an_ambience_tail_with_a_release(self):
        graph = self._cmd()[self._cmd().index("-filter_complex") + 1]
        # The last shot's final seconds loop under the card...
        assert "[3:a]atrim=2.500:5.000" in graph
        assert "aloop=" in graph
        # ...and release over _TAIL_RELEASE_S instead of cutting to silence.
        assert f"d={nodes._TAIL_RELEASE_S}" in graph
        # The tail starts where the card starts.
        assert "adelay=14000:all=1[tail]" in graph

    def test_no_card_means_no_tail(self):
        graph = self._cmd(end_card_s=0.0)[
            self._cmd(end_card_s=0.0).index("-filter_complex") + 1
        ]
        assert "[tail]" not in graph
        assert "aloop" not in graph


class TestAssembleAudioStage:
    def test_failure_keeps_the_original_master(self, monkeypatch):
        monkeypatch.setattr(nodes, "_ffmpeg_ok", lambda: True)
        monkeypatch.setattr(nodes, "_measure_clip_lufs", lambda p: -25.0)

        def failing_ffmpeg(args, timeout=300):
            return subprocess.CompletedProcess(
                args=args, returncode=1, stdout=b"", stderr=b"boom"
            )

        monkeypatch.setattr(nodes, "_run_ffmpeg", failing_ffmpeg)
        out, meta = asyncio.run(
            _assemble_audio(b"MASTER", ["/tmp/s1.mp4"], [5.0], 0.0, 5.0)
        )
        assert out == b"MASTER"
        assert meta["audio_assembly"].startswith("failed:")

    def test_no_shots_is_skipped(self):
        out, meta = asyncio.run(_assemble_audio(b"MASTER", [], [], 0.0, 5.0))
        assert out == b"MASTER"
        assert meta["audio_assembly"].startswith("skipped:")

    def test_success_reports_measurements(self, monkeypatch):
        monkeypatch.setattr(nodes, "_ffmpeg_ok", lambda: True)
        lufs = iter([-20.0, -30.0])
        monkeypatch.setattr(nodes, "_measure_clip_lufs", lambda p: next(lufs))

        def ok_ffmpeg(args, timeout=300):
            with open(args[-1], "wb") as fh:
                fh.write(b"ASSEMBLED")
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=b"", stderr=b""
            )

        monkeypatch.setattr(nodes, "_run_ffmpeg", ok_ffmpeg)
        out, meta = asyncio.run(
            _assemble_audio(
                b"MASTER", ["/tmp/s1.mp4", "/tmp/s2.mp4"], [5.0, 5.0], 2.4, 12.4
            )
        )
        assert out == b"ASSEMBLED"
        assert meta["audio_assembly"] == "ok"
        assert meta["shot_lufs"] == [-20.0, -30.0]
        assert meta["shot_gains_db"] == [-5.0, 5.0]
        assert meta["seam_leveled"] is True


class TestRenderWiring:
    def test_assembly_runs_between_card_attach_and_loudness(self):
        import inspect

        # render_video has two paths; the assembly stage lives on the
        # multi-shot one, so compare LAST occurrences.
        src = inspect.getsource(nodes.render_video)
        assembly_at = src.rindex("_assemble_audio(")
        assert src.rindex("_attach_end_card(") < assembly_at < src.rindex(
            "_finish_audio("
        )
