# Sophia Monorepo

Unified workspace for the Sophia agent, gateway, and backend services.

## Structure

- `agents/` - User-facing agents (e.g. sophia_prima)
- `services/` - Backend services (scrivener, sophia_arithmos, sophia_kampe, sophia_pylon)
- `core/` - Shared core packages (episto, onto, teleo)
- `shared/` - Shared schemas, client helpers
- `infra/` - Deployment artifacts
- `docs/` - System-level docs and runbooks

## Quick Start (Local Dev)

```bash
python3.11 -m venv .venv
source .venv/bin/activate

cd services/sophia_pylon && pip install -e .
cd ../../agents/sophia_prima && pip install -e .
```

See `docs/runbook.md` for running the services.

## Quick Start (Docker)

```bash
make up
```

Services:
- `http://localhost:8000` scrivener
- `http://localhost:8001` sophia_arithmos
- `http://localhost:8002` sophia_kampe
- `http://localhost:8003` sophia_canvas
- `http://localhost:13000` sophia_dashboard
- `http://localhost:18080` sophia_gateway

Useful commands:
- `make logs`
- `make ps`
- `make down`

Gateway notes:
- `sophia_gateway` serves `GET /health`, `POST /v1/messages`, and `WS /ws`.
- Set `OPENAI_API_KEY` in `infra/.env` to enable live agent responses.
- Optional: set `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` to use Anthropic instead.
- Optional: set `LLM_PROVIDER=groq` + `GROQ_API_KEY` to use Groq (OpenAI-compatible API).
- Optional: set `PERSONALITY_PATH` and `SOUL_PATH` to override prompt component files.
- Set `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_ACCOUNTS_JSON`) to enable Telegram polling.
