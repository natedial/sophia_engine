"""Configuration management for Sophia."""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from sophia.security.filesystem import ReadPolicy, WritePolicy, parse_allowlist


def get_project_root() -> Path:
    """Get the project root directory."""
    source_root = Path(__file__).resolve().parent.parent.parent

    # In containerized/package installs, cwd can be the checked-out project tree.
    # Prefer that when config assets are present there.
    cwd = Path.cwd().resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / "config" / "personality.md").exists():
            return candidate

    return source_root


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Configuration
    llm_provider: str = Field(
        default="openai",
        description="LLM provider: anthropic, openai, groq",
    )
    anthropic_api_key: str = Field(default="", description="Anthropic API key")
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for OpenAI-compatible chat completions API",
    )
    groq_api_key: str = Field(default="", description="Groq API key")
    groq_base_url: str = Field(
        default="https://api.groq.com",
        description="Base URL for Groq API (SDK appends /openai/v1 internally)",
    )
    google_api_key: str = Field(default="", description="Google AI API key")
    llm_model: str = Field(
        default="gpt-4.1-mini",
        description="Model to use for chat completions",
    )
    llm_request_timeout_sec: float = Field(
        default=180.0,
        description="HTTP timeout (seconds) for LLM completion requests",
    )

    # Personality
    personality_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "personality.md",
        description="Path to personality definition markdown file",
    )
    soul_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "soul.md",
        description="Path to soul definition markdown file",
    )
    lessons_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "LESSONS.md",
        description="Path to read-only seed lessons markdown file",
    )
    skills_enabled: bool = Field(
        default=True,
        description="Enable local skill discovery and prompt injection",
    )
    skills_path: Path = Field(
        default_factory=lambda: get_project_root() / "skills",
        description="Path to local skill folders containing SKILL.md files",
    )
    skills_max_loaded_chars: int = Field(
        default=12000,
        description="Maximum characters loaded from each skill body",
    )
    skills_implicit_match_min_overlap: int = Field(
        default=2,
        description="Minimum keyword overlap required for implicit skill matching",
    )
    agent_fs_enforce_write_policy: bool = Field(
        default=True,
        description="Enforce deny-by-default write policy for agent-owned writes",
    )
    agent_fs_write_allowlist: str = Field(
        default=".sophia",
        description=(
            "Comma-separated allowlist of writable paths (absolute or project-relative). "
            "Writes outside these roots are denied when policy is enabled."
        ),
    )
    agent_fs_enforce_read_policy: bool = Field(
        default=True,
        description="Enforce deny-by-default read policy for agent-owned reads",
    )
    agent_fs_read_allowlist: str = Field(
        default="config,skills,.sophia",
        description=(
            "Comma-separated allowlist of readable paths (absolute or project-relative). "
            "Reads outside these roots are denied when policy is enabled."
        ),
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
    tholos_base_url: str = Field(
        default="http://localhost:8004",
        description="Base URL for Tholos research search service",
    )
    fed_tracker_url: str = Field(
        default="http://127.0.0.1:8005",
        description="Base URL for Fed Textual Change Tracker service",
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
    telegram_polling_enabled: bool = Field(
        default=True,
        description="Enable Telegram long polling in gateway mode",
    )
    telegram_accounts_json: str = Field(
        default="",
        description=(
            "Optional JSON list of Telegram account configs. "
            "Each item: {account_id, bot_token}. "
            "When empty, TELEGRAM_BOT_TOKEN is used as a single account."
        ),
    )

    # Web Server
    web_host: str = Field(default="0.0.0.0", description="Web server host")
    web_port: int = Field(default=8080, description="Web server port")

    # Surface gateway
    gateway_default_agent_id: str = Field(
        default="sophia_prima",
        description="Default agent id for gateway routing",
    )
    gateway_bindings_json: str = Field(
        default="",
        description=(
            "Optional JSON list of deterministic gateway binding rules. "
            "Fields: channel, account_id, peer_id, agent_id, session_id."
        ),
    )
    gateway_agents_json: str = Field(
        default="",
        description=(
            "Optional JSON list of gateway agent profile overrides. "
            "Fields: agent_id, label, description, prompt, tool_allowlist, "
            "skills_enabled, subagents_enabled."
        ),
    )
    gateway_artifact_store_path: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "gateway_runs.db",
        description="Path to the SQLite store for persisted gateway runs and skill artifacts",
    )

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
    memory_lessons_top_k: int = Field(
        default=4,
        description="Top lessons memories to inject into prompt context",
    )
    memory_semantic_top_k: int = Field(
        default=3,
        description="Top semantic memories to inject into prompt context",
    )
    memory_lesson_promotion_min_repeats: int = Field(
        default=2,
        description="Minimum repeated non-explicit candidate count before lesson promotion",
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

    # Subagent Orchestration (thin-slice)
    subagents_enabled: bool = Field(
        default=False,
        description="Enable supervisor-driven subagent delegation flow",
    )
    subagents_max_parallel_workers: int = Field(
        default=2,
        description="Maximum delegated workers running concurrently",
    )
    subagents_default_timeout_sec: float = Field(
        default=20.0,
        description="Default timeout applied to one delegated worker task",
    )
    subagents_default_max_tool_iterations: int = Field(
        default=4,
        description="Default max tool-loop iterations for delegated workers",
    )
    subagents_default_token_budget_chars: int = Field(
        default=24000,
        description="Approximate token budget for delegated workers (character proxy)",
    )
    subagents_default_max_result_chars: int = Field(
        default=4000,
        description="Maximum worker summary length merged back to supervisor",
    )
    dev_worker_enabled: bool = Field(
        default=False,
        description="Enable Codex-backed delegated development tasks",
    )
    dev_worker_codex_command: str = Field(
        default="codex",
        description="Executable name or absolute path for Codex CLI",
    )
    dev_worker_model: str = Field(
        default="",
        description="Optional Codex model override for dev worker runs",
    )
    dev_worker_codex_sandbox: str = Field(
        default="workspace-write",
        description="Codex sandbox mode used for delegated development tasks",
    )
    dev_worker_workspace_root: Path = Field(
        default_factory=get_project_root,
        description="Workspace root handed to Codex for delegated development tasks",
    )
    dev_worker_output_dir: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "dev_worker",
        description="Directory used for dev worker schema/output artifacts",
    )
    dev_worker_max_message_chars: int = Field(
        default=12000,
        description="Maximum dev worker final message characters retained by supervisor",
    )

    def build_write_policy(self) -> WritePolicy:
        """Build filesystem write policy from settings."""
        return WritePolicy(
            enabled=self.agent_fs_enforce_write_policy,
            allowed_roots=parse_allowlist(
                self.agent_fs_write_allowlist,
                project_root=get_project_root(),
            ),
        )

    def build_read_policy(self) -> ReadPolicy:
        """Build filesystem read policy from settings."""
        return ReadPolicy(
            enabled=self.agent_fs_enforce_read_policy,
            allowed_roots=parse_allowlist(
                self.agent_fs_read_allowlist,
                project_root=get_project_root(),
            ),
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
