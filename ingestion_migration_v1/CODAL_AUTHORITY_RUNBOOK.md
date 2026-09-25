# CODAL AUTHORITY RUNBOOK

## Enable canonical-primary (Codal only)

```powershell
$env:CDF_INGESTION_MODE          = "dual_write"
$env:CDF_CANONICAL_DB            = "company_financial_analytics_shadow_v121"
$env:CDF_CODAL_INGESTION_AUTHORITY = "canonical"
$env:CDF_CODAL_FALLBACK_LEGACY     = "true"
```

## Rollback (one flip)

```powershell
$env:CDF_CODAL_INGESTION_AUTHORITY = "legacy"
```

Restores legacy-authoritative + canonical secondary for Codal only. Config-only;
SQL Server retained.

## Verify

- `output/canonical_ingestion_status.json` (`domains.CODAL`).
- `output/codal_authority_freshness.json`, `codal_authority_cycles.csv`.
- per-batch stdout: `domain=CODAL authority=CANONICAL outcome=...`.

## Health / actions

| state | action |
| --- | --- |
| `HEALTHY` | none |
| `DEGRADED_LEGACY_MIRROR` | inspect legacy registry mirror |
| `CANONICAL_BEHIND` | replay pending `codal_report` retries |
| `CANONICAL_ERROR` | check DSN/PG; fallback; replay |
| `IDENTITY_QUARANTINE` | classify (out-of-scope/fund vs alias-mapping); no fabrication |
| `PARSER_FAILED` | inspect parse run; canonical transaction rolled back |

## Retry

Shared `canonical_retry_manifest.jsonl` (`domain=codal_report`, `keys.source_report_id`).
Replay re-fetches/uses stored raw and writes canonical-only; idempotent by
content hash.

## Do not

- use company names as report identity;
- fabricate identifiers or historical raw payloads;
- remove SQL Server compatibility.
