# Sophia Monorepo

Unified workspace for Sophia engine services and MCP-exposed tools.

## Structure

- `agents/` - Legacy user-facing agents (e.g. sophia_prima)
- `services/` - Backend services (scrivener, sophia_arithmos, sophia_kampe, sophia_pylon)
- `core/` - Shared core packages (episto, onto, teleo)
- `shared/` - Shared schemas, client helpers
- `infra/` - Deployment artifacts
- `docs/` - System-level docs and runbooks

## Quick Start (Local Dev)

```bash
python3.11 -m venv .venv
source .venv/bin/activate

cd services/sophia_pylon && pip install -e ".[mcp]"
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
- `http://localhost:8091/mcp` sophia_pylon_mcp
- `http://localhost:13000` sophia_dashboard

Useful commands:
- `make logs`
- `make ps`
- `make down`

Agent notes:
- Hermes or another MCP-capable agent should connect to `http://localhost:8091/mcp`.
- The MCP server exposes Pylon tools plus `sophia_pylon_preflight`.
- `agents/sophia_prima` remains available as legacy orchestration code.
- To start the old Prima gateway, run compose with the `legacy-prima` profile.
