"""Core economic concepts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Concept:
    concept_id: str
    name: str
    description: str


def core_concepts() -> tuple[Concept, ...]:
    return (
        Concept("growth", "Growth", "Aggregate economic growth and resilience"),
        Concept("labor", "Labor", "Employment, slack, wages, and labor demand"),
        Concept("inflation", "Inflation", "Price pressure and inflation persistence"),
        Concept("policy", "Policy", "Monetary policy stance and reaction function"),
        Concept("supply", "Supply", "Treasury issuance and duration supply"),
        Concept("positioning", "Positioning", "Investor positioning and flow dynamics"),
    )
