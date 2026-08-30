"""Assert the shipped Kalshi and Polymarket parsers consume REAL captured
live messages without error. Polymarket fixtures captured read-only under
Task 1.5 (2026-08-30) against a single liquid market (Baltimore Orioles vs.
Athletics), see capture_polymarket.py. Kalshi fixtures captured read-only
the same day, once a read-only-scoped key was provisioned (scopes
confirmed == ['read'] before this ran), against a single liquid live-game
market (Manchester United vs Ipswich Town, KXEPLGAME-26AUG30MUNIPS-MUN,
discovered via a live GET to the public /markets endpoint, not guessed —
see capture_kalshi.py.
"""
import json
from decimal import Decimal
from pathlib import Path

from data_logger import (
    apply_kalshi_delta,
    best_kalshi_level,
    parse_kalshi_snapshot_levels,
    parse_pm_book_snapshot,
    parse_pm_price_change,
)

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


# --------------------------------------------------------------------------
# Kalshi
# --------------------------------------------------------------------------

def test_kalshi_snapshot_fixture_exists():
    assert (FIXTURES / "kalshi_orderbook_snapshot.json").exists()


def test_kalshi_delta_fixture_exists():
    assert (FIXTURES / "kalshi_orderbook_delta.json").exists()


def test_kalshi_snapshot_field_names_are_dollars_fp_not_yes_no():
    """Regression guard for the Task-1.5 bug: an earlier draft read
    body["yes"]/body["no"]. The real fields are yes_dollars_fp/no_dollars_fp."""
    msg = load_fixture("kalshi_orderbook_snapshot.json")["msg"]
    assert "yes_dollars_fp" in msg
    assert "no_dollars_fp" in msg
    assert "yes" not in msg
    assert "no" not in msg


def test_parse_kalshi_snapshot_levels_consumes_live_fixture():
    msg = load_fixture("kalshi_orderbook_snapshot.json")["msg"]
    yes_levels = parse_kalshi_snapshot_levels(msg["yes_dollars_fp"])
    no_levels = parse_kalshi_snapshot_levels(msg["no_dollars_fp"])
    assert yes_levels and no_levels
    assert all(isinstance(p, Decimal) and isinstance(s, Decimal) for p, s in yes_levels.items())
    best_yes = best_kalshi_level(yes_levels)
    best_no = best_kalshi_level(no_levels)
    assert best_yes is not None and best_no is not None
    assert Decimal("0") < best_yes[0] < Decimal("1")
    assert Decimal("0") < best_no[0] < Decimal("1")


def test_kalshi_delta_is_a_single_mutation_not_a_full_array():
    """Regression guard for the bigger Task-1.5 bug: orderbook_delta does
    NOT carry yes_dollars_fp/no_dollars_fp — it's a single incremental
    (price_dollars, delta_fp, side) mutation against persistent book state
    an earlier draft never maintained, which would have frozen the
    recorded Kalshi price at snapshot-time forever."""
    msg = load_fixture("kalshi_orderbook_delta.json")["msg"]
    assert "yes_dollars_fp" not in msg
    assert "no_dollars_fp" not in msg
    assert {"price_dollars", "delta_fp", "side"} <= msg.keys()


def test_apply_kalshi_delta_against_live_snapshot_then_live_delta():
    """End-to-end: build book state from the real snapshot, apply the real
    captured delta, and confirm the resulting best-of-book is still sane
    (this is exactly the sequence data_logger.Orchestrator.on_kalshi_update
    performs)."""
    snapshot_msg = load_fixture("kalshi_orderbook_snapshot.json")["msg"]
    delta_msg = load_fixture("kalshi_orderbook_delta.json")["msg"]

    yes_levels = parse_kalshi_snapshot_levels(snapshot_msg["yes_dollars_fp"])
    no_levels = parse_kalshi_snapshot_levels(snapshot_msg["no_dollars_fp"])

    side = delta_msg["side"]
    price = Decimal(delta_msg["price_dollars"])
    delta = Decimal(delta_msg["delta_fp"])
    levels = yes_levels if side == "yes" else no_levels
    size_before = levels.get(price)
    apply_kalshi_delta(levels, price, delta)

    if size_before is not None and size_before + delta > 0:
        assert levels[price] == size_before + delta
    else:
        assert price not in levels  # level removed when size drops to <= 0

    best_yes = best_kalshi_level(yes_levels)
    best_no = best_kalshi_level(no_levels)
    assert best_yes is not None and best_no is not None
    yes_ask_from_no = Decimal("1") - best_no[0]
    assert Decimal("0") < yes_ask_from_no < Decimal("1")
