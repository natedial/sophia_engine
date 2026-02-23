"""Telegram channel adapter owned by the gateway runtime."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from sophia.gateway.models import InboundMessage
from sophia.gateway.runtime import GatewayRuntime

logger = logging.getLogger("sophia.gateway.telegram")


@dataclass(frozen=True)
class TelegramAccountConfig:
    """Configuration for one Telegram bot account."""

    account_id: str
    bot_token: str


class TelegramChannelAdapter:
    """Long-polling Telegram adapter bound to one bot account."""

    def __init__(
        self,
        *,
        runtime: GatewayRuntime,
        account: TelegramAccountConfig,
    ) -> None:
        self.runtime = runtime
        self.account = account
        self._app: Application | None = None

    async def start(self) -> None:
        """Start telegram polling and message handlers."""
        app = Application.builder().token(self.account.bot_token).build()
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        await app.initialize()
        await app.start()
        if app.updater is None:
            raise RuntimeError("telegram updater is unavailable")
        await app.updater.start_polling()
        self._app = app
        logger.info("telegram adapter started: account_id=%s", self.account.account_id)

    async def stop(self) -> None:
        """Stop telegram polling and release resources."""
        if self._app is None:
            return
        app = self._app
        self._app = None
        if app.updater is not None:
            await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("telegram adapter stopped: account_id=%s", self.account.account_id)

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None:
            return
        await update.effective_message.reply_text("Sophia gateway is online. Send a message to begin.")

    async def _on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message is None or update.effective_chat is None:
            return

        text = (update.effective_message.text or "").strip()
        if not text:
            return

        inbound = InboundMessage(
            channel="telegram",
            account_id=self.account.account_id,
            peer_id=str(update.effective_chat.id),
            user_id=str(update.effective_user.id) if update.effective_user else None,
            message_id=str(update.effective_message.message_id),
            text=text,
            metadata={
                "chat_type": update.effective_chat.type,
            },
        )

        try:
            outbound = await self.runtime.handle_inbound(inbound)
            await update.effective_message.reply_text(outbound.text)
        except Exception:
            logger.exception("telegram message handling failed")
            await update.effective_message.reply_text(
                "I hit an internal error while processing that message."
            )


def load_telegram_accounts(
    *,
    token_fallback: str | None,
    raw_accounts_json: str,
) -> list[TelegramAccountConfig]:
    """Parse configured Telegram accounts with a single-token fallback."""
    raw = raw_accounts_json.strip()
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("telegram_accounts_json must be a JSON list")
        accounts: list[TelegramAccountConfig] = []
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise ValueError(f"telegram account at index {i} must be an object")
            account_id = str(item.get("account_id", "")).strip()
            bot_token = str(item.get("bot_token", "")).strip()
            if not account_id or not bot_token:
                raise ValueError(
                    f"telegram account at index {i} requires account_id and bot_token"
                )
            accounts.append(TelegramAccountConfig(account_id=account_id, bot_token=bot_token))
        return accounts

    if token_fallback:
        return [TelegramAccountConfig(account_id="default", bot_token=token_fallback)]

    return []
