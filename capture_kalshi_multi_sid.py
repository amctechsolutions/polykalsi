"""One-off read-only capture for the Bug 2/3 fix (2026-08-30): confirms `seq`
is shared per subscription-id (sid), not per market ticker, and confirms the
get_snapshot on-demand resync mechanism. NOT part of the shipped instrument.
"""
import asyncio
import json
import os
import sys

import websockets

from data_logger import KALSHI_WS_HOST, KALSHI_WS_PATH, kalshi_auth_headers, load_kalshi_private_key

API_KEY_ID = os.environ["KALSHI_API_KEY_ID"]
PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "/root/arb-secrets/kalshi_key.txt")
TICKER_A = "KXFEDDECISION-26SEP-H0"
TICKER_B = "KXGOVTSHUTDOWN-26OCT01"


async def main():
    key = load_kalshi_private_key(PRIVATE_KEY_PATH)
    headers = kalshi_auth_headers(key, API_KEY_ID, "GET", KALSHI_WS_PATH)
    captured = {}
    async with websockets.connect(KALSHI_WS_HOST, additional_headers=headers) as ws:
        await ws.send(json.dumps({
            "id": 1, "cmd": "subscribe",
            "params": {"channels": ["orderbook_delta"], "market_tickers": [TICKER_A], "use_yes_price": True},
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        captured["subscribe_ack_single_ticker"] = json.loads(raw)
        sid = captured["subscribe_ack_single_ticker"]["msg"]["sid"]

        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        captured["snapshot_ticker_a_seq1"] = json.loads(raw)

        await ws.send(json.dumps({
            "id": 2, "cmd": "subscribe",
            "params": {"channels": ["orderbook_delta"], "market_tickers": [TICKER_B], "use_yes_price": True},
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        captured["merged_subscribe_ok_response"] = json.loads(raw)

        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        captured["snapshot_ticker_b_seq3"] = json.loads(raw)

        await ws.send(json.dumps({
            "id": 3, "cmd": "update_subscription",
            "params": {"sid": sid, "market_tickers": [TICKER_A], "action": "get_snapshot"},
        }))
        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        captured["get_snapshot_response"] = json.loads(raw)

    with open("tests/fixtures/kalshi_multi_sid_seq_evidence.json", "w") as f:
        json.dump(captured, f, indent=2)
    print("captured", list(captured.keys()), file=sys.stderr)


asyncio.run(main())
