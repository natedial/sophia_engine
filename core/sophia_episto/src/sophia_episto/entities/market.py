"""Market entity implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sophia_episto.entities.base import ActorType, EconomicAgent


class AssetClass(str, Enum):
    """Asset class types."""

    FIXED_INCOME = "fixed_income"
    EQUITY = "equity"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    CREDIT = "credit"
    DERIVATIVE = "derivative"


@dataclass
class Market(EconomicAgent):
    """Market entity representing an asset class or market segment.

    Extends EconomicAgent with market specific properties:
    - asset_classes: list of asset classes in this market
    - current_state: description of current market conditions
    """

    asset_classes: list[AssetClass] = field(default_factory=list)
    current_state: str = ""

    def __post_init__(self) -> None:
        if not self.actor_type:
            self.actor_type = ActorType.MARKET


def core_markets() -> list[Market]:
    """Return core market entities for the causal model."""
    return [
        Market(
            id="us_treasury",
            name="US Treasury Market",
            asset_classes=[AssetClass.FIXED_INCOME],
            current_state="",
            properties={
                "region": "United States",
                "currency": "USD",
            },
        ),
        Market(
            id="euro_bond",
            name="Euro Sovereign Bond Market",
            asset_classes=[AssetClass.FIXED_INCOME],
            current_state="",
            properties={
                "region": "Euro Area",
                "currency": "EUR",
            },
        ),
        Market(
            id="jgb",
            name="Japanese Government Bond Market",
            asset_classes=[AssetClass.FIXED_INCOME],
            current_state="",
            properties={
                "region": "Japan",
                "currency": "JPY",
            },
        ),
        Market(
            id="us_equity",
            name="US Equity Market",
            asset_classes=[AssetClass.EQUITY],
            current_state="",
            properties={
                "region": "United States",
                "currency": "USD",
            },
        ),
        Market(
            id="fx_usd",
            name="USD Exchange Rate",
            asset_classes=[AssetClass.CURRENCY],
            current_state="",
            properties={
                "region": "Global",
            },
        ),
    ]
