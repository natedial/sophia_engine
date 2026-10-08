# Slice D runtime inventory

Date: 2026-10-08  
Checkout: `cursor/causal-slice-d-70a1` stacked on Slice C  
Research path: outside agent → `sophia-research` CLI → Episto ledger → Oikonomia → Arithmos Granger

This is a usage inventory, not a deployment shutdown. Package trees for Prima, Forge, Canvas, and the dashboard remain in git until a later deletion pass. They are off the default runtime.

| Surface | Consumers found | Disposition this slice |
|---|---|---|
| Episto research CLI / ledger | Outside agent, research tests | **KEEP** |
| Arithmos Granger | Oikonomia hypothesis-test adapter | **KEEP** |
| Oikonomia in-process runtime | Episto `OikonomiaMethodRunner` | **KEEP** |
| Scrivener | Compose default; observations owner | **KEEP** |
| Prima gateway / Telegram / LLM | Compose `sophia_gateway` | **RETIRE-FROM-RUNTIME** (`legacy-assistant` profile). Causal adapter no longer loads `causal_service`. |
| Canvas | Compose `sophia_canvas` | **RETIRE-FROM-RUNTIME** |
| Dashboard | Compose `sophia_dashboard` | **RETIRE-FROM-RUNTIME** |
| Tholos + semantic ML | Compose `sophia_tholos`; default semantic on | **RETIRE-FROM-RUNTIME**; semantic defaults **off** |
| Kampe | Compose `sophia_kampe` only | **RETIRE-FROM-RUNTIME** |
| Forge | Not in compose; Prima coding client | **RETIRE-FROM-RUNTIME** (already not default-on) |
| Pylon | Prima library, not a server | **RETIRE-FROM-RUNTIME** (research CLI does not use it) |
| Sentry | Not in compose; optional Oikonomia notify | **KEEP optional client**; service not default-on |
| Episto optimizer / AutoresearchAdapter | No runtime importers | **DELETE-STUB** |
| PC / causal-learn in `discovery.py` | Zero callers; silent empty on ImportError | **DELETE-STUB** |
| `causal_service` daily batch | Prima adapter (now uncoupled); import smoke test | **UNCOUPLE**; keep module for graph.json until importer-only path is enough |

Inspection covered: `infra/docker-compose.yml`, `Makefile`, Python imports, package tests, Dockerfiles. No live deployment traffic was available; dispositions are from this checkout.
