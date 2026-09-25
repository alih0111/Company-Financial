# CODAL AUTHORITY REPORT (Part B)

Codal lineage promoted to canonical-authoritative (shadow), reversible. Part A
financial soak passed first. SQL Server retained.

## 1. Configuration

`CDF_CODAL_INGESTION_AUTHORITY=canonical`, `CDF_CODAL_FALLBACK_LEGACY=true`,
`CDF_INGESTION_MODE=dual_write`. Source identity = Codal `TracingNo`.

## 2. Real Codal reports processed

5 live letters fetched (`LetterType=6`). All **quarantined** (classified):
outer universe/funds → `EXPECTED_SCOPE_EXCLUSION`; known tracked symbols →
`ALIAS_MAPPING_REQUIRED`. No fabrication. `codal_authority_cycles.csv`.

## 3. Raw payload behavior

New fetches store the real body in `raw.report_payloads` (content hash, mime,
byte size, URL, collected_at). Controlled proof: 2 versions → 2 raw payloads
(identical content stored once). No session/browser secrets; no historical
fabrication.

## 4. Version / parse behavior

- identical content re-fetch → `inserted=0` (no new report_version)
- changed content → new `report_version` (max version_no 2)
- parser rerun → new `parse_run`, versions stay 2
- `parser_rerun_new_parse_run_no_new_version=true`

## 5. Correction / supersession

Controlled corrected report (distinct TracingNo) with
`supersedes_source_report_id` → `supersession_linked=true` (new report
`supersedes_report_id` = old report id); old version preserved, new version
preserved; PIT can distinguish availability. No deletion.

## 6. Normalized data written

Codal lineage writes reports/versions/parse_runs/raw. Normalized monthly/financial
outputs remain canonical via the shared `canonical_ingest` writer (proven in
Parts A and prior phases) — no competing normalization semantics.

## 7. Quarantine / retry / freshness

Quarantines classified; shared retry manifest (`domain=codal_report`) with keys =
`source_report_id`; `codal_authority_freshness.json` +
`canonical_ingestion_status.json` (all domains HEALTHY, backlog 0).

## 8. End-to-end canonical proof

Chain proven: Codal source → raw (`raw.report_payloads`) → `ingestion.reports`
(TracingNo) → `report_versions` (content hash) → `parse_runs`; normalized
market/monthly/financial data is canonical and reaches Go reads
(`cmd/shadowcheck` 0 unexpected) and analytics (`fundamentals.*` visible,
score runs untouched). Live letters quarantine by identity as designed.

## 9. Gate

**`CODAL_CANONICAL_AUTHORITY_READY`** (live identity coverage is a scope/alias
matter, not a lineage defect; path itself is canonical-authoritative).
