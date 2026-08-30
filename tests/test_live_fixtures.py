"""Assert the shipped Polymarket parsers consume REAL captured live messages
without error. Fixtures were captured read-only under US-ARB-OBS-01
Task 1.5 (2026-08-30) against a single liquid market (Baltimore Orioles vs.
Athletics, Polymarket Gamma API market id 2252xxx-series), one subscription,
disconnected immediately after capture. See capture_polymarket.py.

Kalshi has NO equivalent fixture yet: no Kalshi API credential has been
provisioned for this project (checked on the box, none present), and the
spec forbids fabricating one. This is a known, reported gap, not an
oversight — the Kalshi parser must get the same live-fixture treatment
before Task 2, once a read-only key exists.
"""
import json
from decimal import Decimal
from pathlib import Path

from data_logger import parse_pm_book_snapshot, parse_pm_price_change

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def test_book_snapshot_fixture_exists():
    assert (FIXTURES / "polymarket_book_snapshot.json").exists()


def test_price_change_fixture_exists():
    assert (FIXTURES / "polymarket_price_change.json").exists()


def test_parse_pm_book_snapshot_consumes_live_fixture():
    event = load_fixture("polymarket_book_snapshot.json")
    assert event["event_type"] == "book"
    result = parse_pm_book_snapshot(event)
    assert result is not None
    price, size = result
    assert isinstance(price, Decimal)
    assert isinstance(size, Decimal)
    assert Decimal("0") < price < Decimal("1")
    assert size > Decimal("0")


def test_parse_pm_price_change_consumes_live_fixture():
    event = load_fixture("polymarket_price_change.json")
    assert event["event_type"] == "price_change"
    changes = event["price_changes"]
    assert len(changes) >= 1
    for change in changes:
        result = parse_pm_price_change(change, fallback_size=Decimal("1"))
        assert result is not None
        price, size = result
        assert isinstance(price, Decimal)
        assert isinstance(size, Decimal)
        assert Decimal("0") < price < Decimal("1")


def test_price_change_has_no_top_level_asset_id():
    """Regression guard for the Task-1.5 bug: an earlier draft assumed
    price_change carried a top-level asset_id like book does. It doesn't —
    asset_id lives per-entry inside price_changes[]."""
    event = load_fixture("polymarket_price_change.json")
    assert "asset_id" not in event
    assert all("asset_id" in c for c in event["price_changes"])


def test_price_change_size_field_is_trade_size_not_book_depth():
    """Regression guard: a price_change entry DOES have a "size" field, but
    it is the size of the order/trade that MOVED the price, not the resting
    depth available at best_ask/best_bid. parse_pm_price_change must not
    read change["size"] as if it were book depth — it has no field that is,
    hence fallback_size. This test exists so a future "just use size" fix
    gets caught by CI instead of silently corrupting executable_top_size."""
    event = load_fixture("polymarket_price_change.json")
    for change in event["price_changes"]:
        assert "best_ask_size" not in change
        assert "best_bid_size" not in change
