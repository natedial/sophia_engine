# Phase 1: Point-in-time data — design

Date: 2026-11-12. Source: the mechanism-registry handover (`docs/2026-11-11-mechanism-registry-handover.md`), review items R5 and R6, and the Scrivener section of the training-plan tab. Owner approved the outline in chat on 2026-11-12.

## Why

Today Scrivener overwrites a value when it is revised, and the research path never reads Scrivener: the agent passes observations inline, so the "vintage" on every result is a label the agent typed. The registry phases need to ask "what did we know on date X?" and get an answer the engine can check. Predictions (Phase 4) resolve against the first print; backtests (Phase 3) replay history one release at a time. Both need stored vintages.

## Exit criterion

The same test request at two as-of dates returns two different hashed snapshots, and each replays byte-identical.

## Goals

1. Scrivener keeps every vintage of every observation; nothing is overwritten.
2. `GET /series/{id}/observations` accepts `as_of` and returns what was known then; it can also return first prints.
3. `GET /changes?since=` lists series that gained observations or revisions.
4. One call returns a release's first print together with every forecast row for that release.
5. A test can be requested by series reference and as-of date; Oikonomia builds the snapshot from Scrivener and stores its content hash. Inline observations are marked `agent_supplied`.

## Non-goals

- Choosing which forecast counts as consensus (owner decision 8; blocks Phase 3, not this phase). The endpoint returns all rows with source and review status.
- The registry tables, `list_due`, predictions, scoring (Phases 2–4).
- Alembic baseline (R-item for migrations) — keep `create_all` plus a hand-written SQL file, as today.
- Backfilling BLS history; BLS has no public vintage archive.

## Anti-goals

- An as-of read that can return a value published after the as-of date.
- A snapshot hash that changes on replay of a settled as-of date.
- Silent float formatting differences between write and replay.

## Decided

- **Vintage key.** Observations are insert-only, unique on `(series_id, date, realtime_start)`. `realtime_start` is the date a value became known (date granularity, as ALFRED uses). Column `vintage_source` says where it came from: `alfred` (FRED's archive) or `observed` (Scrivener first saw it on that date; used for BLS and for any FRED value fetched outside ALFRED). `revision_num` is dropped.
- **No duplicate vintages.** A new row is written only when its value differs from the latest stored vintage for that `(series_id, date)`. This absorbs ALFRED clipping `realtime_start` to the requested window start on incremental fetches.
- **FRED fetch.** Every FRED fetch goes through ALFRED (`get_series_all_releases` with a `realtime_start`). The daily sweep requests vintages since the last stored `realtime_start` for that series. ALFRED caps vintage dates per request, so backfill walks the realtime range in chunks.
- **History depth.** Reference series `CPILFESL`, `DGS2`, `SOFR` backfill their full ALFRED history; all others keep the existing 5-year observation window.
- **BLS.** Rows are stored with `vintage_source = observed` and `realtime_start` = the fetch date (America/New_York). History before tracking began does not exist and is not invented.
- **As-of rule.** A row is visible at `as_of` when `realtime_start <= as_of`. For each date the visible row with the greatest `realtime_start` is returned. `first_print=true` returns the row with the least `realtime_start` instead. Without `as_of`, reads return the latest vintage, so existing callers see no change.
- **Settled.** An as-of response is `settled` when `as_of` is before today in America/New_York. Only settled snapshots are guaranteed to replay; unsettled ones carry `settled: false` in the snapshot.
- **Values on the wire.** The as-of endpoint returns values as decimal strings straight from `Numeric`, so hashing never depends on float formatting. The existing float field stays for old callers.
- **Change feed.** Driven by a new `first_seen_at timestamptz` on each observation row (server default now). `since` is a timestamp; the response lists per series the count of new dates and of revisions (rows for a date that already had a vintage) and a `next_since` cursor.
- **First print + forecasts.** `GET /series/{id}/first-print?date=YYYY-MM-DD&indicator_key=...` returns the first-print row and every `economic_event_forecasts` row with that `indicator_key` whose `release_date` equals the first print's `realtime_start`, each with `source` and `review_status`. The caller passes `indicator_key`; Scrivener keeps no series-to-indicator map yet.
- **Snapshot by reference (R6).** Episto's `InputSnapshot` gains `source_ref` and `target_ref` (`{series_id, source, window_start, window_end}`), `content_hash`, `settled` and `origin` (`scrivener` | `agent_supplied`). `request_test` accepts refs plus `as_of` instead of observations. Episto never fetches: the Oikonomia runner builds both series through `ScrivenerClient` with `as_of`, computes the hash, and the result's `input_snapshot` carries observations, hash and `origin=scrivener`. The run fingerprint covers refs plus `as_of` plus hash.
- **Hash.** SHA-256 of canonical JSON (sorted keys, no whitespace, UTF-8) of `{as_of, source_ref, target_ref, source_observations, target_observations}` with observation values as the decimal strings Scrivener returned.
- **agent_supplied.** Inline observations get `origin = agent_supplied`. Policy stops granting `predict` from a result whose snapshot is `agent_supplied`; it still grants `explain` as today. Existing assessments are re-scored, as in Phase 0.
- **Rebuild, not migrate.** The local database is one day old. The SQL migration drops and recreates `observations`; the next sweep and the reference backfill refill it.
- **PRs.** One per numbered task group below, each branched from main after the previous merges (no stacked PRs).

## Left to the builder

- Internal helper names, chunk size for ALFRED backfill (within the API cap), CLI command naming for the backfill.
- Whether the latest/first-print selection is a `DISTINCT ON` query or a window function.
