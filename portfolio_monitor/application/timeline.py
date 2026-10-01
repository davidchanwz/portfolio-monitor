"""Timeline: accepted trades in business (timestamp) order, replayed through the Portfolio state machine.

Because Portfolio is immutable, a snapshot is just a reference to a past state. One is kept
before every `snapshot_interval`-th trade, so a late (back-dated) trade only replays the suffix
from the nearest snapshot at or before its position instead of the whole history.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Iterable, Sequence

from portfolio_monitor.domain.issues import Issue, IssueCode
from portfolio_monitor.domain.portfolio import Portfolio, TradeOutcome
from portfolio_monitor.domain.trade import Trade
from portfolio_monitor.domain.value_objects import Money

DEFAULT_SNAPSHOT_INTERVAL = 500


def replay(start: Portfolio, trades: Iterable[Trade]) -> tuple[Portfolio, list[TradeOutcome]]:
    """Pure fold of trades over the state machine. The reference definition of portfolio state."""
    state, outcomes = start, []
    for trade in trades:
        state, outcome = state.apply(trade)
        outcomes.append(outcome)
    return state, outcomes


def _key(trade: Trade):
    return trade.timeline_key


class Timeline:
    def __init__(self, initial_cash: Money, snapshot_interval: int = DEFAULT_SNAPSHOT_INTERVAL) -> None:
        if snapshot_interval < 1:
            raise ValueError("snapshot_interval must be >= 1")
        self._interval = snapshot_interval
        self._trades: list[Trade] = []
        self._outcomes: list[TradeOutcome] = []
        # _snapshots[k] is the portfolio state *before* trade k * interval.
        self._snapshots: list[Portfolio] = [Portfolio.open(initial_cash)]
        self._state = self._snapshots[0]
        self.last_replay_count = 0  # trades re-applied by the last change (observability / tests)

    def reset_initial_cash(self, initial_cash: Money, cause: str = "initial cash changed") -> list[Issue]:
        """Changing the starting point invalidates everything: replay from the beginning."""
        self._snapshots = [Portfolio.open(initial_cash)]
        return self._replay_from(0, cause)

    def insert(self, trades: Sequence[Trade], cause: str = "new trades arrived") -> list[Issue]:
        """Add newly accepted trades; returns TRADE_STATUS_CHANGED issues for earlier trades they affect."""
        if not trades:
            self.last_replay_count = 0
            return []
        new = sorted(trades, key=_key)
        # Everything before `earliest` is unaffected: same trades, same order, same outcomes.
        earliest = bisect_left(self._trades, _key(new[0]), key=_key)
        self._trades = sorted([*self._trades, *new], key=_key)  # Timsort merges the two runs in ~O(n)
        return self._replay_from(earliest, cause)

    def _replay_from(self, index: int, cause: str) -> list[Issue]:
        # Nearest snapshot at or before `index`. The boundary snapshot may not exist yet when
        # trades are appended exactly at it, so fall back to the last one taken.
        k = min(index // self._interval, len(self._snapshots) - 1)
        start = k * self._interval
        previous = {o.trade.trade_id: o for o in self._outcomes[start:]}
        del self._snapshots[k + 1 :]
        del self._outcomes[start:]

        state = self._snapshots[k]
        for i in range(start, len(self._trades)):
            if i % self._interval == 0 and i // self._interval == len(self._snapshots):
                self._snapshots.append(state)
            state, outcome = state.apply(self._trades[i])
            self._outcomes.append(outcome)
        self._state = state
        self.last_replay_count = len(self._trades) - start
        return self._status_changes(previous, self._outcomes[start:], cause)

    @staticmethod
    def _status_changes(previous: dict, outcomes: Sequence[TradeOutcome], cause: str) -> list[Issue]:
        changes = []
        for outcome in outcomes:
            before = previous.get(outcome.trade.trade_id)
            if before is None or before.status is outcome.status:
                continue
            why = f" ({outcome.reason})" if outcome.reason else ""
            changes.append(
                Issue(
                    outcome.trade.source,
                    IssueCode.TRADE_STATUS_CHANGED,
                    f"{outcome.trade.trade_id} ({outcome.trade.describe()}) changed from {before.status.value} "
                    f"to {outcome.status.value}{why}. Cause: {cause}.",
                )
            )
        return changes

    @property
    def state(self) -> Portfolio:
        return self._state

    @property
    def initial_state(self) -> Portfolio:
        return self._snapshots[0]

    @property
    def trades(self) -> tuple[Trade, ...]:
        return tuple(self._trades)

    @property
    def outcomes(self) -> tuple[TradeOutcome, ...]:
        return tuple(self._outcomes)

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)
