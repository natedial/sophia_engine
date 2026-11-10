# Sophia Monorepo

Unified workspace for the Sophia agent, gateway, and backend services.

## Structure

- `agents/` - User-facing agents (e.g. sophia_prima)
- `clients/` - Standalone clients, including the outside research agent
- `services/` - Backend services (Scrivener, Arithmos, Oikonomia, and legacy services)
- `core/` - Shared core packages (episto, onto, teleo)
- `infra/` - Deployment artifacts
- `docs/` - System-level docs and runbooks

## Quick Start (Local Dev)

```bash
python3.11 -m venv .venv
source .venv/bin/activate

pip install -e 'core/sophia_episto[dev,legacy-causal]'
pip install -e 'clients/outside_research_agent[dev]'
```

Inspect the research protocol without starting an agent or LLM provider:

```bash
mkdir -p .sophia
sophia-research --db .sophia/research.db capabilities
outside-research-agent --help
```

See [`docs/runbook.md`](docs/runbook.md) for service and legacy-assistant setup.

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
