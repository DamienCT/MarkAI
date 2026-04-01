from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    MARKAI_ENV: str = "development"
    SECRET_KEY: str = "change-me-to-a-random-string"

    # --- Microsoft Entra ID (SSO) ---
    AZURE_AD_TENANT_ID: str = ""
    AZURE_AD_CLIENT_ID: str = ""
    AZURE_AD_CLIENT_SECRET: str = ""
    ADMIN_SECURITY_GROUP_ID: str = ""

    # --- PostgreSQL ---
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "markai"
    POSTGRES_USER: str = "markai"
    POSTGRES_PASSWORD: str = "change-me"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # --- Qdrant ---
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""

    # --- MinIO ---
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "markai-minio"
    MINIO_SECRET_KEY: str = "change-me"
    MINIO_BUCKET: str = "markai-assets"

    # --- Valkey ---
    VALKEY_HOST: str = "valkey"
    VALKEY_PORT: int = 6379
    VALKEY_PASSWORD: str = ""

    # --- NATS ---
    NATS_URL: str = "nats://nats:4222"

    # --- LiteLLM ---
    LITELLM_BASE_URL: str = "http://litellm:4000"
    LITELLM_MASTER_KEY: str = ""

    # --- OpenAI (used for model discovery) ---
    OPENAI_API_KEY: str = ""

    # --- Google Gemini (used for product image replacement) ---
    GEMINI_API_KEY: str = ""

    # --- Frontend ---
    FRONTEND_URL: str = ""

    # --- n8n ---
    N8N_BASE_URL: str = "http://n8n:5678"
    N8N_WEBHOOK_BASE: str = "https://n8n.example.com/webhook"
    N8N_WEBHOOK_SECRET: str = ""

    # --- Browser Worker ---
    BROWSER_WORKER_URL: str = "http://browser-worker:8001"

    # --- Notifications (Microsoft Teams) ---
    TEAMS_WEBHOOK_URL: str = ""

    # --- Social Platform API Keys ---
    # Meta (Instagram + Facebook)
    META_ACCESS_TOKEN: str = ""
    META_PAGE_ID: str = ""
    META_INSTAGRAM_ACCOUNT_ID: str = ""
    # LinkedIn
    LINKEDIN_ACCESS_TOKEN: str = ""
    LINKEDIN_ORG_ID: str = ""
    # YouTube
    YOUTUBE_CLIENT_ID: str = ""
    YOUTUBE_CLIENT_SECRET: str = ""
    YOUTUBE_REFRESH_TOKEN: str = ""
    YOUTUBE_CHANNEL_ID: str = ""
    # TikTok
    TIKTOK_CLIENT_KEY: str = ""
    TIKTOK_CLIENT_SECRET: str = ""
    TIKTOK_ACCESS_TOKEN: str = ""
    # X (Twitter)
    X_API_KEY: str = ""
    X_API_SECRET: str = ""
    X_ACCESS_TOKEN: str = ""
    X_ACCESS_TOKEN_SECRET: str = ""

    # --- OpenTelemetry ---
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    # --- Scheduler ---
    SCHEDULER_TIMEZONE: str = "Indian/Mauritius"
    MORNING_SCHEDULE_HOUR: int = 6
    MORNING_SCHEDULE_MINUTE: int = 0
    PUBLISH_CHECK_INTERVAL_MINUTES: int = 15
    ENGAGEMENT_PULL_INTERVAL_HOURS: int = 6
    BC_SYNC_INTERVAL_HOURS: int = 6

    # --- Microsoft Entra ID (Fabric / Power BI) ---
    FABRIC_TENANT_ID: str = ""
    FABRIC_CLIENT_ID: str = ""
    FABRIC_CLIENT_SECRET: str = ""
    FABRIC_SQL_ENDPOINT: str = ""
    FABRIC_LAKEHOUSE_NAME: str = "lh_bronze"

    # --- Business Central Tables ---
    BC_TABLE_ITEMS: str = "items"
    BC_TABLE_ITEM_CATEGORIES: str = "item_categories"
    BC_TABLE_VENDORS: str = "vendors"
    BC_TABLE_ITEM_LEDGER_ENTRIES: str = "item_ledger_entries"


settings = Settings()

# Warn on startup if critical secrets are still at default values
_DEFAULTS_TO_CHECK = {
    "SECRET_KEY": "change-me-to-a-random-string",
    "POSTGRES_PASSWORD": "change-me",
    "MINIO_SECRET_KEY": "change-me",
}
if settings.MARKAI_ENV == "production":
    import logging as _log

    _startup_logger = _log.getLogger("app.config")
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
            f"Refusing to start in production with default secrets: "
            f"{', '.join(_insecure_defaults)}. "
            f"Set strong values in .env for these settings."
        )
    # Validate required Azure AD configuration
    _REQUIRED_AUTH = [
        "AZURE_AD_TENANT_ID",
        "AZURE_AD_CLIENT_ID",
        "AZURE_AD_CLIENT_SECRET",
    ]
    _missing_auth = [f for f in _REQUIRED_AUTH if not getattr(settings, f, "")]
    if _missing_auth:
        raise RuntimeError(
            f"Refusing to start in production without Azure AD config: "
            f"{', '.join(_missing_auth)}. Set these in .env."
        )
