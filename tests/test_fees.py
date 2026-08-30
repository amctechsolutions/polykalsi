from decimal import Decimal

import pytest

from arb_common import kalshi_fee, kalshi_fee_per_contract_c1, net_edge, polymarket_fee


def test_kalshi_fee_per_contract_064():
    assert kalshi_fee_per_contract_c1(Decimal("0.64")) == Decimal("0.02")


def test_kalshi_fee_per_contract_010():
    assert kalshi_fee_per_contract_c1(Decimal("0.10")) == Decimal("0.01")


def test_kalshi_fee_size_aware_100_at_050():
    # total-then-ceil, NOT per-contract-fee * 100 (see arb_common.kalshi_fee docstring)
    assert kalshi_fee(Decimal("100"), Decimal("0.50")) == Decimal("1.75")


def test_kalshi_fee_size_aware_differs_from_naive_multiply():
    per_contract = kalshi_fee_per_contract_c1(Decimal("0.50"))
    naive = per_contract * Decimal("100")
    total = kalshi_fee(Decimal("100"), Decimal("0.50"))
    assert naive == Decimal("2.00")
    assert total == Decimal("1.75")
    assert naive != total


def test_net_edge_basic():
    edge = net_edge(Decimal("0.40"), Decimal("0.55"), Decimal("0.02"), Decimal("0.01"))
    assert edge == Decimal("0.02")


def test_net_edge_requires_decimal():
    with pytest.raises(TypeError):
        net_edge(0.40, Decimal("0.55"), Decimal("0.02"), Decimal("0.01"))


# Worked examples verbatim from docs.polymarket.com/trading/fees (Crypto
# feeRate=0.07), confirmed live under Task 1.5, 2026-08-30.

def test_polymarket_fee_worked_example_050():
    assert polymarket_fee(Decimal("100"), Decimal("0.50"), Decimal("0.07")) == Decimal("1.75000")


def test_polymarket_fee_worked_example_030():
    assert polymarket_fee(Decimal("100"), Decimal("0.30"), Decimal("0.07")) == Decimal("1.47000")


def test_polymarket_fee_worked_example_070_symmetric():
    # docs explicitly note a trade at 30c incurs the same dollar fee as 70c
    assert polymarket_fee(Decimal("100"), Decimal("0.70"), Decimal("0.07")) == Decimal("1.47000")


def test_polymarket_fee_geopolitics_is_zero():
    assert polymarket_fee(Decimal("100"), Decimal("0.50"), Decimal("0")) == Decimal("0.00000")
