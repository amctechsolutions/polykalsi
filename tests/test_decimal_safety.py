from decimal import Decimal

import pytest

from arb_common import ceil_to_cent, kalshi_fee, loads_decimal, polymarket_fee, require_decimal


def test_require_decimal_rejects_float():
    with pytest.raises(TypeError):
        require_decimal(0.5, "x")


def test_require_decimal_rejects_int():
    with pytest.raises(TypeError):
        require_decimal(1, "x")


def test_require_decimal_accepts_decimal():
    assert require_decimal(Decimal("0.5"), "x") == Decimal("0.5")


def test_ceil_to_cent_rejects_float():
    with pytest.raises(TypeError):
        ceil_to_cent(0.0175)


def test_kalshi_fee_rejects_float_contracts():
    with pytest.raises(TypeError):
        kalshi_fee(100.0, Decimal("0.50"))


def test_kalshi_fee_rejects_float_price():
    with pytest.raises(TypeError):
        kalshi_fee(Decimal("100"), 0.50)


def test_polymarket_fee_rejects_float_rate():
    with pytest.raises(TypeError):
        polymarket_fee(Decimal("1"), Decimal("0.5"), 0.04)


def test_loads_decimal_never_produces_float():
    payload = loads_decimal('{"price": 0.64, "size": 100, "nested": [0.1, 0.2]}')
    assert isinstance(payload["price"], Decimal)
    assert isinstance(payload["nested"][0], Decimal)
    assert not any(isinstance(v, float) for v in _walk(payload))


def _walk(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)
    else:
        yield obj
