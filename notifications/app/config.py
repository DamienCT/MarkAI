from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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

    # --- Valkey ---
    VALKEY_HOST: str = "valkey"
    VALKEY_PORT: int = 6379
    VALKEY_PASSWORD: str = ""

    # --- General ---
    # Compose injects the shared .env, so the deployment environment is known
    # here too; the anon escape hatch below is inert in production.
    MARKAI_ENV: str = "development"

    # --- Notifications Auth ---
    # Blank token = every request is refused (fail closed). Local dev without
    # a token requires the explicit NOTIFICATIONS_ALLOW_ANON=true escape hatch.
    NOTIFICATIONS_AUTH_TOKEN: str = ""
    NOTIFICATIONS_ALLOW_ANON: bool = False

    # --- Microsoft Teams ---
    TEAMS_WEBHOOK_URL: str = ""


settings = Settings()
