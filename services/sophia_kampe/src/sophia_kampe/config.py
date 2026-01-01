"""Configuration settings for Sophia Kampe."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class ArithmosSettings(BaseSettings):
    """Settings for Arithmos client."""

    url: str = "http://localhost:8001"
    timeout: float = 30.0


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="KAMPE_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8002
    debug: bool = False

    # Arithmos client
    arithmos: ArithmosSettings = ArithmosSettings()


settings = Settings()
