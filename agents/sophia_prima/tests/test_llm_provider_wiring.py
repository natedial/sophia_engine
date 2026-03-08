from __future__ import annotations

import pytest

from sophia.config import Settings
from sophia.gateway.runtime import GatewayRuntime


def test_gateway_runtime_create_provider_supports_groq(monkeypatch) -> None:
    captured: dict[str, str | float] = {}

    class FakeGroqProvider:
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["timeout"] = timeout

    import sophia.llm.groq_provider as groq_module

    monkeypatch.setattr(groq_module, "GroqProvider", FakeGroqProvider)
    runtime = GatewayRuntime(
        settings=Settings(
            llm_provider="groq",
            groq_api_key="groq-secret",
            groq_base_url="https://api.groq.com/openai/v1",
            llm_request_timeout_sec=123.0,
        )
    )
    provider = runtime._create_provider()

    assert isinstance(provider, FakeGroqProvider)
    assert captured == {
        "api_key": "groq-secret",
        "base_url": "https://api.groq.com/openai/v1",
        "timeout": 123.0,
    }


def test_gateway_runtime_create_provider_requires_groq_api_key() -> None:
    runtime = GatewayRuntime(
        settings=Settings(
            llm_provider="groq",
            groq_api_key="",
        )
    )

    with pytest.raises(ValueError, match="GROQ_API_KEY"):
        runtime._create_provider()


def test_gateway_runtime_unsupported_provider_lists_groq() -> None:
    runtime = GatewayRuntime(settings=Settings(llm_provider="unsupported"))

    with pytest.raises(ValueError, match="anthropic, openai, groq"):
        runtime._create_provider()
