"""Hypothesis generation and lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class HypothesisStatus(str, Enum):
    """Lifecycle status for hypotheses."""

    PROPOSED = "proposed"
    TESTING = "testing"
    VALIDATED = "validated"
    REJECTED = "rejected"


@dataclass
class Hypothesis:
    """A testable hypothesis about causal relationships.

    Represents a proposed causal relationship that can be tested
    through model runs or data analysis.
    """

    id: str
    description: str
    source: str
    target: str
    mechanism: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    evidence: dict[str, Any] = field(default_factory=dict)
    test_results: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def validate(self) -> bool:
        """Check if hypothesis has sufficient evidence to be tested."""
        return (
            self.source
            and self.target
            and self.mechanism
            and self.status == HypothesisStatus.PROPOSED
        )

    def mark_testing(self) -> None:
        """Mark hypothesis as being tested."""
        self.status = HypothesisStatus.TESTING
        self.updated_at = datetime.now(UTC)

    def mark_validated(self, evidence: dict[str, Any]) -> None:
        """Mark hypothesis as validated with evidence."""
        self.status = HypothesisStatus.VALIDATED
        self.evidence.update(evidence)
        self.confidence = 1.0
        self.updated_at = datetime.now(UTC)

    def mark_rejected(self, reason: str) -> None:
        """Mark hypothesis as rejected."""
        self.status = HypothesisStatus.REJECTED
        self.evidence["rejection_reason"] = reason
        self.confidence = 0.0
        self.updated_at = datetime.now(UTC)

    def add_test_result(self, result: dict[str, Any]) -> None:
        """Add a test result to the hypothesis."""
        self.test_results.append(result)
        self.updated_at = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "source": self.source,
            "target": self.target,
            "mechanism": self.mechanism,
            "status": self.status.value,
            "evidence": self.evidence,
            "test_results": self.test_results,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hypothesis:
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            description=data["description"],
            source=data["source"],
            target=data["target"],
            mechanism=data["mechanism"],
            status=HypothesisStatus(data["status"]),
            evidence=data.get("evidence", {}),
            test_results=data.get("test_results", []),
            confidence=data.get("confidence", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


class HypothesisGenerator:
    """Generates hypotheses from patterns in data and literature."""

    def __init__(self) -> None:
        self.hypotheses: dict[str, Hypothesis] = {}

    def generate_from_discovered_edge(
        self,
        edge_id: str,
        source: str,
        target: str,
        strength: float,
        mechanism: str,
    ) -> Hypothesis:
        """Generate a hypothesis from a discovered causal edge."""
        hypothesis = Hypothesis(
            id=f"hypothesis-{edge_id}",
            description=f"Discovered causal relationship: {source} → {target}",
            source=source,
            target=target,
            mechanism=mechanism,
            evidence={"discovered_strength": strength},
            confidence=strength,
        )
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    def generate_from_pattern(
        self,
        pattern: str,
        variables: list[str],
    ) -> Hypothesis | None:
        """Generate a hypothesis from an observed pattern.

        Example patterns:
        - "inflation_spike": High inflation without policy response
        - "policy_lag": Policy change followed by delayed effect
        - "divergence": Two related series diverging unexpectedly
        """
        if (
            pattern == "inflation_spike"
            and "inflation" in variables
            and "policy" in variables
        ):
            return self._generate_inflation_policy_hypothesis(variables)
        elif (
            pattern == "policy_lag" and "policy" in variables and "growth" in variables
        ):
            return self._generate_policy_lag_hypothesis(variables)

        return None

    def _generate_inflation_policy_hypothesis(self, variables: list[str]) -> Hypothesis:
        """Generate hypothesis about inflation-policy relationship."""
        hypothesis = Hypothesis(
            id=f"hypothesis-inflation-policy-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            description="Inflation is rising faster than policy responds",
            source="inflation",
            target="policy",
            mechanism="Central bank reaction function may be delayed or asymmetric",
            evidence={"pattern": "inflation_spike"},
        )
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    def _generate_policy_lag_hypothesis(self, variables: list[str]) -> Hypothesis:
        """Generate hypothesis about policy transmission lag."""
        hypothesis = Hypothesis(
            id=f"hypothesis-policy-lag-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            description="Policy changes are not fully reflected in growth within expected timeframe",
            source="policy",
            target="growth",
            mechanism="Monetary policy transmission may be longer than typical",
            evidence={"pattern": "policy_lag"},
        )
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    def generate_from_literature(
        self,
        citation: str,
        claim: str,
        source: str,
        target: str,
    ) -> Hypothesis:
        """Generate a hypothesis from academic literature or research."""
        hypothesis = Hypothesis(
            id=f"hypothesis-literature-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            description=claim,
            source=source,
            target=target,
            mechanism=f"From literature: {citation}",
            evidence={"citation": citation, "source": "literature"},
        )
        self.hypotheses[hypothesis.id] = hypothesis
        return hypothesis

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        """Get a hypothesis by ID."""
        return self.hypotheses.get(hypothesis_id)

    def get_hypotheses_by_status(self, status: HypothesisStatus) -> list[Hypothesis]:
        """Get all hypotheses with a specific status."""
        return [h for h in self.hypotheses.values() if h.status == status]

    def list_hypotheses(self) -> list[Hypothesis]:
        """List all hypotheses."""
        return list(self.hypotheses.values())
