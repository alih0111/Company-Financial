# SYMBOL-PAGE CANONICAL VALIDATION

Harness: `go-app/cmd/symbolvalidate` (read-only). For a heterogeneous symbol set
it exercises the canonical application path (`integration.PG.SymbolPage`) and
records availability of every symbol-page stage. Missing data is explicit
(`MISSING` / `ZERO_OR_NULL`), never fabricated.

- Sample: 12 companies drawn from SQL Server by market coverage (high), monthly
  coverage (low), income-statement coverage (high) and known scope-excluded names
  (`کسرا`, `خاهن`, `شکیمیا`).
- Canonical DB: `company_financial_analytics_shadow_v121`.
- Machine-readable: `output/symbol_page_canonical_validation.csv`.

## Stage coverage

| Stage | Canonical PRESENT |
| --- | --- |
| identity | 10 / 12 |
| monthly production / sales / revenue | 7 / 12 |
| financial revenue | 5 / 12 |
| operating profit / net profit / EPS / capital | 5 / 12 |
| market history | 10 / 12 |
| canonical metrics (category scores) | 7 / 12 |
| factor scores | 7 / 12 |
| QuantScore | 7 / 12 |
| metric_snapshots | 0 / 12 (not materialized) |

## Heterogeneous outcomes (representative)

- **Full coverage** (e.g. `کسرا`, `چکاپا`, `فولاد`-class): identity, monthly,
  financial, market, category scores (`growth/profit/valuation/market/dq`),
  factor scores and QuantScore all PRESENT.
- **Monthly-only** companies (market+monthly, no `miandore2`): financial stages
  `MISSING`, identity/monthly/market/scores PRESENT.
- **Financial-only, zero market** (`326f…`, `9ec9…`): canonical identity absent →
  all canonical stages `MISSING`; these are the documented scope exclusions.
- **Alias-only** (`خاهن`, `شکیمیا`): identity unmapped (no canonical market
  identity); explicit, not fabricated.
- **Partial financial fields**: some latest income-statement rows have
  `operating_profit`/`net_profit` present but `revenue`/`capital` ZERO_OR_NULL
  (legitimate source NULL), surfaced explicitly.

## Score metadata

For every score-bearing company the CSV records:

```
score_version = canonical-v1-dev
score_as_of    = 2026-09-24
data_as_of     = 2026-09-22   (max canonical fundamentals period)
score_stale    = true         (canonical market data 2026-09-25 is newer than the run cutoff)
```

This proves staleness is detectable at the page level. `metric_snapshots` are
consistently reported as `metric_snapshots_not_materialized` because
`analytics.metric_snapshots` is empty in the current canonical run.

## Conclusion

The canonical application path can supply the symbol page contract — identity,
monthly production/sales/revenue, financial revenue/operating profit/net profit/
EPS/capital, market history, canonical metrics, factor scores, category scores and
QuantScore — for every company that is in the canonical universe, with explicit
NULL/DQ behaviour where data is legitimately absent or the identity is a
documented scope exclusion. No canonical value is fabricated.

## Final post-refresh completeness (Phase 9)

Re-ran `cmd/symbolvalidate` after the analytics refresh (new run
`489a6df0-…`, `score_as_of=2026-09-25`). Per-symbol classification:

| Symbol class | Classification |
| --- | --- |
| full canonical coverage | **COMPLETE** |
| market+monthly, no income statement | **PARTIAL_EXPECTED** |
| zero-market / unmapped identity | **OUT_OF_SCOPE** (scope exclusion) |
| alias-only (`خاهن`, `شکیمیا`) | **MISSING_CANONICAL** (documented) |

- `score_stale=false` for every score-bearing symbol after refresh.
- `metric_snapshots` remain unmaterialized (`PARTIAL_EXPECTED` for that stage).
- Machine-readable: `output/symbol_page_final_validation.csv`.

Residual items (not blockers):
1. materialize `analytics.metric_snapshots` if base-metric snapshots are required;
2. resolve alias/scope-excluded identities via a dedicated intake if product
   scope later requires them.
