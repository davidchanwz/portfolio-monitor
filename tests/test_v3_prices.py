from portfolio_monitor.domain.value_objects import Symbol
from tests.conftest import D, EXAMPLE_PRICES, make_service, money, prices_csv, trades_csv
from tests.test_v2_sells import EXAMPLE_TRADES_NO_DUP


def test_golden_example_valuation():
    v = make_service(EXAMPLE_TRADES_NO_DUP, EXAMPLE_PRICES).valuation()
    aapl, msft = v.positions
    assert (str(aapl.symbol), aapl.quantity, aapl.latest.price.value) == ("AAPL", 7, 125)
    assert aapl.avg_cost.quantize(D("0.000001")) == D("103.333333")
    assert aapl.market_value == 875
    assert money(aapl.unrealized_pnl) == D("151.67")
    assert (str(msft.symbol), msft.quantity, msft.avg_cost, msft.latest.price.value) == ("MSFT", 5, 200, 195)
    assert msft.market_value == 975
    assert msft.unrealized_pnl == -25
    assert v.cash == 8410
    assert v.total_market_value == 1850
    assert v.total_portfolio_value == 10260
    assert money(v.realized_pnl) == D("133.33")
    assert money(v.unrealized_pnl) == D("126.67")
    assert v.is_complete
    # Accounting identity: value = initial cash + realized + unrealized.
    assert money(10000 + v.realized_pnl + v.unrealized_pnl) == money(v.total_portfolio_value)


def test_latest_price_is_by_timestamp_not_arrival_order():
    svc = make_service(
        trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,1,100"),
        prices_csv("2026-10-02T12:00:00,AAPL,125", "2026-10-02T11:00:00,AAPL,118"),
    )
    svc.upload_prices("late.csv", prices_csv("2026-10-02T10:00:00,AAPL,90"))
    assert svc.price_book.latest(Symbol("AAPL")).price.value == 125


def test_missing_price_is_unavailable_and_valuation_incomplete():
    svc = make_service(
        trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,1,100", "T2,2026-10-02T09:00:00,NVDA,BUY,2,50"),
        prices_csv("2026-10-02T12:00:00,AAPL,125"),
    )
    v = svc.valuation()
    nvda = next(p for p in v.positions if str(p.symbol) == "NVDA")
    assert nvda.latest is None and nvda.market_value is None and nvda.unrealized_pnl is None
    assert not v.is_complete
    assert v.unpriced_symbols == (Symbol("NVDA"),)
    assert v.total_market_value == 125  # priced positions only, never NVDA-as-zero silently
    assert v.unrealized_pnl == 25


def test_price_for_unheld_symbol_does_not_affect_portfolio():
    svc = make_service(EXAMPLE_TRADES_NO_DUP, EXAMPLE_PRICES)
    before = svc.valuation()
    svc.upload_prices("more.csv", prices_csv("2026-10-02T12:00:00,TSLA,250"))
    assert svc.valuation() == before
    assert svc.price_book.latest(Symbol("TSLA")).price.value == 250


def test_closed_position_is_not_listed_but_realized_pnl_is_kept():
    svc = make_service(
        trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,1,100", "T2,2026-10-02T09:01:00,AAPL,SELL,1,110"),
    )
    v = svc.valuation()
    assert v.positions == ()
    assert v.realized_pnl == 10
    assert v.is_complete
