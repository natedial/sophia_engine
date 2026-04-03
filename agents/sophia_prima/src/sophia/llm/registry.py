"""Shared model-spec parsing and provider resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass

from sophia.config import Settings

PROVIDER_ALIASES: dict[str, str] = {
    "openai": "openai",
    "gpt": "openai",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "groq": "groq",
    "deepinfra": "deepinfra",
}

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


@dataclass(frozen=True)
class ModelCatalogEntry:
    provider: str
    wire_model: str
    label: str
    description: str
    supports_tool_calls: bool = True

    @property
    def model_spec(self) -> str:
        return f"{self.provider}:{self.wire_model}"


MODEL_CATALOG: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        provider="openai",
        wire_model="gpt-4.1-mini",
        label="GPT-4.1 Mini",
        description="Fast OpenAI general-purpose model with tool support.",
    ),
    ModelCatalogEntry(
        provider="openai",
        wire_model="gpt-4.1",
        label="GPT-4.1",
        description="Higher-capability OpenAI general-purpose model.",
    ),
    ModelCatalogEntry(
        provider="openai",
        wire_model="gpt-4o-mini",
        label="GPT-4o Mini",
        description="Compact multimodal OpenAI model.",
    ),
    ModelCatalogEntry(
        provider="openai",
        wire_model="gpt-4o",
        label="GPT-4o",
        description="Higher-capability OpenAI multimodal model.",
    ),
    ModelCatalogEntry(
        provider="anthropic",
        wire_model="claude-3-5-sonnet-20241022",
        label="Claude 3.5 Sonnet",
        description="Anthropic flagship reasoning and writing model.",
    ),
    ModelCatalogEntry(
        provider="anthropic",
        wire_model="claude-3-haiku-20240307",
        label="Claude 3 Haiku",
        description="Fast Anthropic model for lighter tasks.",
    ),
    ModelCatalogEntry(
        provider="groq",
        wire_model="llama-3.3-70b-versatile",
        label="Llama 3.3 70B Versatile",
        description="Groq-hosted fast inference for tool-driven workflows.",
    ),
    ModelCatalogEntry(
        provider="groq",
        wire_model="llama-3.1-8b-instant",
        label="Llama 3.1 8B Instant",
        description="Lower-latency Groq option for lighter tasks.",
    ),
    ModelCatalogEntry(
        provider="deepinfra",
        wire_model="MiniMaxAI/MiniMax-M2.5",
        label="MiniMax M2.5",
        description="DeepInfra-hosted OpenAI-compatible model.",
    ),
    ModelCatalogEntry(
        provider="deepinfra",
        wire_model="meta-llama/Llama-3.3-70B-Instruct",
        label="DeepInfra Llama 3.3 70B Instruct",
        description="DeepInfra-hosted Llama instruct model.",
    ),
    ModelCatalogEntry(
        provider="deepinfra",
        wire_model="Qwen/Qwen2.5-72B-Instruct",
        label="DeepInfra Qwen 2.5 72B Instruct",
        description="DeepInfra-hosted Qwen instruct model.",
    ),
)


def parse_model_spec(model_spec: str) -> ParsedModelSpec:
    """Parse one llm_model spec into explicit provider and wire-model parts."""
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


def resolve_llm_config(
    settings: Settings,
    *,
    require_api_key: bool = False,
) -> ResolvedLLMConfig:
    """Resolve one Settings object into effective provider and wire-model config."""
    parsed = parse_model_spec(settings.llm_model)
    legacy_provider = _normalize_legacy_provider(settings.llm_provider)

    if parsed.explicit:
        provider = _resolve_explicit_provider(
            explicit_provider=parsed.provider,
            legacy_provider=legacy_provider,
        )
    else:
        provider = _resolve_bare_provider(
            model_name=parsed.model,
            legacy_provider=legacy_provider,
        )

    config = PROVIDER_CONFIG[provider]
    api_key_field = str(config["api_key"])
    base_url_field = str(config["base_url"]) if config["base_url"] else None
    api_key = getattr(settings, api_key_field)
    base_url = getattr(settings, base_url_field) if base_url_field else None

    if require_api_key and not api_key:
        raise ValueError(f"{api_key_field.upper()} is required for gateway operation")

    return ResolvedLLMConfig(
        provider=provider,
        requested_model_spec=settings.llm_model,
        wire_model=parsed.model,
        api_key_field=api_key_field,
        base_url_field=base_url_field,
        api_key=api_key,
        base_url=base_url,
    )


def normalized_llm_settings(
    settings: Settings,
    *,
    require_api_key: bool = False,
) -> Settings:
    """Return a settings copy whose llm fields match the resolved wire model."""
    resolved = resolve_llm_config(settings, require_api_key=require_api_key)
    return settings.model_copy(
        update={
            "llm_provider": resolved.provider,
            "llm_model": resolved.wire_model,
        }
    )


def get_effective_provider(settings: Settings) -> str:
    """Return the resolved provider name without requiring credentials."""
    return resolve_llm_config(settings, require_api_key=False).provider


def list_model_catalog() -> list[ModelCatalogEntry]:
    """Return the curated dashboard model catalog."""
    return list(MODEL_CATALOG)


def _normalize_legacy_provider(raw_provider: str) -> str | None:
    provider = raw_provider.strip().lower()
    if not provider:
        return None
    normalized = PROVIDER_ALIASES.get(provider)
    if not normalized:
        raise ValueError(
            f"Unsupported llm_provider '{raw_provider}'. "
            f"Supported providers: {sorted(PROVIDER_CONFIG)}"
        )
    return normalized


def _resolve_explicit_provider(
    *,
    explicit_provider: str | None,
    legacy_provider: str | None,
) -> str:
    assert explicit_provider is not None
    if legacy_provider and legacy_provider not in {"openai", explicit_provider}:
        raise ValueError(
            "Conflicting llm_provider and llm_model values. "
            "Use explicit provider:model and remove the old llm_provider override."
        )
    return explicit_provider


def _resolve_bare_provider(*, model_name: str, legacy_provider: str | None) -> str:
    alias_provider = MODEL_ALIASES.get(model_name)
    if alias_provider:
        if legacy_provider and legacy_provider not in {"openai", alias_provider}:
            raise ValueError(
                f"Model '{model_name}' maps to provider '{alias_provider}', "
                f"but llm_provider is '{legacy_provider}'. "
                "Use explicit provider:model to disambiguate."
            )
        return alias_provider

    if legacy_provider:
        return legacy_provider

    raise ValueError(f"Unknown model '{model_name}'. Use explicit provider:model format.")
