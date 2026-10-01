# Portfolio Monitor

## Background

Our investment team holds positions in financial instruments and executes trades throughout the day. They currently use spreadsheets to understand the portfolio’s current state.

We would like a small application that processes portfolio activity and gives the team a clear, current view of its holdings and performance.

You have three hours to produce a working prototype.

## Inputs

A portfolio begins with a cash balance.

The application will receive trades with the following fields:

| Field | Description |
|---|---|
| `trade_id` | Identifier supplied by the source system |
| `timestamp` | Time at which the trade occurred |
| `symbol` | Instrument identifier |
| `side` | `BUY` or `SELL` |
| `quantity` | Number of units traded |
| `price` | Execution price per unit |

It will also receive market-price observations:

| Field | Description |
|---|---|
| `timestamp` | Time of the observation |
| `symbol` | Instrument identifier |
| `price` | Observed market price |

You may choose an appropriate method for entering or loading this information. You do not need to connect to a real market-data provider.

Assume all monetary values are denominated in USD.

## Required functionality

A user should be able to:

1. Create or initialize a portfolio with a cash balance.
2. Record trades.
3. record market-price observations.
4. View the portfolio’s current positions.
5. View, for each position:
   - quantity held;
   - average acquisition price;
   - latest market price;
   - market value;
   - unrealized profit or loss.
6. View:
   - current cash;
   - total market value;
   - total portfolio value;
   - realized profit or loss.
7. Inspect the trades that have been processed.
8. Understand when an input could not be processed and why.

The application should behave sensibly when data is duplicated, invalid, missing, or received in an unexpected order.

## Example data

The portfolio begins with `10,000 USD`.

### Trades

```csv
trade_id,timestamp,symbol,side,quantity,price
T001,2026-10-02T09:00:00,AAPL,BUY,10,100
T002,2026-10-02T09:15:00,MSFT,BUY,5,200
T004,2026-10-02T11:30:00,AAPL,SELL,8,120
T003,2026-10-02T10:00:00,AAPL,BUY,5,110
T004,2026-10-02T11:30:00,AAPL,SELL,8,120
```

### Market prices

```csv
timestamp,symbol,price
2026-10-02T10:00:00,AAPL,112
2026-10-02T12:00:00,AAPL,125
2026-10-02T12:00:00,MSFT,195
2026-10-02T11:00:00,AAPL,118
```

The example data is illustrative. Your application should not be limited to these instruments or records.

## Deliverable

Produce a runnable application that demonstrates the primary workflow from input through portfolio calculation to presentation.

The interface may be a web application, desktop application, command-line program, or another form you consider appropriate.

Please include:

- instructions for running the application;
- automated tests for important behaviour;
- a short explanation of your design;
- assumptions you made;
- known limitations or unfinished work.

You may use any programming language, libraries, development tools, online resources, or AI coding assistants.

You do not need to implement authentication, deployment infrastructure, or integration with external financial systems.

## Review

At the end of the exercise, we will ask you to:

1. Demonstrate the application.
2. Explain how information flows through the system.
3. Explain the portfolio calculations.
4. Discuss assumptions and edge cases.
5. Describe the trade-offs you made under the time constraint.
6. Make or discuss a small change to the requirements.
