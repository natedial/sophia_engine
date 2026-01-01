"""Configuration management for Sophia."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Configuration
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    llm_model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Model to use for chat completions",
    )

    # Personality
    personality_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "personality.md",
        description="Path to personality definition markdown file",
    )

    # Backend Services
    scrivener_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for Scrivener data service",
    )

    # Telegram (optional)
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram bot token",
    )

    # Web Server
    web_host: str = Field(default="0.0.0.0", description="Web server host")
    web_port: int = Field(default=8080, description="Web server port")


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance, creating it if necessary."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def configure(settings: Settings) -> None:
    """Override the global settings instance (useful for testing)."""
    global _settings
    _settings = settings
