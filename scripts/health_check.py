#!/usr/bin/env python3
"""arb-obs read-only health check. Run via crontab (day-3, day-8 one-shots
during the 14-day HYP-ARB-01 window). Touches NOTHING belonging to the
running process or its state — only reads files pm2/data_logger.py already
write, plus pm2's own process table. Sends one Telegram message, then exits.

The only coupling to /root/rsibot is reading TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID out of its .env (grep-extracted, per the project's own
"never source rsibot's .env" rule — a multi-line PEM on line 3 breaks
`source`). No rsibot code is imported or invoked. This is the one
deliberate, minimal exception to arb-obs's zero-coupling design, made
because there is only one operational messaging channel on this box and
standing up a second one for a 14-day observation window isn't worth it.
"""
import json
import re
import subprocess
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ARB_ROOT = Path("/root/arb")
LEDGER_PATH = ARB_ROOT / "edge_ledger.jsonl"
RESTART_COUNT_PATH = ARB_ROOT / "restart_count.json"
RSIBOT_ENV_PATH = Path("/root/rsibot/.env")
PM2_OUT_LOG = Path("/root/.pm2/logs/arb-obs-out.log")


def read_rsibot_telegram_creds():
    """grep-extract only, never source (see module docstring)."""
    token = chat_id = None
    if not RSIBOT_ENV_PATH.exists():
        return None, None
    for line in RSIBOT_ENV_PATH.read_text(errors="replace").splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("TELEGRAM_CHAT_ID="):
            chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token, chat_id


def ledger_summary():
    if not LEDGER_PATH.exists():
        return {"total_rows": 0, "by_close_reason": {}}
    reasons = Counter()
    total = 0
    for line in LEDGER_PATH.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        total += 1
        try:
            row = json.loads(line)
            reasons[row.get("close_reason", "?")] += 1
        except json.JSONDecodeError:
            reasons["UNPARSEABLE_ROW"] += 1
    return {"total_rows": total, "by_close_reason": dict(reasons)}


def latest_checkpoint():
    """Last 'checkpoint: {...}' line from pm2's own log, read-only."""
    if not PM2_OUT_LOG.exists():
        return None
    match = None
    for line in PM2_OUT_LOG.read_text(errors="replace").splitlines():
        m = re.search(r"checkpoint: (\{.*\})", line)
        if m:
            match = m.group(1)
    if match is None:
        return None
    try:
        return json.loads(match)
    except json.JSONDecodeError:
        return None


def persisted_restart_count():
    if not RESTART_COUNT_PATH.exists():
        return None
    try:
        return int(RESTART_COUNT_PATH.read_text().strip())
    except ValueError:
        return None


def pm2_process_info():
    """Read-only: pm2 jlist, no pm2 restart/reload/stop anywhere in this script."""
    try:
        out = subprocess.run(["pm2", "jlist"], capture_output=True, text=True, timeout=10)
        procs = json.loads(out.stdout)
    except Exception:
        return None
    for p in procs:
        if p.get("name") == "arb-obs":
            return {
                "status": p.get("pm2_env", {}).get("status"),
                "pm2_restarts": p.get("pm2_env", {}).get("restart_time"),
                "uptime_ms": p.get("pm2_env", {}).get("pm_uptime"),
                "rss_bytes": p.get("monit", {}).get("memory"),
            }
    return None


def build_message():
    led = ledger_summary()
    ckpt = latest_checkpoint()
    pm2_info = pm2_process_info()
    our_restart_count = persisted_restart_count()

    lines = ["arb-obs health check (read-only)"]
    if pm2_info:
        rss_mb = pm2_info["rss_bytes"] / (1024 * 1024) if pm2_info["rss_bytes"] else None
        lines.append(
            f"pm2: status={pm2_info['status']} pm2_restarts={pm2_info['pm2_restarts']} "
            f"rss={rss_mb:.0f}MB" if rss_mb is not None else
            f"pm2: status={pm2_info['status']} pm2_restarts={pm2_info['pm2_restarts']}"
        )
    else:
        lines.append("pm2: arb-obs NOT FOUND in process list")
    lines.append(f"our restart_count.json: {our_restart_count}")
    lines.append(f"ledger: {led['total_rows']} total rows, by close_reason: {led['by_close_reason']}")
    orphans = led["by_close_reason"].get("orphan_recovered", 0)
    if orphans:
        lines.append(f"NOTE: {orphans} orphan_recovered row(s) — process died uncleanly at least once")
    if ckpt:
        for pair_id, stats in ckpt.items():
            lines.append(
                f"{pair_id}: events/hr={stats.get('events_per_pair_hour')} "
                f"occupancy={stats.get('edge_occupancy')} "
                f"observed_pair_ms={stats.get('observed_pair_ms')}"
            )
    else:
        lines.append("no checkpoint line found yet in pm2 log (fires every 5 min)")
    return "\n".join(lines)


def send_telegram(text):
    token, chat_id = read_rsibot_telegram_creds()
    if not token or not chat_id:
        print("no Telegram credentials found, printing instead:\n" + text)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception as exc:
        print(f"Telegram send failed ({exc}); message was:\n{text}")


if __name__ == "__main__":
    send_telegram(build_message())
