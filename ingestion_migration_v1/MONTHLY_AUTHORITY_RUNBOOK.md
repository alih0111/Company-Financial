# MONTHLY AUTHORITY RUNBOOK

## Enable canonical-primary (monthly only)

```powershell
$env:CDF_INGESTION_MODE              = "dual_write"
$env:CDF_CANONICAL_DB                = "company_financial_analytics_shadow_v121"
$env:CDF_MONTHLY_INGESTION_AUTHORITY = "canonical"
$env:CDF_MONTHLY_FALLBACK_LEGACY     = "true"
```

## Rollback (one flip)

```powershell
$env:CDF_MONTHLY_INGESTION_AUTHORITY = "legacy"
```

Restores legacy-authoritative + canonical secondary for monthly only.
Config-only; SQL Server retained.

## Verify

- `output/monthly_authority_freshness.json` (authority/health/backlog/quarantine).
- `output/monthly_authority_cycles.csv`, `monthly_authority_summary.json`.
- per-batch stdout: `domain=MONTHLY_ACTIVITY authority=CANONICAL outcome=...`.

## Health / actions

| state | action |
| --- | --- |
| `HEALTHY` | none |
| `DEGRADED_LEGACY_MIRROR` | inspect SQL Server mirror; canonical truth intact |
| `CANONICAL_BEHIND` | run `drivers/retry_monthly` (replay pending monthly retries) |
| `CANONICAL_ERROR` | check DSN/PG; fallback keeps continuity; replay retry |
| `IDENTITY_QUARANTINE` | review `ingestion.data_quality_issues` (no fabrication) |

## Retry

Same retry system (`output/canonical_retry_manifest.jsonl`, `domain=monthly_activity`).
Replay re-reads the legacy `mahane` row and writes canonical-only; idempotent, no
destructive legacy replay.

## Do not

- do not promote FINANCIAL_STATEMENT or change CODAL;
- do not remove SQL Server;
- do not enable `CANONICAL_ONLY` globally.
