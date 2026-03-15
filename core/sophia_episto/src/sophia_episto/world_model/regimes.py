"""Macro regime definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Regime:
    regime_id: str
    name: str
    state_variables: tuple[str, ...]


def core_regimes() -> tuple[Regime, ...]:
    return (
        Regime("disinflation", "Disinflation", ("growth", "inflation", "policy")),
        Regime("reacceleration", "Reacceleration", ("growth", "labor", "inflation")),
        Regime("late_cycle_slowdown", "Late Cycle Slowdown", ("growth", "labor", "policy")),
    )
