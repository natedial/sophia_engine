"""Configuration for Sophia Oikonomia."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings."""

    model_config = SettingsConfigDict(env_prefix="OIKONOMIA_", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8006
    debug: bool = False
    timezone: str = "America/New_York"
    db_path: str = ".sophia/oikonomia/oikonomia.db"
    scrivener_url: str = "http://localhost:8000"
    request_timeout_sec: float = 30.0
    market_models_root: str = "/Users/ncdial/devwork/market_models"
    default_observation_lookback_days: int = 3650


settings = Settings()
