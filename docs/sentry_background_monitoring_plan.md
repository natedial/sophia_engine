# Sophia Sentry Background Monitoring Plan

## Goal

Add a background operating layer to the Sophia stack that can notice meaningful change,
evaluate whether it matters, enrich it, and persist actionable events without waiting for a
user prompt.

## Why Sentry

The current platform is strong at pull-based execution:

- `scrivener` refreshes upstream data
- `sophia_oikonomia` reruns and publishes models
- `tholos` and Brave provide context retrieval
- `sophia_prima` and `pylon` expose interactive capabilities

What is still missing is a stateful watch runtime that can:

- monitor configured conditions in the background
- evaluate materiality
- emit durable insight events
- drive inboxes, alerts, and briefings downstream

## Service Boundary

Create `services/sophia_sentry/` as a dedicated background service.

Owns:

- watch definitions
- watch state
- scheduled evaluation
- event persistence
- delivery status
- briefing-ready event feeds

Does not own:

- raw data ingestion
- model execution
- full-text research indexing
- browser automation

## Initial Watch Types

Phase 1 should support two concrete watch kinds:

1. `numeric_threshold`
   - Trigger when a named numeric signal crosses a threshold or moves materially versus prior state.
   - Examples: 10Y yield above 5%, auction tail beyond a threshold, CPI monthly print surprise.

2. `model_revision`
   - Trigger when a published model metric changes materially versus the prior value.
   - Examples: Oikonomia inflation projection revised by more than 30bp, recession probability jumps.

Future phases should add:

- `web_topic`
- `release_surprise`
- `language_shift`
- `briefing_digest`

## Execution Workflow

1. A cron tick, upstream trigger, or manual request reaches Sentry.
2. Sentry resolves the set of enabled watches to evaluate.
3. For each watch, Sentry loads the last known state.
4. Sentry evaluates the current observation payload against watch policy.
5. If material, Sentry persists an event with severity, summary, and payload.
6. Delivery workers can later route that event to inboxes, Telegram, dashboards, or briefing queues.

## Storage Model

Use SQLite first for local development and service bootstrap:

- `sentry_watches`
- `sentry_state`
- `sentry_events`

Later, move structured metadata to Postgres if event volume or multi-writer access requires it.

## Initial API Surface

- `GET /health`
- `GET /v1/watches`
- `GET /v1/watches/{watch_id}`
- `POST /v1/watches`
- `POST /v1/watches/{watch_id}/evaluate`
- `POST /v1/evaluate`
- `GET /v1/events`

## Phase 1 Implementation Cut

The first implementation inside `sophia_engine` should do four things:

1. persist watch definitions and watch state
2. evaluate numeric threshold watches
3. evaluate model revision watches
4. persist material events as a durable feed

This is enough to create a real background monitoring boundary before integrating the full
enrichment and delivery pipeline.

## Planned Integrations

Future work should connect Sentry directly to:

- Scrivener release and data-refresh triggers
- Oikonomia publication changes
- Brave-backed web topic watches
- briefing and notification delivery channels
