# SCORE EXPANSION RESEARCH — FINAL REPORT

**Label: HISTORICAL EVIDENCE SYNTHESIS** — there is no untouched historical holdout
left. Every forward-return statistic in this report is descriptive historical evidence
on an already-analyzed panel. Nothing here is NEW VALIDATION, nothing is promoted,
and nothing was written to production or the live shadow.

- Frozen preregistration: `PREREGISTRATION_SCORE_EXPANSION_V1.md`
  SHA-256 `39c43e21de02596760c77789ef2f77fc84e282ad0d7ef8e38036e749c4e017c5`
- Frozen machine spec: `spec_frozen.json`
  SHA-256 `0ec9a4f470bd8f3cb69a9116405265e0561fc8f4c56f8f6d89a50fa64bde1b58`
- Both hashed before any forward-return diagnostic was computed; execution ran once
  against the certified panel (`pit_feature_panel.parquet`, SHA-verified;
  base PIT panel + JSONL, daily panel, portfolio engine all SHA-verified via
  `v2lib.verify_frozen_shas()`; PIT contract `SCORE_V2_PIT_FEATURE_CONTRACT = PASS`).
- Sanity anchors reproduced exactly: V1 standalone ICs (0.0574/0.0853/0.1096/0.1031
  at 21/63/126/252) match the frozen reference; V1 Top-20% portfolio
  CAGR 0.3979, MDD −0.2685, turnover 0.293 match the frozen portfolio record.

## Execution notes and deviations (honest disclosure)

1. The single analysis pass (`run_score_expansion.py`) failed three times on purely
   mechanical code bugs before completing (a None in a sanity print, an import-order
   error, a dict-attribute typo in the summary block). The frozen analysis logic was
   never changed; each rerun was a deterministic recomputation of the same spec, and
   no result was consumed from a failed pass. The one completed pass exited 0.
2. The Part 13 snapshot script had a column-alias bug that initially produced
   empty FM/EQ scores; it was fixed before any snapshot number was read or reported.
3. Postgres access was SELECT-only (latest production run + factor raw values).
   No `analytics.*` table was written; no production/shadow/engine file was modified;
   no SQL Server was used; no broker, no orders. New artifacts exist only in
   `score_expansion_research/`. (Pre-existing dirty files — `.gitignore`, go-app logs,
   integration-shadow output — predate this study; no git command was run here.)
4. **Data observation (flagged, unresolved):** the market raw files show a large
   missed-session spike at 2026-05-31 (mean 1−td60 = 0.86) and 2026-06-30 (0.57)
   vs ~0.03–0.05 in late 2025. This is either a real market-halt period or a backfill
   artifact in the raw TSETMC files. It affects LQ/TC levels at those dates; the L1/L2
   cross-sectional guards are rank-based and did not spike. Flagged for data owners.

## Part 2 — PIT & coverage audit (artifacts: part2_*.csv)

- All candidate inputs pass the leak check: they are either certified PIT panel
  columns (proven `visible_from ≤ knowledge_cutoff`) or computed from sessions ≤ T
  only (chain-invariant ratios / raw traded value). No silent backfill; shares
  `knowledge_from` rule untouched.
- Coverage is the study's dominant constraint:
  - **TC and LQ: ~98.7%** of panel rows (market features; min date-coverage 92.4%).
  - **FM: 33.5% of rows** (4,218/12,604). `revenue_growth` (5%), `opg` (7%),
    `margin_trend` (4%) are the rare inputs; `npg` 92%, `sg12` 56%. The accel /
    consistency features need an anchor row 70–100d back and are structurally absent
    at panel dates whose prior row falls outside the window (0% at 2026-06-30).
  - **EQ: 3.9% of rows (496/12,604)** — `cash_conversion`, `earnings_quality`,
    `interest_coverage`, `debt_ratio`, `current_ratio` are each present on only
    ~500 rows of the PIT rebuild (unprovable historical publication dates are
    INVISIBLE by the accepted PIT contract). This is a declared, reported limitation,
    not a bug.
- **Missingness is potentially informative:** rows with `sales_growth_12m` missing
  have median ret_63 IC of the missing-indicator = −0.087 (25.6% positive dates);
  `sales_stability` missing = −0.062. Missing fundamentals are NOT random — they mark
  weaker names — so renormalized scores are partly a data-availability signal.
- Neutral/default-fill: none inside candidate scores (renormalization only); its
  effect is the implicit up-weighting quantified in the effective-contribution table.

## Part 3 — construction & distribution (part3_*.csv, scores_by_date.csv)

All four scores are 0–100 percentile-scale (mean of present feature percentiles,
min-feats gate). Month-to-month rank persistence (median): FM 0.83, EQ 0.95,
LQ 0.78, TC 0.67, V1 0.93. TC is the fastest-moving (as expected for trend
information); EQ is the slowest.

## Part 4 — redundancy / orthogonality (part4_*.csv)

Median cross-sectional Spearman vs V1 (`ui_score`) and components:

| Score | vs V1 | vs Growth | vs Profit | vs Valuation | vs Market | Top-10% overlap | Top-20% overlap |
|---|---|---|---|---|---|---|---|
| FM | **0.72** | 0.79 | 0.16 | 0.09 | 0.01 | 31% | 49% |
| EQ | 0.33 | 0.18 | **0.70** | 0.08 | 0.56 | 33% | 31% |
| LQ | **−0.03** | −0.04 | 0.02 | −0.02 | 0.01 | 9% | 19% |
| TC | **0.18** | 0.11 | −0.00 | −0.01 | 0.43 | 15% | 27% |

- **FM is redundant with V1** (ρ 0.72 overall, 0.79 with the Growth block) — 5 of its
  9 features ARE V1's growth block. ORTHOGONAL_INFORMATION = LOW.
- **EQ duplicates V1's Profitability block** (ρ 0.70) more than it complements V1
  overall. ORTHOGONAL = MEDIUM.
- **LQ is fully orthogonal** to V1 and every component. ORTHOGONAL = HIGH.
- **TC is near-orthogonal to V1 as a whole** (0.18) but ρ 0.43 with the Market/Risk
  component and **ρ 0.77 with V1's MomentumRank** — TC is essentially a momentum/trend
  bundle; it looks incremental against V1 partly because Momentum carries only 1/89 of
  V1's weight. Within TC, `mom60 ~ vam60` median ρ = 0.94: the 8 features are ~4
  distinct clusters, not 8 signals. ORTHOGONAL = HIGH (with the momentum caveat).

## Part 5 — standalone diagnostics (part5_*.csv) — HISTORICAL EVIDENCE ONLY

Mean IC (median in parentheses), block-3 bootstrap 95% CI, positive-date fraction:

| Score | IC21 | IC63 | IC126 | IC252 |
|---|---|---|---|---|
| FM | 0.093 (0.126) CI [0.039, 0.146] | 0.075 (0.142) CI [−0.012, 0.155] | 0.076 (0.124) CI [−0.016, 0.149] | 0.007 (0.045) CI [−0.088, 0.097] |
| EQ | 0.011 (0.033) CI crosses 0 | 0.023 (0.012) CI crosses 0 | 0.015 (0.017) CI crosses 0 | 0.089 (0.100) CI crosses 0 |
| LQ | 0.010 CI crosses 0 | 0.026 CI crosses 0 | 0.022 CI crosses 0 | **−0.035** (pos 27%) |
| TC | 0.028 CI crosses 0 | **0.074 CI [0.022, 0.131]** | **0.112 CI [0.057, 0.171]** | **0.126 CI [0.057, 0.193]** |

Q5−Q1 (h=63): FM +3.5%/quarter; TC +2.1% with fully monotonic quintiles (4/4 steps);
LQ +0.7% (flat); EQ **−29%** (inverted, but on ~10 names/date — not interpretable).

## Part 6 — incremental information vs V1 (part6_*.csv) — headline test

Incremental (partial-rank residual) IC, median (CI):

| Score | INC-IC21 | INC-IC63 | INC-IC126 | INC-IC252 |
|---|---|---|---|---|
| FM | 0.072 CI [0.018, 0.115] | 0.073 CI [−0.057, 0.098] | 0.055 CI [−0.036, 0.082] | 0.030 CI crosses 0 |
| EQ | ~0 everywhere | ~0 | ~0 | 0.095 CI crosses 0 |
| LQ | −0.000 | 0.017 CI crosses 0 | 0.008 CI crosses 0 | −0.065 |
| TC | 0.055 CI crosses 0 | **0.057 CI [0.009, 0.111]** | **0.095 CI [0.042, 0.147]** | **0.132 CI [0.043, 0.174]** |

Within-V1-quintile (median IC63): TC positive in 4/5 quintiles (Q1 0.036, Q2 0.118,
Q3 0.060, Q4 −0.0005, Q5 0.154). FM positive in 5/5 but low n. LQ positive only in the
BOTTOM two V1 quintiles (0.054/0.061) and negative in top quintiles — liquidity adds
nothing where V1 is already selective.

Inside frozen V1 Top-20%: TC high-vs-low = **+2.9%/quarter (CI [0.001, 0.057])** and
**+6.3%/half-year (CI [0.028, 0.102])**; within-top20 IC 0.165/0.151.
FM high-vs-low = +3.8%/quarter (CI [0.012, 0.065]) — but on only 36 of 63 dates
(coverage). LQ high-vs-low = −2.5%/quarter (CI crosses 0) — mild preference for the
less-liquid tail, except the very-illiquid bottom tertile which is toxic (Part 7).

Classification (frozen rules): TC = **YES**; FM = **INCONCLUSIVE** (defined on 33.5%
< 50% of V1 rows; its partial evidence is directionally positive); EQ = **INCONCLUSIVE
/ INSUFFICIENT** (3.9% coverage; top-20 conditional had zero usable dates); LQ =
**WEAK** (positive small medians, no CI excludes 0).

## Part 7 — fixed descriptive overlays inside V1 Top-20% (part7_overlays.json)

BASE cost (50 bps), bench = frozen V1 Top-20% (CAGR 39.8%):

- **FM:** upper half CAGR +79.4% (excess +0.83%/mo, CI [−0.009, +0.024]); lower half
  CAGR +35.6% (**excess −1.60%/mo, CI [−0.035, −0.002]** — significantly negative).
  Asymmetry: FM's bottom half inside V1 Top-20% is what to avoid; its top half helps
  but not significantly. Turnover rises 0.29 → 0.55/0.71.
- **TC:** upper half ≈ bench (+0.02%/mo); lower half −0.35%/mo (CI crosses 0); bottom
  tertile −1.04%/mo (CI crosses 0). Direction consistent with Part 6 but the overlay
  edge does not survive 50 bps costs as significant; turnover 0.29 → 0.63.
- **LQ:** both halves below bench; bottom (most illiquid) tertile −1.64%/mo
  (**CI [−0.023, −0.010]** — the only significant overlay result for LQ): the
  illiquid tail inside V1 Top-20% is a real drag. Chasing the most liquid names adds
  nothing (−0.96%/mo, CI crosses 0).
- **EQ:** inverted on tiny coverage; not interpretable.

No strategy is promoted; these are diagnostic splits only.

## Part 8 — liquidity special test (part8_capacity*.csv)

Historical V1 Top-20% (median across 63 dates): missed-session rate 5.3%; 11%/11%/2%
of names fail L1/L2/L3; capacity ratio at 1B toman: median 0.65% (comfortable), at
10B toman: median 6.5% with **63% of names above the 5% threshold** — a 10B toman
program is NOT cleanly implementable in V1 Top-20%; 1B is (98% of dates < 5%).
Current snapshot (54 names): median cap@1B 0.05%, but one name
(`جم پیلن3`) at **17% of 30d traded value at 1B toman** — exactly the implementation
risk V1 (LiquidityRank weight 3/89) does not surface. **Answer: YES — LQ exposes
implementability information V1 does not; it is not alpha (IC≈0, negative at 252d).**

## Part 9 — technical special test (part9_technical.json)

Redundancy vs V1 is LOW (0.18) so the frozen verdict rule does NOT return NO — but the
explicit momentum test shows **ρ(TC, V1 MomentumRank) = 0.77** and internal
`mom60~vam60` ρ = 0.94. Honest reading: TC's incremental value is a momentum/trend
extension that V1 currently underweights, not a new information family; its 8
features carry ~4 distinct clusters. TECHNICAL_CONFIRMATION_VALUE per frozen rule:
**not NO** (redundancy LOW and incremental YES), with the momentum-overlap caveat
recorded and the effective cluster count ~4.

## Part 10 — regime stability (part10_regimes.csv)

Median IC63 by era (E1 2021-22 / E2 2023-24 / E3 2025-26):

| Score | E1 | E2 | E3 | Frozen class |
|---|---|---|---|---|
| FM | **−0.300** | +0.139 | +0.148 | REGIME_DEPENDENT (sign flip in 2021-22) |
| EQ | −0.048 | +0.060 | +0.132 | REGIME_DEPENDENT (coverage-limited) |
| LQ | −0.005 | +0.056 | −0.036 | REGIME_DEPENDENT (≈ noise everywhere) |
| TC | +0.030 | +0.130 | +0.075 | REGIME_DEPENDENT (positive in ALL eras, magnitude varies; excluding the 3 strongest IC dates mean is still +0.058; top-3 dates = 17% of positive IC sum) |

No score passes the strict BROADLY_STABLE rule (max/min ≤ 3). The decisive contrast:
TC never flips sign across eras; FM flips hard negative in 2021-22.

## Part 11 — score card (part11_score_card.csv)

| SCORE_NAME | PIT | COVERAGE | STANDALONE | INCREMENTAL | REDUNDANCY | REGIME | IMPL. VALUE | RESEARCH VALUE | STATUS |
|---|---|---|---|---|---|---|---|---|---|
| FUNDAMENTAL_MOMENTUM_SCORE | YES | LOW (33%) | MEDIUM | INCONCLUSIVE | HIGH | REGIME-DEP | n/a | LOW | C |
| EARNINGS_QUALITY_RESILIENCE_SCORE | YES | LOW (3.9%) | MEDIUM | INCONCLUSIVE | LOW | REGIME-DEP | n/a | LOW | D |
| LIQUIDITY_CAPACITY_SCORE | YES | ADEQUATE (98.5%) | MEDIUM | WEAK | LOW | REGIME-DEP | **HIGH** | MEDIUM | B |
| TECHNICAL_CONFIRMATION_SCORE | YES | ADEQUATE (98.5%) | HIGH | **YES** | LOW | REGIME-DEP* | n/a | HIGH | A |

*TC: positive in all three eras but weaker in 2021-22; momentum-overlap caveat applies.

## Part 12 — promotion (binding)

PRODUCTION_CHANGED = NO. SHADOW_CHANGED = NO. NEW_PRODUCTION_SCORE = NO. Nothing is
promoted. Because no untouched holdout remains, historical evidence alone cannot
justify production promotion for ANY candidate.

- **FUTURE_PROSPECTIVE_RESEARCH_CANDIDATE = YES** for TECHNICAL_CONFIRMATION_SCORE
  only: PIT-safe, 98.5% coverage, non-redundant with V1, incremental IC63/126/252
  bootstrap CIs exclude 0, positive in all three regimes, economically interpretable
  (trend confirmation V1 underweights). Caveats recorded: momentum-cluster overlap
  (ρ 0.77 with V1 Momentum), effective cluster count ~4, weak 2021-22 era, and the
  overlay edge not surviving 50 bps costs. Prospective (forward) testing would be the
  first genuinely fresh evidence it can ever get.
- LQ is a future **implementation** candidate (status B), not alpha research.
- FM: recoverable only if revenue/op-growth/margin-trend PIT coverage is repaired;
  rerun of the same frozen spec would then be possible. EQ: abandoned as
  historically untestable (3.9%); the current 99-name coverage shows what a repaired
  OCF/balance-sheet backfill could enable, but no historical claim is made.

## Part 13 — current 271-name snapshot (RESEARCH PREVIEW ONLY)

Source: latest completed production run `0d2e5bc7-fde1-4af3-87fa-f292376beb79`,
as_of 2026-10-01, exactly **271** companies (read-only SELECT; nothing written;
not exposed to any UI). Market features at session 2026-10-05 via the certified chain.
Defined: LQ 269/271, TC 269/271, FM 165/271, EQ 99/271 — `part13_snapshot.csv` carries
symbol, quant_score, all four candidate scores, n_avail counts, market_ok and
n_history_rows flags. Top of the current table by quant_score: کیمیا 68.6,
شسپا 67.2, غاذر 66.0, کاما 65.9, سباقر 62.9 — e.g. کیمیا: FM 84.0, EQ 47.8, LQ 45.2,
TC 80.2. These numbers are a research preview and will differ from any future
production definition.

## Part 14 — required answers

1. **Most incremental information beyond V1:** TECHNICAL_CONFIRMATION_SCORE — the
   only candidate whose incremental IC63/126/252 bootstrap CIs exclude zero and which
   separates future returns inside V1's own Top-20% (+2.9%/quarter, CI excludes 0).
   With the caveat that its information is a momentum/trend cluster V1 underweights.
2. **Most useful operationally without alpha:** LIQUIDITY_CAPACITY_SCORE — orthogonal
   to V1, exposes per-name capacity (one current Top-20% name at 17% of ADV at 1B
   toman) and the illiquid-tail drag (−1.64%/mo, CI excludes 0).
3. **Does Technical Confirmation add anything after V1, or is it redundant?** It adds
   measurable after-V1 information (not redundant with the composite), but it is
   internally concentrated (mom60~vam60 ρ 0.94) and 77%-correlated with V1's momentum
   factor — it is best understood as "momentum deserves more weight", pending
   prospective testing. Per the frozen rule it is not classified NO.
4. **Does Fundamental Momentum add beyond V1's Growth block?** Not demonstrably:
   ρ 0.79 with Growth, redundancy HIGH, sign-flip regime in 2021-22, and its
   incremental CIs cross zero at 63/126d. Its acceleration/consistency features could
   not be fairly tested at 33% coverage — INCONCLUSIVE, not NO-by-evidence.
5. **Does Earnings Quality/Resilience identify risks V1 misses?** Cannot be
   determined historically: 3.9% coverage. Its Q5−Q1 was inverted (−29%) and its
   overlay inverted too, which on ~10 names/date is as consistent with "junk risk
   warning" as with noise. INSUFFICIENT_DATA; no claim either way.
6. **Is Liquidity/Capacity useful enough for a future user-facing score?** Yes as an
   implementation/capacity view (status B): capacity ratios, missed-session flags and
   L1/L2/L3 guards are decision-relevant for position sizing. It must NOT be sold as
   a predictor (IC≈0; negative at 252d).
7. **Which scores should be abandoned?** EQ as a historical research family (data
   does not exist PIT-safely; revisit only after an OCF/balance-sheet backfill with
   proven visibility). FM in its current 9-feature form (redundant with Growth; regime
   sign-flip); a leaner accel/consistency-only variant could be re-preregistered once
   coverage is repaired.
8. **Is ANY candidate strong enough to justify prospective research?** Yes — one:
   TECHNICAL_CONFIRMATION_SCORE, under the Part 12 caveats (momentum overlap, ~4
   effective clusters, weak 2021-22 era, cost sensitivity). Everything else: NO.

## FINAL REQUIRED STATUS BLOCK

```
SCORE_EXPANSION_RESEARCH_ONLY = YES

V1_PRODUCTION_UNCHANGED = YES
SHADOW_V1_1_UNCHANGED = YES

NEW_PRODUCTION_SCORE_CREATED = NO
NEW_MODEL_PROMOTED = NO
WEIGHTS_OPTIMIZED = NO
THRESHOLDS_OPTIMIZED = NO

FUNDAMENTAL_MOMENTUM_RESEARCH_VALUE = LOW
EARNINGS_QUALITY_RESILIENCE_RESEARCH_VALUE = INCONCLUSIVE
LIQUIDITY_CAPACITY_RESEARCH_VALUE = MEDIUM
TECHNICAL_CONFIRMATION_RESEARCH_VALUE = HIGH

BEST_INCREMENTAL_SCORE = TECHNICAL_CONFIRMATION_SCORE
BEST_IMPLEMENTATION_SCORE = LIQUIDITY_CAPACITY_SCORE

ANY_FUTURE_PROSPECTIVE_RESEARCH_CANDIDATE = YES   (TECHNICAL_CONFIRMATION_SCORE only)

PRODUCTION_CHANGED = NO
LIVE_SHADOW_CHANGED = NO
BROKER_CONNECTED = NO
REAL_MONEY_ORDERS = NO
SQL_SERVER_USED = NO
```

STOP. Research artifacts delivered in `score_expansion_research/`. No further action
taken or implied.
