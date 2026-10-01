"""Ledger: state machine over the input log in ARRIVAL order.

Owns identity: which trade_id / (symbol, timestamp) has been seen, so it decides what is a
duplicate (ignored) or a conflict (rejected). "First seen" means lowest log position.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_monitor.application.commands import RecordPriceBatch, RecordTradeBatch
from portfolio_monitor.domain.issues import Issue, IssueCode
from portfolio_monitor.domain.price_book import PriceBook
from portfolio_monitor.domain.trade import Trade
from portfolio_monitor.domain.value_objects import TradeId

_TRADE_FIELDS = ("timestamp", "symbol", "side", "quantity", "price")


@dataclass(frozen=True)
class UploadSummary:
    upload_no: int
    file_name: str
    kind: str  # "trades" | "prices"
    rows: int
    accepted: int
    duplicates: int
    rejected: int
    file_error: str | None = None
    rule_rejections: int = 0  # accepted trades currently rejected by portfolio rules (filled by the service)


class Ledger:
    def __init__(self) -> None:
        self._trades: dict[TradeId, Trade] = {}
        self.price_book = PriceBook()
        self._issues: list[Issue] = []
        self._uploads: list[UploadSummary] = []

    def record_trades(self, batch: RecordTradeBatch) -> list[Trade]:
        """Returns the newly accepted trades (to be placed on the timeline)."""
        issues = list(batch.issues)
        accepted: list[Trade] = []
        for trade in batch.trades:
            existing = self._trades.get(trade.trade_id)
            if existing is None:
                self._trades[trade.trade_id] = trade
                accepted.append(trade)
            elif existing.details == trade.details:
                issues.append(
                    Issue(
                        trade.source,
                        IssueCode.DUPLICATE_IGNORED,
                        f"{trade.trade_id} was already processed from {existing.source}; identical record ignored.",
                    )
                )
            else:
                issues.append(Issue(trade.source, IssueCode.TRADE_ID_CONFLICT, _conflict_message(existing, trade)))
        self._finish(batch, "trades", len(accepted), issues)
        return accepted

    def record_prices(self, batch: RecordPriceBatch) -> None:
        issues = list(batch.issues)
        accepted = 0
        for observation in batch.observations:
            issue = self.price_book.record(observation)
            if issue is None:
                accepted += 1
            else:
                issues.append(issue)
        self._finish(batch, "prices", accepted, issues)

    def _finish(self, batch: RecordTradeBatch | RecordPriceBatch, kind: str, accepted: int, issues: list[Issue]) -> None:
        self._issues.extend(issues)
        duplicates = sum(i.code is IssueCode.DUPLICATE_IGNORED for i in issues)
        file_error = next((i.message for i in issues if i.source.row_no is None), None)
        self._uploads.append(
            UploadSummary(
                upload_no=batch.upload_no,
                file_name=batch.file_name,
                kind=kind,
                rows=batch.row_count,
                accepted=accepted,
                duplicates=duplicates,
                rejected=batch.row_count - accepted - duplicates,
                file_error=file_error,
            )
        )

    @property
    def issues(self) -> tuple[Issue, ...]:
        return tuple(self._issues)

    @property
    def uploads(self) -> tuple[UploadSummary, ...]:
        return tuple(self._uploads)


def _conflict_message(existing: Trade, trade: Trade) -> str:
    differences = ", ".join(
        f"{name} {getattr(existing, name)} vs {getattr(trade, name)}"
        for name in _TRADE_FIELDS
        if getattr(existing, name) != getattr(trade, name)
    )
    return (
        f"{trade.trade_id} was already processed from {existing.source} with different details "
        f"({differences}). Kept the first version; this row was NOT applied. "
        f"If this is a correction, amendments are not supported; if it is a different trade, give it a new trade_id."
    )
