# pairs.yaml settlement-diff worksheet

Purpose: turn populating `pairs.yaml` from a blank page into a fill-in
exercise. One row per candidate pair. The "Definitional diff notes" and
"Recommended?" columns are deliberately left for the operator — that
judgment call is the point of the manual review, not something to
automate away.

**Honest finding before the template:** I tried to auto-discover
Geopolitics-category candidates from both venues' public APIs and hit a
real limit, reported here rather than papered over.

- Polymarket's public tag taxonomy (`GET /tags` on gamma-api) has no tag
  literally named "Geopolitics" — the closest are `foreign affairs` (id
  842), `international affairs` (id 1396), `military invasion` (id 1308),
  `hostage crisis` (id 1542). Querying markets under those tags returned
  only thin, low-volume markets (largest was ~$10.8k 24h volume on a
  Ceuta-migrant-wave market) — nothing both liquid and with an obvious
  Kalshi equivalent.
- Worse: Polymarket's per-market `takerBaseFee`/`makerBaseFee` API fields
  do **not** reflect the category fee schedule from Task 1.5 — a Crypto
  market (documented 7% fee) and a Politics/Fed market (documented 4% fee)
  both returned identical `takerBaseFee: 1000`. So **fee-tier membership
  cannot be confirmed via API at all**; it has to be checked visually on
  polymarket.com (or by asking Polymarket support whether a
  category-to-market mapping is exposed anywhere) before treating any
  candidate as genuinely fee-free.

Recommendation: browse each platform's own UI (both have a friendlier
category/world-events navigation than the raw API tag list) to shortlist
Geopolitics candidates, then bring the specific market(s) here — I can
pull the live ticker/condition-ID/resolution-source data for anything you
point at, the way the row below was built.

## Template

| Field | Kalshi | Polymarket |
|---|---|---|
| pair_id (candidate) | | |
| Ticker / condition ID | | |
| Resolution source (verbatim) | | |
| Close / cutoff time | | |
| Fee tier (confirmed how?) | n/a — no Kalshi fee applies to this leg's cost basis the same way; use `kalshi_fee()` | needs manual confirmation, see above |
| **Definitional diff notes** (operator fill-in) | colspan | |
| **Recommended?** (operator fill-in: Y / N / needs more review) | colspan | |

## Worked example (verified live, 2026-08-30) — NOT Geopolitics tier, included to calibrate the format

This is the one pair I could verify end-to-end with high confidence. It's
Politics/Economics (Polymarket fee 4%, not fee-free), so it's a format
example, not a Geopolitics submission.

| Field | Kalshi | Polymarket |
|---|---|---|
| pair_id (candidate) | `fed-sep2026-no-change` | same |
| Ticker / condition ID | `KXFEDDECISION-26SEP-H0` ("Will the Federal Reserve Hike rates by 0bps at their September 2026 meeting?") | conditionId `0xa3b36b2d6104d34af4e6c6215fc818e43352e78a748fbfb0b85e3a35f71dec9a` ("Will there be no change in Fed interest rates after the September 2026 meeting?") — clobTokenIds `["5615282760875985231868508008056959876238536896643315063916840237042205273721" (YES), "97050921740416192996389806693742575608111328819185493163189880975611314813724" (NO)]` |
| Resolution source (verbatim) | "If the Federal Reserve does a Hike of 0bps on September 16, 2026, then the market resolves to Yes." Secondary: mutually exclusive across the bracket family; a canceled/unscheduled meeting resolves "Fed maintains rate" to Yes and all others No. | "This market will resolve to the amount of basis points the upper bound of the target federal funds rate is changed by... resolution source is the FOMC's statement after its meeting scheduled for September 15-16, 2026... If no statement is released by the end date of the next scheduled meeting, this market will resolve to the 'No change' bracket." |
| Close / cutoff time | `close_time` 2026-09-16T17:59:00Z; `expected_expiration_time` 2026-09-16T18:05:00Z; `expiration_time` (outside default) 2026-12-16T18:01:00Z | `endDate` 2026-09-16T00:00:00Z |
| Fee tier | Kalshi fee via `kalshi_fee()`, category-agnostic | 0.04 (Politics), confirmed from the docs table, not this specific market's API fields |
| **Definitional diff notes** | *(operator fill-in — one thing worth your eyes: Kalshi's close is 17:59 UTC same day, ~2 hours after a typical 2pm ET FOMC statement; Polymarket's `endDate` reads as midnight UTC the same calendar day, i.e. technically BEFORE the meeting even starts on the 16th — that's almost certainly just a nominal "event day" field rather than the real settlement cutoff, but worth confirming which timestamp each venue actually enforces before trusting book age vs. settlement-window math on this pair)* | |
| **Recommended?** | *(operator fill-in)* | |

## Notes for whoever fills this in

- Ticker/condition-ID pairs must be pulled live, never from memory — every
  value above came from a `curl` against the venue's own public endpoint
  (Kalshi: `GET /trade-api/v2/markets/{ticker}` and
  `?series_ticker=...`; Polymarket: `gamma-api.polymarket.com/markets`).
  If you hand me a specific market you've found on either site, I'll do
  the same live pull for it rather than guess at the matching ticker.
- `pairs.yaml.example` already documents the `pm_fee_rate` field per
  category from Task 1.5 — Geopolitics is the only 0 entry, everything
  else is 0.04–0.07.
