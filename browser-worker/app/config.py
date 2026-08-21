from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MinIO ---
    MINIO_ENDPOINT: str = "minio:9000"
    MINIO_ACCESS_KEY: str = "markai-minio"
    MINIO_SECRET_KEY: str = "change-me"
    MINIO_BUCKET: str = "markai-assets"
    MINIO_SECURE: bool = False

    # --- General ---
    # Compose injects the shared .env, so the deployment environment is known
    # here too; the anon escape hatch below is inert in production.
    MARKAI_ENV: str = "development"

    # --- API Key ---
    # Blank key = every request is refused (fail closed). Local dev without a
    # key requires the explicit BROWSER_WORKER_ALLOW_ANON=true escape hatch.
    BROWSER_WORKER_API_KEY: str = ""
    BROWSER_WORKER_ALLOW_ANON: bool = False

    # --- Browser ---
    BROWSER_HEADLESS: bool = True
    PAGE_TIMEOUT_MS: int = 30_000
    SCREENSHOT_FULL_PAGE: bool = True


settings = Settings()
