# Portfolio Monitor

A prototype that turns trade and market-price CSV files into a current view of a portfolio:
positions, average cost, market value, unrealized and realized P&L, cash and total value. It also
explains every input it could not process.

Brief: [docs/BRIEF.md](docs/BRIEF.md) · Interviewer answers: [docs/INTERVIEWER_ANSWERS.md](docs/INTERVIEWER_ANSWERS.md) · Plan: [docs/PLAN.md](docs/PLAN.md)

## Running it

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # or: uv venv && uv pip install -r requirements.txt

.venv/bin/streamlit run app.py              # opens http://localhost:8501
.venv/bin/pytest                            # 79 tests, ~1s
```

### Demo script

1. **Load example data**. This creates a portfolio with 10,000 USD and loads the brief's two CSVs.
   The upload banner reports that the repeated T004 was ignored as a duplicate. Expected figures:
   cash 8,410.00, market value 1,850.00, total value 10,260.00, realized +133.33, unrealized +126.67.
2. **Trades** tab: trades are listed in timestamp order (T003 before T004, even though the file lists them the other way round), with running cash.
3. **Sample file → `example_trades.csv` → Load as trades** again. Nothing changes, because uploads can be repeated safely.
4. **`messy_trades.csv` → Load as trades**. This shows each kind of row error, a `trade_id` conflict, a short sale
   rejection, an insufficient-cash rejection, and an NVDA position with no price. The totals are starred as
   incomplete, and NVDA is not counted as zero.
5. **`messy_prices.csv` → Load as prices**. This shows a duplicate, a conflicting price, bad numbers, too many decimals, and an
   older price that does not replace the latest one.
6. **`late_trade.csv` → Load as trades**. This is a back-dated sale at 11:00. T004 (11:30) is no longer covered, so it
   changes from APPLIED to REJECTED and the Issues tab explains why (`TRADE_STATUS_CHANGED`).
7. **`example_prices.csv` → Load as trades**. The wrong file type is rejected as a whole file (`MISSING_COLUMNS`).

You can also upload your own files with the uploaders under **2. Load data**.

## Design

### Information flow

```
CSV ──► Ingestion (anti-corruption layer) ──► Command ──► Input Log (append-only, ARRIVAL order)
        value objects validate each field                       │
        bad rows → Issues (file, row, reason)                   ▼
                                                  Ledger (arrival-order state machine)
                                                  · trade_id identity: duplicate → ignore, conflict → reject
                                                  · PriceBook: latest price per symbol by TIMESTAMP
                                                        │ newly accepted trades
                                                        ▼
                                                  Timeline (trades sorted by timestamp, then arrival)
                                                  · Portfolio state machine: apply(state, trade) → (state', outcome)
                                                  · immutable snapshots every 500 trades
                                                        │
                                                        ▼
                                                  Valuation (portfolio × latest prices) ──► Streamlit UI
```

**Two orderings.** Data arrives in one order, but the portfolio must be calculated in timestamp order.
The *input log* records arrival order, and that is what you would replicate. Portfolio state is a
**deterministic function of the log**: accepted trades are replayed through a pure transition
function in `(timestamp, upload #, row #)` order. When a back-dated trade arrives, the timeline
restores the nearest snapshot at or before the trade's position and replays only from there.

**State machine replication.** The transitions are pure: no clock, no randomness, no I/O, and a
fixed `Decimal` context. Any replica that applies the same log reaches identical state. Tests check this
with a hash of the whole state (`fingerprint()`). Recovery is: rebuild from the log up to the crash, then
catch up on the rest. Replication itself (Raft or Kafka) is not built. The design leaves room for it.

### Domain-driven design

| Bounded context | Code | Responsibility |
|---|---|---|
| Ingestion (anti-corruption layer) | `ingestion/csv_adapter.py` | The only place that knows CSV. Rows become domain objects or `Issue`s |
| Trading / Portfolio (core) | `domain/portfolio.py`, `domain/trade.py` | `Portfolio` aggregate (immutable), `Position`, weighted average cost, no-short and no-margin rules |
| Market Data | `domain/price_book.py` | `PriceBook` aggregate: observations keyed by (symbol, timestamp), latest by timestamp |
| Valuation | `domain/valuation.py` | Domain service: portfolio × prices → read model, with completeness flag |
| Application | `application/` | Commands, input log, ledger, timeline (snapshots), `PortfolioService` |
| UI | `ui/` | Streamlit. No business logic, only commands and read models |

The value objects (`Quantity`, `Price`, `Symbol`, `TradeId`, `Side`, `Timestamp`) validate
themselves, so invalid values can't be constructed. Format validation therefore lives in the
domain, and the adapter just collects the errors.

### Calculations

All arithmetic uses `Decimal` (34 significant digits). Values are rounded only for display: money to 2
decimal places, prices and average cost to 6, quantities to 8.

| Event | Rule |
|---|---|
| BUY q @ p | Rejected if `q×p > cash` (no margin). Else `cash −= q×p`, `qty += q`, `cost_basis += q×p` |
| SELL q @ p | Rejected if `q > qty` (no shorting). Else `realized += q×(p − avg)`, `cash += q×p`, `qty −= q`, `cost_basis −= q×avg`. When qty reaches 0, `cost_basis = 0` exactly, so the average resets with no rounding residue |
| Derived | `avg = cost_basis / qty`; `market value = qty × latest price`; `unrealized = market value − cost_basis`; `total value = cash + Σ market value` |

Rejected trades do not change state. Check for the example data: 10,000 + 133.33 realized +
126.67 unrealized = 10,260 total value.

## Assumptions

These come from the interviewer's answers unless marked **(ours)**.

- Input arrives as CSV batches: trades and prices in separate uploads, up to about 10k rows each. Files can be re-uploaded, and rows can be in any order.
- Timestamps have no offset and are read as Singapore time. Quantity must be > 0 with at most 8 decimal places, and price > 0 with at most 6. **(ours)** Trailing zeros don't count toward the limit (`1.50000000000` is valid).
- Weighted average cost, which resets when a position closes. No shorting.
- **(ours)** No margin: a buy costing more than the cash available *at that point in time* is rejected.
- **(ours)** Trades with the same timestamp are ordered by arrival (upload #, then row #).
- Duplicate trades (same `trade_id`, same details) are ignored. The same `trade_id` with different details is a conflict: it is rejected, and the first one seen wins.
- **(ours)** The same rule applies to prices, keyed by (symbol, timestamp).
- **(ours)** A row that fails format validation doesn't reserve its `trade_id`, so a corrected row can be sent later with the same id.
- **(ours)** Trade execution prices are not used as market prices.
- A position with no price stays in the table, with its value shown as *Unavailable*. The totals cover only priced positions and are clearly marked incomplete.
- **(ours)** Symbols are trimmed and uppercased, and `side` is case-insensitive. Extra columns and column order don't matter. A missing required column rejects the whole file.
- **(ours)** Closed positions (qty 0) are hidden from the positions table, but their realized P&L stays in the total.
- **(ours)** Changing the initial cash replays all trades from the start.
- Fees, cancellations and amendments, historical views, persistence, authentication and APIs are out of scope.

## Edge cases covered by tests

| Area | Tests |
|---|---|
| Example from the brief | Exact figures, including the duplicate T004 and the out-of-order T003/T004 |
| Ordering | File order versus timestamp order; batches shuffled in any arrival order give the same state (property test) |
| Cost basis | Average unchanged by a partial sell; resets after close; fractional close-out leaves exactly 0 cost and cash reconciles exactly |
| Rules | Over-sell, selling a symbol never held, sell timestamped before its buy, over-buy, spending exactly all cash |
| Bad input | Each row error code, all errors in a row reported together, short rows, missing columns, empty or header-only or non-UTF-8 files, header variations (BOM, case, order, extra columns) |
| Identity | Duplicate ignored, conflict rejected (across files and within one file), re-upload changes nothing, malformed rows don't reserve ids |
| Prices | Latest chosen by timestamp, not arrival; duplicate and conflict handling; unpriced position; price for a symbol not held |
| State machine | Incremental replay with snapshots equals full replay (hypothesis, random snapshot intervals); late trade flips an earlier status and the change is reported; snapshots limit how much is replayed; replicas agree; recovery from any crash point |
| UI | Headless Streamlit `AppTest` runs of the demo flow |

## Trade-offs and limitations

- **No persistence.** State lives in the Streamlit session and is lost on restart, as the brief allows. In production, the
  input log would go to a durable store (Postgres or Kafka) and snapshots to object storage.
- **Replication is designed for but not built.** The determinism tests show the property it depends on.
- **Snapshots cover the portfolio timeline only.** Recovery replays the whole input log, which is fine at this scale.
  At larger scale, you would also checkpoint the ledger at a log position.
- **Conflicts can't be resolved in the UI.** The first version seen wins, and the user must fix the source data. Amendments and cancellations are not supported.
- **Status is derived, not stored.** A late trade can turn an earlier accepted trade into a rejected one. This is reported, but
  nobody is asked to approve it.
- **Domain events are not separate classes.** The plan named `TradeApplied`, `TradeRejected` and others. In the code they are the
  `TradeOutcome` and `Issue` records. That was a deliberate simplification to save time.
- **Single portfolio, USD only, no fees.** The single place to add fees is the BUY/SELL transition in `Portfolio`.
- **Ties at the same timestamp follow arrival order**, so a buy and a sell at the identical second are processed in arrival order.
- **UI**: Streamlit tables display numbers as formatted text so precision is kept exactly, which means columns sort as text.

## Scaling further

Measured locally: 10k trades take about 0.14s to ingest, 10k prices about 0.06s, and a late trade replays only from
the nearest snapshot (about 500 trades, about 6ms).

At 100× or more:
- Move the log to Kafka or Raft.
- Put unique constraints on `trade_id` and on `(symbol, ts)` in a database.
- Persist snapshots so recovery replays only the end of the log.
- Keep only the latest price per symbol in the hot path.
- Partition by symbol for throughput. The catch is the no-margin cash check, which couples all symbols together. You would need either a single
  cash sequencer or a looser rule, such as checking cash at settlement.

## Likely requirement changes

| Change | Where it lands |
|---|---|
| Fees or commissions | `Portfolio._buy` / `_sell` (cash and cost basis) |
| FIFO instead of average cost | `Position` holds lots instead of a total cost; same transition interface |
| Allow shorting | Remove the guard in `_sell`; define average-cost rules for a negative quantity |
| Cancel or amend | New command type. The ledger replaces or removes the trade, then the timeline replays from its position |
| As-of view | `replay()` over trades up to time T (snapshots make it cheap) |
| Multi-currency | FX observations in `PriceBook`; valuation converts |

## Layout

```
app.py                      Streamlit entry point
portfolio_monitor/
  domain/                   value_objects, issues, trade, portfolio, price_book, valuation
  application/              commands, input_log, ledger, timeline, service
  ingestion/csv_adapter.py  anti-corruption layer
  ui/                       app.py (Streamlit), formatting.py
tests/                      one file per build slice (v0–v5) + value objects + UI
data/                       example + demo CSVs
docs/                       brief, interviewer answers, plan
```
