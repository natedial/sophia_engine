# Sophia Forge

`sophia_forge` is the in-monorepo coding runtime service for Sophia.

Phase 1 scope:

- accept coding run requests over a small HTTP API
- persist run status and runtime events in a forge-owned store
- execute runs through native forge backend adapters
- run forge-owned verification and persist structured verification results
- expose run status, events, artifacts, and verification results to clients such as `sophia_prima`

Current API surface:

- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/request`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/artifacts`
- `GET /v1/runs/{run_id}/verification`
- `GET /v1/metrics/summary`
- `GET /v1/capabilities`
- `POST /v1/capabilities`
- `GET /v1/retention/summary`
- `POST /v1/retention/cleanup`
- `POST /v1/evals/replay`
- `GET /v1/evals`
- `GET /v1/evals/{eval_run_id}`
- `POST /v1/evals/export/{run_id}`
- `GET /v1/evals/cases`
- `POST /v1/evals/cases/{case_id}/review`
- `POST /v1/runs/{run_id}/cancel`

`sophia_prima` can call this service through `ForgeClient` when `CODING_RUNTIME_MODE=forge_service`.

Local service run:

```bash
PYTHONPATH=services/sophia_forge/src:agents/sophia_prima/src python -m sophia_forge --host 127.0.0.1 --port 8090
```

Supported backends:

- `codex`
- `claude_code`

Execution guarantees today:

- runs are submitted through a stable request/result contract
- forge owns run persistence, events, artifacts, verification, and retention cleanup
- isolated execution supports shared workspace or git worktree plus shared or ephemeral process environments
- `sophia_prima` prefers forge service mode and can fall back to inline execution when the service is unavailable

Phase 2 additions:

- task-type-aware auto verification recipes
- aggregate forge runtime metrics for success rate, retry rate, verification pass rate, and common failure classes
- replayable eval corpus support under `services/sophia_forge/evals/corpus/`
- in-process eval replay via `ForgeRuntime.run_eval_corpus(...)`
- durable persisted eval summaries under `.sophia/forge/runs/evals/` plus queryable eval run records
- exporter support to turn completed forge runs into candidate eval-case JSON fixtures
- candidate/approved/rejected case curation with default replay filtered to approved cases only

Phase 3 additions:

- workspace strategy controls in the execution policy: shared workspace or git worktree
- cleanup policy controls for isolated workspaces
- forge-managed workspace preparation and teardown in `core/workspaces.py`
- runtime-managed process environments with shared or ephemeral strategy and explicit secret env allowlists
- verification now runs against the prepared isolated workspace instead of the caller's original mutable checkout
- retention inspection and cleanup for old workspaces, environments, run artifacts, and eval artifacts

Phase 4 additions:

- `sophia_prima` now prefers `forge_service` by default, with inline fallback when the service is unreachable
- durable forge capability handoffs are stored in a forge-owned registry and can be reloaded by clients after restart
- service API now exposes capability registry listing and upsert operations for adopted Sophia-facing tools
- temporary bridge execution path removed; forge now runs through native service backends only
- local ops path is explicit via `python -m sophia_forge`

Promotion support today:

- `promotion_policy.mode=patch` writes a durable patch artifact after verification
- `promotion_policy.mode=draft_pr` prepares a local branch and commit plus a PR request artifact
- optional GitHub/GitLab publication is supported through configurable git-host providers when remotes and tokens are available
- `direct_commit` and `deploy_after_merge` are still contract-only modes and currently return blocked promotion status
