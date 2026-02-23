"""Configuration for sophia_tholos service."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service settings loaded from environment variables with THOLOS_ prefix."""

    db_path: str
    npz_path: str
    model_name: str = "all-MiniLM-L6-v2"
    port: int = 8004
    host: str = "0.0.0.0"

    model_config = {"env_prefix": "THOLOS_"}
