"""Anti-corruption layer: CSV files -> domain commands.

This is the only module that knows about CSV. Each row either becomes a domain object
(by constructing self-validating value objects) or an Issue naming the row and the problem.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import TypeVar

from portfolio_monitor.application.commands import RecordPriceBatch, RecordTradeBatch
from portfolio_monitor.domain.issues import Issue, IssueCode, Source
from portfolio_monitor.domain.price_book import PriceObservation
from portfolio_monitor.domain.trade import Trade
from portfolio_monitor.domain.value_objects import (
    DomainError,
    Price,
    Quantity,
    Side,
    Symbol,
    Timestamp,
    TradeId,
)

TRADE_COLUMNS = ("trade_id", "timestamp", "symbol", "side", "quantity", "price")
PRICE_COLUMNS = ("timestamp", "symbol", "price")

Row = dict[str, str | None]
T = TypeVar("T")


def parse_trade_csv(upload_no: int, file_name: str, content: bytes | str) -> RecordTradeBatch:
    rows, file_issue = _read_rows(content, TRADE_COLUMNS, Source(upload_no, file_name))
    trades: list[Trade] = []
    issues: list[Issue] = [file_issue] if file_issue else []
    for row_no, row in rows:
        source = Source(upload_no, file_name, row_no)
        try:
            trades.append(_to_trade(row, source))
        except _RowErrors as e:
            issues.append(e.to_issue(source, row))
    return RecordTradeBatch(upload_no, file_name, len(rows), tuple(trades), tuple(issues))


def parse_price_csv(upload_no: int, file_name: str, content: bytes | str) -> RecordPriceBatch:
    rows, file_issue = _read_rows(content, PRICE_COLUMNS, Source(upload_no, file_name))
    observations: list[PriceObservation] = []
    issues: list[Issue] = [file_issue] if file_issue else []
    for row_no, row in rows:
        source = Source(upload_no, file_name, row_no)
        try:
            observations.append(_to_price(row, source))
        except _RowErrors as e:
            issues.append(e.to_issue(source, row))
    return RecordPriceBatch(upload_no, file_name, len(rows), tuple(observations), tuple(issues))


# ---- row parsing ------------------------------------------------------------------------


class _RowErrors(Exception):
    def __init__(self, errors: list[DomainError]):
        self.errors = errors

    def to_issue(self, source: Source, row: Row) -> Issue:
        message = "; ".join(e.message for e in self.errors)
        return Issue(source, self.errors[0].code, message[0].upper() + message[1:], raw=row)


class _FieldCollector:
    """Parses every field so the user sees all problems with a row at once."""

    def __init__(self, row: Row) -> None:
        self.row = row
        self.errors: list[DomainError] = []

    def __call__(self, parse: Callable[[str | None], T], column: str) -> T:
        try:
            return parse(self.row.get(column))
        except DomainError as e:
            self.errors.append(e)
            return None  # type: ignore[return-value]

    def raise_if_errors(self) -> None:
        if self.errors:
            raise _RowErrors(self.errors)


def _to_trade(row: Row, source: Source) -> Trade:
    field = _FieldCollector(row)
    trade = dict(
        trade_id=field(TradeId.parse, "trade_id"),
        timestamp=field(Timestamp.parse, "timestamp"),
        symbol=field(Symbol.parse, "symbol"),
        side=field(Side.parse, "side"),
        quantity=field(Quantity.parse, "quantity"),
        price=field(Price.parse, "price"),
    )
    field.raise_if_errors()
    return Trade(**trade, source=source)


def _to_price(row: Row, source: Source) -> PriceObservation:
    field = _FieldCollector(row)
    observation = dict(
        timestamp=field(Timestamp.parse, "timestamp"),
        symbol=field(Symbol.parse, "symbol"),
        price=field(Price.parse, "price"),
    )
    field.raise_if_errors()
    return PriceObservation(**observation, source=source)


# ---- file reading -----------------------------------------------------------------------


def _read_rows(
    content: bytes | str, required: tuple[str, ...], source: Source
) -> tuple[list[tuple[int, Row]], Issue | None]:
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return [], Issue(source, IssueCode.UNREADABLE, "File is not UTF-8 text. Is it a CSV file?")
    text = content.lstrip("﻿")
    if not text.strip():
        return [], Issue(source, IssueCode.EMPTY_FILE, "File is empty.")
    try:
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        names = [h.strip().lower() for h in header]
        missing = [c for c in required if c not in names]
        if missing:
            return [], Issue(
                source,
                IssueCode.MISSING_COLUMNS,
                f"Missing required column(s): {', '.join(missing)}. "
                f"Expected: {', '.join(required)}. Found: {', '.join(header)}. Whole file rejected.",
            )
        rows: list[tuple[int, Row]] = []
        for row_no, values in enumerate(reader, start=2):  # header is spreadsheet row 1
            if not any(v.strip() for v in values):
                continue  # blank line
            rows.append((row_no, {name: values[i] if i < len(values) else None for i, name in enumerate(names)}))
    except csv.Error as e:
        return [], Issue(source, IssueCode.UNREADABLE, f"Could not parse CSV: {e}. Whole file rejected.")
    if not rows:
        return [], Issue(source, IssueCode.EMPTY_FILE, "File has a header but no data rows.")
    return rows, None
