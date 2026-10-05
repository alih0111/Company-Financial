# PREREGISTRATION — SCORE EXPANSION RESEARCH V1 (RESEARCH ONLY)

Status: **HISTORICAL EVIDENCE SYNTHESIS study.** No untouched historical holdout remains;
every number produced under this document is descriptive historical evidence, NOT fresh
validation. Nothing here promotes, activates, or modifies any score.

This document and `spec_frozen.json` are hashed (SHA-256) BEFORE any forward-return,
IC, spread, or portfolio diagnostic is computed. The SHA values are recorded in
`_spec_sha.txt`. Execution happens ONCE, exactly as specified here; failures are
reported, not patched silently.

---

## 0. Hard constraints (restated, binding)

- Production V1 (`canonical-v1-dev` engine, `analytics.*`) is NOT modified. Shadow V1.1
  is NOT modified. No V4. No weight optimization. No threshold search. No activation.
  No broker. No real-money orders. No SQL Server (Postgres reads are SELECT-only).
- No "Super Score"; no combination of candidate scores with `quant_score`.
- Artifacts are written ONLY to `score_expansion_research/`.

## 1. Frozen inputs (SHA-verified at run time)

| Artifact | Path | Verification |
|---|---|---|
| Certified PIT base panel (V1 rebuild per signal date, proven `visible_from` rule) | `ui_score_research/ui_score_historical_pit_v2.parquet` (+ `.jsonl`) | SHA must equal `v2lib.SHA_PANEL_PQ` / `SHA_PANEL_JSONL` |
| Certified derived panel (features + frozen forward returns) | `score_v2_research/pit_feature_panel.parquet` | SHA must equal `score_v3_minimal_research/_input_shas.json:pit_feature_panel_sha` |
| Daily market panel (tradability) | `research_bundle/daily_market_panel.parquet` | SHA = `v2lib.SHA_DAILY` |
| Corporate actions / calendar / securities cache | `score_v2_research/_cache/*` | certified chain (`tsetmc_gap_rule_v1`, CONFIRMED only) |
| Raw TSETMC files | `historical_codal_backfill/output/raw_closing_universe/` | as certified |
| Portfolio engine | `portfolio_research/repair_accounting_v1.py` | SHA = `v2lib.SHA_REPAIR` |
| Frozen seeds | — | `SEED = 20261003`, `B = 2000`, IC bootstrap block = 3 signal dates, portfolio bootstrap block = 6 monthly observations |
| PIT contract | `score_v2_research/_pit_contract_result.json` | must read PASS |

Panel shape asserted at run time: 12,604 rows; 63 monthly signal dates
2021-01-31 … 2026-06-30; split frozen: development ≤ 2024-06-30 (42), validation
2024-07-01…2024-12-31 (6), locked holdout ≥ 2025-01-01 (15). The split is REPORTED
(as a diagnostic grouping) but never used for selection, because nothing is selected.

## 2. V1 reference (untouched)

`V1 = ui_score` per (as_of, symbol): the exact frozen production engine
(`canonical-v1-dev`, VAL_DIRECT) rebuilt PIT per signal date. Components:
`growth_score`, `profitability_score`, `valuation_score`, `market_score`,
`data_quality_score`. V1 percentile rank per date = cross-sectional midrank
(`v2lib.midrank_pct`, present-only) of `ui_score`.

## 3. Candidate score families — FROZEN construction

Common rules for ALL four scores:

- **Feature transform:** cross-sectional midrank percentile among present (finite)
  values per signal date (`midrank_pct`), 0..1, direction fixed below.
- **Aggregation:** `score_raw = mean(available feature percentiles)`; final score
  `S = 100 × score_raw` (interpretable 0–100).
- **Missing values:** a missing feature is EXCLUDED and the mean is taken over the
  available features (renormalization). There is NO neutral fill inside candidate
  scores. A row whose available-feature count is below `min_feats` gets `S = null`.
  This renormalization effect (implicit up-weighting of available features) is
  documented per score via the effective-contribution table (§3.5).
- **Caps** replicate the frozen V1 engine caps where a V1 analogue exists; new
  features use the cap stated below. Capping is applied to raw values BEFORE ranking.
- No candidate score uses DQ gating; coverage behavior is reported instead.

### 3.1 A — FUNDAMENTAL_MOMENTUM_SCORE (FM) — min_feats = 5 of 9

Purpose: improvement/acceleration of fundamentals, distinct from V1's level-of-growth
block by the last three features (acceleration and consistency). Equal-weight ranks
(predeclared; no optimizer).

| # | Feature (panel source) | Raw definition | Direction | Cap |
|---|---|---|---|---|
| 1 | sales_growth_12m | panel `sales_growth_12m` | + | ±150 |
| 2 | sales_growth_3m | panel `sales_growth_3m` | + | ±150 |
| 3 | revenue_growth | panel `revenue_growth` | + | ±200 |
| 4 | operating_profit_growth | panel `operating_profit_growth` | + | ±250 |
| 5 | earnings growth | `net_profit_growth` else `eps_growth` | + | ±300 |
| 6 | margin_trend | panel `margin_trend` | + | ±25 |
| 7 | sales_growth_accel | `f_sales_growth_accel` (certified: sg12(T) − sg12(prev row 70–100d back)) | + | ±150 |
| 8 | profit_growth_accel | `f_profit_growth_accel` (certified chain, same anchor rule) | + | ±300 |
| 9 | profit_growth_consistency | `f_profit_growth_consistency` (certified: −std over rows T, T−1q, T−2q, T−3q, ddof=0; all 4 required) | + | ±100 (predeclared; values are negated std of capped units) |

### 3.2 B — EARNINGS_QUALITY_RESILIENCE_SCORE (EQ) — min_feats = 5 of 8

Purpose: quality / repeatability / balance-sheet resilience of earnings.

| # | Feature | Raw definition | Direction | Cap |
|---|---|---|---|---|
| 1 | cash_conversion | panel `cash_conversion` | + | [−2, 5] |
| 2 | earnings_quality (non-operating share) | panel `earnings_quality` | − | min(abs, 150) |
| 3 | interest_coverage | panel `interest_coverage`; ≤0 → −999999 sentinel (worst) | + | min(x, 20), sentinel wins bottom rank |
| 4 | sales_stability | panel `sales_stability` | + | none |
| 5 | leverage | panel `debt_ratio` | − | min(x, 50) |
| 6 | current_ratio | panel `current_ratio` | + | min(x, 15) |
| 7 | net-margin stability | `f_earnings_margin_stability` (certified: −std(net_margin, 4 rows)) | + | ±40 |
| 8 | operating-margin improvement | `f_operating_margin_delta` (certified: om(T) − om(prev row 70–100d)) | + | ±25 |

Known coverage limitation (declared up front): features 7–8 require the 70–100d anchor
row, so their coverage is materially below 100% and historical cash-flow support is only
proxied by `cash_conversion` (OCF-based, materialized only when OCF history exists).
Coverage is audited in Part 2; no hidden neutral fill exists.

### 3.3 C — LIQUIDITY_CAPACITY_SCORE (LQ) — min_feats = 2 of 3

Purpose: implementability, NOT alpha. LQ is never used to modify V1 rankings in this
study.

| # | Feature | Raw definition | Direction | Cap |
|---|---|---|---|---|
| 1 | traded_days_ratio_60 | certified `t_traded_days_ratio_60`: fraction of last 60 file-records with qTotTran5J > 0 | + | none |
| 2 | avg traded value 30d | certified `t_trade_value_30d`: mean raw qTotCap (rial) over last 30 sessions | + | none (ranked) |
| 3 | liquidity stability | NEW `tval_cv60` = std(qTotCap, 60 sessions, ddof=1) / mean(qTotCap, 60 sessions), raw rial | − | none |

`tval_cv60` is computed from the same raw files through the certified
`v2lib.MarketData` path, at the same per-date sampling points as the certified
technical features, and is only defined where the certified
`t_traded_days_ratio_60` is defined (identical 200-session gate → identical sample).
It uses sessions ≤ T only (raw traded value; no corporate-action adjustment applies to
traded value), therefore PIT-safe by construction.

### 3.4 D — TECHNICAL_CONFIRMATION_SCORE (TC) — min_feats = 6 of 8

Deliberately small, per directive; no indicator zoo.

| # | Feature | Raw definition | Direction | Cap |
|---|---|---|---|---|
| 1 | momentum 20d | certified `t_mom_20` | + | ±100 |
| 2 | momentum 60d | certified `t_mom_60` | + | ±100 |
| 3 | momentum 120d | certified `t_mom_120` | + | ±100 |
| 4 | MA60 slope | certified `t_ma60_slope` | + | ±50 |
| 5 | price vs MA60 | certified `t_price_vs_ma60` | + | ±80 |
| 6 | drawdown from 60-session high | certified `t_dist_high_60` | + | [−1, 0] |
| 7 | vol-adjusted momentum | NEW `vam60` = (c(T)/c(T−59) − 1) / (std(session returns, 60, ddof=1) + 1e-12), certified chain, sessions ≤ T only | + | ±30 |
| 8 | vol 60d | certified `t_vol_60` | − | none |

`vam60` is a ratio of two chain-invariant window quantities ending ≤ T (adjusted
close ratio and std of adjusted session returns), therefore chain-invariant and
PIT-safe (same argument as certified leakage test B). Sampled where both mom_60 and
vol_60 windows exist (≥60 sessions); inherited 200-session gate applies only insofar
as the certified columns are gated identically.

### 3.5 Published per score (Part 3 outputs)

Exact formula (above), feature directions, missing-value treatment (renormalize +
`min_feats` gate), minimum required coverage (= `min_feats`), effective feature
contribution (mean over defined rows of [1 if feature present else 0] / n_available),
score distribution per date (P10/25/50/75/90 + mean), and month-to-month cross-sectional
rank persistence (Spearman on common symbols between consecutive signal dates; mean +
median).

## 4. Analysis plan (all executed once, after hashing)

### 4.1 Part 2 — PIT & coverage audit
Per candidate feature and per score: source table/file (as in §3), PIT availability
rule (proven `visible_from` ≤ knowledge_cutoff for fundamentals; sessions ≤ T for
market features; shares `knowledge_from` rule unchanged), coverage by date (CSV
matrix), median / minimum / current (2026-06-30) coverage, renormalization rate
(fraction of defined-score cells where a feature was absent), missingness
informativeness (per-date Spearman of the missing-indicator vs `ret_63`, aggregated
median + positive-date fraction — diagnostic only), leak check: every candidate input
is either a certified PIT panel column (contract PASS on file) or derived from
sessions ≤ T only (chain-invariant or raw); hard-fail any feature that fails; none
silently backfilled; no current shares backward; no `collected_at` misuse.

### 4.2 Part 4 — Redundancy / orthogonality
Per candidate score per date: Spearman vs V1 (`ui_score`) and vs each component
(`growth_score`, `profitability_score`, `valuation_score`, `market_score`) on common
defined rows. Report median across dates, P10/P25/P75/P90, last-date value, top-10%
and top-20% overlap (|A∩B|/k, k = round(10%/20% of common rows), both sets by score).
Score-vs-score: per-date Spearman between each candidate pair. Classification:
`REDUNDANCY_WITH_V1`: HIGH if median|ρ(V1)| ≥ 0.7; MEDIUM if 0.4–0.7; LOW if < 0.4.
`ORTHOGONAL_INFORMATION`: HIGH ⇔ LOW redundancy; MEDIUM ⇔ MEDIUM; LOW ⇔ HIGH.

### 4.3 Part 5 — Standalone diagnostics (HISTORICAL EVIDENCE SYNTHESIS)
Per candidate score: per-date IC (Spearman, min_pairs=5, frozen `v2lib.ics`) vs
frozen `ret_21/63/126/252`; mean/median IC, positive-date fraction, block-3 bootstrap
CI (SEED 20261003, B=2000); Q5–Q1 spreads at h=63 and 126 (`v2lib.qspread`,
min_rows=10) with mean Q1..Q5 and monotonicity step count (0–4); year-by-year mean IC;
era medians E1 = 2021-01…2022-12, E2 = 2023-01…2024-12, E3 = 2025-01…2026-06.

### 4.4 Part 6 — Incremental information vs V1 (headline test)
1. **Partial-rank IC:** per date, OLS of candidate percentile on V1 percentile
   (cross-section, defined rows); residual → Spearman vs `ret_h` →
   `INCREMENTAL_IC_h`, h ∈ {21,63,126,252}; aggregate + block-3 bootstrap CI.
2. **Within-V1-bucket:** V1 quintiles per date (defined rows, `ui_score`); per-date
   Spearman(candidate, ret_63) within each bucket (min 4 pairs); pooled median per
   quintile.
3. **Conditional top/bottom:** within V1 Top-20% per date: high-vs-low split at the
   candidate median → mean `ret_63`/`ret_126` difference per date; aggregate +
   block-3 bootstrap; and within-Top-20% IC.
Classification (frozen): **YES** iff (CI_lower > 0 for INC-IC63 or INC-IC126) AND
median within-quintile IC > 0 in ≥ 4 of 5 quintiles; **WEAK** iff median INC-IC > 0 at
both 63 and 126 but no CI excludes 0; **NO** iff median INC-IC ≤ 0 at both 63 and 126;
**INCONCLUSIVE** iff the score is defined on < 50% of V1's defined (as_of, symbol) rows.

### 4.5 Part 7 — Fixed descriptive overlays (no optimization, no promotion)
Certified engine (`repair_accounting_v1.simulate`) at costs GROSS/LOW/BASE/HIGH;
headline = BASE (50 bps). Bench = V1 Top-20% (`ui_score`, frac 0.20). Overlays
(predeclared, no threshold search):
- U/L: within V1 Top-20%, upper vs lower half by candidate score (simulate frac 0.50
  on the Top-20%-restricted frame with score = candidate; the complementary half is
  the same frame scored by −candidate).
- T1/T2/T3: top / middle / bottom tertile within V1 Top-20% (frac 1/3 on the
  restricted frame; bottom tertile = −candidate, frac 1/3).
Report per overlay vs bench: CAGR, MDD, annualized volatility, mean monthly turnover,
average holdings, mean monthly excess, block-6 bootstrap CI of excess, mean selection
overlap (fraction of V1 Top-20% names held), and capacity impact (join to Part 8
cap ratios at the snapshot date). Diagnostic only; no strategy is created.

### 4.6 Part 8 — Liquidity special test
Per date and at the snapshot: for V1 Top-20% and for each U/L candidate split:
cap_ratio(size) = (size / n_names) / TV30_toman for sizes {100M, 500M, 1B, 5B, 10B}
toman (TV30 rial → toman = rial/10, stated certified assumption); fraction of names
with cap_ratio > 1% / 2% / 5% / 10%; mean missed-session rate (1 − traded_days_ratio_60);
fraction failing L1 (pct_td60 < 0.10), L2 (pct_tv30 < 0.10), L3 (both < 0.15) using
cross-sectional percentiles within the analyzed universe. No fills assumed; V1
selection untouched. Question answered: does LQ expose implementation information V1
does not?

### 4.7 Part 9 — Technical special test
Explicit tests: ρ(TC, ui_score); ρ(TC, market_score); ρ(TC, V1 MomentumRank
percentile); per-date median Spearman matrix among the 8 TC features (max off-diagonal
median reported); incremental IC after V1 (§4.4); conditional value inside V1 Top-20%
(§4.4.3). Frozen verdict rule: `TECHNICAL_CONFIRMATION_VALUE = NO` iff
REDUNDANCY_WITH_V1 ∈ {HIGH, MEDIUM} AND INCREMENTAL_INFORMATION ≠ YES.

### 4.8 Part 10 — Regime stability
Era medians (§4.3) + yearly medians; classification: BROADLY_STABLE if all three era
median ICs share one sign and max|era|/min|era| ≤ 3; REGIME_DEPENDENT if signs differ
or ratio > 3; plus concentration diagnostics: mean IC excluding the 3 strongest-|IC|
dates; share of the sum of positive ICs contributed by the top-3 dates; share of the
sum of positive Q5−Q1 (h=63) spreads contributed by the top-10 spread dates.

### 4.9 Part 11 — Score card & statuses
Per candidate: PIT_SAFE, COVERAGE, STANDALONE_INFORMATION, INCREMENTAL_INFORMATION_VS_V1,
REDUNDANCY_WITH_V1, REGIME_STABILITY, TURNOVER_IMPACT, IMPLEMENTABILITY_VALUE,
RESEARCH_VALUE (HIGH/MEDIUM/LOW/NO/INCONCLUSIVE) + one status A–E per directive §11.
RESEARCH_VALUE rule (frozen): HIGH iff INCREMENTAL = YES and REDUNDANCY = LOW;
MEDIUM iff (INCREMENTAL ∈ {YES, WEAK} and REDUNDANCY ∈ {LOW, MEDIUM}); LOW iff
INCREMENTAL = WEAK or (STANDALONE = HIGH with REDUNDANCY = HIGH); NO iff
INCREMENTAL = NO; INCONCLUSIVE iff coverage-driven INCONCLUSIVE.
Status rule: A = RESEARCH_VALUE HIGH; B = implementation-only (LQ-type: IMPLEMENTABILITY
HIGH, alpha not required); C = REDUNDANCY HIGH and INCREMENTAL ≠ YES; D = WEAK_OR_UNSTABLE
(REGIME_DEPENDENT with RESEARCH_VALUE ≤ MEDIUM); E = INSUFFICIENT_DATA (coverage
INCONCLUSIVE).

### 4.10 Part 13 — Current snapshot (RESEARCH PREVIEW ONLY)
Read-only Postgres (shadow v121): latest completed non-fixture run of
`canonical-v1-dev` (fixture run `e5998f6d-93ab-4577-b13a-7b2f89c39c02` excluded),
`analytics.company_scores` + `analytics.factor_scores.raw_value` + primary securities.
Universe size reported as found (directive says 271; actual reported honestly).
Candidate scores computed on the current cross-section with the §3 formulas;
accel/consistency/stability features use the frozen anchor rule over the union of
certified panel rows (≤ 2026-06-30) and the current run's `as_of`, per symbol sorted
by as_of (≤ quarterly spacing enforced by the anchor window rule). Technical/liquidity
features from the certified MarketData path at the latest session ≤ snapshot date.
Output CSV only; nothing written to `analytics.*`; nothing exposed to the production UI.

## 5. Outputs

`score_expansion_research/`: `spec_frozen.json`, `_spec_sha.txt`,
`part2_coverage_feature_by_date.csv`, `part2_coverage_summary.csv`,
`part2_missingness_informativeness.csv`, `scores_by_date.csv`,
`part3_distributions.csv`, `part3_persistence.csv`, `part4_redundancy.csv`,
`part4_score_score.csv`, `part5_ics_per_date.csv`, `part5_ic_summary.csv`,
`part5_qspread.csv`, `part6_incremental_ics_per_date.csv`,
`part6_incremental_summary.csv`, `part6_within_quintile.csv`,
`part6_top20_conditional.csv`, `part7_overlays.json`, `part8_capacity.csv`,
`part8_current_capacity.csv`, `part9_technical.json`, `part10_regimes.csv`,
`part10_concentration.csv`, `part11_score_card.csv`, `part13_snapshot.csv`,
`FINAL_REPORT.md`.

## 6. Prohibited during execution

No re-running with adjusted rules after seeing results; no feature additions; no
weight/threshold tuning; no deletion of unfavorable artifacts. Failures are reported
in `FINAL_REPORT.md` exactly as encountered.
