"""Portfolio aggregate: the core state machine.

Portfolio is immutable. `apply(trade)` is a pure transition returning the next state and
the trade's outcome, which is what makes snapshots free and replay deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from enum import Enum

from portfolio_monitor.domain.issues import IssueCode
from portfolio_monitor.domain.trade import Trade
from portfolio_monitor.domain.value_objects import DECIMAL_CTX, ZERO, Money, Side, Symbol


class TradeStatus(str, Enum):
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Position:
    symbol: Symbol
    quantity: Decimal = ZERO
    total_cost: Money = ZERO  # cost basis of the units still held
    realized_pnl: Money = ZERO

    @property
    def avg_cost(self) -> Money | None:
        if self.quantity == 0:
            return None
        return DECIMAL_CTX.divide(self.total_cost, self.quantity)

    @property
    def is_open(self) -> bool:
        return self.quantity > 0


@dataclass(frozen=True)
class TradeOutcome:
    trade: Trade
    status: TradeStatus
    cash_after: Money
    position_after: Decimal
    realized_pnl: Money = ZERO  # realized by this trade alone
    reason_code: IssueCode | None = None
    reason: str | None = None


@dataclass(frozen=True)
class Portfolio:
    initial_cash: Money
    cash: Money
    realized_pnl: Money = ZERO
    positions: Mapping[Symbol, Position] = field(default_factory=dict)  # never mutated; copied on change

    @classmethod
    def open(cls, initial_cash: Money) -> Portfolio:
        return cls(initial_cash=initial_cash, cash=initial_cash)

    def position(self, symbol: Symbol) -> Position:
        return self.positions.get(symbol) or Position(symbol)

    def apply(self, trade: Trade) -> tuple[Portfolio, TradeOutcome]:
        if trade.side is Side.BUY:
            return self._buy(trade)
        return self._sell(trade)

    # ---- transitions ----------------------------------------------------------------

    def _buy(self, trade: Trade) -> tuple[Portfolio, TradeOutcome]:
        position = self.position(trade.symbol)
        cost = trade.notional
        if cost > self.cash:
            return self._reject(
                trade,
                IssueCode.INSUFFICIENT_CASH,
                f"costs {_show(cost)} but only {_show(self.cash)} cash is available at that time (no margin)",
            )
        new_position = replace(
            position,
            quantity=DECIMAL_CTX.add(position.quantity, trade.quantity.value),
            total_cost=DECIMAL_CTX.add(position.total_cost, cost),
        )
        next_state = self._with(new_position, cash=DECIMAL_CTX.subtract(self.cash, cost))
        return next_state, TradeOutcome(trade, TradeStatus.APPLIED, next_state.cash, new_position.quantity)

    def _sell(self, trade: Trade) -> tuple[Portfolio, TradeOutcome]:
        position = self.position(trade.symbol)
        quantity = trade.quantity.value
        if quantity > position.quantity:
            return self._reject(
                trade,
                IssueCode.INSUFFICIENT_POSITION,
                f"sells {_show(quantity)} but only {_show(position.quantity)} held at that time (short selling not allowed)",
            )
        remaining = DECIMAL_CTX.subtract(position.quantity, quantity)
        if remaining == 0:
            # Closing out: release the whole cost basis so the average resets with no rounding residue.
            cost_released = position.total_cost
        else:
            cost_released = DECIMAL_CTX.multiply(quantity, position.avg_cost)
        proceeds = trade.notional
        realized = DECIMAL_CTX.subtract(proceeds, cost_released)
        new_position = replace(
            position,
            quantity=remaining,
            total_cost=DECIMAL_CTX.subtract(position.total_cost, cost_released),
            realized_pnl=DECIMAL_CTX.add(position.realized_pnl, realized),
        )
        next_state = self._with(
            new_position,
            cash=DECIMAL_CTX.add(self.cash, proceeds),
            realized_pnl=DECIMAL_CTX.add(self.realized_pnl, realized),
        )
        return next_state, TradeOutcome(trade, TradeStatus.APPLIED, next_state.cash, remaining, realized)

    # ---- helpers --------------------------------------------------------------------

    def _with(self, position: Position, *, cash: Money, realized_pnl: Money | None = None) -> Portfolio:
        positions = dict(self.positions)
        positions[position.symbol] = position
        return replace(
            self,
            cash=cash,
            positions=positions,
            realized_pnl=self.realized_pnl if realized_pnl is None else realized_pnl,
        )

    def _reject(self, trade: Trade, code: IssueCode, reason: str) -> tuple[Portfolio, TradeOutcome]:
        outcome = TradeOutcome(
            trade,
            TradeStatus.REJECTED,
            cash_after=self.cash,
            position_after=self.position(trade.symbol).quantity,
            reason_code=code,
            reason=reason,
        )
        return self, outcome


def _show(value: Decimal) -> str:
    """Exact value without trailing zeros, for messages."""
    return f"{value.normalize(DECIMAL_CTX):,f}"
