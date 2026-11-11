# Handover: Sophia research engine review and mechanism-registry training plan

Date: 2026-11-11
Reviewed commit: `1f58c6b` on `main` (working tree was clean)
Status: review and design complete; **no code has been changed**; development has not started
Audience: the next development session

## How to use this document

Read this file first. It is self-contained for Phase 0. The full review and the full training plan live in a Claude doc with two tabs:

- Review: https://claude.ai/artifact/L5EYamzALMkGRpG3hTAYgR
- Training plan tab: https://claude.ai/artifact/L5EYamzALMkGRpG3hTAYgR#0953f69b-69fd

Read the doc with the docs connector tools, not a web fetch. The owner may have edited it or left comments since this handover was written, so treat the doc as newer than this file where they differ.

The project's own statement of goals is `docs/superpowers/plans/2026-10-07-sophia-causal-engine-refactor-plan.md`. Everything below is measured against it. Read it before designing anything.

## What this repo is

Sophia is mid-pivot from a chat-assistant monorepo to a research and causal-reasoning engine driven by an outside agent.

- **Research path (keep, build on):** `core/sophia_episto` (contracts, SQLite case ledger, assessment policy, `sophia-research` CLI), `services/sophia_oikonomia` (run records, leases), `services/sophia_arithmos` (numerical methods), `services/scrivener` (FRED, BLS, Treasury, Fed data), `clients/outside_research_agent` (scripted reference client).
- **Legacy (do not extend):** `agents/sophia_prima`, `services/sophia_forge`, `services/sophia_pylon`, `services/sophia_canvas`, `services/sophia_tholos`, `services/sophia_kampe`, `frontend/sophia-dashboard`. These sit in the `legacy-assistant` Compose profile. About 37,000 of 58,000 non-test source lines.
- **Also legacy, inside Episto:** `causal/`, `world_model/`, `entities/`, `hypothesis/`, `planner.py`, `causal_service.py`. The live code is `core/sophia_episto/src/sophia_episto/research/`.

Three rules from the refactor plan that the code honours and new work must keep:

1. Sophia has no LLM, no agenda and no scheduler on the research path. The agent is outside.
2. One owner per record type: Analyst owns author claims, Scrivener owns observations, Episto owns hypotheses and assessments, Oikonomia owns runs.
3. Schema validity is not support. The engine alone decides status and permitted uses.

## Test baseline

Run on 2026-11-10 at `1f58c6b`. Each package has its own virtualenv.

```bash
cd core/sophia_episto && .venv/bin/python -m pytest -q        # 63 passed, 3 skipped
cd services/sophia_oikonomia && .venv/bin/python -m pytest -q  # 33 passed
cd services/sophia_arithmos && .venv/bin/python -m pytest -q   # 21 passed
```

Not run: `clients/outside_research_agent` tests. The package is not installed in the root `.venv`, so collection fails with `ModuleNotFoundError`. Install it (`pip install -e 'clients/outside_research_agent[dev]'` into an environment that also has Episto, Oikonomia and Arithmos) before relying on it. Scrivener and the legacy packages were not run either.

Environment notes:

- `python3.11` is not on `PATH`; `uv` and `python3` are. The per-package `.venv` directories work.
- Shared env file is `infra/.env`. Source it before running any service: `set -a && source infra/.env && set +a`.
- The only CI workflow is CodeQL. No job runs tests.

## Findings that drive the work

Rows marked **reproduced** were run against a scratch ledger. The rest come from reading the code.

| # | Finding | Where |
| --- | --- | --- |
| 1 | The research path never calls Scrivener. Observations arrive inline from the agent, so `vintage` and `as_of` are unverifiable strings. | `research/contracts.py` `InputSnapshot`; `research/engine.py:308` |
| 2 | Scrivener does not keep revisions in practice. `fetch_with_revisions` has no caller; the normal fetch upserts revision 0. Read queries have no revision filter. | `services/scrivener/src/fetchers/fred.py:156`; `fetchers/base.py:140`; `query/series.py:202` |
| 3 | **Reproduced.** Provenance is `verified` when a claim has any identity field and any excerpt. One such claim moves a hypothesis to `useful_bounded` with `explain`. | `research/contracts.py` `SourceClaimRef.provenance_status` |
| 4 | The policy never reads stance, independence group, falsifiers, or an evidence-to-hypothesis link. Stance is hard-coded to `non_diagnostic`. | `research/policy.py`; `research/engine.py:195` |
| 5 | **Reproduced.** Contribution IDs are unique across the ledger, not per case. A claim submitted to a second case returns `duplicate`, is not attached, and later fails with `cited_records_not_bound`. | `research/ledger.py:149`; `research/engine.py:186` |
| 6 | Granger pairs source and target by list position. Source dates are dropped; only equal length is checked. | `services/sophia_oikonomia/.../adapters/hypothesis_test.py` `_run_granger`; `services/sophia_arithmos/.../computations/causality.py:118` |
| 7 | `request_test` creates and executes the run in the same process before returning. Leases exist; no worker does. | `research/oikonomia_runner.py:155` |
| 8 | `explain_case` filters results by exact vintage string. `assessment_history` is written and never read (`list_assessment_history` has no caller). | `research/engine.py:593`; `research/ledger.py:392` |
| 9 | Episto declares only Pydantic, but its default runner needs Oikonomia and Arithmos importable. The README quick start installs neither. | `core/sophia_episto/pyproject.toml`; `research/runners.py:217` |
| 10 | The Granger wrapper exists twice. `policy_version` is set to `PROTOCOL_VERSION`. | `research/runners.py:66`; `adapters/hypothesis_test.py`; `research/policy.py` |
| 11 | `import_legacy_graph` mints a fresh ID per edge, so a second run duplicates every hypothesis. | `research/importer.py` |
| 12 | `data/causal_graph/graph.json` (gitignored) holds decayed priors, 0.56 and 0.42 where `expert_priors()` says 0.7 and 0.6. | `causal/edge.py` `expert_priors` |

Paths under `research/` are relative to `core/sophia_episto/src/sophia_episto/`.

### Reproduction for findings 3 and 5

Run from `core/sophia_episto` with a scratch directory for the database. Do not point it at a real ledger.

```python
from pathlib import Path
from sophia_episto.research.engine import ResearchEngine

e = ResearchEngine(Path("<scratch>/x.sqlite"))
claim = {"namespace": "t", "occurrence_id": "o1", "content_hash": "h", "excerpt": "anything at all"}
for k in "ab":
    c = e.open_case({"protocol_version": "1", "actor": "r", "question": "q" + k})
    ev = e.submit_evidence({"protocol_version": "1", "actor": "r", "case_id": c["case_id"],
        "expected_revision": 1, "idempotency_key": "e", "claims": [claim]})
    print(k, ev["provenance"], len(e.explain_case({"case_id": c["case_id"]})["source_claims"]))
    h = e.propose_hypothesis({"protocol_version": "1", "actor": "r", "case_id": c["case_id"],
        "expected_revision": ev["revision"], "idempotency_key": "h", "cause": "x", "effect": "y"})
    a = e.propose_assessment({"protocol_version": "1", "actor": "r", "case_id": c["case_id"],
        "expected_revision": h["revision"], "idempotency_key": "a",
        "hypothesis_id": h["hypothesis"]["hypothesis_id"],
        "cited_evidence_ids": ev["contribution_ids"], "requested_uses": ["explain"]})
    print("  ", a["assessment"]["status"], a["assessment"]["allowed_uses"], a["assessment"]["unmet_requirements"])
```

Observed output: case `a` gives `verified`, 1 claim, `useful_bounded ['explain']`. Case `b` gives `duplicate`, 0 claims, `unmet_requirements ['cited_records_not_bound']`.

## Target design in brief

The causal world model becomes a **mechanism registry**: case-independent, versioned mechanisms keyed on catalog variables, each with a registered test spec, re-estimated on every data release, and scored on dated predictions. The graph is a read-only view over the registry.

Ownership:

| Owner | Owns | Never does |
| --- | --- | --- |
| Episto | Variables, mechanisms, test specs, estimates, predictions, scores, standing rule | Fetch data, compute statistics, choose what to study |
| Oikonomia | Which runs a data event makes due, execution, leases | Judge whether a mechanism is supported |
| Arithmos | Surprise construction, event-study estimates, baselines, scoring | Store anything |
| Scrivener | Observations with every vintage, release dates, consensus forecasts, a change feed | Know about mechanisms |
| Agent: trainer | The clock. Calls the protocol in a fixed order. No LLM. | Change the registry's contents |
| Agent: curator | Proposing, revising, splitting, retiring mechanisms and specs. LLM-driven. | Set a status, skip pre-registration |

Design rules that must survive implementation:

- **The engine computes every number.** `record_prediction` and `resolve_prediction` take no forecast or score from the caller.
- **The trainer is stateless.** It asks `list_due` what to do each pass.
- **Score before re-estimating**, so each prediction is scored against the estimate that produced it.
- **Standing never carries across revisions.**
- **Specs are registered and timestamped before any run.**
- **Oikonomia model state is not mechanism standing.** Keep the two apart.
- **No automated path grants `intervene` or `counterfactual`.**
- **Tables are append-only** except `variables`. A re-estimate or a data revision adds a row.

Existing machinery to reuse, not rebuild: Oikonomia's `TriggerType.ECONOMIC_RELEASE`, `DataDependency`, `plan_runs`, `FileClock` (`core/clock.py`), `ScrivenerClient.build_series_snapshot` (used by `adapters/bistro.py`), and the lease and reconcile code. Scrivener already has `release_dates`, `economic_event_forecasts`, and FRED series `DGS2`, `SOFR`, `CPILFESL`.

New tables, protocol v2 operations, the Arithmos computations, the standing statuses and the agent package layout are specified in the training-plan tab. Do not re-derive them; read them there.

## Phases

| Phase | Work | Exit criterion |
| --- | --- | --- |
| 0. Trust fixes | Case-scoped evidence, honest provenance, date-joined series, tests in CI | The two reproduced defects fail in a test before the fix and pass after. CI green on a pull request. |
| 1. Point-in-time data | Scrivener vintages, `as_of`, change feed, first-print plus consensus endpoint; snapshot-by-reference in Oikonomia | The same request at two as-of dates returns two different hashed snapshots; each replays identically. |
| 2. Registry | New tables, variable catalog, registry operations, graph view; import the six priors from `expert_priors()` | One mechanism linked from two cases. |
| 3. Method and backtest | Arithmos computations, `EstimateAdapter`, walk-forward harness on `FileClock` | Reference mechanism backtested over full history; rerun gives the same scorecard; standing parameters chosen and recorded. |
| 4. Live trainer | Prediction ledger, standing rule, `list_due`, worker, `research-agent tick` | One full cycle with no human action. |
| 5. Curator | MCP server over `engine.dispatch`, triggers, tool loop, proposal budget | Curator revises a deliberately degraded mechanism; the gate runs; the revision enters at `candidate`. |
| 6. Breadth | More mechanisms, regimes, pooling, an identified method | Set after Phase 5. |

## Phase 0 in detail

This is the next work. Each item is small and independent. Write the failing test first.

**P0.1 Scope contributions to a case** (finding 5)

- Change the `contributions` key to `(case_id, contribution_id)` in `research/ledger.py`. Make `get_contribution` and the duplicate check in `submit_evidence` and `transact_evidence` case-scoped.
- The ledger creates tables with `CREATE TABLE IF NOT EXISTS`, and there is already one in-place column migration for `idempotency`. An existing ledger file needs a migration path for this key change; do not assume a fresh database.
- Keep the content hash available as a cross-case identity; independence accounting will need it later.
- Done when the reproduction's case `b` attaches the claim and the assessment no longer returns `cited_records_not_bound`.

**P0.2 Stop calling shape checks "verified"** (finding 3)

- Minimum for Phase 0: rename the current result to `well_formed` and make the policy stop granting `explain` on it alone.
- Real verification (store the source snapshot text by content hash, recompute the hash, confirm the excerpt occurs in it) depends on an open decision below. Do not build it until that is answered.
- This changes a contract enum. Existing tests assert `verified` in places; `test_honesty.py` and `test_acceptance.py` are the likely ones. Stored ledgers hold the old value in JSON payloads.

**P0.3 Join series on date** (finding 6)

- Send dated pairs for both series to Arithmos. Inner-join on date, reject mixed frequencies, record the joined window and observation count in the result.
- Two call sites build the Granger input: `research/runners.py` `InProcessArithmosRunner` and `adapters/hypothesis_test.py` `_run_granger`. Fix both or delete the first (finding 10).
- `GrangerCausality` takes `source_values` as a JSON string of bare numbers. Its parameter shape has to change.

**P0.4 Tests in CI**

- Add a GitHub Actions workflow with one job per research-path package plus `ruff`. Leave `codeql.yml` alone.
- Episto's default runner needs Oikonomia and Arithmos installed in the same environment (finding 9). The job has to install all three.

## Decisions waiting on the owner

Do not guess these. Ask, or build only what does not depend on them.

1. Is the Prima assistant or its Telegram channel still in use? Decides whether the legacy stack is deleted or moved to its own repository.
2. May Sophia keep a copy of the source text behind an Analyst claim? Decides how real provenance verification works (P0.2 follow-up).
3. Who assigns stance: the agent, or the engine from a result's sign?
4. Is the outside agent a Claude session with tools, or scripted jobs? Decides the priority of the MCP server.
5. Is Supabase still Scrivener's production database? Compose uses local Postgres; the runbook says Supabase. Storing every vintage multiplies rows.
6. What are the files in `data/`? They are Databento batch metadata for CME Globex with no reader found.
7. Is one user on one host the horizon for the next six months? If so, SQLite and in-process Oikonomia stay.
8. Which consensus source defines a release surprise? `economic_event_forecasts` holds parsed research with `review_status` defaulting to `pending`. Blocks Phase 3.
9. Is the 2-year Treasury yield an acceptable first proxy for the policy path? Blocks Phase 3.
10. Does curator output need human review before entering live? The plan assumes the backtest gate is enough for `candidate`.
11. Where does the trainer run?
12. Should the legacy code be deleted before Phase 2?

## Working agreements

- The owner declined to start Phase 0 twice during the review session ("Not yet"), then asked for this handover for development. Confirm scope before the first change.
- The repo is on `main`. Branch before editing. Commit or push only when asked.
- Small reviewable changes. The refactor plan says not to mix mass deletion with a change in inferential semantics; keep it that way.
- Preserve the distinctions the code already draws between a source statement, a computed result and an agent interpretation.
- Do not invent thresholds. Standing-rule parameters come from the Phase 3 backtest.
- Report test results as they are, including what was not run.

## What was not checked

- Legacy packages were sized and placed, not reviewed in depth.
- Scrivener was read for schema, fetch and query behaviour around revisions; its fetchers, scheduler and tests were not exercised.
- Finding 9's consequence (Granger reported unavailable after the README quick start) was inferred from the code, not run.
- No service was started. No deployment was inspected.
- Which yield and rate series Scrivener actually holds in its database was not checked, only the `CORE_SERIES` list in `fetchers/fred.py`.
