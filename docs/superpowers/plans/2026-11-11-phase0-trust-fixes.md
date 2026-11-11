# Phase 0 Trust Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the research path's tests run in CI and fix the three trust defects (cross-case evidence, "verified" provenance, position-paired Granger) so that each one is proven by a test that fails before the fix.

**Architecture:** Four stacked branches, one pull request each, in this order: CI → case-scoped evidence → well-formed provenance → date-joined Granger. Each PR's base is the previous branch, so CI runs on every PR. Ledger changes use detect-and-migrate steps in `Ledger._init_db`, the pattern the `idempotency.request_digest` column already uses, so an existing ledger file upgrades in place.

**Tech Stack:** Python 3.11, Pydantic 2, SQLite (stdlib `sqlite3`), statsmodels VAR (Arithmos), pytest, ruff 0.15.10, GitHub Actions.

**Spec:** `docs/2026-11-11-mechanism-registry-handover.md` (section "Phase 0 in detail"). The full review is in the Claude doc linked there; it agrees with the handover as of 2026-11-11 (no comments, no decisions ticked).

## Global Constraints

- Sophia has no LLM, no agenda and no scheduler on the research path.
- One owner per record type. Episto owns hypotheses and assessments; Arithmos computes and stores nothing.
- Schema validity is not support. The engine alone decides status and permitted uses.
- Do not invent thresholds. No new statistical cut-offs beyond what the spec names.
- Small reviewable changes; never mix mass deletion with a change in inferential semantics.
- Leave `.github/workflows/codeql.yml` alone.
- Branch before editing; the repo is on `main`. Push and open PRs (the owner asked for one PR per item on 2026-11-11). Never merge.
- Report test results as they are, including what was not run.
- Paths under `research/` mean `core/sophia_episto/src/sophia_episto/research/`.

## Findings made while planning (not in the handover)

1. **A hidden test failure.** With Oikonomia and Arithmos installed beside Episto (what CI must do, finding 9), Episto runs 73 tests, not 66, and `test_durable_execution.py::test_concurrent_clients_one_fingerprint` fails about 1 run in 4. Root cause, reproduced deterministically with `FakeRunner`: `ResearchEngine.request_test` runs `_mutation_prelude`'s revision check before its fingerprint dedup. A second client that sends the same computation under a different idempotency key with the revision it read gets `Stale case revision`, although `Ledger.transact_queued_result` (fingerprint first, revision second) and the test both intend it to receive the existing run. Fixed in Task 1.
2. **Lint debt.** Each package's own ruff config fails today: Oikonomia 28 findings, Arithmos 32. Episto (`research/` + `tests/test_research`, ruff defaults, no config) has 1. The client has 0. Task 1 clears them. `UP042` (`(str, Enum)` → `StrEnum`) is ignored, not fixed: `StrEnum` changes `format()` output, which reaches serialized values.
3. **The Oikonomia Granger fixture is finding 6 in miniature.** `services/sophia_oikonomia/tests/test_hypothesis_test_runs.py::_trigger` gives all 40 observations the date `2020-01-01`. It passes only because pairing is positional. Task 4 must give it distinct dates.
4. **`InProcessArithmosRunner` is dead code.** No caller in src, tests or the client; `default_runner` returns `OikonomiaMethodRunner`. Task 4 deletes it (finding 10).

## Review Focus

1. **An existing ledger file opened by new code.** It must keep every case, contribution and result, and the migration must be a no-op when run again. Pinned by `test_legacy_contributions_table_is_migrated` (Task 2) and `test_stored_verified_status_is_rewritten` (Task 3).
2. **The same claim submitted twice to the same case.** It must still return `duplicate` and not create a second row. Pinned by `test_same_claim_same_case_is_still_duplicate` (Task 2).
3. **A citation of another case's contribution ID.** Now that IDs are case-scoped, this must be refused rather than bound, as `cited_records_not_found`. Pinned by `test_citing_other_case_contribution_is_not_found` (Task 2).
4. **Series with gaps or misaligned calendars.** For example, monthly source on the 1st and monthly target at month end must join to zero rows and fail loudly, not run on misaligned pairs. Pinned by `test_disjoint_dates_fail_with_join_count` (Task 4).
5. **A replayed `submit_evidence` response stored before the rename.** It must not return `verified` after migration. Pinned by `test_stored_verified_status_is_rewritten` (Task 3).

---

### Task 1: CI workflow, lint baseline, and the fingerprint-before-revision fix (PR 1)

Branch `phase0/ci` from `main`. The first commit also adds the two untracked docs: the handover and this plan.

**Files:**
- Create: `.github/workflows/research-tests.yml`
- Modify: `services/sophia_oikonomia/pyproject.toml`, `services/sophia_arithmos/pyproject.toml` (`[tool.ruff.lint] ignore = ["UP042"]` with a comment giving the reason)
- Modify: the files ruff flags in Oikonomia, Arithmos and `core/sophia_episto/tests/test_research` (mechanical fixes only)
- Modify: `research/engine.py` (`request_test`, `_mutation_prelude`)
- Test: `core/sophia_episto/tests/test_research/test_durable_execution.py`

**Interfaces:**
- Produces: workflow jobs `lint`, `episto`, `oikonomia`, `arithmos`, `client`. Later PRs rely on these names in their CI checks.
- Produces: `_mutation_prelude(self, payload, *, operation: str, check_revision: bool = True)`. `request_test` passes `check_revision=False` and calls `self.ledger.require_revision(case, int(payload["expected_revision"]))` itself, only after `get_result_by_fingerprint` returns `None`. A missing `expected_revision` is still an `INVALID_REQUEST` in both paths.

- [ ] **Step 1: Write the failing test** `test_second_client_same_fingerprint_gets_existing_run(engine)` in `test_durable_execution.py`. Open a case and propose a hypothesis. Call `request_test` with key `"c1"`, then again with key `"c2"`, both using `proposed["revision"]`. Assert both `run_id`s are equal, `second["replayed"] is True`, and `len(engine.runner.calls) == 1`.
- [ ] **Step 2: Run it.** `cd core/sophia_episto && .venv/bin/python -m pytest -q tests/test_research/test_durable_execution.py -k second_client`. Expected: FAIL with `ProtocolError: Stale case revision`.
- [ ] **Step 3: Implement** the `check_revision` change above. A *different* computation sent with a stale revision must still raise `Stale case revision`, because only the dedup path may skip the check. Add `test_stale_revision_new_fingerprint_still_rejected` alongside the fix to pin this.
- [ ] **Step 4: Run the Episto suite in the combined environment, 10 times.** Use `uv venv -p 3.11 <scratch>/ci` and `uv pip install -e core/sophia_episto[dev] -e services/sophia_oikonomia[dev] -e services/sophia_arithmos[dev] -e clients/outside_research_agent[dev]`, then run `pytest -q` in a loop of 10. Expected: 75 passed every time.
- [ ] **Step 5: Clear lint.** Apply `ruff check --fix` (safe fixes only) per package, wrap the E501 lines by hand, move the Arithmos `main.py` E402 import, and add the `UP042` ignore. Expected: `ruff check .` exits 0 in Oikonomia, Arithmos and the client. In Episto, `ruff check src/sophia_episto/research tests/test_research` exits 0. All four pytest suites are unchanged in count and still pass.
- [ ] **Step 6: Write the workflow.**
  - Triggers: `push` to `main`, and `pull_request` with no branch filter, so stacked PRs get CI.
  - `permissions: contents: read`.
  - Every job uses `actions/checkout@v6`, `actions/setup-python@v6` with `python-version: "3.11"`, and `cache: pip`.
  - `lint`: `pip install ruff==0.15.10`, then the four ruff commands from Step 5.
  - `episto`: install Episto, Oikonomia and Arithmos `[dev]` editable, then run `pytest -q` in `core/sophia_episto`.
  - `oikonomia`: install Oikonomia and Arithmos `[dev]`, then run pytest.
  - `arithmos`: install Arithmos `[dev]`, then run pytest.
  - `client`: install all four, then run pytest in `clients/outside_research_agent`.
- [ ] **Step 7: Commit in three commits:** `fix(episto): dedup identical test requests before revision check`, `style: clear ruff findings on the research path`, `ci: run research-path tests and ruff`. Then push and open the PR against `main`.
- [ ] **Step 8: Confirm CI is green on the PR** with `gh pr checks`. Report each job's result. If a job fails only in CI, debug it there; don't skip or mark it xfail.

### Task 2: Case-scoped contributions (P0.1, finding 5) (PR 2)

Branch `phase0/case-scoped-evidence` from `phase0/ci`; the PR's base is `phase0/ci`.

**Files:**
- Modify: `research/ledger.py` (`_init_db` table definition and migration, `get_contribution`, `transact_evidence` duplicate check)
- Modify: `research/engine.py` (`submit_evidence` at line 186, `propose_assessment` at line 531)
- Create: `core/sophia_episto/tests/test_research/test_case_scoped_evidence.py`

**Interfaces:**
- Produces: `Ledger.get_contribution(self, case_id: str, contribution_id: str) -> EvidenceAssessment | None`.
- Produces: the `contributions` table with `PRIMARY KEY (case_id, contribution_id)`. `_contribution_id(claim)` is unchanged; it is content-derived, so the same claim has the same ID in every case. That is the cross-case identity the handover says to keep.

- [ ] **Step 1: Write the failing tests:**
  - `test_same_claim_in_two_cases_binds_in_both` is the handover's reproduction as a test. For case `b`: `ev["provenance"][0]["status"] != "duplicate"`, `len(explain_case(b)["source_claims"]) == 1`, and `"cited_records_not_bound" not in assessment["unmet_requirements"]`. Both cases' `contribution_ids` are equal.
  - `test_same_claim_same_case_is_still_duplicate`: the second submit, under a new idempotency key, returns `status == "duplicate"`, and `list_contributions` has length 1.
  - `test_citing_other_case_contribution_is_not_found`: case `a` cites an ID that exists only in case `b`, and `"cited_records_not_found" in unmet_requirements`.
  - `test_legacy_contributions_table_is_migrated`: create a SQLite file with the *old* `contributions` DDL (copied verbatim from `1f58c6b`) and one row. Open it with `Ledger`. Assert the row is readable through `get_contribution(case_id, id)`, that `PRAGMA table_info(contributions)` reports `pk` on both `case_id` and `contribution_id`, and that opening it a second time succeeds and leaves one row.
- [ ] **Step 2: Run them.** Expected: the first and fourth tests FAIL. The second and third may already pass; record which.
- [ ] **Step 3: Implement.**
  - Change the DDL to the composite key.
  - In `_init_db`, if `PRAGMA table_info(contributions)` shows `pk` only on `contribution_id`, rebuild inside the same connection: `CREATE TABLE contributions_new` → `INSERT ... SELECT` → `DROP` → `ALTER TABLE ... RENAME`.
  - Scope every `contributions` lookup by `case_id`.
- [ ] **Step 4: Run** `pytest -q` in the combined environment. Expected: all tests pass, 79 total.
- [ ] **Step 5: Commit** `fix(episto): scope evidence contributions to their case`. Push, open the PR against `phase0/ci`, and confirm CI is green.

### Task 3: `well_formed`, not `verified` (P0.2, finding 3) (PR 3)

Branch `phase0/well-formed-provenance` from `phase0/case-scoped-evidence`.

**Files:**
- Modify: `research/contracts.py` (`ProvenanceStatus`, `SourceClaimRef.provenance_status`)
- Modify: `research/policy.py` (lines 97–155)
- Modify: `research/ledger.py` (`_init_db` data migration)
- Modify: `core/sophia_episto/tests/test_research/test_contracts.py`
- Create: `core/sophia_episto/tests/test_research/test_provenance_honesty.py`

**Interfaces:**
- Produces: `ProvenanceStatus` = `{WELL_FORMED = "well_formed", UNVERIFIED = "unverified", INVALID = "invalid"}`. `VERIFIED` is removed; real verification (decision 2) will add it back with a check that earns it.
- Policy: no `ProvenanceStatus` grants any `AllowedUse`. `explain` comes only from a bound, succeeded predictive or identified result. The limitation `unverified_or_invalid_source_provenance` and the unmet requirement `verified_source_or_result_required` keep their exact strings.

- [ ] **Step 1: Write the failing tests:**
  - `test_identity_and_excerpt_is_only_well_formed`: the handover's claim gives `ProvenanceStatus.WELL_FORMED`. This replaces `test_verified_claim_needs_identity_and_locus`.
  - `test_well_formed_claim_alone_grants_nothing`: the handover's reproduction gives `status == "unmet_requirements"`, `allowed_uses == []`, and `"verified_source_or_result_required" in unmet_requirements`.
  - `test_stored_verified_status_is_rewritten`: write a ledger with a contribution payload and a `submit_evidence` idempotency response, both holding `"verified"`. Reopen it. `get_contribution(...).provenance_status == WELL_FORMED`. The replayed `submit_evidence` returns `provenance[0]["status"] == "well_formed"`. A second open is a no-op.
- [ ] **Step 2: Run them.** Expected: all three FAIL. The third fails with a Pydantic validation error once the enum changes, which is the reason the migration exists.
- [ ] **Step 3: Implement** the enum, policy and migration. The migration parses JSON and rewrites only `provenance_status` fields and `provenance[].status` entries equal to `"verified"`; it does no string replacement on whole payloads. Stored *assessments* are not re-scored; the PR description says so and names it as a follow-up for the owner.
- [ ] **Step 4: Run** `pytest -q` in Episto and the client. Fix any test that asserted `verified` or relied on a claim granting `explain`, and list each one in the PR description.
- [ ] **Step 5: Commit** `fix(episto): call shape-checked provenance well_formed; grant no use on it`. Push, open the PR against `phase0/case-scoped-evidence`, and confirm CI is green.

### Task 4: Date-joined Granger (P0.3, findings 6 and 10) (PR 4)

Branch `phase0/date-joined-granger` from `phase0/well-formed-provenance`.

**Files:**
- Create: `services/sophia_arithmos/src/sophia_arithmos/computations/alignment.py`
- Modify: `services/sophia_arithmos/src/sophia_arithmos/computations/causality.py`
- Modify: `services/sophia_oikonomia/src/sophia_oikonomia/adapters/hypothesis_test.py` (`_run_granger`, `GRANGER_VERSION`)
- Modify: `research/runners.py` (delete `InProcessArithmosRunner` and its `_arithmos_importable`; bump `GRANGER_VERSION`)
- Modify: `services/sophia_arithmos/tests/test_computations/test_causality.py`, `services/sophia_oikonomia/tests/test_hypothesis_test_runs.py` (`_trigger` dates)
- Create: `services/sophia_arithmos/tests/test_computations/test_alignment.py`

**Interfaces:**
- Produces: `infer_frequency(dates: list[date]) -> str`. It returns one of `"daily" | "weekly" | "monthly" | "quarterly" | "annual"` from the median gap in days: ≤4, 5–9, 25–35, 85–95, 360–370. It raises `ValueError` otherwise, or with fewer than 2 dates. These are calendar definitions, not statistical thresholds.
- Produces: `inner_join_on_date(source: list[Observation], target: list[Observation]) -> JoinedSeries`, where `JoinedSeries` is a frozen dataclass with `dates: list[date]`, `source: list[float]`, `target: list[float]` and `frequency: str`. It raises `ValueError` on duplicate dates in either series, or when the two inferred frequencies differ, naming both.
- `GrangerCausality` parameter `source_values` is **removed** and replaced by `source_observations`: a JSON list of `{"date": "YYYY-MM-DD", "value": number}`. The target stays as `data`. The required count `max_lag + 10` applies to the *joined* length. The summary adds `n_source`, `n_target`, `n_joined`, `joined_start`, `joined_end` and `frequency`; `n_observations` becomes `n_joined`.
- `GRANGER_VERSION = "arithmos-granger-2"` in both Episto and Oikonomia.

- [ ] **Step 1: Write the failing tests:**
  - `test_alignment.py`: `test_infer_frequency_daily_with_weekends`, `test_infer_frequency_monthly`, `test_duplicate_dates_rejected`, `test_mixed_frequencies_rejected` (message contains `"daily"` and `"monthly"`), and `test_join_keeps_only_shared_dates` (source shifted by 5 days gives `n_joined == len - 5` and `joined_start` equal to the later start).
  - `test_causality.py`: `test_shuffled_source_order_gives_same_result` (sorting does not depend on input order; this fails today because pairing is positional), `test_disjoint_dates_fail_with_join_count` (month-start vs month-end raises `ValueError` mentioning `n_joined=0`), and `test_summary_reports_joined_window`. Rewrite the existing `source_values` tests to use `source_observations`.
- [ ] **Step 2: Run them.** Expected: they FAIL with an import error (`alignment`) or a wrong result (shuffled order).
- [ ] **Step 3: Implement** `alignment.py`, then switch `GrangerCausality.compute` to it.
- [ ] **Step 4: Switch** Oikonomia's `_run_granger` to send `source_observations` as dated pairs, and fix `_trigger` to use 40 consecutive daily dates. Delete `InProcessArithmosRunner` and Episto's `_arithmos_importable` from `runners.py`; `oikonomia_runner.py` keeps its own copy. Bump both `GRANGER_VERSION`s.
- [ ] **Step 5: Run** all four suites and ruff in the combined environment. Expected: green.
- [ ] **Step 6: Commit** `fix(arithmos): join Granger series on date; reject mixed frequency`. Push, open the PR against `phase0/well-formed-provenance`, and confirm CI is green.

### Exit check (after Task 4)

- [ ] The two reproduced defects fail in a test before the fix and pass after: case `b` binds (Task 2), and a single well-formed claim grants nothing (Task 3). Show each test's red run from the step log.
- [ ] CI is green on all four PRs. Report the per-job results and anything not run: Scrivener and the legacy packages are still out of CI, by design.
