from datetime import datetime

import pytest

from portfolio_monitor.domain.issues import IssueCode
from portfolio_monitor.domain.value_objects import (
    SGT,
    DomainError,
    Price,
    Quantity,
    Side,
    Symbol,
    Timestamp,
    TradeId,
    decimal_places,
)
from tests.conftest import D


@pytest.mark.parametrize(
    "parse, raw, code",
    [
        (Quantity.parse, "", IssueCode.MISSING_FIELD),
        (Quantity.parse, None, IssueCode.MISSING_FIELD),
        (Quantity.parse, "ten", IssueCode.INVALID_NUMBER),
        (Quantity.parse, "Infinity", IssueCode.INVALID_NUMBER),
        (Quantity.parse, "0", IssueCode.NON_POSITIVE),
        (Quantity.parse, "-5", IssueCode.NON_POSITIVE),
        (Quantity.parse, "0.123456789", IssueCode.TOO_MANY_DECIMALS),
        (Price.parse, "1.1234567", IssueCode.TOO_MANY_DECIMALS),
        (Price.parse, "-1", IssueCode.NON_POSITIVE),
        (Side.parse, "HOLD", IssueCode.INVALID_SIDE),
        (Side.parse, " ", IssueCode.MISSING_FIELD),
        (Symbol.parse, "  ", IssueCode.MISSING_FIELD),
        (TradeId.parse, "", IssueCode.MISSING_FIELD),
        (Timestamp.parse, "not-a-date", IssueCode.INVALID_TIMESTAMP),
        (Timestamp.parse, "2026-13-02T09:00:00", IssueCode.INVALID_TIMESTAMP),
    ],
)
def test_invalid_values_cannot_be_constructed(parse, raw, code):
    with pytest.raises(DomainError) as e:
        parse(raw)
    assert e.value.code is code


def test_precision_limits_ignore_trailing_zeros():
    assert Quantity.parse("0.12345678").value == D("0.12345678")
    assert Quantity.parse("100.000000000000").value == 100
    assert Price.parse("1.123456").value == D("1.123456")
    assert decimal_places(D("1.50")) == 1
    assert decimal_places(D("1E+2")) == 0


def test_normalization():
    assert Symbol.parse(" aapl ") == Symbol("AAPL")
    assert Side.parse("sell") is Side.SELL
    assert TradeId.parse(" T001 ") == TradeId("T001")


def test_naive_timestamps_are_singapore_time():
    ts = Timestamp.parse("2026-10-02T09:00:00")
    assert ts.value == datetime(2026, 10, 2, 9, 0, tzinfo=SGT)
    assert Timestamp.parse("2026-10-02T01:00:00+00:00") == ts
