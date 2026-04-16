"""Base economic agent and actor types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActorType(str, Enum):
    """Types of economic actors."""

    CENTRAL_BANK = "central_bank"
    CORPORATION = "corporation"
    GOVERNMENT = "government"
    MARKET = "market"
    INVESTOR = "investor"


@dataclass
class EconomicAgent:
    """Base class for all economic actors.

    Represents any entity that can take actions or be influenced in the
    causal economic model.
    """

    id: str
    name: str
    actor_type: ActorType | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EconomicAgent):
            return NotImplemented
        return self.id == other.id


@dataclass
class ActorConceptEdge:
    """Edge from an actor to a concept they influence or are influenced by.

    Example: Fed → influences → policy
    """

    source_id: str
    target_concept: str
    relationship: str
    description: str = ""


@dataclass
class ActorActorEdge:
    """Edge between two actors.

    Example: Treasury → issues_to → Market
    """

    source_id: str
    target_id: str
    relationship: str
    description: str = ""
