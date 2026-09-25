# Canonical Report-Chain TTM — Specification (Class-B recovery)

Scope: recover Class-B TTM gaps identified by the data coverage audit
(`TTM_RECOVERABLE_REPORT_CHAIN`, 137 rows, ~136 `operating_profit`) using
**canonical** statements/facts only. No SQL Server, no legacy CSV, no `compat_v37`,
no v3.7 oracle, no `Product1`/`NPUnitRatio`/`OpK`/`OpAmt`, no scale guessing.

## 1. Contract

For an interim cumulative/YTD statement at period `P = (fiscal_year t, month m)`,
`m ≠ 12`:

```
TTM(fact, t, m) = FY(t-1, 12M) + YTD(t, m) - YTD(t-1, m)
```

* `YTD(t, m)`  = canonical fact `period_order = 1` of the report at `(t, m)`
* `FY(t-1, 12M)` = canonical fact `period_order = 1` of the report at `(t-1, 12)`
* `YTD(t-1, m)` = canonical fact `period_order = 1` of the report at `(t-1, m)`

For a full-year statement (`m = 12`): `TTM = YTD(t, 12)`.

All three legs must share the same **company**, **canonical metric_code**, and
**statement scope/type** (metric-coded, so type is implied), and be comparable
fiscal periods. Periods are matched via canonical `period_end_date` →
`(fiscal_year, fiscal_month)` (jalali); **row adjacency is never assumed**.

## 2. Resolution order (deterministic)

A. **Direct canonical TTM** — existing behavior: within-report
   `period_order 1 + 3 − 2` (or `1` when month = 12). Wins whenever valid; its
   value is never changed.
B. **Report-chain TTM** — used only when A is unavailable/NULL and the metric is
   chainable (`FLOW_CUMULATIVE`).
C. Otherwise **NULL** with a Data Quality / provenance reason.

## 3. PIT safety

The engine builds its report index from statements already filtered by the run's
`source_cutoff_at` / `as_of_date` (reports with `published_at` use the cutoff;
legacy synthetic reports use `period_end_date <= as_of`). The report-chain helper
therefore only sees facts visible at the cutoff. A corrected/superseded report
that did not exist at the historical cutoff cannot enter the chain. If the chain
was not available at the cutoff, the result is `NULL` with a PIT/insufficiency
reason.

## 4. Metric semantics (machine-readable)

`flow_type` in `metric_spec.json`:

| flow_type | metrics | chainable |
| --- | --- | --- |
| `FLOW_CUMULATIVE` | revenue, net_profit, operating_profit, operating_cash_flow, eps | yes |
| `STOCK_POINT_IN_TIME` | total_assets, current_assets, total_liabilities, current_liabilities, total_equity | **no** |
| `DIRECT_ONLY` | finance_cost, other_non_operating (used as latest point values) | no |

Balance-sheet/stock metrics must never use TTM chaining. Eligibility is read from
the registry, never inferred from metric names at runtime.

## 5. Edge cases

| case | behavior |
| --- | --- |
| full-year statement available (m=12) | direct; chain not needed |
| Q1 / half-year / 9M interim | chain formula applies |
| missing prior annual `(t-1,12)` | NULL, `MISSING_PRIOR_ANNUAL` |
| missing comparable prior interim `(t-1,m)` | NULL, `MISSING_PRIOR_COMPARABLE` |
| fiscal-year change | no `(t-1,12)`/`(t-1,m)` under the derived fiscal year → NULL |
| duplicate/corrected reports | deterministic latest `(period_end_date, version_no)` per `(t,m)` (existing index rule) |
| superseded reports | excluded from the report index (existing PIT rule) |
| PIT cutoff before correction | corrected report absent → chain uses only visible facts / NULL |
| NULL source values | treated as missing leg → NULL, never fabricated |
| zero / negative values | valid arithmetic (0 and negatives allowed) |
| report version ordering | highest `version_no` wins at equal period |
| non-calendar fiscal years | derived from canonical `period_end_date`; chain requires `(t-1,12)` report to exist |
| unequal/non-comparable period lengths | comparable-period match is strict on `(fiscal_year-1, fiscal_month)`; no mixing |
| deterministic tie-breaking | `(period_end_date, version_no)` desc |

## 6. Provenance / DQ codes

`DIRECT_CANONICAL`, `REPORT_CHAIN_TTM`, `INSUFFICIENT_TTM_PERIODS`,
`MISSING_PRIOR_ANNUAL`, `MISSING_PRIOR_COMPARABLE`, `NON_COMPARABLE_PERIOD`,
`PIT_UNAVAILABLE`. Recorded per metric in the run output so each recovered value is
explainable down to `(latest, prior-annual, prior-comparable)` canonical cells.

## 7. Non-goals

No broad re-ingestion; no balance-sheet chaining; no factor-weight changes; no
backtesting; existing direct TTM values are preserved.
