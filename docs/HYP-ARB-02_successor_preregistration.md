# HYP-ARB-02 — Conditional successor pre-registration (DRAFT, not activated)

**Status:** DRAFT, conditional. This document does nothing by itself — no
code, no `pairs.yaml`, no process, no new clock. Docs-only, ops exemption
per the WORKBOARD rule of 2026-08-30. It exists so that *if* HYP-ARB-01
triggers its condition (below), a successor study can start the same day
instead of a week later, with the design work already done rather than
begun cold. Pre-staging a branch of a decision tree is not opening a
second WIP thread — see the adjudication that authorized drafting this
(2026-09-09).

**Filed:** 2026-09-09, before HYP-ARB-01's 2026-09-14T22:04Z verdict, so
this design cannot be shaped by that outcome either.

## 1. Trigger condition

**Fires only if HYP-ARB-01 resolves as PASS (§5.3 of
`HYP-ARB-01_preregistration.md`).**

This is a narrower reading than "any non-KILL outcome." Reasoning,
stated explicitly rather than silently chosen: HYP-ARB-01's own §5.2
already rules that qualifying episodes below `N_min` are KILL, not
"extend and see" — mirroring the house rule set in SHORT-KILL-01 §3.2.
A successor study firing on KILL-underpowered would contradict that
precedent inside the same program. §5.4 INCONCLUSIVE is an instrument
fault, not a market-signal finding — the correct response there is
re-running the *existing* window, not launching a new one. Only §5.3 PASS
constitutes actual evidence of an executable, repeatable edge, which is
the only thing that justifies the cost of a second study.

**As of the 2026-09-09 live pull, PASS is structurally unreachable this
window** (v2 prereg §3.2: `S_min`=$1,000 forecloses the shutdown pair,
and §5.3 requires ≥2 distinct pairs) — so on current evidence this
document is very unlikely to activate. It is drafted anyway, at zero
marginal cost, because the alternative — designing it *after* a surprise
PASS — would be exactly the kind of under-time-pressure decision this
program's own doctrine treats as higher-risk.

## 2. Candidate pairs

Both already identified and partially vetted in
`PAIRS_WORKSHEET.md`'s Day-14 backlog — reproduced here with their
verification status, not re-verified as of this filing:

**ECB rate decision, Oct 29, 2026 meeting** (`Pair 4` in the worksheet).
Same 5-way bracket structure as the Fed pair (structurally clean, not a
CPI-style bin/threshold trap) — Kalshi `KXCBDECISIONEU-26OCT29-HOLD`
(vol ~$1,707 at last pull), Polymarket conditionId
`0xf97e2e2b845a3e5ce0646ce7563cca294f58b1c23affc38010386c08627075ac`
(vol ~$20,676). Fee tier NOT yet confirmed on either venue.

**BoE rate decision, Nov 5, 2026 meeting** (`Pair 5`). Same 5-way
structure, Kalshi `KXCBDECISIONENGLAND-26NOV05-HOLD` (vol ~$1,179).
Polymarket side not independently re-verified for the November event —
the worksheet only checked the September contract and assumed identical
structure. Fee tier NOT yet confirmed.

Both entries carry their own worksheet warning: "don't trust this note by
then — pull live." That instruction stands for this document too.

## 3. Required pre-launch step — the lesson this program already paid for

**Neither candidate has been checked for `S_min` compatibility, and one
of them (`ECB`, Kalshi vol ~$1,707) is thin enough on the same axis that
foreclosed the shutdown pair in HYP-ARB-01 v2.** Before either pair is
added to any `pairs.yaml`, pull each venue's live executable top-of-book
size and confirm it clears whatever `S_min` the activating pre-reg sets —
**at worksheet stage, before launch**, not discovered after weeks of
data collection the way the shutdown pair's incompatibility was. This is
the direct lesson from HYP-ARB-01 v2 §3.2, applied prospectively rather
than just recorded as a regret.

## 4. What activation actually requires (this document does not grant it)

This filing pre-stages the design and the reasoning only. If §1's
condition fires, activation still requires, in full:

1. A live re-pull of both pairs' resolution text, fee tier, and
   executable size on both venues (per §3) — not a reuse of the figures
   above.
2. A proper prereg for HYP-ARB-02 itself (bar, inputs, verdict rules) —
   this document is not that; it only answers "which pairs, and under
   what trigger," not "what counts as a qualifying episode this time."
3. `pairs.yaml` / instrument-config changes, which are **not** docs-only
   — full commit-approval + push-word + restart-word sequence applies,
   no carve-out.
4. Its own clock, independent of HYP-ARB-01's — per HYP-ARB-01 v2 §7's
   anti-gaming clause, a newly adopted pair does not splice into an
   existing dataset.

## 5. Cross-reference

See `docs/HYP-ARB-01_preregistration.md` §5 for the verdict this document
is conditioned on, and `docs/PAIRS_WORKSHEET.md` for the source vetting
of both candidate pairs.
