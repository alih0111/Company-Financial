# Factor Validation Report (Phase 3)

VALIDATION ONLY. canonical-v1 is the frozen control; no weights, directions,
formulas, or missing-data rules changed; no production/Go/Python changes; no
overwriting of runs. All multivariate/decomposition outputs are
`DIAGNOSTIC_ONLY_NOT_MODEL`.

Control model: `canonical-v1-dev` + `report-chain-ttm-v1`. PIT infra: the validated
Phase-2 backtester (dynamic universe, `trade_date` market proxy, raw-price returns,
coverage diagnostics). 13,303 signals across 66 monthly rebalances (2021-01-31 …
2026-06-30). Reproducibility: identical summary hash across two runs
(`9039b5694a09da4646b2b816c134056032d4e63c72b97a4b3700084abbeb9f6e`).

## Evidence classification (pre-declared rules)

Counts: **ROBUST_SIGNAL 4 · WEAK_BUT_CONSISTENT 2 · COVERAGE_CONFOUNDED 0 ·
TIME_UNSTABLE 2 · DIRECTION_UNSTABLE 3 · INSUFFICIENT_DATA 9 · NO_MEASURABLE_SIGNAL 1**.

| factor | cat | w | cov% | raw IC | ctrl IC | 2021–23 | 2024–25 | 5/21/63d | class | dir |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SalesGrowthRank | growth | 10 | 45.8 | 0.085 | 0.100 | 0.05 | 0.13 | + | **ROBUST** | ok |
| RevenueGrowthRank | growth | 5 | 6.2 | 0.025 | 0.070 | – | – | + | **ROBUST** | ok |
| PERank | valuation | 11 | 97.7 | 0.120 | 0.112 | 0.10 | 0.15 | + | **ROBUST** | ok |
| LowVolatilityRank | market | 2 | 100 | 0.043 | 0.036 | – | – | + | **ROBUST** | ok |
| SalesGrowth3MRank | growth | 6 | 64.2 | 0.075 | 0.021 | – | – | + | WEAK_BUT_CONSISTENT | ok |
| EarningsQualityRank | profitability | 4 | 6.4 | 0.014 | 0.023 | – | – | + | WEAK_BUT_CONSISTENT | ok |
| MarginTrendRank | profitability | 3 | 5.9 | −0.000 | −0.011 | – | – | – | TIME_UNSTABLE | ok |
| InterestCoverageRank | profitability | 3 | 6.1 | −0.000 | 0.018 | – | – | – | TIME_UNSTABLE | ok |
| OperatingProfitGrowthRank | growth | 5 | 79.7 | 0.014 | −0.028 | – | – | – | DIRECTION_UNSTABLE | **REVIEW** |
| StabilityRank | market | 1 | 59.3 | 0.018 | −0.027 | – | – | – | DIRECTION_UNSTABLE | **REVIEW** |
| MomentumRank | market | 1 | 99.7 | 0.000 | −0.026 | – | – | – | DIRECTION_UNSTABLE | **REVIEW** |
| NetProfitGrowthRank | growth | 10 | 3.9 | 0.018 | 0.200 | – | – | – | INSUFFICIENT_DATA | ok |
| NetMarginRank | profitability | 4 | 4.5 | 0.013 | 0.039 | – | – | – | INSUFFICIENT_DATA | ok |
| ROERank | profitability | 6 | 4.5 | 0.022 | 0.124 | – | – | – | INSUFFICIENT_DATA | ok |
| PSRank | valuation | 3 | 4.5 | −0.001 | 0.048 | – | – | – | INSUFFICIENT_DATA | ok |
| PBRank | valuation | 2 | 4.5 | −0.001 | 0.051 | – | – | – | INSUFFICIENT_DATA | ok |
| LeverageRank | market | 2 | 4.6 | −0.015 | −0.065 | – | – | – | INSUFFICIENT_DATA | **REVIEW** |
| CurrentRatioRank | market | 2 | 4.6 | −0.016 | −0.090 | – | – | – | INSUFFICIENT_DATA | **REVIEW** |
| CashConversionRank | profitability | 2 | 4.5 | −0.006 | −0.041 | – | – | – | INSUFFICIENT_DATA | **REVIEW** |
| LiquidityRank | market | 3 | 0.0 | – | – | – | – | – | INSUFFICIENT_DATA | ok |
| OperatingMarginRank | profitability | 4 | 5.9 | −0.009 | 0.041 | – | – | – | NO_MEASURABLE_SIGNAL | ok |

`coverage` = % of signals with the underlying fact. `CI` and monotonicity trends
are in `factor_validation.csv`.

## Directional correctness

Ranks are higher-better by construction (expected direction `+`). Observed raw and
coverage-controlled directions agree for 15/21. `DIRECTION_REVIEW_REQUIRED`:
**OperatingProfitGrowth, Stability, Momentum, Leverage, CurrentRatio,
CashConversion** (controlled IC ≤ −0.02 or ≤ −0.04). Nothing was flipped.

## Missingness sensitivity

For most low-coverage factors, `mean_ret_present` ≈ `mean_ret_absent`; the apparent
IC comes from ranking *within* the present set, not from presence/absence. Presence
alone is **not** treated as predictive.

## Incremental value (per-date multivariate rank regression)

Top mean incremental coefficients (DIAGNOSTIC_ONLY_NOT_MODEL): PBRank 0.161,
NetMargin 0.128, MarginTrend 0.125, EarningsQuality 0.078, ROE 0.050, PE 0.031.
The largest coefficients belong to low-coverage factors → treat as **unreliable**
(small cross-section). High-coverage contributors remain PE and Sales growth.

## Redundancy (rank correlations)

Highly redundant pairs: **PS↔PB 0.84**, **Leverage↔CurrentRatio 0.79**,
**PE↔PS 0.73**, **SalesGrowth↔RevenueGrowth 0.70**, PE↔PB 0.65,
NetMargin↔PS −0.63, OperatingMargin↔InterestCoverage 0.57. High correlation is not
automatically bad but flags overlapping information (two valuation, two leverage,
two sales-growth factors).

## Leave-one-factor-out (diagnostic QuantScore, DIAGNOSTIC_ONLY_NOT_MODEL)

Baseline diagnostic IC 0.1098 (≈ canonical QuantScore IC 0.1088). Dropping a factor
*reduces* IC only for: **PE (−0.0320)**, **SalesGrowth3M (−0.0064)**,
**SalesGrowth (−0.0044)**, **LowVolatility (−0.0020)**. Dropping any other factor
slightly *increases* diagnostic IC (i.e., no measurable incremental contribution at
current coverage). `Liquidity` drop = 0.0 (neutral historically).

## Weight/evidence consistency (`weight_evidence.csv`)

* SUPPORTED: SalesGrowth, SalesGrowth3M, RevenueGrowth, EarningsQuality, PE.
* **OVERWEIGHTED_RELATIVE_TO_EVIDENCE:** NetProfitGrowth (w10, insufficient),
  ROE (w6, insufficient).
* **UNDERWEIGHTED_RELATIVE_TO_EVIDENCE:** LowVolatility (w2, robust).
* INSUFFICIENT_EVIDENCE: the remaining 14.

No weight was changed.

## Statistical discipline

CIs are block bootstraps over rebalance dates (≈62 dates, not 13k rows). With 21
factors, nominal 95% CIs imply ~1 false positive expected; only factors whose CI
excludes 0, are coverage-consistent, and time-consistent are called ROBUST
(4 factors), so multiple-testing risk is contained.

## Conclusion

Evidence is **partially supportive**: 4 robust factors (PE, SalesGrowth,
RevenueGrowth, LowVolatility) plus 2 weak-but-consistent. A large block (9) cannot be
validated historically because underlying profitability/balance-sheet coverage is
~4.5%. Three factors show direction instability and warrant review (not in-place
flips). Full table: `FACTOR_DECISION_TABLE.csv`; summary: `output/phase3_summary.json`.
