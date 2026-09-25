# SHADOW COMPARISON REPORT — Phase 1 + Phase 2

Command:

```powershell
cd go-app
$env:CDF_READ_MODE="shadow"
$env:CDF_CANONICAL_DB="company_financial_analytics_shadow_v121"
go run ./cmd/shadowcheck
```

Environment: local PostgreSQL 18 (`company_financial_analytics_shadow_v121`) and
legacy SQL Server `codal`, both read-only. Score version `canonical-v1-dev`
(run `c6cb1579-2c28-4526-b3eb-f71d781ca4a4`, as-of `2026-09-24`).

Artifacts: `output/shadow_summary.json`, `output/shadow_differences.csv`,
`output/endpoint_summary.csv`.

## 1. Coverage

| Endpoint | Comparison units |
| --- | --- |
| `GET /api/CompanyNames` | full legacy name set (267) vs canonical (273) |
| `GET /api/summary` | top-20 legacy score rows |
| `GET /api/price-history` | 6 symbols × 30 sessions |
| `GET /api/SalesData2` | 12 heterogeneous companies (monthly activities) |
| `GET /api/SalesData` | 12 heterogeneous companies (income statement) |

Heterogeneous sample deliberately includes strong monthly coverage (افق 77,
دکپسول 79, هجرت 78), sparse coverage (چخزر 1, غپاک 1, شکیمیا 0/3), companies
with no market identity (خاهن، شخارک، شکیمیا) and an alias-only named company
(کسرا).

## 2. Aggregate classification totals (cumulative)

| Classification | Count |
| --- | --- |
| `EXACT_MATCH` | 4648 |
| `EXPECTED_UNIT_PRESENTATION` | 384 |
| `EXPECTED_CANONICAL_SEMANTIC_CHANGE` | 83 |
| `LEGACY_ONLY` | 106 |
| `CANONICAL_ONLY` | 10 |
| `ORDER_ONLY_DIFFERENCE` | 1 |
| `NUMERIC_MISMATCH` | 0 |
| `IDENTITY_MISMATCH` | 0 |
| `NULL_SEMANTICS_DIFFERENCE` | 0 |
| `QUERY_ERROR` | 0 |
| `UNCLASSIFIED_MISMATCH` | 0 |

**No unexplained difference remains.**

## 3. Per-endpoint results

| Endpoint | Legacy | Canonical | Matched | Exact | Expected | Unexpected | Errors |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `GET /api/CompanyNames` | 267 | 273 | 263 | 263 | 14 | 0 | 0 |
| `GET /api/summary` | 20 | 20 | 20 | 77 | 84 | 0 | 0 |
| `GET /api/price-history` | 180 | 180 | 180 | 1260 | 0 | 0 | 0 |
| `GET /api/SalesData2` | 428 | 384 | 384 | 1536 | 428 | 0 | 0 |
| `GET /api/SalesData` | 310 | 252 | 252 | 1512 | 58 | 0 | 0 |

## 4. Fundamentals interpretation

### SalesData2 (monthly activities)

- `production_quantity` and `sales_quantity` are **exact matches** row-for-row.
- `reported_sales_amount` (legacy `Value3` million_rial) is an **exact match**
  against `fundamentals.monthly_activities.reported_sales_amount`.
- `sales_amount_rial` fires `EXPECTED_UNIT_PRESENTATION` (×1,000,000), which is
  the documented canonical IRR vs legacy million_rial difference.
- 44 `LEGACY_ONLY` rows belong to شخارک, which has no canonical identity — an
  expected scope exclusion (see `UNMAPPED_LEGACY_NAMES.md`).
- Legacy API divides `Value1/2/3` by 1e6 for presentation; the comparison uses
  stored values and does not change that behavior.

### SalesData (income statement)

- `eps`, `revenue`, `operating_profit`, `net_profit`, `capital` are **exact
  matches** for all 252 matched periods.
- 58 `LEGACY_ONLY` rows are خاهن (28), شخارک (27), شکیمیا (3) — the scope-excluded
  companies.
- `Product1/2/3` are **not** compared: they are legacy derived mixed-scale
  heuristics (`EPS × Capital`) with no canonical metric. They are not
  re-derived in Go.

## 5. Latency (aggregated, local, no caching)

Final run (warm page cache):

| Endpoint | Legacy | Canonical | Combined |
| --- | --- | --- | --- |
| CompanyNames | 23.3 ms | 10.7 ms | 34.0 ms |
| Summary | 4363.2 ms | 29.3 ms | 4392.5 ms |
| Price-history | 365.7 ms | **46.2 ms** | 411.8 ms |
| SalesData2 | 49.2 ms | 21.1 ms | 70.3 ms |
| SalesData | 104.2 ms | 87.4 ms | 191.6 ms |

- Price-history canonical dropped from **3280.4 ms** (Phase 1) to **46–71 ms**
  depending on cache warmth.
- SalesData canonical was **1475 ms on the cold first run** and ~87 ms warm; the
  cold cost is one canonical query per company (N+1). Acceptable for bounded
  shadow; flagged as a future batching option.
- The legacy `vw_AIStockMetrics` query remains the dominant cost (~4.4–5.1 s) and
  is unrelated to this integration.

## 6. Market query profile (summary)

Root cause: `VIEW_EXPANSION` + `QUERY_SHAPE` — `market.daily_prices`
(`DISTINCT ON` over the whole `price_observations` table) ranked 331,265 rows
before applying the security predicate. Fix: resolve the security once and read
`price_observations` directly. Median 655.6 ms → 1.8 ms (15 samples); `EXCEPT`
equivalence over `(trade_date, closing_price_rial, observation_id)` = 0/0. Full
detail in `MARKET_QUERY_PROFILE.md`.

## 7. Failure isolation

Unit tests cover canonical failure for monthly, income-statement, scores and
price paths: a canonical error yields `QUERY_ERROR` while the legacy slice is
byte-for-byte unchanged. Phase-1 also observed a real canonical query failure
during development that returned all legacy rows unchanged.

## 8. Unexplained differences

None. Every difference is classified and documented.
