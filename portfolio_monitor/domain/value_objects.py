"""Value objects: immutable, self-validating domain primitives.

An invalid value object cannot be constructed, so format validation lives here and
the rest of the domain can trust its inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation
from enum import Enum
from typing import ClassVar
from zoneinfo import ZoneInfo

from portfolio_monitor.domain.issues import IssueCode

# One fixed arithmetic context for every calculation, so every replica computes
# bit-identical results regardless of thread-local decimal settings.
DECIMAL_CTX = Context(prec=34, rounding=ROUND_HALF_EVEN)
ZERO = Decimal(0)
SGT = ZoneInfo("Asia/Singapore")

# Monetary amounts are plain Decimals evaluated in DECIMAL_CTX (all USD).
Money = Decimal


class DomainError(ValueError):
    def __init__(self, code: IssueCode, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def parse_decimal(raw: str | None, field: str) -> Decimal:
    text = (raw or "").strip()
    if not text:
        raise DomainError(IssueCode.MISSING_FIELD, f"{field} is missing")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise DomainError(IssueCode.INVALID_NUMBER, f"{field} '{text}' is not a number") from None
    if not value.is_finite():
        raise DomainError(IssueCode.INVALID_NUMBER, f"{field} '{text}' is not a finite number")
    return value


def parse_cash(raw: str | Decimal) -> Money:
    value = raw if isinstance(raw, Decimal) else parse_decimal(raw, "initial cash")
    if not value.is_finite():
        raise DomainError(IssueCode.INVALID_NUMBER, "initial cash must be a finite number")
    if value < 0:
        raise DomainError(IssueCode.NON_POSITIVE, f"initial cash must not be negative (got {value})")
    return value


def decimal_places(value: Decimal) -> int:
    """Significant decimal places, ignoring trailing zeros (exact; no rounding)."""
    _, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    while exponent < 0 and len(digits) > 1 and digits[-1] == 0:
        digits, exponent = digits[:-1], exponent + 1
    return max(0, -exponent)


def _require_positive(value: Decimal, field: str, max_dp: int) -> None:
    if value <= 0:
        raise DomainError(IssueCode.NON_POSITIVE, f"{field} must be greater than zero (got {value})")
    if decimal_places(value) > max_dp:
        raise DomainError(IssueCode.TOO_MANY_DECIMALS, f"{field} {value} has more than {max_dp} decimal places")


@dataclass(frozen=True, order=True)
class Quantity:
    """Units traded: > 0, at most 8 decimal places."""

    value: Decimal

    MAX_DP: ClassVar[int] = 8

    def __post_init__(self) -> None:
        _require_positive(self.value, "quantity", self.MAX_DP)

    @classmethod
    def parse(cls, raw: str | None) -> Quantity:
        return cls(parse_decimal(raw, "quantity"))

    def __str__(self) -> str:
        return f"{self.value:f}"


@dataclass(frozen=True, order=True)
class Price:
    """Price per unit in USD: > 0, at most 6 decimal places."""

    value: Decimal

    MAX_DP: ClassVar[int] = 6

    def __post_init__(self) -> None:
        _require_positive(self.value, "price", self.MAX_DP)

    @classmethod
    def parse(cls, raw: str | None) -> Price:
        return cls(parse_decimal(raw, "price"))

    def __str__(self) -> str:
        return f"{self.value:f}"


@dataclass(frozen=True, order=True)
class Symbol:
    """Instrument identifier, normalized to trimmed upper case."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().upper()
        if not normalized:
            raise DomainError(IssueCode.MISSING_FIELD, "symbol is missing")
        object.__setattr__(self, "value", normalized)

    @classmethod
    def parse(cls, raw: str | None) -> Symbol:
        return cls(raw or "")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True)
class TradeId:
    """Identifier from the source system (trimmed; case-sensitive)."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise DomainError(IssueCode.MISSING_FIELD, "trade_id is missing")
        object.__setattr__(self, "value", normalized)

    @classmethod
    def parse(cls, raw: str | None) -> TradeId:
        return cls(raw or "")

    def __str__(self) -> str:
        return self.value


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @classmethod
    def parse(cls, raw: str | None) -> Side:
        text = (raw or "").strip()
        if not text:
            raise DomainError(IssueCode.MISSING_FIELD, "side is missing")
        try:
            return cls(text.upper())
        except ValueError:
            raise DomainError(IssueCode.INVALID_SIDE, f"side '{text}' must be BUY or SELL") from None

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, order=True)
class Timestamp:
    """A point in time. Inputs without an offset are Singapore time."""

    value: datetime

    def __post_init__(self) -> None:
        if self.value.tzinfo is None:
            object.__setattr__(self, "value", self.value.replace(tzinfo=SGT))
        else:
            object.__setattr__(self, "value", self.value.astimezone(SGT))

    @classmethod
    def parse(cls, raw: str | None) -> Timestamp:
        text = (raw or "").strip()
        if not text:
            raise DomainError(IssueCode.MISSING_FIELD, "timestamp is missing")
        try:
            return cls(datetime.fromisoformat(text))
        except ValueError:
            raise DomainError(
                IssueCode.INVALID_TIMESTAMP,
                f"timestamp '{text}' is not a valid ISO 8601 date-time (e.g. 2026-10-02T09:00:00)",
            ) from None

    def __str__(self) -> str:
        return self.value.strftime("%Y-%m-%d %H:%M:%S")
