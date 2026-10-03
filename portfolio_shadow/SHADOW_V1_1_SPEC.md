# SHADOW V1.1 — PRE-LAUNCH CLARIFICATION SPEC (supersedes SHADOW_V1 for schedule, guard, refresh, and identity semantics)

Frozen BEFORE any shadow decision or observation exists. This is a PRE-FIRST-DECISION
correction only: no shadow outcome has ever been observed, so no prospective evidence is
contaminated. The original spec `SHADOW_V1_SPEC.md` (SHA-256
`959b56904added66812ab3726fc067112d7bc12ab3d58d8334f3c4381540df3a`) is preserved
UNCHANGED and remains authoritative for everything not clarified here.

## 0. What V1.1 changes — and what it does NOT

Changed (clarified to match the certified historical SCORE_PORTFOLIO_V1 conventions):
§2 monthly decision schedule, §3 source-cutoff window, §6 forward cache-refresh mechanics,
§7 identity onboarding, §8 eligibility-layer definitions, §9 Decision #1 convention.

NOT changed (still frozen exactly as V1 / preregistration):
production score `canonical-v1-dev`; Top20 selection `n = max(1, floor(0.20 × N_eligible))`
with ties `(quant_score DESC, symbol ASC)`; equal target weights before failed executions;
monthly rebalance; 50 bps one-way BASE costs; certified repaired accounting engine
(deterministic port); paper-only restriction; benchmark = equal-weight all eligible with
identical conventions; write-once artifacts; append-only issues log; minimum 12 prospective
cycles; no automatic promotion to real money; no broker connectivity; execution calendar of
V1 §5a (re-certified in §4 below).

## 1. Historical decision schedule (recovered — launch audit Part 1)

The certified SCORE_PORTFOLIO_V1 backtest used 63 monthly score dates,
2021-01-31 … 2026-06-30 (`ui_score_historical_pit_v2.parquet`, SHA
`543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a`). Recovered rule:

- **score_date = the LAST canonical trading date of the calendar month** (verified for all
  63 months against the certified canonical trading calendar). In 44/63 months this equals
  the calendar month-end; in 19/63 months the month-end fell on a non-trading day
  (Thu/Fri/weekend/holiday) and the date walked back to the last trading day.
- **knowledge_cutoff = 23:59:59 UTC on the score date** (all 63 months).
- 3 of the 66 calendar months (2026-02, 2026-03, 2026-04) have NO score date (production
  coverage gap): skipped months are part of the historical convention.

`HISTORICAL_DECISION_SCHEDULE_RULE = "score at the last canonical trading date of each
calendar month; knowledge cutoff EOD UTC of that date; months without a qualifying run are
skipped."` Full per-month table: `launch_audit/historical_decision_schedule.json`.

## 2. Monthly decision rule (forward analogue — replaces the V1 §1 cadence sentence)

V1's rule ("earliest qualifying run whose as_of_date falls in a strictly later calendar
month") replays 63/63 against the historical series, but it does not ENCODE the historical
timing convention: applied to actual production run stamps (which occur on arbitrary days,
e.g. as_of 2026-10-01, 2026-10-02) it would fire mid-month — a different economic monthly
timing (launch audit Part 2 verdict: FAIL as written). The forward analogue:

- **Decision month M** (first decision: any month; thereafter strictly later calendar month
  than the previous decision; one decision per calendar month).
- A production run qualifies for month M iff ALL hold:
  1. `status='completed'`, `score_version='canonical-v1-dev'`;
  2. `completed_at > 2026-10-03T18:45:00Z` (the preserved V1 freeze instant);
  3. `as_of_date` == the **last canonical trading date of month M**, accepted only when
     that property is CERTAIN at build time (a mid-month build cannot know that later
     sessions will not occur):
       (a) every calendar date d with `as_of_date < d ≤` calendar month-end of M is a
           Thursday or a Friday (no possible further M session under the frozen weekday
           rule); OR
       (b) the calendar month M has fully elapsed at build time (build date > month-end
           of M) AND as_of_date is the last canonical trading date of M in the recorded
           calendar. Clause (b) rescues months whose month-end weekday is a market
           holiday (historical precedent: 2024-03, last session Sat 2024-03-30, month-end
           Sun 2024-03-31 closed). A mid-month as_of can never qualify;
  4. the §3 source-cutoff window holds;
  5. the earliest such run by `completed_at` is THE decision for M (re-runs of the same
     as_of never displace it);
  6. the projected execution date (first §4 calendar date strictly after as_of) has not
     begun at build time — if it is past, or today-with-session-closed, the month is
     SKIPPED as LATE (a decision may never be backfilled).
- If no run qualifies for M, month M is **skipped and logged** (historical precedent). No
  substitute run, no mid-month acceptance, no schedule optimization.

## 3. Source-cutoff window (launch audit Part 3: the V1 guard was OPERATIONAL_ONLY)

The historical information contract is "all knowledge ≤ EOD UTC of the score date"; the V1
12:45-Tehran guard was an operational data-quality guard, not part of that contract. V1.1
freezes it as a two-sided window; it cannot shift a decision to another day or month (it
can only disqualify a run, leaving the month skipped):

- **lower bound (operational):** `source_cutoff_at ≥ 12:45 Tehran on as_of_date`
  (session closes ~12:30 Tehran; guarantees final post-close prices);
- **upper bound (historical contract):** `source_cutoff_at ≤ 23:59:59 UTC on as_of_date`
  (= EOD UTC of as_of, exactly the historical knowledge cutoff; prevents a next-morning
  data pull from contaminating the month-end information set).

No time in this window is ever optimized.

## 4. Execution calendar (launch audit Part 4: PASS, unchanged)

V1 §5a stands: a canonical trading date has ≥ 30 distinct securities with volume > 0 in
`market.price_observations` and is not a Thursday/Friday. Certification over the full
historical period: the shadow calendar reproduces the **certified execution date exactly in
63/63 decisions** (0 mismatches, 0 missing); it excludes 50 low-breadth collector-artifact
dates (breadth 1–6, Jun 2025–May 2026) — none was ever a certified execution date — and
contains 0 dates outside the certified calendar. `EXECUTION_DATE = first canonical trading
date strictly after as_of`; decision-time projection is frozen, final E is recomputed at
observation (change logged, never applied later-ward).

## 5. Raw price contract (launch audit Part 5: PASS, unchanged)

Path-A = raw closing cache `pClosing` × CONFIRMED `tsetmc_gap_rule_v1` adjustment factors
via the certified `repair_accounting_v1.build_adj`/`price_at` (imported unmodified by the
shadow observer). Vendor-adjusted BRS series remain diagnostic-only (path B). Certification:
three independent legs (certified execution pipeline chain; shadow observer chain source;
independent recomputation in certified factor order) agree with **zero difference** on 229
priced (security × execution-date) pairs spanning 2021–2026 and all four event classes
(capital increases, rights issues, reverse splits, confirmed unclassified mechanical
resets), plus 4 consistently-absent pairs and 229 exact-session raw-pClosing checks with
zero conflicting duplicates. See `SHADOW_V1_LAUNCH_CERTIFICATION.json`.

## 6. Forward raw-cache refresh (V1 §5c mechanism, now specified)

`refresh_raw_caches_forward.py` is the only forward writer of the raw caches. Per cycle:

- paced re-fetch of the TSETMC `GetClosingPriceDailyList` API for every existing cache and
  every scored-but-uncached identity-clean company (onboarding acquisition);
- **merge semantics:** records keyed by `(dEven, hEven)`; existing records kept VERBATIM
  (first-seen-wins — no retrospective rewrite of a session close; PIT-preserving); new
  sessions appended; a second intraday record for an already-covered session is SKIPPED and
  counted (it could otherwise rewrite the certified chain's last-record-per-dEven read);
  vendor revisions of existing records are counted and ignored; a file is rewritten only
  when it gains records, with pre/post SHA-256 recorded;
- every accepted record must carry `insCode == filename ins_code` (source identity);
- per-cycle evidence JSON (fetch timestamps, per-symbol rows, added session dates, weekday
  histogram, failures) is written under `launch_audit/`; no backdating; the cycle never
  fabricates sessions — weekend/holiday artifacts, if the vendor ever returns them, are
  reported and excluded by the §4 calendar, never deleted;
- observation finalization (cache coverage of E, or E+7-day deadline → DATA_MISSING) is
  unchanged from V1 §15b.

Launch audit Part 6 documents one genuine post-freeze cycle (all fetch timestamps after the
freeze instant; new session 2026-10-03 acquired with raw pClosing retained).

## 7. Identity onboarding (launch audit Part 7)

Classification of every scored company (deterministic, no symbol-only acceptance):

- **HISTORICAL_MAP_VERIFIED** — bound by the certified 235-row historical identity map
  (`mapping_status=UNIQUE`, same symbol + ins_code as the company's primary security).
- **FORWARD_MAP_VERIFIED** — not in the historical map, but: exactly ONE primary security
  in `core.securities`; canonical symbol and TSETMC ins_code present; raw cache exists for
  `(symbol, ins_code)` and EVERY record inside carries the same insCode; the map does not
  bind that symbol to another instrument. Persisted **append-only** in
  `identity_onboarding_ledger.jsonl` (sole writer: `onboard_shadow_identities.py`,
  idempotent batches).
- **UNRESOLVED** — no primary security / missing symbol or ins_code / no cache.
- **AMBIGUOUS** — multiple primary securities, certified-map conflict, symbol reused across
  instruments, or price-source identity conflict.

Fill gate: only MAP_VERIFIED and FORWARD_MAP_VERIFIED receive paper fills. A selected
UNRESOLVED/AMBIGUOUS name can NEVER receive a fill — its target weight stays cash (frozen
failed-execution rule). The ledger is re-verified live at every decision build; the live
evidence must still hold.

## 8. Eligibility layers (never silently expanded or collapsed)

`SCORE ELIGIBLE` (every row of the decision run — the ranking universe, governed solely by
the frozen score rule) ⊇ `SELECTED TOP20` (frozen selection arithmetic) ⊇ `IDENTITY
VERIFIED` (fill-eligible subset) ⊇ `PRICE OBSERVABLE` (cache holds the session) ⊇
`EXECUTABLE` (identity verified AND volume > 0 on E). Execution failure never removes a
company from the ranking universe or from future selection; it only routes that target to
cash for the current cycle. The benchmark applies the identical layers.

## 9. SHADOW DECISION #1 — exact deterministic condition

Decision #1 exists iff a run qualifying under §2 exists for some month M (with M's month
ended and its calendar recorded), the §7 onboarding state is current, and the decision
artifacts (snapshot / targets / orders / state entry, §14 of V1) are frozen BEFORE the
projected execution date begins. The decision entry binds: decision month, run_id,
as_of_date (= last canonical trading date of M), source_cutoff_at (within the §3 window),
completed_at, identity classification counts from the ledger state at build, decision
freeze timestamp (= artifact write), and projected execution date. Decision #1 is never
created manually and never backfilled.

## 10. Forward clock

The 12-cycle prospective evaluation clock starts ONLY when a valid Decision #1 is frozen
per §9 BEFORE its execution outcome is observed. Spec freeze dates (V1 or V1.1) do not
start the clock.

## 11. Engineering change log (this clarification)

- `shadow_common.raw_caches_max_date()` filename parsing fixed (`.json` leak into ins_code;
  would have forced every observation to finalize by deadline with DATA_MISSING). Defect
  never reached an observation.
- `refresh_raw_caches_forward.py` and `onboard_shadow_identities.py` added (§6, §7).
- `build_shadow_portfolio.next_decision_run` implements §2/§3; `resolve_identity`
  implements §7; snapshot rows carry `primary_count`.
- Observer benchmark executability now requires identity verification (§8).
- Accounting engine, selection, costs, artifacts: unchanged.
