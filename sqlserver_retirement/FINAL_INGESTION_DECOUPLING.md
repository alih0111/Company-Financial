# FINAL INGESTION DECOUPLING

Goal achieved: all four real ingestion entrypoints run with SQL Server
completely unreachable. Gate: **`SQLSERVER_CAN_BE_STOPPED`** (STAGE_3).

Executable proof: `prove_real_ingestion_offline.py` →
`output/real_ingestion_offline_proof.csv`; Go-trigger →
`output/go_trigger_offline_proof.csv`; final state →
`output/sqlserver_retirement_final.json`.

## Canonical-first order (authority=canonical)

```
source fetch -> parse/normalize in memory -> canonical PostgreSQL write -> optional SQL mirror
```

The legacy SQL-first order is preserved only when authority=legacy (rollback).

## Mode helpers (`go-app/py/canonical_hook.py`)

- `sqlserver_mode()` → `active | fallback | offline_expected`.
- `sql_connection_required()` — false for canonical authority under
  `offline_expected`.
- `canonical_only_offline()` — canonical must proceed with no SQL Server.
- `resolve_legacy_key(name|symbol|ins_code)` — canonical-only identity resolution
  (PostgreSQL `core.legacy_entity_map` + aliases); no SQL Server.
- `facts_from_values(...)` — one normalized in-memory fact set (ps → rial_per_share,
  money → million_rial input / rial canonical) feeding both canonical and mirror.

## Per-script changes

| Script | Change | Offline result |
| --- | --- | --- |
| `py/brs_prices.py` | `resolve_matched_symbols_canonical`, `_persist_market_canonical_only`; `cmd_daily`/`cmd_backfill_raw` canonical-only branches that never call `get_db_connection` | `cmd_daily`: canonical inserted 269 (real BRS), no pyodbc |
| `py/MianSql2.py` | `save_report_to_sql` canonical-only branch writes canonical from `calculated_values` before any SQL connection | EXECUTED, no pyodbc |
| `py/MianSql.py` | `save_profit_loss_to_sql` canonical-only branch builds `facts_from_values(...)` from parsed params and calls the hook with `facts=`; `_facts_from_db` retains only the rollback path | EXECUTED, in-memory facts, no pyodbc |
| `py/sync_codal.py` | `run_sync_canonical_only`; `run_sync` short-circuits to it when canonical-only. `TracingNo → source_report_id` unchanged | scanned 20, quarantined 20, 0 errors, no pyodbc |

## Lazy SQL connection

Connections are function-scoped (`get_db_connection`). No module-level
connection is created. Canonical-only branches never call it, so
`CDF_SQLSERVER_MODE=offline_expected` is non-fatal and non-noisy.

## Mirror-failure vs canonical-retry

- Mirror failure → `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`; **no** canonical
  retry enqueued (proven by `test_canonical_hook_offline.py`).
- Canonical PostgreSQL failure → `CANONICAL_FAILED`; canonical retry enqueued.

## No SQL transport

Financial/monthly canonical values come directly from the parser's normalized
representation; SQL Server is never re-read on the canonical-primary path.

## Remaining SQL references (all non-blocking)

`MIRROR_ONLY`, `ROLLBACK_ONLY`, `MIGRATION_ONLY`, `TEST_ONLY`, `DEPRECATED`, and
explicit `ACTIVE_OPTIONAL` (GetUrl/GetUrl2, admin triggers, viewed-items; family
deferred). Static scan: **0 CRITICAL_SHUTDOWN_BLOCKER, 0 ACTIVE_FEATURE_BLOCKER**.
