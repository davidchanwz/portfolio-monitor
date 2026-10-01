"""Streamlit presentation layer.

Holds no business logic: it sends commands to the PortfolioService and renders its read models.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from portfolio_monitor.application.ledger import UploadSummary
from portfolio_monitor.application.service import PortfolioService
from portfolio_monitor.domain.issues import Severity
from portfolio_monitor.domain.portfolio import TradeStatus
from portfolio_monitor.domain.value_objects import DomainError
from portfolio_monitor.ui.formatting import UNAVAILABLE, fmt_money, fmt_price, fmt_quantity


DATA_DIR = Path(__file__).resolve().parents[2] / "data"


HOW_IT_WORKS = """
**Information flow**

CSV upload → *ingestion* (validates every field; bad rows become Issues) → *input log* (append-only, arrival order)
→ *ledger* (drops identical duplicates, rejects conflicting `trade_id`s; keeps the price book)
→ *timeline* (accepted trades sorted by **trade timestamp**, then arrival) → *portfolio state machine* → *valuation* → this page.

**Calculations** (weighted-average cost, exact decimals; rounding is display-only)

| Event | Effect |
|---|---|
| BUY q @ p | rejected if q×p > cash (no margin); else cash −= q×p, quantity += q, cost basis += q×p |
| SELL q @ p | rejected if q > quantity held (no shorting); else realized += q×(p − avg cost), cash += q×p, quantity −= q, cost basis −= q×avg cost (reset to exactly 0 when the position closes) |

* Average cost = cost basis ÷ quantity
* Latest price = observation with the latest *timestamp* (not the latest upload)
* Market value = quantity × latest price; Unrealized P&L = market value − cost basis
* Total portfolio value = cash + total market value
* A position with no price is shown as *Unavailable* and the totals are marked incomplete; it is never valued at zero.

**Late or out-of-order data**: a trade with an earlier timestamp than trades already processed is slotted into place
and everything after it is recalculated. If that changes whether a later trade is valid, the Issues tab says so
(`TRADE_STATUS_CHANGED`).
"""


def _service() -> PortfolioService | None:
    return st.session_state.get("service")


def _flash(kind: str, message: str) -> None:
    st.session_state.setdefault("flash", []).append((kind, message))


# ---- sidebar: commands ------------------------------------------------------------------


def _sidebar() -> None:
    svc = _service()
    with st.sidebar:
        st.header("1. Portfolio")
        cash_text = st.text_input("Initial cash (USD)", value="10000", key="cash_input")
        label = "Create portfolio" if svc is None else "Update initial cash"
        if st.button(label, type="primary" if svc is None else "secondary", key="init_button"):
            try:
                target = svc or PortfolioService()
                target.initialize(cash_text)
                st.session_state.service = target
                svc = target
                _flash("success", f"Initial cash set to {fmt_money(target.portfolio.initial_cash)} USD.")
            except DomainError as e:
                _flash("error", f"Could not set initial cash: {e.message}")

        if svc is not None:
            st.header("2. Load data")
            st.caption("CSV files may be re-uploaded and rows may be in any order.")
            _upload_control("Trades CSV", "trades", svc.upload_trades)
            _upload_control("Market prices CSV", "prices", svc.upload_prices)

    _demo_sidebar(svc)


def _upload_control(label: str, kind: str, upload) -> None:
    # Changing the uploader key after processing clears it, so a file is processed exactly once per click.
    generation = st.session_state.setdefault(f"{kind}_generation", 0)
    file = st.file_uploader(label, type=["csv"], key=f"{kind}_uploader_{generation}")
    if st.button(f"Process {kind} file", disabled=file is None, key=f"process_{kind}"):
        _report_upload(upload(file.name, file.getvalue()))
        st.session_state[f"{kind}_generation"] = generation + 1
        st.rerun()


def _demo_sidebar(svc: PortfolioService | None) -> None:
    with st.sidebar:
        st.header("Demo")
        if st.button("Load example data (10,000 USD + brief's CSVs)", key="load_example"):
            fresh = PortfolioService()
            fresh.initialize("10000")
            st.session_state.service = fresh
            _flash("success", "Created a portfolio with 10,000.00 USD.")
            for name, upload in (("example_trades.csv", fresh.upload_trades), ("example_prices.csv", fresh.upload_prices)):
                _report_upload(upload(name, (DATA_DIR / name).read_bytes()))
            st.rerun()
        if svc is not None:
            files = sorted(p.name for p in DATA_DIR.glob("*.csv"))
            name = st.selectbox("Sample file", files, key="demo_file")
            trades_col, prices_col = st.columns(2)
            if trades_col.button("Load as trades", key="demo_trades"):
                _report_upload(svc.upload_trades(name, (DATA_DIR / name).read_bytes()))
                st.rerun()
            if prices_col.button("Load as prices", key="demo_prices"):
                _report_upload(svc.upload_prices(name, (DATA_DIR / name).read_bytes()))
                st.rerun()
            if st.button("Reset (discard everything)", key="reset"):
                del st.session_state["service"]
                st.rerun()


def _report_upload(u: UploadSummary) -> None:
    head = f"**{u.file_name}** ({u.kind}, upload #{u.upload_no})"
    if u.file_error:
        _flash("error", f"{head}: whole file rejected. {u.file_error}")
        return
    text = f"{head}: {u.rows} rows → {u.accepted} accepted, {u.duplicates} duplicates ignored, {u.rejected} rejected"
    if u.rule_rejections:
        text += f"; {u.rule_rejections} accepted trade(s) rejected by portfolio rules"
    if u.rejected or u.rule_rejections:
        _flash("warning", text + ". See the **Issues** tab.")
    else:
        _flash("success", text + ".")


# ---- main area: read models -------------------------------------------------------------


def _flash_messages() -> None:
    for kind, message in st.session_state.pop("flash", []):
        getattr(st, kind)(message)


def _kpis(svc: PortfolioService) -> None:
    v = svc.valuation()
    mark = "" if v.is_complete else " *"
    cols = st.columns(5)
    cols[0].metric("Cash", fmt_money(v.cash))
    cols[1].metric("Total market value", fmt_money(v.total_market_value) + mark)
    cols[2].metric("Total portfolio value", fmt_money(v.total_portfolio_value) + mark)
    cols[3].metric("Realized P&L", fmt_money(v.realized_pnl, signed=True))
    cols[4].metric("Unrealized P&L", fmt_money(v.unrealized_pnl, signed=True) + mark)
    if not v.is_complete:
        symbols = ", ".join(str(s) for s in v.unpriced_symbols)
        st.warning(
            f"**Valuation incomplete (\\*)** — {len(v.unpriced_symbols)} open position(s) have no market price: "
            f"**{symbols}**. Their market value is unknown and is *excluded* from the starred totals "
            "(not counted as zero). Upload prices for these symbols to complete the valuation."
        )


def _positions_tab(svc: PortfolioService) -> None:
    v = svc.valuation()
    if not v.positions:
        st.caption("No open positions.")
        return
    rows = [
        {
            "Symbol": str(p.symbol),
            "Quantity": fmt_quantity(p.quantity),
            "Avg cost": fmt_price(p.avg_cost),
            "Cost basis": fmt_money(p.total_cost),
            "Latest price": fmt_price(p.latest.price.value) if p.latest else UNAVAILABLE,
            "Price as of": str(p.latest.timestamp) if p.latest else UNAVAILABLE,
            "Market value": fmt_money(p.market_value),
            "Unrealized P&L": fmt_money(p.unrealized_pnl, signed=True),
            "Realized P&L": fmt_money(p.realized_pnl, signed=True),
        }
        for p in v.positions
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _prices_tab(svc: PortfolioService) -> None:
    latest = svc.price_book.latest_all()
    if not latest:
        st.caption("No market prices recorded yet.")
        return
    st.subheader("Latest price per symbol")
    st.caption("Latest = most recent observation *timestamp*, regardless of upload order.")
    st.dataframe(
        pd.DataFrame(
            [
                {"Symbol": str(o.symbol), "Price": fmt_price(o.price.value), "As of": str(o.timestamp), "Source": str(o.source)}
                for o in latest
            ]
        ),
        hide_index=True,
        width="stretch",
    )
    st.subheader("All observations")
    latest_set = set(latest)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Symbol": str(o.symbol),
                    "Timestamp": str(o.timestamp),
                    "Price": fmt_price(o.price.value),
                    "Latest": "✓" if o in latest_set else "",
                    "Source": str(o.source),
                }
                for o in svc.price_book.observations()
            ]
        ),
        hide_index=True,
        width="stretch",
    )


def _trades_tab(svc: PortfolioService) -> None:
    history = svc.trade_history()
    if not history:
        st.caption("No trades processed yet.")
        return
    st.caption("All accepted trades in timestamp order (not file order), with the result of applying each one.")
    rows = [
        {
            "Timestamp": str(o.trade.timestamp),
            "Trade ID": str(o.trade.trade_id),
            "Symbol": str(o.trade.symbol),
            "Side": o.trade.side.value,
            "Quantity": fmt_quantity(o.trade.quantity.value),
            "Price": fmt_price(o.trade.price.value),
            "Notional": fmt_money(o.trade.notional),
            "Status": "✅ Applied" if o.status is TradeStatus.APPLIED else "❌ Rejected",
            "Reason": o.reason or "",
            "Cash after": fmt_money(o.cash_after),
            "Position after": fmt_quantity(o.position_after),
            "Realized P&L": fmt_money(o.realized_pnl, signed=True) if o.status is TradeStatus.APPLIED else "",
            "Source": str(o.trade.source),
        }
        for o in history
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _issues_tab(issues) -> None:
    if not issues:
        st.caption("No issues. Every input was processed.")
        return
    st.caption(
        "Every input that was not applied, and why. ERROR rows were not applied; fix the source row and re-upload "
        "(only the corrected rows are needed). INFO rows need no action."
    )
    severities = st.multiselect("Severity", [s.value for s in Severity], default=[s.value for s in Severity])
    rows = [
        {
            "Severity": i.severity.value,
            "Code": i.code.value,
            "Upload #": i.source.upload_no,
            "File": i.source.file_name,
            "Row": i.source.row_no if i.source.row_no is not None else "(file)",
            "Message": i.message,
            "Raw row": ", ".join(f"{k}={v}" for k, v in i.raw.items()) if i.raw else "",
        }
        for i in issues
        if i.severity.value in severities
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _uploads_tab(svc: PortfolioService) -> None:
    uploads = svc.uploads()
    if not uploads:
        st.caption("No files uploaded yet.")
        return
    rows = [
        {
            "Upload #": u.upload_no,
            "File": u.file_name,
            "Type": u.kind,
            "Rows": u.rows,
            "Accepted": u.accepted,
            "Duplicates ignored": u.duplicates,
            "Rejected": u.rejected,
            "Rejected by portfolio rules (now)": u.rule_rejections if u.kind == "trades" else "",
            "File error": u.file_error or "",
        }
        for u in uploads
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def main() -> None:
    st.set_page_config(page_title="Portfolio Monitor", layout="wide")
    st.title("Portfolio Monitor")
    _sidebar()
    _flash_messages()
    svc = _service()
    if svc is None:
        st.info(
            "Set the initial cash balance in the sidebar and click **Create portfolio** to begin, "
            "or click **Load example data**."
        )
        return
    _kpis(svc)
    issues = svc.issues()
    errors = sum(i.severity is Severity.ERROR for i in issues)
    positions, trades, issues_tab, prices, uploads, how = st.tabs(
        ["Positions", "Trades", f"Issues ({errors} errors)" if errors else "Issues", "Prices", "Upload log", "How it works"]
    )
    with positions:
        _positions_tab(svc)
    with trades:
        _trades_tab(svc)
    with issues_tab:
        _issues_tab(issues)
    with prices:
        _prices_tab(svc)
    with uploads:
        _uploads_tab(svc)
    with how:
        st.markdown(HOW_IT_WORKS)
