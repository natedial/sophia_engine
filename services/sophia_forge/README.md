# Sophia Forge

`sophia_forge` is the in-monorepo coding runtime service for Sophia.

Phase 1 scope:

- accept coding run requests over a small HTTP API
- persist run status and runtime events in a forge-owned store
- execute runs through native forge backend adapters
- run forge-owned verification and persist structured verification results
- expose run status, events, artifacts, and verification results to clients such as `sophia_prima`

Current API surface:

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/artifacts`
- `GET /v1/runs/{run_id}/verification`
- `POST /v1/runs/{run_id}/cancel`

`sophia_prima` can call this service through `ForgeClient` when `CODING_RUNTIME_MODE=forge_service`.
