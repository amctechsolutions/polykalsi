from decimal import Decimal

import pytest

from data_logger import parse_pm_fee_rate
from startup_checks import StartupAbort


def test_parse_pm_fee_rate_accepts_quoted_string():
    assert parse_pm_fee_rate({"pair_id": "p1", "pm_fee_rate": "0.04"}) == Decimal("0.04")


def test_parse_pm_fee_rate_none_when_absent():
    assert parse_pm_fee_rate({"pair_id": "p1"}) is None


def test_parse_pm_fee_rate_none_when_explicit_null():
    assert parse_pm_fee_rate({"pair_id": "p1", "pm_fee_rate": None}) is None


def test_parse_pm_fee_rate_rejects_unquoted_yaml_float():
    """Regression guard for the v3 pre-flight dry-run bug (2026-08-30): an
    unquoted pm_fee_rate: 0.04 in pairs.yaml parses as a Python float via
    yaml.safe_load, which used to reach polymarket_fee() and blow up on
    the first live tick instead of failing closed at config-load time."""
    with pytest.raises(StartupAbort):
        parse_pm_fee_rate({"pair_id": "p1", "pm_fee_rate": 0.04})
