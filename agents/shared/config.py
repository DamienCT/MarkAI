"""Centralized configuration loaded from environment variables via Pydantic Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All environment variables consumed by the agents service."""

    # ── LiteLLM ──────────────────────────────────────────────────────────
    LITELLM_BASE_URL: str = "http://litellm:4000"
    LITELLM_MASTER_KEY: str = ""

    # ── Backend API (for model resolution) ────────────────────────────
    BACKEND_URL: str = "http://backend:8000"
    # GET-only credential for the backend's media endpoints (/api/v1/files/*,
    # brand logos). Blank in local dev (backend accepts anonymous media GETs
    # until the token is enforced); in production the shared .env carries the
    # same value the backend requires, and every backend media GET sends it
    # as X-Media-Token via media_auth_headers().
    MEDIA_PROXY_TOKEN: str = ""

    # ── NATS ─────────────────────────────────────────────────────────────
    NATS_URL: str = "nats://nats:4222"
    NATS_AUTH_TOKEN: str = ""

    # ── Postgres ─────────────────────────────────────────────────────────
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "markai"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "markai"

    # ── Qdrant ───────────────────────────────────────────────────────────
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""

    # ── MinIO ────────────────────────────────────────────────────────────
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_SECURE: bool = False

    # ── Browser Worker ───────────────────────────────────────────────────
    BROWSER_WORKER_URL: str = "http://browser-worker:8001"
    BROWSER_WORKER_API_KEY: str = ""

    # ── Microsoft Fabric / Power BI ──────────────────────────────────────
    FABRIC_TENANT_ID: str = ""
    FABRIC_CLIENT_ID: str = ""
    FABRIC_CLIENT_SECRET: str = ""
    FABRIC_SQL_ENDPOINT: str = ""
    FABRIC_LAKEHOUSE_NAME: str = "lh_bronze"

    # ── Business Central API v2.0 (item-card pictures) ───────────────────
    # The Fabric lakehouse mirror carries no item pictures, so product photos
    # come from the BC API directly. Credentials default to the Fabric service
    # principal; override only if a separate app registration holds the BC
    # API.ReadWrite.All grant.
    BC_API_ENABLED: bool = True
    BC_API_BASE_URL: str = "https://api.businesscentral.dynamics.com"
    BC_API_ENVIRONMENT: str = "Production"
    BC_API_TENANT_ID: str = ""
    BC_API_CLIENT_ID: str = ""
    BC_API_CLIENT_SECRET: str = ""

    # ── LangChain / LangSmith ────────────────────────────────────────────
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "markai-agents"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    # ── Google Gemini (product image replacement) ────────────────────────
    GEMINI_API_KEY: str = ""

    # ── Video generation (Forge local GPU / fal.ai / Google Veo) ─────────
    VIDEO_FORGE_URL: str = "http://host.docker.internal:9100"
    VIDEO_FORGE_API_KEY: str = ""
    FAL_API_KEY: str = ""
    # Verified fal endpoint (fal.ai/models/fal-ai/ltx-2.3/image-to-video):
    # LTX-2.3 — portrait 9:16 + native audio.
    FAL_VIDEO_MODEL: str = "fal-ai/ltx-2.3/image-to-video"
    VEO_MODEL: str = "veo-3.1-fast-generate-preview"
    VIDEO_RENDER_TIMEOUT_S: int = 2400
    FAL_COST_PER_S: float = 0.06
    VEO_COST_PER_S: float = 0.15
    # Native multishot: when the forge /health advertises the "multishot"
    # mode, the whole reel is rendered in ONE forge call (per-scene segments,
    # model-chosen transitions) instead of the chained per-shot loop. The
    # switch exists so an operator can pin a reel back onto the proven
    # chained path without redeploying; hero-tier reels ignore it and stay
    # on Veo either way.
    VIDEO_NATIVE_MULTISHOT: bool = True

    # ── Generated-image text guard ───────────────────────────────────────
    # Image models hallucinate lettering — invented labels on unlabelled jars,
    # garbled signage, misspelled words on packaging — and no amount of
    # negative prompting reliably stops it. Every generated image is therefore
    # vision-checked for text the brief did not ask for, and a flagged frame is
    # re-rolled with a strengthened no-text instruction. Set
    # IMAGE_TEXT_GUARD_ENABLED=false to bypass the whole path.
    # Retries are additionally clamped by shared.image_text_guard.MAX_RETRY_CAP
    # so a misconfigured value here cannot multiply image-generation spend.
    IMAGE_TEXT_GUARD_ENABLED: bool = True
    IMAGE_TEXT_GUARD_MAX_RETRIES: int = 2
    IMAGE_TEXT_GUARD_TIMEOUT_S: int = 90
    # Blank → the active "vision" model from the backend's model selections.
    IMAGE_TEXT_GUARD_MODEL: str = ""
    IMAGE_TEXT_GUARD_MAX_IMAGE_MB: int = 20

    # ── Social API Tokens ────────────────────────────────────────────────
    META_ACCESS_TOKEN: str = ""  # Shared token for Instagram + Facebook Graph API
    LINKEDIN_ACCESS_TOKEN: str = ""

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Runtime environment ───────────────────────────────────────────────
    MARKAI_ENV: str = "development"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()


def media_auth_headers() -> dict[str, str]:
    """Headers authenticating a GET against the backend's media endpoints.

    Empty when MEDIA_PROXY_TOKEN is unset (local dev); callers pass the
    result straight to httpx. Only send this to the backend — never to
    external hosts.
    """
    if settings.MEDIA_PROXY_TOKEN:
        return {"X-Media-Token": settings.MEDIA_PROXY_TOKEN}
    return {}


# ── Video render budget ────────────────────────────────────────────────
# A reel is rendered shot by shot (see workflows.video.nodes): one provider
# call per shot, each bounded by VIDEO_RENDER_TIMEOUT_S, then the ffmpeg
# finishing passes. Both the worker's asyncio.wait_for budget and the NATS
# ack_wait derive from video_workflow_timeout_s so they can never drift.
# The native multishot path renders the whole reel in ONE call (two with its
# seed-bumped motion retry), each bounded by the same VIDEO_RENDER_TIMEOUT_S,
# so the chained worst case below remains the binding bound.
VIDEO_MAX_REEL_SHOTS = 8
# ffmpeg work on top of the shot renders, sized to the passes it actually
# runs: per-shot normalization (600s each, worst case every clip is non-forge),
# the concat (900s) and the overlay burn (600s). The old flat 1800s covered
# barely three of the ten passes an 8-shot reel can need.
VIDEO_NORMALIZE_TIMEOUT_S = 600
VIDEO_CONCAT_TIMEOUT_S = 900
VIDEO_BURN_TIMEOUT_S = 600
VIDEO_AUDIO_TIMEOUT_S = 600
VIDEO_FINISHING_BUDGET_S = (
    VIDEO_MAX_REEL_SHOTS * VIDEO_NORMALIZE_TIMEOUT_S
    + VIDEO_CONCAT_TIMEOUT_S
    + VIDEO_BURN_TIMEOUT_S
    + VIDEO_AUDIO_TIMEOUT_S
)

# ── Reel audio ─────────────────────────────────────────────────────────────
# Reels shipped silent: LTX/forge produces no audio at all, and the concat
# pass substituted anullsrc silence without saying so, while video_jobs
# recorded audio: true regardless. A silent reel is the single loudest
# amateur signal on a feed where every competing post has a bed.
#
# Beds are supplied as files, NOT generated and NOT fetched: music licensing
# is the operator's call, so the pipeline reads whatever is dropped in this
# directory and says plainly in the metadata when there is nothing to read.
# Layout: <dir>/<mood>/*.{mp3,m4a,wav,opus,ogg,flac}, plus any files at the
# top level as the fallback pool.
VIDEO_MUSIC_DIR = "/app/assets/music"
# Platform delivery targets. Instagram, TikTok and YouTube all normalize
# playback to roughly -14 LUFS; delivering quieter throws away loudness the
# platform will not give back, and delivering hotter just gets turned down
# with the transients already squashed. -1 dBTP leaves headroom for the
# lossy re-encode every platform runs.
VIDEO_TARGET_LUFS = -14.0
VIDEO_TARGET_TRUE_PEAK_DB = -1.0
# Bed level under diegetic audio vs. carrying the reel alone. A bed under
# dialogue or foley sits well down; with nothing else in the mix it comes up
# but still stays under unity so the platform's own normalization has room.
VIDEO_MUSIC_DUCKED_DB = -18.0
VIDEO_MUSIC_SOLO_DB = -6.0
# Anything peaking below this is silence with encoder noise on top, not a
# real track — measured, because "the file has an audio stream" was exactly
# the check that let silent reels through.
VIDEO_SILENCE_PEAK_DB = -50.0


def video_workflow_timeout_s(base_timeout_s: int) -> int:
    """Longest a video workflow may run before the worker cancels it.

    Worst case for the multi-shot path: every one of VIDEO_MAX_REEL_SHOTS
    shots burns its full per-render deadline, plus the finishing passes. That
    ``shots x VIDEO_RENDER_TIMEOUT_S`` term is only a true bound because
    render_video wraps each shot's generate_video in its own
    ``asyncio.wait_for(VIDEO_RENDER_TIMEOUT_S)`` — the provider cascade gives
    EVERY provider its own deadline, so an unbounded shot could otherwise run
    3x that on its own. The legacy single-call path does walk the full
    3-provider cascade inside ONE render, so that older budget is kept as a
    floor. Never shorter than the generic workflow timeout. Operators wanting
    a tighter bound should lower VIDEO_RENDER_TIMEOUT_S — every term is
    derived from it.
    """
    return max(
        int(base_timeout_s),
        3 * settings.VIDEO_RENDER_TIMEOUT_S + 600,
        VIDEO_MAX_REEL_SHOTS * settings.VIDEO_RENDER_TIMEOUT_S
        + VIDEO_FINISHING_BUDGET_S,
    )


# ── Startup validation for production ──────────────────────────────────
_DEFAULTS_TO_CHECK = {
    "POSTGRES_PASSWORD": "",
    "MINIO_SECRET_KEY": "",
    "LITELLM_MASTER_KEY": "",
}
if settings.MARKAI_ENV == "production":
    import logging as _log

    _startup_logger = _log.getLogger("agents.config")
    _insecure_defaults = []
    for _field, _default in _DEFAULTS_TO_CHECK.items():
        if getattr(settings, _field, None) == _default:
            _insecure_defaults.append(_field)
            _startup_logger.critical(
                "SECURITY: %s is still set to its default value. "
                "Set a strong value in .env before deploying to production.",
                _field,
            )
    if _insecure_defaults:
        raise RuntimeError(
            f"Refusing to start agents in production with default secrets: "
            f"{', '.join(_insecure_defaults)}. "
            f"Set strong values in .env for these settings."
        )
    # Validate required service URLs
    _REQUIRED_URLS = ["NATS_URL", "BACKEND_URL", "LITELLM_BASE_URL"]
    _missing_urls = [f for f in _REQUIRED_URLS if not getattr(settings, f, "")]
    if _missing_urls:
        raise RuntimeError(
            f"Refusing to start agents in production without service URLs: "
            f"{', '.join(_missing_urls)}. Set these in .env."
        )
    # Forge auth is all-or-nothing: a configured forge URL with a blank API
    # key passes the unauthenticated /health probe, 401s on submit, and
    # silently fails every reel over to paid cloud at ~$0.06/s (N-11).
    # Operators disabling the forge must blank VIDEO_FORGE_URL explicitly.
    if settings.VIDEO_FORGE_URL and not settings.VIDEO_FORGE_API_KEY:
        _startup_logger.critical(
            "SECURITY: VIDEO_FORGE_URL is set but VIDEO_FORGE_API_KEY is "
            "blank. Set the forge API key in .env (or blank VIDEO_FORGE_URL "
            "to disable the forge) before deploying to production."
        )
        raise RuntimeError(
            "Refusing to start agents in production: VIDEO_FORGE_URL is set "
            "but VIDEO_FORGE_API_KEY is blank."
        )
