# Economic Model Orchestration Plan

## Goal

Move economic and market model execution from an external experimentation repo into a stateful Sophia runtime that can:

- know which models depend on which data
- rerun models when new inputs arrive
- persist input snapshots, runs, projections, and insights
- publish stable outputs for Sophia Prima and downstream tools
- score model quality over time as actuals arrive

## Recommended Repo Hierarchy

Keep `~/devwork/market_models` as the incubation workspace:

- external repos and wrappers
- experiments and notebooks
- benchmark harnesses
- draft adapters before promotion

Use `sophia_engine` as the production runtime:

- `services/scrivener/`
  - source-of-truth ingestion, normalization, release calendar, market/econ data APIs
- `services/sophia_arithmos/`
  - stateless transforms, regressions, descriptive analytics
- `services/sophia_kampe/`
  - stateful finance-specific surfaces and curves
- `services/sophia_oikonomia/`
  - stateful orchestration for macro, market, and forecasting models

## Service Boundaries

### Scrivener

Owns:

- raw series ingestion
- release-aware scheduling for upstream data
- market/economic query APIs

Does not own:

- model reruns
- forecast publication
- model scoring

### Arithmos

Owns:

- transformations
- regressions
- helper analytics

Does not own:

- model state
- projection lifecycle

### Oikonomia

Owns:

- model definitions
- dependency graph from data inputs to models
- trigger resolution
- immutable input snapshots
- run records and lifecycle
- publication records
- time-series delta analysis
- insight extraction
- champion/challenger scoring

## Storage Model

Use Postgres for structured metadata:

- `model_definitions`
- `model_dependencies`
- `input_snapshots`
- `model_runs`
- `published_projections`
- `projection_insights`
- `model_scores`

Use file or object storage for heavy artifacts:

- `data/model_runs/<family>/<model_id>/<as_of_date>/<run_id>/`
  - `input_snapshot.json`
  - `raw_output.json`
  - `analysis.json`
  - `insights.json`

## Trigger Model

Use a hybrid scheduling model.

### Event-driven triggers

Fire when:

- Scrivener refreshes a series used by a model
- a release lands, such as CPI, NFP, FOMC, Treasury refunding
- a manual override or analyst rerun is requested

### Scheduled triggers

Use for:

- daily close reruns for market-sensitive models
- weekly recalibration
- monthly forecast refresh
- periodic backfills and rescoring

## Execution Workflow

1. Scrivener ingests or updates data.
2. Oikonomia receives a trigger with source, series IDs, release metadata, and as-of timestamp.
3. Oikonomia resolves which active models are impacted.
4. Oikonomia creates an immutable input snapshot reference for each model run.
5. The model adapter executes against that snapshot.
6. Post-run analysis compares:
   - new forecast vs prior forecast
   - new forecast vs actual realizations
   - new forecast vs peer models
   - new uncertainty vs prior uncertainty
7. Insight extraction emits only material changes.
8. A successful run can be published as the current projection.

## Publication Contract

Each published projection should expose:

- `model_id`
- `as_of`
- `input_snapshot_id`
- `forecast_horizon`
- `base_projection`
- `scenario_projections`
- `uncertainty_summary`
- `change_vs_prior`
- `quality_score`
- `insight_summary`
- `trade_relevance`

## Phase 1 Implementation Cut

The first implementation inside `sophia_engine` should do four things:

1. Create `services/sophia_oikonomia/`.
2. Persist model definitions plus data dependencies.
3. Resolve data and release triggers into queued run records.
4. Persist run completion and publication records.

This is enough to connect Scrivener’s data freshness to a real model lifecycle without prematurely building every adapter.

## Initial API Surface

- `GET /health`
- `GET /v1/models`
- `POST /v1/models`
- `POST /v1/triggers/plan`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `POST /v1/runs/{run_id}/complete`
- `GET /v1/publications`
- `POST /v1/publications`

## First Adapter Priority

Promote one stable model first, preferably BISTRO, behind an Oikonomia adapter. Do not migrate the full `market_models` workspace at once.

## Future Work

### Scrivener Trigger Emission

Future production work should make Scrivener emit explicit Oikonomia triggers instead of relying on manual or ad hoc API calls.

Recommended follow-on:

- emit `data_refresh` triggers after successful series updates
- emit `economic_release` triggers after release-aware fetch jobs complete
- include source, provider, series IDs, and as-of timestamp in the trigger payload
- support idempotency so repeated ingestion jobs do not create duplicate model runs

### CI and Promotion Automation

Future production work should automate the promotion gates currently modeled in Oikonomia.

Recommended follow-on:

- contract-test replay for promoted adapters
- eval-corpus replay in CI for every promotion candidate
- shadow-run score collection before champion promotion
- deployment-time checks for artifact presence, dependency lock, and latency budget
- promotion bundle generation as a build artifact rather than manual metadata
