"""Configuration for sophia_tholos service."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Service settings loaded from environment variables with THOLOS_ prefix."""

    db_path: str
    npz_path: str
    model_name: str = "all-MiniLM-L6-v2"
    semantic_enabled: bool = True
    semantic_local_files_only: bool = True
    semantic_verify_on_startup: bool = False
    semantic_strict: bool = False
    model_cache_dir: str | None = None
    port: int = 8004
    host: str = Field(default="0.0.0.0")

    model_config = {"env_prefix": "THOLOS_"}
