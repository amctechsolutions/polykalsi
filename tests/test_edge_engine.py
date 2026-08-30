import json
from decimal import Decimal

import pytest

from edge_engine import EdgeEngine


@pytest.fixture
def engine(tmp_path):
    return EdgeEngine(tmp_path / "ledger.jsonl", tmp_path / "state.json")


def read_ledger(engine):
    """Ledger rows serialize Decimal as str (never float, see edge_engine
    LedgerWriter). Parse back with Decimal so tests compare like-for-like."""
    if not engine.ledger.path.exists():
        return []
    rows = []
    for line in engine.ledger.path.read_text().splitlines():
        row = json.loads(line)
        for key in ("net_edge_at_open", "net_edge_peak"):
            if key in row and row[key] is not None:
                row[key] = Decimal(row[key])
        rows.append(row)
    return rows


def test_open_event_on_qualifying_edge(engine):
    engine.on_tick("p1", "dir_a", False, True, {"k_yes_ask": Decimal("0.5")},
                    Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    assert ("p1", "dir_a") in engine.open_events


def test_no_open_below_threshold(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("-0.02"), True, 0, 0, {}, monotonic_now=100.0)
    assert ("p1", "dir_a") not in engine.open_events
    assert read_ledger(engine) == []


def test_edge_closed_writes_row(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("-0.02"), True, 0, 0, {}, monotonic_now=100.5)
    rows = read_ledger(engine)
    assert len(rows) == 1
    assert rows[0]["close_reason"] == "edge_closed"
    assert rows[0]["survival_ms"] == 500
    assert ("p1", "dir_a") not in engine.open_events


def test_net_edge_peak_tracks_max(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.03"), True, 0, 0, {}, monotonic_now=100.1)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("-0.02"), True, 0, 0, {}, monotonic_now=100.2)
    rows = read_ledger(engine)
    assert rows[0]["net_edge_peak"] == Decimal("0.03")


def test_persisted_250ms_flag(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.3)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("-0.02"), True, 0, 0, {}, monotonic_now=100.4)
    rows = read_ledger(engine)
    assert rows[0]["persisted_250ms"] is True


def test_book_invalidated_closes_open_event(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    engine.handle_book_invalidated("p1", "dir_a", monotonic_now=100.2)
    rows = read_ledger(engine)
    assert len(rows) == 1
    assert rows[0]["close_reason"] == "book_invalidated"
    assert ("p1", "dir_a") not in engine.open_events


def test_book_stale_closes_via_invalid_tick(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    # both_books_valid=False with a stale age simulates the 5s staleness path
    engine.on_tick("p1", "dir_a", False, True, {}, None, False, 6000, 0, {}, monotonic_now=106.0)
    rows = read_ledger(engine)
    assert len(rows) == 1
    assert rows[0]["close_reason"] == "book_stale"


def test_shutdown_closes_all_open_events(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    engine.on_tick("p2", "dir_b", True, True, {}, Decimal("0.02"), True, 0, 0, {}, monotonic_now=100.0)
    engine.handle_shutdown(monotonic_now=101.0)
    rows = read_ledger(engine)
    assert len(rows) == 2
    assert all(r["close_reason"] == "shutdown" for r in rows)
    assert engine.open_events == {}


def test_orphan_recovered_on_restart(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    state_path = tmp_path / "state.json"

    engine1 = EdgeEngine(ledger_path, state_path)
    engine1.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    assert state_path.exists()
    # simulate a hard crash: state file left behind, no shutdown row written
    assert read_ledger(engine1) == []

    engine2 = EdgeEngine(ledger_path, state_path)
    closed = engine2.reconcile_orphans(monotonic_now=5.0)  # fresh process, monotonic clock reset
    assert closed == 1
    rows = read_ledger(engine2)
    assert len(rows) == 1
    assert rows[0]["close_reason"] == "orphan_recovered"
    assert engine2.open_events == {}


def test_survival_stats_only_from_edge_closed(engine):
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=100.0)
    engine.handle_book_invalidated("p1", "dir_a", monotonic_now=100.1)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("0.01"), True, 0, 0, {}, monotonic_now=101.0)
    engine.on_tick("p1", "dir_a", False, True, {}, Decimal("-0.02"), True, 0, 0, {}, monotonic_now=101.2)
    rows = read_ledger(engine)
    reasons = [r["close_reason"] for r in rows]
    assert reasons == ["book_invalidated", "edge_closed"]
