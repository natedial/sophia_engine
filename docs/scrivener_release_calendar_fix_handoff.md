# Scrivener Release Calendar Fix Handoff

## Scope

This handoff covers the Scrivener release calendar hardening work completed in this session and
the remaining operational follow-through.

Current status:

- the release-calendar corruption is repaired
- the broad `sync-releases --days 120` path is healthy again
- the analyst rerun for `research_id=5194` confirmed the payroll-related `no_event_found` failure mode is gone
- residual misses are now narrowed to canonicalization gaps for Retail Sales and ISM matching

Implemented in this session:

- paginated FRED fetching for `releases` and `releases/dates`
- completeness-aware `release_dates` reconciliation
- anchor validation for:
  - `Employment Situation`
  - `ADP National Employment Report`
- degraded sync semantics on CLI and API
- sync audit persistence via `release_calendar_sync_runs`
- single-flight locking around release calendar sync
- focused tests for pagination, safe reconciliation, degraded auto-sync behavior, and degraded API behavior

Not completed in this session:

- canonical calendar layer design and implementation

## Recovery Status Update

As of April 3, 2026 in the configured Scrivener database used during this session:

- migration `004_release_calendar_sync_runs.sql` has been applied
- the broad `sync-releases --days 120` path now completes successfully after the fetcher fix below
- degraded sync audit rows were recorded in `release_calendar_sync_runs`
- `Employment Situation` now includes `2026-04-03`
- `release_dates` is no longer empty for `2026-04-03`
- future coverage now begins on `2026-04-03` and extends through `2026-08-01`

How recovery was achieved:

- the full 120-day paginated sync was attempted twice and both runs degraded with:
  - `request_failed:The read operation timed out`
- a one-off operational backfill then fetched `releases/dates` one day at a time across the
  120-day horizon and inserted missing rows directly
- this avoided the oversized multi-page FRED fetch that was timing out
- after that repair, the fetcher was updated to split all-release `releases/dates` fetches into
  smaller windows and the broad 120-day sync completed successfully
- the latest successful audit row shows:
  - `status=complete`
  - `ready=true`
  - `dates_inserted=0`
  - `dates_removed=0`

Important implication:

- the immediate calendar corruption has been repaired for the near-term horizon
- the normal broad sync path is now operational again for the 120-day horizon tested in this session
- the one-off daily backfill remains part of the recovery history, but it should not be needed for
  routine operation if the new windowed fetch behavior remains stable

## Key Behavior Changes

### FRED Sync Safety

- `sync_release_dates()` no longer deletes future `release_dates` unless the fetched snapshot is
  both complete and plausible.
- A partial or degraded FRED pagination run is now insert-only.
- Cleanup is also blocked when:
  - anchor validation fails
  - fetched release dates reference release IDs not present in the local release catalog

### Read Path Behavior

- `ReleaseQuery._auto_sync_release_calendar()` now treats degraded syncs as non-authoritative.
- This prevents query-triggered auto-sync from masking a degraded calendar state as success.

### Operational Semantics

- `scrivener sync-releases` now exits non-zero when the sync result is degraded.
- `POST /releases/sync` now returns HTTP `503` for degraded syncs and includes the sync payload in
  the error detail.
- Every release calendar sync attempt now records an audit row in
  `release_calendar_sync_runs`.
- Concurrent sync attempts are rejected by a single-flight lock instead of running overlapping
  reconciliations.

## Files Changed

Primary implementation files:

- `services/scrivener/src/fetchers/fred.py`
- `services/scrivener/src/query/releases.py`
- `services/scrivener/src/cli.py`
- `services/scrivener/src/api/main.py`
- `services/scrivener/src/db/models.py`
- `services/scrivener/src/db/__init__.py`

Migration:

- `services/scrivener/migrations/004_release_calendar_sync_runs.sql`

Tests:

- `services/scrivener/tests/test_fred_release_sync.py`
- `services/scrivener/tests/test_release_query_auto_sync.py`
- `services/scrivener/tests/test_release_sync_api.py`

Docs:

- `services/scrivener/README.md`
- `services/scrivener/API.md`
- `docs/scrivener_release_calendar_fix_implementation_plan.md`
- `docs/scrivener_release_calendar_fix_handoff.md`

## Current Sync Contract

`FredFetcher.sync_release_calendar(days_ahead=...)` now returns a structured result with:

- top-level:
  - `status`
  - `ready`
  - `degraded_reason`
  - `releases`
  - `dates`
- releases section:
  - `fetched`
  - `expected`
  - `inserted`
  - `updated`
  - `complete`
  - `status`
  - `degraded_reason`
- dates section:
  - `fetched`
  - `expected`
  - `inserted`
  - `skipped`
  - `skipped_missing_release`
  - `removed`
  - `complete`
  - `status`
  - `degraded_reason`
  - `destructive_cleanup_performed`
  - `integrity_ok`
  - `anchor_validation`

Operational meaning:

- `ready=true` means the sync is authoritative enough to rely on for scheduling and query repair.
- `status=degraded` means the run may have inserted or refreshed data, but it must not be treated as
  a clean reconciliation.

## Required Rollout Steps

1. Apply the new migration:

```bash
services/scrivener/migrations/004_release_calendar_sync_runs.sql
```

2. Ensure the deployed Scrivener image or environment includes the updated code paths.

3. Confirm the new table exists:

```sql
select *
from information_schema.tables
where table_name = 'release_calendar_sync_runs';
```

4. Run a manual sync from the deployed environment and confirm an audit row is written.

## Immediate Next Steps

### 1. Run Recovery Sync

Do not use the default horizon blindly. Use a wide enough window to cover the known affected dates.

Suggested command:

```bash
cd services/scrivener
scrivener sync-releases --days 120
```

Expected outcomes:

- CLI exits `0`
- sync status is `complete`
- anchor validation passes
- destructive cleanup is performed only if the snapshot is complete

Current note:

- The broad all-release sync was fixed by collecting `releases/dates` in smaller windows rather than
  one oversized horizon request.
- The current implementation still uses a single final reconciliation pass, but the fetch-side
  timeout that caused the earlier degraded runs is no longer reproducing in the verified 120-day run.

### 2. Verify Calendar Repair

Confirm all of the following after the recovery sync:

1. `Employment Situation` includes `2026-04-03`
2. `release_dates` on `2026-04-03` is populated
3. near-term anchor releases still look plausible through the recovery horizon
4. a row exists in `release_calendar_sync_runs` for the recovery run

Suggested verification queries:

```sql
select r.name, rd.release_date
from releases r
join release_dates rd on rd.release_id = r.id
where r.name = 'Employment Situation'
  and rd.release_date = date '2026-04-03';
```

```sql
select r.name, rd.release_date
from release_dates rd
join releases r on r.id = rd.release_id
where rd.release_date = date '2026-04-03'
order by r.name;
```

```sql
select started_at, completed_at, status, ready, degraded_reason, dates_removed, missing_anchors
from release_calendar_sync_runs
order by started_at desc
limit 10;
```

Observed result in this session:

- `Employment Situation` row for `2026-04-03` exists
- `release_dates` has `28` rows for `2026-04-03`
- `release_calendar_sync_runs` contains degraded audit rows for the failed broad sync attempts and a
  later complete audit row for the repaired broad sync
- the one-off daily backfill was not recorded in `release_calendar_sync_runs`

### 3. Rerun Analyst Flow

Observed result in this session:

```bash
cd /Users/ncdial/devwork/research_processing/research_analyst
set -a
source .env
export PYTHONPATH=/Users/ncdial/devwork/research_processing/research_analyst/src:/Users/ncdial/devwork/research_processing/research_pipeline_ops/src
/Users/ncdial/devwork/research_processing/research_parser/.venv/bin/python -m research_analysis_layer.main extract-forecasts --research-id 5194 --rebuild
/Users/ncdial/devwork/research_processing/research_parser/.venv/bin/python -m research_analysis_layer.main upload-forecasts --limit 50
```

Results:

- `11` forecast candidates were extracted for `research_id=5194`
- `7` candidates matched exactly and `4` remained `no_event_found`
- payroll-related rows no longer fail with `no_event_found`
- the repaired payroll family matched Scrivener release `3549` on `2026-04-03`
- upload finished with `uploaded_count=7`, `skipped_count=4`, `failed_count=0`

Uploaded indicators:

- `us_adp_employment_change`
- `us_average_hourly_earnings_mom`
- `us_average_weekly_hours`
- `us_labor_force_participation_rate`
- `us_nfp`
- `us_private_payrolls`
- `us_unemployment_rate`

Residual unmatched indicators to carry into canonical-calendar follow-on:

- `us_retail_sales_headline_mom`
- `us_retail_sales_ex_auto_mom`
- `us_retail_sales_control_group_mom`
- `us_ism_manufacturing`

Important integration note:

- analyst upload writes to the app-facing Supabase configured by `PARSED_DB_URL`
- analyst matching reads Scrivener calendar data from the Supabase configured by `CALENDAR_DB_URL`
- Scrivener Postgres `economic_event_forecasts` remains empty in this workspace because it is not the upload target for the analyst flow

### 4. Monitor Degraded Runs

If a sync returns degraded after rollout, inspect:

- `degraded_reason`
- `missing_anchors`
- whether `skipped_missing_release` is non-zero
- whether a lock failure occurred (`lock_acquired=false`)

Likely degraded causes now include:

- incomplete FRED pagination
- missing anchor coverage
- release catalog mismatch
- concurrent sync contention

## Recommended Follow-on Work

1. Move sync initiation fully off the read path.
   Keep auto-sync as a temporary self-heal only if operationally necessary.

2. Add alerting on degraded sync runs.
   A degraded row in `release_calendar_sync_runs` should page or at least notify the owner.

3. Expand integrity checks carefully.
   Good next anchors:
   - `Consumer Price Index`
   - `Advance Retail Sales`
   - `ISM Manufacturing Index`

4. Normalize sync result naming.
   The current payload still mixes:
   - snapshot completeness
   - reconciliation readiness
   - overall run status

5. Design the canonical analyst-facing calendar layer.
   This should be a Scrivener-owned table or model, not an extension of `economic_events`.

## Residual Risks

### Read-path mutation still exists

Auto-sync remains present on some query paths. It is safer now, but it still performs writes during
reads when the local calendar is empty or stale.

### Audit table requires rollout discipline

`Base.metadata.create_all()` will create the new table in fresh environments, but existing deployed
databases still need the explicit migration applied.

### Local lock is per-process

The implementation uses:

- a process-local mutex
- a PostgreSQL advisory lock when running on Postgres

This is correct for deployed Postgres environments, but SQLite test environments only exercise the
local lock.

## Verification Run

The focused tests run in this session were:

```bash
cd services/scrivener
uv run pytest tests/test_fred_release_sync.py tests/test_release_query_auto_sync.py tests/test_release_sync_api.py
```

Result:

- `16 passed`

## Definition of Done For The Next Operator

This workstream should only be considered closed once all of the following are true:

- migration `004_release_calendar_sync_runs.sql` is applied in the target environment
- a manual recovery sync completes with `status=complete`
- `Employment Situation` includes `2026-04-03`
- `release_dates` on `2026-04-03` is no longer empty
- the analyst rerun for `research_id=5194` confirms the calendar repair removed the missing-event failure mode
- any residual forecast mismatches are documented as canonicalization gaps rather than calendar corruption

Status in this session:

- all of the above are now satisfied except the final canonical-calendar follow-on work
