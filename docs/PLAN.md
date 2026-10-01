# Portfolio Monitor — Build Plan

Sources: [BRIEF.md](BRIEF.md), [INTERVIEWER_ANSWERS.md](INTERVIEWER_ANSWERS.md).
Items marked **(A)** are our assumed defaults (not confirmed by the interviewer) — list them in the README.

---

## 1. Requirements (locked)

### Input
- Two separate CSV uploads: **trades** and **prices**. Batches of up to ~10k rows each. Files may be re-uploaded; rows are unordered.
- Timestamps: ISO 8601, no offset, interpreted as Singapore time (Asia/Singapore). No DST.
- Quantity > 0, ≤ 8 dp. Price > 0, ≤ 6 dp. Exact decimal arithmetic only — never floats.
  - Decimal-place check is on the *normalized* value (`100.000000000` is valid). **(A)**
- `side` case-insensitive; symbol trimmed + uppercased. **(A)**
- Extra columns ignored; column order irrelevant; missing required column → whole file rejected. **(A)**

### Calculations
- Weighted-average cost; average cost resets when a position returns to zero.
- State determined by trade **timestamp**, not row/file order. Tie-break: `(timestamp, seq)` where seq = arrival sequence (upload #, row #). **(A)**
- No shorting: reject a SELL exceeding current holding.
- No margin: reject a BUY whose cost exceeds current cash. **(A)**
- Latest market price per symbol = observation with the greatest timestamp (not arrival order).
- Trade execution prices do **not** update market price. **(A)**
- Fees ignored; transition function structured so fees can be added in one place.

### Duplicates and conflicts
- Trade: same `trade_id`, identical details → ignored, reported as INFO.
- Trade: same `trade_id`, different details → rejected as conflict; first-seen (lowest seq) wins; both versions shown.
- Price: same `(symbol, timestamp)`, same price → ignored (INFO); different price → conflict, first-seen wins. **(A)**
- Only rows that pass format validation claim a `trade_id` (a malformed row doesn't block a corrected re-send). **(A)**

### Missing prices
- Position still shown; price / market value / unrealized P&L shown as **Unavailable**.
- Totals carry a banner: "Valuation incomplete — N position(s) unpriced: …". Never treat missing as zero.

### Display
- Positions with quantity 0 are hidden from the positions table, but their realized P&L stays in the total. **(A)**
- Rounding is display-only: money 2 dp, prices/avg cost 6 dp, quantities 8 dp.

### Out of scope
Persistence across restarts, cancellations/amendments, historical/as-of view, manual entry, streaming, machine-facing API, auth, multiple portfolios, multi-currency.

---

## 2. Core design idea — two orderings, two state machines

State machine replication requires every replica to apply the same log in the same order — but our
data arrives out of order and the business needs timestamp order. Resolve by separating them:

```
               (ARRIVAL order — the replicable thing)
Commands ──► [ Input Log: seq 1, 2, 3 … ] ──► Ledger state machine
                                                │  dedupe / conflicts ("first seen" = lowest seq)
                                                │  accepted trades, PriceBook
                                                ▼
               (TIMESTAMP order — the business thing)
            [ Trade timeline sorted by (ts, seq) ] ──► Portfolio state machine
                                                         │  transition(state, trade) → (state', outcome)
                                                         │  immutable snapshots every N trades
                                                         ▼
                                                    Valuation (read model) ──► UI
```

- **Input log** = append-only, arrival-ordered, source of truth. This is what you'd replicate.
- **Portfolio state** = deterministic function of the log. A late trade (ts before timeline head)
  → restore latest snapshot before its `(ts, seq)` position → replay the suffix.
- Same log ⇒ same state on every replica ⇒ SMR-ready. Recovery = snapshot + log tail.

### Determinism rules
- Transition functions are pure: no wall clock, no random/uuid, no I/O. Upload time + seq are
  stamped on the command *before* it enters the log.
- Fixed Decimal context (precision 28+). Deterministic tie-breaks everywhere.
- Trade status (APPLIED/REJECTED) is **derived by replay, never stored** — a late trade can flip it.

### Scope honesty
Design *for* SMR; don't implement replication. Persistence is out of scope and Raft in 3 h is a red
flag. Production story: log → Raft/Kafka, snapshots → durable store, replicas recover via snapshot + replay.

---

## 3. Domain model (DDD)

### Bounded contexts
| Context | Responsibility |
|---|---|
| **Ingestion** (anti-corruption layer) | CSV → domain commands or row-level issues. Only place that knows CSV. |
| **Trading / Portfolio** (core domain) | Portfolio aggregate, positions, cost basis, P&L, short/cash rules |
| **Market Data** | PriceBook aggregate: latest price per symbol, price conflicts |
| **Valuation** | Domain service: Portfolio snapshot + PriceBook → valuation read model |

### Ubiquitous language
Trade, Price Observation, Position, Average Cost, Total Cost, Realized P&L, Unrealized P&L,
Market Value, Portfolio Value, Valuation Completeness, Input Log, Timeline, Snapshot, Issue.

### Value objects (enforce format validation — invalid values can't exist)
`Money`, `Quantity` (>0, ≤8 dp), `Price` (>0, ≤6 dp), `Symbol` (normalized), `TradeId`, `Side`,
`Timestamp` (SGT). Ingestion's validator just tries to construct these and collects errors.

### Entities / aggregates
- **Position** (entity within Portfolio): symbol, quantity, total cost, realized P&L. Avg cost derived.
- **Portfolio** (aggregate root): cash, positions, realized P&L; owns `apply(trade) → outcome`.
- **Ledger** (application state machine over the input log): owns trade-id identity → duplicates/conflicts.
- **PriceBook** (aggregate): latest observation per symbol, conflict detection.

### Domain entities for results
- `TradeOutcome`: trade, status (APPLIED/REJECTED), reason, cash after, position qty after, realized P&L on this trade.
- `Issue`: source (upload #, file, row), raw row, severity (ERROR/INFO), code, human-readable message.
- `Valuation`: per-position MV / unrealized (or Unavailable), totals, `is_complete`, unpriced symbols.

### Commands
`InitializePortfolio(cash)`, `RecordTradeBatch(file, rows)`, `RecordPriceBatch(file, rows)`.
Changing initial cash = new InitializePortfolio → full replay.

### Domain events
`TradeAccepted`, `DuplicateIgnored`, `TradeIdConflict`, `TradeApplied`, `TradeRejected(reason)`,
`PriceObserved`, `PriceConflict`, `TradeStatusChanged`.
Events feed the Issues tab, Trades tab and upload log. `TradeStatusChanged` = diff of suffix
outcomes before vs after a replay.

### Snapshots
Immutable `PortfolioState` keyed by timeline position `(ts, seq)`, every N = 500 trades
(10k trades ≈ 20 snapshots). Late trade cost = O(trades after nearest prior snapshot).

### Code layout (by context; build order is still vertical)
```
domain/        value_objects, portfolio (state + transition), price_book, valuation, events
application/   input_log, ledger, timeline (snapshots + replay), service (command handlers)
ingestion/     csv_adapter (anti-corruption layer)
ui/            streamlit app (read models only — no logic)
tests/         one file per slice
docs/          BRIEF.md, INTERVIEWER_ANSWERS.md, PLAN.md
```

### Stack
Python + Streamlit (human ops users, file upload + tables for free, session state = in-memory, no
persistence needed). `Decimal` for all numbers. pytest (+ `hypothesis` if time).
Trade-off: less UI control than FastAPI + frontend; engine is UI-agnostic so the UI is swappable.

---

## 4. Calculation spec

For each accepted trade in `(ts, seq)` order:

**BUY q @ p**
- Reject `INSUFFICIENT_CASH` if `q×p > cash`.
- Else: `cash −= q×p`; `qty += q`; `total_cost += q×p`.

**SELL q @ p**
- Reject `INSUFFICIENT_POSITION` if `q > qty`.
- Else: `avg = total_cost / qty`; `realized += q×(p − avg)`; `cash += q×p`; `qty −= q`.
- If `qty == 0` → `total_cost = 0` exactly (resets average, no rounding residue).
- Else `total_cost −= q×avg`.

**Derived**
- `avg_cost = total_cost / qty`
- `market_value = qty × latest_price`
- `unrealized = market_value − total_cost`
- `total_market_value = Σ market_value` (priced positions only; flagged incomplete otherwise)
- `total_portfolio_value = cash + total_market_value` (flagged incomplete if any position unpriced)

Rejected trades do not change state.

### Expected result for the brief's example data (golden test)

| Symbol | Qty | Avg cost | Latest | Market value | Unrealized |
|---|---|---|---|---|---|
| AAPL | 7 | 103.333333 | 125 | 875.00 | +151.67 |
| MSFT | 5 | 200 | 195 | 975.00 | −25.00 |

- Cash **8,410.00** · Total MV **1,850.00** · Total value **10,260.00**
- Realized P&L **+133.33** · Unrealized total **+126.67**
- Second T004 → DUPLICATE_IGNORED. AAPL latest = 125 (12:00), not 118 (arrived later, 11:00).
- Cash path (timestamp order): 10,000 → 9,000 (T001) → 8,000 (T002) → 7,450 (T003) → 8,410 (T004).
- Sanity: 10,000 + 133.33 + 151.67 − 25 = 10,260 ✓
- Note: processing in arrival order would give realized 160 / avg 107.14 — that's the trap.

---

## 5. Issue codes

| Level | Code | Example |
|---|---|---|
| File (ERROR) | `MISSING_COLUMNS`, `EMPTY_FILE`, `UNREADABLE` | Prices file uploaded into trades slot |
| Row (ERROR) | `MISSING_FIELD`, `INVALID_NUMBER`, `NON_POSITIVE`, `TOO_MANY_DECIMALS`, `INVALID_SIDE`, `INVALID_TIMESTAMP` | `qty=-5`, `side=HOLD` |
| Row (ERROR) | `TRADE_ID_CONFLICT`, `PRICE_CONFLICT` | T004 re-sent with qty 9 |
| Row (INFO) | `DUPLICATE_IGNORED` | T004 re-sent identical |
| Engine (ERROR) | `INSUFFICIENT_POSITION`, `INSUFFICIENT_CASH` | Sell 20 while holding 7 |
| Engine (INFO) | `TRADE_STATUS_CHANGED` | Late trade made a previously applied sell invalid |

Every issue shows file, row number, raw row, and a human message, e.g.
*"Row 6 (T004): trade_id already processed with quantity 8; this row has quantity 9. Not applied."*

---

## 6. UI (Streamlit)

**Sidebar:** initial cash input · trades CSV upload · prices CSV upload · "Load example data" · Reset.

**Main**
1. Upload result banner — e.g. "trades.csv: 5 rows → 4 accepted, 1 duplicate, 0 rejected."
2. KPI row — Cash, Total MV, Total Portfolio Value, Realized P&L, Unrealized P&L; incomplete-valuation warning when applicable.
3. Tabs:
   - **Positions** — table from §4 with Unavailable markers.
   - **Trades** — processed ledger in timestamp order: status, reason, running cash, realized P&L per trade.
   - **Issues** — all rejections / conflicts / duplicates / status changes, filterable by severity.
   - **Prices** — latest per symbol (with its timestamp) + all observations.
   - **Upload log** — per-upload counts.

---

## 7. Build order — vertical slices

Each slice cuts CSV → domain → UI → tests and leaves a demo-able app. Ordered by risk: required
features first, optimizations last. Running out of time cuts from the bottom and leaves a correct app.

| # | Slice | End-to-end scope | Done when | Time |
|---|---|---|---|---|
| **V0** | Walking skeleton | Streamlit app, `InitializePortfolio`, input log, cash KPI | App runs and shows cash | 0–15 |
| **V1** | Buy trades | Trades CSV adapter, value objects, `Portfolio.apply` BUY, full replay by `(ts, seq)`, Positions + Trades tabs | Buys → qty/avg cost, cash drops, out-of-order handled | 15–45 |
| **V2** | Sell trades | SELL transition, realized P&L, avg reset, short/cash rejections in Trades tab | Example trades (dup excluded) → cash 8,410, realized 133.33 | 45–70 |
| **V3** | Market prices | Prices CSV adapter, PriceBook (latest by ts), Valuation, KPIs, incomplete banner | Full golden example matches §4 | 70–100 |
| **V4** | Bad input | Ledger dedupe/conflicts, all row/file issue codes, Issues tab, upload log, idempotent re-upload | Re-uploading example is a no-op; corrupted file reports exact rows | 100–135 |
| **V5** | Snapshots + incremental replay | Snapshot store, restore + suffix replay, `TradeStatusChanged` | Property test: incremental == full replay for any arrival order | 135–160 |
| **V6** | Wrap | README (run, design, info flow, assumptions, limitations, scale + SMR story), example button, demo rehearsal | | 160–180 |

V1–V4 use full replay (already correct, ms-fast at 10k). V5 adds snapshots behind the same interface
— a pure optimization proven by property test. If V5 is cut, the design is still explainable and nothing breaks.

**Cut order if behind:** V5 status-change diff → Prices tab → Upload log → V5 entirely. Never cut engine tests.

---

## 8. Test plan (pytest)

**Portfolio / engine**
- Golden: brief example → exact §4 figures.
- Arrival-order independence: shuffled arrivals of unique valid trades → same final state.
- Avg cost resets after full close + reopen.
- Over-sell rejected; state unchanged.
- Over-buy (insufficient cash) rejected.
- Late trade invalidates a previously applied later trade (status flips, event emitted).
- Precision: buy 0.1 + 0.2 → qty exactly 0.3; sell all → total cost exactly 0.

**Value objects / ingestion**
- Each value object rejects invalid construction (sign, dp limits, bad side, bad timestamp).
- Each row-level code produced by a corresponding bad row.
- Missing column → whole file rejected.
- Partially invalid file → valid rows still processed.
- Identical duplicate ignored; conflicting duplicate rejected, first wins.
- Same file uploaded twice → state unchanged (idempotent).

**Market data / valuation**
- Latest price by timestamp, not arrival.
- Missing price → Unavailable + totals incomplete.
- Price for un-held symbol stored but doesn't affect totals.

**State machine / SMR properties**
- Determinism: same input log applied twice → identical state (compare by hash).
- Snapshot equivalence: after every command, incremental replay == full replay.
- Recovery: restore snapshot + replay log tail == live state.

---

## 9. Review prep

**Information flow:** CSV → Ingestion (ACL) → commands stamped with seq → Input Log → Ledger
(dedupe/conflicts, PriceBook) → Timeline sorted (ts, seq) → Portfolio state machine (+ snapshots)
→ Valuation → UI read models.

**Scale (100×+):**
- DB with unique constraints on `trade_id` and `(symbol, ts)`.
- Durable snapshots; late trade replays only from nearest prior checkpoint.
- PriceBook keeps only latest per symbol (O(symbols)), updated incrementally.
- Streaming/batched ingestion; log in Kafka/Raft.
- Caveat: symbols are independent *except* via cash (cash check couples them) — limits per-symbol partitioning.

**Likely requirement changes → where they land:**
| Change | Lands in |
|---|---|
| Fees | BUY/SELL transition (one place) |
| FIFO | Cost-basis strategy on Position (lots instead of total cost) |
| Allow shorting | Remove one guard; handle negative qty / avg cost semantics |
| Cancellations | New command/event type → replay |
| Multi-currency | FX observations in PriceBook; Valuation converts |
| As-of view | Stop replay at T (snapshots make it cheap) |
| Margin | Relax cash guard; add borrowing cost |

**Known limitations (README):** no persistence; single portfolio; first-seen wins conflicts with no
UI resolution; same-timestamp ties ordered by arrival; no auth/audit; replication designed for but not implemented.
