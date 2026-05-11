"""Causal edge implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CausalEdge:
    """Represents a causal relationship between two nodes in the causal graph.

    This is an independent type that can reference a Relationship by key
    (source_concept, target_concept), rather than inheriting from it.
    This keeps the Relationship type frozen as a semantic skeleton while
    allowing CausalEdge to have probabilistic properties.

    Attributes:
        source: Source node ID (concept or actor)
        target: Target node ID (concept or actor)
        relationship_key: Optional reference to a frozen Relationship
        probability: P(effect | cause) - Bayesian posterior probability
        confidence: Expert prior confidence in this relationship
        strength: Empirical strength from data (0-1)
        mechanism: Description of the transmission channel
        conditions: Regime-dependent modifiers
        regime_dependent: Whether the relationship varies by regime
    """

    source: str
    target: str
    relationship_key: tuple[str, str] | None = None
    probability: float = 0.5
    confidence: float = 0.0
    strength: float = 0.0
    p_value: float | None = None
    mechanism: str = ""
    conditions: dict[str, Any] = field(default_factory=dict)
    regime_dependent: bool = False

    def __hash__(self) -> int:
        return hash((self.source, self.target))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CausalEdge):
            return NotImplemented
        return self.source == other.source and self.target == other.target

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON persistence."""
        return {
            "source": self.source,
            "target": self.target,
            "relationship_key": self.relationship_key,
            "probability": self.probability,
            "confidence": self.confidence,
            "strength": self.strength,
            "p_value": self.p_value,
            "mechanism": self.mechanism,
            "conditions": self.conditions,
            "regime_dependent": self.regime_dependent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CausalEdge:
        """Deserialize from dictionary."""
        return cls(
            source=data["source"],
            target=data["target"],
            relationship_key=tuple(data["relationship_key"])
            if data.get("relationship_key")
            else None,
            probability=data.get("probability", 0.5),
            confidence=data.get("confidence", 0.0),
            strength=data.get("strength", 0.0),
            p_value=data.get("p_value"),
            mechanism=data.get("mechanism", ""),
            conditions=data.get("conditions", {}),
            regime_dependent=data.get("regime_dependent", False),
        )


def expert_priors() -> list[CausalEdge]:
    """Return expert-defined prior causal edges for G3 central bank relationships.

    These represent initial beliefs about causal relationships before
    data-driven learning.
    """
    return [
        CausalEdge(
            source="inflation",
            target="policy",
            relationship_key=("inflation", "policy"),
            probability=0.7,
            confidence=0.8,
            strength=0.0,
            mechanism="Central banks react to inflation deviations from target",
            regime_dependent=True,
            conditions={"regime": "high_inflation"},
        ),
        CausalEdge(
            source="labor",
            target="inflation",
            relationship_key=("labor", "inflation"),
            probability=0.6,
            confidence=0.7,
            strength=0.0,
            mechanism="Tighter labor markets support wage pressure",
            regime_dependent=True,
            conditions={"regime": "tight_labor"},
        ),
        CausalEdge(
            source="growth",
            target="labor",
            relationship_key=("growth", "labor"),
            probability=0.7,
            confidence=0.8,
            strength=0.0,
            mechanism="Growth resilience supports labor demand",
            regime_dependent=False,
        ),
        CausalEdge(
            source="supply",
            target="policy",
            relationship_key=("supply", "policy"),
            probability=0.5,
            confidence=0.6,
            strength=0.0,
            mechanism="Treasury issuance affects term premium and policy transmission",
            regime_dependent=True,
            conditions={"regime": "quantitative_tightening"},
        ),
        CausalEdge(
            source="policy",
            target="growth",
            relationship_key=("policy", "growth"),
            probability=0.6,
            confidence=0.7,
            strength=0.0,
            mechanism="Monetary policy affects borrowing costs and aggregate demand",
            regime_dependent=True,
            conditions={"regime": "tightening"},
        ),
        CausalEdge(
            source="policy",
            target="positioning",
            relationship_key=("policy", "positioning"),
            probability=0.7,
            confidence=0.6,
            strength=0.0,
            mechanism="Policy changes affect investor positioning and flows",
            regime_dependent=False,
        ),
    ]
