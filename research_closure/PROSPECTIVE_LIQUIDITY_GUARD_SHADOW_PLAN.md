# PROSPECTIVE LIQUIDITY GUARD SHADOW PLAN — DRAFT (NOT APPROVED, NOT ACTIVATED)

**Status: DRAFT ONLY.** This document is a preregistration draft written per Part 12 of the
liquidity-guard task. Per the frozen decision matrix (`LIQUIDITY_GUARD_DEFS_FROZEN.md`
§6c), **every guard is UNACCEPTABLE for adoption on historical evidence** and
`BEST_LIQUIDITY_GUARD = NONE`. Nothing here is activated, no shadow is started, no
production table is written, no order is placed. **Activation requires an explicit,
separate operator approval.**

Rationale for drafting (not adopting): the frozen Part 2 rule classified the V3 2021–22
failure as PRIMARILY LIQUIDITY-SCREENING (rule 6a: YES), and the current production V1
Top20% carries the same exposure today (Part 9: 7 of 54 names fail L1/L2/L3; one name at
16.8% of its 30d ADV for a 1B-toman portfolio). No untouched historical holdout exists, so
the only clean test of any guard is prospective.

**Official status (final bookkeeping correction, 2026-10-04):** under the restored
preregistered Direction D, frozen §6e mechanically gives
`PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING = NO` — the official token. This document's
existence is therefore recorded as a post-hoc artifact, not a §6e output:
`PROSPECTIVE_GUARD_SHADOW_PLAN_DRAFT_EXISTS = YES`;
`PROSPECTIVE_GUARD_SHADOW_PLAN_STATUS = DORMANT_POST_HOC_DRAFT`;
`PROSPECTIVE_GUARD_SHADOW_ACTIVATED = NO`. The draft is retained unchanged and dormant
(still DRAFT ONLY — NOT APPROVED, NOT ACTIVATED).

---

## 1. Frozen rule under test (no thresholds may change)

**L1 — TRADED-DAYS FLOOR**, exactly as frozen in `LIQUIDITY_GUARD_DEFS_FROZEN.md`:

> Exclude security s at date T iff pct_TD60(s,T) < 0.10, where TD60 =
> `t_traded_days_ratio_60` (fraction of the last 60 file-records with qTotTran5J > 0) and
> pct_TD60 is the cross-sectional midrank percentile within the date's eligible universe.
> Missing metric → excluded. Substitution: move down the SAME frozen score ranking to the
> next eligible name; Top20% count preserved; equal weight; scores untouched.

The guard is applied to **V1 only** (the production score). V3 is terminated and is not
tested prospectively.

**Candidate-selection status (operator correction, 2026-10-04):** L1's selection as the
proposed prospective candidate is **POST-HOC**, based on historical descriptive evidence
only (reference: largest V1 2021–22 improvement among the frozen guards). It is NOT a
historically validated choice and NOT the official preregistered decision output — the
official `NEXT_RESEARCH_DIRECTION = D` (INSUFFICIENT_EVIDENCE); see
`LIQUIDITY_GUARD_RESULTS.md` Part 11. Only future prospective observations collected under
this plan can provide new evidence.

## 2. Arm structure — shadow-of-the-shadow (parallel computation only)

- The existing **untouched Shadow V1.1** remains the control and the ONLY live shadow.
- The test arm is a **parallel research computation** over the same production snapshots:
  at each production run, compute V1 Top20% (as published) and the L1-guarded basket
  (same ranking, guard-failing names skipped), record both to a research-only artifact
  (file or `research_closure`-scoped table). **No production writes. No broker. No orders.**
- Guard metrics are computed from raw PIT TSETMC fields as-of each snapshot date
  (certified chain, sessions ≤ as_of only).

## 3. Start date

First production run on or after **2026-11-01** following explicit operator approval,
so the test cannot interfere with the standing Message A / Decision #1 freeze
(structurally impossible before 2026-10-31). If no qualifying production run exists when
approval is given, the start is the first run after approval — recorded, not chosen.

## 4. Pre-registered metrics (computed monthly per snapshot)

1. Guard-fail rate: share of the unguarded V1 Top20% that fails L1.
2. Substitutions per rebalance and retention % (frozen definitions §5).
3. Capacity ratios at 100M / 500M / 1B / 5B / 10B toman (frozen §6b formula).
4. Hypothetical guarded-portfolio NAV vs untouched V1 basket NAV via the certified engine
   (research mode, BASE cost), monthly returns, MDD, turnover, fees.
5. Median Δ pct_TD60 / Δ TV30 of substitutions (frozen §5 pairing).

## 5. Minimum observation horizon

**12 months of production snapshots** (≥ 12 rebalances). No interim conclusion is drawn
before month 12 except a stop criterion below.

## 6. Stop / close criteria (pre-registered)

- **NO_LONGER_RELEVANT**: guard-fail rate < 1% for 6 consecutive snapshots.
- **NO_VALUE**: at month 12, guarded cumulative return < untouched V1 cumulative − 5pp.
- **UNIMPLEMENTABLE**: average substitutions > 15% of slots per rebalance over any
  6-month window.
- **PROMISING**: at month 12, guarded cumulative ≥ untouched V1 cumulative AND
  substitutions ≤ 10% AND guard-fail rate ≥ 5% (the guard is binding and not harmful) —
  only then may a NEW preregistration for continued observation be drafted.
- **INCIDENT**: any contamination of production, Shadow V1.1, or the Message A gate →
  immediate stop, full incident note in SESSION_HANDOFF.

## 7. Integrity constraints

- No retrospective changes to this plan; any modification requires a NEW dated
  preregistration that supersedes it.
- No threshold may be revisited because of interim results.
- No real-money orders, no broker connection, SQL Server not used.
- All artifacts land in `research_closure/` and SESSION_HANDOFF; production remains
  untouched.
