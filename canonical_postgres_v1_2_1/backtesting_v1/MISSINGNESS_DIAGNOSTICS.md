# Missingness Diagnostics (Phase 1)

Purpose: detect whether score performance is an artifact of factor availability.
The current neutral missing-factor policy is **frozen** and not changed here.

## Factor-coverage distribution (13,303 signal observations)

| n factors available | observations |
| --- | --- |
| 2–4 | 4,866 |
| 5–7 | 7,636 |
| 8–14 | 202 |
| 15–17 | 81 |
| 18–20 | 519 |

Coverage is low because historical monetary facts (`SOURCE_ABSENT`) are sparse and
valuation/profitability factors depend on them. The divide is historical, not by
design.

## Missingness stratification (`coverage_buckets = (7, 14)`)

| bucket | n obs | mean 21d return | hit rate |
| --- | --- | --- | --- |
| low (≤7) | 11,683 | 3.19% | 53.6% |
| medium (8–14) | 181 | 4.25% | 49.7% |
| high (≥15) | 548 | 5.28% | 56.9% |

`pearson(QuantScore, n_factors_available) = 0.581` — **the QuantScore is
correlated with how many factors are available**. This is a first-class finding:
part of the apparent score/return association may reflect factor coverage rather
than the score's cross-sectional content.

## DQ flags across signals

| flag | count |
| --- | --- |
| `missing_comparable_period` | 12,521 |
| `missing_monthly_activity` | 4,422 |
| `missing_current_financials` | 178 |
| `missing_price` | 1 |
| REPORT_CHAIN_TTM provenance | 8,630 |

## Interpretation

* The framework is correctly separated from predictive claims. High coverage
  companies are few and systematically newer/higher-quality-data names.
* Any IC/spread result must be read alongside the coverage-bias diagnostic
  (`missingness_diagnostics.csv`), not in isolation.
* No neutral-percentile or policy change is made in Phase 1; quantifying the effect
  is the deliverable.
