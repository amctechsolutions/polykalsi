# HYP-ARB-01 — Pre-registered verdict criteria for the cross-venue edge window (DRAFT)

**Status:** DRAFT — becomes binding on operator review + word. The original
lock deadline, **2026-09-05**, passed with no operator word and is
superseded. **Revised deadline: 2026-09-12T23:59 UTC** — see the lapse
clause at the end of §3. This revision (adjudicated 2026-09-09) re-sources
`r_f`, rewrites `rho` from named first-principles components, and adds a
peek acknowledgment because interim data (the 09-04 3% peak, informal
"trending toward KILL" reads) was seen before this version was written —
see §3.0. **The lock utterance should name this file's commit hash**, so
what was locked is unambiguous.
**Filed:** 2026-09-03 03:10Z, Day 3 of the 14-day window, by CC on operator
instruction ("draft the prereg").
**Every threshold below is a CC recommendation, not an operator decision.**
Sections marked `[OPERATOR]` are non-delegable and are deliberately left as
recommendations for the operator to accept, change, or reject at lock. See
the standing governance flag on this instrument (2026-08-30) for why this
file does not fill them in as though decided.

**This does not change the instrument.** No code, no `pairs.yaml`, no
process. Docs-only, ops exemption per the WORKBOARD rule of 2026-08-30.

## 1. What is being evaluated

HYP-ARB-01: *do structurally-matched Kalshi/Polymarket pairs exhibit a
persistent, executable, net-of-fee cross-venue edge that survives the cost
of holding both legs to resolution?*

Evaluated against the ledger produced by `arb-obs` (`data_logger.py` +
`edge_engine.py`) at build `d9862e9` or later, on the two pairs frozen in
`pairs.yaml` at launch:

- `fed-sep2026-no-change` (Kalshi `KXFEDDECISION-26SEP-H0` / PM
  `0xa3b3…ec9a`), settles 2026-09-16T18:05Z.
- `govt-shutdown-oct1-2026` (Kalshi `KXGOVTSHUTDOWN-26OCT01` / PM
  `0x937a…82bd`), settles 2026-10-01T14:00Z (K) / 2026-10-02T03:59Z (PM).

**Window:** 2026-08-31T22:04:09Z → **2026-09-14T22:04Z**. The 2026-08-30
launch is void and contributes no evidence (see the archived run under
`archive/2026-08-30-preFix-corrupted-run/`).

## 2. Evidence base at filing

**n = 1 episode in the first 53.1 hours.** Recorded 2026-09-02
14:11:54Z→14:37:30Z on `fed-sep2026-no-change`: `net_edge_at_open` 0.00020,
`net_edge_peak` 0.00020 (never widened), survival 1,535,954 ms,
`close_reason: edge_closed`, `censored: false`, `executable_top_size`
7,266.34 (bound by the Polymarket no-ask). `govt-shutdown-oct1-2026`:
zero qualifying edge ms to date.

This file is written now, at n=1, specifically so no criterion below can be
shaped by the outcome it is going to judge. The single observed episode is
used only to check that the criteria are *computable* from a real ledger row
(§4 worked example) — never to calibrate where a bar sits.

## 3. The bar is a return on locked capital, not a raw edge

### 3.0 Peek acknowledgment

This is not a true pre-registration. The original 2026-09-05 lock deadline
passed unmet; this version is written 2026-09-09, after the day-3
trajectory, the 09-04 3.0% peak, and informal "trending toward KILL" reads
were already stated in conversation. `r_f` is an external lookup and `rho`
is derived from named risk components fixed *before* any verdict arithmetic
was run against current data (§3.2), specifically to limit — not
eliminate — the risk that the bar was shaped by the outcome it judges.
Weight this verdict accordingly against a genuine ex-ante prereg.

### 3.1 Definition and units

The instrument records `net_edge` in dollars per $1 notional contract.
**Units, stated once to remove ambiguity: `net_edge = 0.0100` means 1%
(1¢ per $1 of notional), not 1 basis point.** This note exists because this
window's own reporting has oscillated between "2bp" and "3.0%" for values
that were dollars-per-contract throughout — a 100x unit ambiguity inside
the document that defines the verdict is not acceptable at lock.

That number is **not** the thing to threshold, because this is not a
fast arbitrage. Capturing the edge means buying both legs and **holding
them to resolution** — weeks, not seconds. Capital is locked the whole
time, and the correct question is whether the trade beats leaving that
capital in cash.

For an episode opening at time `t`:

```
C            = total outlay per matched pair, net of both venues' fees
             = 1 − net_edge_at_open
return_hold  = net_edge_at_open / C          (realised at resolution)
T            = days from t to the LATER of the two venues' settlement times
hurdle(T)    = r_f × (T / 365)  +  rho
```

A **qualifying episode** is one where:

1. `return_hold ≥ hurdle(T)`, and
2. `executable_top_size ≥ S_min`, and
3. `censored == false` and both `book_fresh_flags` are true at open.

### 3.2 Inputs

`[OPERATOR]` **Inputs to fix at lock:**

| input | meaning | CC recommendation |
|---|---|---|
| `r_f` | risk-free annual rate, the cash alternative | **3.72%** |
| `rho` | risk premium for cross-venue, settlement-timing, definitional-divergence and execution risk on an unsecured two-venue position | **1.50% (150 bp)** |
| `S_min` | minimum executable top-of-book size for an episode to count | **$1,000** |
| `N_min` | minimum qualifying-episode count for the verdict to bind (see §5.2) | **5** |

**`r_f` sourcing.** U.S. Treasury daily 4-week bill rate, coupon-equivalent
basis (comparable to `return_hold`, which is already annualized via `T`):
most recent published row at time of writing is **08/27/2026: 3.72%**
(`home.treasury.gov` daily bill-rate table; the rate held a flat 3.62–3.66%
discount-basis band through all of August). **This is a ~2-week-stale
publication lag — the lock utterance should re-pull the current rate and
use that value, not copy this number verbatim.**

**`rho` derivation — fixed from named components before checking where it
lands, not fit to the data:**

| component | rationale | est. |
|---|---|---|
| Counterparty/custody | Polymarket is a smart-contract/USDC venue, no segregated-funds protection comparable to a regulated exchange; USDC depeg is a small but real tail | 50 bp |
| Settlement/definitional divergence | different resolution texts, different settlement instants — the shutdown pair's ~14hr window mismatch is the concrete case already on file | 40 bp |
| Oracle/dispute risk | Polymarket resolves via an optimistic oracle, disputable and delayable past the clean settlement time `T` assumes | 30 bp |
| Locked-capital illiquidity | a T-bill is liquid; this position cannot be exited early if the thesis breaks mid-hold | 30 bp |
| **Total** | | **150 bp** |

This is above the original 100bp placeholder, deliberately: raising `rho`
raises the hurdle, which is the *conservative* direction (harder to pass).
A `rho` chosen generously toward a lower hurdle after already having seen
weak data would be the goalpost-move this file exists to prevent.

**`S_min` consequence — a finding, not a tuning knob.** The single recorded
`govt-shutdown-oct1-2026` episode had `executable_top_size = 5.00`, and the
pair's Polymarket side is structurally thin (worksheet dry-run measured
~5.9 contracts top-of-book). **At `S_min = $1,000`, this pair will almost
certainly never produce a qualifying episode.** Since §5.3 requires
qualifying episodes on **≥ 2 distinct pairs** for a PASS, this means PASS
is not reachable this window through any realistic combination of edges —
only KILL (§5.1) or KILL-underpowered (§5.2) can fire, regardless of edge
quality on the Fed pair alone. **Ruling: `S_min` stays at $1,000 and §5.3's
two-pair requirement stays as written.** Lowering `S_min` post-peek to let
the shutdown pair contribute (at $500 the 09-04 episode below would
qualify on size) is the same sin as a generous `rho` — relaxing a bar
toward PASS after seeing the data. **The operator signs §5.3 aware of this
asymmetry: this window can only conclude KILL or underpowered by
construction, independent of what the data does between now and 09-14.**
If the data had instead looked PASS-worthy, the correct response would be
a new, properly designed study with liquidity-screened pairs — not
loosening this one after the fact. Lesson for next time, not actioned
here: pair selection needs an `S_min`-compatibility check at *worksheet*
stage, before launch — the shutdown pair was foreclosed as a PASS
contributor from day one and nobody ran that arithmetic then.

## 4. Worked example — best episode on record as of this revision (2026-09-08)

Demonstrates §3 is computable from real rows, and shows what the §3.2
inputs actually do at signing — not calibration; this episode was found by
sorting all 53 recorded episodes by `net_edge_at_open`, after the inputs
above were already fixed.

Best candidate: 2026-09-04T12:30:29Z, `fed-sep2026-no-change`,
`net_edge_at_open = 0.03000`, `executable_top_size = 722.2`, both
`book_fresh_flags` true, `persisted_250ms: true`, `close_reason:
edge_closed`.

```
net_edge_at_open = 0.03000    C = 0.97000
return_hold      = 0.03000 / 0.97000          = 3.093%
T (2026-09-04 12:30:29Z → 2026-09-16 18:05Z)  = 12.232 days
carry  = 3.72% × 12.232/365                   = 0.125%
hurdle = 0.125% + 1.50%                       = 1.625%
```

`3.093% ≥ 1.625%` — **this episode clears criterion 1**, by ~1.9x, the
first time any recorded episode has cleared the return hurdle. But
`executable_top_size = 722.2 < S_min = 1,000` — **it fails criterion 2 on
size.** The next five largest episodes by `net_edge_at_open` were checked
the same way; none approach the hurdle (best of the rest: ~1.04%
return_hold against a ~1.63% hurdle).

**Net result at time of writing: zero of 53 recorded episodes qualify
under §3.** If the window closed today, §5.1 (zero qualifying → KILL) is
what fires — not the underpowered case. This is what locking these four
inputs actually produces; it is shown here so the operator signs having
seen it, not as a prediction of the 09-14 outcome.

## 5. Pre-committed verdict — no discretion on 2026-09-14

1. **KILL** if the window completes with **zero** qualifying episodes
   (§3). The hypothesis is that an executable edge exists; no qualifying
   episode is a direct answer, not a data problem.
2. **KILL — underpowered** if qualifying episodes ≥ 1 but < `N_min`. A
   cross-venue edge that appears fewer than `N_min` times in 14 days on
   two liquid pairs is not a repeatable process, and the instrument cannot
   distinguish it from a quote anomaly. This mirrors the house rule already
   set in SHORT-KILL-01 §3.2: underpowered = kill, not "extend and see."
3. **PASS (observation only)** if qualifying episodes ≥ `N_min`, spread
   across **≥ 2 distinct pairs** and **≥ 2 distinct calendar days** (so a
   single venue outage or one stale-book afternoon cannot carry the
   verdict).
4. **INCONCLUSIVE** only on an instrument fault, defined in advance:
   summed per-pair observed coverage (§6.1) < 90% of window wall-clock, or
   any epoch found running a build earlier than `d9862e9`. Operator
   latency, venue reconnects, and the daily `apt-daily-upgrade` pm2 bounce
   are **not** faults and do not trigger this.

`N_min` is fixed in §3.2 (**5**), alongside the other three inputs.

**No outcome of this verdict authorises capital.** A PASS authorises
drafting an *execution-feasibility* pre-registration — with the naked-leg
safeguards from the original design rounds — and nothing else. The
instrument is observation-only by construction and stays that way.

**A PASS verdict's pair-extension successor is pre-drafted, conditional,
and not activated:** see `docs/HYP-ARB-02_successor_preregistration.md`
(ECB Oct 29 / BoE Nov 5 candidates, fires only on PASS, requires its own
`S_min`-compatibility check before launch).

## 6. Analysis steps pre-committed before the verdict is read

These are known measurement traps, recorded now so the day-14 analysis
cannot quietly skip one and so none is rediscovered as a surprise.

1. **Sum `observed_pair_ms` across restart epochs.** The counter resets per
   process — verified 2026-09-02/03: the 08-31 epoch's counter read 6,881,230 ms at
   23:59Z (1.91 h, i.e. its own elapsed time since the 22:04Z restart, not
   the window's), while the current epoch reads 158.68 M ms (its own
   44.1 h), against 53.1 h of window elapsed. Reading `edge_occupancy` off
   the final checkpoint understates the denominator and **overstates
   occupancy** (0.97% per-epoch vs 0.80% window-wide at filing). Rebuild
   coverage from the rotated logs, per pair.
2. **Cross-check the maintained Kalshi book against REST** (`GET
   /markets/{ticker}/orderbook`) as an independent witness. Book-state
   drift leaves the feed looking healthy and would not trip
   `book_invalidated`; this is the failure class the 50x yes-ask bug came
   from, and continuity of seq numbers is not evidence of correctness.
3. **Treat Polymarket sizes as lower-confidence than Polymarket prices.**
   `price_change` carries no resting size, so a delta-triggered open
   inherits size from the last `book` snapshot. `pm_book_age_ms` makes this
   auditable. This matters directly for criterion 2 (`S_min`), which is a
   size test.
4. **Count `censored: true` rows separately** and exclude them from
   survival statistics. They are truncations, not observations of an edge
   closing.
5. **Do not decide whether reconnect gaps were excluded from
   `observed_pair_ms` — verify it in code.** Five Polymarket WS drops were
   logged on 2026-09-02 alone. If dead time accrues to the denominator,
   coverage in §5.4 is wrong in one direction; if it accrues to neither,
   it is wrong in another.
6. **`govt-shutdown-oct1-2026` is disqualified from any execution
   inference** regardless of what its edge looks like, on the ~14-hour
   settlement-window divergence (Kalshi single-instant 10:00 ET vs
   Polymarket through 23:59 ET). Any persistent price gap on this pair
   partly *prices that divergence* — a real value difference, not an
   inefficiency. It remains valid as an observation of a thin, less
   efficient pair.
7. **`restart_count` in the high single digits is expected**, from the
   daily `apt-daily-upgrade.timer` pm2-fleet bounce. Distinguish it from
   `unstable_restarts` (pm2's crash counter, 0 throughout). Do not
   re-investigate.

## 7. Anti-gaming clauses

- **`pairs.yaml` is frozen for the window.** The Day-14 backlog candidates
  (ECB Oct 29, BoE Nov 5, per `PAIRS_WORKSHEET.md`) are **not** added
  mid-window and are not spliced into this dataset. If adopted they start
  their own clock, per the operator instruction of 2026-09-01 not to create
  an uneven observation baseline.
- **The window does not extend.** 2026-09-14T22:04Z is the end. A
  disappointing n is a result under §5.2, not grounds for more time.
- **No threshold in §3 or §5 moves after lock.** A change to `r_f`, `rho`,
  `S_min` or `N_min` after the lock word is given voids the pre-registration
  and the window reports as exploratory only.
- Any parameter change to `edge_engine.py`'s qualification logic during the
  window voids the window, same rule.
- **Lapse clause (added 2026-09-09, supersedes the original 09-05
  deadline):** if no operator lock word is given by **2026-09-12T23:59
  UTC**, this pre-registration lapses and the 2026-09-14 verdict reports as
  exploratory only — recorded as a **lapsed lock**, a specific documented
  state, not a silent default. To make this a *chosen* exploratory outcome
  instead of a lapsed one, the operator states that explicitly before the
  deadline; either statement is a valid governance action, silence is not.

## 8. What a KILL means operationally

The instrument is stopped (`pm2 stop arb-obs`, `pm2 save`), the ledger and
logs are retained, the repo is left in place. Code is mothballed, not
deleted — DEC-01 pattern. The two self-removing health-check crons are
already self-removing and need no cleanup.

A KILL on HYP-ARB-01 does **not** kill HYP-LONGSHOT-01, which asks a
different question of the same data and is parked pending this verdict.

## 9. Open governance item carried into this file

The launch-day gate compression (four separate gate actions collapsed into
one "Goahead" on 2026-08-30) is **still pending operator countersign or
veto** as of filing. It concerns the pair-approval judgment columns in
`PAIRS_WORKSHEET.md` — i.e. the provenance of the two pairs this verdict
will be computed from. It should be closed before 2026-09-14, not after,
so it is a documented waiver rather than a provenance question raised
against a completed verdict.
