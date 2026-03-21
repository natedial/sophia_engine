from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telegram")

from sophia.gateway.telegram_adapter import (
    TelegramAccountConfig,
    TelegramChannelAdapter,
    _chunk_telegram_text,
)


class _FakeRuntime:
    def __init__(self, text: str) -> None:
        self._text = text

    async def handle_inbound(self, _message):
        return SimpleNamespace(text=self._text, run_id="run-123")


def test_chunk_telegram_text_splits_long_payloads() -> None:
    text = ("alpha " * 900).strip()
    chunks = _chunk_telegram_text(text, max_chars=4000)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 4000 for chunk in chunks)
    assert " ".join(chunks).replace("  ", " ").startswith("alpha alpha")


@pytest.mark.asyncio
async def test_on_text_sends_long_response_in_multiple_messages() -> None:
    reply = AsyncMock()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=321, type="private"),
        effective_user=SimpleNamespace(id=777),
        effective_message=SimpleNamespace(
            text=("alpha " * 900).strip(),
            message_id=42,
            reply_text=reply,
        ),
    )
    adapter = TelegramChannelAdapter(
        runtime=_FakeRuntime(("beta " * 900).strip()),
        account=TelegramAccountConfig(account_id="default", bot_token="token"),
    )

    await adapter._on_text(update, SimpleNamespace())

    assert reply.await_count >= 2
    for call in reply.await_args_list:
        assert len(call.args[0]) <= 4000
