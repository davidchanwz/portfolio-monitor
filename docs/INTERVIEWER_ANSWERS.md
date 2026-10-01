# Interviewer Answers to Clarifying Questions

Verbatim responses from the interviewer. Anything not covered here falls back to the
assumed defaults recorded in [PLAN.md](PLAN.md) (marked **(A)**).

- **Arrival method:** For this prototype, trades and market prices arrive as CSV files in batches. Files may be uploaded more than once and records are not guaranteed to be ordered. Manual entry and streaming support are not required.
- **Scale:** Assume up to approximately 10,000 trades and 10,000 price observations in one batch. You should be prepared to discuss how the design would change at substantially larger scale, but you do not need to optimize for millions of records.
- **Timestamps:** Assume all timestamps use the same timezone and format. You may treat them as Singapore time. Daylight-saving handling is unnecessary.
- **Quantities and precision:** Quantities may be fractional, with up to eight decimal places. Prices may have up to six decimal places. Avoid behaviour that introduces visible floating-point inaccuracies.
- **Fees and commissions:** Ignore them for this exercise. Extensibility for fees is welcome but not required.
- **Cost basis:** Use weighted-average cost. When a position returns to zero, its average cost should reset.
- **Missing market prices:** Retain and display the position, but mark its current price, market value, and unrealized P&L as unavailable. Clearly indicate that the total portfolio valuation is incomplete; do not silently treat the missing value as zero.
- **Historical view:** Not required. We only need the current state and the processed-trade history.
- **Shorting:** Not allowed. Reject a sale that exceeds the quantity currently held.
- **Cancellations and amendments:** Out of scope.
- **Persistence:** The application does not need to retain data across restarts.
- **Intended user:** A human investment or operations team member. Prioritize clarity and explainability over providing a machine-facing API.
- **Duplicate trades:** An identical record with an already processed `trade_id` should not be applied twice. If the same identifier appears with different trade details, reject it and surface the conflict.
- **Ordering:** Determine trade state according to trade timestamps, not CSV row order. For market prices, use the most recent observation by timestamp.
- **Partially invalid files:** Valid rows should still be processed. Invalid or conflicting rows should be reported clearly enough for the user to identify and correct them.
