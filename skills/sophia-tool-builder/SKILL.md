---
name: sophia-tool-builder
description: Create or revise Sophia-facing tools that must become callable by Sophia Prima, including Pylon registration, capability metadata, usage examples, and post-build adoption verification after refresh_tools().
---

# Sophia Tool Builder

Use this skill when the task is to add, revise, or wire a tool that Sophia Prima should call.

This skill is for tools that must be surfaced through live tool schemas, not just helper code that
exists somewhere in the repo.

Do not use this skill for:

- pure backend refactors with no new callable tool
- internal helpers that are not exposed through Pylon
- prompt-only changes with no tool-schema impact

## Source Of Truth

The runtime path for Sophia-facing tools is:

1. service/client implementation in `services/`
2. tool definition and executor in `services/sophia_pylon/src/pylon/tools/`
3. registration in `services/sophia_pylon/src/pylon/core.py`
4. live schema exposure through `Pylon.get_tools()`
5. consumption in `agents/sophia_prima/src/sophia/agent.py`

Capability metadata and adoption reporting for coding runs live in:

- `agents/sophia_prima/src/sophia_forge_protocol/run_models.py`
- `agents/sophia_prima/src/sophia/forge_client.py`
- `agents/sophia_prima/src/sophia/agent.py`

Read [references/output-contract.md](references/output-contract.md) when creating a new tool or
changing how a tool should be used by Sophia Prima.

## Workflow

1. Identify the callable surface.
   - What exact tool name should Sophia Prima call?
   - Which service owns the capability?
   - What are the required parameters and output shape?

2. Implement the runtime path.
   - Add or update the service/client code if needed.
   - Add or update the tool definition/executor under `services/sophia_pylon/src/pylon/tools/`.
   - Register the tool in `services/sophia_pylon/src/pylon/core.py`.

3. Make the tool legible to Sophia Prima.
   - Write a clear tool description.
   - Keep parameter names stable and explicit.
   - Prefer a schema that makes misuse hard.

4. Emit capability metadata in the coding result.
   - Include `capabilities_added` when the coding run adds a callable tool.
   - Supply `when_to_use`, `input_schema`, and a concrete `usage_example` object that could be turned into a real tool call.

5. Verify adoption.
   - Refresh the live Pylon registry.
   - Confirm the claimed tool appears in Sophia Prima's tool schemas.
   - If the tool is implemented but not visible after refresh, mark the run blocked or pending adoption.

6. Add focused tests.
   - Tool executor behavior
   - Pylon registration/refresh
   - Any new capability metadata or adoption behavior if touched

## Rules

- A new tool is not complete until it is both implemented and visible after registry refresh.
- Do not claim a capability in `capabilities_added` unless the tool is intended to be callable by Sophia Prima.
- `input_schema` must match the live callable schema.
- `usage_example` must be a JSON object, short, concrete, and match the actual schema.
- Prefer adding one crisp tool over adding several vague tools at once.
- If the tool depends on a new backend service capability, note that dependency explicitly in the run summary.

## Deliverables

For a typical new tool, expect repo changes in:

- the owning service under `services/`
- `services/sophia_pylon/src/pylon/tools/`
- `services/sophia_pylon/src/pylon/core.py`
- targeted tests in `services/sophia_pylon/tests/` or service tests
- coding-run capability metadata if the task is being completed through the coding runtime

## Completion Check

Before calling the task complete, verify:

- the tool has a stable name
- the schema is clear enough for Sophia Prima to call directly
- `capabilities_added` is present when appropriate
- `when_to_use` is present
- `input_schema` matches the live tool schema
- `usage_example` matches the schema
- `Pylon.refresh_tools()` makes the tool visible
- tests cover the new callable surface
