# FINANCIAL AUTHORITY RUNBOOK

## Enable canonical-primary (financial only)

```powershell
$env:CDF_INGESTION_MODE                = "dual_write"
$env:CDF_CANONICAL_DB                  = "company_financial_analytics_shadow_v121"
$env:CDF_FINANCIAL_INGESTION_AUTHORITY = "canonical"
$env:CDF_FINANCIAL_FALLBACK_LEGACY     = "true"
```

## Rollback (one flip)

```powershell
$env:CDF_FINANCIAL_INGESTION_AUTHORITY = "legacy"
```

Restores legacy-authoritative + canonical secondary for financial only.
Config-only; `miandore2`, pyodbc, legacy code and config are retained.

## Verify

- `output/financial_authority_freshness.json` (authority/health/backlog/quarantine).
- `output/financial_authority_cycles.csv`, `financial_authority_summary.json`.
- per-batch stdout: `domain=FINANCIAL_STATEMENT authority=CANONICAL outcome=...`.

## Health / actions

| state | action |
| --- | --- |
| `HEALTHY` | none |
| `DEGRADED_LEGACY_MIRROR` | inspect SQL Server mirror; canonical truth intact |
| `CANONICAL_BEHIND` | replay pending financial retries (shared manifest) |
| `CANONICAL_ERROR` | check DSN/PG; fallback keeps continuity; replay retry |
| `IDENTITY_QUARANTINE` | review DQ rows; alias mapping decision (no fabrication) |
| `PARSER_ERROR` | inspect parser run; canonical transaction rolled back |

## Retry

Shared `output/canonical_retry_manifest.jsonl` (`domain=financial_statement`).
Replay re-reads the legacy `miandore2` row, writes canonical-only, marks done.
Idempotent; no destructive legacy re-ingestion.

## Do not

- promote CODAL;
- remove SQL Server / legacy financial write code;
- enable `CANONICAL_ONLY` globally.
