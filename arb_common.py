"""Decimal-only math primitives shared by the arb-obs instrument.

No float is ever permitted to enter fee or edge calculations. JSON payloads
from both venues must be decoded with `loads_decimal` (parse_float=Decimal)
so a stray float can never even be constructed from wire data.
"""
import json
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

CENT = Decimal("0.01")
FIVE_DP = Decimal("0.00001")
KALSHI_FEE_RATE = Decimal("0.07")
FEE_MODEL_VERSION = "pm-fee-v2-docs-2026-08-30"


def require_decimal(value, name="value"):
    if isinstance(value, float):
        raise TypeError(f"{name} must be Decimal, got float: {value!r}")
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}: {value!r}")
    return value


def loads_decimal(raw):
    """json.loads with all numeric literals parsed as Decimal, never float."""
    return json.loads(raw, parse_float=Decimal)


def ceil_to_cent(amount):
    require_decimal(amount, "amount")
    return amount.quantize(CENT, rounding=ROUND_CEILING)


def kalshi_fee(contracts, price):
    """Total Kalshi fee for `contracts` at `price`, ceil'd once on the total
    (not per-contract-then-multiplied) to avoid rounding drift on size."""
    require_decimal(contracts, "contracts")
    require_decimal(price, "price")
    raw = KALSHI_FEE_RATE * price * (Decimal("1") - price) * contracts
    return ceil_to_cent(raw)


def kalshi_fee_per_contract_c1(price):
    """The kalshi_fee_per_contract_c1 ledger field: fee at C=1, recorded per
    fill. Size-aware analysis must recompute via kalshi_fee(), not multiply
    this value by contract count (see kalshi_fee docstring)."""
    return kalshi_fee(Decimal("1"), price)


def polymarket_fee(contracts, price, fee_rate):
    """fee = C * feeRate * p * (1-p), per docs.polymarket.com/trading/fees
    (verified live under US-ARB-OBS-01 Task 1.5, 2026-08-30). No exponent
    term — an earlier Task-0 research summary claimed the CLOB market
    metadata exposes a rate/exponent/takerOnly/rebateRate shape; the fees
    page itself names neither "exponent" nor "takerOnly", so that summary
    was wrong and this formula supersedes it. Polymarket rounds fees to 5
    decimal places (not cent-ceiling like Kalshi); the exact rounding MODE
    isn't specified beyond "rounded", so ROUND_HALF_UP is a best-effort
    choice pending a live example that pins it down more precisely."""
    require_decimal(contracts, "contracts")
    require_decimal(price, "price")
    require_decimal(fee_rate, "fee_rate")
    raw = fee_rate * price * (Decimal("1") - price) * contracts
    return raw.quantize(FIVE_DP, rounding=ROUND_HALF_UP)


def net_edge(leg_a_ask, leg_b_ask, kalshi_fee_amount, pm_fee):
    for v, n in (
        (leg_a_ask, "leg_a_ask"),
        (leg_b_ask, "leg_b_ask"),
        (kalshi_fee_amount, "kalshi_fee_amount"),
        (pm_fee, "pm_fee"),
    ):
        require_decimal(v, n)
    return Decimal("1") - leg_a_ask - leg_b_ask - kalshi_fee_amount - pm_fee
