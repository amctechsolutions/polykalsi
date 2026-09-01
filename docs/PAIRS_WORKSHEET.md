# pairs.yaml settlement-diff worksheet

Purpose: turn populating `pairs.yaml` from a blank page into a fill-in
exercise. One row per candidate pair. The "Definitional diff notes" and
"Recommended?" columns are deliberately left for the operator — that
judgment call is the point of the manual review, not something to
automate away. `pairs.yaml` itself is only ever populated from rows the
operator has approved here first — nothing below is live config.

**Honest finding on Geopolitics (still stands):** Polymarket's public tag
taxonomy (`GET /tags` on gamma-api) has no tag literally named
"Geopolitics" — the closest are `foreign affairs` (id 842),
`international affairs` (id 1396), `military invasion` (id 1308),
`hostage crisis` (id 1542). Markets under those tags were thin (largest
~$10.8k 24h volume). Separately, Polymarket's per-market
`takerBaseFee`/`makerBaseFee` API fields do **not** reflect the category
fee schedule (see `53aa65d`) — fee-tier membership can't be confirmed via
API at all, only visually on polymarket.com. Net effect: the three
candidates below are Fed/econ/politics-tier (4-5% fee, UI-confirmed), not
Geopolitics — consistent with the round-2 demotion from plan to
nice-to-have.

## Template

| Field | Kalshi | Polymarket |
|---|---|---|
| pair_id (candidate) | | |
| Ticker / condition ID | | |
| Resolution source (verbatim) | | |
| Close / cutoff time | | |
| Fee tier (confirmed how?) | n/a — use `kalshi_fee()` | UI-confirmed only, see above |
| **Definitional diff notes** (operator fill-in) | colspan | |
| **Recommended?** (operator fill-in: Y / N / needs more review) | colspan | |

## Pair 1 — Fed rate decision, Sept 2026, "no change" (operator-verified: Politics, 0.04)

Same pair as the original worked example, now confirmed by the operator's
own UI check rather than presented only as a format demo.

| Field | Kalshi | Polymarket |
|---|---|---|
| pair_id (candidate) | `fed-sep2026-no-change` | same |
| Ticker / condition ID | `KXFEDDECISION-26SEP-H0` ("Will the Federal Reserve Hike rates by 0bps at their September 2026 meeting?") | conditionId `0xa3b36b2d6104d34af4e6c6215fc818e43352e78a748fbfb0b85e3a35f71dec9a` ("Will there be no change in Fed interest rates after the September 2026 meeting?", event `fed-decision-in-september-762`) — clobTokenIds `["5615282760875985231868508008056959876238536896643315063916840237042205273721" (YES), "97050921740416192996389806693742575608111328819185493163189880975611314813724" (NO)]` |
| Resolution source (verbatim) | "If the Federal Reserve does a Hike of 0bps on September 16, 2026, then the market resolves to Yes." Secondary: mutually exclusive across the bracket family; a canceled/unscheduled meeting resolves "Fed maintains rate" to Yes and all others No. | "This market will resolve to the amount of basis points the upper bound of the target federal funds rate is changed by... resolution source is the FOMC's statement after its meeting scheduled for September 15-16, 2026... If no statement is released by the end date of the next scheduled meeting, this market will resolve to the 'No change' bracket." |
| Close / cutoff time | `close_time` 2026-09-16T17:59:00Z; `expected_expiration_time` 2026-09-16T18:05:00Z | `endDate` 2026-09-16T00:00:00Z |
| Fee tier | via `kalshi_fee()` | 0.04, operator-confirmed on-site |
| **Definitional diff notes** | **[CC recommendation, operator delegated via "Goahead" 2026-08-30]** Kalshi's close (17:59 UTC) is ~2hrs after a typical 2pm ET FOMC statement; Polymarket's `endDate` (00:00 UTC same day) is a nominal "event day" marker, not the real settlement cutoff. This is a read-only observation instrument — the mismatch matters for interpreting ledger timestamps at day-14 analysis, not for any live risk, since nothing is ever traded. Not a blocker for observation. | |
| **Recommended?** | **Y — CC recommendation.** Live-verified end-to-end in the v3 dry run (`f02dd78`): both venues' quotes were sane and REST-cross-checked correct, raw edge sat consistently negative (~-1%), tight and liquid on both sides. Lowest-risk of the three candidates. | |

## Pair 2 — August 2026 CPI print — STRUCTURAL MISMATCH, likely not a clean pair

Flagging this loudly rather than presenting a false equivalence: **the two
venues bet on different things here.** Kalshi frames CPI as a cumulative
threshold ("above X%"); Polymarket frames it as a set of discrete point
bins ("exactly X%"). A single Polymarket bin is not the same claim as a
Kalshi threshold market — they'd only be equivalent if you summed every
Polymarket bin above the threshold, which is a basket, not a 1:1 pair.

| Field | Kalshi | Polymarket |
|---|---|---|
| pair_id (candidate) | `cpi-aug2026-3.3` (tentative — see mismatch above) | same |
| Ticker / condition ID | `KXCPIYOY-26AUG-T3.3` ("Will the rate of CPI inflation be above 3.3% for the year ending in August 2026?") — most liquid threshold in the August bracket family (vol ~54.7k) | conditionId `0x8153bb8767d01033f362f7b7b89bb3e12c3007442bf34e3e3bfbcc5b4fee9f16` ("Will annual inflation be 3.3% in August?", event `august-inflation-us-annual-1786474662954`) — one of 11 discrete bins (2.9%-or-less through 4.0%-or-more) in the same event; nearest-liquidity bin, vol ~10.3k, next bin (3.4%) vol ~15.1k |
| Resolution source (verbatim) | "If the Consumer Price Index (CPI) increases by more than 3.3% in the twelve months ending August 2026 (as represented by the one-decimal place value reported by the Bureau of Labor Statistics), then the market resolves to Yes." | "This market will resolve to the percentage change in the Consumer Price Index (CPI) over the 12-month period ending in August 2026 according to the monthly Bureau of Labor Statistics (BLS) report... resolution source... BLS CPI report... scheduled to be released on September 11, 2026, at 8:30 AM ET." |
| Close / cutoff time | `close_time` 2026-09-11T12:29:00Z; `expected_expiration_time` 2026-09-11T14:00:00Z | `endDate` 2026-09-11T03:59:00Z (again reads as before the actual 8:30am ET release — nominal, not real cutoff) |
| Fee tier | via `kalshi_fee()` | needs UI confirmation (Economics tier expected, 0.05) |
| **Definitional diff notes** | *(operator fill-in, though the headline finding is above: cumulative-threshold vs discrete-bin is a structural mismatch, not a wording nuance — decide whether this pair is even in scope for a single-market arb, or whether it needs a basket construction the current instrument doesn't support)* | |
| **Recommended?** | **N — CC recommendation, operator delegated via "Goahead" 2026-08-30.** Excluded from pairs.yaml: the cumulative-threshold vs discrete-bin mismatch means this isn't a valid single-market pair as specced. Would need a basket construction (summing Polymarket bins above the Kalshi threshold) the current instrument doesn't support — a real future feature, not this launch. | |

## Pair 3 — Government shutdown by/on Oct 1, 2026 (strong resolution-text match, real timing + liquidity caveats)

Closest resolution-language match of the three — both venues appear to
draw on near-identical OMB/OPM shutdown-determination language. Two real
differences worth your attention, not just the usual boilerplate caution.

| Field | Kalshi | Polymarket |
|---|---|---|
| pair_id (candidate) | `govt-shutdown-oct1-2026` | same |
| Ticker / condition ID | `KXGOVTSHUTDOWN-26OCT01` ("Will the US government be shut down on Oct 1, 2026?") — vol ~355k, yes_bid/ask 0.04/0.05 | conditionId `0x937a7f4210f01a06ed95228c255b5d141f93994c00c5508c6abbf1ce542282bd` ("Government shutdown by October 1?", event `government-shutdown-by-october-1-20260610162414910`) — clobTokenIds `["8601474761739494662879132877571233419511374108958084174727177012285914530506" (YES), "27431848238380441159866176169932849060440136760407552489857058375069535196775" (NO)]` — vol ~7.5k total, 24h vol ~$116 |
| Resolution source (verbatim) | "If the United States federal government is at least partially shut down due to a lapse of appropriations **at 10:00 AM ET on Oct 1, 2026**, then the market resolves to Yes." Detailed OMB-directive / OPM-status examples of what does/doesn't qualify. | "This market will resolve to 'Yes' if the United States federal government enters a shutdown due to a lapse in appropriations **by the specified date, 11:59 PM ET**. Otherwise... No." Near-identical OMB-directive / OPM-status qualifying examples. |
| Close / cutoff time | `close_time` 2026-10-01T14:00:00Z (= 10:00 AM ET, a point-in-time check) | `endDate` 2026-10-02T03:59:00Z (= 11:59 PM ET Oct 1, a window through end-of-day) |
| Fee tier | via `kalshi_fee()` | needs UI confirmation (Politics tier expected, 0.04) |
| **Definitional diff notes** | **[CC recommendation, operator delegated via "Goahead" 2026-08-30]** Two real things: (1) Kalshi checks status at a single instant (10am ET Oct 1) while Polymarket checks a window through 11:59pm ET the same day (~14hrs longer) — a late-day shutdown would resolve them differently; observation-only, so this just means the two ledger rows for this pair may legitimately disagree near the boundary, not a risk. (2) Liquidity is asymmetric (Kalshi ~$355k vs Polymarket ~$7.5k, and the dry run measured `pm_yes_ask_size≈5.9` contracts directly) — day-14 analysis MUST apply a minimum executable-size floor before treating any "edge" on this pair as real; noting that requirement here so it isn't lost. | |
| **Recommended?** | **Y, with the size-floor caveat above — CC recommendation.** Included specifically because it's thin: valuable to observe how the instrument behaves on a less-efficient, less-liquid pair, which is exactly the contrast case the Fed pair doesn't provide. | |

## Notes for whoever fills this in

- Ticker/condition-ID pairs must be pulled live, never from memory — every
  value above came from a `curl` against the venue's own public endpoint
  (Kalshi: `GET /trade-api/v2/markets/{ticker}` and `?series_ticker=...`;
  Polymarket: `gamma-api.polymarket.com/events`, `/markets`, and
  `/public-search?q=...`). If you hand me a specific market you've found
  on either site, I'll do the same live pull for it rather than guess at
  the matching ticker.
- `pairs.yaml.example` already documents the `pm_fee_rate` field per
  category from Task 1.5/round-3 — Geopolitics is the only 0 entry,
  everything else is 0.04-0.07, and it must be set from the venue's own
  UI, never from API metadata (see `53aa65d`).
- Pair 2 is included specifically as a negative result: not every topic
  that exists on both venues is a valid pair. Structural bet-type
  mismatches are exactly the kind of thing this manual review step exists
  to catch before they'd otherwise surface as a confusing empirical
  anomaly on day 14.

## Backlog — candidates for the Day-14 review only, NOT enabled in pairs.yaml

Operator instruction 2026-09-01: keep researching/cataloging in the
background, hold actually adding or enabling any new pair until Day-14 —
adding pairs mid-window creates an uneven observation baseline (14 days
of data on the original pairs vs. partial days on anything added later)
and complicates the post-hoc analysis. Everything below is prep only.

### Candidate: ECB rate decision — Pair 4 (Sept meeting expires before Day-14; Oct meeting is the real candidate)

Same bracket structure as the Fed pair (5-way: 50+bp cut / 25bp cut / no
change / 25bp hike / 50+bp hike on both venues) — structurally clean,
not a CPI-style trap. **Timing note: the September 2026 ECB meeting
(Sept 9-10) resolves BEFORE the ~Sept 14 Day-14 verdict**, so it's not a
usable candidate by the time this backlog would be acted on. The **October
29, 2026 meeting is the real candidate** — still has runway post-Day-14.

| Field | Kalshi | Polymarket |
|---|---|---|
| Ticker / condition ID (Oct 29 "no change" leg) | `KXCBDECISIONEU-26OCT29-HOLD` (vol ~$1,707) | conditionId `0xf97e2e2b845a3e5ce0646ce7563cca294f58b1c23affc38010386c08627075ac` (vol ~$20,676), event `ecb-interest-rates-october-2026-20260723225848778` |
| Resolution basis | ECB deposit facility rate change vs. pre-meeting level | Same — verbatim: "resolve according to the change in basis points in the deposit facility rate...relative to the level it was prior to this meeting" |
| Close | 2026-10-29T13:14:00Z | not yet pulled — pull live at Day-14, don't trust this note by then |
| Fee tier | via `kalshi_fee()` | needs UI confirmation at Day-14 (Economics tier expected, 0.05 per the confirmed category table — do NOT assume, re-check) |
| **Definitional diff notes / Recommended?** | *(Day-14 operator judgment — not pre-filled)* | |

### Candidate: BoE rate decision — Pair 5 (same timing note: Sept meeting too close to Day-14, Nov 5 is the real candidate)

Same 5-way bracket structure, both venues. September 2026 BoE meeting
(Sept 17) resolves only 3 days after the ~Sept 14 Day-14 verdict — too
tight to be useful as a fresh addition. **November 5, 2026 is the real
candidate.**

| Field | Kalshi | Polymarket |
|---|---|---|
| Ticker / condition ID (Nov 5 "hold" leg) | `KXCBDECISIONENGLAND-26NOV05-HOLD` (vol ~$1,179) | need to re-pull the Nov event at Day-14 — only the Sept event (`bank-of-england-decision-in-september-...`) was checked this pass |
| Resolution basis | BoE Bank Rate change vs. pre-meeting level | Same basis confirmed on the Sept event; Nov event assumed identical structure, NOT independently re-verified |
| Fee tier | via `kalshi_fee()` | needs UI confirmation at Day-14 |
| **Definitional diff notes / Recommended?** | *(Day-14 operator judgment — not pre-filled)* | |

### Candidate: US unemployment rate — flagged as LIKELY the same trap as CPI, not pre-verified clean

Polymarket has an open "August Unemployment Rate" market (~$26k volume).
Given Polymarket structured CPI as discrete point-bins ("exactly X%")
while Kalshi structures inflation/rate prints as cumulative thresholds
("above X%"), unemployment is very likely the same shape on both sides —
**this needs the identical threshold-vs-bin check that killed the CPI
pair before it's treated as a real candidate**, not assumed clean because
the topic exists on both venues. Do not add without that check.

### Checked and rejected as candidates (topic overlap exists, no clean match found)

- **2028 US Presidential Election** — Polymarket has one national winner
  market; Kalshi (checked 2026-09-01) only has ~60 state-by-state
  party-winner markets, no single national-winner market found. Would
  require reconstructing a national view from many state markets — not a
  1:1 pair, not pursued further.
- **Israel-Iran ceasefire / US-Iran relations** — real volume on both
  venues, but Kalshi's markets are narrower/differently-framed (specific
  officials, specific narrow actions) rather than the same broad
  "does the ceasefire hold" question Polymarket asks. Same class of trap
  as CPI; no clean match found on a first pass.

### Categories not yet checked (operator-suggested, still open)

- Single-game sports (high liquidity confirmed to exist on both venues
  from earlier live testing — the Man U vs Ipswich capture — but fee
  tier is confirmed 0.05/Sports per docs.polymarket.com/trading/fees,
  NOT 0.75% as floated in one conversation; re-verify on whatever
  specific match gets picked, categories can vary)
- Broader geopolitics/world-events beyond what's been checked so far —
  the original Task-1.5-era finding (thin liquidity under Polymarket's
  adjacent tags) still stands as the baseline expectation; worth another
  pass but temper expectations accordingly.
