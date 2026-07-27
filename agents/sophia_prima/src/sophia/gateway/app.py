"""Gateway web app: health, generic ingress, and control websocket."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from sophia import __version__
from sophia.config import get_settings
from sophia.events import AgentEvent
from sophia.gateway.models import InboundMessage
from sophia.gateway.run_store import serialize_agent_event
from sophia.gateway.runtime import GatewayRuntime
from sophia.gateway.skills import GatewaySkillService
from sophia.presentation.models import PresentationRenderTheme
from sophia.self_editing import SelfEditProposal, build_self_edit_service

logger = logging.getLogger("sophia.gateway.app")

_FORGE_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9_-])?$"
)


def _forge_path_segment(value: str, *, field_name: str) -> str:
    """Validate and encode an identifier before including it in a Forge URL path."""
    if not _FORGE_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"invalid {field_name}")
    return quote(value, safe="")


def _forge_upstream_detail(exc: httpx.HTTPStatusError) -> tuple[int, str]:
    """Return a safe client-facing Forge error without exposing upstream internals."""
    status_code = exc.response.status_code if exc.response is not None else 502
    return status_code, "Forge service request failed"


class InboundMessageRequest(BaseModel):
    """HTTP ingress payload for normalized messages."""

    channel: str = Field(..., min_length=1)
    account_id: str = Field(..., min_length=1)
    peer_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    user_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeliveryArtifactResponse(BaseModel):
    """Serializable artifact metadata for dashboard and channel clients."""

    artifact_id: str
    kind: str
    mime_type: str
    path: str
    caption: str | None = None


class OutboundMessageResponse(BaseModel):
    """HTTP egress payload with resolved session and content."""

    text: str
    session_id: str
    agent_id: str
    channel: str
    account_id: str
    peer_id: str
    run_id: str | None = None
    delivery_mode: str = "text"
    artifacts: list[DeliveryArtifactResponse] = Field(default_factory=list)


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


class PresentationCoreUpdateRequest(BaseModel):
    content: str = Field(default="")


class PresentationChannelUpdateRequest(BaseModel):
    supports_markdown_tables: bool = True
    supports_image_attachments: bool = False
    supports_document_attachments: bool = False
    max_text_chars: int = Field(default=4000, ge=1)
    preferred_structured_delivery: dict[str, str] = Field(default_factory=dict)


class PresentationThemeUpdateRequest(BaseModel):
    font_family: str
    title_font_size: int = Field(ge=1)
    body_font_size: int = Field(ge=1)
    line_height: int = Field(ge=1)
    margin: int = Field(ge=0)
    char_width: float = Field(gt=0)
    corner_radius: int = Field(ge=0)
    background_start: str
    background_end: str
    panel_fill: str
    panel_stroke: str
    accent: str
    title_color: str
    header_color: str
    text_color: str
    divider_color: str
    shadow_color: str
    header_fill: str


class CommunicationPreferencesUpdateRequest(BaseModel):
    big_picture_vs_brevity: Literal["full_picture", "brevity"]
    verbose_vs_terse: Literal["verbose", "terse"]
    precision_vs_approximation: Literal["precision", "approximation"]
    structured_vs_narrative: Literal["structured", "narrative"]
    proactive_vs_reactive: Literal["proactive", "reactive"]
    decisive_vs_caveated: Literal["decisive", "caveated"]


class ProposalReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]
    actor: str = Field(default="dashboard")
    reason: str = Field(default="")


class LLMSelectionUpdateRequest(BaseModel):
    model_spec: str = Field(..., min_length=1)


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

    def _refresh_skill_service() -> None:
        if runtime._pylon is not None:
            app.state.skill_service = GatewaySkillService(
                pylon=runtime._pylon,
                run_store=runtime._ensure_run_store(),
            )
        else:
            app.state.skill_service = None

    @app.on_event("startup")
    async def startup_event() -> None:
        await runtime.start()
        _refresh_skill_service()
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

    @app.get("/v1/dashboard/runs")
    async def list_runs(
        limit: int = Query(default=25, ge=1, le=100),
        agent_id: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        return {
            "runs": runtime.list_run_records(
                limit=limit,
                agent_id=agent_id,
                status=status,
            )
        }

    @app.get("/v1/dashboard/components")
    async def list_component_inventory() -> dict[str, Any]:
        return {"components": await runtime.describe_components()}

    @app.get("/v1/dashboard/llm/catalog")
    async def get_llm_catalog() -> dict[str, Any]:
        return runtime.describe_llm_catalog()

    @app.put("/v1/dashboard/llm/selection")
    async def update_llm_selection(payload: LLMSelectionUpdateRequest) -> dict[str, Any]:
        try:
            catalog = await runtime.update_llm_model(payload.model_spec)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        _refresh_skill_service()
        return catalog

    @app.get("/v1/dashboard/presentation")
    async def get_presentation_config() -> dict[str, Any]:
        return _read_presentation_config(settings)

    @app.put("/v1/dashboard/presentation/core")
    async def update_presentation_core(payload: PresentationCoreUpdateRequest) -> dict[str, Any]:
        settings.presentation_core_path.parent.mkdir(parents=True, exist_ok=True)
        settings.presentation_core_path.write_text(payload.content.rstrip() + "\n", encoding="utf-8")
        runtime.reload_presentation_registry()
        return {"core_guidance": payload.content.rstrip()}

    @app.put("/v1/dashboard/presentation/channels/{channel}")
    async def update_presentation_channel(
        channel: str,
        payload: PresentationChannelUpdateRequest,
    ) -> dict[str, Any]:
        normalized_channel = channel.strip().lower()
        if not normalized_channel:
            raise HTTPException(status_code=400, detail="channel is required")
        config_path = settings.presentation_channels_path / f"{normalized_channel}.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        channel_payload = {
            "channel": normalized_channel,
            "supports_markdown_tables": payload.supports_markdown_tables,
            "supports_image_attachments": payload.supports_image_attachments,
            "supports_document_attachments": payload.supports_document_attachments,
            "max_text_chars": payload.max_text_chars,
            "preferred_structured_delivery": payload.preferred_structured_delivery,
        }
        config_path.write_text(json.dumps(channel_payload, indent=2) + "\n", encoding="utf-8")
        runtime.reload_presentation_registry()
        return {"channel_config": channel_payload}

    @app.put("/v1/dashboard/presentation/rendering/theme")
    async def update_presentation_theme(payload: PresentationThemeUpdateRequest) -> dict[str, Any]:
        theme_path = settings.presentation_rendering_path / "png_table_theme.json"
        theme_path.parent.mkdir(parents=True, exist_ok=True)
        theme_payload = payload.model_dump()
        theme_path.write_text(json.dumps(theme_payload, indent=2) + "\n", encoding="utf-8")
        runtime.reload_presentation_registry()
        return {"render_theme": theme_payload}

    @app.put("/v1/dashboard/presentation/preferences")
    async def update_communication_preferences(
        payload: CommunicationPreferencesUpdateRequest,
    ) -> dict[str, Any]:
        preferences_path = _communication_preferences_path(settings)
        preferences_path.parent.mkdir(parents=True, exist_ok=True)
        preferences_payload = payload.model_dump()
        preferences_path.write_text(
            json.dumps(preferences_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"communication_preferences": preferences_payload}

    @app.get("/v1/dashboard/artifacts/{artifact_id}")
    async def get_dashboard_artifact(artifact_id: str) -> dict[str, Any]:
        artifact = runtime.get_skill_artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail=f"artifact '{artifact_id}' not found")
        return artifact

    @app.get("/v1/dashboard/proposals")
    async def list_dashboard_proposals(
        status: str | None = None,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        service = build_self_edit_service(settings=settings)
        proposals = service.list_proposals()
        if status:
            proposals = tuple(item for item in proposals if item.status == status)
        return {
            "proposals": [_serialize_proposal(proposal, include_patch=False) for proposal in proposals[:limit]]
        }

    @app.get("/v1/dashboard/proposals/{proposal_id}")
    async def get_dashboard_proposal(proposal_id: str) -> dict[str, Any]:
        service = build_self_edit_service(settings=settings)
        try:
            proposal = service.load_proposal(proposal_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _serialize_proposal(proposal, include_patch=True)

    @app.post("/v1/dashboard/proposals/{proposal_id}/review")
    async def review_dashboard_proposal(
        proposal_id: str,
        payload: ProposalReviewRequest,
    ) -> dict[str, Any]:
        service = build_self_edit_service(settings=settings)
        try:
            proposal = service.review_proposal(
                proposal_id=proposal_id,
                status=payload.status,
                actor=payload.actor,
                reason=payload.reason,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _serialize_proposal(proposal, include_patch=True)

    @app.get("/v1/dashboard/forge/promotions")
    async def list_forge_promotions(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            runs = await _fetch_forge_runs(settings=settings, limit=limit)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        promotion_runs = [
            run
            for run in runs
            if str(run.get("promotion_mode") or "") in {"patch", "draft_pr"}
        ]
        return {"runs": promotion_runs}

    @app.get("/v1/dashboard/forge/promotions/{run_id}")
    async def get_forge_promotion(run_id: str) -> dict[str, Any]:
        try:
            run = await _fetch_forge_run(settings=settings, run_id=run_id)
            artifacts = await _fetch_forge_artifacts(settings=settings, run_id=run_id)
            promotion_artifacts = [
                artifact
                for artifact in artifacts
                if artifact.get("artifact_type") in {"promotion_status", "pr_request", "patch"}
            ]
            contents: dict[str, Any] = {}
            for artifact in promotion_artifacts:
                artifact_id = str(artifact.get("artifact_id") or "")
                artifact_type = str(artifact.get("artifact_type") or "")
                if not artifact_id or artifact_type not in {"promotion_status", "pr_request", "patch"}:
                    continue
                content = await _fetch_forge_artifact_content(
                    settings=settings,
                    run_id=run_id,
                    artifact_id=artifact_id,
                )
                if artifact_type in {"promotion_status", "pr_request"}:
                    contents[artifact_type] = json.loads(content.decode("utf-8"))
                else:
                    contents[artifact_type] = content.decode("utf-8")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status_code, detail = _forge_upstream_detail(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc
        return {
            "run": run,
            "artifacts": promotion_artifacts,
            "content": contents,
        }

    @app.post("/v1/dashboard/forge/promotions/{run_id}/publish")
    async def publish_forge_promotion(run_id: str) -> dict[str, Any]:
        try:
            return await _publish_forge_promotion(settings=settings, run_id=run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status_code, detail = _forge_upstream_detail(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc

    @app.get("/v1/dashboard/forge/promotions/{run_id}/artifacts/{artifact_id}/content")
    async def get_forge_promotion_artifact_content(run_id: str, artifact_id: str) -> Response:
        try:
            content = await _fetch_forge_artifact_content(
                settings=settings,
                run_id=run_id,
                artifact_id=artifact_id,
            )
            artifacts = await _fetch_forge_artifacts(settings=settings, run_id=run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            status_code, detail = _forge_upstream_detail(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc

        artifact = next(
            (item for item in artifacts if str(item.get("artifact_id") or "") == artifact_id),
            None,
        )
        media_type = None if artifact is None else artifact.get("content_type")
        return Response(content=content, media_type=media_type)

    @app.get("/v1/dashboard/artifacts/{artifact_id}/content")
    async def get_dashboard_artifact_content(artifact_id: str) -> FileResponse:
        artifact = runtime.get_skill_artifact(artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail=f"artifact '{artifact_id}' not found")
        payload = artifact.get("payload")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=404, detail="artifact has no file payload")
        raw_path = payload.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise HTTPException(status_code=404, detail="artifact has no file path")
        artifact_path = Path(raw_path).expanduser().resolve(strict=False)
        allowed_root = settings.presentation_artifact_dir.expanduser().resolve(strict=False)
        if not _path_within(artifact_path, allowed_root):
            raise HTTPException(status_code=403, detail="artifact path is outside allowed directory")
        if not artifact_path.exists() or not artifact_path.is_file():
            raise HTTPException(status_code=404, detail="artifact file not found")
        mime_type = payload.get("mime_type")
        media_type = mime_type if isinstance(mime_type, str) and mime_type else None
        return FileResponse(path=artifact_path, media_type=media_type, filename=artifact_path.name)

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
            delivery_mode=outbound.delivery_mode,
            artifacts=[_serialize_delivery_artifact(artifact) for artifact in outbound.artifacts],
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
                                        "delivery_mode": item.delivery_mode,
                                        "artifacts": [
                                            _serialize_delivery_artifact(artifact).model_dump()
                                            for artifact in item.artifacts
                                        ],
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
                                    "delivery_mode": outbound.delivery_mode,
                                    "artifacts": [
                                        _serialize_delivery_artifact(artifact).model_dump()
                                        for artifact in outbound.artifacts
                                    ],
                                },
                            }
                        )
                except Exception as exc:
                    await websocket.send_json({"type": "error", "error": str(exc)})
        except WebSocketDisconnect:
            return

    return app


def _read_presentation_config(settings) -> dict[str, Any]:
    core_guidance = ""
    if settings.presentation_core_path.exists():
        core_guidance = settings.presentation_core_path.read_text(encoding="utf-8").strip()

    channels: list[dict[str, Any]] = []
    if settings.presentation_channels_path.exists():
        for config_path in sorted(settings.presentation_channels_path.glob("*.json")):
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            channels.append(payload)

    theme = asdict(PresentationRenderTheme())
    theme_path = settings.presentation_rendering_path / "png_table_theme.json"
    if theme_path.exists():
        theme = json.loads(theme_path.read_text(encoding="utf-8"))

    return {
        "core_guidance": core_guidance,
        "channels": channels,
        "render_theme": theme,
        "communication_preferences": _read_communication_preferences(settings),
    }


def _serialize_delivery_artifact(artifact) -> DeliveryArtifactResponse:
    return DeliveryArtifactResponse(
        artifact_id=artifact.artifact_id,
        kind=artifact.kind,
        mime_type=artifact.mime_type,
        path=artifact.path,
        caption=artifact.caption,
    )


def _communication_preferences_path(settings) -> Path:
    return settings.presentation_channels_path.parent / "communication_preferences.json"


def _default_communication_preferences() -> dict[str, str]:
    return {
        "big_picture_vs_brevity": "full_picture",
        "verbose_vs_terse": "terse",
        "precision_vs_approximation": "precision",
        "structured_vs_narrative": "structured",
        "proactive_vs_reactive": "proactive",
        "decisive_vs_caveated": "caveated",
    }


def _read_communication_preferences(settings) -> dict[str, str]:
    defaults = _default_communication_preferences()
    preferences_path = _communication_preferences_path(settings)
    if not preferences_path.exists():
        return defaults
    payload = json.loads(preferences_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return defaults
    return {
        key: str(payload.get(key) or default_value)
        for key, default_value in defaults.items()
    }


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _serialize_proposal(
    proposal: SelfEditProposal,
    *,
    include_patch: bool,
) -> dict[str, Any]:
    payload = proposal.model_dump(mode="json")
    payload["change_count"] = len(proposal.changes)
    if include_patch:
        patch_path = Path(proposal.patch_path).expanduser().resolve(strict=False)
        payload["patch_text"] = patch_path.read_text(encoding="utf-8") if patch_path.exists() else ""
    return payload


async def _fetch_forge_runs(
    *,
    settings,
    limit: int,
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        base_url=settings.forge_base_url.rstrip("/"),
        timeout=settings.forge_request_timeout_sec,
    ) as client:
        try:
            response = await client.get("/v1/runs", params={"limit": limit})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError("forge service unavailable") from exc
    payload = response.json()
    runs = payload.get("runs", [])
    return [item for item in runs if isinstance(item, dict)]


async def _fetch_forge_run(
    *,
    settings,
    run_id: str,
) -> dict[str, Any]:
    safe_run_id = _forge_path_segment(run_id, field_name="run_id")
    async with httpx.AsyncClient(
        base_url=settings.forge_base_url.rstrip("/"),
        timeout=settings.forge_request_timeout_sec,
    ) as client:
        response = await client.get(f"/v1/runs/{safe_run_id}")
        response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("forge run response was not a JSON object")
    return payload


async def _fetch_forge_artifacts(
    *,
    settings,
    run_id: str,
) -> list[dict[str, Any]]:
    safe_run_id = _forge_path_segment(run_id, field_name="run_id")
    async with httpx.AsyncClient(
        base_url=settings.forge_base_url.rstrip("/"),
        timeout=settings.forge_request_timeout_sec,
    ) as client:
        response = await client.get(f"/v1/runs/{safe_run_id}/artifacts")
        response.raise_for_status()
    payload = response.json()
    artifacts = payload.get("artifacts", [])
    return [item for item in artifacts if isinstance(item, dict)]


async def _fetch_forge_artifact_content(
    *,
    settings,
    run_id: str,
    artifact_id: str,
) -> bytes:
    safe_run_id = _forge_path_segment(run_id, field_name="run_id")
    safe_artifact_id = _forge_path_segment(artifact_id, field_name="artifact_id")
    async with httpx.AsyncClient(
        base_url=settings.forge_base_url.rstrip("/"),
        timeout=settings.forge_request_timeout_sec,
    ) as client:
        response = await client.get(
            f"/v1/runs/{safe_run_id}/artifacts/{safe_artifact_id}/content"
        )
        response.raise_for_status()
    return response.content


async def _publish_forge_promotion(
    *,
    settings,
    run_id: str,
) -> dict[str, Any]:
    safe_run_id = _forge_path_segment(run_id, field_name="run_id")
    async with httpx.AsyncClient(
        base_url=settings.forge_base_url.rstrip("/"),
        timeout=settings.forge_request_timeout_sec,
    ) as client:
        try:
            response = await client.post(
                f"/v1/runs/{safe_run_id}/promotion/publish"
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                raise
            raise RuntimeError("forge service unavailable") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("forge publish response was not a JSON object")
    return payload
