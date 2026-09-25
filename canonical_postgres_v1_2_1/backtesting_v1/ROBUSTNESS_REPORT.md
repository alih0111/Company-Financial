# Robustness Report (Phase 2)

All diagnostics pre-declared; no horizon/N/threshold chosen by performance.

## Horizon robustness (`horizon_diagnostics.csv`)

| horizon (trading days) | mean IC | 95% CI | n |
| --- | --- | --- | --- |
| 5 | 0.0335 | [0.0115, 0.0568] | 63 |
| 21 | 0.1088 | [0.0736, 0.1415] | 62 |
| 63 | 0.1519 | [0.1218, 0.1844] | 60 |

Association is **not** extreme-horizon-specific; it rises with horizon. All three
are reported equally; none is declared the strategy horizon.

## Time robustness (`time_robustness`)

| period | mean IC | n |
| --- | --- | --- |
| 2021 | 0.0666 | 12 |
| 2022 | 0.0445 | 12 |
| 2023 | 0.0377 | 12 |
| 2024 | 0.1964 | 12 |
| 2025 | 0.1655 | 12 |
| 2026 | 0.3083 | 2 — **INSUFFICIENT_PERIOD_COUNT_FOR_YEARLY_INFERENCE** |
| 2021–2023 | 0.0496 | 36 |
| 2024–2025 | 0.1809 | 24 |

Positive in every year; stronger in 2024–2025. The recent increase coincides with
**higher factor coverage** (more companies with profitability/valuation data) —
consistent with the coverage confounder. Market regime cannot be separated from
coverage with the available evidence; not speculated further. 2026 (n=2) is not
treated as robust.

## Concentration (`performance_concentration.csv`)

* 65 intervals, 118 distinct companies traded.
* Top-5 company contributions ≈ 0.484 (of period-sum), top-10 ≈ 0.793 — moderate
  concentration.
* Best 10% of periods account for **41.2%** of positive P&L.
* Largest single interval: 2026-05-31 (+0.366).

Concentration is quantified, not judged; no leave-one-out optimization performed.

## Cost sensitivity (`cost_sensitivity.csv`)

| bps/side | gross cum | net cum | net annualized | net Sharpe-like |
| --- | --- | --- | --- | --- |
| 0 | 7.214 | 7.214 | 47.5% | 1.31 |
| 10 | 7.214 | 6.905 | 46.5% | 1.29 |
| 25 | 7.214 | 6.461 | 44.9% | 1.26 |
| 50 | 7.214 | 5.776 | 42.4% | 1.21 |

Illustrative scenarios only; no Iranian cost estimate is claimed as historically
exact. Mean turnover 0.306/period.

## Statistical inference

Mean IC/spread CIs use a **block bootstrap over rebalance dates** (seed fixed,
1,000 resamples), treating the rebalance-date count (≈62) as the effective sample —
not the ~13k company rows. Reported with every estimate above.

## Horizon/tradability notes

* `trade_value_rial` is populated only in 2026, so the **Liquidity** factor is
  neutral (0.0) historically and its diagnostics are not measurable (`MARKET_PIT_AUDIT.md`).
* `corr(QuantScore, market_score) = 0.294` (market factors partially align with the
  score); not evidence of liquidity compensation.

## Verdict

Results are not driven solely by one horizon, one year, one company, or a few price
jumps, though coverage and 2024–2025 regime/concentration effects are material and
disclosed.
