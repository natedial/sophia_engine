"""Configuration settings for Sophia Canvas."""

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CANVAS_",
        extra="ignore",
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8003
    debug: bool = False

    # Database - Supabase / PostgreSQL
    supabase_db_host: str = ""
    supabase_db_port: int = 5432
    supabase_db_name: str = "postgres"
    supabase_db_user: str = "postgres"
    supabase_db_password: str = ""

    # Alternative: direct connection string (takes precedence if set)
    database_url: str | None = None

    # Cognito Auth (optional - can be disabled for local dev)
    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    auth_enabled: bool = Field(default=False, description="Enable JWT auth validation")

    # WebSocket settings
    ws_heartbeat_interval: int = Field(default=30, description="WebSocket ping interval in seconds")

    @computed_field
    @property
    def db_connection_string(self) -> str:
        """Build database connection string."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.supabase_db_user}:{self.supabase_db_password}"
            f"@{self.supabase_db_host}:{self.supabase_db_port}/{self.supabase_db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
