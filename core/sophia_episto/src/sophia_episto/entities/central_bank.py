"""Central bank entity implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum
from typing import Any

from sophia_episto.entities.base import ActorType, EconomicAgent


class CentralBankType(str, Enum):
    """Types of central banks."""

    FED = "fed"
    ECB = "ecb"
    BOJ = "boj"
    BOE = "boe"
    SNB = "snb"
    OTHER = "other"


@dataclass
class CentralBank(EconomicAgent):
    """Central bank economic agent.

    Extends EconomicAgent with central bank specific properties:
    - mandate: primary policy objective
    - policy_function: description of policy reaction
    - meeting_schedule: meeting cadence
    """

    central_bank_type: CentralBankType = CentralBankType.OTHER
    mandate: str = ""
    policy_function: str = ""
    meeting_schedule: str = ""
    meeting_time: time | None = None
    base_rate: float | None = None

    def __post_init__(self) -> None:
        if not self.actor_type:
            self.actor_type = ActorType.CENTRAL_BANK


def g3_central_banks() -> list[CentralBank]:
    """Return the G3 central banks (Fed, ECB, BOJ)."""
    return [
        CentralBank(
            id="fed",
            name="Federal Reserve",
            central_bank_type=CentralBankType.FED,
            mandate="Maximum employment and price stability",
            policy_function="Dual mandate with inflation targeting, reacts to labor and inflation",
            meeting_schedule="8 per year (~6 weeks apart)",
            meeting_time=time(14, 0),
            properties={
                "jurisdiction": "United States",
                "currency": "USD",
                "region": "North America",
            },
        ),
        CentralBank(
            id="ecb",
            name="European Central Bank",
            central_bank_type=CentralBankType.ECB,
            mandate="Price stability, inflation target of 2%",
            policy_function="Inflation targeting, focuses on HICP inflation",
            meeting_schedule="~6 weeks apart",
            meeting_time=time(12, 45),
            properties={
                "jurisdiction": "Euro Area",
                "currency": "EUR",
                "region": "Europe",
            },
        ),
        CentralBank(
            id="boj",
            name="Bank of Japan",
            central_bank_type=CentralBankType.BOJ,
            mandate="Price stability, achieve 2% inflation",
            policy_function="Yield curve control, aggressive monetary easing",
            meeting_schedule="Monthly",
            meeting_time=time(8, 50),
            properties={
                "jurisdiction": "Japan",
                "currency": "JPY",
                "region": "Asia",
            },
        ),
    ]
