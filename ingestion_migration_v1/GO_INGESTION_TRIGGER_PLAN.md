# GO INGESTION TRIGGER PLAN

The six Go `os/exec` ingestion triggers are **unchanged** in Phase 1. This
document records how each will eventually invoke the canonical ingestion
entrypoint.

| Go handler | Current command | Domain | Future canonical path | Readiness | Blocking dependency |
| --- | --- | --- | --- | --- | --- |
| `handlers/run_script.go` (`/api/run-script`) | `python py/scraper.py …` | FINANCIAL_STATEMENT | `scraper.py` keeps legacy write, then calls `canonical_ingest.dual_write_financial` | partial | wire hook into `MianSql` after insert; mode flag |
| `handlers/run_script2.go` (`/api/run-script2`) | `python py/scraper2.py …` | MONTHLY_ACTIVITY | `scraper2.py` keeps legacy write, then `dual_write_monthly` | partial | wire hook into `MianSql2`; mode flag |
| `handlers/full_run_scripts.go` (`/api/fetchAllData`) | `python py/scraper.py`/`scraper2.py` per company | FINANCIAL + MONTHLY | same hooks as above | partial | per-company hook + batch reconciliation |
| `handlers/run_script_pe.go` (`/api/FetchFullPE`) | `python py/scraperFullPE.py` | OTHER (FullPE heuristic) | none (legacy heuristic; no canonical metric) | blocked | none — intentionally not migrated |
| `handlers/brs_prices.go` (`/api/brs/collect`) | `python py/brs_prices.py …` | MARKET_PRICE | `brs_prices.py` keeps legacy write, then `dual_write_market` with source `collected_at` | partial | wire hook into price collector; mode flag |
| `handlers/sync_codal.go` (`/api/sync-codal`) | `python py/sync_codal.py …` | CODAL_REPORT (+ downstream) | `sync_codal.py` writes registry + raw payload, then canonical report chain | partial | map Codal TracingNo → `source_report_id`; raw payload capture |

## Strategy

- Do **not** rewrite the Go handlers. They keep invoking the existing Python
  scripts.
- The canonical routing lives inside the Python scripts, gated by
  `CDF_INGESTION_MODE`, so Go needs no change and the default remains
  `LEGACY_ONLY`.
- A later phase may add an explicit canonical entrypoint (e.g.
  `python -m canonical_ingest --from-legacy-run <id>`) invoked after a legacy
  batch, so the Go layer stays transport-only.
- `FetchFullPE` is intentionally excluded (legacy heuristic, no canonical
  equivalent).

## Migration readiness summary

- MARKET_PRICE: **wired** into `py/brs_prices.py` (post-commit hook); real BRS
  batch dual-written and idempotent.
- MONTHLY_ACTIVITY: **wired** into `py/MianSql2.py` post-commit hook.
- FINANCIAL_STATEMENT: **wired** into `py/MianSql.py` post-commit hook (both
  success paths).
- CODAL_REPORT: writer implemented; TracingNo mapping and raw capture wiring
  remain (Phase 3).
- **No Go trigger changes** were required or made; scripts are dual-write
  capable via `CDF_INGESTION_MODE`, so Go/API behavior is unchanged.

Go continues to invoke the same scripts. To enable dual-write, set
`CDF_INGESTION_MODE=DUAL_WRITE` for the ingestion interpreter (which must have
`psycopg` and a canonical DSN).
