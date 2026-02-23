---
name: release-calendar-query-formatting
description: Use Scrivener release tools with a deterministic call order and standardized output format for economic release schedule questions (today, this week, next N days, or exact date checks).
tool_allowlist: get_releases_today, get_releases_week, get_releases_upcoming
---

# Release Calendar Query + Formatting

Use this skill when the user asks for economic release schedules, date checks, or key-release calendars.

## Tool Call Policy

1. Always call tools first.
2. Pick calls by request type:
   - "today": `get_releases_today`
   - "this week": `get_releases_week`
   - "next N days": `get_releases_upcoming(days=N)`
   - specific date or day check: `get_releases_upcoming(days=14)` then exact-date filter
3. If user asks for major or key releases, set `key_only=true`.
4. If no rows are returned, retry once with a broader window (`days=30`) before concluding empty.

## Filtering Rules

- Normalize to explicit date strings (`YYYY-MM-DD`) before filtering.
- For day checks (for example "Wednesday"), compute the exact date first, then filter.
- Sort rows by `release_date`, then `name`.

## Output Contract

Always use this structure:

1. `Answer`: one sentence with exact scope and count.
2. `Calendar`:
   - Group by date.
   - Under each date, list releases in a compact table with columns:
     - `Release`
     - `Type` (`Key` or `Standard`)
3. `Data Notes`:
   - List tool names used.
   - List filters used (`days`, `key_only`).
   - If retried, note retry window.

## Guardrails

- Never claim a date is empty without at least one tool call and exact-date filtering.
- Never infer holidays or schedule shifts without evidence in tool output.
- If data appears inconsistent, state uncertainty and show what the tools returned.
