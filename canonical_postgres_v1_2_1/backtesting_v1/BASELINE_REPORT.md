# Baseline Report — Canonical v1 (untuned, Phase 1)

Run: `score_version = canonical-v1-dev`, `implementation_revision = report-chain-ttm-v1`.
This is a **measurement** baseline, not model selection. Nothing was changed after
inspecting results.

## Chosen conventions

| item | value | why supported |
| --- | --- | --- |
| historical range | 2021-01-31 → 2026-06-30 | fundamentals begin 2019-04; monthly 2020-01; ~1y warm-up for TTM |
| rebalance | monthly (last trading day), 66 dates | simple baseline |
| signal | analytics as-of `T` | canonical PIT |
| execution | next trading day close | avoids same-close look-ahead |
| return | raw price return | `corporate_actions` empty (see audit) |
| portfolio | equal-weight top-20 | minimal assumptions |
| benchmark | equal-weight tradable universe | same PIT schedule |
| costs | illustrative 10 bps/side | clearly not historically exact |

## Usable data / universe behavior

* 66 rebalance dates; **13,303** signal observations.
* Eligible universe: 243 → 267 (mean 261.3). Tradable (has execution price):
  mean 201.6, min 0 (one date with no eligible execution prices), max 230.
* Universe churn: 1,015 additions / 804 removals across dates — **no static
  universe, no survivorship**.

## PIT test results

All anti-look-ahead tests pass: future report, future correction, future price
(`trade_date` mode), report-chain missing-leg safety, signal/execution separation,
no static universe. Market-PIT limitation documented: canonical `collected_at` is
migration time, so historical market reconstruction uses `trade_date <= T`.

## Return convention / corporate actions

**Raw price return** (`closing_price_rial`). `market.corporate_actions` has 0 rows,
so adjusted/total returns are **not** produced and are **not** implied. See
`CORPORATE_ACTION_AUDIT.md`.

## QuantScore IC (primary horizon = 21 trading days)

| stat | value |
| --- | --- |
| mean IC | **0.1088** |
| median IC | 0.0949 |
| IC std | 0.1334 |
| IC hit rate | 79.0% |
| periods | 62 |

Quantile (5 buckets): mean top-minus-bottom spread **0.0273** (2.73% per 21d),
hit rate 75.8%.

## Portfolio baseline (monthly, gross)

| metric | portfolio | benchmark |
| --- | --- | --- |
| cumulative return | **7.21 (721%)** | 2.50 (250%) |
| annualized return | 51.3% | 27.9% |
| volatility | 10.1% | 9.8% |
| max drawdown | −23.2% | −31.1% |
| Sharpe-like (×√12) | 1.36 | 0.89 |
| hit rate | 63.9% | 50.8% |

Cost-adjusted (10 bps/side, mean turnover 0.306): cumulative **6.91 (691%)**,
annualized 50.2%, Sharpe 1.34. Reported separately from gross; cost figure is
illustrative.

Turnover: mean **0.306** per rebalance (entered/exited counts in `turnover.csv`).

## Time-segment robustness (IC by year)

2021 0.067 · 2022 0.044 · 2023 0.038 · 2024 0.196 · 2025 0.166 · 2026 0.308 (n=2).
Positive in every year; stronger recently. Not uniform — read with coverage bias.

## Factor diagnostics (mean 21d IC, selected)

Positive: PE 0.120, SalesGrowth 0.085, SalesGrowth3M 0.075, LowVolatility 0.043,
RevenueGrowth 0.025, ROE 0.022. Near-zero/negative: Momentum 0.001, InterestCoverage
−0.000, MarginTrend −0.001, PS/PB −0.001, OperatingMargin −0.009, Leverage −0.015,
CurrentRatio −0.017. Full table: `factor_diagnostics.csv`.

## Missingness bias findings (first-class)

* `pearson(QuantScore, n_factors_available) = 0.581` — score is **correlated with
  factor coverage**.
* Forward returns rise with coverage: low ≤7 → 3.19%, medium 8–14 → 4.25%,
  high ≥15 → 5.28%.
* ⇒ part of the apparent score/return association may be coverage-driven. The
  neutral-percentile policy was **not** changed. See `MISSINGNESS_DIAGNOSTICS.md`.

## Data-quality context (signal observations)

`missing_comparable_period` 12,521 · `missing_monthly_activity` 4,422 ·
`missing_current_financials` 178 · `missing_price` 1 · `REPORT_CHAIN_TTM` 8,630.

## Reproducibility

Two identical full runs produced the same `summary_hash =
4a628e7d730ccb090bc8b04a7558086bc50ef62e213837cd2556c85d48bbad29`.
Signal/forward/portfolio hashes in `summary_metrics.json`.

## Tests

`backtesting_v1/tests` (11) + `analytics_canonical_v1/tests` (18) +
`analytics_v37_oracle` (3) all green. Oracle golden hash unchanged
(`849a4efd…ca5c7c`). No production/legacy/oracle input; no `score_runs` writes.

## Framework gate

# BACKTEST_FRAMEWORK_READY

PIT-safe snapshots proven; no survivorship leakage; signal/return separation
correct; market-return limitations documented; model frozen/reproducible;
missingness diagnostics present; baseline reproducible; no production/legacy
dependency introduced. This does **not** mean the model is predictive or
profitable.

## Data blockers

None blocking the framework. Known limitation: corporate-action coverage absent →
raw price returns only; market PIT uses `trade_date` proxy (documented).

## Recommended next single action

**Phase 2 — measurement hardening and coverage-bias control** (still no weight
tuning): add corporate-action-aware total-return reconstruction where canonical
data permits, and evaluate score/return association restricted to comparable
factor-coverage strata before any factor optimization is considered.
