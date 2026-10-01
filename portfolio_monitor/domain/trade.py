"""Trade: an execution reported by the source system."""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_monitor.domain.issues import Source
from portfolio_monitor.domain.value_objects import (
    DECIMAL_CTX,
    Money,
    Price,
    Quantity,
    Side,
    Symbol,
    Timestamp,
    TradeId,
)

TimelineKey = tuple[Timestamp, int, int]


@dataclass(frozen=True)
class Trade:
    trade_id: TradeId
    timestamp: Timestamp
    symbol: Symbol
    side: Side
    quantity: Quantity
    price: Price
    source: Source

    @property
    def details(self) -> tuple:
        """Everything except identity and provenance: two records with equal details are the same trade."""
        return (self.timestamp, self.symbol, self.side, self.quantity, self.price)

    @property
    def timeline_key(self) -> TimelineKey:
        """Business order: timestamp, then arrival (upload #, row #) as a deterministic tie-break."""
        return (self.timestamp, self.source.upload_no, self.source.row_no or 0)

    @property
    def notional(self) -> Money:
        return DECIMAL_CTX.multiply(self.quantity.value, self.price.value)

    def describe(self) -> str:
        return f"{self.side.value} {self.quantity} {self.symbol} @ {self.price} at {self.timestamp}"
