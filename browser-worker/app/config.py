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

    # --- Browser ---
    BROWSER_HEADLESS: bool = True
    PAGE_TIMEOUT_MS: int = 30_000
    SCREENSHOT_FULL_PAGE: bool = True


settings = Settings()
