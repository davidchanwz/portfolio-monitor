import random

from portfolio_monitor.domain.issues import IssueCode
from portfolio_monitor.domain.portfolio import TradeStatus
from portfolio_monitor.domain.value_objects import Symbol
from tests.conftest import D, make_service, trades_csv

AAPL = Symbol("AAPL")


def test_buys_update_quantity_average_cost_and_cash():
    svc = make_service(
        trades_csv(
            "T001,2026-10-02T09:00:00,AAPL,BUY,10,100",
            "T003,2026-10-02T10:00:00,AAPL,BUY,5,110",
        )
    )
    position = svc.portfolio.position(AAPL)
    assert position.quantity == 15
    assert position.total_cost == 1550
    assert position.avg_cost.quantize(D("0.000001")) == D("103.333333")
    assert svc.portfolio.cash == 8450


def test_trades_are_processed_in_timestamp_order_not_file_order():
    rows = [
        "T001,2026-10-02T09:00:00,AAPL,BUY,10,100",
        "T002,2026-10-02T09:15:00,MSFT,BUY,5,200",
        "T003,2026-10-02T10:00:00,AAPL,BUY,5,110",
    ]
    in_order = make_service(trades_csv(*rows))
    reversed_ = make_service(trades_csv(*reversed(rows)))
    assert reversed_.portfolio == in_order.portfolio
    assert [str(o.trade.trade_id) for o in reversed_.trade_history()] == ["T001", "T002", "T003"]


def test_trades_split_across_uploads_in_any_order_give_same_state():
    rows = [f"T{i:03},2026-10-02T09:{i:02}:00,AAPL,BUY,1,{100 + i}" for i in range(20)]
    expected = make_service(trades_csv(*rows)).portfolio
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    svc = make_service()
    for chunk in (shuffled[:7], shuffled[7:12], shuffled[12:]):
        svc.upload_trades("chunk.csv", trades_csv(*chunk))
    assert svc.portfolio == expected


def test_buy_exceeding_cash_is_rejected_and_state_unchanged():
    svc = make_service(trades_csv("T001,2026-10-02T09:00:00,AAPL,BUY,101,100"))
    (outcome,) = svc.trade_history()
    assert outcome.status is TradeStatus.REJECTED
    assert outcome.reason_code is IssueCode.INSUFFICIENT_CASH
    assert svc.portfolio.cash == 10000
    assert not svc.portfolio.position(AAPL).is_open


def test_buy_spending_exactly_all_cash_is_allowed():
    svc = make_service(trades_csv("T001,2026-10-02T09:00:00,AAPL,BUY,100,100"))
    assert svc.trade_history()[0].status is TradeStatus.APPLIED
    assert svc.portfolio.cash == 0


def test_fractional_quantities_are_exact():
    svc = make_service(
        trades_csv(
            "T1,2026-10-02T09:00:00,AAPL,BUY,0.1,1",
            "T2,2026-10-02T09:01:00,AAPL,BUY,0.2,1",
        )
    )
    assert svc.portfolio.position(AAPL).quantity == D("0.3")
    assert svc.portfolio.cash == D("9999.7")
