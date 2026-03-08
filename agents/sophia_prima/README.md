# Sophia Prima

Sophia Prima is the conversational agent layer for the Sophia system.

It now includes:
- Interactive CLI (`sophia`)
- Surface gateway daemon (`sophia-gateway`) with deterministic routing
- Telegram channel adapter support via gateway-owned polling

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

Telegram:
- `TELEGRAM_BOT_TOKEN` (single account fallback)
- `TELEGRAM_ACCOUNTS_JSON` (multi-account config)
- `TELEGRAM_POLLING_ENABLED` (`true`/`false`)
