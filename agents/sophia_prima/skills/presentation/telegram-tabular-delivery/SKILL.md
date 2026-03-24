---
name: telegram-tabular-delivery
description: Use attachment-first delivery for tabular answers on Telegram when plain text tables would degrade readability.
channels: telegram
content_types: table, comparison, calendar, leaderboard
trigger_terms: table, compare, calendar, matrix, ranking, schedule
preferred_mode: image
fallback_mode: document
---

# Telegram Tabular Delivery

Use this SOP when the current channel is Telegram and the answer is naturally tabular.

## Delivery Policy

1. Prefer an attachment instead of inline markdown tables.
2. If a raster image is unavailable, fall back to a document attachment that preserves table structure.
3. Keep the inline text short:
   - one sentence explaining why the attachment was used
   - one short summary or count if it adds value

## Guardrails

- Do not dump a wide markdown table into Telegram plain text.
- Preserve exact values and labels from the structured output.
- If attachment generation fails, fall back to a compact textual summary rather than a broken table.
