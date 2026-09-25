# CODAL AUTHORITY SPEC — canonical-authoritative Codal lineage

## 1. Scope

CODAL source/raw/report/version/parse path. MARKET/MONTHLY/FINANCIAL remain
canonical-primary. No global-mode change.

## 2. Configuration

| Env | Values | Default |
| --- | --- | --- |
| `CDF_CODAL_INGESTION_AUTHORITY` | `legacy` \| `canonical` | `legacy` |
| `CDF_CODAL_FALLBACK_LEGACY` | `true` \| `false` | `true` |

## 3. Flow / semantics

```
Codal fetch -> raw.report_payloads (content hash, url, mime, byte size, collected_at)
  -> ingestion.reports (source_report_id = TracingNo)
  -> ingestion.report_versions (content-hash versioning)
  -> ingestion.parse_runs (parser execution)
  -> canonical normalized outputs (reuse canonical_ingest; no competing writer)
```

Outcomes: `CANONICAL_SUCCESS_LEGACY_SUCCESS`,
`CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`, `CANONICAL_FAILED_LEGACY_FALLBACK_USED`,
`CANONICAL_FAILED`, `QUARANTINED_IDENTITY`, `PARSER_FAILED`.

## 4. Identity / raw / versioning

Identity via `canonical_ingest.identity`; unresolved → quarantine (classified),
no fabrication. Raw-first capture for new fetches (no historical fabrication, no
session secrets). `report = logical source`, `report_version = content`,
`parse_run = parser execution`; identical content → same version, changed content
→ new version, parser rerun → new parse_run (no fake version), corrections use
`supersedes_report_id`.

## 5. Timestamps

`collected_at`/`published_at` reflect actual source/fetch availability; no
migration-time assignment for new history.

## 6. Retry / freshness

Shared retry manifest (`domain=codal_report`, keys = source_report_id).
`output/canonical_ingestion_status.json` and `codal_authority_freshness.json`
report authority/latest/backlog/quarantine/health per domain.

## 7. Rollback (one flip)

`CDF_CODAL_INGESTION_AUTHORITY=legacy` — legacy-authoritative + canonical
secondary. Config-only; SQL Server retained.
