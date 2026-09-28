# FUNDAMENTALS PRESENTATION CONTRACT (`percentage`, `wow`)

The active React client consumes `percentage`, `wow`, `reportDate` (and
SalesData `companyName`) from `/api/SalesData` and `/api/SalesData2`. This
document fixes their exact semantics so a future canonical serving path is
unambiguous. Presentation values are **never** stored as canonical facts.

## Current legacy computation

### SalesData2 (monthly activity) — `go-app/handlers/sales_data2.go`
```go
s.Value1 /= 1e6; s.Value2 /= 1e6; s.Value3 /= 1e6
s.Percentage = math.Round(s.Value3*1000*100) / 100
if s.Value1 > 0 && (s.Value2 < 0 || s.Value3 < 0) { woW =  1 }
else if s.Value1 < 0 && (s.Value2 > 0 || s.Value3 > 0) { woW = -1 }
else { woW = 0 }
```
`Value1/2/3` = canonical `production_quantity`, `sales_quantity`,
`reported_sales_amount` (million_rial).

### SalesData (income statement) — `go-app/handlers/sales_data.go`
```go
s.Percentage = roundFloat(s.Product1/1_000_000, 2)   // Product1 = EPS_current * Capital
# WoW from the signs of Product1/Product2/Product3
```

## Classification

| Field | Endpoint | Classification |
| --- | --- | --- |
| `percentage` | SalesData2 | **VALID_PRESENTATION_DERIVATION** |
| `wow` | SalesData2 | **UI_ONLY_DERIVATION** |
| `percentage` | SalesData | **LEGACY_HEURISTIC** (`Product1 = EPS × Capital`, mixed scale) |
| `wow` | SalesData | **UI_ONLY_DERIVATION** (sign relation of the three Product values) |

`CANONICAL_ANALYTIC_METRIC` is not used: neither value is a canonical analytics
output. `SalesData2.percentage` is a linear rescaling of the canonical monthly
sales amount, so it *is* a mathematically valid presentation derivation.

## Canonical API-boundary definition

Implemented as a pure function in `go-app/integration/presentation.go`:

```go
func MonthlyPresentation(productionQuantity, salesQuantity, salesAmountRial float64) (percentage float64, wow int)
```

- `percentage = math.Round(sales_amount_rial / 1e9 * 100) / 100`
  - Equivalent to the legacy `reported_million_rial / 1e3`.
  - Units: legacy presentation scalar (IRR expressed in units of 1e9). No scale
    guessing; canonical IRR is the input.
- `wow`:
  - `+1` if `production_quantity > 0 && (sales_quantity < 0 || sales_amount_rial < 0)`
  - `-1` if `production_quantity < 0 && (sales_quantity > 0 || sales_amount_rial > 0)`
  - `0` otherwise
- `reportDate` = canonical `jalali_period_text` (identity, not derived).
- `companyName` = canonical display/legal name at the API boundary.

### NULL / zero handling
- Canonical NULL reads currently coerce to `0` at the read boundary (documented in
  `FUNDAMENTALS_READ_MIGRATION.md`); `percentage` then becomes `0`.
- A zero component never creates a `wow` sign conflict (strict inequalities).
- No value is fabricated when canonical data is absent; the row is simply omitted
  or carries explicit `0`.

### Ordering
- Legacy SalesData2 has no `ORDER BY`; the chart renders in received order.
- Canonical serving **must** return a deterministic order: `period_end_date DESC`
  for the API list, reversed to ascending for the chart. This is a documented
  presentation decision, not a canonical fact.

## SalesData (income statement) decision

`Product1` is the banished legacy heuristic (`EPS × Capital`, mixed scale) and is
**CLIENT_UNUSED**. There is no mathematically faithful canonical equivalent.
Therefore:

- canonical serving for `SalesData` is **not** enabled on this basis;
- a canonical replacement for the EPS-chart `percentage` must be an explicitly
  chosen canonical metric (e.g. `net_profit` or a defined EPS metric) approved as
  a product decision before the endpoint can be canary-eligible;
- `Product1/2/3` may be **omitted** in the future canonical contract.

## Tests
`go-app/integration/presentation_test.go` pins the percentage/wow formulas,
rounding, zero handling and sign semantics.
