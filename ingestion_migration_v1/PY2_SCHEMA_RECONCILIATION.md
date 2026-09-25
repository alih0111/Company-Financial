# PY2 SCHEMA RECONCILIATION

Audit of `go-app/py2/` versus canonical v1.2.1. Nothing was deleted. Newly wired
ingestion uses only the canonical v1.2.1 schema/contracts.

## 1. Classification

| Path | Classification | Note |
| --- | --- | --- |
| `src/canonical_ingest/*` | **CANONICAL_V121_COMPATIBLE** | the only canonical writer; used by Phase-2 hooks |
| `src/codal_ingestor/models.py` | **CONFLICTING_SCHEMA** | defines `companies`/`reports`/`report_versions`/`monthly_activities`/`financial_facts` in a separate non-canonical schema |
| `src/codal_ingestor/repository.py` | **CONFLICTING_SCHEMA** | writes those tables with its own upsert/delete semantics |
| `alembic/versions/0001_initial.py` | **CONFLICTING_SCHEMA** | creates the separate schema |
| `src/codal_ingestor/db.py` | REUSABLE_UTILITY | engine/session pattern; superseded by `canonical_ingest.db` |
| `src/codal_ingestor/config.py` | REUSABLE_UTILITY | env/pydantic patterns |
| `src/codal_ingestor/domain.py` | REUSABLE_UTILITY | Jawali→Gregorian, Persian normalization, decimal, content hash |
| `src/codal_ingestor/collectors/*`, `parsers/*` | REUSABLE_UTILITY | HTML parsing (potential Phase-3 canonical parser core) |
| `src/codal_ingestor/runner.py`, `cli.py` | DEPRECATED_BY_CANONICAL_V121 | not invoked by Go; superseded by the canonical path |
| `py2/scraper.py`, `py2/scraper2.py` | DEPRECATED_BY_CANONICAL_V121 | Go-compat wrappers; Go still uses `py/` |
| `tests/test_domain.py` | REUSABLE_UTILITY | pure domain tests |
| `.runtime/`, `.venv/`, caches | UNUSED | local artifacts |

## 2. Decision

- `canonical_ingest` is the single canonical writer for all newly wired ingestion.
- The `codal_ingestor` models/repository/alembic are **not** used by any
  Phase-2 path and must not gain new canonical responsibilities.
- Keep a single parser per domain: reuse `codal_ingestor` parsing utilities only
  if they are later refactored to emit canonical payloads; do not run two
  independent writers.
- No deletion in this phase; a later phase may retire the separate schema once
  canonical-only ingestion is approved.

## 3. Guarantee

All Phase-2 dual-write and tests target `core`/`ingestion`/`raw`/`fundamentals`/
`market` (v1.2.1). The separate `codal_ingestor` schema is not written by any
wired path.
