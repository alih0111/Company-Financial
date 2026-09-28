# QUARTERLY PROFIT CONTRACT

## What the upper chart represents

Repository evidence: the legacy upper chart plotted `percentage = Product1/1e6`
where `Product1 = Num1_Value1 (EPS) × Num2_Value1 (capital)` — a **cumulative
(YTD) net-profit proxy**, not standalone quarterly profit and not raw EPS. The
React code comment labels it "EPS Chart", but the plotted value was the cumulative
profit proxy. There was no historical standalone-quarter derivation anywhere.

The agreed target semantics (per product intent) is **standalone quarterly
profitability**. This contract implements that while preserving the legacy series
definition.

## Data reality (source-absent true net profit)

Verified against SQL Server `dbo.miandore2` for کاسپین (and systematically):
`NetProfitAmount`/`NetProfitAmountLY`/`NetProfitAmountFYPrev`/`RevenueNew` are
**NULL for every historical period** (only the latest report is populated).
`Num1_Value1` (EPS), `Num2_Value1` (capital) and the derived `Product1` are
complete across ~29 periods. No other table holds historical net profit.

Therefore true historical net profit cannot be displayed without fabrication.
The deterministic cumulative net-profit **proxy** `EPS × Capital` (which equals
source `Product1` exactly) is used for the chart. It is a presentation value and
is **never stored** as a canonical fact.

## Derivation rule

Within one fiscal year, with periods ordered oldest→newest and `cum_t = EPS_t × Capital_t`:

```
Q1 standalone = cum_Q1
Q2 standalone = cum_Q2 - cum_Q1
Q3 standalone = cum_Q3 - cum_Q2
Q4 standalone = cum_Q4 - cum_Q3   (cum_Q4 = FY 12-month total)
```

- Subtractions happen **only within the same fiscal year**; a new fiscal year
  resets to Q1 with no cross-year subtraction.
- Fiscal year is the **Jalali year prefix** of the period (canonical migrated
  statements carry no fiscal_year/fiscal_month metadata) — a documented fiscal
  proxy; non-standard (non-Esfand) fiscal calendars are NOT yet distinguished.
- Negative values (losses) are supported.
- Corrected/superseded versions: the live series uses the current statements
  (canonical `financial_statements` per report); PIT/backtesting semantics are
  untouched.

## API contract

`GET /api/SalesData` (canonical) returns, oldest→newest:

```json
{ "companyName","companyID","reportDate","periodEndDate",
  "fiscalYear","quarter","cumulativeNetProfit","quarterlyNetProfit",
  "percentage","wow",
  "Product1":0,"Product2":0,"Product3":0 }
```

- `quarterlyNetProfit` / `cumulativeNetProfit` = the proxy in source units.
- **Compatibility** `percentage` = `quarterlyNetProfit / 1e6` (same scale the
  legacy `Product1/1e6` chart used). Documented single meaning: standalone
  quarterly profit proxy, NOT EPS.
- `wow` = sign relation of adjacent standalone quarters.
- `Product1/2/3` are deprecated compatibility fields (unused, 0).
- Empty history → `200 []`.

EPS is **not** substituted into the profit metric; it is used only for the
EPS-growth donut (`/api/CompanyScores`) and remains a separate metric.
