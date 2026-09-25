# Canonical Analytics v1 — Readiness Decision

Score version `canonical-v1-dev` (+ report-chain revision). Canonical-only runtime.
This report separates **correctness**, **data availability**, **scoring
semantics**, **future improvement**, and **backtesting readiness**. It does not
claim predictive quality.

Machine-readable supports: `data_work/readiness_summary.json`,
`data_work/readiness_metrics.csv`, `data_work/factor_availability.csv`,
`data_work/missing_data_contract.md`, `data_work/REPORT_CHAIN_TTM_REPORT.md`.

## 1. Correctness

| check | result |
| --- | --- |
| unit contract (monetary IRR, eps `rial_per_share`, no scale detection) | PASS |
| TTM semantics (direct → report-chain → NULL; no Product1) | PASS (`REPORT_CHAIN_TTM_PASS`) |
| stock metrics not TTM-chained | PASS |
| PIT cutoff (no future report leak) | PASS |
| supersession handling | PASS |
| deterministic output | PASS |
| legacy-free (no Product1/NPUnitRatio/OpK/OpAmt, no SQL Server/legacy-CSV runtime) | PASS |
| migration fidelity (`MIGRATION_NOT_IMPORTED`) | 0 |
| oracle comparison `BUG_SUSPECTED` | 0 |

Conclusion: canonical metrics are semantically correct; no unresolved analytics bug.

## 2. Data availability

* Canonical scored population: **267**.
* Complete factor coverage (all 21): **9** companies; **0** companies have zero factors.
* Median available factors: **8 / 21**; min **4**; max **21**.
* `SOURCE_ABSENT` affects **165 / 267 (61.8%)** companies (monetary/balance-sheet
  facts never populated in legacy for those companies).
* All `missing` are represented as `NULL` + DQ provenance; none are zero-filled.

Accepted historical limitations (genuine source absence, no canonical source):
`SOURCE_ABSENT`, `MISSING_PRIOR_ANNUAL` (7, non-Esfand fiscal years),
`INSUFFICIENT_TTM_PERIODS` (35, optional future re-ingestion).

Intentionally out-of-scope (no remediation): 5 subjects
(`ACCEPTED_CANONICAL_SCOPE_EXCLUSION`) and 4 policy exclusions.

## 3. Scoring semantics

`data_work/missing_data_contract.md`. Every factor is `OPTIONAL_WITH_NULL`; no
factor is `EXCLUDED_IF_MISSING`. Missing factors receive documented neutral
percentiles (`0.30`; `0.50` for InterestCoverage/EarningsQuality; `0.00` for
PE/PS/PB and Liquidity as specified), the percentile denominator uses only
companies with data, and every participating company receives a deterministic
QuantScore. No implicit zero-filling and no legacy fill-ins. **267 / 267 (100%)**
receive a valid deterministic QuantScore.

Factor availability (companies with underlying data):

| availability band | factors |
| --- | --- |
| 100% | Liquidity, LowVolatility |
| 88–99% | OperatingProfitGrowth, Momentum, PE |
| 46–69% | SalesGrowth, SalesGrowth3M, Stability, RevenueGrowth, EarningsQuality, InterestCoverage |
| 37–38% | NetMargin, ROE, OperatingMargin, MarginTrend, Leverage, CurrentRatio, PS, PB, CashConversion |
| 3.7% | NetProfitGrowth |

Category coverage (`any` available factor / `complete`): growth 262/10,
valuation 264/95, market 267/93, profitability 130/87.

## 4. Future improvement (optional)

`OPTIONAL_FUTURE_REINGESTION`: the ~1,579 `SOURCE_ABSENT` rows and the 35
`INSUFFICIENT_TTM_PERIODS` rows could be improved by scoped re-ingestion/re-parse of
original reporting, if/when authorized. Not required for v1 correctness and not a
blocker. Do **not** reconstruct from Product1/EPS×capital.

## 5. Backtesting readiness

Technically ready to enter **point-in-time backtesting** with the frozen
`as_of_date`/`source_cutoff_at` contracts and legacy-free canonical metrics. This
does **not** claim predictive quality; historical sparsity (61.8% companies with
some missing monetary factors) must be represented via the neutral-factor policy
and DQ flags, not hidden.

## 6. Gate

# CANONICAL_V1_METRICS_READY

Criteria met: no unresolved correctness bug · no required recoverable canonical-data
work remaining (report-chain done; identity gaps explicitly accepted) · remaining
missing data explicitly accepted as source limitation · missing-data scoring
deterministic and documented · PIT/unit/reproducibility/DQ/legacy-free contracts
pass. Legacy population parity and complete historical coverage are **not** required.

Supersedes the previous `CANONICAL_V1_NEEDS_DATA_WORK` gate.

## 7. Recommended next major phase

**POINT-IN-TIME BACKTESTING FRAMEWORK** (not started in this task).
