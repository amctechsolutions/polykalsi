# Quarantined: pre-fix corrupted run, 2026-08-30

**Do not use this data for any analysis. Kept for the record, not deleted, per project doctrine (kill-record permanence).**

## What this is

The pm2 stdout/stderr log (`arb-obs-error.log.snapshot`) and `restart_count.json` value
from the FIRST launch of arb-obs, 2026-08-30T15:40:16Z (restart_count=1), through the
point this snapshot was taken (~111 minutes later, still running at snapshot time).
No `edge_ledger.jsonl` or `open_state.json` exist for this run — zero episodes ever
opened on either pair during this window, so there is no ledger to quarantine
separately; the log is the only data artifact this run produced.

## Why it's untrusted

Two confirmed bugs affected this entire run, both fixed in the commit landing
immediately after this quarantine was created (see git log):

1. **Exposure double-counting (~2x).** `observed_pair_ms`/`qualifying_edge_ms` in the
   checkpoint log lines are inflated by roughly 2x real elapsed wall-clock time —
   confirmed by computing deltas between consecutive checkpoint lines against the
   real 300s interval between them (consistently ~550-600k ms instead of ~300k ms).

2. **Kalshi orderbook state corruption (the serious one).** `seq` is scoped per
   subscription-id (sid), shared across all tickers on that sid — not per ticker,
   which this run's code assumed. With 2 tickers subscribed, this produced a false
   "sequence gap" roughly every 30-90 seconds for the entire run (dozens of times,
   see the WARNING lines in the log), each time wiping that ticker's order book to
   empty. Worse, the code then marked the book "valid" again on the very next price
   update, without waiting for a real fresh snapshot — so the book operated in a
   degraded, incompletely-rebuilt-from-deltas-only state most of the time, while
   being trusted as if it were the real order book. `k_yes_bid`/`k_yes_ask` values
   computed during most of this run are unreliable.

Both bugs were caught the same session by the operator asking "show me what it
watched," triggering a review of the checkpoint numbers and log warning frequency —
not by any automated alert. See project memory (`us_arb_obs_01_status`, doctrine
entry D5) for the full writeup: a fail-safe (seq-gap detection) firing far more
often than its threat model predicts is itself a bug signature, not a health
signal — this run's pre-flight and launch reports both mis-narrated the first gap
as evidence the safety path worked.

## What superseded this

The 14-day HYP-ARB-01 observation clock was restarted cleanly after the fix. See
WORKBOARD.md and `us_arb_obs_01_status` memory for the new launch timestamp and
verdict date.

## Reuse

This log is also the origin of `tests/fixtures/kalshi_multi_sid_seq_evidence.json`
and the regression tests in `tests/test_kalshi_client.py` — it's the evidence base
the fix was built and verified against, not just a discarded artifact.
