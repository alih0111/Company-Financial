# SHADOW V1 — LAUNCH CERTIFICATION (pre-first-decision)

Certified: 2026-10-03 (UTC timestamps in `shadow_v1_launch_certification.json`).
Machine-readable twin: `portfolio_shadow/shadow_v1_launch_certification.json`.
No shadow decision or observation exists. Nothing below is derived from any shadow outcome.

## Spec status

| Spec | SHA-256 | Status |
|---|---|---|
| SHADOW_V1_SPEC.md | `959b56904added66812ab3726fc067112d7bc12ab3d58d8334f3c4381540df3a` | preserved UNCHANGED |
| **SHADOW_V1_1_SPEC.md (ACTIVE)** | `f396b5f65474a017f7f97ff9f2d0c8679708f6e20ee104dc19dc53d06709ff0e` | frozen 2026-10-03T19:40:34Z — pre-first-decision clarification; supersedes V1 only for schedule / guard window / refresh mechanics / identity onboarding |

All economics of V1 are untouched: production score `canonical-v1-dev`, Top20 selection
(`n = max(1, floor(0.20 × N_eligible))`, ties `(quant_score DESC, symbol ASC)`), equal
weights, monthly rebalance, 50 bps one-way BASE, certified repaired accounting engine
(deterministic port), benchmark, paper-only, artifact immutability, 12-cycle minimum, no
automatic promotion.

## Part 1 — Historical decision schedule (RECOVERED)

**HISTORICAL_DECISION_SCHEDULE_RULE = "score_date = the LAST canonical trading date of the
calendar month (certified canonical trading calendar); knowledge_cutoff = 23:59:59 UTC on
the score date; months without a qualifying run are skipped."**

Verified for all 63 certified months (2021-01 … 2026-06): in every month
`score_date == last canonical trading date of that month`; in 44/63 it coincides with the
calendar month-end; in 19/63 the month-end fell on a non-trading day (Thu/Fri/weekend/
holiday) and the date walked back; months 2026-02/03/04 are absent (coverage gap) — the
historical precedent for skipped months. Cutoff is EOD-UTC of the score date in all 63.

| Month | score_date | Weekday | Month-end | Last trading date | knowledge_cutoff |
|---|---|---|---|---|---|
| 2021-01 | 2021-01-31 | Sun | 2021-01-31 | = score_date | 2021-01-31T23:59:59Z |
| 2021-02 | 2021-02-28 | Sun | 2021-02-28 | = score_date | 2021-02-28T23:59:59Z |
| 2021-03 | 2021-03-31 | Wed | 2021-03-31 | = score_date | 2021-03-31T23:59:59Z |
| 2021-04 | 2021-04-28 | Wed | 2021-04-30 | = score_date | 2021-04-28T23:59:59Z |
| 2021-05 | 2021-05-31 | Mon | 2021-05-31 | = score_date | 2021-05-31T23:59:59Z |
| 2021-06 | 2021-06-30 | Wed | 2021-06-30 | = score_date | 2021-06-30T23:59:59Z |
| 2021-07 | 2021-07-31 | Sat | 2021-07-31 | = score_date | 2021-07-31T23:59:59Z |
| 2021-08 | 2021-08-31 | Tue | 2021-08-31 | = score_date | 2021-08-31T23:59:59Z |
| 2021-09 | 2021-09-29 | Wed | 2021-09-30 | = score_date | 2021-09-29T23:59:59Z |
| 2021-10 | 2021-10-31 | Sun | 2021-10-31 | = score_date | 2021-10-31T23:59:59Z |
| 2021-11 | 2021-11-30 | Tue | 2021-11-30 | = score_date | 2021-11-30T23:59:59Z |
| 2021-12 | 2021-12-29 | Wed | 2021-12-31 | = score_date | 2021-12-29T23:59:59Z |
| 2022-01 | 2022-01-31 | Mon | 2022-01-31 | = score_date | 2022-01-31T23:59:59Z |
| 2022-02 | 2022-02-28 | Mon | 2022-02-28 | = score_date | 2022-02-28T23:59:59Z |
| 2022-03 | 2022-03-30 | Wed | 2022-03-31 | = score_date | 2022-03-30T23:59:59Z |
| 2022-04 | 2022-04-30 | Sat | 2022-04-30 | = score_date | 2022-04-30T23:59:59Z |
| 2022-05 | 2022-05-31 | Tue | 2022-05-31 | = score_date | 2022-05-31T23:59:59Z |
| 2022-06 | 2022-06-29 | Wed | 2022-06-30 | = score_date | 2022-06-29T23:59:59Z |
| 2022-07 | 2022-07-31 | Sun | 2022-07-31 | = score_date | 2022-07-31T23:59:59Z |
| 2022-08 | 2022-08-31 | Wed | 2022-08-31 | = score_date | 2022-08-31T23:59:59Z |
| 2022-09 | 2022-09-28 | Wed | 2022-09-30 | = score_date | 2022-09-28T23:59:59Z |
| 2022-10 | 2022-10-31 | Mon | 2022-10-31 | = score_date | 2022-10-31T23:59:59Z |
| 2022-11 | 2022-11-30 | Wed | 2022-11-30 | = score_date | 2022-11-30T23:59:59Z |
| 2022-12 | 2022-12-31 | Sat | 2022-12-31 | = score_date | 2022-12-31T23:59:59Z |
| 2023-01 | 2023-01-31 | Tue | 2023-01-31 | = score_date | 2023-01-31T23:59:59Z |
| 2023-02 | 2023-02-28 | Tue | 2023-02-28 | = score_date | 2023-02-28T23:59:59Z |
| 2023-03 | 2023-03-29 | Wed | 2023-03-31 | = score_date | 2023-03-29T23:59:59Z |
| 2023-04 | 2023-04-30 | Sun | 2023-04-30 | = score_date | 2023-04-30T23:59:59Z |
| 2023-05 | 2023-05-31 | Wed | 2023-05-31 | = score_date | 2023-05-31T23:59:59Z |
| 2023-06 | 2023-06-28 | Wed | 2023-06-30 | = score_date | 2023-06-28T23:59:59Z |
| 2023-07 | 2023-07-31 | Mon | 2023-07-31 | = score_date | 2023-07-31T23:59:59Z |
| 2023-08 | 2023-08-30 | Wed | 2023-08-31 | = score_date | 2023-08-30T23:59:59Z |
| 2023-09 | 2023-09-30 | Sat | 2023-09-30 | = score_date | 2023-09-30T23:59:59Z |
| 2023-10 | 2023-10-31 | Tue | 2023-10-31 | = score_date | 2023-10-31T23:59:59Z |
| 2023-11 | 2023-11-29 | Wed | 2023-11-30 | = score_date | 2023-11-29T23:59:59Z |
| 2023-12 | 2023-12-31 | Sun | 2023-12-31 | = score_date | 2023-12-31T23:59:59Z |
| 2024-01 | 2024-01-31 | Wed | 2024-01-31 | = score_date | 2024-01-31T23:59:59Z |
| 2024-02 | 2024-02-28 | Wed | 2024-02-29 | = score_date | 2024-02-28T23:59:59Z |
| 2024-03 | 2024-03-30 | Sat | 2024-03-31 | = score_date | 2024-03-30T23:59:59Z |
| 2024-04 | 2024-04-30 | Tue | 2024-04-30 | = score_date | 2024-04-30T23:59:59Z |
| 2024-05 | 2024-05-29 | Wed | 2024-05-31 | = score_date | 2024-05-29T23:59:59Z |
| 2024-06 | 2024-06-30 | Sun | 2024-06-30 | = score_date | 2024-06-30T23:59:59Z |
| 2024-07 | 2024-07-31 | Wed | 2024-07-31 | = score_date | 2024-07-31T23:59:59Z |
| 2024-08 | 2024-08-31 | Sat | 2024-08-31 | = score_date | 2024-08-31T23:59:59Z |
| 2024-09 | 2024-09-30 | Mon | 2024-09-30 | = score_date | 2024-09-30T23:59:59Z |
| 2024-10 | 2024-10-30 | Wed | 2024-10-31 | = score_date | 2024-10-30T23:59:59Z |
| 2024-11 | 2024-11-30 | Sat | 2024-11-30 | = score_date | 2024-11-30T23:59:59Z |
| 2024-12 | 2024-12-31 | Tue | 2024-12-31 | = score_date | 2024-12-31T23:59:59Z |
| 2025-01 | 2025-01-29 | Wed | 2025-01-31 | = score_date | 2025-01-29T23:59:59Z |
| 2025-02 | 2025-02-26 | Wed | 2025-02-28 | = score_date | 2025-02-26T23:59:59Z |
| 2025-03 | 2025-03-30 | Sun | 2025-03-31 | = score_date | 2025-03-30T23:59:59Z |
| 2025-04 | 2025-04-30 | Wed | 2025-04-30 | = score_date | 2025-04-30T23:59:59Z |
| 2025-05 | 2025-05-31 | Sat | 2025-05-31 | = score_date | 2025-05-31T23:59:59Z |
| 2025-06 | 2025-06-30 | Mon | 2025-06-30 | = score_date | 2025-06-30T23:59:59Z |
| 2025-07 | 2025-07-30 | Wed | 2025-07-31 | = score_date | 2025-07-30T23:59:59Z |
| 2025-08 | 2025-08-31 | Sun | 2025-08-31 | = score_date | 2025-08-31T23:59:59Z |
| 2025-09 | 2025-09-30 | Tue | 2025-09-30 | = score_date | 2025-09-30T23:59:59Z |
| 2025-10 | 2025-10-29 | Wed | 2025-10-31 | = score_date | 2025-10-29T23:59:59Z |
| 2025-11 | 2025-11-30 | Sun | 2025-11-30 | = score_date | 2025-11-30T23:59:59Z |
| 2025-12 | 2025-12-31 | Wed | 2025-12-31 | = score_date | 2025-12-31T23:59:59Z |
| 2026-01 | 2026-01-31 | Sat | 2026-01-31 | = score_date | 2026-01-31T23:59:59Z |
| 2026-02 | — | — | — | no score date (coverage gap) | — |
| 2026-03 | — | — | — | no score date (coverage gap) | — |
| 2026-04 | — | — | — | no score date (coverage gap) | — |
| 2026-05 | 2026-05-31 | Sun | 2026-05-31 | = score_date | 2026-05-31T23:59:59Z |
| 2026-06 | 2026-06-30 | Tue | 2026-06-30 | = score_date | 2026-06-30T23:59:59Z |

## Part 2 — Decision-schedule parity

- Replay of the V1 rule ("earliest qualifying run whose as_of falls in a strictly later
  calendar month") over the historical as_of series: **63/63 exact, 0 mismatches,
  0 missing, mean/max displacement 0.0 days** — but this match is an artifact of the
  historical artifact having exactly one as_of per month, positioned at the month's last
  trading day.
- The identical rule applied to real production stamps (`as_of` 2026-09-24 … 2026-10-02,
  including a Friday and multiple re-runs) fires **mid-month** (2026-10-01) — a different
  economic monthly timing.
- **SHADOW_DECISION_SCHEDULE_PARITY (V1 as written) = FAIL.** Not launched under V1.
  Resolution: V1.1 §2 defines the forward analogue — the decision run's `as_of_date` must
  be the **certifiable last canonical trading date of the decision month** (two-clause
  certainty: structural weekday walk-back, or month fully elapsed with as_of = last
  recorded session), cutoff window per V1.1 §3, months without such a run skipped, no
  backfill. **SHADOW_DECISION_SCHEDULE_PARITY (V1.1) = PASS.**
- Predicate audit of all 12 existing canonical-v1-dev runs against the V1.1 rule:
  **0 qualify** (the two 2026-09-30 runs sit exactly on September's certified last trading
  date — convention validated — but pre-date the freeze; `launch_audit/v1_1_predicate_audit.json`).

## Part 3 — Mid-session guard

**MID_SESSION_GUARD = OPERATIONAL_ONLY.** The 12:45-Tehran guard was not part of the
historical information contract (cutoff = EOD UTC of score date). V1.1 §3 freezes it as a
window — lower bound 12:45 Tehran on as_of (operational, final post-close prices; the time
is not optimized), upper bound EOD UTC on as_of (the historical contract itself). It can
only disqualify a run; it can never move a decision to another day or month.

## Part 4 — Execution calendar parity

**SHADOW_EXECUTION_CALENDAR_PARITY = PASS.** Shadow calendar (no Thu/Fri; breadth ≥ 30
securities with volume > 0) vs certified calendar over all 63 decisions: **63/63 exact, 0
mismatches, 0 missing**. The filter excludes 50 low-breadth collector-artifact dates
(breadth 1–6, Jun 2025–May 2026); none was ever a certified execution date; 0 shadow dates
fall outside the certified calendar (`launch_audit/calendar_parity.json`).

## Part 5 — Raw price contract parity

**SHADOW_PRICE_CONTRACT_PARITY = PASS.** Three independent legs — (A) certified execution
pipeline chain (`execute_score_portfolio_v1.build_adj`), (B) the chain the shadow observer
actually imports (`repair_accounting_v1.build_adj/price_at`), (C) an independent
recomputation in certified factor order — agree with **zero difference** (max abs diff
0.000e+00) on **229 priced (security × execution-date) pairs** from 233 samples, spanning
2021–2026 and all four event classes (capital increases 30, rights issues 30, reverse
splits 17, confirmed unclassified mechanical resets 30, normal 126); 4 pairs consistently
absent (security not yet listed — all legs agree); 229 exact-session raw-pClosing checks
with 0 conflicting duplicates. Vendor-adjusted BRS was not used
(`launch_audit/price_contract_parity.json`).

## Part 6 — Forward raw-cache refresh (genuine, post-freeze)

**FORWARD_RAW_CACHE_REFRESH_PROVEN = YES.** Evidence:
`launch_audit/forward_refresh_evidence_20261003T193204Z.json`.

- Cycle 2026-10-03T19:25:19Z → 19:32:04Z; **every fetch timestamp after the spec freeze
  instant (2026-10-03T18:45:00Z)**; 0 failures.
- **New session 2026-10-03 acquired** (real Saturday session; no weekend fabrication): raw
  `pClosing` retained verbatim, all vendor fields preserved, 0 `insCode` identity mismatches.
- Coverage after cycle: **271/271 scored companies** (was 238 files / 235 map rows).
- Merge semantics (V1.1 §6): append by `(dEven, hEven)`, first-seen-wins; 172 same-day
  late arrivals for already-covered sessions skipped (protects the certified chain's
  last-record-per-dEven read); 2,207 vendor-revised existing records ignored — field-level
  audit shows revisions touch `priceChange` bookkeeping only, **0 pClosing differences**;
  rewritten files carry pre/post SHA-256.
- Six Thu/Fri vendor-history dates (2016-2018) arrived inside newly onboarded instruments'
  full histories; they are reported, calendar-excluded, never deleted.

## Part 7 — Identity onboarding

**SHADOW_IDENTITY_ONBOARDING_READY = YES.** Deterministic rule (V1.1 §7; no symbol-only
acceptance), append-only ledger `identity_onboarding_ledger.jsonl` (batch
`ONBOARD-20261003T193414Z`, basis run `e5998f6d-93ab-4577-b13a-7b2f89c39c02`):

| Classification | Count |
|---|---|
| HISTORICAL_MAP_VERIFIED | 235 |
| FORWARD_MAP_VERIFIED | 36 |
| UNRESOLVED | 0 |
| AMBIGUOUS | 0 |
| **Total classified (latest run universe)** | **271** |

A selected UNRESOLVED/AMBIGUOUS name can never receive a paper fill; its target weight
stays cash (frozen failed-execution rule). The ledger is re-verified live at every build.

## Part 8 — Eligibility layers (not silently expanded)

`SCORE ELIGIBLE` (frozen score rule ranking universe) ⊇ `SELECTED TOP20` ⊇ `IDENTITY
VERIFIED` ⊇ `PRICE OBSERVABLE` ⊇ `EXECUTABLE`. Execution failure never removes a company
from the ranking universe or future selection; it only routes that target to cash.

## Part 9 — SHADOW DECISION #1 (exact condition)

Decision #1 is created only when: a production run qualifies under V1.1 §2 (as_of =
certifiable last canonical trading date of month M, e.g. **2026-10-31** for October 2026;
completed after 2026-10-03T18:45:00Z; cutoff within the §3 window; earliest qualifying run
of M; month not already decided) — and its decision artifacts (snapshot / targets / orders
/ state entry) are frozen **before the projected execution date begins**. The entry binds
decision month, run_id, as_of_date, source_cutoff_at, completed_at, identity
classification snapshot, decision freeze timestamp, and projected execution date. No
genuinely qualifying run exists today; Decision #1 is NOT created in this audit.

## Part 10 — Forward clock

**SHADOW_FORWARD_CLOCK_STARTED = NO.** The 12-cycle prospective clock starts only when a
valid Decision #1 is frozen per Part 9 before its execution outcome is observed. Spec
freeze dates do not start the clock.

## Determinism after the V1.1 harness changes

Full suite re-executed after the V1.1 code changes: T1 unit tests A–E PASS, T2 500-case
invariant sweep PASS, T3 parity vs certified engine max diff 5.68e-14 (float
summation-order noise) PASS, T4 observer month-close 10/10 PASS, T5 byte-identical
artifacts across PYTHONHASHSEED 1/2/3 PASS. Production dry-runs remain no-ops.

## Engineering change log

- `shadow_common.raw_caches_max_date()` filename parsing fixed (`.json` leaked into
  ins_code; would have forced every observation to finalize by deadline as DATA_MISSING).
  Defect found by this audit; never reached an observation.
- `refresh_raw_caches_forward.py` (V1.1 §6) and `onboard_shadow_identities.py` (V1.1 §7)
  added; builder `next_decision_run`/`resolve_identity` implement V1.1 §2/§3/§7; observer
  benchmark executability requires identity verification.
- One aborted partial refresh cycle (before the filename fix) was killed within 25 fetches;
  its writes were merge-append only and are indistinguishable from the certified cycle's
  (idempotent semantics); the certified evidence above is the completed corrected cycle.

## Final flags

SHADOW_DECISION_SCHEDULE_PARITY = FAIL (V1 as written) → **PASS under V1.1**
MID_SESSION_GUARD = **OPERATIONAL_ONLY**
SHADOW_EXECUTION_CALENDAR_PARITY = **PASS**
SHADOW_PRICE_CONTRACT_PARITY = **PASS**
FORWARD_RAW_CACHE_REFRESH_PROVEN = **YES**
SHADOW_IDENTITY_ONBOARDING_READY = **YES**
SHADOW_DATA_PIPELINE_READY = **YES**
SHADOW_LIVE_START_READY = **YES** (under V1.1; start awaits a genuinely qualifying run)
SHADOW_FORWARD_CLOCK_STARTED = **NO**
REAL_MONEY_ORDERS_ENABLED = **NO**
BROKER_CONNECTION_ENABLED = **NO**
