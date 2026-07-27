"""Deterministic first-match routing for channel ingress."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sophia.gateway.models import InboundMessage


@dataclass(frozen=True)
class BindingRule:
    """A deterministic routing rule for channel ingress."""

    channel: str
    account_id: str | None = None
    peer_id: str | None = None
    agent_id: str = "sophia_prima"
    session_id: str | None = None

    def matches(self, message: InboundMessage) -> bool:
        """Return True when this rule matches the inbound message."""
        if self.channel != message.channel:
            return False
        if self.account_id is not None and self.account_id != message.account_id:
            return False
        if self.peer_id is not None and self.peer_id != message.peer_id:
            return False
        return True


@dataclass(frozen=True)
class RouteDecision:
    """Selected target for a normalized inbound message."""

    agent_id: str
    session_id: str


class GatewayRouter:
    """First-match router with deterministic fallback semantics."""

    def __init__(
        self,
        *,
        bindings: list[BindingRule] | None = None,
        default_agent_id: str = "sophia_prima",
    ) -> None:
        self.bindings = bindings or []
        self.default_agent_id = default_agent_id

    @classmethod
    def from_json(
        cls,
        raw: str,
        *,
        default_agent_id: str = "sophia_prima",
    ) -> "GatewayRouter":
        """Create a router from JSON-encoded binding definitions."""
        if not raw.strip():
            return cls(default_agent_id=default_agent_id)

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise ValueError("gateway bindings JSON must be a list")

        bindings: list[BindingRule] = []
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise ValueError(f"gateway binding at index {i} must be an object")
            bindings.append(
                BindingRule(
                    channel=str(item["channel"]),
                    account_id=_optional_str(item.get("account_id")),
                    peer_id=_optional_str(item.get("peer_id")),
                    agent_id=str(item.get("agent_id") or default_agent_id),
                    session_id=_optional_str(item.get("session_id")),
                )
            )

        return cls(bindings=bindings, default_agent_id=default_agent_id)

    def resolve(self, message: InboundMessage) -> RouteDecision:
        """Resolve an inbound message to (agent_id, session_id)."""
        for rule in self.bindings:
            if not rule.matches(message):
                continue
            session_id = self._session_id_from_rule(rule, message)
            return RouteDecision(agent_id=rule.agent_id, session_id=session_id)

        return RouteDecision(
            agent_id=self.default_agent_id,
            session_id=self._default_session_id(message),
        )

    @staticmethod
    def _default_session_id(message: InboundMessage) -> str:
        return f"{message.channel}:{message.account_id}:{message.peer_id}"

    @staticmethod
    def _session_id_from_rule(rule: BindingRule, message: InboundMessage) -> str:
        template = rule.session_id
        if not template:
            return GatewayRouter._default_session_id(message)
        return template.format(
            channel=message.channel,
            account_id=message.account_id,
            peer_id=message.peer_id,
            user_id=message.user_id or "",
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
