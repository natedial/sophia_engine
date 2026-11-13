# Phase 1: Point-in-time Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrivener keeps every vintage and answers as-of reads; a research test can be requested by series reference and as-of date, and its snapshot is content-hashed and replays byte-identical.

**Architecture:** Observations become insert-only rows keyed on `(series_id, date, realtime_start)`. FRED data comes from ALFRED; BLS rows are stamped with the date Scrivener first saw them. Readers pick the latest vintage (or, as-of, the latest visible one). Oikonomia's `ScrivenerClient` gains `as_of` and a canonical hash; Episto passes series refs through to the Oikonomia runner and never fetches.

**Tech Stack:** Python 3.12, SQLAlchemy 2 + Postgres 16 (Scrivener), FastAPI, fredapi, httpx, Pydantic v2, SQLite ledger (Episto), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-12-phase1-point-in-time-data-design.md`

## Global Constraints

- Start from `main` after PR #48 merges. One PR per task group (A–E below); branch each from `main` after the previous one merges. Do not stack PRs.
- Test-first for every behavior change; watch each new test fail before the code exists.
- No invented thresholds. The only fixed numbers are those in the spec: reference series `CPILFESL`, `DGS2`, `SOFR`; 5-year window for others; timezone `America/New_York` for "today".
- Episto never fetches data or calls Scrivener.
- Do not touch Supabase. Do not print secrets from `infra/.env`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the Claude Code line.

## Review Focus

1. **ALFRED clipping on incremental fetch.** A request with `realtime_start=X` reports older unrevised values with `realtime_start=X`; they must not become new vintages. Pinned in Task A1 (`test_unchanged_value_is_not_a_new_vintage`).
2. **As-of on the release day.** A value with `realtime_start == as_of` is visible at that `as_of`. Pinned in Task B1 (`test_value_released_on_as_of_date_is_visible`).
3. **Replay of an unsettled as-of.** `as_of` = today must say `settled: false`, and a later vintage on the same day may change it. Pinned in Task B1 (`test_as_of_today_is_not_settled`).
4. **Float drift in the hash.** The hash must be computed over decimal strings, not floats. Pinned in Task D1 (`test_hash_uses_decimal_strings`).
5. **Existing callers.** `GET /series/{id}/observations` without `as_of`, `get_latest`, `get_change` must return one row per date (latest vintage), not one per vintage. Pinned in Task A1 (`test_readers_return_one_row_per_date`).

---

## PR A — Keep every vintage

### Task A0: Scrivener tests in CI with a Postgres service

**Files:**
- Create: `services/scrivener/tests/db.py` (fixture `pg_session` that connects to `SCRIVENER_TEST_DATABASE_URL`, runs `Base.metadata.create_all`, truncates between tests, and `pytest.skip`s when the variable is unset)
- Modify: `.github/workflows/research-tests.yml` (new job `scrivener` with `services: postgres:16`, env `SCRIVENER_TEST_DATABASE_URL`, `pip install -e services/scrivener[dev]`, `pytest`; add `services/scrivener/src/fetchers services/scrivener/src/query services/scrivener/tests` to the ruff job only for files this phase touches, so pre-existing lint debt stays out of scope)

**Interfaces:**
- Produces: pytest fixture `pg_session` yielding a SQLAlchemy `Session` bound to an empty schema; `get_session()` in code under test must use the same engine (monkeypatch `src.db.connection` engine to the test URL).

- [ ] Step 1: write `tests/test_pg_fixture.py::test_fixture_gives_empty_observations` asserting `session.query(Observation).count() == 0`.
- [ ] Step 2: run locally with a scratch Postgres (`LC_ALL=C` initdb, TCP on 127.0.0.1, no socket dir). Expected: PASS; without the env var, SKIPPED.
- [ ] Step 3: commit `test(scrivener): Postgres-backed test fixture and CI job`.

### Task A1: Insert-only vintage storage and latest-vintage readers

**Files:**
- Modify: `services/scrivener/src/db/models.py` — `Observation`: add `realtime_start: Date NOT NULL`, `vintage_source: String(16) NOT NULL` (`alfred` | `observed`), `first_seen_at: DateTime(tz) server_default now()`; drop `revision_num`; unique index `idx_observations_vintage (series_id, date, realtime_start)`; index `idx_observations_first_seen (first_seen_at)`.
- Create: `services/scrivener/migrations/007_observation_vintages.sql` — `DROP TABLE observations` and recreate to match the model (spec: rebuild, not migrate).
- Modify: `services/scrivener/src/fetchers/base.py` — replace `upsert_observations` with `store_vintages(series_id, observations) -> dict` returning `{"new_dates": int, "revisions": int, "unchanged": int}`. Each input dict has `date`, `value`, `realtime_start`, `vintage_source`. Insert only when no vintage exists for `(series_id, date)` or the latest stored vintage's value differs; `ON CONFLICT (series_id, date, realtime_start) DO NOTHING`. `fetch_and_store` reports `records_inserted = new_dates + revisions`. An input row without `realtime_start` is stored as `vintage_source="observed"` with `realtime_start` = today in America/New_York, so the sweep keeps working between A1 and A2.
- Modify: `services/scrivener/src/query/series.py` — `get_observations`, `get_latest`, `get_change`, `get_multiple_latest` select the latest vintage per date.
- Test: `services/scrivener/tests/test_vintages.py`

**Interfaces:**
- Produces: `BaseFetcher.store_vintages(series_id: int, observations: list[dict]) -> dict[str, int]`; helper `latest_vintages(session, series_id, start, end, *, as_of: date | None = None, first_print: bool = False)` in `src/query/series.py` returning `Observation` rows, one per date (Task B1 adds the `as_of`/`first_print` branches; A1 implements the default).

- [ ] Step 1: write tests (all use `pg_session`):
  - `test_first_value_is_stored` — one input row → `new_dates == 1`.
  - `test_revised_value_adds_a_row` — same date, later `realtime_start`, different value → 2 rows, `revisions == 1`.
  - `test_unchanged_value_is_not_a_new_vintage` — same date and value, later `realtime_start` → still 1 row, `unchanged == 1`.
  - `test_readers_return_one_row_per_date` — two vintages for one date; `SeriesQuery.get_observations` returns one row with the later value; `get_latest` returns the later value.
- [ ] Step 2: run `pytest tests/test_vintages.py -v`. Expected: FAIL (`store_vintages` missing).
- [ ] Step 3: implement model, migration, `store_vintages`, readers.
- [ ] Step 4: run the full Scrivener suite. Expected: all pass.
- [ ] Step 5: commit `feat(scrivener): store observations insert-only by vintage`.

### Task A2: FRED through ALFRED, BLS as observed

**Files:**
- Modify: `services/scrivener/src/fetchers/fred.py` — `fetch_observations` calls `get_series_all_releases(external_id, realtime_start=<since>)` and returns rows with `realtime_start` (date) and `vintage_source="alfred"`; `<since>` is the series' greatest stored `realtime_start`, or the observation-window start when none. Remove `fetch_with_revisions` (superseded).
- Modify: `services/scrivener/src/fetchers/bls.py` — rows get `realtime_start = today in America/New_York`, `vintage_source="observed"`.
- Test: `services/scrivener/tests/test_vintage_fetchers.py` (stub the fredapi client; no network).

**Interfaces:**
- Consumes: `store_vintages` (A1).
- Produces: `FredFetcher.fetch_observations(external_id, start_date=None, end_date=None) -> list[dict]` with keys `date, value, realtime_start, vintage_source`.

- [ ] Step 1: tests — `test_fred_rows_carry_alfred_realtime_start`; `test_fred_incremental_fetch_starts_at_last_stored_vintage` (assert the stub saw `realtime_start` equal to the stored max); `test_bls_rows_are_observed_today` (freeze time at 2026-11-12 23:30 UTC → `realtime_start == date(2026, 11, 12)` because it is 18:30 ET).
- [ ] Step 2: run. Expected: FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: full suite. Expected: pass.
- [ ] Step 5: commit `feat(scrivener): fetch FRED vintages from ALFRED; stamp BLS as observed`.

### Task A3: Full-history backfill for the reference series

**Files:**
- Modify: `services/scrivener/src/fetchers/fred.py` — `backfill_vintages(external_id: str) -> dict` walks the realtime range from the series' first vintage to today in chunks that stay under ALFRED's vintage-date cap, calling `store_vintages` per chunk.
- Modify: `services/scrivener/src/cli.py` — command `backfill-vintages [SERIES...]`, default `CPILFESL DGS2 SOFR`.
- Modify: `services/scrivener/README.md` — one paragraph under "Running in-house".
- Test: `services/scrivener/tests/test_vintage_fetchers.py::test_backfill_requests_chunks_covering_the_whole_range` (stub records the `(realtime_start, realtime_end)` pairs; assert they are contiguous and cover first vintage → today).

- [ ] Steps: test → FAIL → implement → full suite → commit `feat(scrivener): backfill full vintage history for reference series`.
- [ ] After merge (not in CI): run `scrivener backfill-vintages` against the local stack and record row counts per series in the PR description.

## PR B — As-of reads

### Task B1: `as_of` and `first_print` on the observations endpoint

**Files:**
- Modify: `services/scrivener/src/query/series.py` — `latest_vintages` honours `as_of` (only rows with `realtime_start <= as_of`, latest per date) and `first_print` (least `realtime_start` per date). `get_observations` gains `as_of: date | None`, `first_print: bool`.
- Modify: `services/scrivener/src/api/main.py` — endpoint query params `as_of`, `first_print`. When either is set, response model `VintageObservation {date: str, value: str | None, realtime_start: str, vintage_source: str}` wrapped as `{"as_of": str | None, "settled": bool, "observations": [...]}`; otherwise the existing list response, unchanged.
- Test: `services/scrivener/tests/test_as_of.py`

- [ ] Step 1: tests — `test_as_of_before_revision_returns_original`; `test_as_of_after_revision_returns_revised`; `test_value_released_on_as_of_date_is_visible`; `test_first_print_ignores_later_revisions`; `test_as_of_today_is_not_settled` and `test_as_of_yesterday_is_settled` (freeze clock); `test_values_are_decimal_strings` (`"3.10"` stays `"3.10"`, is not `3.1`); `test_no_as_of_keeps_old_response_shape`.
- [ ] Steps 2–5: FAIL → implement → full suite → commit `feat(scrivener): as-of and first-print reads`.

## PR C — Change feed and first print with forecasts

### Task C1: `GET /changes?since=`

**Files:**
- Create: `services/scrivener/src/query/changes.py` — `ChangeQuery.since(since: datetime) -> dict` returning `{"since": iso, "next_since": iso, "series": [{"series_id", "source", "new_dates", "revisions", "last_seen_at"}]}`; `next_since` is the greatest `first_seen_at` returned, or `since` when nothing changed.
- Modify: `services/scrivener/src/api/main.py` — route; `since` required, timezone-aware.
- Test: `services/scrivener/tests/test_changes.py` — `test_new_date_counts_as_new`; `test_second_vintage_counts_as_revision`; `test_nothing_after_cursor_returns_same_cursor`; `test_naive_since_is_rejected` (422).

- [ ] Steps: test → FAIL → implement → suite → commit `feat(scrivener): change feed`.

### Task C2: `GET /series/{id}/first-print`

**Files:**
- Modify: `services/scrivener/src/query/forecasts.py` — `ForecastQuery.for_release(indicator_key: str, release_date: date) -> list[dict]` (all rows, each with `source`, `review_status`).
- Modify: `services/scrivener/src/api/main.py` — route with params `date` (required), `indicator_key` (optional). Response `{"series_id", "date", "first_print": VintageObservation, "forecasts": [...]}`; `forecasts` is `[]` when `indicator_key` is absent; 404 when the date has no vintage.
- Test: `services/scrivener/tests/test_first_print.py` — `test_returns_first_print_not_revision`; `test_forecasts_match_release_date_of_first_print`; `test_pending_forecasts_are_returned_with_status` (no filtering by review status); `test_unknown_date_is_404`.

- [ ] Steps: test → FAIL → implement → suite → commit `feat(scrivener): first print with forecasts for a release`.

## PR D — Hashed snapshots in Oikonomia

### Task D1: `as_of` and content hash in `ScrivenerClient`

**Files:**
- Modify: `services/sophia_oikonomia/src/sophia_oikonomia/clients/scrivener.py` — `get_observations(..., as_of: date | None = None)`; when `as_of` is set, parse the B1 wrapped response and keep values as strings. `SeriesSnapshot` gains `as_of: date | None`, `settled: bool | None`. New module-level `snapshot_hash(payload: dict) -> str` (spec's canonical JSON + SHA-256) and `build_pair_snapshot(source_ref: dict, target_ref: dict, as_of: date) -> dict` returning `{as_of, settled, source_ref, target_ref, source_observations, target_observations, content_hash}`; `settled` is the AND of both series.
- Test: `services/sophia_oikonomia/tests/test_scrivener_snapshot.py` using `httpx.MockTransport`: `test_hash_is_stable_across_calls`; `test_hash_changes_with_as_of` (two as-of responses differ → hashes differ); `test_hash_uses_decimal_strings` (`"3.10"` vs `"3.1"` give different hashes; float never appears); `test_unsettled_side_makes_pair_unsettled`.

**Interfaces:**
- Produces: `ScrivenerClient.build_pair_snapshot(source_ref: dict, target_ref: dict, as_of: date) -> dict` and `snapshot_hash(payload: dict) -> str`.

- [ ] Steps: test → FAIL → implement → `pytest` in Oikonomia → commit `feat(oikonomia): as-of snapshots with content hash`.

## PR E — Request tests by reference

### Task E1: Episto contract and `request_test` by reference

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/research/contracts.py` — `SeriesRef(series_id: str, source: str | None, window_start: str, window_end: str)`; `InputSnapshot` gains `source_ref: SeriesRef | None`, `target_ref: SeriesRef | None`, `content_hash: str | None`, `settled: bool | None`, `origin: Literal["scrivener", "agent_supplied"] = "agent_supplied"`. A validator requires either both refs plus `as_of`, or inline observations — not both.
- Modify: `core/sophia_episto/src/sophia_episto/research/engine.py` — `_run_fingerprint` includes refs and `as_of` when present.
- Modify: `core/sophia_episto/src/sophia_episto/research/oikonomia_runner.py` — when refs are present, call `build_pair_snapshot`, fill the result's `input_snapshot` with observations (decimal strings converted at the Arithmos boundary only), `content_hash`, `settled`, `origin="scrivener"`. Scrivener base URL from Oikonomia's existing config.
- Test: `core/sophia_episto/tests/test_research/test_snapshot_by_reference.py` with a fake `ScrivenerClient` injected into the runner: `test_request_by_reference_records_hash_and_origin`; `test_inline_observations_are_agent_supplied`; `test_refs_and_inline_together_are_rejected`; **exit criterion** `test_two_as_of_dates_give_two_hashes_and_each_replays` (request at as-of D1 and D2 over a fake with a revision between them → two different hashes; repeating each request returns the same hash and byte-identical `input_snapshot` JSON).

- [ ] Steps: test → FAIL → implement → Episto suite with Oikonomia and Arithmos installed (as CI does) → commit `feat(episto): request tests by series reference and as-of date`.

### Task E2: `agent_supplied` results do not grant `predict`

**Files:**
- Modify: `core/sophia_episto/src/sophia_episto/research/policy.py` — `predict` is granted only from succeeded results whose `input_snapshot.origin == "scrivener"`; add limitation `agent_supplied_inputs` otherwise. `explain` unchanged.
- Modify: the policy version constant, and run the existing re-score path so stored assessments are recomputed (as Phase 0 did).
- Test: `core/sophia_episto/tests/test_research/test_policy_origin.py` — `test_agent_supplied_result_does_not_grant_predict`; `test_scrivener_result_grants_predict`; `test_rescore_removes_predict_from_old_inline_assessment`.

- [ ] Steps: test → FAIL → implement → Episto suite → commit `feat(episto): agent-supplied inputs do not support predict`.

## After the last PR

- Run the exit check live: request one Granger test for `CPILFESL` → `DGS2` at two settled as-of dates on either side of a CPI revision in the backfilled data; record both hashes and a replay in the PR description.
- Final whole-branch review per the executing skill, then update the handover's phase table.
