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
    llm_provider: str = Field(
        default="anthropic",
        description="LLM provider: anthropic, openai, google",
    )
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    google_api_key: str = Field(default="", description="Google AI API key")
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
    arithmos_base_url: str = Field(
        default="http://localhost:8001",
        description="Base URL for Arithmos compute service",
    )
    canvas_base_url: str = Field(
        default="http://localhost:8003",
        description="Base URL for Canvas visualization service",
    )
    canvas_dashboard_url: str = Field(
        default="http://localhost:3000",
        description="Frontend dashboard URL shown to user at session start",
    )

    # Telegram (optional)
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram bot token",
    )

    # Web Server
    web_host: str = Field(default="0.0.0.0", description="Web server host")
    web_port: int = Field(default=8080, description="Web server port")

    # Memory Framework
    memory_enabled: bool = Field(
        default=True,
        description="Enable layered memory recall and ingestion",
    )
    memory_working_window: int = Field(
        default=8,
        description="Number of recent conversational lines kept in working memory snapshots",
    )
    memory_episodic_top_k: int = Field(
        default=3,
        description="Top episodic memories to inject into prompt context",
    )
    memory_semantic_top_k: int = Field(
        default=3,
        description="Top semantic memories to inject into prompt context",
    )
    memory_semantic_search_enabled: bool = Field(
        default=True,
        description="Enable semantic similarity scoring for memory retrieval",
    )
    memory_lexical_weight: float = Field(
        default=0.45,
        description="Weight of lexical overlap in hybrid memory retrieval score",
    )
    memory_semantic_weight: float = Field(
        default=0.35,
        description="Weight of semantic similarity in hybrid memory retrieval score",
    )
    memory_embedding_enabled: bool = Field(
        default=True,
        description="Enable embedding index for memory records",
    )
    memory_embedding_model: str = Field(
        default="hash-v1",
        description="Embedding model identifier used by the memory index",
    )
    memory_embedding_provider: str = Field(
        default="hash",
        description="Embedding provider for memory index: hash or openai",
    )
    memory_embedding_openai_api_key: str = Field(
        default="",
        description="Optional OpenAI API key override for memory embeddings",
    )
    memory_embedding_openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI-compatible base URL for embedding requests",
    )
    memory_embedding_timeout_sec: float = Field(
        default=20.0,
        description="HTTP timeout for embedding provider requests",
    )
    memory_embedding_retry_max_attempts: int = Field(
        default=4,
        description="Maximum embedding API retry attempts for transient failures",
    )
    memory_embedding_retry_base_ms: int = Field(
        default=500,
        description="Base backoff delay in milliseconds for embedding API retries",
    )
    memory_embedding_retry_max_ms: int = Field(
        default=8000,
        description="Maximum backoff delay in milliseconds for embedding API retries",
    )
    memory_embedding_retry_jitter: bool = Field(
        default=True,
        description="Apply random jitter to embedding API retry backoff",
    )
    memory_embedding_batch_size: int = Field(
        default=128,
        description="Batch size for asynchronous memory embedding indexing",
    )
    memory_embedding_max_batches: int = Field(
        default=10,
        description="Maximum embedding batches processed by one indexing run",
    )
    memory_embed_episodic: bool = Field(
        default=True,
        description="Include episodic memories in embedding index",
    )
    memory_embed_semantic: bool = Field(
        default=True,
        description="Include semantic memories in embedding index",
    )
    memory_query_use_embedding_index: bool = Field(
        default=True,
        description="Use indexed embeddings during query-time memory retrieval",
    )
    memory_log_level: str = Field(
        default="INFO",
        description="Log level used by memory index worker and memory storage logs",
    )
    memory_store_backend: str = Field(
        default="sqlite",
        description="Memory store backend: sqlite or memory",
    )
    memory_store_path: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "memory.db",
        description="Path to SQLite memory store when backend=sqlite",
    )
    memory_compaction_enabled: bool = Field(
        default=True,
        description="Enable episodic -> semantic memory compaction",
    )
    memory_compaction_every_n_turns: int = Field(
        default=10,
        description="Run compaction every N ingested turns per session",
    )
    memory_compaction_max_episodic_per_session: int = Field(
        default=120,
        description="Maximum episodic records per session before pruning/compaction",
    )
    memory_compaction_batch_size: int = Field(
        default=40,
        description="Maximum number of episodic records compacted in one pass",
    )


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
