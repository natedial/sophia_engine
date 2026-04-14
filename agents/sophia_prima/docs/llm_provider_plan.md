# LLM Provider Abstraction Plan

## Objective
Allow users to select models with a single `llm_model` setting using canonical
`provider:model` specs, while preserving backward compatibility for existing
`llm_provider` + bare `llm_model` configs.

Primary goals:
- Make `provider:model` the canonical production format.
- Support DeepInfra without creating a new provider class.
- Keep legacy configs working.
- Resolve provider selection and wire-model normalization in one shared code path.

Non-goals for this phase:
- A dynamic provider plugin system.
- Expanding memory embeddings to use the same abstraction.
- Adding new non-OpenAI-compatible providers beyond the current set.

## Core Concept
`llm_model` becomes the user-facing model selector. It may be:

- Explicit canonical spec: `openai:gpt-4.1-mini`
- Explicit canonical spec: `deepinfra:MiniMaxAI/MiniMax-M2.5`
- Legacy bare model: `gpt-4.1-mini`
- Legacy bare model: `claude-3-5-sonnet-20241022`

Two values must be kept distinct:

- Config model spec: the exact string in `settings.llm_model`
- Wire model: the provider-native model name actually sent to the SDK/API

Example:

- Config model spec: `deepinfra:MiniMaxAI/MiniMax-M2.5`
- Resolved provider: `deepinfra`
- Wire model: `MiniMaxAI/MiniMax-M2.5`

The implementation must never send the `provider:` prefix upstream.

## Resolution Rules
Resolution order must be explicit and shared across runtime and CLI.

1. If `llm_model` is `provider:model`, use that provider exactly and strip the
   prefix before calling the provider SDK.
2. If `llm_model` is bare and appears in `MODEL_ALIASES`, use the aliased
   provider.
3. If `llm_model` is bare and not in `MODEL_ALIASES`, fall back to legacy
   `llm_provider`.
4. If the config is contradictory, fail with a helpful error instead of silently
   picking one side.

Contradictory examples that should raise:

- `llm_provider=groq`, `llm_model=gpt-4.1-mini`
- `llm_provider=anthropic`, `llm_model=deepinfra:MiniMaxAI/MiniMax-M2.5`

Compatibility rule:

- A default `llm_provider="openai"` must not override a known bare alias such
  as `claude-3-5-sonnet-20241022`.

This preserves the new abstraction without silently misrouting aliased models.

## Architecture

```
settings.llm_model (config spec)
settings.llm_provider (legacy fallback only)
        │
        ▼
┌─────────────────────────────┐
│ sophia/llm/registry.py      │
│ - provider aliases          │
│ - model aliases             │
│ - provider config           │
│ - parse_model_spec()        │
│ - resolve_llm_config()      │
└─────────────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ ResolvedLLMConfig           │
│ - provider                  │
│ - requested_model_spec      │
│ - wire_model                │
│ - api_key_field             │
│ - base_url_field            │
│ - api_key                   │
│ - base_url                  │
└─────────────────────────────┘
        │
        ├──────────────┐
        ▼              ▼
┌────────────────┐  ┌──────────────────────┐
│ gateway/runtime│  │ cli.py               │
│ - create SDK   │  │ - validate key       │
│ - cache config │  │ - create SDK         │
│ - normalize    │  │ - normalize settings │
│   agent config │  │   for SophiaAgent    │
└────────────────┘  └──────────────────────┘
        │
        ▼
┌─────────────────────────────┐
│ Provider instance           │
│ - AnthropicProvider         │
│ - GroqProvider              │
│ - OpenAIProvider            │
│   for OpenAI + DeepInfra    │
└─────────────────────────────┘
```

## Implementation Details

### 1. New: `src/sophia/llm/registry.py`

This module becomes the single source of truth for:

- Provider aliases
- Bare model aliases
- Provider config field mapping
- Parsing and resolution

#### Provider aliases

```python
PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "gpt": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "groq": "groq",
    "deepinfra": "deepinfra",
}
```

#### Bare model aliases

This is convenience-only and intentionally incomplete. Explicit
`provider:model` remains the canonical format.

```python
MODEL_ALIASES: dict[str, str] = {
    # OpenAI
    "gpt-4.1": "openai",
    "gpt-4.1-mini": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    # Anthropic
    "claude-3-5-sonnet-20241022": "anthropic",
    "claude-3-5-sonnet": "anthropic",
    "claude-3-opus-20240229": "anthropic",
    "claude-3-opus": "anthropic",
    "claude-3-haiku-20240307": "anthropic",
    "claude-3-haiku": "anthropic",
    # Groq
    "llama-3.1-70b-versatile": "groq",
    "llama-3.1-8b-instant": "groq",
    "llama-3.3-70b-versatile": "groq",
    "mixtral-8x7b-32768": "groq",
    # DeepInfra
    "MiniMaxAI/MiniMax-M2.5": "deepinfra",
    "meta-llama/Llama-3.3-70B-Instruct": "deepinfra",
    "Qwen/Qwen2.5-72B-Instruct": "deepinfra",
}
```

#### Provider config

```python
PROVIDER_CONFIG: dict[str, dict[str, str | None]] = {
    "openai": {
        "api_key": "openai_api_key",
        "base_url": "openai_base_url",
    },
    "anthropic": {
        "api_key": "anthropic_api_key",
        "base_url": None,
    },
    "groq": {
        "api_key": "groq_api_key",
        "base_url": "groq_base_url",
    },
    "deepinfra": {
        "api_key": "deepinfra_api_key",
        "base_url": "deepinfra_base_url",
    },
}

OPENAI_COMPATIBLE_PROVIDERS: frozenset[str] = frozenset({
    "openai",
    "deepinfra",
})
```

#### Data structures

```python
@dataclass(frozen=True)
class ParsedModelSpec:
    provider: str | None
    model: str
    explicit: bool


@dataclass(frozen=True)
class ResolvedLLMConfig:
    provider: str
    requested_model_spec: str
    wire_model: str
    api_key_field: str
    base_url_field: str | None
    api_key: str
    base_url: str | None
```

#### Parser

The parser only answers one question: was the spec explicit, and what is the
wire model portion?

```python
def parse_model_spec(model_spec: str) -> ParsedModelSpec:
    spec = model_spec.strip()
    if not spec:
        raise ValueError("llm_model cannot be empty")

    if ":" not in spec:
        return ParsedModelSpec(provider=None, model=spec, explicit=False)

    provider_raw, model_raw = spec.split(":", 1)
    provider = PROVIDER_ALIASES.get(provider_raw.strip().lower())
    model = model_raw.strip()

    if not provider:
        raise ValueError(
            f"Unknown provider '{provider_raw}'. "
            f"Supported providers: {sorted(PROVIDER_CONFIG)}"
        )
    if not model:
        raise ValueError("Model spec must include a model after 'provider:'")

    return ParsedModelSpec(provider=provider, model=model, explicit=True)
```

#### Resolver

This is the shared function runtime and CLI must both call.

```python
def resolve_llm_config(settings: Settings) -> ResolvedLLMConfig:
    parsed = parse_model_spec(settings.llm_model)
    legacy_provider = PROVIDER_ALIASES.get(settings.llm_provider.strip().lower())

    if parsed.explicit:
        if legacy_provider and legacy_provider != "openai" and legacy_provider != parsed.provider:
            raise ValueError(
                "Conflicting llm_provider and llm_model values. "
                "Use explicit provider:model and remove the old llm_provider override."
            )
        provider = parsed.provider
        wire_model = parsed.model
    else:
        alias_provider = MODEL_ALIASES.get(parsed.model)
        if alias_provider:
            if legacy_provider and legacy_provider not in {"openai", alias_provider}:
                raise ValueError(
                    f"Model '{parsed.model}' maps to provider '{alias_provider}', "
                    f"but llm_provider is '{legacy_provider}'. "
                    "Use explicit provider:model to disambiguate."
                )
            provider = alias_provider
        elif legacy_provider:
            provider = legacy_provider
        else:
            raise ValueError(
                f"Unknown model '{parsed.model}'. "
                "Use explicit provider:model format."
            )
        wire_model = parsed.model

    config = PROVIDER_CONFIG[provider]
    api_key_field = str(config["api_key"])
    base_url_field = str(config["base_url"]) if config["base_url"] else None
    api_key = getattr(settings, api_key_field)
    base_url = getattr(settings, base_url_field) if base_url_field else None

    if not api_key:
        raise ValueError(f"{api_key_field.upper()} is required for gateway operation")

    return ResolvedLLMConfig(
        provider=provider,
        requested_model_spec=settings.llm_model,
        wire_model=wire_model,
        api_key_field=api_key_field,
        base_url_field=base_url_field,
        api_key=api_key,
        base_url=base_url,
    )
```

Implementation note:

- `resolve_llm_config()` should live in `registry.py` even though it touches
  `Settings`; the goal is one authoritative resolution path, not a pure parser.

### 2. Modify: `src/sophia/config.py`

Add DeepInfra settings:

```python
deepinfra_api_key: str = Field(default="", description="DeepInfra API key")
deepinfra_base_url: str = Field(
    default="https://api.deepinfra.com/v1/openai",
    description="Base URL for DeepInfra OpenAI-compatible API",
)
```

Update `llm_model`:

```python
llm_model: str = Field(
    default="gpt-4.1-mini",
    description=(
        "Model selector. Canonical format: 'provider:model' "
        "(for example 'openai:gpt-4.1-mini' or "
        "'deepinfra:MiniMaxAI/MiniMax-M2.5'). "
        "Bare model names are supported for legacy configs and best-effort aliases."
    ),
)
```

Update `llm_provider` description:

```python
llm_provider: str = Field(
    default="openai",
    description=(
        "Legacy provider fallback for bare llm_model values. "
        "Deprecated in favor of explicit provider:model."
    ),
)
```

No environment alias remapping is needed for this change.

### 3. No new `DeepInfraProvider`

DeepInfra is OpenAI-compatible. It should reuse `OpenAIProvider` with a
different `base_url`.

That means:

- No `deepinfra_provider.py`
- No new protocol surface
- One new provider entry in `PROVIDER_CONFIG`

### 4. Modify: `src/sophia/gateway/runtime.py`

#### Cache the resolved config, not just the provider string

Add to `GatewayRuntime.__init__`:

```python
self._resolved_llm: ResolvedLLMConfig | None = None
```

Add a helper:

```python
def _resolve_llm(self) -> ResolvedLLMConfig:
    if self._resolved_llm is None:
        self._resolved_llm = resolve_llm_config(self.settings)
    return self._resolved_llm
```

This avoids re-implementing precedence logic in multiple methods and works even
in tests that use `GatewayRuntime` without calling `start()`.

#### Refactor `_create_provider()`

```python
def _create_provider(self) -> ModelProvider:
    resolved = self._resolve_llm()

    if resolved.provider == "anthropic":
        from sophia.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=resolved.api_key)

    if resolved.provider in OPENAI_COMPATIBLE_PROVIDERS:
        from sophia.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=resolved.api_key,
            base_url=resolved.base_url or self.settings.openai_base_url,
            timeout=self.settings.llm_request_timeout_sec,
        )

    if resolved.provider == "groq":
        from sophia.llm.groq_provider import GroqProvider
        return GroqProvider(
            api_key=resolved.api_key,
            base_url=resolved.base_url or self.settings.groq_base_url,
            timeout=self.settings.llm_request_timeout_sec,
        )

    raise ValueError(f"Unsupported provider '{resolved.provider}'")
```

#### Normalize settings before constructing `SophiaAgent`

This is the critical behavior missing from the previous plan.

The provider factories alone are not enough because `SophiaAgent` currently
passes `self.settings.llm_model` directly to the provider. To avoid touching
every provider call site in `agent.py`, construct each agent with a normalized
settings copy:

```python
resolved = self._resolve_llm()

agent_settings = self.settings.model_copy(
    update={
        "llm_provider": resolved.provider,
        "llm_model": resolved.wire_model,
        # existing profile overrides remain here too
    }
)
```

Use this normalized settings object for every `SophiaAgent` created in
`start()`.

Result:

- Runtime diagnostics still have access to the original configured model spec
  via `self.settings.llm_model`
- Provider calls receive only the wire model via the agent settings copy
- `agent.py` does not need invasive edits for this feature

#### Update diagnostics and inventory

All diagnostics that currently read `self.settings.llm_provider` should use:

```python
resolved = self._resolve_llm()
provider_name = resolved.provider
```

Affected areas include:

- provider-capacity diagnostics
- run completion diagnostics
- tool event diagnostics
- live-web unavailability diagnostics

`_provider_target()` should also resolve from `_resolve_llm()`:

```python
def _provider_target(self) -> str | None:
    resolved = self._resolve_llm()
    if resolved.provider == "openai":
        return self.settings.openai_base_url
    if resolved.provider == "groq":
        return self.settings.groq_base_url
    if resolved.provider == "deepinfra":
        return self.settings.deepinfra_base_url
    return None
```

For `_build_component_inventory()`:

- `provider` should be the resolved provider
- `model_name` should remain `self.settings.llm_model`

This keeps dashboard behavior stable while making provider reporting correct.

### 5. Modify: `src/sophia/cli.py`

CLI must use the same shared resolver as runtime.

#### Refactor validation

Current validation branches on `settings.llm_provider`. Replace that with:

```python
try:
    resolved = resolve_llm_config(settings)
except ValueError as exc:
    console.print(f"[red]Error: {exc}[/red]")
    return
```

This single call should cover:

- explicit provider parsing
- alias resolution
- contradictory config detection
- API key validation

#### Refactor `_create_provider()`

Make `_create_provider()` accept a resolved config or call the same resolver
internally. Do not keep separate provider-selection logic in CLI.

#### Normalize settings before constructing the agent

Create the agent with a normalized settings copy:

```python
agent_settings = settings.model_copy(
    update={
        "llm_provider": resolved.provider,
        "llm_model": resolved.wire_model,
    }
)

agent = SophiaAgent(
    provider=provider,
    settings=agent_settings,
    ...
)
```

This keeps CLI and gateway behavior identical.

### 6. No required changes to `src/sophia/agent.py`

This plan intentionally avoids touching the multiple `provider.complete()` and
`provider.stream()` call sites in `agent.py`.

Reason:

- `SophiaAgent` already reads `settings.llm_model`
- if runtime and CLI pass normalized agent settings, the existing agent code
  will automatically send the correct wire model

Optional follow-up:

- Add a helper on `SophiaAgent` for `self._wire_model`, but this is not needed
  for phase 1

### 7. `src/sophia/llm/__init__.py`

No change is required for implementation.

If later tests or modules want cleaner imports, exporting the resolver symbols is
acceptable, but it should not be part of the initial implementation scope.

## Files to Create or Modify

| File | Action |
|------|--------|
| `src/sophia/llm/registry.py` | Create shared parsing and resolution helpers |
| `src/sophia/config.py` | Add DeepInfra config and update field descriptions |
| `src/sophia/gateway/runtime.py` | Cache resolved config, create provider from resolver, normalize agent settings, update diagnostics |
| `src/sophia/cli.py` | Use shared resolver for validation and provider creation, normalize agent settings |
| `tests/test_llm_registry.py` | Create resolver and parser unit tests |
| `tests/test_llm_provider_wiring.py` | Expand runtime provider wiring coverage |
| `tests/test_gateway_platform_expansion.py` | Update component inventory expectations if needed |

No new provider class is created.

## Backward Compatibility

| Config | Result |
|--------|--------|
| `llm_model=openai:gpt-4.1-mini` | Explicit OpenAI, wire model `gpt-4.1-mini` |
| `llm_model=deepinfra:MiniMaxAI/MiniMax-M2.5` | Explicit DeepInfra, wire model `MiniMaxAI/MiniMax-M2.5` |
| `llm_provider=openai`, `llm_model=gpt-4.1-mini` | Resolved to OpenAI via alias |
| `llm_provider=groq`, `llm_model=my-org/custom-model` | Resolved to Groq via legacy fallback |
| `llm_provider=groq`, `llm_model=gpt-4.1-mini` | Error: contradictory config, require explicit spec |

## Testing

### Unit tests for `registry.py`

- `parse_model_spec("openai:gpt-4.1-mini")` returns explicit provider and wire model
- `parse_model_spec("deepinfra:MiniMaxAI/MiniMax-M2.5")` strips only the first colon
- bare model returns `provider=None`, `explicit=False`
- unknown explicit provider raises a clean error
- missing model after `provider:` raises a clean error

### Unit tests for `resolve_llm_config()`

- explicit spec resolves provider, wire model, key field, and base URL
- bare aliased model resolves via alias table
- bare unknown model resolves via legacy `llm_provider`
- conflicting alias vs legacy provider raises
- conflicting explicit spec vs non-default legacy provider raises
- missing API key raises with the correct env var name
- DeepInfra resolves to OpenAI-compatible provider config with DeepInfra base URL

### Runtime wiring tests

- `GatewayRuntime._create_provider()` uses `OpenAIProvider` for DeepInfra
- runtime caches resolved config and reuses it across diagnostics
- `_provider_target()` returns DeepInfra base URL when provider is DeepInfra
- component inventory reports resolved provider and configured model spec

### Agent-normalization tests

- when runtime builds agents, each `SophiaAgent` receives a settings copy whose
  `llm_model` is the wire model, not the raw `provider:model` spec
- same assertion for CLI agent construction

### Regression tests

- existing Groq wiring tests continue to pass
- existing gateway diagnostics tests still record provider name correctly even
  when `GatewayRuntime.start()` was never called

### Manual integration test

Run one real completion with:

- `llm_model=deepinfra:MiniMaxAI/MiniMax-M2.5`
- `DEEPINFRA_API_KEY` set

Verify:

- provider creation succeeds
- the upstream request uses `MiniMaxAI/MiniMax-M2.5`
- dashboard/component inventory shows provider `deepinfra`

## Implementation Sequence

1. Add `registry.py` and its unit tests first.
2. Update `config.py`.
3. Refactor `gateway/runtime.py` to use the resolver and normalized agent settings.
4. Refactor `cli.py` to use the same resolver and normalized agent settings.
5. Update and run tests.
6. Perform one manual DeepInfra smoke test.

## Future Extensions

- Add more bare aliases without changing explicit-spec users.
- Add additional OpenAI-compatible providers by extending `PROVIDER_CONFIG` and
  settings.
- Add a second abstraction for embeddings later if needed.
- If dashboard consumers need both views, add separate `requested_model_spec`
  and `wire_model` fields to component inventory in a later change.
