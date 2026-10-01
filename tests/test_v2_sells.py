from portfolio_monitor.domain.issues import IssueCode
from portfolio_monitor.domain.portfolio import TradeStatus
from portfolio_monitor.domain.value_objects import Symbol
from tests.conftest import D, money, make_service, trades_csv

AAPL = Symbol("AAPL")

# The brief's trades without the duplicate T004 (duplicates are handled in V4).
EXAMPLE_TRADES_NO_DUP = trades_csv(
    "T001,2026-10-02T09:00:00,AAPL,BUY,10,100",
    "T002,2026-10-02T09:15:00,MSFT,BUY,5,200",
    "T004,2026-10-02T11:30:00,AAPL,SELL,8,120",
    "T003,2026-10-02T10:00:00,AAPL,BUY,5,110",
)


def test_example_trades_cash_and_realized_pnl():
    svc = make_service(EXAMPLE_TRADES_NO_DUP)
    assert svc.portfolio.cash == 8410
    # Weighted average in TIMESTAMP order: T003 is bought before T004 sells.
    # 8 x (120 - 1550/15) = 133.33 -- not 160, which is what file order would give.
    assert money(svc.portfolio.realized_pnl) == D("133.33")
    aapl = svc.portfolio.position(AAPL)
    assert aapl.quantity == 7
    assert aapl.avg_cost.quantize(D("0.000001")) == D("103.333333")
    assert [o.cash_after for o in svc.trade_history()] == [9000, 8000, 7450, 8410]


def test_average_cost_unchanged_by_partial_sell():
    svc = make_service(
        trades_csv(
            "T1,2026-10-02T09:00:00,AAPL,BUY,10,100",
            "T2,2026-10-02T09:01:00,AAPL,BUY,10,110",
            "T3,2026-10-02T09:02:00,AAPL,SELL,5,200",
        )
    )
    position = svc.portfolio.position(AAPL)
    assert position.avg_cost == 105
    assert position.quantity == 15
    assert svc.portfolio.realized_pnl == 5 * (200 - 105)


def test_average_cost_resets_after_position_closes():
    svc = make_service(
        trades_csv(
            "T1,2026-10-02T09:00:00,AAPL,BUY,10,100",
            "T2,2026-10-02T09:01:00,AAPL,SELL,10,120",
            "T3,2026-10-02T09:02:00,AAPL,BUY,5,50",
        )
    )
    position = svc.portfolio.position(AAPL)
    assert position.avg_cost == 50
    assert position.total_cost == 250
    assert svc.portfolio.realized_pnl == 200


def test_sell_exceeding_holding_is_rejected_and_state_unchanged():
    svc = make_service(
        trades_csv(
            "T1,2026-10-02T09:00:00,AAPL,BUY,10,100",
            "T2,2026-10-02T09:01:00,AAPL,SELL,11,120",
        )
    )
    rejected = svc.trade_history()[1]
    assert rejected.status is TradeStatus.REJECTED
    assert rejected.reason_code is IssueCode.INSUFFICIENT_POSITION
    assert svc.portfolio.position(AAPL).quantity == 10
    assert svc.portfolio.cash == 9000
    assert svc.portfolio.realized_pnl == 0


def test_sell_of_never_held_symbol_is_rejected():
    svc = make_service(trades_csv("T1,2026-10-02T09:00:00,AAPL,SELL,1,100"))
    assert svc.trade_history()[0].reason_code is IssueCode.INSUFFICIENT_POSITION


def test_sell_before_buy_by_timestamp_is_rejected_even_if_file_lists_buy_first():
    svc = make_service(
        trades_csv(
            "T1,2026-10-02T10:00:00,AAPL,BUY,10,100",
            "T2,2026-10-02T09:00:00,AAPL,SELL,5,120",
        )
    )
    statuses = {str(o.trade.trade_id): o.status for o in svc.trade_history()}
    assert statuses == {"T2": TradeStatus.REJECTED, "T1": TradeStatus.APPLIED}


def test_fractional_close_out_leaves_no_residue():
    svc = make_service(
        trades_csv(
            "T1,2026-10-02T09:00:00,AAPL,BUY,0.1,3.333333",
            "T2,2026-10-02T09:01:00,AAPL,BUY,0.2,7.777777",
            "T3,2026-10-02T09:02:00,AAPL,SELL,0.12345678,9.1",
            "T4,2026-10-02T09:03:00,AAPL,SELL,0.17654322,9.1",
        )
    )
    position = svc.portfolio.position(AAPL)
    assert position.quantity == 0
    assert position.total_cost == 0
    assert position.avg_cost is None
    # Fully closed: realized P&L is exactly proceeds - cost, and cash reconciles exactly.
    cost = D("0.1") * D("3.333333") + D("0.2") * D("7.777777")
    assert svc.portfolio.realized_pnl == D("0.3") * D("9.1") - cost
    assert svc.portfolio.cash == 10000 + svc.portfolio.realized_pnl
