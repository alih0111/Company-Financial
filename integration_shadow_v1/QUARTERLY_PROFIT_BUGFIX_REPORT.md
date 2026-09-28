# QUARTERLY PROFIT BUGFIX REPORT

**Gate: `QUARTERLY_PROFIT_DATA_PARTIAL`**

## What was wrong
The previous fix plotted raw canonical **EPS** as the bar height because EPS had
good coverage. That was a rendering diagnostic, not the business meaning, and it
silently substituted EPS for profit. The chart is intended to show **standalone
quarterly profitability** (period profit), derived from cumulative YTD within the
same fiscal year.

## Root cause for کاسپین
- The chart metric was wrong (raw EPS), and the canonical `net_profit` series was
  sparse (1 of ~29 periods).
- Investigation: the sparsity is **SOURCE_ABSENT** — `dbo.miandore2.NetProfitAmount`
  is NULL historically; the complete historical series is the legacy cumulative
  proxy `EPS × Capital` (`Product1`).
- No canonical migration/parser/query defect (canonical EPS/capital reproduce
  source `Product1` exactly).

## Fix
- New deterministic derivation `integration.DeriveQuarterlyProfit`:
  oldest→newest, `cumQ1`, `cumQ2−cumQ1`, `cumQ3−cumQ2`, `cumQ4−cumQ3`, **within
  the same fiscal year only**; new fiscal year resets to Q1; negatives supported.
- `integration.ProfitProxyValue` = `EPS × Capital` (single consistent series,
  equals source `Product1`); true `net_profit` remains a separate stored metric,
  never substituted by EPS.
- API `SalesData` now returns explicit fields (`periodEndDate`, `fiscalYear`,
  `quarter`, `cumulativeNetProfit`, `quarterlyNetProfit`) plus the compatibility
  `percentage = quarterlyNetProfit/1e6` documented with a single meaning.
- Removed the raw-EPS substitution from the profit chart.
- Empty history → `200 []`; ordering oldest→newest; negative bars supported.

## کاسپین numbers (live API, verified)
FY1404 standalone quarters: Q1 3,862.6 → Q2 5,260.46 → Q3 5,558.0 → Q4 7,130.12
(units 1e6 of the proxy) — **monotonically increasing**, matching the known
profitability improvement. FY1405 Q1 = 12,465.8 (new-year Q1, no cross-year
subtraction).

## Other-symbol validation
`output/quarterly_profit_validation.csv` + `symbol_page_bugfix_validation.csv`.
Heterogeneous coverage/sign cases exercised in tests; sales chart ordering and
values verified separately (canonical monthly `reported_sales_amount` equals the
source `mahane.Value3`; the earlier combined soak showed 384 exact + 384 expected
unit conversions, 0 unexplained).

## Top KPI
`/api/summary` base values (EPS growth %, sales growth %, P/E) remain `null`
because canonical-v1 does not materialize factor `raw_value` and the underlying
historical net-profit/revenue inputs are source-absent. The KPI cards show `--`
(explicit missing), not a misleading 0. Ranks/fills and category scores are
correct. Wiring raw canonical inputs for these cards is deferred (requires
materialized raw values or a live-series read), and is not a scoring change.

## Tests
`integration` tests: `TestQuarterlyProfitDerivationWithinFiscalYear`,
`TestQuarterlyProfitNoCrossYearSubtraction`, `TestQuarterlyProfitNegativeAndProxy`,
`TestQuarterlyProfitMissingPriorQuarter`. `go build/vet/test ./...` pass.

## Remaining limitations
- Historical true `net_profit` is source-absent (proxy used).
- Fiscal year is inferred from the Jalali year prefix (canonical migrated
  statements carry no fiscal metadata); non-Esfand fiscal calendars are not yet
  distinguished.
- Corrected/superseded live-series selection uses current canonical statements;
  PIT/backtesting semantics unchanged.
