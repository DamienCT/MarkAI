"""Tests for the LOCAL_IMAGES path in shared/llm.py.

The local provider renders post images on our own GPU through the Video Forge
gateway instead of paying OpenAI/Gemini. It sits in front of the existing cloud
cascade and must be invisible until someone switches it on, so these tests pin
three things: it is OFF by default, it is tried FIRST when on, and it NEVER
takes an image job down with it — every local failure mode falls through to the
cloud path that runs today.

All HTTP is a fake httpx.AsyncClient monkeypatched into the module; no network,
no GPU, no forge process."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from shared import llm


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-pixels"
PNG_DATA_URI_PREFIX = "data:image/png;base64,"


# ── Fake httpx.AsyncClient ──────────────────────────────────────────────


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Routes by (method, url substring). A handler is a FakeResponse, a list
    of them consumed in order (polling sequences), or a callable that may raise."""

    is_closed = False

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get(self, url, **kwargs):
        return self._dispatch("GET", url, kwargs)

    async def post(self, url, **kwargs):
        return self._dispatch("POST", url, kwargs)

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

    def urls(self, method):
        return [url for m, url, _ in self.calls if m == method]

    def bodies(self, method):
        return [kw.get("json") for m, _, kw in self.calls if m == method]


BASE = "http://forge.test:9100"


def _forge_routes(
    *,
    poll_states=("queued", "running", "succeeded"),
    content=PNG_BYTES,
    error=None,
):
    return [
        ("POST", "/v1/images", FakeResponse(202, {"job_id": "job-1", "status": "queued"})),
        (
            "GET",
            "/v1/images/job-1/result",
            FakeResponse(200, content=content, headers={"content-type": "image/png"}),
        ),
        (
            "GET",
            "/v1/images/job-1",
            [
                FakeResponse(200, {"status": s, "progress": 0, "error": error})
                for s in poll_states
            ],
        ),
        ("DELETE", "/v1/images/job-1", FakeResponse(200, {"status": "cancelled"})),
    ]


@pytest.fixture
def local_on(monkeypatch):
    """LOCAL_IMAGES enabled with the forge credentials the container ships."""
    monkeypatch.setenv("LOCAL_IMAGES", "1")
    monkeypatch.setattr(llm.settings, "VIDEO_FORGE_URL", BASE, raising=False)
    monkeypatch.setattr(llm.settings, "VIDEO_FORGE_API_KEY", "forge-key", raising=False)
    monkeypatch.setattr(llm, "_LOCAL_IMAGE_POLL_S", 0)
    # settings may carry a LOCAL_IMAGES field of its own; the env var is the
    # documented switch, so make sure it is what the test is exercising.
    monkeypatch.delattr(llm.settings, "LOCAL_IMAGES", raising=False)


def _use_client(monkeypatch, fake):
    monkeypatch.setattr(llm, "get_http_client", lambda: fake)


def _no_cloud(monkeypatch):
    """Make any cloud attempt loudly identifiable rather than a real request."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        llm, "get_model_for_category", _async_return("gemini-3.1-flash-image")
    )

    async def _gemini(model, prompt, size):
        return "data:image/png;base64,Q0xPVUQ="  # "CLOUD"

    monkeypatch.setattr(llm, "_generate_image_gemini", _gemini)


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


# ── the flag ────────────────────────────────────────────────────────────


class TestFlag:
    def test_off_by_default(self, monkeypatch):
        monkeypatch.delenv("LOCAL_IMAGES", raising=False)
        monkeypatch.delattr(llm.settings, "LOCAL_IMAGES", raising=False)
        assert llm.local_images_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
    def test_truthy_values_enable(self, monkeypatch, value):
        monkeypatch.delattr(llm.settings, "LOCAL_IMAGES", raising=False)
        monkeypatch.setenv("LOCAL_IMAGES", value)
        assert llm.local_images_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values_stay_disabled(self, monkeypatch, value):
        monkeypatch.delattr(llm.settings, "LOCAL_IMAGES", raising=False)
        monkeypatch.setenv("LOCAL_IMAGES", value)
        assert llm.local_images_enabled() is False

    def test_a_settings_field_wins_over_the_env_var(self, monkeypatch):
        """Forward-compatible: today shared.config carries no LOCAL_IMAGES field, so
        the env var is the switch. If one is ever added it takes precedence, the same
        way every other forge setting is read from config rather than os.environ."""
        from types import SimpleNamespace

        monkeypatch.setenv("LOCAL_IMAGES", "0")
        monkeypatch.setattr(llm, "settings", SimpleNamespace(LOCAL_IMAGES=True))
        assert llm.local_images_enabled() is True

    def test_config_carries_no_local_images_field_today(self):
        """Pins the assumption the env-var path rests on."""
        assert getattr(llm.settings, "LOCAL_IMAGES", None) is None


# ── the provider itself ─────────────────────────────────────────────────


class TestLocalProvider:
    def test_submits_polls_and_returns_a_data_uri(self, monkeypatch, local_on):
        fake = FakeClient(_forge_routes())
        _use_client(monkeypatch, fake)

        ref = asyncio.run(llm._generate_image_local_forge("a jar on oak", "1024x1536"))

        assert ref.startswith(PNG_DATA_URI_PREFIX)
        import base64

        assert base64.b64decode(ref.split(",", 1)[1]) == PNG_BYTES
        # submit, then poll until terminal, then fetch the bytes
        assert fake.urls("POST") == [f"{BASE}/v1/images"]
        assert fake.urls("GET")[-1] == f"{BASE}/v1/images/job-1/result"

    def test_sends_the_api_key_and_no_preset(self, monkeypatch, local_on):
        fake = FakeClient(_forge_routes())
        _use_client(monkeypatch, fake)
        asyncio.run(llm._generate_image_local_forge("x", "1024x1024"))

        for _, _, kwargs in fake.calls:
            assert kwargs["headers"] == {"X-API-Key": "forge-key"}
        body = fake.bodies("POST")[0]
        # the gateway owns preset + negative prompt, so a model swap is an ops
        # change on the GPU box rather than a redeploy of the agents container
        assert "preset" not in body and "negative_prompt" not in body

    @pytest.mark.parametrize(
        "size,aspect",
        [
            ("1024x1024", "1:1"),
            ("1536x1024", "3:2"),
            ("1024x1536", "2:3"),
            ("1024x1792", "2:3"),  # the reel keyframe size
            ("nonsense", "1:1"),
        ],
    )
    def test_maps_pixel_sizes_to_forge_aspects(self, monkeypatch, local_on, size, aspect):
        fake = FakeClient(_forge_routes())
        _use_client(monkeypatch, fake)
        asyncio.run(llm._generate_image_local_forge("x", size))
        assert fake.bodies("POST")[0]["aspect"] == aspect

    def test_failed_job_raises(self, monkeypatch, local_on):
        fake = FakeClient(_forge_routes(poll_states=("failed",), error="OOM on the 4090"))
        _use_client(monkeypatch, fake)
        with pytest.raises(RuntimeError, match="OOM on the 4090"):
            asyncio.run(llm._generate_image_local_forge("x", "1024x1024"))

    def test_timeout_cancels_the_job_so_the_gpu_is_freed(self, monkeypatch, local_on):
        monkeypatch.setattr(llm, "_LOCAL_IMAGE_TIMEOUT_S", 0)
        fake = FakeClient(_forge_routes(poll_states=("running",)))
        _use_client(monkeypatch, fake)
        with pytest.raises(TimeoutError):
            asyncio.run(llm._generate_image_local_forge("x", "1024x1024"))
        assert fake.urls("DELETE") == [f"{BASE}/v1/images/job-1"]

    def test_missing_credentials_raise_without_any_request(self, monkeypatch, local_on):
        monkeypatch.setattr(llm.settings, "VIDEO_FORGE_API_KEY", "", raising=False)
        fake = FakeClient([])
        _use_client(monkeypatch, fake)
        with pytest.raises(RuntimeError, match="VIDEO_FORGE"):
            asyncio.run(llm._generate_image_local_forge("x", "1024x1024"))
        assert fake.calls == []

    def test_empty_body_is_an_error_not_a_broken_image(self, monkeypatch, local_on):
        fake = FakeClient(_forge_routes(content=b""))
        _use_client(monkeypatch, fake)
        with pytest.raises(ValueError, match="empty body"):
            asyncio.run(llm._generate_image_local_forge("x", "1024x1024"))


# ── position in the cascade ─────────────────────────────────────────────


class TestCascadePosition:
    def test_local_is_tried_first_when_enabled(self, monkeypatch, local_on):
        fake = FakeClient(_forge_routes())
        _use_client(monkeypatch, fake)
        _no_cloud(monkeypatch)

        ref = asyncio.run(llm._generate_image_once("a jar", size="1024x1536"))

        import base64

        assert base64.b64decode(ref.split(",", 1)[1]) == PNG_BYTES
        assert fake.urls("POST") == [f"{BASE}/v1/images"]

    def test_local_is_skipped_when_the_flag_is_off(self, monkeypatch):
        monkeypatch.delenv("LOCAL_IMAGES", raising=False)
        monkeypatch.delattr(llm.settings, "LOCAL_IMAGES", raising=False)
        fake = FakeClient([])  # any forge call would raise "Unexpected"
        _use_client(monkeypatch, fake)
        _no_cloud(monkeypatch)

        ref = asyncio.run(llm._generate_image_once("a jar", size="1024x1536"))

        assert ref == "data:image/png;base64,Q0xPVUQ="
        assert fake.calls == []

    def test_local_failure_falls_back_to_the_cloud(self, monkeypatch, local_on, caplog):
        def _refused(url, kwargs):
            raise ConnectionError("connection refused")

        fake = FakeClient([("POST", "/v1/images", _refused)])
        _use_client(monkeypatch, fake)
        _no_cloud(monkeypatch)

        with caplog.at_level("WARNING"):
            ref = asyncio.run(llm._generate_image_once("a jar", size="1024x1536"))

        assert ref == "data:image/png;base64,Q0xPVUQ="
        assert "falling back to the cloud cascade" in caplog.text

    def test_success_and_failure_both_log_which_path_ran(self, monkeypatch, local_on, caplog):
        fake = FakeClient(_forge_routes())
        _use_client(monkeypatch, fake)
        _no_cloud(monkeypatch)

        with caplog.at_level("INFO"):
            asyncio.run(llm._generate_image_once("a jar", size="1024x1536"))

        assert "Image generated LOCALLY via Video Forge" in caplog.text
        assert llm._LOCAL_IMAGE_MODEL in caplog.text

    def test_an_explicit_model_bypasses_the_local_path(self, monkeypatch, local_on):
        """A caller that names a model gets that model, flag or no flag."""
        fake = FakeClient([])
        _use_client(monkeypatch, fake)
        _no_cloud(monkeypatch)

        ref = asyncio.run(
            llm._generate_image_once("a jar", model="gemini-3.1-flash-image")
        )

        assert ref == "data:image/png;base64,Q0xPVUQ="
        assert fake.calls == []

    def test_image_edit_category_bypasses_the_local_path(self, monkeypatch, local_on):
        """The local preset is text-to-image; reference edits stay on Gemini."""
        fake = FakeClient([])
        _use_client(monkeypatch, fake)
        _no_cloud(monkeypatch)

        ref = asyncio.run(llm._generate_image_once("a jar", category="image-edit"))

        assert ref == "data:image/png;base64,Q0xPVUQ="
        assert fake.calls == []
