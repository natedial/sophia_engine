# Forge Promotion Handoff

## Scope

This handoff covers the Forge and Sophia Prima changes completed in this session:

- explicit repo/codebase/build/deploy requests now delegate to the coding worker
- follow-up turns now retain a durable trace of delegated execution, including whether Forge was used
- Forge promotion policy is now modeled in the shared protocol
- Forge implements `patch` promotion end to end
- Forge implements the first `draft_pr` slice: local branch + commit + PR request artifact, with optional GitHub/GitLab publication

## Key Behavior Changes

### Sophia Prima

- Requests such as "write this into our codebase", "open a PR", "build a tool", and "deploy this"
  now route into the `coding_worker` path instead of remaining prompt-only generation.
- After delegated coding runs, the agent stores a compact execution trace in conversation metadata.
- Follow-up questions like "did you use our Forge tool?" can now be grounded on real prior
  execution instead of guessed from the model's own narrative.

### Sophia Forge

- `RunRequest` now accepts `promotion_policy`.
- `promotion_started` and `promotion_finished` are now part of the Forge event taxonomy.
- `promotion_status`, `patch`, and `pr_request` are now first-class artifact types.
- `patch` mode writes a durable patch artifact under the run's promotion directory.
- `draft_pr` mode now:
  - validates repo state
  - creates a local branch
  - commits the Forge-managed changed files
  - writes a PR request artifact
  - optionally publishes to GitHub or GitLab if configured

## Files Changed

Primary Sophia Prima files:

- `agents/sophia_prima/src/sophia/agent.py`
- `agents/sophia_prima/src/sophia/subagents.py`
- `agents/sophia_prima/src/sophia_forge_protocol/run_models.py`
- `agents/sophia_prima/src/sophia_forge_protocol/artifact_models.py`
- `agents/sophia_prima/src/sophia_forge_protocol/event_models.py`
- `agents/sophia_prima/tests/test_gateway_platform_expansion.py`
- `agents/sophia_prima/tests/test_subagent_orchestration.py`
- `agents/sophia_prima/tests/test_forge_protocol.py`

Primary Forge files:

- `services/sophia_forge/src/sophia_forge/config.py`
- `services/sophia_forge/src/sophia_forge/core/artifacts.py`
- `services/sophia_forge/src/sophia_forge/core/scheduler.py`
- `services/sophia_forge/src/sophia_forge/core/promotion.py`
- `services/sophia_forge/src/sophia_forge/core/git_host.py`
- `services/sophia_forge/tests/test_api.py`
- `services/sophia_forge/README.md`

Docs:

- `docs/forge_promotion_policy.md`
- `docs/forge_promotion_handoff.md`

## Current Promotion Semantics

### Implemented

- `patch`
- `draft_pr`

### Partially Implemented

- `draft_pr` remote publication:
  - local branch and local commit are implemented
  - PR/MR publication is implemented behind provider configuration
  - without provider config or tokens, Forge records a `prepared` status and writes the PR request artifact

### Not Yet Implemented

- `direct_commit`
- `deploy_after_merge`
- merge orchestration
- policy enforcement around approvals/review gates beyond the current contract fields

## Operational Notes

- `draft_pr` currently mutates the target git checkout by creating a local branch and commit.
- For production use, `draft_pr` should run against `git_worktree` workspaces by default rather than a
  shared mutable checkout.
- Remote PR publication depends on:
  - `git_host_provider`
  - reachable remote URL on the configured remote
  - `GITHUB_TOKEN` or `GITLAB_TOKEN` depending on provider

## Recommended Next Steps

1. Enforce `git_worktree` automatically for `draft_pr` promotion runs.
2. Add explicit promotion artifacts/events for branch push results separate from PR publication results.
3. Expose promotion artifacts and status cleanly through any Sophia Prima UI or gateway surfaces that need them.
4. Add provider integration tests with mocked GitHub/GitLab APIs.
5. Implement `direct_commit` only after policy rules for protected branches are explicit.
6. Keep deploy orchestration separate from coding execution and require explicit environment targeting.

## Verification Run

The relevant tests run in this session were:

```bash
env PYTHONPATH=/Users/ncdial/devwork/sophia_engine/agents/sophia_prima/src:/Users/ncdial/devwork/sophia_engine/services/sophia_pylon/src /Users/ncdial/devwork/sophia_engine/.venv/bin/pytest tests/test_gateway_platform_expansion.py tests/test_subagent_orchestration.py

env PYTHONPATH=/Users/ncdial/devwork/sophia_engine/agents/sophia_prima/src /Users/ncdial/devwork/sophia_engine/.venv/bin/pytest agents/sophia_prima/tests/test_forge_protocol.py

env PYTHONPATH=/Users/ncdial/devwork/sophia_engine/services/sophia_forge/src:/Users/ncdial/devwork/sophia_engine/agents/sophia_prima/src /Users/ncdial/devwork/sophia_engine/.venv/bin/pytest agents/sophia_prima/tests/test_forge_protocol.py services/sophia_forge/tests/test_api.py
```
