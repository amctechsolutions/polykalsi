"""One-off read-only capture script for Task 1.5 item 3. NOT part of the
shipped instrument — run manually, once, then delete/ignore. Subscribes to
exactly one liquid market's YES token, saves the first 'book' snapshot and
first 'price_change' delta to tests/fixtures/, then disconnects."""
import asyncio
import json
import sys

import websockets

POLY_WS_HOST = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
YES_TOKEN_ID = "5630818831549356726302724271139359195392953403478032399036743244616719599069"


async def main():
    got_snapshot = False
    got_delta = False
    async with websockets.connect(POLY_WS_HOST) as ws:
        await ws.send(json.dumps({"assets_ids": [YES_TOKEN_ID], "type": "market"}))
        deadline = asyncio.get_event_loop().time() + 90
        while (not got_snapshot or not got_delta) and asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if raw == "PONG":
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            events = msg if isinstance(msg, list) else [msg]
            for event in events:
                etype = event.get("event_type")
                if etype == "book" and not got_snapshot:
                    with open("tests/fixtures/polymarket_book_snapshot.json", "w") as f:
                        json.dump(event, f, indent=2)
                    got_snapshot = True
                    print("captured book snapshot", file=sys.stderr)
                elif etype == "price_change" and not got_delta:
                    with open("tests/fixtures/polymarket_price_change.json", "w") as f:
                        json.dump(event, f, indent=2)
                    got_delta = True
                    print("captured price_change delta", file=sys.stderr)
    print(f"done: snapshot={got_snapshot} delta={got_delta}", file=sys.stderr)


asyncio.run(main())
