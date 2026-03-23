# Forge Promotion Policy

## Purpose

This document defines how Sophia Forge should promote verified code changes after a delegated
coding run finishes.

The core principle is:

- Forge executes and verifies changes first.
- Promotion is a separate gated step.
- Draft PR is the default promotion path for non-trivial code.

Forge should not treat Git hosting as the coding primitive. It should treat promotion as the
delivery primitive applied after implementation succeeds.

## Policy Summary

Default policy:

- use isolated execution for coding
- verify before promotion
- prefer `draft_pr` for code, infra, tools, and deploy-related work
- keep merge and deploy as explicit later gates unless the caller opts into a higher-trust mode

Fast-path exceptions:

- use `patch` for local/offline workflows, air-gapped environments, or when host auth is not available
- use `direct_commit` only for low-risk changes such as docs, tiny tests, or explicitly approved fast paths
- use `none` when the run is exploratory and should stop after producing artifacts and a summary

## Promotion Modes

### `none`

Use when Forge should stop after implementation, verification, and artifact persistence.

Typical uses:

- exploration
- repo read-only sessions
- debugging why a change would be needed before proposing it

### `patch`

Forge emits an applyable patch artifact but does not interact with a git host.

Typical uses:

- local developer workflows
- no repository credentials available
- review is wanted, but PR automation is not yet configured

### `draft_pr`

Forge creates a branch and opens a draft pull request after verification passes.

This should be the default mode for:

- new tools
- runtime-visible capability additions
- infra changes
- schema changes
- deployment-affecting changes
- any change that touches more than one module or has non-trivial risk

Default expectations:

- draft PR, not ready-for-review PR
- verification must pass before PR creation
- no auto-merge
- no auto-deploy

### `direct_commit`

Forge commits directly to a configured branch without opening a PR.

This is a higher-trust mode and should be limited to:

- docs-only edits
- tiny scoped test fixes
- explicitly user-approved fast paths
- internal branches that are not protected default branches

Required safeguards:

- branch must be explicitly named
- default branch direct commit should be disabled by policy
- verification must still pass unless the caller overrides intentionally

### `deploy_after_merge`

Forge prepares a PR as above, but the intended operational flow includes deployment after merge.

This mode should not mean "deploy immediately from the coding run." It means:

- Forge creates the verified PR
- merge remains gated by review or automation policy
- deployment proceeds only after merge and only for the named environment

## Recommended Defaults By Change Type

Use `draft_pr` by default for:

- source code changes
- tool registration changes
- CI changes
- infra and deployment config
- DB or contract changes

Use `direct_commit` only for:

- docs-only
- comments-only
- trivial test-only changes

Use `patch` when:

- Forge has no git-host credentials
- the environment is local-only
- the user explicitly wants a patch artifact instead of host-side actions

## Required Gates

Promotion should be blocked when any of the following are true:

- run status is not `completed`
- required verification failed
- the backend reported changed files outside the allowed writable scope
- the promotion target is missing required fields for its mode
- the repository is in a state the selected mode does not permit

Examples:

- `draft_pr` without a valid base branch
- `direct_commit` targeting a protected default branch
- `deploy_after_merge` without a named deployment environment

## Proposed Request Contract

Forge callers should specify promotion intent through `RunRequest.promotion_policy`.

Recommended fields:

- `mode`
- `base_branch`
- `branch_name`
- `commit_message`
- `pr_title`
- `pr_body`
- `draft`
- `require_verification_pass`
- `require_review`
- `auto_deploy_after_merge`
- `deployment_environment`

Recommended default when omitted:

- `mode=inherit`, resolved by Forge to `draft_pr` for non-trivial code and `patch` when host-side
  promotion is unavailable

## Runtime Behavior

When promotion support is implemented, Forge should follow this order:

1. Prepare workspace.
2. Execute coding backend.
3. Run verification.
4. Persist run artifacts and events.
5. Evaluate promotion policy.
6. Create promotion artifact or host-side promotion action.
7. Persist promotion outcome as a Forge artifact and event stream entry.

Promotion should produce durable artifacts such as:

- patch file
- promotion summary JSON
- PR metadata JSON

## Current Status

Today Forge supports execution, verification, artifacts, events, and the first promotion slices.

Implemented now:

- `patch` promotion artifact generation
- `draft_pr` local branch creation and local commit creation
- durable PR request artifacts
- optional GitHub/GitLab publication through configurable git-host providers

Still not implemented:

- `direct_commit` automation
- `deploy_after_merge` automation
- merge orchestration
- provider-specific review policy enforcement

This policy defines the intended contract so those steps can be added without rethinking the
control model.
