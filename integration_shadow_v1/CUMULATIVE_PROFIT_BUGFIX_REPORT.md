# CUMULATIVE PROFIT BUGFIX REPORT

**Gate: `CUMULATIVE_PROFIT_DATA_INCOMPLETE`**

## Old vs new semantics
- Wrong (previous): standalone quarterly profit = `Qn − Q(n−1)` within a year,
  and before that raw **EPS** as a rendering fallback.
- Correct (now): the upper chart plots the **reported cumulative (YTD) net
  profit** for each financial period: `FY: 3M → 6M → 9M → 12M`, then the next FY
  resets to its own 3M value. No subtraction, no EPS.

## Canonical metric now used
`fundamentals.financial_facts.metric_code = 'net_profit'`, `period_order = 1`
(current statement of each report), `canonical_value` in IRR. New canonical read
`PG.NetProfitSeriesByLegacyCompanyID` + `Shadow.FetchCumulativeProfitCanonical`.

## EPS substitution removed
Yes. The chart no longer calls the EPS/FEPS derivation. EPS remains only in the
EPS-growth donut (`/api/CompanyScores`). `DeriveQuarterlyProfit` is retained as a
separate analytics utility but is no longer used by the chart.

## Ordering / fiscal reset
Strictly oldest→newest by `period_end_date`; `periodOrder` labelled 3/6/9/12 from
the Jalali month (Esfand-ending convention). Each period is its own reported
cumulative value, so a new fiscal year naturally resets — e.g. 1404 3M is small
and never stacked on 1403 12M. Negative values preserved. One value per period.

## کاسپین reconciliation (source vs canonical)
`output/kaspin_cumulative_profit.csv`. 27 source periods; **only 1 has reported
net profit** (1405/03/31 = 12,467,922 million_rial; canonical
12,467,922,000,000 IRR). All 26 historical periods are `MISSING_SOURCE`
(`miandore2.NetProfitAmount IS NULL`). Canonical matches the source exactly (no
migration/parser/query defect).

Live API now returns one cumulative point for کاسپین:
`1405/03/31, periodOrder=3, cumulativeNetProfitRial=12467922000000`.

## Missing historical net_profit count
Systemic: `miandore2` has **378 / 6864** non-null `NetProfitAmount`; **162
companies have zero** net-profit periods; only ~18 companies have >1. کاسپین: 1/27.

## Repair performed
**None.** The original source does not contain historical net profit, so there is
nothing to migrate and it must not be fabricated. `DERIVED` proxies (EPS×Capital)
are explicitly **not** used for this chart anymore.

## Tests
`go build/vet/test ./...` pass. Helpers (`periodOrderFromMonth`, cumulative
series ordering, no-EPS substitution) covered; `DeriveQuarterlyProfit` unit tests
retained for the separate utility.

## Remaining limitation / path to CORRECT
Historical net profit exists only in the Codal source reports (not in the legacy
`miandore2` column). Reaching `CUMULATIVE_PROFIT_CHART_CORRECT` requires
re-ingesting historical `net_profit` from Codal income-statement reports per
period (a data-ingestion task), deterministically and with lineage. Until then
the chart is semantically correct but data-incomplete for the affected universe.
