# KASPIN FINANCIAL RECONCILIATION

> CORRECTION (current): the chart semantics were corrected to **cumulative (YTD)
> reported net profit**, not standalone quarters and not EPS. Canonical
> `net_profit` for کاسپین exists only for **1405/03/31** (source
> `miandore2.NetProfitAmount` is NULL for all 26 earlier periods). The historical
> cumulative net-profit series is therefore **not available from the source** and
> the chart correctly returns only that period. See
> `CUMULATIVE_PROFIT_CHART_CONTRACT.md` and
> `CUMULATIVE_PROFIT_BUGFIX_REPORT.md`. The tables below remain the audit of the
> available data (cumulative proxy), retained for lineage evidence. Gate:
> `CUMULATIVE_PROFIT_DATA_INCOMPLETE`.


End-to-end trace, source (SQL Server `dbo.miandore2`) → canonical
(`fundamentals.financial_statements` / `financial_facts` / `ingestion.reports`)
→ API. Machine-readable: `output/kaspin_financial_periods.csv`.

Company: کاسپین (`3d594732-5172-49ca-b8c5-7b684189196d`), legacy key
`7386c9d3264a07cdaacbdba2e1941d42`. 27 income-statement periods (1398/09…1405/03).

## Period-by-period (cumulative proxy, standalone quarter)

| period | FY | Q | canonical EPS | capital | source NetProfit | Product1 = EPS×Cap | cumulative proxy | standalone quarter |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1403/12/30 | 1403 | 4 | 6988 | 1,400,000 | NULL | 9,783,200,000 | 9,783,200,000 | 5,016,200,000 |
| 1404/03/31 | 1404 | 1 | 2759 | 1,400,000 | NULL | 3,862,600,000 | 3,862,600,000 | 3,862,600,000 |
| 1404/06/31 | 1404 | 2 | 1149 | 7,940,000 | NULL | 9,123,060,000 | 9,123,060,000 | 5,260,460,000 |
| 1404/09/30 | 1404 | 3 | 1849 | 7,940,000 | NULL | 14,681,060,000 | 14,681,060,000 | 5,558,000,000 |
| 1404/12/29 | 1404 | 4 | 2747 | 7,940,000 | NULL | 21,811,180,000 | 21,811,180,000 | 7,130,120,000 |
| 1405/03/31 | 1405 | 1 | 1570 | 7,940,000 | 12,467,922 | 12,465,800,000 | 12,465,800,000 | 12,465,800,000 |

- `Product1 = EPS × Capital` matches the source `Product1` column exactly for
  every period → the canonical facts (EPS, capital) faithfully reproduce the
  legacy chart metric.
- `source NetProfit = NULL` for all periods except 1405/03/31 → true historical
  net profit is **SOURCE_ABSENT**.
- FY1404 standalone quarters increase monotonically (3.86→5.26→5.56→7.13
  billion), i.e. the profitability improvement is correctly represented.
- FY1405/Q1 (12.47bn) is a new-fiscal-year Q1: **no cross-year subtraction**.

## Lineage per period
Each period has its own `financial_statement` with `report_id`,
`report_version_id`, `parse_run_id`, and `reports.source_report_id`
(`legacy:<key>:<date>:financial`). Facts carry `reported_value` (million_rial /
rial_per_share) and `canonical_value` (rial / rial_per_share), period_order 1.
`fiscal_year`/`fiscal_month`/`duration_months` are NULL on migrated statements.

## Conclusion
Canonical faithfully holds the available source facts; the sparsity of
`net_profit` is a source limitation, not a canonical migration/parser/query
defect. The quarterly-profit chart is derived deterministically from the complete
EPS×Capital cumulative series.
