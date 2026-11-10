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

Default `make up` is the research stack (postgres, Scrivener, Arithmos). Causal cases run through `sophia-research` / the outside-agent harness, not the gateway.

```bash
make up
```

Services:
- `http://localhost:8000` scrivener
- `http://localhost:8001` sophia_arithmos

Prima, Canvas, dashboard, Telegram, Tholos, and Kampe are the `legacy-assistant` profile:

```bash
make up-legacy
```

Useful commands:
- `make logs`
- `make ps`
- `make down`

The research CLI does not require an LLM provider, Telegram, or the dashboard.
