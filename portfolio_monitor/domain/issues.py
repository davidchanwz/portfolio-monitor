"""Issues: the record of every input that could not be (fully) processed, and why."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    ERROR = "ERROR"
    INFO = "INFO"


class IssueCode(str, Enum):
    # File level: the whole file is rejected.
    MISSING_COLUMNS = "MISSING_COLUMNS"
    EMPTY_FILE = "EMPTY_FILE"
    UNREADABLE = "UNREADABLE"
    # Row level: format validation (value objects).
    MISSING_FIELD = "MISSING_FIELD"
    INVALID_NUMBER = "INVALID_NUMBER"
    NON_POSITIVE = "NON_POSITIVE"
    TOO_MANY_DECIMALS = "TOO_MANY_DECIMALS"
    INVALID_SIDE = "INVALID_SIDE"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    # Row level: identity (ledger / price book).
    TRADE_ID_CONFLICT = "TRADE_ID_CONFLICT"
    PRICE_CONFLICT = "PRICE_CONFLICT"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    # Portfolio rules (derived by replay; can change when late trades arrive).
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    INSUFFICIENT_CASH = "INSUFFICIENT_CASH"
    TRADE_STATUS_CHANGED = "TRADE_STATUS_CHANGED"

    @property
    def severity(self) -> Severity:
        if self in (IssueCode.DUPLICATE_IGNORED, IssueCode.TRADE_STATUS_CHANGED):
            return Severity.INFO
        return Severity.ERROR


@dataclass(frozen=True)
class Source:
    """Where an input came from. (upload_no, row_no) is its arrival sequence."""

    upload_no: int
    file_name: str
    row_no: int | None = None  # spreadsheet row number (header = row 1); None for file-level

    def __str__(self) -> str:
        row = f" row {self.row_no}" if self.row_no is not None else ""
        return f"{self.file_name}{row} (upload #{self.upload_no})"


@dataclass(frozen=True)
class Issue:
    source: Source
    code: IssueCode
    message: str
    raw: Mapping[str, str | None] | None = field(default=None, compare=False)

    @property
    def severity(self) -> Severity:
        return self.code.severity
