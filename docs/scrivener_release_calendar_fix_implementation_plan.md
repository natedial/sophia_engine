# Scrivener Release Calendar Fix Implementation Plan

## Goal

Repair Scrivener's FRED release calendar sync so that:

- `release_dates` is no longer vulnerable to partial-sync corruption
- release-based scheduling remains reliable
- analyst matching can depend on Scrivener as the system of record for macro release timing
- Scrivener can evolve toward a dedicated canonical analyst-facing calendar layer

This plan covers the implementation work inside `sophia_engine`. It is based on the April 3, 2026 handoff and critique documents in `research_processing/research_analyst/plans/`.

## Outcome Targets

Minimum outcome:

- `Employment Situation` includes `2026-04-03` after recovery sync
- `release_dates` is not destructively reconciled from an incomplete upstream snapshot
- sync logs clearly indicate whether the fetched FRED snapshot was complete
- automated tests cover both complete and incomplete sync behavior

Strategic outcome:

- Scrivener remains the source of truth for release timing
- downstream analyst matching eventually targets a dedicated canonical calendar layer owned by Scrivener rather than raw FRED release names

## Scope

### In scope now

- harden FRED `release_dates` sync
- make destructive cleanup completeness-aware
- add integrity checks for anchor releases
- backfill and verify the repaired calendar
- document the path toward a dedicated canonical calendar layer

### Explicitly not in scope for this first implementation cut

- full canonical macro-event schema build
- analyst-side matching redesign
- replacing scheduler normalization with a shared calendar model
- adding new upstream data providers beyond FRED for this patch

## File Targets

Primary code:

- `services/scrivener/src/fetchers/fred.py`
- `services/scrivener/src/query/releases.py`
- `services/scrivener/src/cli.py`

Likely test additions:

- `services/scrivener/tests/test_fred_release_sync.py`
- `services/scrivener/tests/test_release_query_auto_sync.py`

Likely doc updates after implementation:

- `services/scrivener/README.md`
- `services/scrivener/API.md`

## Phase 0: Containment

### Objective

Prevent any further accidental shrinking of future `release_dates` before or during the pagination fix.

### Tasks

1. Change `sync_release_dates()` so destructive cleanup runs only when the upstream snapshot is explicitly marked complete.
2. If completeness cannot be established, perform insert or skip behavior only and record that the run was degraded.
3. Review whether `ReleaseQuery._auto_sync_release_calendar()` should remain enabled during degraded sync behavior.
4. If read-path auto-sync can still trigger risky mutations, narrow or disable it temporarily.

### Implementation notes

- The current failure mode is not just "zero rows fetched".
- A partial page can produce a non-empty `desired_dates_by_release` set and still be unsafe to reconcile against.
- The completeness flag must be computed before deletion is considered.

### Acceptance check

- An incomplete fetch can no longer delete future rows.

## Phase 1: Pagination and Safe Reconciliation

### Objective

Fetch a complete FRED snapshot for release dates and reconcile only from a complete snapshot.

### Tasks

1. Add paginated fetching for `releases/dates` using FRED `limit` and `offset`.
2. Use FRED response-body metadata such as `count`, `limit`, and `offset` to determine completeness.
3. Return enough sync metadata from the fetch path to distinguish complete vs degraded runs.
4. Update `sync_release_dates()` to reconcile only when `complete=true`.
5. Log sync metrics including:
   - fetched rows
   - inserted rows
   - skipped rows
   - removed rows
   - complete or degraded status
6. Add pagination support for `fetch_releases()` as a secondary hygiene change.

### Design guidance

- Prioritize `fetch_release_dates()` first. It is the live blocker because it returns one row per dated event and is the endpoint most likely to exceed the default page size.
- Do not infer completeness from HTTP headers such as `Content-Range`. FRED pagination metadata is returned in the JSON body.
- Prefer a helper that centralizes paginated FRED collection logic so the behavior is testable.

### Suggested implementation shape

- Introduce a small internal helper in `fred.py` for paginated collection:
  - endpoint
  - params
  - item key
  - limit
- Return:
  - collected items
  - fetched count
  - expected count when available
  - completion flag
- Update sync result dictionaries so callers and logs can surface degraded behavior cleanly.

### Acceptance check

- A complete multi-page FRED response produces a complete local desired-state set.
- An incomplete paginated fetch leaves existing future rows intact.

## Phase 2: Integrity Checks

### Objective

Fail loudly when the future release calendar becomes implausibly sparse or loses critical anchor events.

### Tasks

1. Add post-sync validation for anchor releases.
2. Start with a small anchor set:
   - `Employment Situation`
   - `ADP National Employment Report`
3. Validate that anchor releases have expected upcoming dates inside the sync horizon.
4. Mark the sync as failed or degraded when anchor coverage disappears unexpectedly.
5. Surface this outcome in logs and CLI output.

### Design guidance

- Keep anchor validation simple and explicit.
- This is not a generalized anomaly-detection system.
- The purpose is to catch calendar corruption quickly.

### Acceptance check

- A missing near-term NFP release date is surfaced as an integrity failure rather than silently accepted.

## Phase 3: Recovery and Verification

### Objective

Repair the live calendar and verify end-to-end impact on analyst matching.

### Tasks

1. Run a manual Scrivener release sync with a `days_ahead` window large enough to cover all affected upcoming dates.
2. Verify `Employment Situation` includes `2026-04-03`.
3. Verify `release_dates` on `2026-04-03` is no longer empty.
4. Confirm anchor releases look plausible through the full recovery horizon.
5. Rerun the analyst flow for `research_id=5194`.
6. Record which forecast families still fail after calendar recovery.

### Design guidance

- Do not use the default `days_ahead` blindly for recovery.
- Recovery should cover the dates needed for both verification and near-term operational scheduling.

### Acceptance check

- Payroll-related rows that depend on `Employment Situation` no longer fail due to missing calendar coverage.

## Phase 4: Canonical Calendar Design Follow-on

### Objective

Define the dedicated analyst-facing calendar layer Scrivener should own after the immediate sync fix is stable.

### Direction

Scrivener should own canonical macro-event normalization, but that should not be implemented by extending `economic_events`.

`economic_events` stores extracted document events and associated provenance. It is not the correct source-of-truth table for scheduled release instances.

### Follow-on tasks

1. Define a dedicated canonical calendar table or model.
2. Map raw source releases into canonical event keys.
3. Make that model reusable across:
   - scheduler flows
   - API/query flows
   - analyst matching
4. Use the residual unmatched forecast families from Phase 3 to set the first normalization slice.

### Likely first canonical keys

- `us_nfp`
- `us_adp_employment_change`
- `us_retail_sales_headline_mom`
- `us_retail_sales_ex_auto_mom`
- `us_retail_sales_control_group_mom`
- `us_ism_manufacturing`

## Test Plan

### Unit and service tests to add

1. `fetch_release_dates()` paginates across multiple pages and returns all rows.
2. `fetch_release_dates()` marks the result incomplete when pagination cannot finish cleanly.
3. `sync_release_dates()` deletes stale rows only on a complete snapshot.
4. `sync_release_dates()` skips deletion on an incomplete snapshot.
5. Anchor validation fails when `Employment Situation` loses an expected upcoming date.
6. `fetch_releases()` pagination works, even if it is not the live blocker.

### Existing tests to review

- `services/scrivener/tests/test_release_query_auto_sync.py`

This file already covers retry behavior on empty read paths, but it does not currently cover fetch completeness or deletion safety.

## Verification Plan

### Code verification

Run focused Scrivener tests:

```bash
uv run pytest services/scrivener/tests/test_fred_release_sync.py services/scrivener/tests/test_release_query_auto_sync.py
```

If the new tests are folded into an existing file, update the command accordingly.

### Functional verification

Run a manual sync:

```bash
cd services/scrivener
scrivener sync-releases --days 120
```

Then verify:

1. `Employment Situation` includes `2026-04-03`
2. `release_dates` for `2026-04-03` is populated
3. sync output reports whether the snapshot was complete
4. no degraded or anchor-failure states are hidden

### Downstream verification

Rerun the analyst flow:

```bash
research_analysis_layer.main extract-forecasts --research-id 5194 --rebuild
research_analysis_layer.main upload-forecasts --limit 50
```

Then confirm:

1. payroll-related rows no longer fail with `no_event_found`
2. residual unmatched rows are categorized for canonical-calendar follow-on work

## Risks

### Risk: read-path sync still mutates data

Mitigation:

- keep Phase 0 explicit
- verify query-triggered sync behavior before relying on it in production

### Risk: pagination is implemented but completeness is still ambiguous

Mitigation:

- make the sync API explicitly return degraded state
- never delete unless completeness is proven

### Risk: recovery horizon is too short

Mitigation:

- use a wider manual recovery window than the default operational sync

### Risk: remaining analyst mismatches are misclassified as source gaps

Mitigation:

- use the Phase 3 rerun to separate calendar corruption from canonicalization gaps

## Execution Order

1. Implement Phase 0 containment in `fred.py`
2. Implement paginated `releases/dates` fetching
3. Add safe reconciliation and structured sync results
4. Add anchor validation
5. Add focused tests
6. Run targeted Scrivener tests
7. Run manual recovery sync
8. Verify analyst rerun outcomes
9. Write follow-on canonical calendar design note if residual gaps remain

## Definition of Done

- code changes land in Scrivener fetch and query paths
- tests cover complete and incomplete sync behavior
- recovery sync restores missing near-term anchor releases
- analyst rerun confirms the calendar repair improved matching
- the repo contains a concrete follow-on direction for Scrivener-owned canonical normalization
