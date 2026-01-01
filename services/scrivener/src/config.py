"""Configuration management using pydantic-settings."""

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase / Database
    supabase_url: str = ""
    supabase_db_host: str = ""
    supabase_db_port: int = 5432
    supabase_db_name: str = "postgres"
    supabase_db_user: str = "postgres"
    supabase_db_password: str = ""

    # Alternative: direct connection string (takes precedence if set)
    database_url: str | None = None

    # API Keys
    fred_api_key: str = ""
    bls_api_key: str = ""
    alpha_vantage_api_key: str = ""
    nasdaq_data_link_api_key: str = ""

    # Scheduling
    daily_sweep_hour: int = Field(default=17, ge=0, le=23)
    daily_sweep_minute: int = Field(default=0, ge=0, le=59)
    timezone: str = "America/New_York"

    # Data settings
    default_lookback_years: int = 5

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
