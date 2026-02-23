"""Gateway web app: health, generic ingress, and control websocket."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from sophia import __version__
from sophia.config import get_settings
from sophia.gateway.models import InboundMessage
from sophia.gateway.runtime import GatewayRuntime
from sophia.gateway.telegram_adapter import TelegramChannelAdapter, load_telegram_accounts

logger = logging.getLogger("sophia.gateway.app")


class InboundMessageRequest(BaseModel):
    """HTTP ingress payload for normalized messages."""

    channel: str = Field(..., min_length=1)
    account_id: str = Field(..., min_length=1)
    peer_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    user_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutboundMessageResponse(BaseModel):
    """HTTP egress payload with resolved session and content."""

    text: str
    session_id: str
    agent_id: str
    channel: str
    account_id: str
    peer_id: str


def create_app() -> FastAPI:
    """Build the gateway web app."""
    settings = get_settings()
    runtime = GatewayRuntime(settings=settings)
    app = FastAPI(
        title="Sophia Gateway",
        description="Surface gateway daemon for channel adapters and deterministic routing.",
        version=__version__,
    )
    app.state.runtime = runtime
    app.state.telegram_adapters = []

    @app.on_event("startup")
    async def startup_event() -> None:
        await runtime.start()
        if not settings.telegram_polling_enabled:
            return

        try:
            accounts = load_telegram_accounts(
                token_fallback=settings.telegram_bot_token,
                raw_accounts_json=settings.telegram_accounts_json,
            )
        except Exception:
            logger.exception("invalid Telegram account configuration")
            return

        adapters: list[TelegramChannelAdapter] = []
        for account in accounts:
            adapter = TelegramChannelAdapter(runtime=runtime, account=account)
            await adapter.start()
            adapters.append(adapter)
        app.state.telegram_adapters = adapters

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        adapters: list[TelegramChannelAdapter] = app.state.telegram_adapters
        for adapter in adapters:
            try:
                await adapter.stop()
            except Exception:
                logger.exception("failed stopping telegram adapter")
        await runtime.stop()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok" if runtime.is_ready else "degraded",
            "startup_error": runtime.startup_error,
            "gateway_version": __version__,
        }

    @app.post("/v1/messages", response_model=OutboundMessageResponse)
    async def post_message(payload: InboundMessageRequest) -> OutboundMessageResponse:
        inbound = InboundMessage(
            channel=payload.channel,
            account_id=payload.account_id,
            peer_id=payload.peer_id,
            user_id=payload.user_id,
            message_id=payload.message_id,
            text=payload.text,
            metadata=payload.metadata,
        )
        try:
            outbound = await runtime.handle_inbound(inbound)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("gateway message handling failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return OutboundMessageResponse(
            text=outbound.text,
            session_id=outbound.session_id,
            agent_id=outbound.agent_id,
            channel=outbound.channel,
            account_id=outbound.account_id,
            peer_id=outbound.peer_id,
        )

    @app.websocket("/ws")
    async def ws_gateway(websocket: WebSocket) -> None:
        await websocket.accept()

        try:
            connect_msg = await websocket.receive_json()
        except Exception:
            await websocket.close(code=1003)
            return

        if not isinstance(connect_msg, dict) or connect_msg.get("type") != "connect":
            await websocket.send_json(
                {"type": "error", "error": "first frame must be a connect message"}
            )
            await websocket.close(code=1008)
            return

        await websocket.send_json(
            {
                "type": "connected",
                "gateway": "sophia",
                "version": __version__,
            }
        )

        try:
            while True:
                frame = await websocket.receive_json()
                if not isinstance(frame, dict):
                    await websocket.send_json({"type": "error", "error": "frame must be an object"})
                    continue

                frame_type = frame.get("type")
                if frame_type == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                if frame_type != "inbound_message":
                    await websocket.send_json(
                        {"type": "error", "error": f"unsupported frame type: {frame_type}"}
                    )
                    continue

                payload = frame.get("payload")
                if not isinstance(payload, dict):
                    await websocket.send_json({"type": "error", "error": "payload must be an object"})
                    continue

                try:
                    request = InboundMessageRequest.model_validate(payload)
                    outbound = await runtime.handle_inbound(
                        InboundMessage(
                            channel=request.channel,
                            account_id=request.account_id,
                            peer_id=request.peer_id,
                            user_id=request.user_id,
                            message_id=request.message_id,
                            text=request.text,
                            metadata=request.metadata,
                        )
                    )
                    await websocket.send_json(
                        {
                            "type": "outbound_message",
                            "payload": {
                                "text": outbound.text,
                                "session_id": outbound.session_id,
                                "agent_id": outbound.agent_id,
                                "channel": outbound.channel,
                                "account_id": outbound.account_id,
                                "peer_id": outbound.peer_id,
                            },
                        }
                    )
                except Exception as exc:
                    await websocket.send_json({"type": "error", "error": str(exc)})
        except WebSocketDisconnect:
            return

    return app
