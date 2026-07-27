from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("telegram")

from sophia.gateway.telegram_adapter import (
    TelegramAccountConfig,
    TelegramChannelAdapter,
    _chunk_telegram_text,
)
from sophia.gateway.models import DeliveryArtifact


class _FakeRuntime:
    def __init__(self, text: str, *, artifacts: tuple[DeliveryArtifact, ...] = ()) -> None:
        self._text = text
        self._artifacts = artifacts

    async def handle_inbound(self, _message):
        return SimpleNamespace(text=self._text, run_id="run-123", artifacts=self._artifacts)


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


@pytest.mark.asyncio
async def test_on_text_sends_document_attachment_when_present(tmp_path: Path) -> None:
    doc_path = tmp_path / "table.svg"
    doc_path.write_text("<svg></svg>", encoding="utf-8")
    reply = AsyncMock()
    reply_document = AsyncMock()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=321, type="private"),
        effective_user=SimpleNamespace(id=777),
        effective_message=SimpleNamespace(
            text="show me the table",
            message_id=42,
            reply_text=reply,
            reply_document=reply_document,
            reply_photo=AsyncMock(),
        ),
    )
    adapter = TelegramChannelAdapter(
        runtime=_FakeRuntime(
            "I attached the table because Telegram does not render text tables cleanly.",
            artifacts=(
                DeliveryArtifact(
                    artifact_id="artifact-1",
                    kind="document",
                    mime_type="image/svg+xml",
                    path=str(doc_path),
                ),
            ),
        ),
        account=TelegramAccountConfig(account_id="default", bot_token="token"),
    )

    await adapter._on_text(update, SimpleNamespace())

    assert reply.await_count == 1
    assert reply_document.await_count == 1


@pytest.mark.asyncio
async def test_on_text_sends_photo_attachment_when_present(tmp_path: Path) -> None:
    png_path = tmp_path / "table.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    reply = AsyncMock()
    reply_photo = AsyncMock()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=321, type="private"),
        effective_user=SimpleNamespace(id=777),
        effective_message=SimpleNamespace(
            text="show me the table",
            message_id=42,
            reply_text=reply,
            reply_document=AsyncMock(),
            reply_photo=reply_photo,
        ),
    )
    adapter = TelegramChannelAdapter(
        runtime=_FakeRuntime(
            "I attached the table because Telegram does not render text tables cleanly.",
            artifacts=(
                DeliveryArtifact(
                    artifact_id="artifact-2",
                    kind="image",
                    mime_type="image/png",
                    path=str(png_path),
                ),
            ),
        ),
        account=TelegramAccountConfig(account_id="default", bot_token="token"),
    )

    await adapter._on_text(update, SimpleNamespace())

    assert reply.await_count == 1
    assert reply_photo.await_count == 1
