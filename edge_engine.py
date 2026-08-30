"""Edge open/close state machine, ledger writer, and exposure accrual.

One EdgeEngine instance tracks all (pair_id, direction) keys. It is fed
normalized ticks by data_logger.py and is otherwise ignorant of Kalshi/
Polymarket wire formats.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Tuple

EDGE_OPEN_THRESHOLD = Decimal("-0.005")
BOOK_STALE_MS = 5000
PERSIST_THRESHOLD_MS = 250

Key = Tuple[str, str]  # (market_pair_id, direction)


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _decimal_default(obj):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj)}")


@dataclass
class OpenEvent:
    ts_open: str
    open_monotonic: float
    market_pair_id: str
    direction: str
    no_proxy: bool
    use_yes_price: bool
    net_edge_at_open: Decimal
    net_edge_peak: Decimal
    quote: dict
    persisted_250ms: bool = False

    def to_state_dict(self):
        d = {
            "ts_open": self.ts_open,
            "market_pair_id": self.market_pair_id,
            "direction": self.direction,
            "no_proxy": self.no_proxy,
            "use_yes_price": self.use_yes_price,
            "net_edge_at_open": str(self.net_edge_at_open),
            "net_edge_peak": str(self.net_edge_peak),
            "quote": {k: str(v) if isinstance(v, Decimal) else v for k, v in self.quote.items()},
            "persisted_250ms": self.persisted_250ms,
        }
        return d

    @classmethod
    def from_state_dict(cls, d, monotonic_now):
        quote = {}
        for k, v in d["quote"].items():
            try:
                quote[k] = Decimal(v)
            except Exception:
                quote[k] = v
        return cls(
            ts_open=d["ts_open"],
            open_monotonic=monotonic_now,  # wall-clock is authoritative for orphans; see reconcile_orphans
            market_pair_id=d["market_pair_id"],
            direction=d["direction"],
            no_proxy=d["no_proxy"],
            use_yes_price=d["use_yes_price"],
            net_edge_at_open=Decimal(d["net_edge_at_open"]),
            net_edge_peak=Decimal(d["net_edge_peak"]),
            quote=quote,
            persisted_250ms=d.get("persisted_250ms", False),
        )


class LedgerWriter:
    def __init__(self, path):
        self.path = Path(path)

    def append(self, row: dict):
        with open(self.path, "a") as f:
            f.write(json.dumps(row, default=_decimal_default) + "\n")


class PairExposure:
    __slots__ = ("observed_pair_ms", "qualifying_edge_ms", "events_count")

    def __init__(self):
        self.observed_pair_ms = 0
        self.qualifying_edge_ms = 0
        self.events_count = 0


class EdgeEngine:
    def __init__(self, ledger_path, state_path):
        self.ledger = LedgerWriter(ledger_path)
        self.state_path = Path(state_path)
        self.open_events: Dict[Key, OpenEvent] = {}
        self.exposure: Dict[str, PairExposure] = {}
        self._last_tick_monotonic: Dict[Key, float] = {}

    # ---- startup reconciliation ----

    def reconcile_orphans(self, monotonic_now):
        """Any event left in the persisted state file at process start was
        open when the PREVIOUS run died without a clean SIGTERM/SIGINT
        (kill -9, OOM, crash) — a clean shutdown already writes a
        close_reason=shutdown row and clears state. Close each as
        orphan_recovered using wall-clock survival, since monotonic time is
        not meaningful across a process restart."""
        if not self.state_path.exists():
            return 0
        raw = self.state_path.read_text().strip()
        if not raw:
            return 0
        state = json.loads(raw)
        count = 0
        for key_str, ev_dict in state.items():
            ev = OpenEvent.from_state_dict(ev_dict, monotonic_now)
            ts_close = utc_now_iso()
            try:
                opened = datetime.fromisoformat(ev.ts_open)
                closed = datetime.fromisoformat(ts_close)
                survival_ms = int((closed - opened).total_seconds() * 1000)
            except ValueError:
                survival_ms = None
            self._write_close_row(ev, ts_close, survival_ms, "orphan_recovered")
            count += 1
        self.open_events.clear()
        self._persist_state()
        return count

    # ---- state persistence (for orphan recovery across restarts) ----

    def _persist_state(self):
        state = {f"{k[0]}|{k[1]}": ev.to_state_dict() for k, ev in self.open_events.items()}
        self.state_path.write_text(json.dumps(state))

    # ---- core tick handling ----

    def on_tick(self, market_pair_id, direction, no_proxy, use_yes_price, quote,
                net_edge_value, both_books_valid, k_book_age_ms, pm_book_age_ms,
                book_fresh_flags, monotonic_now):
        key = (market_pair_id, direction)
        self._accrue_exposure(key, monotonic_now, both_books_valid, net_edge_value)

        existing = self.open_events.get(key)

        if not both_books_valid:
            if existing is not None:
                self._close(key, monotonic_now, "book_stale" if self._is_stale(k_book_age_ms, pm_book_age_ms) else "book_invalidated")
            return

        qualifies = net_edge_value >= EDGE_OPEN_THRESHOLD

        if existing is None:
            if qualifies:
                ev = OpenEvent(
                    ts_open=utc_now_iso(),
                    open_monotonic=monotonic_now,
                    market_pair_id=market_pair_id,
                    direction=direction,
                    no_proxy=no_proxy,
                    use_yes_price=use_yes_price,
                    net_edge_at_open=net_edge_value,
                    net_edge_peak=net_edge_value,
                    quote=dict(quote),
                )
                self.open_events[key] = ev
                self._persist_state()
            return

        # existing open event
        if not qualifies:
            self._close(key, monotonic_now, "edge_closed")
            return

        existing.net_edge_peak = max(existing.net_edge_peak, net_edge_value)
        existing.quote = dict(quote)
        survival_so_far_ms = (monotonic_now - existing.open_monotonic) * 1000
        if survival_so_far_ms >= PERSIST_THRESHOLD_MS:
            existing.persisted_250ms = True
        self._persist_state()

    def _is_stale(self, k_age_ms, pm_age_ms):
        return (k_age_ms is not None and k_age_ms > BOOK_STALE_MS) or \
               (pm_age_ms is not None and pm_age_ms > BOOK_STALE_MS)

    def handle_book_invalidated(self, market_pair_id, direction, monotonic_now):
        key = (market_pair_id, direction)
        if key in self.open_events:
            self._close(key, monotonic_now, "book_invalidated")

    def handle_shutdown(self, monotonic_now):
        for key in list(self.open_events.keys()):
            self._close(key, monotonic_now, "shutdown")

    def _close(self, key, monotonic_now, close_reason):
        ev = self.open_events.pop(key, None)
        if ev is None:
            return
        survival_ms = int((monotonic_now - ev.open_monotonic) * 1000)
        ts_close = utc_now_iso()
        self._write_close_row(ev, ts_close, survival_ms, close_reason)
        self._persist_state()

    def _write_close_row(self, ev: OpenEvent, ts_close, survival_ms, close_reason):
        row = {
            "ts_open": ev.ts_open,
            "ts_close": ts_close,
            "market_pair_id": ev.market_pair_id,
            "direction": ev.direction,
            "no_proxy": ev.no_proxy,
            "net_edge_at_open": ev.net_edge_at_open,
            "net_edge_peak": ev.net_edge_peak,
            "survival_ms": survival_ms,
            "persisted_250ms": ev.persisted_250ms,
            "close_reason": close_reason,
            "use_yes_price": ev.use_yes_price,
            **ev.quote,
        }
        self.ledger.append(row)
        pe = self.exposure.setdefault(ev.market_pair_id, PairExposure())
        if close_reason == "edge_closed":
            pe.events_count += 1

    # ---- exposure accrual ----

    def _accrue_exposure(self, key, monotonic_now, both_books_valid, net_edge_value):
        last = self._last_tick_monotonic.get(key)
        self._last_tick_monotonic[key] = monotonic_now
        if last is None:
            return
        elapsed_ms = (monotonic_now - last) * 1000
        if elapsed_ms <= 0:
            return
        pe = self.exposure.setdefault(key[0], PairExposure())
        # accrue based on state BEFORE this tick (both_books_valid/net_edge_value
        # passed in reflect the state that was current for the just-elapsed interval)
        if both_books_valid:
            pe.observed_pair_ms += elapsed_ms
            if net_edge_value is not None and net_edge_value >= EDGE_OPEN_THRESHOLD:
                pe.qualifying_edge_ms += elapsed_ms

    def checkpoint(self, wall_hours_elapsed: float):
        """events per pair-hour and edge occupancy, for the periodic checkpoint log."""
        report = {}
        for pair_id, pe in self.exposure.items():
            events_per_pair_hour = pe.events_count / wall_hours_elapsed if wall_hours_elapsed > 0 else 0.0
            occupancy = (pe.qualifying_edge_ms / pe.observed_pair_ms) if pe.observed_pair_ms > 0 else 0.0
            report[pair_id] = {
                "events_per_pair_hour": events_per_pair_hour,
                "edge_occupancy": occupancy,
                "observed_pair_ms": pe.observed_pair_ms,
                "qualifying_edge_ms": pe.qualifying_edge_ms,
            }
        return report
