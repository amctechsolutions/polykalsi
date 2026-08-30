"""Bug 2/3 fix, 2026-08-30: seq is scoped per subscription-id (sid), shared
across all tickers on that sid, NOT per ticker — a prior implementation
tracked it per ticker and produced continuous false gaps on any connection
with 2+ tickers (verified against ~90 minutes of live production logs).
A book must also stay invalid until a REAL orderbook_snapshot arrives, not
just the next delta. See the extensive comment above KalshiClient in
data_logger.py and tests/fixtures/kalshi_multi_sid_seq_evidence.json (live
capture backing this fix).
"""
import asyncio
import json
from pathlib import Path

import pytest

from data_logger import KalshiClient

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def make_client():
    updates = []
    invalidations = []
    client = KalshiClient(
        private_key=None,
        api_key_id="dummy",
        tickers=["TICKER-A", "TICKER-B"],
        on_book_update=lambda ticker, body, is_snapshot: updates.append((ticker, is_snapshot)),
        on_invalidated=lambda ticker: invalidations.append(ticker),
    )
    client._ws = FakeWS()
    return client, updates, invalidations


def run(coro):
    return asyncio.run(coro)


def snapshot_msg(sid, seq, ticker):
    return json.dumps({"type": "orderbook_snapshot", "sid": sid, "seq": seq,
                        "msg": {"market_ticker": ticker, "yes_dollars_fp": [], "no_dollars_fp": []}})


def delta_msg(sid, seq, ticker):
    return json.dumps({"type": "orderbook_delta", "sid": sid, "seq": seq,
                        "msg": {"market_ticker": ticker, "price_dollars": "0.50", "delta_fp": "1", "side": "yes"}})


def ok_ack_msg(sid, seq, tickers):
    return json.dumps({"type": "ok", "id": 2, "sid": sid, "seq": seq, "msg": {"market_tickers": tickers}})


def test_no_false_gap_across_interleaved_tickers_sharing_one_sid():
    """Regression guard for the actual bug: ticker A snapshot (seq=1), an
    'ok' ack from a merged subscribe consuming seq=2 (no market_ticker in
    its body, so the old per-ticker tracker never saw it), ticker B
    snapshot (seq=3) — must NOT be flagged as a gap on either ticker."""
    client, updates, invalidations = make_client()

    async def go():
        client.sid = 1
        await client._handle_message(snapshot_msg(1, 1, "TICKER-A"))
        await client._handle_message(ok_ack_msg(1, 2, ["TICKER-A", "TICKER-B"]))
        await client._handle_message(snapshot_msg(1, 3, "TICKER-B"))

    run(go())
    assert invalidations == []
    assert ("TICKER-A", True) in updates
    assert ("TICKER-B", True) in updates


def test_replays_live_captured_fixture_with_no_false_gap():
    """End-to-end against the actual live-captured wire evidence, not a
    hand-constructed approximation of it."""
    fixture = json.loads((FIXTURES / "kalshi_multi_sid_seq_evidence.json").read_text())
    client, updates, invalidations = make_client()

    async def go():
        for key in ("snapshot_ticker_a_seq1", "merged_subscribe_ok_response", "snapshot_ticker_b_seq3"):
            await client._handle_message(json.dumps(fixture[key]))

    run(go())
    assert invalidations == []


def test_real_gap_is_detected_and_invalidates_all_tickers():
    client, updates, invalidations = make_client()

    async def go():
        client.sid = 1
        await client._handle_message(snapshot_msg(1, 1, "TICKER-A"))
        await client._handle_message(snapshot_msg(1, 2, "TICKER-B"))
        await client._handle_message(delta_msg(1, 9, "TICKER-A"))  # real gap: expected 3, got 9

    run(go())
    assert set(invalidations) == {"TICKER-A", "TICKER-B"}
    assert client.awaiting_snapshot == {"TICKER-A", "TICKER-B"}


def test_real_gap_triggers_get_snapshot_request():
    client, updates, invalidations = make_client()

    async def go():
        client.sid = 1
        await client._handle_message(snapshot_msg(1, 1, "TICKER-A"))
        await client._handle_message(delta_msg(1, 9, "TICKER-A"))

    run(go())
    sent = client._ws.sent
    assert any(m.get("cmd") == "update_subscription" and m["params"].get("action") == "get_snapshot" for m in sent)


def test_delta_dropped_while_awaiting_snapshot():
    client, updates, invalidations = make_client()

    async def go():
        client.sid = 1
        await client._handle_message(snapshot_msg(1, 1, "TICKER-A"))
        await client._handle_message(delta_msg(1, 9, "TICKER-A"))  # triggers invalidation
        updates.clear()
        await client._handle_message(delta_msg(1, 10, "TICKER-A"))  # still awaiting snapshot

    run(go())
    assert updates == []  # the delta must be dropped, not forwarded


def test_validity_restored_only_by_real_snapshot_not_by_delta():
    """The actual bug: an earlier implementation set k_valid=True on ANY
    subsequent update. Here we assert the book only leaves awaiting_snapshot
    when a real orderbook_snapshot arrives."""
    client, updates, invalidations = make_client()

    async def go():
        client.sid = 1
        await client._handle_message(snapshot_msg(1, 1, "TICKER-A"))
        await client._handle_message(delta_msg(1, 9, "TICKER-A"))  # invalidates
        assert "TICKER-A" in client.awaiting_snapshot
        await client._handle_message(delta_msg(1, client.expected_seq + 1, "TICKER-A"))
        assert "TICKER-A" in client.awaiting_snapshot  # still not restored
        await client._handle_message(snapshot_msg(1, client.expected_seq + 1, "TICKER-A"))
        assert "TICKER-A" not in client.awaiting_snapshot  # NOW restored

    run(go())


def test_malformed_message_invalidates_all_and_requests_snapshots():
    client, updates, invalidations = make_client()

    async def go():
        client.sid = 1
        await client._handle_message(snapshot_msg(1, 1, "TICKER-A"))
        await client._handle_message("not json")

    run(go())
    assert set(invalidations) == {"TICKER-A", "TICKER-B"}
    assert any(m["params"].get("action") == "get_snapshot" for m in client._ws.sent)
