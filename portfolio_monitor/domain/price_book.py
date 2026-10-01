"""Market Data context: price observations and the latest price per symbol."""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_monitor.domain.issues import Issue, IssueCode, Source
from portfolio_monitor.domain.value_objects import Price, Symbol, Timestamp


@dataclass(frozen=True)
class PriceObservation:
    timestamp: Timestamp
    symbol: Symbol
    price: Price
    source: Source


class PriceBook:
    """Aggregate keyed by (symbol, timestamp). Latest = greatest timestamp, regardless of arrival order."""

    def __init__(self) -> None:
        self._observations: dict[tuple[Symbol, Timestamp], PriceObservation] = {}
        self._latest: dict[Symbol, PriceObservation] = {}

    def record(self, observation: PriceObservation) -> Issue | None:
        key = (observation.symbol, observation.timestamp)
        existing = self._observations.get(key)
        if existing is not None:
            what = f"Price for {observation.symbol} at {observation.timestamp}"
            if existing.price == observation.price:
                return Issue(
                    observation.source,
                    IssueCode.DUPLICATE_IGNORED,
                    f"{what} was already recorded from {existing.source}; identical observation ignored.",
                )
            return Issue(
                observation.source,
                IssueCode.PRICE_CONFLICT,
                f"{what} was already recorded as {existing.price} from {existing.source}; this row says "
                f"{observation.price}. Kept the first; this row was NOT applied.",
            )
        self._observations[key] = observation
        latest = self._latest.get(observation.symbol)
        if latest is None or observation.timestamp > latest.timestamp:
            self._latest[observation.symbol] = observation
        return None

    def latest(self, symbol: Symbol) -> PriceObservation | None:
        return self._latest.get(symbol)

    def latest_all(self) -> list[PriceObservation]:
        return sorted(self._latest.values(), key=lambda o: o.symbol)

    def observations(self) -> list[PriceObservation]:
        return sorted(self._observations.values(), key=lambda o: (o.symbol, o.timestamp))
