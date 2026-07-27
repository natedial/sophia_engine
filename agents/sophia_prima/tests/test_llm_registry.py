from __future__ import annotations

import pytest

from sophia.config import Settings
from sophia.llm.registry import (
    normalized_llm_settings,
    parse_model_spec,
    resolve_llm_config,
)


def test_parse_model_spec_explicit_provider_and_wire_model() -> None:
    parsed = parse_model_spec("deepinfra:MiniMaxAI/MiniMax-M2.5")

    assert parsed.provider == "deepinfra"
    assert parsed.model == "MiniMaxAI/MiniMax-M2.5"
    assert parsed.explicit is True


def test_parse_model_spec_bare_model_is_not_explicit() -> None:
    parsed = parse_model_spec("gpt-4.1-mini")

    assert parsed.provider is None
    assert parsed.model == "gpt-4.1-mini"
    assert parsed.explicit is False


def test_parse_model_spec_rejects_unknown_explicit_provider() -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        parse_model_spec("mystery:model")


def test_resolve_llm_config_uses_alias_provider_when_legacy_is_default_openai() -> None:
    resolved = resolve_llm_config(
        Settings(
            llm_provider="openai",
            llm_model="claude-3-5-sonnet-20241022",
            anthropic_api_key="anthropic-secret",
        )
    )

    assert resolved.provider == "anthropic"
    assert resolved.wire_model == "claude-3-5-sonnet-20241022"
    assert resolved.api_key == "anthropic-secret"


def test_resolve_llm_config_uses_legacy_provider_for_unknown_bare_model() -> None:
    resolved = resolve_llm_config(
        Settings(
            llm_provider="groq",
            llm_model="my-org/custom-model",
            groq_api_key="groq-secret",
        )
    )

    assert resolved.provider == "groq"
    assert resolved.wire_model == "my-org/custom-model"
    assert resolved.base_url == "https://api.groq.com"


def test_resolve_llm_config_rejects_conflicting_alias_and_legacy_provider() -> None:
    with pytest.raises(ValueError, match="maps to provider 'openai'"):
        resolve_llm_config(
            Settings(
                llm_provider="groq",
                llm_model="gpt-4.1-mini",
                groq_api_key="groq-secret",
            )
        )


def test_resolve_llm_config_rejects_conflicting_explicit_and_legacy_provider() -> None:
    with pytest.raises(ValueError, match="Conflicting llm_provider and llm_model values"):
        resolve_llm_config(
            Settings(
                llm_provider="anthropic",
                llm_model="deepinfra:MiniMaxAI/MiniMax-M2.5",
                anthropic_api_key="anthropic-secret",
                deepinfra_api_key="deepinfra-secret",
            )
        )


def test_resolve_llm_config_requires_matching_api_key_when_requested() -> None:
    with pytest.raises(ValueError, match="DEEPINFRA_API_KEY"):
        resolve_llm_config(
            Settings(llm_model="deepinfra:MiniMaxAI/MiniMax-M2.5"),
            require_api_key=True,
        )


def test_normalized_llm_settings_strips_provider_prefix() -> None:
    settings = Settings(
        llm_model="deepinfra:MiniMaxAI/MiniMax-M2.5",
        deepinfra_api_key="deepinfra-secret",
    )

    normalized = normalized_llm_settings(settings)

    assert normalized.llm_provider == "deepinfra"
    assert normalized.llm_model == "MiniMaxAI/MiniMax-M2.5"
