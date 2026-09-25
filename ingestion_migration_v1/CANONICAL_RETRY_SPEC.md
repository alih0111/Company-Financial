# CANONICAL RETRY SPEC — Phase 3

## 1. Goal

A canonical-side failure during `DUAL_WRITE` must be recoverable without
rerunning destructive legacy work. Legacy already succeeded and is authoritative;
only the canonical mirror needs replay.

## 2. Mechanism (file-based, deterministic)

On any canonical failure the hook appends one JSON line to
`ingestion_migration_v1/output/canonical_retry_manifest.jsonl`:

```json
{"status":"pending","domain":"monthly_activity",
 "keys":{"legacy_company_id":"...","report_date":"1405/06/31"},
 "error":"...","detected_at":"2026-09-25T18:26:26+03:30"}
```

Domains and keys:
- `market_price`: `{"companies":[...]}` (re-read those companies' recent rows)
- `monthly_activity`: `{"legacy_company_id","report_date"}`
- `financial_statement`: `{"legacy_company_id","report_date"}`
- `codal_report`: `{"source_report_id"}` (TracingNo)

This is emitted for hook exceptions **and** for returned `canonical_error`
status (so a disallowed/unavailable DB still produces a retry entry, verified in
`phase2_failure_injection.json` / the manifest).

## 3. Replay

A retry worker processes pending lines by re-invoking the same canonical write
for the recorded keys, **without** touching SQL Server:

1. read pending entries (optionally filter by domain),
2. re-resolve identity via `canonical_ingest.identity`,
3. re-run the idempotent canonical write,
4. mark the entry `done` (or `failed` with the new error) by appending an
   updated line (append-only manifest).

Because every canonical write is idempotent (content hash, natural-key lookup,
logical (company, period) dedup), replay is safe and cannot create duplicates.

## 4. Non-goals

- No distributed transaction with SQL Server.
- No automatic rerun of legacy scrapers to repair canonical.
- No permanent audit platform; this is a bounded, file-based recovery path.

## 5. Cutover requirement

A working retry manifest (present) is a prerequisite for canonical-authoritative
promotion: any canonical gap must be replayable from the recorded keys alone.
