"""Tests for the video provider cascade (shared/video.py).

Runs standalone with plain pytest — coroutines are driven via asyncio.run and
all HTTP goes through a fake httpx.AsyncClient monkeypatched into the module."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from shared import video
from shared.video import VideoRequest, generate_video


# ── Fake httpx.AsyncClient ──────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data
        self.content = content

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Minimal httpx.AsyncClient stand-in — routes by (method, url substring).

    Each route handler is a FakeResponse, a list of FakeResponses consumed in
    order (for polling sequences), or a callable(url, kwargs) that returns a
    FakeResponse or raises."""

    is_closed = False

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get(self, url, **kwargs):
        return self._dispatch("GET", url, kwargs)

    async def post(self, url, **kwargs):
        return self._dispatch("POST", url, kwargs)

    async def put(self, url, **kwargs):
        return self._dispatch("PUT", url, kwargs)

    async def delete(self, url, **kwargs):
        return self._dispatch("DELETE", url, kwargs)

    def _dispatch(self, method, url, kwargs):
        self.calls.append((method, url, kwargs))
        for route_method, fragment, handler in self.routes:
            if route_method == method and fragment in url:
                if isinstance(handler, list):
                    return handler.pop(0)
                if callable(handler):
                    return handler(url, kwargs)
                return handler
        raise AssertionError(f"Unexpected {method} {url}")


def _raise_connect_error(url, kwargs):
    raise ConnectionError("connection refused")


@pytest.fixture
def fast_polls(monkeypatch):
    """No real sleeping between polls; no real ffprobe runs."""
    monkeypatch.setattr(video, "_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(video.shutil, "which", lambda name: None)


def _use_client(monkeypatch, fake):
    monkeypatch.setattr(video, "_get_http_client", lambda: fake)


# fal happy-path routes: submit → IN_QUEUE → IN_PROGRESS → COMPLETED → result
def _fal_routes(video_bytes=b"FAL_MP4"):
    return [
        (
            "POST",
            "queue.fal.run/fal-ai",
            FakeResponse(200, {"request_id": "req-1"}),
        ),
        (
            "GET",
            "/requests/req-1/status",
            [
                FakeResponse(200, {"status": "IN_QUEUE"}),
                FakeResponse(200, {"status": "IN_PROGRESS"}),
                FakeResponse(200, {"status": "COMPLETED"}),
            ],
        ),
        (
            "GET",
            "/requests/req-1",
            FakeResponse(200, {"video": {"url": "https://fal.media/out.mp4"}}),
        ),
        ("GET", "fal.media/out.mp4", FakeResponse(200, content=video_bytes)),
    ]


class TestCascade:
    def test_skips_unhealthy_forge_and_falls_to_fal(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "test-key")
        fake = FakeClient([("GET", "/health", _raise_connect_error)] + _fal_routes())
        _use_client(monkeypatch, fake)

        req = VideoRequest(prompt="a reel", image_url="https://cdn/img.png", duration_s=5)
        result = asyncio.run(generate_video(req))

        assert result.provider == "fal"
        assert result.video_bytes == b"FAL_MP4"
        skipped = [e for e in result.ledger if e["event"] == "skipped"]
        assert skipped and skipped[0]["provider"] == "forge"
        assert "health probe failed" in skipped[0]["detail"]

    def test_hero_tier_tries_veo_then_fal_then_forge(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "")
        monkeypatch.setattr(video.settings, "GEMINI_API_KEY", "")
        fake = FakeClient([("GET", "/health", _raise_connect_error)])
        _use_client(monkeypatch, fake)

        req = VideoRequest(prompt="hero clip", quality_tier="hero")
        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(generate_video(req))

        # Cascade order is recorded in the raised error's attached ledger
        assert [e["provider"] for e in exc_info.value.ledger] == ["veo", "fal", "forge"]

    def test_all_providers_failing_raises_runtime_error(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "")
        fake = FakeClient([("GET", "/health", _raise_connect_error)])
        _use_client(monkeypatch, fake)

        req = VideoRequest(prompt="doomed", duration_s=5)
        with pytest.raises(RuntimeError, match="All video providers failed"):
            asyncio.run(generate_video(req))


class TestForgeProvider:
    def test_healthy_forge_submits_polls_and_fetches(self, monkeypatch, fast_polls):
        fake = FakeClient(
            [
                ("GET", "/health", FakeResponse(200, {"status": "ok"})),
                ("POST", "/v1/jobs", FakeResponse(202, {"job_id": "j1"})),
                (
                    "GET",
                    "/v1/jobs/j1/result",
                    FakeResponse(200, content=b"FORGE_MP4"),
                ),
                (
                    "GET",
                    "/v1/jobs/j1",
                    [
                        FakeResponse(200, {"status": "running", "progress": 40}),
                        FakeResponse(
                            200,
                            {
                                "status": "succeeded",
                                "progress": 100,
                                "output": {
                                    "duration_s": 5.0,
                                    "width": 1080,
                                    "height": 1920,
                                    "size_bytes": 9,
                                },
                            },
                        ),
                    ],
                ),
            ]
        )
        _use_client(monkeypatch, fake)

        progress_updates = []

        async def progress_cb(pct, msg):
            progress_updates.append((pct, msg))

        req = VideoRequest(prompt="a reel", image_bytes=b"\x89PNG\r\n\x1a\npix")
        result = asyncio.run(generate_video(req, progress_cb))

        assert result.provider == "forge"
        assert result.video_bytes == b"FORGE_MP4"
        assert (result.width, result.height) == (1080, 1920)
        assert result.cost_usd == 0.0
        assert (40, "forge:running") in progress_updates
        # image bytes were sent base64-encoded
        submit_call = next(c for c in fake.calls if c[0] == "POST")
        assert "image_b64" in submit_call[2]["json"]


class TestFalProvider:
    def test_queue_status_sequence_and_cost(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "test-key")
        monkeypatch.setattr(video.settings, "FAL_COST_PER_S", 0.06)
        fake = FakeClient([("GET", "/health", _raise_connect_error)] + _fal_routes())
        _use_client(monkeypatch, fake)

        progress_updates = []

        async def progress_cb(pct, msg):
            progress_updates.append((pct, msg))

        req = VideoRequest(prompt="a reel", image_url="https://cdn/img.png", duration_s=5)
        result = asyncio.run(generate_video(req, progress_cb))

        assert result.provider == "fal"
        assert progress_updates == [
            (5, "fal:in_queue"),
            (50, "fal:in_progress"),
            (100, "fal:completed"),
        ]
        assert result.cost_usd == pytest.approx(5 * 0.06)
        # ffprobe was unavailable in this test → zeros + a ledger note
        assert (result.duration_s, result.width, result.height) == (0.0, 0, 0)
        assert any(e["event"] == "probe_skipped" for e in result.ledger)

    def test_failed_queue_status_moves_on(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "test-key")
        fake = FakeClient(
            [
                ("GET", "/health", _raise_connect_error),
                ("POST", "queue.fal.run/fal-ai", FakeResponse(200, {"request_id": "req-9"})),
                ("GET", "/requests/req-9/status", FakeResponse(200, {"status": "FAILED"})),
            ]
        )
        _use_client(monkeypatch, fake)

        req = VideoRequest(prompt="bad", image_url="https://cdn/img.png")
        with pytest.raises(RuntimeError, match="All video providers failed"):
            asyncio.run(generate_video(req))

    def test_bytes_without_url_are_uploaded_first(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "test-key")
        fake = FakeClient(
            [
                ("GET", "/health", _raise_connect_error),
                (
                    "POST",
                    "storage/upload/initiate",
                    FakeResponse(
                        200,
                        {"upload_url": "https://up.fal/x", "file_url": "https://cdn.fal/x.png"},
                    ),
                ),
                ("PUT", "up.fal/x", FakeResponse(200)),
            ]
            + _fal_routes()
        )
        _use_client(monkeypatch, fake)

        req = VideoRequest(prompt="a reel", image_bytes=b"\x89PNG\r\n\x1a\npix")
        result = asyncio.run(generate_video(req))

        submit_call = next(
            c for c in fake.calls if c[0] == "POST" and "queue.fal.run" in c[1]
        )
        assert submit_call[2]["json"]["image_url"] == "https://cdn.fal/x.png"
        assert any(e["event"] == "image_uploaded" for e in result.ledger)


class TestVeoProvider:
    def test_duration_snapping(self):
        assert video._snap_veo_duration(5) == 6  # tie rounds up
        assert video._snap_veo_duration(4.0) == 4
        assert video._snap_veo_duration(4.4) == 4
        assert video._snap_veo_duration(6.9) == 6
        assert video._snap_veo_duration(7) == 8  # tie rounds up
        assert video._snap_veo_duration(12) == 8

    def test_hero_path_snaps_duration_and_downloads_uri(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "GEMINI_API_KEY", "g-key")
        monkeypatch.setattr(video.settings, "VEO_COST_PER_S", 0.15)
        fake = FakeClient(
            [
                (
                    "POST",
                    ":predictLongRunning",
                    FakeResponse(200, {"name": "operations/op-1"}),
                ),
                (
                    "GET",
                    "/v1beta/operations/op-1",
                    [
                        FakeResponse(200, {"done": False}),
                        FakeResponse(
                            200,
                            {
                                "done": True,
                                "response": {
                                    "generateVideoResponse": {
                                        "generatedSamples": [
                                            {"video": {"uri": "https://veo.dl/v.mp4"}}
                                        ]
                                    }
                                },
                            },
                        ),
                    ],
                ),
                ("GET", "veo.dl/v.mp4", FakeResponse(200, content=b"VEO_MP4")),
            ]
        )
        _use_client(monkeypatch, fake)

        req = VideoRequest(
            prompt="hero clip",
            image_bytes=b"\xff\xd8\xffjpeg",
            duration_s=5,
            quality_tier="hero",
        )
        result = asyncio.run(generate_video(req))

        assert result.provider == "veo"
        assert result.video_bytes == b"VEO_MP4"
        submit_call = next(c for c in fake.calls if c[0] == "POST")
        params = submit_call[2]["json"]["parameters"]
        assert params["durationSeconds"] == 6  # 5 → 6
        assert params["aspectRatio"] == "9:16"
        instance = submit_call[2]["json"]["instances"][0]
        assert instance["image"]["mimeType"] == "image/jpeg"
        # the uri download must carry the API key header
        dl_call = next(c for c in fake.calls if "veo.dl/v.mp4" in c[1])
        assert dl_call[2]["headers"]["x-goog-api-key"] == "g-key"
        assert result.cost_usd == pytest.approx(6 * 0.15)


class TestLedger:
    def test_ledger_accumulates_across_providers(self, monkeypatch, fast_polls):
        monkeypatch.setattr(video.settings, "FAL_API_KEY", "test-key")
        fake = FakeClient([("GET", "/health", _raise_connect_error)] + _fal_routes())
        _use_client(monkeypatch, fake)

        req = VideoRequest(prompt="a reel", image_url="https://cdn/img.png", duration_s=5)
        result = asyncio.run(generate_video(req))

        events = [(e["provider"], e["event"]) for e in result.ledger]
        assert ("forge", "skipped") in events
        assert ("fal", "submitted") in events
        assert ("fal", "succeeded") in events
        # every entry carries the full shape
        for entry in result.ledger:
            assert set(entry) == {"ts", "provider", "model", "event", "detail"}
