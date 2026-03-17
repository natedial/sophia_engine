# Sophia Prima

Sophia Prima is the conversational agent layer for the Sophia system.

It now includes:
- Interactive CLI (`sophia`)
- Surface gateway daemon (`sophia-gateway`) with deterministic routing
- Telegram channel adapter support via gateway-owned polling
- Optional `coding_worker` subagent for delegated repo changes via Codex or Claude Code
- Optional append-only lossless history for debugging and reflection

## Run Gateway

```bash
sophia-gateway
```

Default bind:
- host: `0.0.0.0`
- port: `8080`

Environment-driven routing:
- `GATEWAY_DEFAULT_AGENT_ID`
- `GATEWAY_BINDINGS_JSON`

LLM provider:
- `LLM_PROVIDER` (`openai` default, `anthropic` or `groq` optional)
- `OPENAI_API_KEY` (required when `LLM_PROVIDER=openai`)
- `OPENAI_BASE_URL` (optional override)
- `GROQ_API_KEY` (required when `LLM_PROVIDER=groq`)
- `GROQ_BASE_URL` (optional override; default `https://api.groq.com`)
- `ANTHROPIC_API_KEY` (required when `LLM_PROVIDER=anthropic`)
- `LLM_REQUEST_TIMEOUT_SEC` (optional HTTP timeout; default `180`)
- `PERSONALITY_PATH` (optional personality markdown override)
- `SOUL_PATH` (optional soul markdown override)
- `LESSONS_PATH` (optional read-only `LESSONS.md` seed layer path)
- `AGENT_FS_ENFORCE_WRITE_POLICY` (`true` default, deny-by-default write guard)
- `AGENT_FS_WRITE_ALLOWLIST` (comma-separated writable roots, default `.sophia`)
- `AGENT_FS_ENFORCE_READ_POLICY` (`true` default, deny-by-default read guard)
- `AGENT_FS_READ_ALLOWLIST` (comma-separated readable roots, default `config,skills,.sophia`)
- `CODING_WORKER_ENABLED` (`false` default)
- `CODING_WORKER_BACKEND` (`codex` default; `claude_code` optional)
- `CODING_WORKER_WORKSPACE_ROOT` (repo/worktree root the worker may edit)
- `CODING_WORKER_OUTPUT_DIR` (default `.sophia/coding_worker`)
- `CODEX_COMMAND` (`codex` default)
- `CODEX_MODEL` (optional Codex model override)
- `CODEX_SANDBOX` (`workspace-write` default)
- `CLAUDE_CODE_COMMAND` (`claude` default)
- `CLAUDE_CODE_MODEL` (optional Claude Code model override)
- `HISTORY_ENABLED` (`false` default)
- `HISTORY_STORE_PATH` (default `.sophia/history.db`)
- `HISTORY_TOOL_RESULT_MAX_CHARS` (`50000` default; `0` keeps full tool results)

Legacy `DEV_WORKER_*` env names remain supported for compatibility.

When enabling `coding_worker`, widen `AGENT_FS_READ_ALLOWLIST` and `AGENT_FS_WRITE_ALLOWLIST`
to include the repo/worktree root you want the delegated coding backend to inspect and modify.
When enabling lossless history, widen `AGENT_FS_READ_ALLOWLIST` and `AGENT_FS_WRITE_ALLOWLIST`
to include `HISTORY_STORE_PATH`.

Telegram:
- `TELEGRAM_BOT_TOKEN` (single account fallback)
- `TELEGRAM_ACCOUNTS_JSON` (multi-account config)
- `TELEGRAM_POLLING_ENABLED` (`true`/`false`)
