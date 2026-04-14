"""Configuration management for Sophia."""

from pathlib import Path
from typing import Any, Optional

from pydantic import AliasChoices, Field, model_validator
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
        populate_by_name=True,
    )

    # LLM Configuration
    llm_provider: str = Field(
        default="openai",
        description=(
            "Legacy provider fallback for bare llm_model values. "
            "Deprecated in favor of explicit provider:model."
        ),
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
    deepinfra_api_key: str = Field(default="", description="DeepInfra API key")
    deepinfra_base_url: str = Field(
        default="https://api.deepinfra.com/v1/openai",
        description="Base URL for DeepInfra OpenAI-compatible API",
    )
    google_api_key: str = Field(default="", description="Google AI API key")
    llm_model: str = Field(
        default="gpt-4.1-mini",
        description=(
            "Model selector. Canonical format: 'provider:model' "
            "(for example 'openai:gpt-4.1-mini' or "
            "'deepinfra:MiniMaxAI/MiniMax-M2.5'). "
            "Bare model names are supported for legacy configs and best-effort aliases."
        ),
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
    presentation_enabled: bool = Field(
        default=True,
        description="Enable channel-aware presentation policy resolution",
    )
    presentation_core_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "presentation" / "core.md",
        description="Path to compact global presentation policy markdown",
    )
    presentation_channels_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "presentation" / "channels",
        description="Path to per-channel presentation capability config files",
    )
    presentation_rendering_path: Path = Field(
        default_factory=lambda: get_project_root() / "config" / "presentation" / "rendering",
        description="Path to presentation rendering themes and image guidelines",
    )
    presentation_artifact_dir: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "presentation",
        description="Directory used for rendered presentation artifacts",
    )
    self_edit_proposals_enabled: bool = Field(
        default=True,
        description="Enable gated self-edit proposals for Sophia-owned guidance files",
    )
    self_edit_proposal_dir: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "self_edit_proposals",
        description="Directory used for durable self-edit proposal artifacts",
    )
    self_edit_target_globs: str = Field(
        default="config/*.md,config/**/*.md,config/*.json,config/**/*.json,skills/**/SKILL.md",
        description=(
            "Comma-separated project-relative glob patterns allowed as self-edit proposal targets"
        ),
    )
    self_edit_allow_new_files: bool = Field(
        default=False,
        description="Allow self-edit proposals to target new files that do not yet exist",
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
    readwise_cli_path: str = Field(
        default="readwise",
        description="Path to the installed Readwise CLI binary",
    )
    readwise_cli_config_path: str = Field(
        default="~/.readwise-cli.json",
        description="Path to the Readwise CLI auth/config file",
    )
    brave_base_url: str = Field(
        default="https://api.search.brave.com",
        description="Base URL for Brave Search API",
    )
    brave_api_key: str = Field(
        default="",
        description="API key for Brave Search / LLM Context access",
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
    memory_resource_top_k: int = Field(
        default=2,
        description="Top user-endorsed resource memories to inject into prompt context",
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
    history_enabled: bool = Field(
        default=False,
        description="Enable append-only lossless history for debugging and reflection",
    )
    history_store_path: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "history.db",
        description="Path to SQLite store for append-only debugging history",
    )
    history_tool_result_max_chars: int = Field(
        default=50000,
        description=(
            "Maximum stored tool-result characters per history event; 0 keeps full result text"
        ),
    )
    history_session_recall_enabled: bool = Field(
        default=True,
        description="Enable automatic cross-session recall from searchable history",
    )
    history_session_recall_top_k: int = Field(
        default=2,
        description="Maximum number of prior sessions surfaced into prompt context",
    )
    history_session_recall_max_excerpts_per_session: int = Field(
        default=2,
        description="Maximum excerpts included per recalled prior session",
    )
    history_session_recall_max_excerpt_chars: int = Field(
        default=220,
        description="Maximum characters kept from one recalled history excerpt",
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
    coding_worker_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("CODING_WORKER_ENABLED", "DEV_WORKER_ENABLED"),
        description="Enable delegated coding tasks",
    )
    coding_worker_backend: str = Field(
        default="codex",
        validation_alias=AliasChoices("CODING_WORKER_BACKEND"),
        description="Delegated coding backend: codex or claude_code",
    )
    codex_command: str = Field(
        default="codex",
        validation_alias=AliasChoices("CODEX_COMMAND", "DEV_WORKER_CODEX_COMMAND"),
        description="Executable name or absolute path for Codex CLI",
    )
    codex_model: str = Field(
        default="",
        validation_alias=AliasChoices("CODEX_MODEL", "DEV_WORKER_MODEL"),
        description="Optional Codex model override for dev worker runs",
    )
    codex_sandbox: str = Field(
        default="workspace-write",
        validation_alias=AliasChoices("CODEX_SANDBOX", "DEV_WORKER_CODEX_SANDBOX"),
        description="Codex sandbox mode used for delegated development tasks",
    )
    claude_code_command: str = Field(
        default="claude",
        validation_alias=AliasChoices("CLAUDE_CODE_COMMAND"),
        description="Executable name or absolute path for Claude Code CLI",
    )
    claude_code_model: str = Field(
        default="",
        validation_alias=AliasChoices("CLAUDE_CODE_MODEL"),
        description="Optional Claude Code model override for delegated coding runs",
    )
    claude_code_max_turns: int = Field(
        default=8,
        validation_alias=AliasChoices("CLAUDE_CODE_MAX_TURNS"),
        description="Maximum Claude Code turns for a delegated coding run",
    )
    claude_code_permission_mode: str = Field(
        default="acceptEdits",
        validation_alias=AliasChoices("CLAUDE_CODE_PERMISSION_MODE"),
        description="Claude Code permission mode used for delegated coding tasks",
    )
    claude_code_allowed_tools: str = Field(
        default="Bash,Edit,Glob,Grep,LS,MultiEdit,Read,Write",
        validation_alias=AliasChoices("CLAUDE_CODE_ALLOWED_TOOLS"),
        description="Comma-separated Claude Code tool allowlist for delegated coding tasks",
    )
    coding_worker_workspace_root: Path = Field(
        default_factory=get_project_root,
        validation_alias=AliasChoices("CODING_WORKER_WORKSPACE_ROOT", "DEV_WORKER_WORKSPACE_ROOT"),
        description="Workspace root handed to Codex for delegated development tasks",
    )
    coding_worker_output_dir: Path = Field(
        default_factory=lambda: get_project_root() / ".sophia" / "coding_worker",
        validation_alias=AliasChoices("CODING_WORKER_OUTPUT_DIR", "DEV_WORKER_OUTPUT_DIR"),
        description="Directory used for coding worker schema/output artifacts",
    )
    coding_worker_max_message_chars: int = Field(
        default=12000,
        validation_alias=AliasChoices("CODING_WORKER_MAX_MESSAGE_CHARS", "DEV_WORKER_MAX_MESSAGE_CHARS"),
        description="Maximum coding worker final message characters retained by supervisor",
    )
    coding_runtime_mode: str = Field(
        default="forge_service",
        validation_alias=AliasChoices("CODING_RUNTIME_MODE"),
        description="Coding runtime execution mode: inline or forge_service",
    )
    coding_runtime_fallback_inline: bool = Field(
        default=True,
        validation_alias=AliasChoices("CODING_RUNTIME_FALLBACK_INLINE"),
        description="Fall back to inline coding worker execution when forge service is unreachable",
    )
    forge_base_url: str = Field(
        default="http://localhost:8090",
        validation_alias=AliasChoices("FORGE_BASE_URL"),
        description="Base URL for the future Sophia Forge runtime service",
    )
    forge_request_timeout_sec: float = Field(
        default=10.0,
        validation_alias=AliasChoices("FORGE_REQUEST_TIMEOUT_SEC"),
        description="HTTP timeout used by the future Sophia Forge client",
    )

    @model_validator(mode="before")
    @classmethod
    def _apply_legacy_dev_worker_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        remap = {
            "dev_worker_enabled": "coding_worker_enabled",
            "dev_worker_codex_command": "codex_command",
            "dev_worker_model": "codex_model",
            "dev_worker_codex_sandbox": "codex_sandbox",
            "dev_worker_workspace_root": "coding_worker_workspace_root",
            "dev_worker_output_dir": "coding_worker_output_dir",
            "dev_worker_max_message_chars": "coding_worker_max_message_chars",
        }
        normalized = dict(data)
        for legacy_key, new_key in remap.items():
            if new_key not in normalized and legacy_key in normalized:
                normalized[new_key] = normalized[legacy_key]
        return normalized

    @property
    def dev_worker_enabled(self) -> bool:
        return self.coding_worker_enabled

    @property
    def dev_worker_codex_command(self) -> str:
        return self.codex_command

    @property
    def dev_worker_model(self) -> str:
        return self.codex_model

    @property
    def dev_worker_codex_sandbox(self) -> str:
        return self.codex_sandbox

    @property
    def dev_worker_workspace_root(self) -> Path:
        return self.coding_worker_workspace_root

    @property
    def dev_worker_output_dir(self) -> Path:
        return self.coding_worker_output_dir

    @property
    def dev_worker_max_message_chars(self) -> int:
        return self.coding_worker_max_message_chars

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
