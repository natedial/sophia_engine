# Output Contract

Use this reference when a coding run adds or revises a Sophia-facing tool.

## Required Capability Metadata

If the run creates a callable tool, include it in `capabilities_added`.

Minimum shape:

```json
{
  "capability_type": "tool",
  "tool_name": "get_market_ohlcv",
  "service_name": "scrivener",
  "registration_path": "services/sophia_pylon/src/pylon/core.py",
  "description": "Get OHLCV market data for a symbol and date range.",
  "when_to_use": "Use when the user asks for historical OHLCV data for a symbol and date range.",
  "input_schema": {
    "type": "object",
    "properties": {
      "symbol": {"type": "string"},
      "start": {"type": "string"},
      "end": {"type": "string"}
    },
    "required": ["symbol", "start", "end"]
  },
  "usage_example": {
    "symbol": "ZN",
    "start": "2026-01-01",
    "end": "2026-01-31"
  }
}
```

## `when_to_use` Rules

- Must state the user intent or job that should trigger the tool.
- Keep it short and specific.
- Write it so Sophia Prima could reuse the sentence as operator guidance.

## `input_schema` Rules

- Must match the actual live tool schema that Pylon exposes.
- Include the object `properties` and `required` fields for the callable surface.
- Do not invent parameters that are not present in the real tool.

## `usage_example` Rules

- Must be short and concrete.
- Must match the actual parameter schema.
- Must be a JSON object, not prose or a quoted JSON string.
- Prefer one representative happy-path call.

Bad:

```text
call it with symbol and dates
```

Good:

```json
{"symbol":"ZN","start":"2026-01-01","end":"2026-01-31"}
```

## Registration Checklist

A Sophia-facing tool is only adopted when all of the following are true:

1. The executor defines the tool in `services/sophia_pylon/src/pylon/tools/`.
2. `services/sophia_pylon/src/pylon/core.py` registers it.
3. `Pylon.refresh_tools()` rebuilds the registry and the tool appears in `Pylon.get_tools()`.
4. Sophia Prima can see it through `_get_tool_schemas()`.

## Status Guidance

- `completed`: tool exists, refresh succeeds, and the claimed tool is visible in schemas.
- `blocked`: implementation exists but registration or adoption is incomplete.
- `failed`: the tool could not be implemented or wired correctly.

## Summary Guidance

When a tool is added, the run summary should say both:

- what capability was implemented
- whether the capability was adopted after refresh

Example:

```text
Added get_market_ohlcv in Pylon and verified it appears in Sophia Prima tool schemas after refresh.
```
