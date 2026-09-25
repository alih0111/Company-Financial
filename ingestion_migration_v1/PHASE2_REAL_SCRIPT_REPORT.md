# PHASE 2 — REAL SCRIPT DUAL-WRITE REPORT

Wired the actual legacy ingestion scripts to the canonical writer via a single
hook, and validated against live SQL Server + the designated shadow PostgreSQL.
No cutover; default remains `LEGACY_ONLY`.

## 1. Scripts wired

| Script | Hook point | Domain | Canonical call |
| --- | --- | --- | --- |
| `py/brs_prices.py` | after `conn.commit()` in `cmd_daily` and `cmd_backfill_raw` | MARKET_PRICE | `canonical_hook.dual_write_market_rows` |
| `py/MianSql2.py` | after `conn.commit()` in `save_report_to_sql` | MONTHLY_ACTIVITY | `canonical_hook.dual_write_monthly_values` |
| `py/MianSql.py` | after `conn.commit()` in both success paths of `save_profit_loss_to_sql` | FINANCIAL_STATEMENT | `canonical_hook.dual_write_financial_by_key` |

Shared hook: `go-app/py/canonical_hook.py` (lazy-imports
`go-app/py2/src/canonical_ingest`; imports nothing canonical in `LEGACY_ONLY`;
never raises into the caller). Go triggers unchanged; scripts are dual-write
capable purely via `CDF_INGESTION_MODE`.

## 2. Mode contract

`LEGACY_ONLY` (default) → hook returns immediately, **zero PostgreSQL work**
(verified: counts unchanged). `DUAL_WRITE` → additive canonical write after
legacy commit. `CANONICAL_ONLY` → code path present, not the default.

## 3. Real batches executed

Driver `ingestion_migration_v1/drivers/run_phase2_batches.py` uses the real
`brs_prices.resolve_matched_symbols` / `build_daily_row` / `upsert_rows` (live BRS
fetch, 1,608 symbols) and the real hook functions for monthly/financial with
real legacy keys.

| Domain | Legacy rows | Run 1 canonical | Run 2 canonical |
| --- | --- | --- | --- |
| market_price (کیمیا، غاذر، سباقر، دقاضی) | 4 | inserted **4**, skipped 0 | inserted **0**, skipped 4 |
| monthly_activity (قاسم) | 1 | written, inserted 0, skipped 4 | written, inserted 0, skipped 4 |
| financial_statement (تاصیکو) | 25 facts | written, inserted 0, skipped 28 | written, inserted 0, skipped 28 |
| financial_statement (کسرا) | 25 facts | written, inserted 0, skipped 28 | written, inserted 0, skipped 28 |

Second-run inserts: **0** across all domains → idempotent
(`phase2_idempotency.json`).

## 4. Reconciliation

`EXACT_EQUIVALENT` 14, `EXPECTED_UNIT_CONVERSION` 41; **MISSING_CANONICAL /
IDENTITY_MISMATCH / NUMERIC_MISMATCH / DATE_MISMATCH / WRITE_ERROR /
UNCLASSIFIED = 0** (`phase2_reconciliation.csv`, `phase2_summary.json`).

## 5. Market hash contract

Resolved via a stable new-write hash plus a natural-key compatibility lookup; no
historical rewrite. Details: `MARKET_HASH_CONTRACT.md`.

## 6. Failure injection (real hook)

| Scenario | Result |
| --- | --- |
| `LEGACY_ONLY` | `skipped_legacy_only`; canonical counts unchanged (zero writes) |
| Unresolved identity | `quarantined` (DQ row; no fake company) |
| PostgreSQL unavailable / disallowed DB | `canonical_error`; legacy untouched |

`phase2_failure_injection.json`.

## 7. Guardrails

- No `Product1/2/3`/`NPUnitRatio`/`OpK`/`OpAmt` in canonical facts (asserted in
  the hook and covered by tests).
- Identity only via `canonical_ingest.identity`; no name-based identity in
  scripts, no fake entities.
- Market `collected_at` = actual collection time (`now` +03:30) for new fetches,
  never migration time.
- Legacy SQL Server write paths unchanged; canonical write is a separate
  transaction (no distributed coupling).

## 8. Codal status

`canonical_ingest` supports the report → report_version → parse_run → raw
payload chain; live `sync_codal.py` wiring (TracingNo mapping + raw capture) is
deferred to keep market/monthly/financial readiness unblocked.

## 9. Artifacts

`output/phase2_real_batches.csv`, `output/phase2_reconciliation.csv`,
`output/phase2_idempotency.json`, `output/phase2_summary.json`,
`output/phase2_failure_injection.json`; plus `MARKET_HASH_CONTRACT.md`,
`PY2_SCHEMA_RECONCILIATION.md`.
