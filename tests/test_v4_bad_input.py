import pytest

from portfolio_monitor.domain.issues import IssueCode, Severity
from portfolio_monitor.domain.portfolio import TradeStatus
from portfolio_monitor.domain.value_objects import Symbol
from tests.conftest import (
    D,
    EXAMPLE_PRICES,
    EXAMPLE_TRADES,
    PRICE_HEADER,
    TRADE_HEADER,
    make_service,
    money,
    prices_csv,
    trades_csv,
)


def codes(svc):
    return [i.code for i in svc.issues()]


def test_full_brief_example_including_duplicate():
    svc = make_service()
    summary = svc.upload_trades("example_trades.csv", EXAMPLE_TRADES)
    svc.upload_prices("example_prices.csv", EXAMPLE_PRICES)
    assert (summary.rows, summary.accepted, summary.duplicates, summary.rejected) == (5, 4, 1, 0)
    (dup,) = svc.issues()
    assert dup.code is IssueCode.DUPLICATE_IGNORED and dup.severity is Severity.INFO
    assert dup.source.row_no == 6
    v = svc.valuation()
    assert (v.cash, v.total_market_value, v.total_portfolio_value) == (8410, 1850, 10260)
    assert money(v.realized_pnl) == D("133.33")
    assert [str(o.trade.trade_id) for o in svc.trade_history()] == ["T001", "T002", "T003", "T004"]
    assert all(o.status is TradeStatus.APPLIED for o in svc.trade_history())


def test_reuploading_same_files_is_idempotent():
    svc = make_service(EXAMPLE_TRADES, EXAMPLE_PRICES)
    before = (svc.valuation(), svc.trade_history())
    trades = svc.upload_trades("example_trades.csv", EXAMPLE_TRADES)
    prices = svc.upload_prices("example_prices.csv", EXAMPLE_PRICES)
    assert (svc.valuation(), svc.trade_history()) == before
    assert (trades.accepted, trades.duplicates) == (0, 5)
    assert (prices.accepted, prices.duplicates) == (0, 4)


def test_conflicting_trade_id_is_rejected_and_first_version_kept():
    svc = make_service(trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,10,100"))
    summary = svc.upload_trades("fix.csv", trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,9,100"))
    assert summary.rejected == 1
    (conflict,) = svc.issues()
    assert conflict.code is IssueCode.TRADE_ID_CONFLICT
    assert "quantity 10 vs 9" in conflict.message
    assert svc.portfolio.position(Symbol("AAPL")).quantity == 10


def test_conflict_within_same_file_first_row_wins():
    svc = make_service(
        trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,10,100", "T1,2026-10-02T09:00:00,AAPL,SELL,10,100")
    )
    assert codes(svc) == [IssueCode.TRADE_ID_CONFLICT]
    assert svc.portfolio.position(Symbol("AAPL")).quantity == 10


@pytest.mark.parametrize(
    "row, code",
    [
        ("T1,2026-10-02T09:00:00,AAPL,HOLD,1,100", IssueCode.INVALID_SIDE),
        ("T1,2026-10-02T09:00:00,AAPL,BUY,-3,100", IssueCode.NON_POSITIVE),
        ("T1,2026-10-02T09:00:00,AAPL,BUY,0,100", IssueCode.NON_POSITIVE),
        ("T1,2026-10-02T09:00:00,AAPL,BUY,1,0", IssueCode.NON_POSITIVE),
        ("T1,2026-10-02T09:00:00,AAPL,BUY,0.123456789,100", IssueCode.TOO_MANY_DECIMALS),
        ("T1,2026-10-02T09:00:00,AAPL,BUY,1,1.1234567", IssueCode.TOO_MANY_DECIMALS),
        ("T1,2026-10-02T09:00:00,AAPL,BUY,ten,100", IssueCode.INVALID_NUMBER),
        ("T1,yesterday,AAPL,BUY,1,100", IssueCode.INVALID_TIMESTAMP),
        ("T1,2026-10-02T09:00:00,,BUY,1,100", IssueCode.MISSING_FIELD),
        (",2026-10-02T09:00:00,AAPL,BUY,1,100", IssueCode.MISSING_FIELD),
        ("T1,2026-10-02T09:00:00,AAPL,BUY", IssueCode.MISSING_FIELD),  # short row
    ],
)
def test_invalid_trade_rows_are_reported_with_row_number(row, code):
    svc = make_service(trades_csv(row))
    (issue,) = svc.issues()
    assert issue.code is code
    assert issue.source.row_no == 2
    assert issue.raw is not None
    assert svc.trade_history() == ()


def test_all_problems_in_a_row_are_reported_together():
    svc = make_service(trades_csv("T1,bad,AAPL,HOLD,-1,100"))
    (issue,) = svc.issues()
    message = issue.message.lower()
    assert "timestamp" in message and "side" in message and "quantity" in message


def test_partially_invalid_file_still_processes_valid_rows():
    summary = (svc := make_service()).upload_trades(
        "mixed.csv",
        trades_csv(
            "T1,2026-10-02T09:00:00,AAPL,BUY,10,100",
            "T2,2026-10-02T09:00:00,AAPL,HOLD,10,100",
            "T3,2026-10-02T09:05:00,MSFT,BUY,1,200",
        ),
    )
    assert (summary.rows, summary.accepted, summary.rejected) == (3, 2, 1)
    assert [i.source.row_no for i in svc.issues()] == [3]
    assert svc.portfolio.cash == 10000 - 1000 - 200


def test_malformed_row_does_not_claim_trade_id():
    svc = make_service(trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,-1,100"))
    summary = svc.upload_trades("fixed.csv", trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,1,100"))
    assert summary.accepted == 1


def test_wrong_file_type_is_rejected_as_a_whole():
    svc = make_service()
    summary = svc.upload_trades("example_prices.csv", EXAMPLE_PRICES)
    assert summary.file_error and "trade_id" in summary.file_error
    (issue,) = svc.issues()
    assert issue.code is IssueCode.MISSING_COLUMNS and issue.source.row_no is None
    assert svc.trade_history() == ()


@pytest.mark.parametrize(
    "content, code",
    [
        ("", IssueCode.EMPTY_FILE),
        ("   \n", IssueCode.EMPTY_FILE),
        (TRADE_HEADER, IssueCode.EMPTY_FILE),
        (b"\xff\xfe\x00garbage", IssueCode.UNREADABLE),
    ],
)
def test_unusable_files(content, code):
    svc = make_service()
    svc.upload_trades("bad.csv", content)
    assert codes(svc) == [code]


def test_header_variations_are_tolerated():
    svc = make_service(
        "﻿Price, Symbol ,Quantity,Side,Timestamp,Trade_ID,notes\n100,aapl,1,buy,2026-10-02T09:00:00,T1,hello\n\n"
    )
    assert svc.issues() == []
    assert svc.portfolio.position(Symbol("AAPL")).quantity == 1


def test_price_duplicates_and_conflicts():
    svc = make_service(prices=prices_csv("2026-10-02T12:00:00,MSFT,195"))
    summary = svc.upload_prices(
        "more.csv", prices_csv("2026-10-02T12:00:00,MSFT,195", "2026-10-02T12:00:00,MSFT,196", "2026-10-02T13:00:00,MSFT,x")
    )
    assert (summary.accepted, summary.duplicates, summary.rejected) == (0, 1, 2)
    assert codes(svc) == [IssueCode.DUPLICATE_IGNORED, IssueCode.PRICE_CONFLICT, IssueCode.INVALID_NUMBER]
    assert svc.price_book.latest(Symbol("MSFT")).price.value == 195


def test_portfolio_rule_rejections_appear_as_issues_and_in_upload_log():
    svc = make_service(trades_csv("T1,2026-10-02T09:00:00,AAPL,SELL,1,100"))
    (issue,) = svc.issues()
    assert issue.code is IssueCode.INSUFFICIENT_POSITION
    assert svc.uploads()[0].rule_rejections == 1


def test_price_file_header_only():
    svc = make_service()
    summary = svc.upload_prices("p.csv", PRICE_HEADER)
    assert summary.file_error == "File has a header but no data rows."
