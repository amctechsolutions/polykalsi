"""One-off read-only capture script for Task 1.5 item 3 (Kalshi half). NOT
part of the shipped instrument. Subscribes to exactly one liquid market's
orderbook channel (use_yes_price pinned true, matching data_logger.py),
saves the first orderbook_snapshot and first orderbook_delta to
tests/fixtures/, then disconnects. Uses the read-only key verified via
fetch_kalshi_key_scopes (scopes == ['read'])."""
import asyncio
import json
import os
import sys

import websockets

from data_logger import KALSHI_WS_HOST, KALSHI_WS_PATH, kalshi_auth_headers, load_kalshi_private_key

TICKER = "KXEPLGAME-26AUG30MUNIPS-MUN"
API_KEY_ID = os.environ["KALSHI_API_KEY_ID"]
PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "/root/arb-secrets/kalshi_key.txt")


async def main():
    got_snapshot = False
    got_delta = False
    private_key = load_kalshi_private_key(PRIVATE_KEY_PATH)
    headers = kalshi_auth_headers(private_key, API_KEY_ID, "GET", KALSHI_WS_PATH)
    async with websockets.connect(KALSHI_WS_HOST, additional_headers=headers) as ws:
        sub = {
            "id": 1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": [TICKER],
                "use_yes_price": True,
            },
        }
        await ws.send(json.dumps(sub))
        deadline = asyncio.get_event_loop().time() + 60
        while (not got_snapshot or not got_delta) and asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
            except asyncio.TimeoutError:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                print("non-JSON message:", raw[:200], file=sys.stderr)
                continue
            msg_type = msg.get("type")
            print("received type:", msg_type, file=sys.stderr)
            if msg_type == "orderbook_snapshot" and not got_snapshot:
                with open("tests/fixtures/kalshi_orderbook_snapshot.json", "w") as f:
                    json.dump(msg, f, indent=2)
                got_snapshot = True
                print("captured orderbook_snapshot", file=sys.stderr)
            elif msg_type == "orderbook_delta" and not got_delta:
                with open("tests/fixtures/kalshi_orderbook_delta.json", "w") as f:
                    json.dump(msg, f, indent=2)
                got_delta = True
                print("captured orderbook_delta", file=sys.stderr)
            elif msg_type not in ("orderbook_snapshot", "orderbook_delta"):
                print("other message:", json.dumps(msg)[:300], file=sys.stderr)
    print(f"done: snapshot={got_snapshot} delta={got_delta}", file=sys.stderr)


asyncio.run(main())
