# CUMULATIVE PROFIT CHART CONTRACT

## Corrected semantics (supersedes QUARTERLY_PROFIT_CONTRACT.md)

The upper chart shows the **reported cumulative (YTD) net profit** for each
financial period, one data point per available period:

```
FY: 3M -> 6M -> 9M -> 12M     (cumulative within the fiscal year)
next FY: 3M -> 6M -> 9M -> 12M (resets to its own 3M cumulative value)
```

- **No standalone-quarter subtraction** (`Q2=6M−3M` etc.) is performed for this
  chart. (The derivation helper remains available as a separate analytics
  utility, unused by the chart.)
- **EPS is never used** as the profit value; the metric is
  `fundamentals.financial_facts.metric_code='net_profit'`, `period_order=1`
  (current period of each report).
- Ordering: strictly **oldest → newest**: by fiscal year, then by interim length
  (3M → 6M → 9M → 12M). Sorting is by `period_end_date`, never by amount or row
  order.
- Fiscal-year reset is natural because each period is its own reported cumulative
  value; 1404 3M stays small and is never stacked on 1403 12M.
- Negative (loss) cumulative values are preserved (not clamped).
- Missing periods stay missing (no fabrication). Corrected/reparsed versions do
  not duplicate a period: one current value per period (period_order=1 of the
  current statement).

## API contract (`GET /api/SalesData`)

```json
{ "companyName","companyID","reportDate",
  "periodEndDate","fiscalYear","periodOrder",
  "cumulativeNetProfitRial","cumulativeNetProfitMillion",
  "percentage","wow",
  "Product1":0,"Product2":0,"Product3":0 }
```

- `periodOrder` = interim length label **3 | 6 | 9 | 12** (derived from the
  Jalali month of the period for the conventional Esfand-ending fiscal year).
- `cumulativeNetProfitRial` = canonical IRR (`net_profit`, period_order=1).
- `cumulativeNetProfitMillion` = `reported_value` (million_rial).
- **Compatibility** `percentage` = `reported_value` (cumulative net profit in
  million_rial) — a single, documented meaning; **not** EPS.
- `wow` = sign relation of adjacent cumulative periods.
- `Product1/2/3` deprecated compatibility fields (unused, 0).
- No reported net-profit periods → `200 []` (explicit missing).

## React

`ChartComponent` plots `reportDate` + `percentage` in array order and performs no
subtraction or summation; the backend value is already cumulative. No frontend
change required.
