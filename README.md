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
