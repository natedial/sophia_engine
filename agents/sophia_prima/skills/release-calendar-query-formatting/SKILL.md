---
name: release-calendar-query-formatting
description: Economic releases calendar and agenda: reports and announcements scheduled today, this week, upcoming, or on a specific date.
tool_allowlist: get_releases_today, get_releases_week, get_releases_upcoming, get_speeches
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
2. `Agenda`: one short sentence naming the key releases or stating that the slate is light.
3. `Calendar`:
   - Group by date.
   - Under each date, list releases in a compact table with columns:
     - `Release`
     - `Type` (`Key` or `Standard`)
4. `Data Notes`:
   - List tool names used.
   - List filters used (`days`, `key_only`).
   - If retried, note retry window.

## Brevity Rules

- For "today" or "this week" agenda questions, bias toward a concise answer.
- Keep the `Answer` and `Agenda` sections tight and desk-ready.
- If the user did not explicitly ask for the full schedule, show only the key releases by default when the slate is crowded.
- Expand into the full grouped calendar only when:
  - the user explicitly asks for all items
  - the returned slate is already small enough to stay readable
  - omitting rows would hide a material release

## Guardrails

- Never claim a date is empty without at least one tool call and exact-date filtering.
- Never infer holidays or schedule shifts without evidence in tool output.
- If data appears inconsistent, state uncertainty and show what the tools returned.
- Treat release names as calendar labels. Do not convert them into broader event claims unless the tool output explicitly supports that claim.
- Never call a date "Fed day" or imply an FOMC meeting, rate decision, or press conference just because several Fed-related rows appear together.
- If `FOMC Press Release` appears in tool output, report it with the exact date and label it as a release-calendar entry. If the user cares whether the Committee is actually meeting, state that the calendar row alone does not prove that and verify separately.
- Prefer exact phrasing such as `Fed-origin data/reference-rate releases` or the specific release names over narrative shorthand.
