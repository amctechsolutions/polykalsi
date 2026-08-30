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
from edge_engine import EDGE_OPEN_THRESHOLD, EdgeEngine
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
GAMMA_API_HOST = "https://gamma-api.polymarket.com"  # public, unauthenticated, no POLY* env involved

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
#
# SEQ SCOPE, corrected 2026-08-30 (post-launch Bug 2/3 fix): `seq` is
# scoped per SUBSCRIPTION ID (sid), not per market ticker, and not a
# per-connection-wide counter either — confirmed against
# docs.kalshi.com/asyncapi.yaml ("Sequential number... used for
# snapshot/delta consistency", appearing alongside `sid`) AND live capture
# (tests/fixtures/kalshi_multi_sid_seq_evidence.json): subscribing two
# tickers produced sid=1 for both, with seq incrementing 1,2,3,4 across
# EVERY message under that sid regardless of type or which ticker it's
# about (snapshot, an "ok" ack from a second subscribe merging into the
# same sid, another snapshot, a get_snapshot response — all consumed a
# seq number). A second `subscribe` call on an already-subscribed
# connection does NOT create an independent sid; Kalshi merges the new
# tickers into the existing one. So this client tracks ONE expected_seq
# for the whole connection, checked against every message that carries a
# seq field, not per-ticker.
#
# An earlier implementation tracked seq per ticker, which produced a false
# "gap" every time a DIFFERENT ticker's message consumed an intervening
# seq number — with 2 tickers subscribed this fired every 30-90 seconds
# continuously (verified against ~90 minutes of live production logs),
# each time wiping that ticker's book to empty and (see next paragraph)
# incorrectly marking it valid again on the very next delta.
#
# BOOK VALIDITY, corrected: a book must stay invalid until a REAL
# orderbook_snapshot is received — not until the next delta, which was
# the actual bug that let a wiped, empty-then-sparse-rebuilt-from-deltas
# book get silently trusted again within seconds. On any seq gap (or
# malformed message, or reconnect), this client marks every currently
# tracked ticker as awaiting a fresh snapshot, drops any delta for a
# ticker still awaiting one, and ACTIVELY requests a fresh snapshot via
# Kalshi's update_subscription/get_snapshot command (wire-verified live,
# same fixture file) rather than passively waiting for one that might
# never arrive spontaneously mid-connection.
# --------------------------------------------------------------------------

class KalshiClient:
    def __init__(self, private_key, api_key_id, tickers, on_book_update, on_invalidated):
        self.private_key = private_key
        self.api_key_id = api_key_id
        self.tickers = tickers
        self.on_book_update = on_book_update
        self.on_invalidated = on_invalidated
        self.expected_seq = None
        self.awaiting_snapshot = set()
        self.sid = None
        self._ws = None
        self._next_cmd_id = 100

    async def run(self, stop_event):
        backoff = Backoff("kalshi")
        while not stop_event.is_set():
            try:
                await self._connect_once(stop_event)
                backoff.reset()
            except Exception:
                log.exception("kalshi ws error")
                self._invalidate_all()
                if not stop_event.is_set():
                    await backoff.wait()

    async def _connect_once(self, stop_event):
        self.expected_seq = None
        self.awaiting_snapshot = set(self.tickers)
        self.sid = None
        headers = kalshi_auth_headers(self.private_key, self.api_key_id, "GET", KALSHI_WS_PATH)
        async with websockets.connect(KALSHI_WS_HOST, additional_headers=headers) as ws:
            self._ws = ws
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
                await self._handle_message(raw)

    def _invalidate_all(self):
        for ticker in self.tickers:
            self.on_invalidated(ticker)
        self.awaiting_snapshot = set(self.tickers)
        self.expected_seq = None

    async def _request_fresh_snapshots(self):
        if self._ws is None:
            return
        self._next_cmd_id += 1
        cmd = {
            "id": self._next_cmd_id,
            "cmd": "update_subscription",
            "params": {"market_tickers": self.tickers, "action": "get_snapshot"},
        }
        if self.sid is not None:
            cmd["params"]["sid"] = self.sid
        try:
            await self._ws.send(json.dumps(cmd))
        except Exception:
            log.exception("kalshi get_snapshot resync request failed")

    async def _handle_message(self, raw):
        try:
            msg = loads_decimal(raw)
        except (ValueError, json.JSONDecodeError):
            log.warning("kalshi malformed message, invalidating all tracked books")
            self._invalidate_all()
            await self._request_fresh_snapshots()
            return

        if msg.get("type") == "subscribed":
            self.sid = msg.get("msg", {}).get("sid")
            return

        seq = msg.get("seq")
        if seq is not None:
            if self.expected_seq is not None and seq != self.expected_seq + 1:
                log.warning("kalshi seq gap (sid=%s): expected %s got %s", self.sid, self.expected_seq + 1, seq)
                self._invalidate_all()
                await self._request_fresh_snapshots()
            self.expected_seq = seq
            if msg.get("sid") is not None:
                self.sid = msg["sid"]

        msg_type = msg.get("type")
        body = msg.get("msg", msg)
        ticker = body.get("market_ticker")
        if ticker is None:
            return  # "ok" acks etc. carry no per-ticker body

        if msg_type == "orderbook_snapshot":
            self.awaiting_snapshot.discard(ticker)
            self.on_book_update(ticker, body, is_snapshot=True)
        elif msg_type == "orderbook_delta":
            if ticker in self.awaiting_snapshot:
                return  # book not trustworthy yet; seq already tracked above
            self.on_book_update(ticker, body, is_snapshot=False)
        # other message types (error, etc.) intentionally ignored


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


def parse_pm_market_metadata(payload):
    """payload: the JSON list from GET /markets?condition_ids={id} on
    gamma-api. Returns a compact dict of the per-market fee-related fields
    Polymarket exposes, or {} if the market wasn't found.

    NOT used to compute pm_fee — Task 1.5 (round 3, 2026-08-30) found these
    fields do not differentiate by category (a Crypto market and a
    Politics market both returned identical takerBaseFee/makerBaseFee), so
    they cannot be trusted as the fee INPUT; pairs.yaml's operator-verified
    pm_fee_rate (sourced from the venue's own UI) is the actual input to
    polymarket_fee(). This is recorded purely for audit: if this raw
    metadata ever starts actually differentiating by category, or drifts
    from what pm_fee_rate asserts, that discrepancy is visible in every
    ledger row instead of silently lost."""
    if not payload:
        return {}
    m = payload[0]
    return {"takerBaseFee": m.get("takerBaseFee"), "makerBaseFee": m.get("makerBaseFee")}


def fetch_pm_market_metadata(condition_id):
    """One-time GET at startup per enabled pair. Public, unauthenticated.

    Explicit User-Agent required: gamma-api.polymarket.com 403s bare
    urllib requests (default "Python-urllib/x.y" UA), confirmed live
    during the v3 pre-flight dry run, 2026-08-30 — not an auth issue,
    a bot-mitigation rule in front of the public endpoint."""
    import urllib.request

    url = f"{GAMMA_API_HOST}/markets?condition_ids={condition_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "arb-obs/1.0 (+read-only observation instrument)"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return parse_pm_market_metadata(payload)


# --------------------------------------------------------------------------
# Pure Kalshi orderbook_delta/orderbook_snapshot parsers. Confirmed live
# under US-ARB-OBS-01 Task 1.5, 2026-08-30 (tests/fixtures/kalshi_*.json):
#
# orderbook_snapshot.msg = {market_ticker, market_id,
#   yes_dollars_fp: [[price_str, size_str], ...],   # yes-side BID ladder
#   no_dollars_fp:  [[price_str, size_str], ...]}   # SEE WARNING BELOW
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
# CRITICAL, caught by the v3 pre-flight dry run (2026-08-30) via a REST
# /markets/{ticker}/orderbook cross-check: because this client subscribes
# with use_yes_price=True, no_dollars_fp's price field is NOT the native
# no-contract price — Kalshi has ALREADY transformed it to its
# yes-price-equivalent (native_no_price -> 1 - native_no_price) before
# sending. An earlier draft treated it as a native no-bid ladder and
# additionally computed yes_ask = 1 - max(no_levels), a DOUBLE transform
# that turned a true yes_ask of 0.52 into a computed 0.01 — a ~50x error
# that would silently open a phantom "edge" on nearly every tick, with
# every defense (seq continuity, book age) reporting perfectly healthy
# the entire time. The correct read: no_dollars_fp's prices are already
# yes-ask-equivalent, and the LOWEST price in that array is the best
# (cheapest, most competitive) synthetic yes ask — no further arithmetic.
# See best_kalshi_yes_ask() below; do not reintroduce a "1 - price" here.
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
    """Best (highest-price) resting BID level — correct for the yes-side
    ladder (yes_dollars_fp), which use_yes_price does not transform.
    Returns (price, size) or None."""
    if not levels:
        return None
    best_price = max(levels.keys())
    return best_price, levels[best_price]


def best_kalshi_yes_ask(no_levels):
    """no_dollars_fp under use_yes_price=True is already expressed in
    yes-price-equivalent terms (see the module comment above this
    section) — so the LOWEST price in this ladder is the best (cheapest)
    synthetic yes ask. No "1 - price" transform: that was the bug.
    Returns (price, size) or None."""
    if not no_levels:
        return None
    best_price = min(no_levels.keys())
    return best_price, no_levels[best_price]


# --------------------------------------------------------------------------
# Wiring: pairs.yaml -> per-pair quote state -> EdgeEngine ticks
# --------------------------------------------------------------------------

def parse_pm_fee_rate(pair_cfg):
    """pairs.yaml's pm_fee_rate MUST be written as a quoted YAML string
    (e.g. pm_fee_rate: "0.04"), never a bare number — YAML parses an
    unquoted numeric literal as a Python float, which require_decimal()
    correctly rejects at the first tick (caught live during the v3
    pre-flight dry run, 2026-08-30), but only after the process is already
    running. Fail closed at config-load time instead, with a message that
    tells the operator exactly what to fix, rather than a stack trace
    three hops downstream on the first live tick."""
    raw = pair_cfg.get("pm_fee_rate")
    if raw is None:
        return None
    if isinstance(raw, float):
        raise StartupAbort(
            f"pairs.yaml pm_fee_rate for pair_id={pair_cfg.get('pair_id')!r} is an unquoted "
            f"YAML number ({raw!r}), which parses as a float. Quote it as a string, e.g. "
            f'pm_fee_rate: "{raw}"'
        )
    return Decimal(raw)


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
        self.pm_fee_rate = parse_pm_fee_rate(pair_cfg)  # operator-verified, from the venue's own UI
        self.pm_fee_metadata_raw = {}  # untrustworthy API metadata, recorded for audit only


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
            state.pm_fee_metadata_raw = fetch_pm_market_metadata(p["polymarket_condition_id"])
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
        best_ask = best_kalshi_yes_ask(state.k_no_levels)
        if best_yes is not None:
            state.k_yes_bid, state.k_yes_bid_size = best_yes
        if best_ask is not None:
            state.k_yes_ask, state.k_yes_ask_size = best_ask
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
        """Two passes, deliberately: (1) compute both directions' edges
        without touching the EdgeEngine, so exposure can be accrued exactly
        ONCE per pair; (2) dispatch each direction to on_tick() for episode
        open/close tracking. A prior version accrued exposure inside the
        per-direction loop, which called it twice per tick and inflated
        observed_pair_ms/qualifying_edge_ms ~2x (Bug 1, 2026-08-30 fix)."""
        state = self.pair_states[pair_id]
        both_valid = state.k_valid and state.pm_valid
        k_age_ms = int((monotonic_now - state.k_last_update) * 1000) if state.k_last_update else None
        pm_age_ms = int((monotonic_now - state.pm_last_update) * 1000) if state.pm_last_update else None
        book_fresh_flags = {"kalshi": state.k_valid, "polymarket": state.pm_valid}
        have_quotes = None not in (state.k_yes_bid, state.k_yes_ask, state.pm_yes_ask, state.pm_no_ask)
        tickable = both_valid and have_quotes

        direction_results = []  # (direction, no_proxy, edge_or_None, quote)
        for direction, no_proxy in (("kalshi_yes_pm_no", False), ("kalshi_no_proxy_pm_yes", True)):
            if not tickable:
                direction_results.append((direction, no_proxy, None, {}))
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
                "pm_fee_rate_operator": state.pm_fee_rate,
                "pm_fee_metadata_raw": state.pm_fee_metadata_raw,
                "k_book_age_ms": k_age_ms, "pm_book_age_ms": pm_age_ms,
                "book_fresh_flags": book_fresh_flags,
            }
            direction_results.append((direction, no_proxy, edge, quote))

        any_qualifies = any(
            edge is not None and edge >= EDGE_OPEN_THRESHOLD for _, _, edge, _ in direction_results
        )
        self.edge_engine.accrue_pair_exposure(pair_id, monotonic_now, tickable, any_qualifies)

        for direction, no_proxy, edge, quote in direction_results:
            if edge is None:
                self.edge_engine.on_tick(
                    pair_id, direction, no_proxy, True, {}, None, False,
                    k_age_ms, pm_age_ms, book_fresh_flags, monotonic_now,
                )
            else:
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


def bump_restart_count(path):
    """Persisted across restarts, unlike anything in open_state.json (which
    is cleared on every clean shutdown). Every ledger row is stamped with
    the value this returns, so a specific episode can be correlated with
    which process lifetime produced it — independent of, and a cross-check
    against, pm2's own restart counter."""
    path = Path(path)
    try:
        count = int(path.read_text().strip()) if path.exists() else 0
    except (ValueError, OSError):
        count = 0
    count += 1
    path.write_text(str(count))
    return count


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

    restart_count = bump_restart_count(config["restart_count_path"])
    log.info("restart_count=%d", restart_count)
    edge_engine = EdgeEngine(config["ledger_path"], config["state_path"], restart_count=restart_count)
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
    parser.add_argument("--restart-count-path", default=str(ARB_ROOT / "restart_count.json"))
    args = parser.parse_args()
    return {
        "pairs_path": args.pairs,
        "ledger_path": args.ledger,
        "state_path": args.state,
        "restart_count_path": args.restart_count_path,
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
