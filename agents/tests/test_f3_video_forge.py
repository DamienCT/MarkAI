"""Regression tests for the F3 video/forge audit fixes.

Covers:
- N-12: a configured adapter strength of 0.0 must render at 0.0, never be
  coerced back to full strength by an ``or 1.0`` default.
- N-11: a blank VIDEO_FORGE_API_KEY makes the forge UNAVAILABLE loudly
  (instead of passing the unauthenticated /health probe and 401ing later);
  a submit 401/403 raises ProviderConfigError and never fails over to paid
  fal; genuine network unavailability still falls back; production startup
  refuses a forge URL with a blank key.
- P0-10 (partial): the reel label guard samples first/mid/last frames of
  every shot window, and the chained + hero lanes run the guard the native
  lane already had.
"""

import asyncio
import logging
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import shared.video as shared_video
import workflows.video.nodes as video_nodes
from shared.video import (
    ProviderConfigError,
    VideoRequest,
    generate_video,
)
from tests.test_video_providers import (
    FakeClient,
    FakeResponse,
    _fal_routes,
    _raise_connect_error,
)

_AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# ── N-12: zeroed adapter strength stays zero ───────────────────────────────


class TestLoraStrength:
    def test_zero_strength_stays_zero(self):
        assert video_nodes._lora_strength_of({"lora_strength": 0.0}) == 0.0

    def test_null_strength_defaults_to_full(self):
        assert video_nodes._lora_strength_of({"lora_strength": None}) == 1.0

    def test_no_adapter_defaults_to_full(self):
        assert video_nodes._lora_strength_of(None) == 1.0
        assert video_nodes._lora_strength_of({}) == 1.0

    def test_fractional_strength_passes_through(self):
        assert video_nodes._lora_strength_of({"lora_strength": 0.35}) == 0.35

    def _lookup(self, monkeypatch, strength):
        async def fake_query(query, params=None):
            return [{"adapter_name": "brand-video-v1", "strength": strength}]

        monkeypatch.setattr(video_nodes, "execute_query", fake_query)
        return asyncio.run(video_nodes._brand_video_lora("brand-1"))

    def test_db_zero_strength_survives_the_lookup(self, monkeypatch):
        lora = self._lookup(monkeypatch, 0.0)
        assert lora == {"lora_name": "brand-video-v1", "lora_strength": 0.0}

    def test_db_null_strength_defaults_to_full(self, monkeypatch):
        lora = self._lookup(monkeypatch, None)
        assert lora == {"lora_name": "brand-video-v1", "lora_strength": 1.0}


# ── N-11: blank key = loudly unavailable ───────────────────────────────────


class TestBlankForgeKey:
    def test_blank_key_is_unavailable_without_probing(self, monkeypatch, caplog):
        monkeypatch.setattr(shared_video.settings, "VIDEO_FORGE_API_KEY", "")

        def _no_client():
            raise AssertionError("blank key must not reach the network")

        monkeypatch.setattr(shared_video, "_get_http_client", _no_client)
        ledger = []
        req = VideoRequest(prompt="a reel")
        with caplog.at_level(logging.ERROR, logger="shared.video"):
            ok = asyncio.run(shared_video.ForgeProvider().available(req, ledger))

        assert ok is False
        assert len(ledger) == 1
        assert ledger[0]["event"] == "skipped"
        assert "VIDEO_FORGE_API_KEY is blank" in ledger[0]["detail"]
        assert any(
            "VIDEO_FORGE_API_KEY is blank" in r.message for r in caplog.records
        )

    def test_blank_key_skip_is_recorded_in_the_cascade(self, monkeypatch):
        # Dev-box behaviour: the skip is LOUD and lands in the ledger; with
        # fal configured the render still completes (production startup
        # refuses the blank key outright — see TestProductionValidation).
        monkeypatch.setattr(shared_video.settings, "VIDEO_FORGE_API_KEY", "")
        monkeypatch.setattr(shared_video.settings, "FAL_API_KEY", "test-key")
        monkeypatch.setattr(shared_video, "_POLL_INTERVAL_S", 0)
        monkeypatch.setattr(shared_video.shutil, "which", lambda name: None)
        fake = FakeClient(_fal_routes())
        monkeypatch.setattr(shared_video, "_get_http_client", lambda: fake)

        req = VideoRequest(
            prompt="a reel", image_url="https://cdn/img.png", duration_s=5
        )
        result = asyncio.run(generate_video(req))

        assert result.provider == "fal"
        skipped = [e for e in result.ledger if e["event"] == "skipped"]
        assert skipped and skipped[0]["provider"] == "forge"
        assert "VIDEO_FORGE_API_KEY is blank" in skipped[0]["detail"]
        # The /health probe never ran — the key check comes first.
        assert not any("/health" in c[1] for c in fake.calls)


# ── N-11: submit 401/403 aborts the cascade, never pays fal ────────────────


class TestForgeAuthRejection:
    def _routes_401(self, status_code=401):
        return [
            ("GET", "/health", FakeResponse(200, {"status": "ok"})),
            ("POST", "/v1/jobs", FakeResponse(status_code, {"detail": "nope"})),
        ] + _fal_routes()

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_rejected_key_raises_config_error_not_fal(
        self, monkeypatch, status_code
    ):
        monkeypatch.setattr(
            shared_video.settings, "VIDEO_FORGE_API_KEY", "wrong-key"
        )
        monkeypatch.setattr(shared_video.settings, "FAL_API_KEY", "test-key")
        fake = FakeClient(self._routes_401(status_code))
        monkeypatch.setattr(shared_video, "_get_http_client", lambda: fake)

        req = VideoRequest(
            prompt="a reel", image_url="https://cdn/img.png", duration_s=5
        )
        with pytest.raises(ProviderConfigError) as exc_info:
            asyncio.run(generate_video(req))

        assert "VIDEO_FORGE_API_KEY" in str(exc_info.value)
        # The paid provider was never touched.
        assert not any("queue.fal.run" in c[1] for c in fake.calls)
        # The attached ledger records the config error for video_jobs.
        events = [(e["provider"], e["event"]) for e in exc_info.value.ledger]
        assert ("forge", "config_error") in events

    def test_network_unavailability_still_falls_back_to_fal(self, monkeypatch):
        monkeypatch.setattr(
            shared_video.settings, "VIDEO_FORGE_API_KEY", "good-key"
        )
        monkeypatch.setattr(shared_video.settings, "FAL_API_KEY", "test-key")
        monkeypatch.setattr(shared_video, "_POLL_INTERVAL_S", 0)
        monkeypatch.setattr(shared_video.shutil, "which", lambda name: None)
        fake = FakeClient(
            [("GET", "/health", _raise_connect_error)] + _fal_routes()
        )
        monkeypatch.setattr(shared_video, "_get_http_client", lambda: fake)

        req = VideoRequest(
            prompt="a reel", image_url="https://cdn/img.png", duration_s=5
        )
        result = asyncio.run(generate_video(req))

        assert result.provider == "fal"
        skipped = [e for e in result.ledger if e["event"] == "skipped"]
        assert skipped and "health probe failed" in skipped[0]["detail"]


# ── N-11: production refuses a forge URL with a blank key ──────────────────


class TestProductionValidation:
    def _import_config(self, tmp_path, **overrides):
        env = {
            **os.environ,
            "MARKAI_ENV": "production",
            "POSTGRES_PASSWORD": "pg-secret",
            "MINIO_SECRET_KEY": "minio-secret",
            "LITELLM_MASTER_KEY": "llm-secret",
            "PYTHONPATH": _AGENTS_DIR,
            **overrides,
        }
        # cwd without a .env so pydantic-settings reads ONLY the env dict.
        return subprocess.run(
            [sys.executable, "-c", "import shared.config"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=env,
            timeout=120,
        )

    def test_forge_url_with_blank_key_refuses_startup(self, tmp_path):
        proc = self._import_config(
            tmp_path,
            VIDEO_FORGE_URL="http://forge:9100",
            VIDEO_FORGE_API_KEY="",
        )
        assert proc.returncode != 0
        assert "VIDEO_FORGE_API_KEY" in proc.stderr

    def test_forge_url_with_key_starts(self, tmp_path):
        proc = self._import_config(
            tmp_path,
            VIDEO_FORGE_URL="http://forge:9100",
            VIDEO_FORGE_API_KEY="forge-secret",
        )
        assert proc.returncode == 0, proc.stderr

    def test_blank_forge_url_needs_no_key(self, tmp_path):
        # Explicitly disabling the forge remains legal in production.
        proc = self._import_config(
            tmp_path, VIDEO_FORGE_URL="", VIDEO_FORGE_API_KEY=""
        )
        assert proc.returncode == 0, proc.stderr


# ── P0-10: boundary frames sampled; chained/hero lanes run the guard ───────


class TestLabelGuardSampling:
    def _run_guard(self, monkeypatch, durations):
        from shared import image_text_guard as itg
        from shared.image_text_guard import TextGuardVerdict

        monkeypatch.setattr(itg, "guard_enabled", lambda: True)
        seen: list[float] = []

        def fake_frame(path, t):
            seen.append(t)
            return b"jpeg"

        monkeypatch.setattr(video_nodes, "_frame_jpeg_at", fake_frame)

        async def fake_detect(data, content_type, allowed, *, label=""):
            return TextGuardVerdict(flagged=False)

        monkeypatch.setattr(itg, "detect_unintended_text", fake_detect)
        out = asyncio.run(video_nodes._reel_label_guard("reel.mp4", durations))
        return out, sorted(seen)

    def test_first_mid_last_of_each_window(self, monkeypatch):
        out, seen = self._run_guard(monkeypatch, [4.0, 4.0])
        assert seen == pytest.approx([0.25, 2.0, 3.75, 4.25, 6.0, 7.75])
        assert out["frames_checked"] == 6

    def test_boundary_samples_stay_inside_short_windows(self, monkeypatch):
        out, seen = self._run_guard(monkeypatch, [1.0])
        # edge = dur/4 keeps first < mid < last inside the 1s window.
        assert seen == pytest.approx([0.25, 0.5, 0.75])
        assert out["frames_checked"] == 3

    def test_degenerate_window_collapses_to_one_sample(self, monkeypatch):
        out, seen = self._run_guard(monkeypatch, [0.0])
        assert seen == pytest.approx([0.0])
        assert out["frames_checked"] == 1

    def test_frame_extraction_error_fails_open(self, monkeypatch):
        from shared import image_text_guard as itg

        monkeypatch.setattr(itg, "guard_enabled", lambda: True)

        def boom(path, t):
            raise FileNotFoundError("ffmpeg not installed")

        monkeypatch.setattr(video_nodes, "_frame_jpeg_at", boom)
        out = asyncio.run(video_nodes._reel_label_guard("reel.mp4", [4.0]))
        assert out["checked"] is False
        assert out["flagged"] is False


class TestGuardOnEveryLane:
    def _fake_guard(self, calls):
        async def fake(path, durations):
            calls.append((path, list(durations)))
            return {
                "checked": True,
                "frames_checked": 6,
                "flagged": True,
                "flags": [{"t": 2.0, "text": ["ENILLE OIL"]}],
                "soft": [],
            }

        return fake

    def test_chained_lane_records_the_guard_in_meta(self, monkeypatch):
        from tests.test_video_multishot import _Harness, _state

        _Harness(monkeypatch)
        calls = []
        monkeypatch.setattr(
            video_nodes, "_reel_label_guard", self._fake_guard(calls)
        )
        result = asyncio.run(
            video_nodes.render_video(_state([4, 4, 4, 4, 4]))
        )

        assert result.get("status") != "failed"  # record, don't block
        assert len(calls) == 1
        assert calls[0][0].endswith("final.mp4")
        meta = result["video_meta"]
        assert meta["label_guard"]["flagged"] is True
        assert meta["label_guard"]["flags"][0]["text"] == ["ENILLE OIL"]
        # The per-shot ledger array keeps its shape for its consumers.
        assert [e["shot"] for e in meta["ledger"]] == [1, 2, 3, 4, 5]

    def test_hero_lane_runs_the_guard_too(self, monkeypatch):
        from tests.test_video_multishot import _Harness, _state

        _Harness(monkeypatch)
        calls = []
        monkeypatch.setattr(
            video_nodes, "_reel_label_guard", self._fake_guard(calls)
        )
        result = asyncio.run(
            video_nodes.render_video(
                _state([4, 4, 4, 4, 4], quality_tier="hero")
            )
        )

        assert result.get("status") != "failed"
        assert len(calls) == 1
        meta = result["video_meta"]
        assert meta["hero_grid_fit"] is True
        assert meta["label_guard"]["flagged"] is True

    def test_single_call_lane_runs_the_guard_too(self, monkeypatch):
        from tests.test_video_multishot import _Harness, _state

        _Harness(monkeypatch)
        monkeypatch.setattr(video_nodes, "_ffmpeg_ok", lambda: False)
        calls = []
        monkeypatch.setattr(
            video_nodes, "_reel_label_guard", self._fake_guard(calls)
        )
        result = asyncio.run(
            video_nodes.render_video(_state([4, 4, 4, 4, 4]))
        )

        assert result.get("status") != "failed"
        assert len(calls) == 1
        assert calls[0][0].endswith("raw.mp4")
        assert result["video_meta"]["label_guard"]["flagged"] is True
