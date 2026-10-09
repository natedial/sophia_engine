# Sophia Oikonomia

Stateful economic and market model orchestration service for the Sophia ecosystem.

## Purpose

`sophia_oikonomia` sits between upstream data freshness and downstream agent consumption.

It owns:

- model definitions
- data and release dependencies
- trigger-to-model resolution
- run lifecycle
- published projections
- insight-ready projection metadata

It does not replace:

- `scrivener` for ingestion
- `sophia_arithmos` for stateless transforms
- `sophia_kampe` for finance-specific curve/surface lifecycle

## Phase 1 Scope

- register economic and market model definitions
- resolve incoming triggers into impacted models
- create queued run records from triggers or explicit requests
- complete runs with stored output summaries
- publish successful runs as current projections

## Current API Surface

- `GET /health`
- `GET /v1/models`
- `GET /v1/models/{model_id}`
- `POST /v1/models`
- `GET /v1/models/{model_id}/reviews`
- `POST /v1/models/{model_id}/review`
- `POST /v1/models/{model_id}/promote`
- `POST /v1/triggers/plan`
- `POST /v1/triggers/execute`
- `POST /v1/runs`
- `POST /v1/runs/execute`
- `GET /v1/runs/{run_id}`
- `POST /v1/runs/{run_id}/execute`
- `POST /v1/runs/{run_id}/complete` (requires `lease_owner` and `lease_generation`)
- `POST /v1/runs/{run_id}/recover-legacy`
- `GET /v1/publications`
- `GET /v1/publications/latest/{model_id}`
- `POST /v1/publications`

## Local Run

```bash
PYTHONPATH=services/sophia_oikonomia/src python -m sophia_oikonomia --host 127.0.0.1 --port 8006
```

## Architecture

`market_models/` remains the external incubation workspace for wrappers and experiments.

Stable adapters should be promoted into `sophia_oikonomia/adapters/` and executed through this service once they are ready for production lifecycle management.

## First Promoted Adapter

Phase 1 now includes a promoted `bistro` adapter that:

- resolves series dependencies through Scrivener HTTP APIs
- constructs immutable input snapshots with upstream metadata and observations
- executes the external BISTRO wrapper from `market_models/` when dependencies and model artifact paths are available

## Hardened Promotion Workflow

Oikonomia now supports explicit production lifecycle states:

- `research`
- `candidate`
- `shadow`
- `champion`
- `retired`

Promotion is intended to follow:

1. review gates recorded on the model
2. promotion into `candidate`, `shadow`, or `champion`
3. only `shadow` and `champion` models auto-run from incoming triggers
4. only `champion` models can publish projections

Champion promotion is slot-based. Promoting a new model to champion in the same `production_slot` demotes the prior champion to `shadow` and records it as the rollback target.

## Execution leases and upgrade drain

Oikonomia is the sole execution owner. `execute_run` acquires a renewable lease (default 60s, heartbeat every 10s) before invoking an adapter. A second caller that hits a valid lease receives the pending `RUNNING` record and does not start another computation. Completions must present the current `lease_owner` and `lease_generation`; stale or missing credentials are rejected.

Stop old workers before upgrading. Pre-migration `RUNNING` rows have no lease metadata. Missing metadata is not proof that the worker died, so those rows are **not** auto-reclaimed. After the old process is gone, call:

```bash
curl -X POST http://127.0.0.1:8006/v1/runs/$RUN_ID/recover-legacy \
  -H 'content-type: application/json' \
  -d '{"owner":"operator"}'
```

That attaches an already-expired lease. A later `POST /v1/runs/{id}/execute` may then acquire the next generation. Do not recover while a mixed-version worker might still be writing.
