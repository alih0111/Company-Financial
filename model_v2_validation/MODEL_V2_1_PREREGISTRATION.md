# MODEL_V2_1_ROBUST_SET — PRE-REGISTRATION (frozen before Holdout/Forward read)

Status: **FROZEN 2026-10-01, before any Holdout-2025 / Forward-2026 evaluation of
these candidates.** exp-a/exp-b/exp-c are untouched.

## Motivation (from MODEL_V2_REBASELINE.json)

The historical-data blocker is closed. After the net-profit backfill:
`NetProfitGrowthRank` moved INSUFFICIENT_DATA (cov 3.9 %) → **ROBUST_SIGNAL**
(cov 82.4 %, controlled IC 0.135). Hypothesis:

> A model composed **only** of currently ROBUST_SIGNAL factors — including the
> newly validated NetProfitGrowthRank — improves signal quality without relying
> on time-unstable, coverage-confounded, no-signal or insufficient-data factors.

## Robust factor set (taken from the current FACTOR_DECISION_TABLE.csv)

| factor | controlled_ic | coverage |
|---|---|---|
| PERank | 0.0991 | 98.3 % |
| NetProfitGrowthRank | 0.1349 | 82.4 % |
| SalesGrowthRank | 0.0961 | 45.2 % |
| SalesGrowth3MRank | 0.0849 | 63.4 % |
| RevenueGrowthRank | 0.0424 | 6.1 % |
| LowVolatilityRank | 0.0391 | 100.0 % |

Explicitly EXCLUDED: TIME_UNSTABLE (4), COVERAGE_CONFOUNDED (2),
NO_MEASURABLE_SIGNAL (3), INSUFFICIENT_DATA (6) — notably EarningsQualityRank,
StabilityRank, MomentumRank, OperatingProfitGrowthRank, PSRank, NetMarginRank.

## Candidates (3 + 1 ablation; no grid search)

1. **canonical-v2.1-a (equal-weight robust)** — the 6 robust factors, weight 1/6 each.
2. **canonical-v2.1-b (Dev-stat weights)** — weights ∝ `max(0, Dev(2021–2023) IC21 mean)`
   of each factor, normalized to sum 1, computed ONLY from Development rows;
   factors with Dev IC21 ≤ 0 receive weight 0. Deterministic; no Validation/Holdout input.
3. **canonical-v2.1-c (coverage-neutral)** — v2.1-a score, then a within-date
   residualization on `n_factors_available` using a single β estimated on
   Development rows only (`β = cov_dev(score, n_factors)/var_dev(n_factors)`), applied
   frozen to all periods; ranking uses the residual.
4. **canonical-v2.1-a-NPGX (ablation)** — identical to v2.1-a without
   NetProfitGrowthRank (5 factors, equal weight). For attribution only; not a candidate.

## Frozen parameters (identical to the model-v2 harness; no re-tuning)

- normalization: cross-sectional percentile ranks as stored in the frozen signal
  snapshot (`factor_rank`), higher = better; no direction flips anywhere.
- missing-value policy: **drop_unavailable_renormalize** — a factor contributes
  only when available; weights renormalize over available factors; missing is
  neither imputed, nor forward-filled, nor treated as bad/good; no future data.
- rebalance frequency: harness default (monthly signal dates, 66 dates 2021-01→2026-06).
- primary horizon: 21 trading days; horizons 5/21/63 also reported.
- portfolio: TOP_N = 20 equal-weight; execution at the next trading day after
  signal formation (harness `execution_date`).
- transaction cost assumption: **10 bps per side** (frozen harness value).
- return convention: **raw_price_return** (`market.corporate_actions` is empty —
  see backtesting_v1/CORPORATE_ACTION_AUDIT.md) → absolute-return metrics are
  flagged **RETURN_SERIES_NOT_PROMOTION_GRADE**; IC/factor evidence remains usable.
- periods (unchanged): Dev 2021–2023, Validation 2024, Holdout 2025, Forward 2026.

## Decision rule (frozen, applied on Dev+Validation ONLY, before Holdout is read)

Baseline (`canonical-v1-dev`) Dev/Val metrics are computed and used as reference
(baseline is not a candidate). A candidate is ELIGIBLE iff all hold:

- R1  Dev IC21 mean > baseline Dev IC21 mean, AND Val IC21 mean ≥ baseline Val IC21 mean.
- R2  IC21 positive fraction ≥ 0.75 in BOTH Dev and Val.
- R3  coverage–score correlation ≤ 0.30 in BOTH Dev and Val (materially better than
  the baseline's, which is ~0.50–0.58).
- R4  turnover ≤ 0.65 in BOTH Dev and Val.

Selection: among eligible candidates pick the highest (Dev IC21 + Val IC21) / 2.
If none is eligible → `MODEL_V2_1_VALIDATION_WEAK`.

Only after the selection is persisted is Holdout 2025 evaluated (once), then
Forward 2026 as a separate diagnostic. No post-Holdout re-selection.
