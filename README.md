# Sophia Monorepo

Unified workspace for Sophia engine services and MCP-exposed tools.

## Structure

- `agents/` - Optional/local agent experiments; Hermes is the launch agent loop
- `services/` - Backend services and MCP-facing tools
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
- `http://localhost:8006` sophia_oikonomia
- `http://localhost:8091/mcp` sophia_pylon_mcp
- `http://localhost:13000` sophia_dashboard

Useful commands:
- `make logs`
- `make ps`
- `make down`

Agent notes:
- Hermes on the same machine: `http://localhost:8091/mcp` (default bind `127.0.0.1`).
- Hermes on another Tailscale host: set `PYLON_MCP_BIND_ADDRESS=0.0.0.0` in `infra/.env`, then use `http://<sophia-magicdns-or-100.x>:8091/mcp`. See `docs/runbook.md`.
- The MCP server exposes Pylon tools plus `sophia_pylon_preflight`.
- Prima is intentionally out of the default launch path; Hermes owns orchestration for this test suite.
