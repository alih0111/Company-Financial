# Numeric Tolerances

`analysis_cutoff_at` = `2026-09-24T20:41:02Z` · `analysis_as_of_date` = `2026-09-24`.

| metric class | tolerance | rationale |
| --- | --- | --- |
| IDs / dates / flags / categories | **exact** | no numeric drift possible |
| rank population membership | **exact** | a single row difference fails rank parity |
| Decimal financial values (canonical, after ×1e6 scaling) | `abs <= 1e-6` | canonical `numeric(30,6)` vs legacy `FLOAT(53)` rounding only |
| SalesLast12M / SalesPrev12M / TTMNetProfit | `abs <= 1e-6 × max(1,|ref|)` | large magnitudes from metric scalars |
| Ratios / percentages (margins, ROE) | `abs <= 1e-2` | one basis-point granularity |
| P/E, P/S | `abs <= 1e-2` | ratio |
| **QuantScore / sub-scores** | `abs <= 0.5` **planned**, but parity not achieved (see below) | score tolerance must never mask a logic bug |

## Important
Tolerances are only used to classify *value* differences. Any `LOGIC_DIFFERENCE`,
`POPULATION_DIFFERENCE`, `NULL_SEMANTICS`, or `UNKNOWN` classification is **not**
tolerated away and is reported explicitly.
