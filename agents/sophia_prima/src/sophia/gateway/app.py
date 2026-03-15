"""Gateway web app: health, generic ingress, and control websocket."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from sophia import __version__
from sophia.config import get_settings
from sophia.events import AgentEvent
from sophia.gateway.models import InboundMessage
from sophia.gateway.runtime import GatewayRuntime
from sophia.gateway.run_store import serialize_agent_event
from sophia.gateway.skills import GatewaySkillService

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
    run_id: str | None = None


class CreateAcquisitionJobRequest(BaseModel):
    indicator_family: str = Field(..., min_length=1)
    run_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    playbook_id: str | None = None
    requested_source: str | None = None
    mode: str | None = None
    rationale: str | None = None
    retention_target: str | None = None


class ExecuteAcquisitionJobRequest(BaseModel):
    observation_days: int = Field(default=365, ge=1, le=3650)


class CatalystRadarRequest(BaseModel):
    window_hours: int = Field(default=72, ge=1, le=168)
    portfolio_profile: dict[str, Any] = Field(default_factory=dict)
    include: dict[str, bool] = Field(default_factory=dict)
    max_events: int = Field(default=25, ge=1, le=100)
    as_of: str | None = None
    session_id: str | None = None
    run_id: str | None = None


class TradeIdeasRequest(BaseModel):
    horizon: str = Field(default="intraday")
    risk_budget_bps: float = Field(default=25.0, ge=1.0)
    max_ideas: int = Field(default=5, ge=1, le=20)
    catalyst_ids: list[str] = Field(default_factory=list)
    portfolio_constraints: dict[str, Any] = Field(default_factory=dict)
    style: str = Field(default="macro_relative_value")
    session_id: str | None = None
    run_id: str | None = None


class RiskLensRequest(BaseModel):
    portfolio_id: str = Field(..., min_length=1)
    positions: list[dict[str, Any]] = Field(default_factory=list)
    upcoming_catalyst_ids: list[str] = Field(default_factory=list)
    nav_usd: float = Field(..., gt=0)
    session_id: str | None = None
    run_id: str | None = None


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
    app.state.skill_service = None

    @app.on_event("startup")
    async def startup_event() -> None:
        await runtime.start()
        if runtime._pylon is not None:
            app.state.skill_service = GatewaySkillService(
                pylon=runtime._pylon,
                run_store=runtime._ensure_run_store(),
            )
        if not settings.telegram_polling_enabled:
            return

        try:
            from sophia.gateway.telegram_adapter import (
                TelegramChannelAdapter,
                load_telegram_accounts,
            )
            accounts = load_telegram_accounts(
                token_fallback=settings.telegram_bot_token,
                raw_accounts_json=settings.telegram_accounts_json,
            )
        except Exception:
            logger.exception("invalid Telegram account configuration")
            return

        adapters: list[Any] = []
        for account in accounts:
            adapter = TelegramChannelAdapter(runtime=runtime, account=account)
            await adapter.start()
            adapters.append(adapter)
        app.state.telegram_adapters = adapters

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        adapters: list[Any] = app.state.telegram_adapters
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

    @app.get("/v1/agents")
    async def list_agents() -> dict[str, Any]:
        return {"agents": runtime.list_agents()}

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        record = runtime.get_run_record(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
        return record

    @app.post("/v1/acquisition-jobs")
    async def create_acquisition_job(payload: CreateAcquisitionJobRequest) -> dict[str, Any]:
        try:
            return runtime.create_acquisition_job(
                indicator_family=payload.indicator_family,
                run_id=payload.run_id,
                session_id=payload.session_id,
                agent_id=payload.agent_id,
                playbook_id=payload.playbook_id,
                requested_source=payload.requested_source,
                mode=payload.mode,
                rationale=payload.rationale,
                retention_target=payload.retention_target,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc

    @app.get("/v1/acquisition-jobs/{job_id}")
    async def get_acquisition_job(job_id: str) -> dict[str, Any]:
        record = runtime.get_acquisition_job(job_id)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"acquisition job '{job_id}' not found",
            )
        return record

    @app.post("/v1/acquisition-jobs/{job_id}/execute")
    async def execute_acquisition_job(
        job_id: str,
        payload: ExecuteAcquisitionJobRequest,
    ) -> dict[str, Any]:
        try:
            return await runtime.execute_acquisition_job(
                job_id=job_id,
                observation_days=payload.observation_days,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

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
            run_id=outbound.run_id,
        )

    @app.post("/v1/skills/catalyst-radar/run")
    async def run_catalyst_radar(payload: CatalystRadarRequest) -> dict[str, Any]:
        service: GatewaySkillService | None = app.state.skill_service
        if service is None:
            raise HTTPException(status_code=503, detail="skill service unavailable")
        return await service.run_catalyst_radar(
            window_hours=payload.window_hours,
            portfolio_profile=payload.portfolio_profile,
            include=payload.include,
            max_events=payload.max_events,
            as_of=payload.as_of,
            session_id=payload.session_id,
            agent_id="trader_workbench",
            run_id=payload.run_id,
        )

    @app.post("/v1/skills/trade-ideas/generate")
    async def generate_trade_ideas(payload: TradeIdeasRequest) -> dict[str, Any]:
        service: GatewaySkillService | None = app.state.skill_service
        if service is None:
            raise HTTPException(status_code=503, detail="skill service unavailable")
        return await service.generate_trade_ideas(
            horizon=payload.horizon,
            risk_budget_bps=payload.risk_budget_bps,
            max_ideas=payload.max_ideas,
            catalyst_ids=payload.catalyst_ids,
            portfolio_constraints=payload.portfolio_constraints,
            style=payload.style,
            session_id=payload.session_id,
            agent_id="trader_workbench",
            run_id=payload.run_id,
        )

    @app.post("/v1/skills/risk-lens/analyze")
    async def analyze_risk_lens(payload: RiskLensRequest) -> dict[str, Any]:
        service: GatewaySkillService | None = app.state.skill_service
        if service is None:
            raise HTTPException(status_code=503, detail="skill service unavailable")
        return await service.analyze_risk_lens(
            portfolio_id=payload.portfolio_id,
            positions=payload.positions,
            upcoming_catalyst_ids=payload.upcoming_catalyst_ids,
            nav_usd=payload.nav_usd,
            session_id=payload.session_id,
            agent_id="trader_workbench",
            run_id=payload.run_id,
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
                if frame_type not in {"inbound_message", "stream_inbound_message"}:
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
                    inbound = InboundMessage(
                        channel=request.channel,
                        account_id=request.account_id,
                        peer_id=request.peer_id,
                        user_id=request.user_id,
                        message_id=request.message_id,
                        text=request.text,
                        metadata=request.metadata,
                    )
                    if frame_type == "stream_inbound_message":
                        async for item in runtime.stream_inbound(inbound):
                            if isinstance(item, AgentEvent):
                                await websocket.send_json(
                                    {
                                        "type": "agent_event",
                                        "payload": serialize_agent_event(item),
                                    }
                                )
                            else:
                                await websocket.send_json(
                                    {
                                        "type": "outbound_message",
                                        "payload": {
                                            "text": item.text,
                                            "session_id": item.session_id,
                                            "agent_id": item.agent_id,
                                            "channel": item.channel,
                                            "account_id": item.account_id,
                                            "peer_id": item.peer_id,
                                            "run_id": item.run_id,
                                        },
                                    }
                                )
                    else:
                        outbound = await runtime.handle_inbound(inbound)
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
                                    "run_id": outbound.run_id,
                                },
                            }
                        )
                except Exception as exc:
                    await websocket.send_json({"type": "error", "error": str(exc)})
        except WebSocketDisconnect:
            return

    return app
