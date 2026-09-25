# PYTHON MIGRATION MATRIX — Phase 1

Phase 1 does **not** migrate Python ingestion writes. Legacy Python behavior is
untouched. This document records what exists and the intended phase for each
dependency.

## 1. Go → Python invocation map

| Go site | Command | Script | Disposition |
| --- | --- | --- | --- |
| `handlers/run_script.go` | `python py/scraper.py …` | `py/scraper.py` → `MianSql` (miandore2) | **A. remain legacy** (Phase 3 ingestion) |
| `handlers/run_script2.go` | `python py/scraper2.py …` | `py/scraper2.py` → `MianSql2` (mahane) | **A. remain legacy** |
| `handlers/full_run_scripts.go` | `python py/scraper.py|scraper2.py` | bulk | **A. remain legacy** |
| `handlers/run_script_pe.go` | `python py/scraperFullPE.py` | `scraperFullPE.py` (FullPE) | **A. remain legacy** |
| `handlers/brs_prices.go` | `python py/brs_prices.py …` | price collector | **A. remain legacy** |
| `handlers/sync_codal.go` | `python py/sync_codal.py …` | Codal discovery/sync | **A. remain legacy** |
| `Stock/go/main.go` | `python …/import_facts.py` | separate module | **OUT_OF_SCOPE** |

None of these are read/analytics calls that could be cleanly replaced by a
canonical read in Phase 1. They are ingestion **write** paths and stay on SQL
Server.

## 2. Python scripts and PostgreSQL

| Script group | DB | Read/Write | Phase |
| --- | --- | --- | --- |
| `py/MianSql.py`, `MianSql2.py`, `codal_*.py`, `codal_processor.py` | SQL Server | write | Phase 3 (ingestion migration) |
| `py/brs_prices.py`, `price.py` | SQL Server | write | Phase 3 |
| `py/scraperFullPE.py` | SQL Server | write | Phase 3 |
| `py/family_import.py`, `backfill_history.py`, `_backfill_v32.py`, `_apply_view.py` | SQL Server | write | Phase 3 |
| `py/backtest*.py` | SQL Server | read-only, file output | Phase 2/3 analytics consumer |
| `py2/src/codal_ingestor/*` | **PostgreSQL** (own `companies`…`financial_facts`) | write | Separate stack — Phase 3 decision |
| `py2/scraper.py`, `scraper2.py` | PostgreSQL (via py2) | write | Not Go-invoked; Phase 3 |
| `py/tests/*`, `py2/tests/*` | none | tests | unchanged |

## 3. Shared canonical PostgreSQL configuration

The application runtime does not require Python to read canonical PostgreSQL in
Phase 1: Go consumes canonical directly through `integration.PG`. The canonical
connection contract is therefore documented once (see
`SHADOW_INTEGRATION_SPEC.md` §2) and is shared by convention:

- `DATABASE_URL` (SQLAlchemy form, `+psycopg` stripped by Go),
- `CDF_CANONICAL_DB` / `CDF_PILOT_DB` override,
- test/shadow database prefix guard.

No Python file was modified to add PostgreSQL reads, avoiding an unused
`psycopg` dependency on the legacy `py/` stack. If a future runtime tool needs
canonical reads, it should reuse the same env contract and a read-only session.

## 4. Notes / risks found (not fixed in Phase 1)

- `py/scraperFullPE.py` writes via a hard-coded local connection
  (`Trusted_Connection=yes`) while reading via env credentials. Flagged for the
  ingestion phase.
- `py2` schema can be created by both `Base.metadata.create_all` and Alembic,
  which can drift. Not touched.
- `py2` is a **separate ingestion stack**, not the Go application path; do not
  conflate it with canonical application reads.
- Hard-coded Chromium paths in `MianSql.py`/`MianSql2.py`/`price.py` remain.

## 5. Phase 2/3 criteria (future)

- Phase 2: expand application **read** integration (fundamentals, report URLs,
  export) to canonical repositories.
- Phase 3: design ingestion **write** migration from SQL Server to canonical,
  including `py2` reconciliation, with idempotency/rollback — designed separately.
