"""PortfolioService: the application service. Single entry point for commands and read models."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import replace
from decimal import Decimal

from portfolio_monitor.application.commands import (
    Command,
    InitializePortfolio,
    RecordPriceBatch,
    RecordTradeBatch,
)
from portfolio_monitor.application.input_log import InputLog, LogEntry
from portfolio_monitor.application.ledger import Ledger, UploadSummary
from portfolio_monitor.application.timeline import DEFAULT_SNAPSHOT_INTERVAL, Timeline
from portfolio_monitor.domain.issues import Issue
from portfolio_monitor.domain.portfolio import Portfolio, TradeOutcome, TradeStatus
from portfolio_monitor.domain.price_book import PriceBook
from portfolio_monitor.domain.valuation import Valuation, value_portfolio
from portfolio_monitor.domain.value_objects import parse_cash
from portfolio_monitor.ingestion.csv_adapter import parse_price_csv, parse_trade_csv


class PortfolioService:
    def __init__(self, snapshot_interval: int = DEFAULT_SNAPSHOT_INTERVAL) -> None:
        self.log = InputLog()
        self._ledger = Ledger()
        self._timeline = Timeline(Decimal(0), snapshot_interval)
        self._status_changes: list[Issue] = []

    @classmethod
    def replicate(
        cls, entries: Iterable[LogEntry], snapshot_interval: int = DEFAULT_SNAPSHOT_INTERVAL
    ) -> PortfolioService:
        """Build a replica (or recover after a crash) by applying a log. Same log => same state."""
        replica = cls(snapshot_interval)
        replica.catch_up(entries)
        return replica

    def catch_up(self, entries: Iterable[LogEntry]) -> None:
        for entry in entries:
            self._execute(entry.command)

    # ---- commands -------------------------------------------------------------------

    def initialize(self, initial_cash: str | Decimal) -> None:
        self._execute(InitializePortfolio(parse_cash(initial_cash)))

    def upload_trades(self, file_name: str, content: bytes | str) -> UploadSummary:
        self._execute(parse_trade_csv(self.log.next_upload_no(), file_name, content))
        return self.uploads()[-1]

    def upload_prices(self, file_name: str, content: bytes | str) -> UploadSummary:
        self._execute(parse_price_csv(self.log.next_upload_no(), file_name, content))
        return self.uploads()[-1]

    def _execute(self, command: Command) -> None:
        self.apply(self.log.append(command))

    def apply(self, entry: LogEntry) -> None:
        """The state-machine transition for one log entry. Used live and by replicas."""
        match entry.command:
            case InitializePortfolio(initial_cash=cash):
                changes = self._timeline.reset_initial_cash(cash, f"initial cash changed to {cash:,.2f}")
                self._status_changes.extend(changes)
            case RecordTradeBatch() as batch:
                accepted = self._ledger.record_trades(batch)
                cause = f"upload #{batch.upload_no} ({batch.file_name}) added trades with earlier timestamps"
                self._status_changes.extend(self._timeline.insert(accepted, cause))
            case RecordPriceBatch() as batch:
                self._ledger.record_prices(batch)

    # ---- read models ----------------------------------------------------------------

    @property
    def portfolio(self) -> Portfolio:
        return self._timeline.state

    @property
    def price_book(self) -> PriceBook:
        return self._ledger.price_book

    def valuation(self) -> Valuation:
        return value_portfolio(self.portfolio, self.price_book)

    def trade_history(self) -> tuple[TradeOutcome, ...]:
        """Every accepted trade in timestamp order, with its outcome under the portfolio rules."""
        return self._timeline.outcomes

    def issues(self) -> list[Issue]:
        """Ingestion issues (as recorded) plus current portfolio-rule rejections (derived by replay)."""
        rule_rejections = [
            Issue(o.trade.source, o.reason_code, f"{o.trade.trade_id} ({o.trade.describe()}) rejected: {o.reason}.")
            for o in self.trade_history()
            if o.status is TradeStatus.REJECTED
        ]
        issues = [*self._ledger.issues, *self._status_changes, *rule_rejections]
        return sorted(issues, key=lambda i: (i.source.upload_no, i.source.row_no or 0))

    def uploads(self) -> list[UploadSummary]:
        """Upload log. Trades rejected by portfolio rules are counted as they stand *now*."""
        rejected_now: dict[int, int] = {}
        for o in self.trade_history():
            if o.status is TradeStatus.REJECTED:
                rejected_now[o.trade.source.upload_no] = rejected_now.get(o.trade.source.upload_no, 0) + 1
        return [replace(u, rule_rejections=rejected_now.get(u.upload_no, 0)) for u in self._ledger.uploads]

    def fingerprint(self) -> str:
        """Digest of all derived state. Replicas that applied the same log must agree on it."""
        state = (self.portfolio, self.trade_history(), self.price_book.observations(), self.issues(), self.uploads())
        return hashlib.sha256(repr(state).encode()).hexdigest()
