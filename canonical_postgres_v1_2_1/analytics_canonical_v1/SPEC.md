# Canonical Analytics v1 — Specification

Status: **specification (pre-implementation)**. Score version: `canonical-v1-dev`.
Not production. No new factor weights are decided here.

## 1. Goal

A new analytics model that reads **only Canonical PostgreSQL** (`core`,
`ingestion`, `fundamentals`, `market`) and has **no dependency on legacy frozen
inputs**. It is the successor to the v3.7 Golden Regression Oracle
(`analytics_v37_oracle/`), which remains frozen for regression/reference only.

## 2. Allowed inputs

Only these schemas: `core`, `ingestion`, `fundamentals`, `market`.

## 3. Forbidden inputs (hard)

* SQL Server runtime dependency.
* legacy `Product1` / `Product2` / `Product3`.
* legacy `Num1_Value*` / `Num2_Value*` as analytics input.
* `NPUnitRatio`.
* `OpK` / `OpAmt` legacy heuristic.
* frozen CSV as a production input.
* `compat_v37.*` tables.

## 4. Units contract (see `units_contract` in `metric_spec.json`)

* monetary = IRR (rial)
* EPS = `rial_per_share`
* ratios = dimensionless
* percentages = explicit convention (`*_pct` = percent, e.g. `15.0` = 15%; `*_ratio` = fraction)
* **No scale detection** anywhere in analytics. If `canonical_unit` is missing or
  unexpected, emit a Data Quality issue; do not guess.

## 5. Point-in-Time contract

Every run carries `as_of_date` and `source_cutoff_at`. A financial report is
eligible only if its content was visible at the cutoff
(`report_version.collected_at <= source_cutoff_at`, and `reports.published_at <=
source_cutoff_at` when known). A market observation is eligible only if
`collected_at <= source_cutoff_at`. Corrected/superseded reports are excluded via
the supersede chain (see `ttm_spec.md` §6). No look-ahead.

## 6. Company ↔ Security separation

Company-level metrics (fundamentals): revenue, net profit, operating profit,
margins, ROE, balance-sheet ratios, sales growth.
Security-level metrics (market): price, valuation, momentum, volatility, liquidity.

A **scoring subject** is an eligible canonical **company** with an optional
**primary security**. The final score is `company fundamentals` combined with
`primary-security market` factors. See `population_spec.md`.

## 7. Deliverables in this package

| file | content |
| --- | --- |
| `SPEC.md` | this document |
| `population_spec.md` | canonical scoring subject eligibility/policy |
| `ttm_spec.md` | canonical TTM (no Product1) |
| `metric_spec.json` | machine-readable metric registry |
| `factor_review.md` | KEEP/REPLACE/REMOVE for all 21 v3.7 factors |
| `legacy_removal_matrix.md` | every v3.7 legacy heuristic and its canonical replacement |
| `data_quality.py` / `data_quality.md` | DQ flag model |
| `compute_metrics.py` | canonical-only metric engine (`canonical-v1-dev`) |
| `compare_oracle.py` | v3.7 oracle vs canonical-v1 classification |
| `CANONICAL_V1_REPORT.md` | decision report |
| `tests/` | regression tests |

## 8. Non-goals (this phase)

* No production Go API cutover.
* No production DB/code change.
* No validated weighting / optimization — `baseline_weights_v37` is used only as a
  labelled prototype baseline (`NOT VALIDATED FOR CANONICAL V1`).
