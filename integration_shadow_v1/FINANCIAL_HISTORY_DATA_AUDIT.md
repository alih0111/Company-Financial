# FINANCIAL HISTORY DATA AUDIT

## Question
Why is canonical `net_profit` present for ~1 period while `eps` is present for
~29 periods?

## Finding: `SOURCE_ABSENT` (not a migration/parser/query defect)

Verified against the live SQL Server source `dbo.miandore2`:

- `NetProfitAmount`, `NetProfitAmountLY`, `NetProfitAmountFYPrev`, `RevenueNew`
  are **NULL for every historical period**; only the latest report is populated.
- `Num1_Value1` (EPS), `Num2_Value1` (capital) and the derived `Product1`
  (`Num1_Value1 × Num2_Value1`) are complete across the period history.
- No other table (`Information_SCHEMA.COLUMNS` scan for `%Profit%`) holds
  historical net profit; the `vw_AIStockMetrics*` views derive TTM values from
  the same NULL column.

Classification: **SOURCE_ABSENT**. It is NOT
LEGACY_MAPPING_MISSING / CANONICAL_MIGRATION_BUG / METRIC_CODE_MAPPING_BUG /
STATEMENT_SELECTION_BUG / PARSE_BUG / QUERY_BUG / DEDUP_VERSION_SELECTION_BUG /
PERIOD_SEMANTICS_BUG. The canonical facts contain exactly what the legacy source
held (reconciliation: canonical `eps`/`capital` reproduce source `Product1`
exactly).

## Coverage audit

Machine-readable: `output/net_profit_coverage_audit.csv`.

| item | value |
| --- | --- |
| eps facts (period_order=1) | complete |
| capital facts (period_order=1) | complete |
| net_profit facts (period_order=1) | ~1 per company |
| companies with eps but no net_profit | 162 |
| companies with any net_profit | 102 |

So the missing-net-profit pattern is systemic and source-driven.

## Repair
No repair is possible or performed: there is no source history to migrate, and
fabricating net profit is forbidden. The chart instead derives standalone
quarterly profit from the complete deterministic cumulative proxy
`EPS × Capital` (== source `Product1`), documented in `QUARTERLY_PROFIT_CONTRACT.md`
and recorded in `output/financial_history_repair_summary.json`.

## Scope note
If true historical net profit is later required, it must be ingested from the
Codal source reports (re-parse), not reconstructed heuristically. That is a data
ingestion task, out of scope here (no fabrication).
