# Presentation Policy and SOP Spec

**Date:** 2026-03-22  
**Status:** Proposal  
**Scope:** `agents/sophia_prima/config/`, `agents/sophia_prima/skills/`, `agents/sophia_prima/src/sophia/gateway/`, `agents/sophia_prima/src/sophia/agent.py`

## Why This Exists

Sophia currently has strong global prompt guidance and lazy-loaded task skills, but it does not yet have a first-class layer for channel-aware presentation policy.

That creates a real mismatch:

- the global personality currently recommends markdown tables as a default presentation format
- Telegram delivery currently only sends plain text chunks
- some presentation choices are not prompt problems at all; they are delivery problems

Example: if a response is naturally tabular and the user is on Telegram, "use a markdown table" is the wrong default. Telegram plain text does not preserve the intended structure well enough. In that case, Sophia should prefer one of:

1. a compact linearized text summary
2. a rendered image attachment
3. a document attachment

The right answer depends on channel, output shape, and delivery constraints.

## Design Goals

1. Keep always-on prompt context small.
2. Make channel-aware presentation behavior explicit and testable.
3. Reuse the existing `config/` versus `skills/` split instead of inventing a second prompt system.
4. Separate deterministic delivery mechanics from LLM-authored wording.
5. Let the agent author and update presentation SOPs without manually editing global prompts every time.
6. Support future channels without rewriting personality files.

## Non-Goals

- Do not move all formatting logic into prompt prose.
- Do not make the agent load every presentation guide on every turn.
- Do not treat channel delivery constraints as free-form "personality."
- Do not rely on the model alone for attachment decisions when the adapter can enforce them deterministically.

## Current Architecture Constraints

The existing system already gives us most of the right primitives:

- `config/personality.md` and `config/soul.md` are always-on identity and behavior files.
- `config/LESSONS.md` is a compact durable instruction layer.
- `skills/` is already lazy-loaded through metadata-first discovery.
- gateway adapters are channel-specific and own delivery details.
- `GatewayRunStore` already persists artifacts.

That means the correct solution is not "make `personality.md` larger." The correct solution is to add a presentation-policy layer that resolves small metadata first and loads detailed SOP instructions only when needed.

## Proposed Hierarchy

### 1. Global, Always-On Presentation Axioms

Add a small file:

- `agents/sophia_prima/config/presentation/core.md`

This file should stay short. It is not a style encyclopedia. It should contain only presentation invariants that are safe across all channels.

Examples:

- Preserve semantic fidelity when adapting format.
- Prefer the channel's strongest readable format.
- If structured data will degrade in plain text, prefer an artifact or attachment.
- Explain what was sent and why in one short sentence.

This file should be injected into the system prompt with the same status as other compact config layers.

### 2. Deterministic Channel Capability Registry

Add typed config files:

- `agents/sophia_prima/config/presentation/channels/telegram.json`
- `agents/sophia_prima/config/presentation/channels/web.json`
- `agents/sophia_prima/config/presentation/channels/cli.json`

These are runtime capability descriptors, not prompt files.

They should answer deterministic questions like:

- Does the channel support markdown tables well?
- Does the channel support image attachments?
- Does the channel support file attachments?
- What is the message length limit?
- Should long outputs be chunked, attached, or linked?

Example Telegram capability shape:

```json
{
  "channel": "telegram",
  "supports_markdown_tables": false,
  "supports_image_attachments": true,
  "supports_document_attachments": true,
  "max_text_chars": 4000,
  "preferred_structured_delivery": {
    "table": "image",
    "chart": "image",
    "long_report": "document"
  }
}
```

This should be consumed by the runtime directly. It should not be pasted into the prompt unless a tiny summary is needed for the current turn.

### 3. Lazy-Loaded Presentation SOPs

Add detailed SOPs under skills:

- `agents/sophia_prima/skills/presentation/telegram-tabular-delivery/SKILL.md`
- `agents/sophia_prima/skills/presentation/telegram-long-report-delivery/SKILL.md`
- `agents/sophia_prima/skills/presentation/web-rich-layout/SKILL.md`

These should use the existing lazy-loading path:

- metadata loaded at registry refresh time
- body loaded only for the matched SOP

Each SOP should contain:

- trigger conditions
- preferred render mode
- fallback modes
- wording expectations
- artifact instructions
- examples

This is the right home for detailed guidance because it is conditional, human-authored, and already fits the current `SkillRegistry` model.

### 4. Runtime Presentation Module

Add a small runtime package:

- `agents/sophia_prima/src/sophia/presentation/models.py`
- `agents/sophia_prima/src/sophia/presentation/registry.py`
- `agents/sophia_prima/src/sophia/presentation/resolver.py`
- `agents/sophia_prima/src/sophia/presentation/renderers.py`

Responsibilities:

- load channel capability configs
- discover presentation SOP metadata
- resolve the best presentation policy for this turn
- request artifact rendering when needed
- return a structured outbound delivery plan

### 5. Generated Delivery Artifacts

Store generated artifacts in agent-owned storage:

- `.sophia/presentation/`

Also register them in `GatewayRunStore` so runs can be audited and replayed.

Examples:

- rendered table PNG
- PDF brief
- CSV attachment

## Rule Precedence

Presentation guidance should obey this order:

1. adapter hard limits and channel capabilities
2. active presentation SOP
3. active task skill
4. compact global presentation axioms
5. broad personality style

This prevents a generic instruction like "use markdown tables" from overriding a channel that cannot render them correctly.

## How The Agent Knows Without Flooding Context

### Principle

The agent should not read every SOP body. It should resolve presentation in two stages: metadata first, instructions second.

### Stage 1: Metadata-Only Resolution

At startup or refresh time:

- load channel capability configs
- discover presentation SOP files
- parse only frontmatter and summary metadata

Suggested frontmatter fields:

```yaml
---
name: telegram-tabular-delivery
description: Handle tabular answers on Telegram.
channels: telegram
content_types: table, comparison, leaderboard
trigger_terms: table, compare, calendar, matrix, ranking
preferred_mode: image
fallback_mode: text_summary
max_prompt_chars: 1800
---
```

The existing skills loader already supports metadata-only reads. It should be extended with a few extra fields rather than replaced.

### Stage 2: Turn-Time Resolution

When a turn starts:

1. router identifies the channel
2. presentation resolver reads channel capabilities
3. resolver scores candidate SOPs by:
   - channel
   - user request shape
   - tool/result shape
   - predicted output size
4. if no special SOP matches, use compact global presentation axioms only
5. if one SOP matches, load only that body

### Stage 3: Minimal Prompt Injection

Only inject:

- a one-line channel summary when relevant
- the matched SOP body
- the chosen delivery mode if it matters to wording

Do not inject:

- the full channel capability JSON
- unrelated SOPs
- render-engine implementation details

### Deterministic Runtime Overrides

Some behavior should bypass the prompt entirely.

Examples:

- Telegram 4000-character chunking
- attachment transport details
- image versus document API method selection
- artifact path registration

These should be enforced in gateway code even if the model ignores guidance.

## Outbound Delivery Contract

The current outbound model is text-only. That is not sufficient for channel-aware presentation.

Extend `OutboundMessage` from:

```python
@dataclass(frozen=True)
class OutboundMessage:
    text: str
    session_id: str
    agent_id: str
    channel: str
    account_id: str
    peer_id: str
    run_id: str | None = None
```

to something closer to:

```python
@dataclass(frozen=True)
class DeliveryArtifact:
    artifact_id: str
    kind: str  # image, document, csv
    mime_type: str
    path: str
    caption: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    text: str
    session_id: str
    agent_id: str
    channel: str
    account_id: str
    peer_id: str
    run_id: str | None = None
    artifacts: tuple[DeliveryArtifact, ...] = ()
    delivery_mode: str = "text"
```

Then the Telegram adapter can do:

- `delivery_mode=text`: `reply_text`
- `delivery_mode=image`: `reply_photo` plus a short caption
- `delivery_mode=document`: `reply_document`

This is the key separation:

- the model decides what should be presented
- the runtime decides how it is physically delivered on that channel

## Example Resolution Flow: Telegram Table

User asks:

> Show this week's key releases in a table.

Resolution:

1. inbound message channel resolves to `telegram`
2. presentation resolver sees:
   - channel cannot render tables well
   - request is explicitly tabular
   - release-calendar task skill is also active
3. task skill governs tool call order and data shape
4. presentation SOP governs final delivery mode
5. agent produces:
   - short lead sentence
   - structured table payload
   - request for table render artifact
6. renderer creates PNG under `.sophia/presentation/`
7. `OutboundMessage` returns text plus image artifact
8. Telegram adapter sends the image and the short caption

The model should not need to know Telegram API method names. It only needs to know the selected presentation mode and the communication expectations.

## Procurement, Update, and Management Model

### Source Of Truth

Use three layers of source of truth:

1. `config/presentation/core.md`
   Purpose: compact global axioms
2. `config/presentation/channels/*.json`
   Purpose: deterministic channel capabilities
3. `skills/presentation/**/SKILL.md`
   Purpose: detailed operating procedures

No single file should contain all of this.

### How The Agent Procures New SOPs

Add a dedicated authoring skill:

- `agents/sophia_prima/skills/presentation-policy-author/SKILL.md`

Use it when the user asks to:

- add a new channel policy
- revise an existing presentation SOP
- codify an observed delivery pattern
- resolve a conflict between prompt style and channel mechanics

The skill should instruct the agent to:

1. inspect current config and skills
2. define whether the rule belongs in:
   - core axioms
   - channel capability config
   - a lazy-loaded SOP
   - adapter code
3. create or update the right files
4. add or update tests
5. record examples and failure cases

### How Updates Should Work

Updates should be pull-based and file-driven.

Recommended workflow:

1. User or agent identifies a presentation failure or repeated pattern.
2. Agent uses the authoring skill to propose the smallest correct change.
3. Validation runs:
   - frontmatter schema validation
   - no duplicate SOP triggers for the same channel and content type
   - prompt-size budget validation
   - adapter delivery tests
4. If valid, the skill registry and presentation registry hot-refresh.

### How The Agent Manages The Guide Over Time

Each SOP should carry lightweight governance metadata:

```yaml
owner: sophia_prima
version: 1
last_reviewed: 2026-03-22
channels: telegram
content_types: table
preferred_mode: image
fallback_mode: text_summary
```

Management responsibilities:

- prune duplicated SOPs
- split oversized SOPs into narrower ones
- deprecate policies whose channel assumptions are no longer true
- attach example inputs and outputs
- keep the global core file small

### Observability And Audit

Whenever a non-text delivery policy is selected, persist a structured record:

- selected SOP name
- channel
- requested content type
- chosen delivery mode
- fallback mode if used
- artifact ids created

This should go into `GatewayRunStore` alongside existing run artifacts so the team can answer:

- how often Telegram image delivery was selected
- which SOPs are actually used
- where fallbacks are happening
- whether a policy is stale or ineffective

## Required Runtime Changes

### Phase 0: Spec and File Layout

1. Add `docs/presentation_policy_sop_spec.md`.
2. Add `config/presentation/` directory.
3. Add `skills/presentation/` directory.

### Phase 1: Resolver and Metadata

1. Extend skill metadata parsing for presentation tags.
2. Add presentation registry and resolver.
3. Inject only compact resolved presentation context into the prompt.

### Phase 2: Structured Delivery

1. Extend `OutboundMessage` with artifacts and delivery mode.
2. Add renderer interfaces for image/document generation.
3. Teach Telegram adapter to send attachments.

### Phase 3: Authoring and Governance

1. Add `presentation-policy-author` skill.
2. Add validation tests.
3. Add run-store telemetry for presentation decisions.
4. Add a small eval set with channel-specific expectations.

## Testing Requirements

Add focused tests for:

- metadata-only SOP discovery
- resolver selection by channel and content type
- prompt injection budget behavior
- Telegram attachment delivery
- fallback to text when artifact generation fails
- precedence when task skill and presentation SOP both apply

## Opinionated Recommendation

The best fit for this repo is:

- keep identity in `config/`
- keep detailed SOPs in `skills/`
- keep channel capabilities in typed runtime config
- keep delivery mechanics in adapters

Do not put Telegram-specific formatting guidance directly into `personality.md`. That would make the always-on prompt larger, create cross-channel conflicts, and still fail to solve attachment delivery.

## Immediate Next Step

Implement the file hierarchy first, then the structured outbound contract. Until `OutboundMessage` can carry artifacts, any "Telegram tables as images" guidance will remain only partially real.
