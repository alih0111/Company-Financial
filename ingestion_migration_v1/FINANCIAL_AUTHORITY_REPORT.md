# FINANCIAL AUTHORITY REPORT (Part B)

FINANCIAL_STATEMENT promoted to canonical-primary (shadow), reversible, after
the monthly routine soak passed. SQL Server retained as mirror; CODAL unchanged.

## 1. Configuration

`CDF_FINANCIAL_INGESTION_AUTHORITY=canonical`, `CDF_FINANCIAL_FALLBACK_LEGACY=true`,
`CDF_INGESTION_MODE=dual_write`. Wired in `MianSql.save_profit_loss_to_sql`
(both success paths).

## 2. Real cycles (`financial_authority_cycles.csv`)

20 cycles over 5 companies × 2 periods × 2 rounds (تاصیکو strong, قاسم strong,
کسرا alias, چکاپا sparse, شکیمیا legacy-only).

| Metric | Value |
| --- | --- |
| canonical inserted (chain+statements+facts) | 6 |
| canonical skipped | 376 |
| reconciliation | `EXACT_EQUIVALENT` 40, `EXPECTED_UNIT_CONVERSION` 127, mismatches **0** |
| mirror | success (normal cycles) |
| quarantines | شکیمیا (legacy-only, classified) |

## 3. Statements / facts / lineage

Statements reused (`ON CONFLICT (parse_run_id, statement_type)`); facts reused
(`ON CONFLICT (statement_id, metric_code, period_order)`). Second run created no
duplicate statements/facts and no fake versions. Parser rerun check: **new
parse_run without new report_version** (`parser_ok=true`).
`forbidden_facts=0` — no Product1/2/3/NPUnitRatio/OpK/OpAmt.

## 4. Units / periods

monetary `canonical_value = reported_value × 1e6` (million_rial → IRR),
EPS `rial_per_share`; period linkage by `period_end_date`/`period_order`/
`comparison_type`. Reconciliation `EXPECTED_UNIT_CONVERSION` only; no
NUMERIC/DATE/IDENTITY/MISSING/WRITE/UNCLASSIFIED.

## 5. Idempotency

Retry vs intentional reparse distinguished: replay reuses statement/fact keys;
parser rerun adds a parse_run only.

## 6. Failure injection

| Scenario | Result |
| --- | --- |
| PostgreSQL unavailable | `CANONICAL_FAILED_LEGACY_FALLBACK_USED`; retry queued |
| SQL Server mirror failure | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED` (canonical authoritative preserved) |
| Unresolved identity | `quarantined` + DQ (health `IDENTITY_QUARANTINE`); no fake entity |
| Invalid metric/constraint failure | canonical transaction rolled back (covered by `test_canonical_ingest_db`) |
| Parser failure | canonical rolled back; legacy continuity; health `PARSER_ERROR` |

## 7. Retry

Shared manifest; pending `financial_statement` replayed (canonical-only, marked
done) → `retry_backlog=0`.

## 8. Freshness (`financial_authority_freshness.json`)

authority CANONICAL, latest source report, latest canonical period/write,
statements count, mirror active, retry backlog 0, quarantine count (classified),
health `IDENTITY_QUARANTINE`.

## 9. Go read-path end-to-end

`cmd/shadowcheck` SalesData (Go `FinancialMetricsByLegacyCompanyID`): all
matched/expected, **0 unexpected** — Go canonical financial read sees the data.
No endpoint serving change.

## 10. Analytics visibility / TTM

Canonical statements/facts visible; existing score runs not overwritten. TTM
chain feasibility: a company with ≥5 canonical income-statement periods and
revenue facts exists (`report_chain_ttm_feasible=true`), so both direct TTM and
report-chain TTM can consume the new data; no Product1-based substitutes.

## 11. Other domains

MARKET_PRICE and MONTHLY_ACTIVITY canonical-primary (unchanged); CODAL unchanged.
No accidental global authority switch.

## 12. Gate

**`FINANCIAL_CANONICAL_AUTHORITY_READY`**
Routine-use: **`FINANCIAL_CANONICAL_PRIMARY_READY_FOR_ROUTINE_USE`**
