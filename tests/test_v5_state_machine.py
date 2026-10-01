"""State-machine properties: snapshot equivalence, order independence, determinism, recovery."""

import random
from datetime import datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from portfolio_monitor.application.service import PortfolioService
from portfolio_monitor.application.timeline import replay
from portfolio_monitor.domain.issues import IssueCode
from portfolio_monitor.domain.portfolio import Portfolio, TradeStatus
from portfolio_monitor.domain.value_objects import Symbol
from tests.conftest import EXAMPLE_PRICES, EXAMPLE_TRADES, prices_csv, trades_csv

BASE = datetime(2026, 10, 2, 9, 0)

# A random trade: (minute offset, symbol, side, quantity, price). Small cash + random sells
# make sure plenty of trades hit the short-selling and insufficient-cash rules.
trade_rows = st.lists(
    st.tuples(
        st.integers(0, 600),
        st.sampled_from(["AAPL", "MSFT"]),
        st.sampled_from(["BUY", "SELL"]),
        st.decimals("0.5", "20", places=1),
        st.decimals("1", "50", places=2),
    ),
    min_size=1,
    max_size=40,
)


def to_csv_rows(rows):
    return [
        f"T{i},{(BASE + timedelta(minutes=m)).isoformat()},{sym},{side},{qty},{px}"
        for i, (m, sym, side, qty, px) in enumerate(rows)
    ]


def upload_in_batches(svc, csv_rows, rng):
    rows = csv_rows[:]
    rng.shuffle(rows)
    cuts = sorted(rng.sample(range(1, len(rows)), min(len(rows) - 1, rng.randint(0, 4))))
    for lo, hi in zip([0, *cuts], [*cuts, len(rows)]):
        svc.upload_trades("batch.csv", trades_csv(*rows[lo:hi]))


@settings(max_examples=150, deadline=None)
@given(rows=trade_rows, interval=st.integers(1, 6), seed=st.integers(0, 10_000))
def test_incremental_replay_with_snapshots_equals_full_replay(rows, interval, seed):
    svc = PortfolioService(snapshot_interval=interval)
    svc.initialize("500")
    upload_in_batches(svc, to_csv_rows(rows), random.Random(seed))

    full_state, full_outcomes = replay(Portfolio.open(svc.portfolio.initial_cash), svc._timeline.trades)
    assert svc.portfolio == full_state
    assert list(svc.trade_history()) == full_outcomes


@settings(max_examples=100, deadline=None)
@given(rows=trade_rows.map(lambda rs: list({r[0]: r for r in rs}.values())), seed=st.integers(0, 10_000))
def test_final_state_is_independent_of_arrival_order(rows, seed):
    """With distinct timestamps, any arrival order / batching yields the same portfolio."""
    csv_rows = to_csv_rows(rows)
    reference = PortfolioService()
    reference.initialize("500")
    reference.upload_trades("all.csv", trades_csv(*csv_rows))

    svc = PortfolioService(snapshot_interval=2)
    svc.initialize("500")
    upload_in_batches(svc, csv_rows, random.Random(seed))
    assert svc.portfolio == reference.portfolio
    assert [(o.trade.trade_id, o.status) for o in svc.trade_history()] == [
        (o.trade.trade_id, o.status) for o in reference.trade_history()
    ]


def test_late_trade_flips_earlier_accepted_trade_and_reports_it():
    svc = PortfolioService()
    svc.initialize("10000")
    svc.upload_trades("example_trades.csv", EXAMPLE_TRADES)
    assert all(o.status is TradeStatus.APPLIED for o in svc.trade_history())

    # A back-dated sale at 11:00 leaves only 5 AAPL, so T004 (sell 8 at 11:30) is no longer valid.
    summary = svc.upload_trades("late.csv", trades_csv("T014,2026-10-02T11:00:00,AAPL,SELL,10,118"))
    statuses = {str(o.trade.trade_id): o.status for o in svc.trade_history()}
    assert statuses["T014"] is TradeStatus.APPLIED
    assert statuses["T004"] is TradeStatus.REJECTED
    changed = [i for i in svc.issues() if i.code is IssueCode.TRADE_STATUS_CHANGED]
    assert len(changed) == 1 and "T004" in changed[0].message and "upload #2" in changed[0].message
    assert summary.rule_rejections == 0  # T014 itself is fine; T004 belongs to upload #1
    assert svc.uploads()[0].rule_rejections == 1


def test_changing_initial_cash_replays_and_reports_flips():
    svc = PortfolioService()
    svc.initialize("10000")
    svc.upload_trades("t.csv", trades_csv("T1,2026-10-02T09:00:00,AAPL,BUY,10,100"))
    svc.initialize("500")
    assert svc.trade_history()[0].reason_code is IssueCode.INSUFFICIENT_CASH
    assert any(i.code is IssueCode.TRADE_STATUS_CHANGED for i in svc.issues())
    svc.initialize("10000")
    assert svc.portfolio.position(Symbol("AAPL")).quantity == 10


def test_snapshots_bound_the_replay_work_for_late_trades():
    svc = PortfolioService(snapshot_interval=10)
    svc.initialize("1000000")
    svc.upload_trades(
        "bulk.csv",
        trades_csv(*[f"T{i},{(BASE + timedelta(minutes=i)).isoformat()},AAPL,BUY,1,10" for i in range(100)]),
    )
    assert svc._timeline.snapshot_count == 10
    # Back-dated to minute 95.5 -> lands at index 96, so replay starts at snapshot 9 (trade 90), not 0.
    svc.upload_trades("late.csv", trades_csv(f"L1,{(BASE + timedelta(minutes=95, seconds=30)).isoformat()},AAPL,BUY,1,10"))
    assert svc._timeline.last_replay_count == 11


def build_live():
    svc = PortfolioService(snapshot_interval=2)
    svc.initialize("10000")
    svc.upload_trades("example_trades.csv", EXAMPLE_TRADES)
    svc.upload_prices("example_prices.csv", EXAMPLE_PRICES)
    svc.upload_trades("late.csv", trades_csv("T014,2026-10-02T11:00:00,AAPL,SELL,10,118", "X,bad,row,,,"))
    svc.upload_prices("p.csv", prices_csv("2026-10-02T12:00:00,MSFT,196"))
    return svc


def test_same_log_gives_identical_state_on_every_replica():
    live = build_live()
    replica_a = PortfolioService.replicate(live.log.entries)
    replica_b = PortfolioService.replicate(live.log.entries, snapshot_interval=500)
    assert replica_a.fingerprint() == live.fingerprint() == replica_b.fingerprint()


def test_recovery_from_partial_log_then_tail_matches_live():
    live = build_live()
    entries = live.log.entries
    for crash_point in range(len(entries) + 1):
        recovered = PortfolioService.replicate(entries[:crash_point])
        recovered.catch_up(entries[crash_point:])
        assert recovered.fingerprint() == live.fingerprint()
