"""Tests for the vision payload budget (shared/vision_payload.py).

The defect this locks down: every vision check base64'd the multi-MB
original into the request body — 3-6 calls per item, priced by resolution.
The helper bounds any image to a 768px-long-edge JPEG (the same budget the
video reel guard's ffmpeg frame extraction already uses) and fails open on
undecodable bytes, because every caller is itself a fail-open advisory
check. The call-site tests pin that the guard and both content-node vision
calls actually route their payload through it, and that the branded/composed
bytes ride the workflow state instead of being re-downloaded from MinIO.
"""

import asyncio
import base64
import json
import os
import sys
from io import BytesIO

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import workflows.content.nodes as content_nodes
from shared import image_text_guard as guard
from shared.vision_payload import (
    VISION_LONG_EDGE,
    downscale_for_vision,
)


def _png(w: int, h: int, color=(120, 180, 90), mode: str = "RGB") -> bytes:
    buf = BytesIO()
    Image.new(mode, (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _jpeg(w: int, h: int, color=(120, 180, 90)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ── The downscale helper ────────────────────────────────────────────────


class TestDownscaleForVision:
    def test_big_image_shrinks_under_the_pixel_budget_as_jpeg(self):
        out, mime = downscale_for_vision(_png(2048, 1024), "image/png")
        assert mime == "image/jpeg"
        assert out.startswith(b"\xff\xd8\xff")
        with Image.open(BytesIO(out)) as im:
            assert max(im.size) <= VISION_LONG_EDGE
            # Aspect preserved: 2:1 in, 2:1 out.
            assert im.size == (768, 384)

    def test_portrait_aspect_is_preserved(self):
        out, _ = downscale_for_vision(_png(1024, 2048), "image/png")
        with Image.open(BytesIO(out)) as im:
            assert im.size == (384, 768)

    def test_small_image_passes_through_untouched(self):
        data = _jpeg(320, 200)
        out, mime = downscale_for_vision(data, "image/jpeg")
        assert out is data  # not merely equal — never re-encoded
        assert mime == "image/jpeg"

    def test_passthrough_reports_the_real_format_not_the_claimed_one(self):
        # A small PNG mislabelled as JPEG must not produce a lying data URL.
        data = _png(100, 100)
        out, mime = downscale_for_vision(data, "image/jpeg")
        assert out is data
        assert mime == "image/png"

    def test_small_dimensions_but_heavy_file_still_reencodes(self):
        # 700px noise is inside the pixel budget but a PNG of it is ~1.4 MB —
        # the byte ceiling forces the JPEG re-encode anyway.
        rng = np.random.default_rng(7)
        arr = rng.integers(0, 256, (700, 700, 3), dtype=np.uint8)
        buf = BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        data = buf.getvalue()
        assert len(data) > 300 * 1024  # premise of the test

        out, mime = downscale_for_vision(data, "image/png")
        assert mime == "image/jpeg"
        assert len(out) < len(data)
        with Image.open(BytesIO(out)) as im:
            assert im.size == (700, 700)  # no upscale, no needless resize

    def test_transparency_flattens_onto_white_not_black(self):
        data = _png(1024, 1024, color=(0, 0, 0, 0), mode="RGBA")
        out, mime = downscale_for_vision(data, "image/png")
        assert mime == "image/jpeg"
        with Image.open(BytesIO(out)) as im:
            assert np.asarray(im.convert("L")).mean() > 240

    def test_broken_bytes_fail_open_with_the_original(self):
        data = b"definitely not an image"
        out, mime = downscale_for_vision(data, "image/png")
        assert out is data
        assert mime == "image/png"

    def test_empty_bytes_come_back_unchanged(self):
        out, mime = downscale_for_vision(b"", "image/png")
        assert out == b""
        assert mime == "image/png"


# ── Guard call site routes through the helper ───────────────────────────


class FakeResponse:
    def __init__(self, json_data):
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


class FakeVisionClient:
    """Captures the chat/completions request and answers a clean verdict."""

    is_closed = False

    def __init__(self):
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = {
            "visible_text": [],
            "unintended_text": [],
            "gibberish_text": [],
            "has_unintended_text": False,
            "reason": "no lettering anywhere in frame",
        }
        return FakeResponse(
            {"choices": [{"message": {"content": json.dumps(payload)}}]}
        )


@pytest.fixture
def guard_env(monkeypatch):
    """Pinned vision model + generous size gate, no live HTTP."""
    monkeypatch.setattr(guard.settings, "IMAGE_TEXT_GUARD_MODEL", "test-vision")
    monkeypatch.setattr(guard.settings, "IMAGE_TEXT_GUARD_MAX_IMAGE_MB", 20)
    fake = FakeVisionClient()
    monkeypatch.setattr(guard, "_get_http_client", lambda: fake)
    return fake


def _posted_image_url(fake: FakeVisionClient) -> str:
    _, kwargs = fake.calls[0]
    return kwargs["json"]["messages"][0]["content"][1]["image_url"]["url"]


class TestGuardCallSite:
    def test_detect_unintended_text_routes_through_the_downscaler(
        self, guard_env, monkeypatch
    ):
        seen = {}

        def fake_downscale(data, content_type="image/png"):
            seen["data"] = data
            return b"tiny-jpeg", "image/jpeg"

        monkeypatch.setattr(guard, "downscale_for_vision", fake_downscale)
        verdict = asyncio.run(
            guard.detect_unintended_text(b"ORIGINAL-BYTES", "image/png")
        )

        assert seen["data"] == b"ORIGINAL-BYTES"
        assert verdict.checked and not verdict.flagged
        expected = "data:image/jpeg;base64," + base64.b64encode(b"tiny-jpeg").decode()
        assert _posted_image_url(guard_env) == expected

    def test_guard_actually_ships_a_bounded_jpeg(self, guard_env):
        asyncio.run(guard.detect_unintended_text(_png(1600, 900), "image/png"))

        url = _posted_image_url(guard_env)
        assert url.startswith("data:image/jpeg;base64,")
        shipped = base64.b64decode(url.split(",", 1)[1])
        with Image.open(BytesIO(shipped)) as im:
            assert im.format == "JPEG"
            assert max(im.size) <= VISION_LONG_EDGE


# ── Content-node vision call sites route through the helper ─────────────


def _recorded_downscale(monkeypatch, seen: dict):
    def fake_downscale(data, content_type="image/png"):
        seen["data"] = data
        return b"small", "image/jpeg"

    monkeypatch.setattr(content_nodes, "downscale_for_vision", fake_downscale)
    return "data:image/jpeg;base64," + base64.b64encode(b"small").decode()


def _capture_chat(monkeypatch, reply: dict) -> dict:
    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return json.dumps(reply)

    monkeypatch.setattr(content_nodes, "chat_completion", fake_chat)
    return captured


def _sent_image_url(captured: dict) -> str:
    return captured["messages"][1]["content"][1]["image_url"]["url"]


class TestContentNodeCallSites:
    def test_plan_placement_sends_the_downscaled_payload(self, monkeypatch):
        seen: dict = {}
        expected_url = _recorded_downscale(monkeypatch, seen)
        captured = _capture_chat(
            monkeypatch,
            {
                "logo_xy": {"x": 0.5, "y": 0.5},
                "text_anchor": "bottom-left",
                "logo_variant": "primary",
                "reason": "empty sky",
            },
        )

        plan = asyncio.run(
            content_nodes._vision_plan_placement(b"CLEAN-ORIGINAL", ["primary"])
        )

        assert seen["data"] == b"CLEAN-ORIGINAL"
        assert _sent_image_url(captured) == expected_url
        assert plan["logo_xy"] == (0.5, 0.5)

    def test_review_branding_sends_the_downscaled_payload(self, monkeypatch):
        seen: dict = {}
        expected_url = _recorded_downscale(monkeypatch, seen)
        captured = _capture_chat(
            monkeypatch,
            {"ok": True, "reason": "card on wall, logo on sky"},
        )

        review = asyncio.run(
            content_nodes._vision_review_branding(b"BRANDED-ORIGINAL", ["primary"])
        )

        assert seen["data"] == b"BRANDED-ORIGINAL"
        assert _sent_image_url(captured) == expected_url
        assert review["ok"] is True


# ── Bytes ride the state instead of a MinIO round-trip ──────────────────


def _no_minio(monkeypatch):
    async def _refuse(bucket, obj):
        raise AssertionError(f"unexpected MinIO download: {bucket}/{obj}")

    monkeypatch.setattr(content_nodes, "async_download_file", _refuse)


def _quiet_infra(monkeypatch):
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(content_nodes, "update_agent_run_step", _noop)
    monkeypatch.setattr(content_nodes, "async_ensure_bucket", _noop)
    monkeypatch.setattr(content_nodes, "async_upload_file", _noop)


class TestBytesCarriedInState:
    def test_review_branding_reads_state_bytes_and_drops_composed(self, monkeypatch):
        _quiet_infra(monkeypatch)
        _no_minio(monkeypatch)
        seen: dict = {}

        async def fake_review(branded_bytes, variants, **kwargs):
            seen["bytes"] = branded_bytes
            return {
                "ok": True,
                "new_text_anchor": "",
                "new_logo_xy": None,
                "new_logo_variant": "",
                "reason": "card on wall, logo on sky",
                "missing_subjects": [],
                "violated_rules": [],
            }

        monkeypatch.setattr(content_nodes, "_vision_review_branding", fake_review)

        state = {
            "brand_id": "b1",
            "calendar_item_id": "c1",
            "brand": {},
            "image_format": "lifestyle",
            "branded_image": "content-images/b1/c1/branded.png",
            "branded_image_bytes": b"BRANDED-STATE-BYTES",
            "composed_image": "content-images/b1/c1/composed.png",
            "composed_image_bytes": b"COMPOSED-STATE-BYTES",
        }
        out = asyncio.run(content_nodes.review_branding(state))

        assert seen["bytes"] == b"BRANDED-STATE-BYTES"  # no re-download
        assert out["branding_review"]["ok"] is True
        # Last consumer of the composed bytes — they must not outlive it.
        assert out["composed_image_bytes"] is None

    def test_generate_mockups_reads_state_bytes_and_drops_them(self, monkeypatch):
        _quiet_infra(monkeypatch)
        _no_minio(monkeypatch)
        seen: dict = {}

        def fake_mockup(image_data, caption, platform, **kwargs):
            seen.setdefault("bytes", image_data)
            return b"MOCK"

        monkeypatch.setattr(content_nodes, "generate_mockup", fake_mockup)

        state = {
            "brand_id": "b1",
            "calendar_item_id": "c1",
            "brand": {"name": "TestBrand", "slug": "testbrand"},
            "caption": "hello",
            "branded_image": "content-images/b1/c1/branded.png",
            "branded_image_bytes": b"BRANDED-STATE-BYTES",
        }
        out = asyncio.run(content_nodes.generate_mockups_node(state))

        assert seen["bytes"] == b"BRANDED-STATE-BYTES"  # no re-download
        assert out["mockup_urls"]  # mockups still produced
        # Last consumer of the branded bytes — dropped from state here.
        assert out["branded_image_bytes"] is None
