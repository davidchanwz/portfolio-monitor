"""Display formatting. Rounding happens only here; the domain keeps full precision."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

UNAVAILABLE = "Unavailable"


def fmt_decimal(value: Decimal | None, dp: int, *, min_dp: int | None = None, signed: bool = False) -> str:
    if value is None:
        return UNAVAILABLE
    rounded = value.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)
    if rounded == 0:
        rounded = abs(rounded)  # never show "-0.00"
    shown_dp = dp
    if min_dp is not None:
        exponent = rounded.normalize().as_tuple().exponent
        shown_dp = max(min_dp, min(dp, -exponent if isinstance(exponent, int) else dp))
    text = f"{rounded:,.{shown_dp}f}"
    return f"+{text}" if signed and rounded > 0 else text


def fmt_money(value: Decimal | None, *, signed: bool = False) -> str:
    return fmt_decimal(value, 2, signed=signed)


def fmt_price(value: Decimal | None) -> str:
    return fmt_decimal(value, 6, min_dp=2)


def fmt_quantity(value: Decimal | None) -> str:
    return fmt_decimal(value, 8, min_dp=0)
