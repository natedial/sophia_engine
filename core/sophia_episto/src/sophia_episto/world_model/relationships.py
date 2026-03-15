"""Core relationship edges between concepts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Relationship:
    source_concept: str
    relation: str
    target_concept: str
    note: str = ""


def core_relationships() -> tuple[Relationship, ...]:
    return (
        Relationship("growth", "confirms", "labor", "Growth resilience often supports labor demand."),
        Relationship("labor", "feeds", "inflation", "Tighter labor can support wage pressure."),
        Relationship("policy", "reacts_to", "inflation", "Policy often responds asymmetrically to inflation."),
        Relationship("supply", "influences", "policy", "Supply can affect term premium and policy transmission."),
    )
