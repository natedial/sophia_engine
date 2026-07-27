from __future__ import annotations

from types import SimpleNamespace

import pytest

import sophia.cli as cli_module
from sophia.agent_profiles import AgentProfile
from sophia.config import Settings
import sophia.gateway.runtime as runtime_module
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


def test_gateway_runtime_create_provider_supports_deepinfra_via_openai_provider(
    monkeypatch,
) -> None:
    captured: dict[str, str | float] = {}

    class FakeOpenAIProvider:
        def __init__(self, *, api_key: str, base_url: str, timeout: float) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["timeout"] = timeout

    import sophia.llm.openai_provider as openai_module

    monkeypatch.setattr(openai_module, "OpenAIProvider", FakeOpenAIProvider)
    runtime = GatewayRuntime(
        settings=Settings(
            llm_model="deepinfra:MiniMaxAI/MiniMax-M2.5",
            deepinfra_api_key="deepinfra-secret",
            deepinfra_base_url="https://api.deepinfra.com/v1/openai",
            llm_request_timeout_sec=45.0,
        )
    )

    provider = runtime._create_provider()

    assert isinstance(provider, FakeOpenAIProvider)
    assert captured == {
        "api_key": "deepinfra-secret",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "timeout": 45.0,
    }


def test_gateway_runtime_rejects_unsupported_legacy_provider() -> None:
    runtime = GatewayRuntime(settings=Settings(llm_provider="unsupported"))

    with pytest.raises(ValueError, match="Unsupported llm_provider"):
        runtime._create_provider()


@pytest.mark.asyncio
async def test_gateway_runtime_start_normalizes_agent_settings(monkeypatch, tmp_path) -> None:
    captured_settings: list[Settings] = []

    class FakeProvider:
        async def close(self) -> None:
            return None

    class FakePylon:
        async def preflight(self):
            return SimpleNamespace(unavailable_tools=[])

        async def close(self) -> None:
            return None

    class FakeSophiaAgent:
        def __init__(self, *, settings: Settings, **_kwargs) -> None:
            captured_settings.append(settings)
            self.preflight_result = None

    async def fake_create_pylon(self):
        return FakePylon()

    async def fake_build_component_inventory(self, **_kwargs):
        return []

    monkeypatch.setattr(runtime_module, "SophiaAgent", FakeSophiaAgent)
    monkeypatch.setattr(
        runtime_module,
        "load_agent_profiles",
        lambda **_kwargs: {
            "sophia_prima": AgentProfile(agent_id="sophia_prima", label="Sophia Prima")
        },
    )
    monkeypatch.setattr(GatewayRuntime, "_create_provider", lambda self: FakeProvider())
    monkeypatch.setattr(GatewayRuntime, "_create_pylon", fake_create_pylon)
    monkeypatch.setattr(GatewayRuntime, "_build_component_inventory", fake_build_component_inventory)

    runtime = GatewayRuntime(
        settings=Settings(
            gateway_artifact_store_path=tmp_path / "gateway_runs.db",
            llm_model="deepinfra:MiniMaxAI/MiniMax-M2.5",
            deepinfra_api_key="deepinfra-secret",
        )
    )

    await runtime.start()

    assert captured_settings
    assert captured_settings[0].llm_provider == "deepinfra"
    assert captured_settings[0].llm_model == "MiniMaxAI/MiniMax-M2.5"


@pytest.mark.asyncio
async def test_cli_async_main_normalizes_agent_settings(monkeypatch) -> None:
    captured_settings: list[Settings] = []

    class FakeProvider:
        async def close(self) -> None:
            return None

    class FakeSophiaAgent:
        def __init__(self, *, settings: Settings, **_kwargs) -> None:
            captured_settings.append(settings)

    async def fake_setup_pylon(_settings):
        return object(), SimpleNamespace(services={}, unavailable_tools=[])

    async def fake_init_canvas(*_args, **_kwargs):
        return None

    async def fake_chat_loop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "argparse.ArgumentParser.parse_args",
        lambda self: SimpleNamespace(config=None),
    )
    monkeypatch.setattr(
        cli_module,
        "get_settings",
        lambda: Settings(
            llm_model="deepinfra:MiniMaxAI/MiniMax-M2.5",
            deepinfra_api_key="deepinfra-secret",
        ),
    )
    monkeypatch.setattr(cli_module, "_create_provider", lambda *_args, **_kwargs: FakeProvider())
    monkeypatch.setattr(cli_module, "setup_pylon", fake_setup_pylon)
    monkeypatch.setattr(cli_module, "init_canvas", fake_init_canvas)
    monkeypatch.setattr(cli_module, "chat_loop", fake_chat_loop)
    monkeypatch.setattr(cli_module, "SophiaAgent", FakeSophiaAgent)

    await cli_module.async_main()

    assert captured_settings
    assert captured_settings[0].llm_provider == "deepinfra"
    assert captured_settings[0].llm_model == "MiniMaxAI/MiniMax-M2.5"
