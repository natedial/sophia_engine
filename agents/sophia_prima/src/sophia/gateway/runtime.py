"""Gateway runtime: routing + session state + agent execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import AsyncGenerator
from uuid import uuid4

from pylon import Pylon, PylonConfig

from sophia.agent import SophiaAgent
from sophia.agent_profiles import AgentProfile
from sophia.config import Settings, get_settings
from sophia.context import ConversationContext
from sophia.events import AgentEvent, EventType
from sophia.gateway.acquisition import GatewayAcquisitionService
from sophia.gateway.agent_registry import load_agent_profiles
from sophia.gateway.models import InboundMessage, OutboundMessage
from sophia.gateway.research_plan_artifacts import (
    resolve_acquisition_decision,
    resolve_research_plan_event,
)
from sophia.gateway.run_store import GatewayRunStore
from sophia.gateway.routing import GatewayRouter
from sophia.llm.base import ModelProvider

logger = logging.getLogger("sophia.gateway.runtime")


@dataclass
class SessionState:
    """Conversation state stored per resolved session id."""

    context: ConversationContext
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_message_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class GatewayRuntime:
    """Owns route resolution and bounded agent execution."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        router: GatewayRouter | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.router = router or GatewayRouter.from_json(
            self.settings.gateway_bindings_json,
            default_agent_id=self.settings.gateway_default_agent_id,
        )
        self._sessions: dict[str, SessionState] = {}
        self._agents: dict[str, SophiaAgent] = {}
        self._agent_profiles: dict[str, AgentProfile] = {}
        self._provider: ModelProvider | None = None
        self._pylon: Pylon | None = None
        self._run_store: GatewayRunStore | None = None
        self._startup_error: str | None = None
        self._started = False

    @property
    def startup_error(self) -> str | None:
        return self._startup_error

    @property
    def is_ready(self) -> bool:
        return self._started and self._startup_error is None

    async def start(self) -> None:
        """Initialize provider, pylon, and default agent."""
        if self._started:
            return

        self._started = True
        try:
            provider = self._create_provider()
            pylon = await self._create_pylon()
            run_store = GatewayRunStore(self.settings.gateway_artifact_store_path)
            preflight = await pylon.preflight()
            profiles = load_agent_profiles(
                default_agent_id=self.settings.gateway_default_agent_id,
                raw_profiles_json=self.settings.gateway_agents_json,
            )
            agents: dict[str, SophiaAgent] = {}
            for agent_id, profile in profiles.items():
                agent_settings = self.settings.model_copy(
                    update={
                        "skills_enabled": (
                            self.settings.skills_enabled
                            if profile.skills_enabled is None
                            else profile.skills_enabled
                        ),
                        "subagents_enabled": (
                            self.settings.subagents_enabled
                            if profile.subagents_enabled is None
                            else profile.subagents_enabled
                        ),
                    }
                )
                agents[agent_id] = SophiaAgent(
                    provider=provider,
                    settings=agent_settings,
                    pylon=pylon,
                    preflight_result=preflight,
                    profile=profile,
                )
            self._provider = provider
            self._pylon = pylon
            self._run_store = run_store
            self._agent_profiles = profiles
            self._agents = agents
            logger.info(
                "Gateway runtime ready: default_agent_id=%s agents=%s",
                self.settings.gateway_default_agent_id,
                sorted(self._agents.keys()),
            )
        except Exception as exc:
            self._startup_error = str(exc)
            logger.exception("Gateway runtime startup failed: %s", exc)

    async def stop(self) -> None:
        """Shutdown providers/clients owned by this runtime."""
        if self._provider is not None:
            await self._provider.close()
            self._provider = None
        if self._pylon is not None:
            await self._pylon.close()
            self._pylon = None
        self._agents.clear()
        self._agent_profiles.clear()
        self._sessions.clear()
        self._run_store = None
        self._started = False

    async def handle_inbound(self, message: InboundMessage) -> OutboundMessage:
        """Route and execute a channel message against an agent session."""
        final_outbound: OutboundMessage | None = None
        async for item in self.stream_inbound(message):
            if isinstance(item, OutboundMessage):
                final_outbound = item
        if final_outbound is None:
            raise RuntimeError("gateway completed without outbound message")
        return final_outbound

    async def stream_inbound(
        self,
        message: InboundMessage,
    ) -> AsyncGenerator[AgentEvent | OutboundMessage, None]:
        """Run one inbound message while streaming agent events and final output."""
        text = message.text.strip()
        if not text:
            raise ValueError("message text cannot be empty")

        decision = self.router.resolve(message)
        session = self._sessions.get(decision.session_id)
        if session is None:
            session = SessionState(context=ConversationContext(session_id=decision.session_id))
            self._sessions[decision.session_id] = session

        session.last_message_at = datetime.now(UTC)
        run_id = str(uuid4())
        run_store = self._ensure_run_store()
        run_store.start_run(
            run_id=run_id,
            session_id=decision.session_id,
            agent_id=decision.agent_id,
            channel=message.channel,
            account_id=message.account_id,
            peer_id=message.peer_id,
            user_id=message.user_id,
            message_text=text,
        )
        logger.info(
            "gateway run started: run_id=%s channel=%s agent_id=%s session_id=%s text_len=%s",
            run_id,
            message.channel,
            decision.agent_id,
            decision.session_id,
            len(text),
        )

        if self._startup_error:
            fallback = (
                "Sophia gateway is not fully configured yet. "
                f"Startup error: {self._startup_error}"
            )
            outbound = OutboundMessage(
                text=fallback,
                session_id=decision.session_id,
                agent_id=decision.agent_id,
                channel=message.channel,
                account_id=message.account_id,
                peer_id=message.peer_id,
                run_id=run_id,
            )
            run_store.finish_run(
                run_id=run_id,
                status="completed",
                final_text=outbound.text,
                failure_stage="startup_guard",
            )
            yield outbound
            return

        agent = self._agents.get(decision.agent_id)
        if agent is None:
            run_store.finish_run(
                run_id=run_id,
                status="failed",
                error=f"no agent registered for id '{decision.agent_id}'",
                failure_stage="agent_resolution",
            )
            raise RuntimeError(f"no agent registered for id '{decision.agent_id}'")

        last_assistant_text = ""
        sequence = 0
        async with session.lock:
            try:
                logger.info(
                    "gateway agent execution starting: run_id=%s agent_id=%s",
                    run_id,
                    decision.agent_id,
                )
                agent_run = getattr(agent, "run", None)
                if callable(agent_run):
                    async for event in agent_run(text, session.context, run_id=run_id):
                        sequence += 1
                        run_store.append_event(run_id=run_id, sequence=sequence, event=event)
                        if (
                            event.type == EventType.MESSAGE_END
                            and event.data.get("message") is not None
                        ):
                            last_assistant_text = str(event.data["message"].content or "")
                        yield event
                else:
                    assistant = await agent.chat(text, session.context)
                    last_assistant_text = assistant.content
            except RuntimeError as exc:
                if _is_provider_capacity_error(exc):
                    logger.warning("Provider capacity/limit error: %s", exc)
                    run_store.update_run_diagnostics(
                        run_id=run_id,
                        failure_stage="provider_completion",
                        provider_name=self.settings.llm_provider,
                    )
                    retry_text = (
                        "I hit a temporary model capacity limit while processing that. "
                        "Please retry in a few seconds."
                    )
                    outbound = OutboundMessage(
                        text=retry_text,
                        session_id=decision.session_id,
                        agent_id=decision.agent_id,
                        channel=message.channel,
                        account_id=message.account_id,
                        peer_id=message.peer_id,
                        run_id=run_id,
                    )
                    run_store.finish_run(
                        run_id=run_id,
                        status="completed",
                        final_text=retry_text,
                        failure_stage="provider_completion",
                        provider_name=self.settings.llm_provider,
                    )
                    yield outbound
                    return
                logger.exception(
                    "gateway runtime error: run_id=%s stage=agent_runtime error=%s",
                    run_id,
                    exc,
                )
                run_store.finish_run(
                    run_id=run_id,
                    status="failed",
                    error=str(exc),
                    failure_stage="agent_runtime",
                    provider_name=self.settings.llm_provider,
                )
                raise
            except Exception as exc:
                logger.exception(
                    "gateway execution failed: run_id=%s stage=agent_execution error=%s",
                    run_id,
                    exc,
                )
                run_store.finish_run(
                    run_id=run_id,
                    status="failed",
                    error=str(exc),
                    failure_stage="agent_execution",
                    provider_name=self.settings.llm_provider,
                )
                raise

        run_store.update_run_diagnostics(
            run_id=run_id,
            outbound_text_len=len(last_assistant_text.strip() or "(empty response)"),
            provider_name=self.settings.llm_provider,
        )
        outbound = OutboundMessage(
            text=last_assistant_text.strip() or "(empty response)",
            session_id=decision.session_id,
            agent_id=decision.agent_id,
            channel=message.channel,
            account_id=message.account_id,
            peer_id=message.peer_id,
            run_id=run_id,
        )
        run_store.finish_run(
            run_id=run_id,
            status="completed",
            final_text=outbound.text,
            provider_name=self.settings.llm_provider,
        )
        logger.info(
            "gateway run completed: run_id=%s agent_id=%s outbound_len=%s",
            run_id,
            decision.agent_id,
            len(outbound.text),
        )
        yield outbound

    def get_run_record(self, run_id: str) -> dict[str, object] | None:
        """Return one persisted run record with events."""
        store = self._ensure_run_store()
        return store.get_run(run_id)

    def create_acquisition_job(
        self,
        *,
        indicator_family: str,
        run_id: str | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        playbook_id: str | None = None,
        requested_source: str | None = None,
        mode: str | None = None,
        rationale: str | None = None,
        retention_target: str | None = None,
    ) -> dict[str, object]:
        """Create a queued acquisition job, inferring fields from a persisted run when possible."""
        plan_event_data: dict[str, object] = {}
        if run_id is not None:
            record = self.get_run_record(run_id)
            if record is None:
                raise ValueError(f"run '{run_id}' not found")
            if session_id is None:
                raw_session_id = record.get("session_id")
                if isinstance(raw_session_id, str) and raw_session_id:
                    session_id = raw_session_id
            if agent_id is None:
                raw_agent_id = record.get("agent_id")
                if isinstance(raw_agent_id, str) and raw_agent_id:
                    agent_id = raw_agent_id
            plan_event_data = resolve_research_plan_event(record, indicator_family=indicator_family)
            if playbook_id is None:
                raw_playbook_id = plan_event_data.get("playbook_id")
                if isinstance(raw_playbook_id, str) and raw_playbook_id:
                    playbook_id = raw_playbook_id
            decision = resolve_acquisition_decision(
                plan_event_data,
                indicator_family=indicator_family,
            )
            if decision is not None:
                if requested_source is None:
                    raw_source = decision.get("source")
                    if isinstance(raw_source, str) and raw_source:
                        requested_source = raw_source
                if mode is None:
                    raw_mode = decision.get("mode")
                    if isinstance(raw_mode, str) and raw_mode:
                        mode = raw_mode
                if rationale is None:
                    raw_rationale = decision.get("rationale")
                    if isinstance(raw_rationale, str) and raw_rationale:
                        rationale = raw_rationale
                if retention_target is None:
                    raw_retention_target = decision.get("retention_target")
                    if isinstance(raw_retention_target, str) and raw_retention_target:
                        retention_target = raw_retention_target

        if session_id is None or not session_id.strip():
            raise ValueError("session_id is required to create an acquisition job")
        if agent_id is None or not agent_id.strip():
            raise ValueError("agent_id is required to create an acquisition job")
        if mode is None or not mode.strip():
            raise ValueError("mode is required to create an acquisition job")
        if rationale is None or not rationale.strip():
            raise ValueError("rationale is required to create an acquisition job")
        if retention_target is None or not retention_target.strip():
            raise ValueError("retention_target is required to create an acquisition job")

        store = self._ensure_run_store()
        return store.create_acquisition_job(
            run_id=run_id,
            session_id=session_id,
            agent_id=agent_id,
            playbook_id=playbook_id,
            indicator_family=indicator_family,
            requested_source=requested_source,
            mode=mode,
            rationale=rationale,
            retention_target=retention_target,
        )

    def get_acquisition_job(self, job_id: str) -> dict[str, object] | None:
        """Return one persisted acquisition job record."""
        store = self._ensure_run_store()
        return store.get_acquisition_job(job_id)

    async def execute_acquisition_job(
        self,
        *,
        job_id: str,
        observation_days: int = 365,
    ) -> dict[str, object]:
        """Execute one acquisition job against the available tool stack."""
        if self._pylon is None:
            raise RuntimeError("pylon is unavailable for acquisition execution")
        service = GatewayAcquisitionService(
            pylon=self._pylon,
            run_store=self._ensure_run_store(),
            lookup_run=self.get_run_record,
        )
        return await service.execute_job(
            job_id=job_id,
            observation_days=observation_days,
        )

    def list_agents(self) -> list[dict[str, object]]:
        """Return registered agent descriptors for UI/API discovery."""
        out: list[dict[str, object]] = []
        for agent_id, profile in sorted(self._agent_profiles.items()):
            out.append(
                {
                    "agent_id": agent_id,
                    "label": profile.label,
                    "description": profile.description,
                    "tool_allowlist": list(profile.tool_allowlist)
                    if profile.tool_allowlist is not None
                    else None,
                    "skills_enabled": (
                        self.settings.skills_enabled
                        if profile.skills_enabled is None
                        else profile.skills_enabled
                    ),
                    "subagents_enabled": (
                        self.settings.subagents_enabled
                        if profile.subagents_enabled is None
                        else profile.subagents_enabled
                    ),
                }
            )
        return out

    def clear_session(self, message: InboundMessage) -> bool:
        """Clear the resolved session for a given inbound envelope."""
        decision = self.router.resolve(message)
        return self._sessions.pop(decision.session_id, None) is not None

    def _create_provider(self) -> ModelProvider:
        provider_name = self.settings.llm_provider.lower().strip()
        if provider_name == "anthropic":
            if not self.settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is required for gateway operation")
            from sophia.llm.anthropic_provider import AnthropicProvider
            return AnthropicProvider(api_key=self.settings.anthropic_api_key)

        if provider_name == "openai":
            if not self.settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required for gateway operation")
            from sophia.llm.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=self.settings.openai_api_key,
                base_url=self.settings.openai_base_url,
                timeout=self.settings.llm_request_timeout_sec,
            )
        if provider_name == "groq":
            if not self.settings.groq_api_key:
                raise ValueError("GROQ_API_KEY is required for gateway operation")
            from sophia.llm.groq_provider import GroqProvider
            return GroqProvider(
                api_key=self.settings.groq_api_key,
                base_url=self.settings.groq_base_url,
                timeout=self.settings.llm_request_timeout_sec,
            )

        raise ValueError(
            f"unsupported llm_provider '{self.settings.llm_provider}', "
            "gateway currently supports: anthropic, openai, groq"
        )

    async def _create_pylon(self) -> Pylon:
        config = PylonConfig(
            scrivener_url=self.settings.scrivener_base_url,
            arithmos_url=self.settings.arithmos_base_url,
            canvas_url=self.settings.canvas_base_url,
            tholos_url=self.settings.tholos_base_url,
            fed_tracker_url=self.settings.fed_tracker_url,
            brave_base_url=self.settings.brave_base_url,
            brave_api_key=self.settings.brave_api_key,
        )
        pylon = Pylon(config)
        # Prime health state before serving traffic.
        await pylon.preflight()
        return pylon

    def _ensure_run_store(self) -> GatewayRunStore:
        if self._run_store is None:
            self._run_store = GatewayRunStore(self.settings.gateway_artifact_store_path)
        return self._run_store


def _is_provider_capacity_error(exc: RuntimeError) -> bool:
    text = str(exc).lower()
    return (
        "groq api error http 413" in text
        or "groq api error http 429" in text
        or "openai api error http 429" in text
        or "openai api timeout" in text
        or "groq api timeout" in text
        or "readtimeout" in text
        or "timed out" in text
        or "insufficient_quota" in text
        or "billing_hard_limit_reached" in text
        or "requests per day (rpd)" in text
        or "tokens per minute (tpm)" in text
        or "requests per minute (rpm)" in text
        or "rate_limit_exceeded" in text
        or "request too large" in text
        or "rate limit reached" in text
    )
