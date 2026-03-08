from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telegram")

from sophia.gateway.telegram_adapter import TelegramAccountConfig, TelegramChannelAdapter


class _FakeRuntime:
    def __init__(self, *, cleared: bool) -> None:
        self._cleared = cleared
        self.calls = []

    def clear_session(self, message) -> bool:
        self.calls.append(message)
        return self._cleared


@pytest.mark.asyncio
async def test_reset_command_clears_current_chat_session() -> None:
    runtime = _FakeRuntime(cleared=True)
    adapter = TelegramChannelAdapter(
        runtime=runtime,
        account=TelegramAccountConfig(account_id="default", bot_token="token"),
    )
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=321, type="private"),
        effective_user=SimpleNamespace(id=777),
        effective_message=SimpleNamespace(message_id=42, reply_text=reply),
    )

    await adapter._on_reset(update, SimpleNamespace())

    assert len(runtime.calls) == 1
    assert runtime.calls[0].channel == "telegram"
    assert runtime.calls[0].account_id == "default"
    assert runtime.calls[0].peer_id == "321"
    assert runtime.calls[0].user_id == "777"
    assert runtime.calls[0].text == "/reset"
    reply.assert_awaited_once_with("Session reset for this chat.")


@pytest.mark.asyncio
async def test_reset_command_handles_missing_session() -> None:
    runtime = _FakeRuntime(cleared=False)
    adapter = TelegramChannelAdapter(
        runtime=runtime,
        account=TelegramAccountConfig(account_id="default", bot_token="token"),
    )
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=321, type="private"),
        effective_user=SimpleNamespace(id=777),
        effective_message=SimpleNamespace(message_id=42, reply_text=reply),
    )

    await adapter._on_reset(update, SimpleNamespace())

    reply.assert_awaited_once_with("No active session to reset for this chat.")
