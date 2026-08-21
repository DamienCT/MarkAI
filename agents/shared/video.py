"""Video generation provider cascade — Forge (local GPU), fal.ai, Google Veo.

Public contract (consumed by the render worker):

    from shared.video import VideoRequest, VideoResult, generate_video

``generate_video`` walks a quality-tier-dependent cascade of providers:

    draft / standard → [forge, fal]
    hero             → [veo, fal, forge]

Each provider is a class implementing the same internal protocol
(``available`` / ``submit`` / ``poll`` / ``fetch``). Every attempt appends
entries to a shared generation ledger ``{ts, provider, model, event, detail}``
returned on the final ``VideoResult`` (persisted by the caller into
``video_jobs.generation_ledger``). When every provider fails, ``RuntimeError``
is raised with the accumulated ledger attached as ``exc.ledger``.

Provider notes:
    ForgeProvider  → local GPU gateway at ``settings.VIDEO_FORGE_URL``
                     (auth ``X-API-Key``). Output is already master-encoded
                     (1080x1920 H.264+AAC faststart); marginal cost is zero.
                     The only provider that honours ``VideoRequest.segments``
                     (native multishot, ``mode="multishot"``) — probe support
                     with ``forge_supports_multishot()`` before sending one.
    FalProvider    → fal.ai queue API twin, used when ``FAL_API_KEY`` is set.
                     fal requires an image *URL*, so raw bytes are pushed
                     through fal's storage initiate-upload flow first.
    VeoProvider    → Google Veo via the Gemini API ``predictLongRunning``
                     endpoint, used when ``GEMINI_API_KEY`` is set. Generated
                     files are deleted server-side after ~2 days, so the video
                     is always downloaded immediately.

Cloud outputs (fal / veo) are returned AS-IS — NOT master-encoded; the caller
runs the finishing pass. Their width/height/duration are probed with ffprobe
when ffmpeg is installed, otherwise left at zero with a ledger note.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from shared.config import settings

logger = logging.getLogger(__name__)

# Seconds between status polls (module-level so tests can zero it out).
_POLL_INTERVAL_S = 10.0

# fal duration limits (seconds) — clamp requests to what the model accepts.
_FAL_MIN_DURATION_S = 2
_FAL_MAX_DURATION_S = 10
_FAL_PROGRESS = {"IN_QUEUE": 5, "IN_PROGRESS": 50, "COMPLETED": 100}

# Veo only accepts these clip durations (seconds).
_VEO_DURATIONS = (4, 6, 8)
_VEO_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


@dataclass
class VideoRequest:
    """A single video render request, provider-agnostic."""

    prompt: str
    mode: str = "i2v"
    image_bytes: bytes | None = None
    image_url: str | None = None
    duration_s: float = 5.0
    aspect: str = "9:16"
    audio: bool = True
    seed: int | None = None
    quality_tier: str = "standard"
    idempotency_key: str | None = None
    #: Native multishot (forge only): ordered per-scene segments, each
    #: ``{"prompt": ..., "duration_s": ...}`` plus the optional per-segment
    #: keys the gateway accepts (transition, image_b64/image_url,
    #: anchor_strength). ``duration_s`` above carries the segments' sum and
    #: ``image_bytes`` the opening keyframe. Cloud providers cannot serve a
    #: segmented request and refuse it (ProviderUnavailableError), so the
    #: cascade can never mis-route one.
    segments: list[dict[str, Any]] | None = None
    #: Per-brand adapter (forge only): a LoRA filename installed on the forge
    #: box, from the brand's ready brand_model_profiles row. Cloud providers
    #: silently ignore it — an adapter is a bonus, never a routing constraint.
    lora_name: str | None = None
    lora_strength: float = 1.0


@dataclass
class VideoResult:
    """The finished video plus provenance/cost metadata."""

    provider: str
    model: str
    video_bytes: bytes
    duration_s: float
    width: int
    height: int
    cost_usd: float
    ledger: list[dict]
    #: Forge OutputInfo render passes (native multishot splits long reels
    #: into VRAM-sized passes internally and reports them here). None from
    #: every other provider and from older forges.
    passes: list[dict] | None = None


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot serve this request — skip to the next one."""


# ── Shared httpx client (lazy singleton, mirrors shared/tools/browser.py) ──
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=60,
            limits=httpx.Limits(max_connections=20),
            follow_redirects=True,
        )
    return _http_client


def _ledger_entry(provider: str, model: str, event: str, detail: str = "") -> dict:
    """One generation-ledger row: {ts, provider, model, event, detail}."""
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "model": model,
        "event": event,
        "detail": detail,
    }


def _sniff_image_mime(data: bytes) -> str:
    """Best-effort image MIME sniff from magic bytes (defaults to PNG)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _probe_video(video_bytes: bytes) -> tuple[float, int, int] | None:
    """Return (duration_s, width, height) via ffprobe, or None if unavailable.

    Settings-independent: only requires ffprobe (ships with ffmpeg) on PATH."""
    if not shutil.which("ffprobe"):
        return None
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            tmp_path = tmp.name
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-show_entries", "format=duration",
                "-of", "json", tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]
        duration = float((data.get("format") or {}).get("duration") or 0.0)
        return duration, int(stream.get("width") or 0), int(stream.get("height") or 0)
    except Exception:
        return None
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


async def _probe_dimensions(
    video_bytes: bytes, provider: str, model: str, ledger: list[dict]
) -> tuple[float, int, int]:
    """ffprobe a cloud output for duration/width/height; zeros + ledger note
    when ffmpeg is not installed or the probe fails."""
    probed = await asyncio.to_thread(_probe_video, video_bytes)
    if probed is None:
        ledger.append(
            _ledger_entry(
                provider, model, "probe_skipped",
                "ffprobe unavailable or failed — duration/width/height set to 0",
            )
        )
        return 0.0, 0, 0
    return probed


def _snap_veo_duration(duration_s: float) -> int:
    """Snap to the nearest Veo-supported duration (4/6/8s); ties round up (5 → 6)."""
    return min(_VEO_DURATIONS, key=lambda d: (abs(d - duration_s), -d))


class VideoProvider(Protocol):
    """Common internal protocol every adapter implements."""

    name: str
    model: str

    async def available(self, req: VideoRequest, ledger: list[dict]) -> bool: ...

    async def submit(self, req: VideoRequest, ledger: list[dict]) -> str: ...

    async def poll(
        self,
        handle: str,
        ledger: list[dict],
        progress_cb: Callable[[int, str], Awaitable[None]] | None,
    ) -> dict: ...

    async def fetch(
        self, req: VideoRequest, handle: str, status: dict, ledger: list[dict]
    ) -> VideoResult: ...


class ForgeProvider:
    """Local GPU gateway ("Video Forge") — primary provider, zero marginal cost.

    API: POST /v1/jobs → 202 {job_id, status_url} (200 + same job on duplicate
    idempotency_key); GET /v1/jobs/{id} for status; GET /v1/jobs/{id}/result
    for the master-encoded MP4 bytes; DELETE /v1/jobs/{id} cancels."""

    name = "forge"

    def __init__(self) -> None:
        self.model = "video-forge"
        self.base_url = settings.VIDEO_FORGE_URL.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": settings.VIDEO_FORGE_API_KEY}

    async def available(self, req: VideoRequest, ledger: list[dict]) -> bool:
        """Health probe — skip the provider entirely when the box is unreachable."""
        client = _get_http_client()
        try:
            resp = await client.get(f"{self.base_url}/health", timeout=5)
            resp.raise_for_status()
            return True
        except Exception as exc:
            ledger.append(
                _ledger_entry(self.name, self.model, "skipped", f"health probe failed: {exc}")
            )
            return False

    async def submit(self, req: VideoRequest, ledger: list[dict]) -> str:
        payload: dict[str, Any] = {
            "mode": req.mode,
            "prompt": req.prompt,
            "duration_s": req.duration_s,
            "aspect": req.aspect,
            "resolution": "master",
            "audio": req.audio,
            "quality_tier": req.quality_tier,
        }
        if req.segments is not None:
            # Native multishot: the gateway plans its own render passes from
            # the ordered segments; mode is already "multishot" on the
            # request. An older forge 422s the mode literal — the caller's
            # fallback trigger.
            payload["segments"] = req.segments
        if req.image_bytes is not None:
            payload["image_b64"] = base64.b64encode(req.image_bytes).decode()
        elif req.image_url:
            payload["image_url"] = req.image_url
        if req.seed is not None:
            payload["seed"] = req.seed
        if req.idempotency_key:
            payload["idempotency_key"] = req.idempotency_key
        if req.lora_name:
            # Per-brand adapter — an older forge without the field 422s,
            # which the caller's fallback machinery already handles.
            payload["lora_name"] = req.lora_name
            payload["lora_strength"] = req.lora_strength
        client = _get_http_client()
        resp = await client.post(
            f"{self.base_url}/v1/jobs", json=payload, headers=self._headers(), timeout=60
        )
        resp.raise_for_status()  # 202 accepted, or 200 on duplicate idempotency_key
        job_id = (resp.json() or {}).get("job_id")
        if not job_id:
            raise RuntimeError("forge returned no job_id")
        ledger.append(_ledger_entry(self.name, self.model, "submitted", f"job_id={job_id}"))
        return job_id

    async def poll(
        self,
        handle: str,
        ledger: list[dict],
        progress_cb: Callable[[int, str], Awaitable[None]] | None,
    ) -> dict:
        client = _get_http_client()
        deadline = time.monotonic() + settings.VIDEO_RENDER_TIMEOUT_S
        while True:
            resp = await client.get(
                f"{self.base_url}/v1/jobs/{handle}", headers=self._headers(), timeout=30
            )
            resp.raise_for_status()
            status = resp.json() or {}
            state = status.get("status", "")
            if progress_cb is not None:
                await progress_cb(int(status.get("progress") or 0), f"forge:{state}")
            if state == "succeeded":
                ledger.append(_ledger_entry(self.name, self.model, "succeeded", ""))
                return status
            if state in ("failed", "cancelled"):
                raise RuntimeError(
                    f"forge job {handle} {state}: {status.get('error') or 'no detail'}"
                )
            if time.monotonic() >= deadline:
                await self._cancel(handle)
                raise RuntimeError(
                    f"forge job {handle} timed out after {settings.VIDEO_RENDER_TIMEOUT_S}s"
                )
            await asyncio.sleep(_POLL_INTERVAL_S)

    async def _cancel(self, handle: str) -> None:
        """Best-effort cancel of a timed-out forge job (frees the GPU)."""
        try:
            client = _get_http_client()
            await client.delete(
                f"{self.base_url}/v1/jobs/{handle}", headers=self._headers(), timeout=10
            )
        except Exception as exc:
            logger.debug("Forge cancel of %s failed: %s", handle, exc)

    async def fetch(
        self, req: VideoRequest, handle: str, status: dict, ledger: list[dict]
    ) -> VideoResult:
        client = _get_http_client()
        resp = await client.get(
            f"{self.base_url}/v1/jobs/{handle}/result", headers=self._headers(), timeout=600
        )
        resp.raise_for_status()
        output = status.get("output") or {}
        return VideoResult(
            provider=self.name,
            model=self.model,
            video_bytes=resp.content,
            duration_s=float(output.get("duration_s") or req.duration_s),
            width=int(output.get("width") or 0),
            height=int(output.get("height") or 0),
            cost_usd=0.0,
            ledger=ledger,
            # Multishot OutputInfo names the internal render passes; absent
            # on single-pass jobs and older forges.
            passes=output.get("passes") or None,
        )


class FalProvider:
    """fal.ai queue API — the cloud twin, used when FAL_API_KEY is configured."""

    name = "fal"

    def __init__(self) -> None:
        self.model = settings.FAL_VIDEO_MODEL
        self._status_url: str | None = None
        self._response_url: str | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Key {settings.FAL_API_KEY}"}

    @staticmethod
    def _clamp_duration(duration_s: float) -> int:
        return max(_FAL_MIN_DURATION_S, min(_FAL_MAX_DURATION_S, int(round(duration_s))))

    async def available(self, req: VideoRequest, ledger: list[dict]) -> bool:
        if req.segments is not None:
            # A segmented multishot request only the forge can honour must
            # never degrade into a single fal clip of the first prompt.
            raise ProviderUnavailableError(
                "fal cannot render native multishot segments"
            )
        if not settings.FAL_API_KEY:
            ledger.append(
                _ledger_entry(self.name, self.model, "skipped", "FAL_API_KEY not set")
            )
            return False
        return True

    async def _resolve_image_url(self, req: VideoRequest, ledger: list[dict]) -> str | None:
        """fal requires an image *URL* — upload raw bytes to fal storage first."""
        if req.image_url:
            return req.image_url
        if req.image_bytes is None:
            return None
        client = _get_http_client()
        mime = _sniff_image_mime(req.image_bytes)
        try:
            init = await client.post(
                "https://rest.alpha.fal.ai/storage/upload/initiate",
                json={"content_type": mime, "file_name": f"source.{mime.split('/')[1]}"},
                headers=self._headers(),
                timeout=30,
            )
            init.raise_for_status()
            data = init.json() or {}
            upload_url = data.get("upload_url")
            file_url = data.get("file_url")
            if not upload_url or not file_url:
                raise RuntimeError("fal initiate-upload returned no upload_url/file_url")
            put = await client.put(
                upload_url,
                content=req.image_bytes,
                headers={"Content-Type": mime},
                timeout=120,
            )
            put.raise_for_status()
            ledger.append(_ledger_entry(self.name, self.model, "image_uploaded", file_url))
            return file_url
        except Exception as exc:
            # Without a source-image URL fal cannot run i2v — skip the provider.
            raise ProviderUnavailableError(f"fal image upload failed: {exc}") from exc

    async def submit(self, req: VideoRequest, ledger: list[dict]) -> str:
        image_url = await self._resolve_image_url(req, ledger)
        payload: dict[str, Any] = {
            "prompt": req.prompt,
            "duration": self._clamp_duration(req.duration_s),
            "aspect_ratio": req.aspect,
            "audio": req.audio,
        }
        if image_url:
            payload["image_url"] = image_url
        if req.seed is not None:
            payload["seed"] = req.seed
        client = _get_http_client()
        resp = await client.post(
            f"https://queue.fal.run/{self.model}",
            json=payload,
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError("fal queue returned no request_id")
        # Prefer the queue's own URLs; fall back to the documented layout.
        self._status_url = (
            data.get("status_url")
            or f"https://queue.fal.run/{self.model}/requests/{request_id}/status"
        )
        self._response_url = (
            data.get("response_url")
            or f"https://queue.fal.run/{self.model}/requests/{request_id}"
        )
        ledger.append(
            _ledger_entry(self.name, self.model, "submitted", f"request_id={request_id}")
        )
        return request_id

    async def poll(
        self,
        handle: str,
        ledger: list[dict],
        progress_cb: Callable[[int, str], Awaitable[None]] | None,
    ) -> dict:
        client = _get_http_client()
        deadline = time.monotonic() + settings.VIDEO_RENDER_TIMEOUT_S
        while True:
            resp = await client.get(self._status_url, headers=self._headers(), timeout=30)
            resp.raise_for_status()
            status = resp.json() or {}
            state = (status.get("status") or "").upper()
            if progress_cb is not None:
                await progress_cb(_FAL_PROGRESS.get(state, 50), f"fal:{state.lower()}")
            if state == "COMPLETED":
                ledger.append(_ledger_entry(self.name, self.model, "succeeded", ""))
                return status
            if state in ("FAILED", "ERROR", "CANCELLED"):
                raise RuntimeError(f"fal request {handle} ended as {state.lower()}")
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"fal request {handle} timed out after {settings.VIDEO_RENDER_TIMEOUT_S}s"
                )
            await asyncio.sleep(_POLL_INTERVAL_S)

    @staticmethod
    def _extract_video_url(data: dict) -> str | None:
        """The video URL appears under different keys per model — try each shape."""
        video = data.get("video")
        if isinstance(video, dict) and video.get("url"):
            return video["url"]
        if data.get("video_url"):
            return data["video_url"]
        videos = data.get("videos")
        if isinstance(videos, list) and videos and isinstance(videos[0], dict):
            return videos[0].get("url")
        return None

    async def fetch(
        self, req: VideoRequest, handle: str, status: dict, ledger: list[dict]
    ) -> VideoResult:
        client = _get_http_client()
        resp = await client.get(self._response_url, headers=self._headers(), timeout=60)
        resp.raise_for_status()
        data = resp.json() or {}
        video_url = self._extract_video_url(data)
        if not video_url:
            raise RuntimeError(f"fal response for {handle} contains no video URL")
        download = await client.get(video_url, timeout=600)
        download.raise_for_status()
        video_bytes = download.content
        billed_s = self._clamp_duration(req.duration_s)
        duration, width, height = await _probe_dimensions(
            video_bytes, self.name, self.model, ledger
        )
        return VideoResult(
            provider=self.name,
            model=self.model,
            video_bytes=video_bytes,
            duration_s=duration,
            width=width,
            height=height,
            cost_usd=round(billed_s * settings.FAL_COST_PER_S, 4),
            ledger=ledger,
        )


class VeoProvider:
    """Google Veo (hero tier) via the Gemini API predictLongRunning endpoint."""

    name = "veo"

    def __init__(self) -> None:
        self.model = settings.VEO_MODEL

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": settings.GEMINI_API_KEY}

    async def available(self, req: VideoRequest, ledger: list[dict]) -> bool:
        if req.segments is not None:
            # Same routing guard as fal: segments are a forge-only contract.
            raise ProviderUnavailableError(
                "veo cannot render native multishot segments"
            )
        if not settings.GEMINI_API_KEY:
            ledger.append(
                _ledger_entry(self.name, self.model, "skipped", "GEMINI_API_KEY not set")
            )
            return False
        return True

    async def submit(self, req: VideoRequest, ledger: list[dict]) -> str:
        client = _get_http_client()
        instance: dict[str, Any] = {"prompt": req.prompt}
        image_bytes = req.image_bytes
        if image_bytes is None and req.image_url:
            download = await client.get(req.image_url, timeout=60)
            download.raise_for_status()
            image_bytes = download.content
        if image_bytes is not None:
            instance["image"] = {
                "bytesBase64Encoded": base64.b64encode(image_bytes).decode(),
                "mimeType": _sniff_image_mime(image_bytes),
            }
        payload = {
            "instances": [instance],
            "parameters": {
                # Veo supports only 9:16 and 16:9 — anything else renders portrait.
                "aspectRatio": req.aspect if req.aspect in ("9:16", "16:9") else "9:16",
                "durationSeconds": _snap_veo_duration(req.duration_s),
                "resolution": "720p",
            },
        }
        resp = await client.post(
            f"{_VEO_API_BASE}/models/{self.model}:predictLongRunning",
            json=payload,
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        operation_name = (resp.json() or {}).get("name")
        if not operation_name:
            raise RuntimeError("veo predictLongRunning returned no operation name")
        ledger.append(
            _ledger_entry(self.name, self.model, "submitted", f"operation={operation_name}")
        )
        return operation_name

    async def poll(
        self,
        handle: str,
        ledger: list[dict],
        progress_cb: Callable[[int, str], Awaitable[None]] | None,
    ) -> dict:
        client = _get_http_client()
        started = time.monotonic()
        deadline = started + settings.VIDEO_RENDER_TIMEOUT_S
        while True:
            resp = await client.get(
                f"{_VEO_API_BASE}/{handle}", headers=self._headers(), timeout=30
            )
            resp.raise_for_status()
            status = resp.json() or {}
            if progress_cb is not None:
                # The operation exposes no numeric progress — report elapsed time.
                elapsed = time.monotonic() - started
                pct = min(90, max(5, int(100 * elapsed / settings.VIDEO_RENDER_TIMEOUT_S)))
                await progress_cb(pct, "veo:running")
            if status.get("error"):
                raise RuntimeError(f"veo operation {handle} failed: {status['error']}")
            if status.get("done"):
                ledger.append(_ledger_entry(self.name, self.model, "succeeded", ""))
                return status
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"veo operation {handle} timed out after {settings.VIDEO_RENDER_TIMEOUT_S}s"
                )
            await asyncio.sleep(_POLL_INTERVAL_S)

    async def fetch(
        self, req: VideoRequest, handle: str, status: dict, ledger: list[dict]
    ) -> VideoResult:
        response = status.get("response") or {}
        samples = (response.get("generateVideoResponse") or {}).get("generatedSamples") or []
        if not samples:
            raise RuntimeError(f"veo operation {handle} returned no generated samples")
        video = samples[0].get("video") or {}
        if video.get("bytesBase64Encoded"):
            video_bytes = base64.b64decode(video["bytesBase64Encoded"])
        elif video.get("uri"):
            # Generated files are deleted after ~2 days — download immediately.
            # The file endpoint requires the API key header too.
            client = _get_http_client()
            download = await client.get(video["uri"], headers=self._headers(), timeout=600)
            download.raise_for_status()
            video_bytes = download.content
        else:
            raise RuntimeError(
                f"veo sample for {handle} carries neither uri nor bytesBase64Encoded"
            )
        billed_s = _snap_veo_duration(req.duration_s)
        duration, width, height = await _probe_dimensions(
            video_bytes, self.name, self.model, ledger
        )
        return VideoResult(
            provider=self.name,
            model=self.model,
            video_bytes=video_bytes,
            duration_s=duration,
            width=width,
            height=height,
            cost_usd=round(billed_s * settings.VEO_COST_PER_S, 4),
            ledger=ledger,
        )


async def forge_supports_multishot() -> bool:
    """One /health probe: does the forge gateway speak native multishot?

    The extended gateway advertises ``"modes": ["i2v", "t2v", "multishot"]``
    in its /health payload. An older forge has no ``modes`` field at all and
    would 422 a ``mode="multishot"`` submit (mode literal validation), so an
    absent field means no support — as does an unreachable box. Callers
    cache the answer per render run; this function performs one GET per
    call.
    """
    client = _get_http_client()
    base = settings.VIDEO_FORGE_URL.rstrip("/")
    try:
        resp = await client.get(f"{base}/health", timeout=5)
        resp.raise_for_status()
        modes = (resp.json() or {}).get("modes") or []
    except Exception as exc:
        logger.debug("Forge multishot capability probe failed: %s", exc)
        return False
    return "multishot" in modes


def _cascade_for(quality_tier: str) -> list[VideoProvider]:
    """Provider order per quality tier: hero leads with Veo, else Forge first."""
    if quality_tier == "hero":
        return [VeoProvider(), FalProvider(), ForgeProvider()]
    return [ForgeProvider(), FalProvider()]


async def generate_video(
    req: VideoRequest,
    progress_cb: Callable[[int, str], Awaitable[None]] | None = None,
) -> VideoResult:
    """Render *req* through the provider cascade for its quality tier.

    Returns the first successful ``VideoResult`` (with the full ledger of every
    attempt). Raises ``RuntimeError`` — with the ledger attached as
    ``exc.ledger`` — when every provider fails or is unavailable."""
    ledger: list[dict] = []
    failures: list[str] = []
    for provider in _cascade_for(req.quality_tier):
        try:
            if not await provider.available(req, ledger):
                failures.append(f"{provider.name}: unavailable")
                continue
            handle = await provider.submit(req, ledger)
            status = await provider.poll(handle, ledger, progress_cb)
            result = await provider.fetch(req, handle, status, ledger)
            result.ledger = ledger
            return result
        except ProviderUnavailableError as exc:
            logger.warning("Video provider %s skipped: %s", provider.name, exc)
            ledger.append(_ledger_entry(provider.name, provider.model, "skipped", str(exc)))
            failures.append(f"{provider.name}: {exc}")
        except Exception as exc:
            logger.warning("Video provider %s failed: %s", provider.name, exc)
            ledger.append(_ledger_entry(provider.name, provider.model, "failed", str(exc)))
            failures.append(f"{provider.name}: {exc}")
    error = RuntimeError(
        f"All video providers failed for quality_tier={req.quality_tier!r}: "
        + "; ".join(failures)
    )
    error.ledger = ledger  # type: ignore[attr-defined]
    raise error
