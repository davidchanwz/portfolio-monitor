"""Valuation context: marks the portfolio to the latest market prices.

A position with no observed price is still listed, but its market value and unrealized
P&L are None ("unavailable") and the valuation is flagged incomplete. Missing is never zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import reduce

from portfolio_monitor.domain.portfolio import Portfolio
from portfolio_monitor.domain.price_book import PriceBook, PriceObservation
from portfolio_monitor.domain.value_objects import DECIMAL_CTX, ZERO, Money, Symbol


@dataclass(frozen=True)
class PositionValuation:
    symbol: Symbol
    quantity: Decimal
    avg_cost: Money
    total_cost: Money
    realized_pnl: Money
    latest: PriceObservation | None
    market_value: Money | None
    unrealized_pnl: Money | None

    @property
    def is_priced(self) -> bool:
        return self.latest is not None


@dataclass(frozen=True)
class Valuation:
    cash: Money
    positions: tuple[PositionValuation, ...]
    total_market_value: Money  # priced positions only; see is_complete
    total_portfolio_value: Money
    realized_pnl: Money
    unrealized_pnl: Money  # priced positions only; see is_complete
    unpriced_symbols: tuple[Symbol, ...]

    @property
    def is_complete(self) -> bool:
        return not self.unpriced_symbols


def value_portfolio(portfolio: Portfolio, prices: PriceBook) -> Valuation:
    ctx = DECIMAL_CTX
    rows: list[PositionValuation] = []
    for position in sorted((p for p in portfolio.positions.values() if p.is_open), key=lambda p: p.symbol):
        latest = prices.latest(position.symbol)
        market_value = unrealized = None
        if latest is not None:
            market_value = ctx.multiply(position.quantity, latest.price.value)
            unrealized = ctx.subtract(market_value, position.total_cost)
        rows.append(
            PositionValuation(
                symbol=position.symbol,
                quantity=position.quantity,
                avg_cost=position.avg_cost,
                total_cost=position.total_cost,
                realized_pnl=position.realized_pnl,
                latest=latest,
                market_value=market_value,
                unrealized_pnl=unrealized,
            )
        )
    priced = [r for r in rows if r.is_priced]
    total_market_value = reduce(ctx.add, (r.market_value for r in priced), ZERO)
    return Valuation(
        cash=portfolio.cash,
        positions=tuple(rows),
        total_market_value=total_market_value,
        total_portfolio_value=ctx.add(portfolio.cash, total_market_value),
        realized_pnl=portfolio.realized_pnl,
        unrealized_pnl=reduce(ctx.add, (r.unrealized_pnl for r in priced), ZERO),
        unpriced_symbols=tuple(r.symbol for r in rows if not r.is_priced),
    )
