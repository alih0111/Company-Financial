# DUAL-WRITE SPEC — Phase 1

## 1. Scope

Additive canonical PostgreSQL writes for four domains, alongside the unchanged
SQL Server ingestion path. No irreversible cutover.

| Domain | Legacy input | Canonical output |
| --- | --- | --- |
| MONTHLY_ACTIVITY | `mahane` (Value1/2/3, ReportDate) | `fundamentals.monthly_activities` |
| FINANCIAL_STATEMENT | `miandore2` (FACT_MAP columns) | `fundamentals.financial_statements`, `fundamentals.financial_facts` |
| CODAL_REPORT | report metadata + raw payload | `ingestion.reports`, `report_versions`, `parse_runs`, `raw.report_payloads` |
| MARKET_PRICE | `MarketPriceHistory` | `market.price_observations` |

## 2. Configuration

| Env | Meaning | Default |
| --- | --- | --- |
| `CDF_INGESTION_MODE` | `legacy_only` \| `dual_write` \| `canonical_only` | `legacy_only` |
| `DATABASE_URL` / `CDF_CANONICAL_URL` / `CANONICAL_DATABASE_URL` | canonical DSN (SQLAlchemy `+psycopg` stripped) | — |
| `CDF_CANONICAL_DB` / `CDF_PILOT_DB` | database override | URL database |
| `CDF_ALLOW_NON_TEST_PG` | bypass test-DB prefix guard | unset |

Safety guard: writes refuse any database not named
`company_financial_analytics_shadow_*`, `company_financial_migration_pilot_*`,
`company_financial_test_*`.

## 3. Semantics

- LEGACY_ONLY: every `dual_write_*` returns `skipped_legacy_only`; no DB access
  beyond reading the DSN; no canonical write.
- DUAL_WRITE: canonical write inside one explicit transaction; SQL Server write
  remains authoritative and is not blocked by canonical outcomes.
- CANONICAL_ONLY: API present but not enabled by default and not used.

## 4. Identity resolution

`legacy_company_id` → `core.legacy_entity_map` (company/security);
`ins_code` → `core.securities.tsetmc_ins_code`; name/symbol →
`core.security_aliases`. No `md5(name)` identity, no duplicate creation, no
fabricated securities. Unresolved identity → quarantine
(`ingestion.data_quality_issues`, `issue_code='identity_conflict'`) and
`status="quarantined"`.

## 5. Idempotency

- Report: `ON CONFLICT (source, source_report_id)`.
- Report version: `ON CONFLICT (report_id, content_hash)` (version_no = max+1);
  identical content never creates a fake new version.
- Parse run: one completed run per `(report_version_id, parser_name,
  parser_version)`; the writer finishes every run (`completed`) so reruns reuse it.
- Monthly: logical dedup on `(company_id, period_end_date)` plus
  `ON CONFLICT (parse_run_id)`.
- Statement: logical dedup on `(company_id, period_end_date, statement_type)`;
  facts `ON CONFLICT (statement_id, metric_code, period_order)`.
- Price observation: `ON CONFLICT (security_id, trade_date, source,
  price_series, observation_hash)`; append-only, never overwritten.
- Raw payload: `ON CONFLICT (report_version_id, payload_type, content_hash)`.

## 6. Units and facts

Money is canonical IRR (`numeric`); `reported_*` keeps the source unit
(million_rial). EPS is `rial_per_share`. No scale guessing. `Product1/2/3` and
`NPUnitRatio`/`OpK`/`OpAmt` are never written.

## 7. Market timestamps

New market ingestion uses the **actual source collection time**
(`MarketPriceHistory.CollectedAt`, +03:30) as `collected_at`, not migration time.

## 8. Failure isolation

Each `dual_write_*` returns a `DualWriteResult` with status
`written | skipped_legacy_only | quarantined | canonical_error`. A canonical
error rolls back the canonical transaction only; it is recorded and never
surfaces as ingestion success. PostgreSQL unavailable / constraint violation /
unresolved identity / parser error are isolated.

## 8b. Real-script hook

Legacy scripts call `go-app/py/canonical_hook.py` after their successful SQL
Server commit:

- `py/brs_prices.py` (`cmd_daily`, `cmd_backfill_raw`) → `dual_write_market_rows`
- `py/MianSql2.py` (`save_report_to_sql`) → `dual_write_monthly_values`
- `py/MianSql.py` (`save_profit_loss_to_sql`, both success paths) →
  `dual_write_financial_by_key`

The hook lazily imports the canonical package only when
`CDF_INGESTION_MODE=DUAL_WRITE`/`CANONICAL_ONLY`, imports nothing canonical in
`LEGACY_ONLY`, and never raises into the legacy caller. Each call records a
structured batch row (`output/phase2_real_batches.csv`) and a concise summary.

## 9. Reconciliation

After a batch, `reconcile.py` classifies legacy vs canonical:
`EXACT_EQUIVALENT`, `EXPECTED_UNIT_CONVERSION`,
`EXPECTED_CANONICAL_SEMANTIC_CHANGE`, `LEGACY_ONLY_HEURISTIC`,
`CANONICAL_ONLY_METADATA`, `MISSING_CANONICAL`, `IDENTITY_MISMATCH`,
`NUMERIC_MISMATCH`, `DATE_MISMATCH`, `WRITE_ERROR`, `UNCLASSIFIED`.
