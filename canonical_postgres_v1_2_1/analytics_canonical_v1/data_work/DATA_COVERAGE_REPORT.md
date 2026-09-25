# Canonical Data Coverage Report

Read-only audit (canonical shadow + SQL Server SELECT-only). No Product1
substitution, no scale inference, no writes. Artifacts:
`metric_coverage.csv`, `company_fact_coverage.csv`, `missing_reason_summary.csv`,
`population_reconciliation.csv`.

Audit surface: 267 canonical subjects × 13 required facts = 3,471 checks.

## 1. Missing reason summary

| missing_reason | rows | share |
| --- | --- | --- |
| `SOURCE_ABSENT` | 1,579 | 45.5% |
| `TTM_RECOVERABLE_REPORT_CHAIN` | 137 | 3.9% |
| `INSUFFICIENT_TTM_PERIODS` | 35 | 1.0% |
| `PRESENT` | 1,720 | 49.6% |

`MIGRATION_NOT_IMPORTED = 0`, `METRIC_MAPPING_MISSING = 0`,
`STATEMENT_MAPPING_MISSING = 0`, `PERIOD_MAPPING_ERROR = 0`,
`PIT_FILTER_EXPECTED = 0` (all audited facts are eligible at the cutoff),
`IDENTITY_MAPPING_GAP` = 5 **subjects** (population, not facts).

## 2. Why are `revenue_ttm` / `net_profit_ttm` ≈ 62.9% missing?

Because the legacy source columns are empty for most companies:

| canonical metric | legacy source column | companies with non-null source |
| --- | --- | --- |
| `net_profit` | `miandore2.NetProfitAmount` | 102 / 267 |
| `revenue` | `miandore2.RevenueNew` | 124 / 267 |
| `total_assets`/`current_assets`/`total_liabilities`/`current_liabilities`/`total_equity` | respective columns | 102 / 267 |
| `operating_cash_flow` | `OperatingCashFlow` | 102 / 267 |
| `finance_cost` / `other_non_operating` | `FinanceCostsNew` / `OtherNonOpNew` | 131 / 267 |
| `operating_profit` | `OperatingProfitNew` | 264 / 267 |
| `eps` / `capital` | `Num1_Value1` / `Num2_Value1` | 264 / 267 |

The canonical migration imported **every** non-null source value faithfully
(`canonical companies == source companies` for each column), so missingness
**originates in the legacy source**, not in migration, mapping, parser, period
semantics, or PIT filtering. Historically the legacy `miandore2` table populated
`Product1` (a mixed-scale `EPS × capital` product) for ~267 companies but the
explicit monetary/balance columns only for the ~102–127 companies whose reports
carried them.

`Product1` is **not** used as a substitute (forbidden). `EPS × capital` is not
used (it is the Product1 reconstruction heuristic and the share/capital scale is
mixed).

## 3. Why are balance-sheet metrics similarly sparse?

Identical root cause: `TotalAssets`, `CurrentAssets`, `TotalLiabilities`,
`CurrentLiabilities`, `TotalEquity` are non-null for only 102/267 companies in
legacy `miandore2`. Canonical imported all of them; the rest are `SOURCE_ABSENT`.

## 4. `operating_profit` — a different, recoverable cause

`OperatingProfitNew` exists for 264 companies, but `operating_profit_ttm` is 52.1%
missing because the latest report lacks the within-row prior-year columns
(`OperatingProfitLastYear`, `OperatingProfitFYPrev`). The prior-year **reports**
themselves exist in canonical (`fundamentals.financial_statements`). A TTM derived
by **joining the prior reports** (current + prior fiscal-year report −
prior-year-same-period report, all p1 facts) is a legitimate canonical derivation.
Measured: **137** company-metric rows are recoverable this way
(`TTM_RECOVERABLE_REPORT_CHAIN`), 136 of them `operating_profit`.
Remediation class **B** (re-derive from legitimate canonical fields).

## 5. Recoverable vs genuinely unavailable

| category | rows | source | action |
| --- | --- | --- | --- |
| Recoverable now from canonical fields (B) | 137 | prior canonical reports | implement report-chain TTM (no writes) |
| Recoverable only by parser/re-ingestion (C) | 35 | `INSUFFICIENT_TTM_PERIODS` | needs older reports re-parsed |
| Potentially recoverable if raw Codal payload exists (C) | subset of 1,579 | `CodalReports` registry is small; `raw.report_payloads` empty | bounded feasibility check per company |
| Genuinely unavailable in canonical (D) | ~1,500 | legacy monetary/balance columns never populated; Product1 forbidden | keep NULL + Data Quality |
| Policy (E) | 0 facts (4 subjects) | eligibility policy | policy decision only |

## 6. Are these caused by a bug in canonical migration or analytics?

No. Evidence:

* `MIGRATION_NOT_IMPORTED = 0` — every non-null legacy value is present in canonical.
* Population difference is fully explained (9/9 classified; 0 unexplained).
* Canonical analytics is unit-correct and PIT-correct (tests pass).
* The analytics engine correctly returns `NULL` where canonical facts are absent.

No `BUG_SUSPECTED` in the oracle comparison either (previous phase).

## 6b. Reclassification of remaining gaps (post-acceptance)

| gap class | count | reclassification |
| --- | --- | --- |
| 5 no-canonical subjects | 5 | `ACCEPTED_CANONICAL_SCOPE_EXCLUSION` (not required) |
| 4 policy-excluded subjects | 4 | policy (E), not data work |
| `SOURCE_ABSENT` fact rows | ~1,579 | `ACCEPTED_SOURCE_LIMITATION` for v1 / `OPTIONAL_FUTURE_REINGESTION` for future quality |
| `TTM_RECOVERABLE_REPORT_CHAIN` | 137 (129 op recovered) | RESOLVED (report-chain TTM) |
| `MISSING_PRIOR_ANNUAL` | 7 (op) | `ACCEPTED_SOURCE_LIMITATION` (non-Esfand fiscal years) |
| `INSUFFICIENT_TTM_PERIODS` | 35 | `OPTIONAL_FUTURE_REINGESTION` |
| `MIGRATION_NOT_IMPORTED` | 0 | — |
| `TRUE_CANONICAL_BLOCKER` | **0** | — |
| `MODEL_SEMANTICS_BLOCKER` | **0** | — |

The ~1,579 `SOURCE_ABSENT` rows are an **acceptable historical limitation for v1**;
they are not required before point-in-time backtesting, but are `OPTIONAL_FUTURE_REINGESTION`
for future data-quality improvement.

## 7. Affected companies / periods

Full machine-readable list in `company_fact_coverage.csv` (columns:
`company_id`, `symbol`, `required_fact`, `period_count`, `required_period_count`,
`latest_period`, `ttm_eligible`, `pit_eligible`, `missing_reason`,
`source_availability`, `source_column`, `remediation_class`).
Aggregates in `metric_coverage.csv` (latest available period per metric).
Latest available financial periods are the 1405 fiscal-year reports
(gregorian `2026-*`), i.e. the newest data is present; it is historical depth and
coverage breadth that are missing.
