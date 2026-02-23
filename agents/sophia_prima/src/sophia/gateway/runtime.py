"""Gateway runtime: routing + session state + agent execution."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC

from pylon import Pylon, PylonConfig

from sophia.agent import SophiaAgent
from sophia.config import Settings, get_settings
from sophia.context import ConversationContext
from sophia.gateway.models import InboundMessage, OutboundMessage
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
        self._provider: ModelProvider | None = None
        self._pylon: Pylon | None = None
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
            agent = SophiaAgent(
                provider=provider,
                settings=self.settings,
                pylon=pylon,
                preflight_result=await pylon.preflight(),
            )
            self._provider = provider
            self._pylon = pylon
            self._agents[self.settings.gateway_default_agent_id] = agent
            logger.info(
                "Gateway runtime ready: default_agent_id=%s",
                self.settings.gateway_default_agent_id,
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
        self._sessions.clear()
        self._started = False

    async def handle_inbound(self, message: InboundMessage) -> OutboundMessage:
        """Route and execute a channel message against an agent session."""
        text = message.text.strip()
        if not text:
            raise ValueError("message text cannot be empty")

        decision = self.router.resolve(message)
        session = self._sessions.get(decision.session_id)
        if session is None:
            session = SessionState(context=ConversationContext(session_id=decision.session_id))
            self._sessions[decision.session_id] = session

        session.last_message_at = datetime.now(UTC)

        if self._startup_error:
            fallback = (
                "Sophia gateway is not fully configured yet. "
                f"Startup error: {self._startup_error}"
            )
            return OutboundMessage(
                text=fallback,
                session_id=decision.session_id,
                agent_id=decision.agent_id,
                channel=message.channel,
                account_id=message.account_id,
                peer_id=message.peer_id,
            )

        agent = self._agents.get(decision.agent_id)
        if agent is None:
            raise RuntimeError(f"no agent registered for id '{decision.agent_id}'")

        async with session.lock:
            assistant = await agent.chat(text, session.context)

        return OutboundMessage(
            text=assistant.content.strip() or "(empty response)",
            session_id=decision.session_id,
            agent_id=decision.agent_id,
            channel=message.channel,
            account_id=message.account_id,
            peer_id=message.peer_id,
        )

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
            )
        if provider_name == "groq":
            if not self.settings.groq_api_key:
                raise ValueError("GROQ_API_KEY is required for gateway operation")
            from sophia.llm.groq_provider import GroqProvider
            return GroqProvider(
                api_key=self.settings.groq_api_key,
                base_url=self.settings.groq_base_url,
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
        )
        pylon = Pylon(config)
        # Prime health state before serving traffic.
        await pylon.preflight()
        return pylon
