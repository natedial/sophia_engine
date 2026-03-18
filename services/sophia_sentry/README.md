# Sophia Sentry

Background watch-and-alert runtime for the Sophia ecosystem.

## Purpose

`sophia_sentry` is the missing background layer between upstream change and downstream agent use.

It owns:

- watch definitions
- watch evaluation state
- durable event persistence
- background-ready evaluation workflows

It does not replace:

- `scrivener` for data ingestion
- `sophia_oikonomia` for model execution and publication
- `tholos` for research retrieval
- Brave for live web retrieval

## Phase 1 Scope

- register and persist watch definitions
- evaluate `numeric_threshold` watches
- evaluate `model_revision` watches
- persist material events with severity and summaries

## Current API Surface

- `GET /health`
- `GET /v1/watches`
- `GET /v1/watches/{watch_id}`
- `POST /v1/watches`
- `POST /v1/watches/{watch_id}/evaluate`
- `POST /v1/evaluate`
- `GET /v1/events`

## Local Run

```bash
PYTHONPATH=services/sophia_sentry/src python -m sophia_sentry --host 127.0.0.1 --port 8007
```

## Initial Watch Kinds

- `numeric_threshold`
- `model_revision`

Future watch kinds should include:

- `web_topic`
- `release_surprise`
- `language_shift`
- `briefing_digest`
