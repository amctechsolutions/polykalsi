#!/usr/bin/env python3
"""arb-obs: read-only Kalshi<->Polymarket cross-venue edge observation instrument.

NO execution capability. This process only ever opens outbound WebSocket
connections and issues GET requests. See tests/test_static_scan.py, which
fails the build if any order-placement path is introduced here.

Hosts below are sourced from live docs fetched under US-ARB-OBS-01 Task 0
(commit message / operator report carries the exact doc URLs):
  - Kalshi WS:  docs.kalshi.com/getting_started/quick_start_websockets
  - Kalshi auth: docs.kalshi.com/getting_started/quick_start_authenticated_requests
  - Polymarket WS: docs.polymarket.com/api-reference/wss/market

KALSHI_REST_BASE has NO hardcoded default, by deliberate choice, not gap:
Task 1.5 (2026-08-30) confirmed it live as
https://external-api.kalshi.com/trade-api/v2 (demo:
https://external-api.demo.kalshi.co/trade-api/v2), per
docs.kalshi.com/getting_started/quick_start_authenticated_requests. It
stays operator-supplied via env var rather than hardcoded here so a
demo/prod mixup is a config-time decision, not a silent code default.
"""
import argparse
import asyncio
import base64
import json
import logging
import os
import random
import resource
import signal
import time
from decimal import Decimal
from pathlib import Path

import websockets
import yaml
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from arb_common import FEE_MODEL_VERSION, kalshi_fee_per_contract_c1, loads_decimal, net_edge, polymarket_fee
from edge_engine import EdgeEngine
from startup_checks import (
    StartupAbort,
    assert_kalshi_key_read_only,
    assert_kalshi_not_demo,
    assert_memory_headroom,
    assert_no_poly_env,
    load_and_validate_pairs,
    scan_for_stray_secrets,
)

log = logging.getLogger("arb-obs")

ARB_ROOT = Path(__file__).resolve().parent
KALSHI_WS_HOST = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
KALSHI_WS_PATH = "/trade-api/ws/v2"
POLY_WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

RECONNECT_BASE_S = 2
RECONNECT_CAP_S = 30
RECONNECT_ESCALATE_AFTER = 5
HEARTBEAT_INTERVAL_S = 10
SOFT_MEM_WARN_MB = 180
CHECKPOINT_INTERVAL_S = 300


# --------------------------------------------------------------------------
# Kalshi RSA-PSS auth (GET only — never used to sign an order request)
# --------------------------------------------------------------------------

def load_kalshi_private_key(pem_path):
    with open(pem_path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)


def kalshi_sign(private_key, timestamp_ms, method, path):
    message = f"{timestamp_ms}{method}{path}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def kalshi_auth_headers(private_key, api_key_id, method, path):
    timestamp_ms = str(int(time.time() * 1000))
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        "KALSHI-ACCESS-SIGNATURE": kalshi_sign(private_key, timestamp_ms, method, path),
    }


def fetch_kalshi_key_scopes(rest_base, private_key, api_key_id):
    """One-time GET at startup only, to satisfy the fail-closed read-only-key
    assertion. Uses stdlib urllib, not a new dependency.

    rest_base is documented/configured as the FULL versioned base
    (https://external-api.kalshi.com/trade-api/v2) — path below is the
    domain-root-relative path Kalshi's signature scheme requires. Building
    the request URL as rest_base + path double-counts "/trade-api/v2" (a
    real bug caught live under Task 1.5's Kalshi capture, 2026-08-30: it
    404'd against the real API). Fixed by deriving scheme+host from
    rest_base and joining with `path` directly instead of string-concat."""
    import urllib.request
    from urllib.parse import urlsplit, urlunsplit

    path = "/trade-api/v2/api_keys"
    headers = kalshi_auth_headers(private_key, api_key_id, "GET", path)
    origin = urlsplit(rest_base)
    url = urlunsplit((origin.scheme, origin.netloc, path, "", ""))
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    candidates = payload.get("api_keys", payload if isinstance(payload, list) else [])
    for key_obj in candidates:
        if key_obj.get("api_key_id") == api_key_id or key_obj.get("id") == api_key_id:
            return key_obj.get("scopes", [])
    raise StartupAbort(f"configured Kalshi key id {api_key_id!r} not found in api_keys response")


# --------------------------------------------------------------------------
# Reconnect backoff (US-16 house standard: 2s base, x2, cap 30s, jitter,
# escalate after 5 consecutive failures)
# --------------------------------------------------------------------------

class Backoff:
    def __init__(self, label):
        self.label = label
        self.failures = 0

    def reset(self):
        self.failures = 0

    async def wait(self):
        delay = min(RECONNECT_BASE_S * (2 ** self.failures), RECONNECT_CAP_S)
        delay *= 0.5 + random.random()
        self.failures += 1
        if self.failures >= RECONNECT_ESCALATE_AFTER:
            log.error("%s: %d consecutive reconnect failures (escalate)", self.label, self.failures)
        else:
            log.warning("%s: reconnect in %.1fs (failure #%d)", self.label, delay, self.failures)
        await asyncio.sleep(delay)


# --------------------------------------------------------------------------
# Kalshi orderbook client (single channel, per Task 0 decision (b): the
# orderbook_delta/orderbook_snapshot channel carries the sequence numbers
# needed for book_invalidated detection; top-of-book size is derived from
# the best array entry rather than also subscribing to `ticker`)
# --------------------------------------------------------------------------

class KalshiClient:
    def __init__(self, private_key, api_key_id, tickers, on_book_update, on_invalidated):
        self.private_key = private_key
        self.api_key_id = api_key_id
        self.tickers = tickers
        self.on_book_update = on_book_update
        self.on_invalidated = on_invalidated
        self.seq_by_ticker = {}

    async def run(self, stop_event):
        backoff = Backoff("kalshi")
        while not stop_event.is_set():
            try:
                await self._connect_once(stop_event)
                backoff.reset()
            except Exception:
                log.exception("kalshi ws error")
                for ticker in self.tickers:
                    self.on_invalidated(ticker)
                    self.seq_by_ticker.pop(ticker, None)
                if not stop_event.is_set():
                    await backoff.wait()

    async def _connect_once(self, stop_event):
        headers = kalshi_auth_headers(self.private_key, self.api_key_id, "GET", KALSHI_WS_PATH)
        async with websockets.connect(KALSHI_WS_HOST, additional_headers=headers) as ws:
            sub = {
                "id": 1,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": self.tickers,
                    "use_yes_price": True,  # pinned explicitly; Kalshi's own default is scheduled to flip
                },
            }
            await ws.send(json.dumps(sub))
            async for raw in ws:
                if stop_event.is_set():
                    return
                self._handle_message(raw)

    def _handle_message(self, raw):
        try:
            msg = loads_decimal(raw)
        except (ValueError, json.JSONDecodeError):
            log.warning("kalshi malformed message, invalidating all tracked books")
            for ticker in self.tickers:
                self.on_invalidated(ticker)
                self.seq_by_ticker.pop(ticker, None)
            return

        msg_type = msg.get("type")
        body = msg.get("msg", msg)
        ticker = body.get("market_ticker")
        if ticker is None:
            return

        if msg_type == "orderbook_snapshot":
            self.seq_by_ticker[ticker] = msg.get("seq")
            self.on_book_update(ticker, body, is_snapshot=True)
        elif msg_type == "orderbook_delta":
            expected = self.seq_by_ticker.get(ticker)
            seq = msg.get("seq")
            if expected is not None and seq is not None and seq != expected + 1:
                log.warning("kalshi seq gap on %s: expected %s got %s", ticker, expected + 1, seq)
                self.on_invalidated(ticker)
                self.seq_by_ticker.pop(ticker, None)
                return
            self.seq_by_ticker[ticker] = seq
            self.on_book_update(ticker, body, is_snapshot=False)
        # subscribed-ack / error message types intentionally ignored


# --------------------------------------------------------------------------
# Polymarket public market client
# --------------------------------------------------------------------------

class PolymarketClient:
    def __init__(self, asset_ids, on_book_update, on_invalidated):
        self.asset_ids = asset_ids
        self.on_book_update = on_book_update
        self.on_invalidated = on_invalidated

    async def run(self, stop_event):
        backoff = Backoff("polymarket")
        while not stop_event.is_set():
            try:
                await self._connect_once(stop_event)
                backoff.reset()
            except Exception:
                log.exception("polymarket ws error")
                for asset_id in self.asset_ids:
                    self.on_invalidated(asset_id)
                if not stop_event.is_set():
                    await backoff.wait()

    async def _connect_once(self, stop_event):
        async with websockets.connect(POLY_WS_HOST) as ws:
            await ws.send(json.dumps({"assets_ids": self.asset_ids, "type": "market"}))
            heartbeat = asyncio.create_task(self._heartbeat_loop(ws, stop_event))
            try:
                async for raw in ws:
                    if stop_event.is_set():
                        return
                    self._handle_message(raw)
            finally:
                heartbeat.cancel()

    async def _heartbeat_loop(self, ws, stop_event):
        while not stop_event.is_set():
            await asyncio.sleep(HEARTBEAT_INTERVAL_S)
            await ws.send("PING")

    def _handle_message(self, raw):
        """`book` events carry a top-level asset_id + full bids/asks arrays
        (snapshot). `price_change` events do NOT: they carry a top-level
        `price_changes` array bundling deltas for multiple asset_ids at
        once, each entry giving best_bid/best_ask directly (no size at that
        level) — confirmed by live capture under US-ARB-OBS-01 Task 1.5,
        2026-08-30; see tests/fixtures/polymarket_price_change.json. An
        earlier draft of this client wrongly assumed both shapes matched."""
        if raw == "PONG":
            return
        try:
            msg = loads_decimal(raw)
        except (ValueError, json.JSONDecodeError):
            log.warning("polymarket malformed message")
            return
        events = msg if isinstance(msg, list) else [msg]
        for event in events:
            event_type = event.get("event_type")
            if event_type == "book":
                asset_id = event.get("asset_id")
                if asset_id is not None:
                    self.on_book_update(asset_id, event, is_snapshot=True)
            elif event_type == "price_change":
                for change in event.get("price_changes", []):
                    asset_id = change.get("asset_id")
                    if asset_id is not None:
                        self.on_book_update(asset_id, change, is_snapshot=False)


# --------------------------------------------------------------------------
# Pure Polymarket message parsers (no I/O, no state) — kept standalone so
# tests/test_static_scan-adjacent live-fixture tests can call them directly
# against a captured raw message without spinning up the Orchestrator.
# --------------------------------------------------------------------------

def parse_pm_book_snapshot(event):
    """`book` event: top-level asks=[{price,size},...]. Returns (price,
    size) of the best (lowest) ask as Decimals, or None if no asks."""
    asks = event.get("asks", [])
    if not asks:
        return None
    best = min(asks, key=lambda lvl: Decimal(lvl["price"]))
    return Decimal(best["price"]), Decimal(best["size"])


def parse_pm_price_change(change, fallback_size):
    """One entry of a `price_change` event's `price_changes` array: gives
    best_ask directly, but NOT its size. size is carried forward from the
    last snapshot/delta until the next `book` re-snapshot (Polymarket
    re-sends one after every trade per docs) resyncs it — a known,
    documented approximation, not silently assumed correct."""
    best_ask = change.get("best_ask")
    if best_ask is None:
        return None
    return Decimal(best_ask), (fallback_size if fallback_size is not None else Decimal("0"))


# --------------------------------------------------------------------------
# Pure Kalshi orderbook_delta/orderbook_snapshot parsers. Confirmed live
# under US-ARB-OBS-01 Task 1.5, 2026-08-30 (tests/fixtures/kalshi_*.json):
#
# orderbook_snapshot.msg = {market_ticker, market_id,
#   yes_dollars_fp: [[price_str, size_str], ...],   # yes-side BID ladder
#   no_dollars_fp:  [[price_str, size_str], ...]}   # no-side BID ladder
#
# orderbook_delta.msg = {market_ticker, market_id,
#   price_dollars, delta_fp, side ("yes"|"no"), ts, ts_ms}
#
# An earlier draft assumed body["yes"]/body["no"] (wrong field names) AND
# that every message carried a full level array (wrong — orderbook_delta
# is a single incremental mutation against PERSISTENT per-market book
# state that must be maintained here; without it, deltas would silently
# no-op forever after the first snapshot, freezing the recorded Kalshi
# price at whatever it was at startup). Both bugs are fixed by keeping
# state.k_yes_levels/k_no_levels as live dict[Decimal, Decimal] books
# (see PairState) built from parse_kalshi_snapshot_levels and mutated by
# apply_kalshi_delta.
#
# Since Kalshi's orderbook has no separate ask ladder for a binary market,
# a NO-side bid at price X is a synthetic YES ask at (1-X) — this mirrors
# the no_proxy handling already used elsewhere for the reverse direction.
# --------------------------------------------------------------------------

def parse_kalshi_snapshot_levels(levels_raw):
    return {Decimal(price): Decimal(size) for price, size in levels_raw}


def apply_kalshi_delta(levels, price, delta):
    """Mutates `levels` (dict[Decimal, Decimal]) in place."""
    new_size = levels.get(price, Decimal("0")) + delta
    if new_size <= 0:
        levels.pop(price, None)
    else:
        levels[price] = new_size


def best_kalshi_level(levels):
    """Best (highest-price) resting bid level. Returns (price, size) or None."""
    if not levels:
        return None
    best_price = max(levels.keys())
    return best_price, levels[best_price]


# --------------------------------------------------------------------------
# Wiring: pairs.yaml -> per-pair quote state -> EdgeEngine ticks
# --------------------------------------------------------------------------

class PairState:
    def __init__(self, pair_cfg):
        self.cfg = pair_cfg
        self.k_yes_bid = self.k_yes_ask = None
        self.k_yes_bid_size = self.k_yes_ask_size = None
        self.k_yes_levels = {}  # Decimal(price) -> Decimal(size), yes-side bid ladder
        self.k_no_levels = {}   # Decimal(price) -> Decimal(size), no-side bid ladder
        self.k_valid = False
        self.k_last_update = None
        self.pm_yes_ask = self.pm_no_ask = None
        self.pm_yes_ask_size = self.pm_no_ask_size = None
        self.pm_valid = False
        self.pm_last_update = None
        self.pm_fee_rate = pair_cfg.get("pm_fee_rate")


class Orchestrator:
    def __init__(self, pairs_cfg, edge_engine):
        self.edge_engine = edge_engine
        self.pairs_by_kalshi_ticker = {}
        self.pairs_by_pm_asset = {}
        self.pair_states = {}
        for p in pairs_cfg["pairs"]:
            if not p.get("enabled", False):
                continue
            state = PairState(p)
            self.pair_states[p["pair_id"]] = state
            self.pairs_by_kalshi_ticker[p["kalshi_ticker"]] = p["pair_id"]
            self.pairs_by_pm_asset[p["polymarket_yes_token_id"]] = (p["pair_id"], "yes")
            self.pairs_by_pm_asset[p["polymarket_no_token_id"]] = (p["pair_id"], "no")

    def on_kalshi_update(self, ticker, body, is_snapshot, monotonic_now):
        pair_id = self.pairs_by_kalshi_ticker.get(ticker)
        if pair_id is None:
            return
        state = self.pair_states[pair_id]
        if is_snapshot:
            state.k_yes_levels = parse_kalshi_snapshot_levels(body.get("yes_dollars_fp", []))
            state.k_no_levels = parse_kalshi_snapshot_levels(body.get("no_dollars_fp", []))
        else:
            side = body.get("side")
            price = Decimal(body["price_dollars"])
            delta = Decimal(body["delta_fp"])
            levels = state.k_yes_levels if side == "yes" else state.k_no_levels
            apply_kalshi_delta(levels, price, delta)

        best_yes = best_kalshi_level(state.k_yes_levels)
        best_no = best_kalshi_level(state.k_no_levels)
        if best_yes is not None:
            state.k_yes_bid, state.k_yes_bid_size = best_yes
        if best_no is not None:
            # best NO bid at price X implies a synthetic YES ask at (1 - X)
            state.k_yes_ask = Decimal("1") - best_no[0]
            state.k_yes_ask_size = best_no[1]
        state.k_valid = True
        state.k_last_update = monotonic_now
        self._recompute(pair_id, monotonic_now)

    def on_kalshi_invalidated(self, ticker, monotonic_now):
        pair_id = self.pairs_by_kalshi_ticker.get(ticker)
        if pair_id is None:
            return
        state = self.pair_states[pair_id]
        state.k_valid = False
        state.k_yes_levels = {}
        state.k_no_levels = {}
        self.edge_engine.handle_book_invalidated(pair_id, "kalshi_yes_pm_no", monotonic_now)
        self.edge_engine.handle_book_invalidated(pair_id, "kalshi_no_proxy_pm_yes", monotonic_now)

    def on_pm_update(self, asset_id, event, is_snapshot, monotonic_now):
        entry = self.pairs_by_pm_asset.get(asset_id)
        if entry is None:
            return
        pair_id, side = entry
        state = self.pair_states[pair_id]
        if is_snapshot:
            result = parse_pm_book_snapshot(event)
        else:
            existing_size = state.pm_yes_ask_size if side == "yes" else state.pm_no_ask_size
            result = parse_pm_price_change(event, fallback_size=existing_size)
        if result is not None:
            price, size = result
            if side == "yes":
                state.pm_yes_ask, state.pm_yes_ask_size = price, size
            else:
                state.pm_no_ask, state.pm_no_ask_size = price, size
        state.pm_valid = True
        state.pm_last_update = monotonic_now
        self._recompute(pair_id, monotonic_now)

    def on_pm_invalidated(self, asset_id, monotonic_now):
        entry = self.pairs_by_pm_asset.get(asset_id)
        if entry is None:
            return
        pair_id, _side = entry
        state = self.pair_states[pair_id]
        state.pm_valid = False
        self.edge_engine.handle_book_invalidated(pair_id, "kalshi_yes_pm_no", monotonic_now)
        self.edge_engine.handle_book_invalidated(pair_id, "kalshi_no_proxy_pm_yes", monotonic_now)

    def _recompute(self, pair_id, monotonic_now):
        state = self.pair_states[pair_id]
        both_valid = state.k_valid and state.pm_valid
        k_age_ms = int((monotonic_now - state.k_last_update) * 1000) if state.k_last_update else None
        pm_age_ms = int((monotonic_now - state.pm_last_update) * 1000) if state.pm_last_update else None
        book_fresh_flags = {"kalshi": state.k_valid, "polymarket": state.pm_valid}
        have_quotes = None not in (state.k_yes_bid, state.k_yes_ask, state.pm_yes_ask, state.pm_no_ask)

        for direction, no_proxy in (("kalshi_yes_pm_no", False), ("kalshi_no_proxy_pm_yes", True)):
            if not (both_valid and have_quotes):
                self.edge_engine.on_tick(
                    pair_id, direction, no_proxy, True, {}, None, False,
                    k_age_ms, pm_age_ms, book_fresh_flags, monotonic_now,
                )
                continue

            if direction == "kalshi_yes_pm_no":
                leg_a_ask, leg_b_ask, kalshi_price = state.k_yes_ask, state.pm_no_ask, state.k_yes_ask
                exec_size = min(state.k_yes_ask_size, state.pm_no_ask_size)
            else:
                leg_a_ask = Decimal("1") - state.k_yes_bid  # synthetic Kalshi NO ask, no_proxy
                leg_b_ask, kalshi_price = state.pm_yes_ask, leg_a_ask
                exec_size = min(state.k_yes_bid_size, state.pm_yes_ask_size)

            kfee = kalshi_fee_per_contract_c1(kalshi_price)
            pmfee = (
                polymarket_fee(Decimal("1"), leg_b_ask, state.pm_fee_rate)
                if state.pm_fee_rate is not None
                else Decimal("0")
            )
            edge = net_edge(leg_a_ask, leg_b_ask, kfee, pmfee)

            quote = {
                "k_yes_bid": state.k_yes_bid, "k_yes_ask": state.k_yes_ask,
                "k_yes_bid_size": state.k_yes_bid_size, "k_yes_ask_size": state.k_yes_ask_size,
                "pm_yes_ask": state.pm_yes_ask, "pm_no_ask": state.pm_no_ask,
                "pm_yes_ask_size": state.pm_yes_ask_size, "pm_no_ask_size": state.pm_no_ask_size,
                "executable_top_size": exec_size,
                "kalshi_fee_per_contract_c1": kfee, "pm_fee": pmfee,
                "fee_model_version": FEE_MODEL_VERSION,
                "k_book_age_ms": k_age_ms, "pm_book_age_ms": pm_age_ms,
                "book_fresh_flags": book_fresh_flags,
            }
            self.edge_engine.on_tick(
                pair_id, direction, no_proxy, True, quote, edge, True,
                k_age_ms, pm_age_ms, book_fresh_flags, monotonic_now,
            )


# --------------------------------------------------------------------------
# Startup + main
# --------------------------------------------------------------------------

def run_startup_checks(config):
    assert_no_poly_env(os.environ)
    assert_kalshi_not_demo(KALSHI_WS_HOST)
    assert_memory_headroom(min_mb=512)
    scan_for_stray_secrets(ARB_ROOT, declared_kalshi_key_path=Path(config["kalshi_private_key_path"]))
    pairs_cfg = load_and_validate_pairs(config["pairs_path"])
    scopes = fetch_kalshi_key_scopes(
        config["kalshi_rest_base"],
        load_kalshi_private_key(config["kalshi_private_key_path"]),
        config["kalshi_api_key_id"],
    )
    assert_kalshi_key_read_only(scopes)
    return pairs_cfg


async def periodic_checkpoint(edge_engine, start_monotonic, stop_event):
    while not stop_event.is_set():
        await asyncio.sleep(CHECKPOINT_INTERVAL_S)
        elapsed_hours = (time.monotonic() - start_monotonic) / 3600
        report = edge_engine.checkpoint(elapsed_hours)
        log.info("checkpoint: %s", json.dumps(report))
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if rss_mb > SOFT_MEM_WARN_MB:
            log.warning("RSS %.0fMB exceeds soft warning threshold %dMB", rss_mb, SOFT_MEM_WARN_MB)


async def async_main(config):
    pairs_cfg = run_startup_checks(config)

    edge_engine = EdgeEngine(config["ledger_path"], config["state_path"])
    start_monotonic = time.monotonic()
    orphans = edge_engine.reconcile_orphans(start_monotonic)
    if orphans:
        log.warning("startup reconciliation closed %d orphaned open event(s)", orphans)

    orchestrator = Orchestrator(pairs_cfg, edge_engine)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    kalshi_tickers = list(orchestrator.pairs_by_kalshi_ticker.keys())
    pm_asset_ids = list(orchestrator.pairs_by_pm_asset.keys())

    private_key = load_kalshi_private_key(config["kalshi_private_key_path"])
    kalshi_client = KalshiClient(
        private_key, config["kalshi_api_key_id"], kalshi_tickers,
        lambda ticker, body, is_snapshot: orchestrator.on_kalshi_update(ticker, body, is_snapshot, time.monotonic()),
        lambda ticker: orchestrator.on_kalshi_invalidated(ticker, time.monotonic()),
    )
    poly_client = PolymarketClient(
        pm_asset_ids,
        lambda asset_id, event, is_snapshot: orchestrator.on_pm_update(asset_id, event, is_snapshot, time.monotonic()),
        lambda asset_id: orchestrator.on_pm_invalidated(asset_id, time.monotonic()),
    )

    tasks = [
        asyncio.create_task(kalshi_client.run(stop_event)),
        asyncio.create_task(poly_client.run(stop_event)),
        asyncio.create_task(periodic_checkpoint(edge_engine, start_monotonic, stop_event)),
    ]

    await stop_event.wait()
    log.info("shutdown signal received, flushing open events")
    edge_engine.handle_shutdown(time.monotonic())
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def build_config():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default=str(ARB_ROOT / "pairs.yaml"))
    parser.add_argument("--ledger", default=str(ARB_ROOT / "edge_ledger.jsonl"))
    parser.add_argument("--state", default=str(ARB_ROOT / "open_state.json"))
    args = parser.parse_args()
    return {
        "pairs_path": args.pairs,
        "ledger_path": args.ledger,
        "state_path": args.state,
        "kalshi_api_key_id": os.environ["KALSHI_API_KEY_ID"],
        "kalshi_private_key_path": os.environ["KALSHI_PRIVATE_KEY_PATH"],
        "kalshi_rest_base": os.environ["KALSHI_REST_BASE"],
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = build_config()
        asyncio.run(async_main(config))
    except StartupAbort as exc:
        log.error("fail-closed startup abort: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
