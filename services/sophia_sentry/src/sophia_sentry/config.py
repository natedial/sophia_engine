"""Configuration for Sophia Sentry."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings."""

    model_config = SettingsConfigDict(env_prefix="SENTRY_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8007
    debug: bool = False
    timezone: str = "America/New_York"
    db_path: str = ".sophia/sentry/sentry.db"


settings = Settings()
