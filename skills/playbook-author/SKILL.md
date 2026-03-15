---
name: playbook-author
description: Create, extend, or revise Sophia Episto economic research playbooks, including question decomposition, indicator families, transforms, success criteria, and the boundary between runtime playbook logic in episto versus authoring guidance in skills.
---

# Playbook Author

Use this skill when the task is to add or revise an `episto` playbook, tighten a planning workflow,
or turn a recurring econ research pattern into a reusable playbook.

Do not use this skill to implement runtime orchestration, direct data acquisition code, or gateway
API changes unless the user explicitly asks for those too.

## Source Of Truth

Runtime playbook behavior belongs in `core/sophia_episto/src/sophia_episto/`.

Put canonical behavior in:

- `plan_models.py` for typed artifacts
- `playbooks/` for playbook implementations
- `planner.py` for planning flow
- `policy.py` and `capability.py` for runtime decision logic

Use the skill tree only for authoring guidance, checklists, and operating procedures.

## Workflow

1. Read the relevant `episto` specs first:
   - `core/sophia_episto/docs/episto_architecture_spec.md`
   - `core/sophia_episto/docs/econ_research_playbook_spec.md`
   - `core/sophia_episto/docs/optimizer_autoresearch_integration_spec.md`
2. Inspect the nearest existing playbook in `core/sophia_episto/src/sophia_episto/playbooks/`.
3. Define the playbook boundary:
   - what question family it covers
   - what it should explain
   - what it must not overreach on
4. Draft the runtime shape in `episto`:
   - subquestions
   - hypotheses
   - indicator families
   - indicator query specs
   - transforms
   - comparison windows
   - success criteria
5. Add or update companion authoring guidance only if it reduces future ambiguity.
6. Add or update focused tests for plan construction and policy behavior.

## Playbook Checklist

Every playbook should define:

- a narrow question family
- explicit subquestions
- indicator families rather than only one exact series
- query specs that support capability checks
- transforms and harmonization rules when frequencies differ
- success criteria for a good answer
- common failure modes or caveats

## Constraints

- Keep playbooks modular and composable.
- Prefer typed fields and deterministic logic over long prompt prose.
- Do not hide core behavior in `SKILL.md` when it should live in `episto`.
- Do not add source-specific ingestion logic to the playbook itself.
- Keep acquisition policy separate from playbook decomposition.

## Deliverables

For a new playbook, the expected repo changes are usually:

- one playbook module under `core/sophia_episto/src/sophia_episto/playbooks/`
- registry wiring if needed
- any required plan-model updates
- focused tests
- optional authoring guidance updates if the pattern should be reused
