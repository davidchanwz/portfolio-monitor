"""Commands: the only way state changes. Every command is appended to the input log first.

Ingestion (the anti-corruption layer) has already turned CSV rows into domain objects and
format issues, so a command fully describes its effect and replaying the log needs no files.
"""

from __future__ import annotations

from dataclasses import dataclass

from portfolio_monitor.domain.issues import Issue
from portfolio_monitor.domain.price_book import PriceObservation
from portfolio_monitor.domain.trade import Trade
from portfolio_monitor.domain.value_objects import Money


@dataclass(frozen=True)
class InitializePortfolio:
    initial_cash: Money


@dataclass(frozen=True)
class RecordTradeBatch:
    upload_no: int
    file_name: str
    row_count: int
    trades: tuple[Trade, ...]
    issues: tuple[Issue, ...]  # rows (or the whole file) that failed format validation


@dataclass(frozen=True)
class RecordPriceBatch:
    upload_no: int
    file_name: str
    row_count: int
    observations: tuple[PriceObservation, ...]
    issues: tuple[Issue, ...]


Command = InitializePortfolio | RecordTradeBatch | RecordPriceBatch
BATCH_COMMANDS = (RecordTradeBatch, RecordPriceBatch)
