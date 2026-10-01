from decimal import Decimal

from portfolio_monitor.application.service import PortfolioService

TRADE_HEADER = "trade_id,timestamp,symbol,side,quantity,price\n"
PRICE_HEADER = "timestamp,symbol,price\n"

EXAMPLE_TRADES = TRADE_HEADER + (
    "T001,2026-10-02T09:00:00,AAPL,BUY,10,100\n"
    "T002,2026-10-02T09:15:00,MSFT,BUY,5,200\n"
    "T004,2026-10-02T11:30:00,AAPL,SELL,8,120\n"
    "T003,2026-10-02T10:00:00,AAPL,BUY,5,110\n"
    "T004,2026-10-02T11:30:00,AAPL,SELL,8,120\n"
)
EXAMPLE_PRICES = PRICE_HEADER + (
    "2026-10-02T10:00:00,AAPL,112\n"
    "2026-10-02T12:00:00,AAPL,125\n"
    "2026-10-02T12:00:00,MSFT,195\n"
    "2026-10-02T11:00:00,AAPL,118\n"
)


def D(value) -> Decimal:
    return Decimal(str(value))


def money(value: Decimal) -> Decimal:
    """Round to cents the way the UI displays it."""
    return value.quantize(Decimal("0.01"))


def make_service(trades: str | None = None, prices: str | None = None, cash: str = "10000") -> PortfolioService:
    svc = PortfolioService()
    svc.initialize(cash)
    if trades is not None:
        svc.upload_trades("trades.csv", trades)
    if prices is not None:
        svc.upload_prices("prices.csv", prices)
    return svc


def trades_csv(*rows: str) -> str:
    return TRADE_HEADER + "".join(f"{r}\n" for r in rows)


def prices_csv(*rows: str) -> str:
    return PRICE_HEADER + "".join(f"{r}\n" for r in rows)
