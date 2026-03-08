from __future__ import annotations

from types import SimpleNamespace

import pytest

from sophia.config import Settings
from sophia.gateway.models import InboundMessage
from sophia.gateway.runtime import GatewayRuntime


@pytest.mark.asyncio
async def test_handle_inbound_returns_retry_message_on_groq_capacity_error() -> None:
    class FakeAgent:
        async def chat(self, _text, _context):
            raise RuntimeError("Groq API error HTTP 429: rate_limit_exceeded")

    runtime = GatewayRuntime(settings=Settings())
    runtime._agents[runtime.settings.gateway_default_agent_id] = FakeAgent()

    inbound = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="123",
        text="hello",
    )

    outbound = await runtime.handle_inbound(inbound)

    assert outbound.channel == "telegram"
    assert "temporary model capacity limit" in outbound.text.lower()


@pytest.mark.asyncio
async def test_handle_inbound_returns_retry_message_on_openai_quota_error() -> None:
    class FakeAgent:
        async def chat(self, _text, _context):
            raise RuntimeError(
                'OpenAI API error HTTP 429: {"error":{"message":"insufficient_quota","type":"insufficient_quota"}}'
            )

    runtime = GatewayRuntime(settings=Settings())
    runtime._agents[runtime.settings.gateway_default_agent_id] = FakeAgent()

    inbound = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="123",
        text="hello",
    )

    outbound = await runtime.handle_inbound(inbound)

    assert outbound.channel == "telegram"
    assert "temporary model capacity limit" in outbound.text.lower()


@pytest.mark.asyncio
async def test_handle_inbound_returns_retry_message_on_provider_timeout() -> None:
    class FakeAgent:
        async def chat(self, _text, _context):
            raise RuntimeError("OpenAI API timeout: ReadTimeout")

    runtime = GatewayRuntime(settings=Settings())
    runtime._agents[runtime.settings.gateway_default_agent_id] = FakeAgent()

    inbound = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="123",
        text="hello",
    )

    outbound = await runtime.handle_inbound(inbound)

    assert outbound.channel == "telegram"
    assert "temporary model capacity limit" in outbound.text.lower()


@pytest.mark.asyncio
async def test_handle_inbound_raises_unrelated_runtime_error() -> None:
    class FakeAgent:
        async def chat(self, _text, _context):
            raise RuntimeError("unexpected crash")

    runtime = GatewayRuntime(settings=Settings())
    runtime._agents[runtime.settings.gateway_default_agent_id] = FakeAgent()

    inbound = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="123",
        text="hello",
    )

    with pytest.raises(RuntimeError, match="unexpected crash"):
        await runtime.handle_inbound(inbound)


@pytest.mark.asyncio
async def test_clear_session_removes_only_target_chat_session() -> None:
    class FakeAgent:
        async def chat(self, _text, _context):
            return SimpleNamespace(content="ok")

    runtime = GatewayRuntime(settings=Settings())
    runtime._agents[runtime.settings.gateway_default_agent_id] = FakeAgent()

    inbound_a = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="123",
        text="hello",
    )
    inbound_b = InboundMessage(
        channel="telegram",
        account_id="default",
        peer_id="456",
        text="hello",
    )

    await runtime.handle_inbound(inbound_a)
    await runtime.handle_inbound(inbound_b)

    assert runtime.clear_session(inbound_a)
    assert not runtime.clear_session(inbound_a)

    outbound_b = await runtime.handle_inbound(
        InboundMessage(
            channel="telegram",
            account_id="default",
            peer_id="456",
            text="still there",
        )
    )
    assert outbound_b.session_id == "telegram:default:456"
