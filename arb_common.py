"""Decimal-only math primitives shared by the arb-obs instrument.

No float is ever permitted to enter fee or edge calculations. JSON payloads
from both venues must be decoded with `loads_decimal` (parse_float=Decimal)
so a stray float can never even be constructed from wire data.
"""
import json
from decimal import Decimal, ROUND_CEILING

CENT = Decimal("0.01")
KALSHI_FEE_RATE = Decimal("0.07")
FEE_MODEL_VERSION = "pm-fee-v1-rate-exponent"


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


def polymarket_fee(contracts, price, rate, exponent):
    """Placeholder formula pending confirmation against a live
    GET /clob-markets/{condition_id} response (Task 0 only verified the
    rate/exponent/takerOnly/rebateRate FIELDS exist, not Polymarket's exact
    fee formula). Mirrors the Kalshi quadratic-against-extremes shape so it
    is at least directionally sane; fee_model_version is recorded on every
    ledger row precisely so this can be revised without corrupting history."""
    require_decimal(contracts, "contracts")
    require_decimal(price, "price")
    require_decimal(rate, "rate")
    base = price * (Decimal("1") - price)
    raw = rate * (base ** exponent) * contracts
    return ceil_to_cent(raw)


def net_edge(leg_a_ask, leg_b_ask, kalshi_fee_amount, pm_fee):
    for v, n in (
        (leg_a_ask, "leg_a_ask"),
        (leg_b_ask, "leg_b_ask"),
        (kalshi_fee_amount, "kalshi_fee_amount"),
        (pm_fee, "pm_fee"),
    ):
        require_decimal(v, n)
    return Decimal("1") - leg_a_ask - leg_b_ask - kalshi_fee_amount - pm_fee
