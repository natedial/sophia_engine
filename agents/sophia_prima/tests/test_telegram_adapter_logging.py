from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telegram")

from sophia.gateway.telegram_adapter import TelegramAccountConfig, TelegramChannelAdapter


class _FakeRuntime:
    async def handle_inbound(self, _message):
        return SimpleNamespace(text="short reply", run_id="run-456")


@pytest.mark.asyncio
async def test_on_text_sends_single_short_message() -> None:
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=321, type="private"),
        effective_user=SimpleNamespace(id=777),
        effective_message=SimpleNamespace(
            text="hello",
            message_id=42,
            reply_text=reply,
        ),
    )
    adapter = TelegramChannelAdapter(
        runtime=_FakeRuntime(),
        account=TelegramAccountConfig(account_id="default", bot_token="token"),
    )

    await adapter._on_text(update, SimpleNamespace())

    reply.assert_awaited_once_with("short reply")
