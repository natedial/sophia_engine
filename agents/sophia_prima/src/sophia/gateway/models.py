"""Typed gateway models for normalized inbound/outbound messages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InboundMessage:
    """Channel-agnostic inbound message envelope."""

    channel: str
    account_id: str
    peer_id: str
    text: str
    user_id: str | None = None
    message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryArtifact:
    """One outbound attachment created by presentation policy."""

    artifact_id: str
    kind: str
    mime_type: str
    path: str
    caption: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    """Gateway response envelope produced after agent execution."""

    text: str
    session_id: str
    agent_id: str
    channel: str
    account_id: str
    peer_id: str
    run_id: str | None = None
    artifacts: tuple[DeliveryArtifact, ...] = ()
    delivery_mode: str = "text"
