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

    # ── NATS ─────────────────────────────────────────────────────────────
    NATS_URL: str = "nats://nats:4222"

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

    # ── Microsoft Fabric / Power BI ──────────────────────────────────────
    FABRIC_TENANT_ID: str = ""
    FABRIC_CLIENT_ID: str = ""
    FABRIC_CLIENT_SECRET: str = ""
    FABRIC_SQL_ENDPOINT: str = ""
    FABRIC_LAKEHOUSE_NAME: str = "lh_bronze"

    # ── LangChain / LangSmith ────────────────────────────────────────────
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "markai-agents"
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"

    # ── Google Gemini (product image replacement) ────────────────────────
    GEMINI_API_KEY: str = ""

    # ── Social API Tokens ────────────────────────────────────────────────
    INSTAGRAM_ACCESS_TOKEN: str = ""
    FACEBOOK_ACCESS_TOKEN: str = ""
    LINKEDIN_ACCESS_TOKEN: str = ""

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
