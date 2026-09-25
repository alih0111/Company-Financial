# INGESTION ARCHITECTURE — Phase 1

## 1. Target architecture

```
source adapter (Codal / BRS / TSETMC)
  -> raw capture        (raw.report_payloads or source observation payload)
  -> canonical parser/normalizer (one implementation, no drift)
  -> canonical PostgreSQL writer (core / ingestion / fundamentals / market)
       + SQL Server compatibility writer (temporary, authoritative during migration)
```

One canonical write boundary: `go-app/py2/src/canonical_ingest/`. Legacy scripts
remain authoritative and unchanged; they may invoke the canonical layer during
transition (dual-write) rather than keeping a second independent parser.

## 2. Python package layout (`go-app/py2/src/canonical_ingest/`)

| Module | Responsibility |
| --- | --- |
| `config.py` | ingestion mode (`legacy_only`/`dual_write`/`canonical_only`), canonical DSN + test-DB guard |
| `db.py` | explicit transaction/connection helpers |
| `identity.py` | company/security resolution via `legacy_entity_map`/`security_aliases`/`securities`; returns None (quarantine) instead of fabricating |
| `writer.py` | single idempotent canonical write layer (report, version, parse_run, raw payload, monthly, statements, facts, observations, quarantine) |
| `service.py` | high-level dual-write entrypoints with transaction + failure isolation |
| `reconcile.py` | legacy-vs-canonical classification |
| `__main__.py` | bounded dual-write sample runner + reconciliation CSV |

## 3. Canonical write chain

```
ingestion.reports (source, source_report_id UNIQUE; identity immutable)
  -> ingestion.report_versions (content_hash dedup; append-only)
  -> ingestion.parse_runs (completed run per version+parser; append-only identity)
  -> fundamentals.monthly_activities        (UNIQUE parse_run_id)
  -> fundamentals.financial_statements      (UNIQUE parse_run_id, statement_type)
  -> fundamentals.financial_facts           (UNIQUE statement_id, metric_code, period_order)
  -> market.price_observations              (UNIQUE security_id, trade_date, source, price_series, observation_hash)
  raw.report_payloads                       (UNIQUE report_version_id, payload_type, content_hash)
```

Contracts preserved: Company ≠ Security; UUID identity; `tsetmc_ins_code` on
Security; explicit legacy mapping; monetary = IRR (`numeric`); no Product1/2/3
facts; Gregorian business dates; `timestamptz` events; fetch/parse separation;
append-only lineage.

## 4. Ingestion mode

| Mode | Behavior |
| --- | --- |
| `LEGACY_ONLY` (default) | no canonical write; existing SQL Server path only |
| `DUAL_WRITE` | SQL Server write (authoritative, unchanged) + additive canonical write in one transaction; canonical failure isolated and recorded |
| `CANONICAL_ONLY` | reserved; must not be enabled in production this phase |

Selected via `CDF_INGESTION_MODE`.

## 5. Failure isolation

`dual_write_*` never raises: canonical errors roll back the canonical
transaction and return `status="canonical_error"`; the legacy transaction is
untouched (it already committed / runs independently). Unresolved identity
returns `status="quarantined"` and writes an
`ingestion.data_quality_issues` row. A canonical failure is never reported as
overall ingestion success.

## 6. Raw payload strategy

New Codal fetches store the original payload in `raw.report_payloads` (content
hash, size, mime, collected_at) before/alongside normalization. Historical raw
payloads are not fabricated. Market observations carry the source `collected_at`
and provenance so PIT reconstruction is possible.

## 7. Future (not this phase)

- Wire `py/brs_prices.py`, `py/MianSql*.py`, `py/sync_codal.py` to call
  `canonical_ingest` after their legacy write (guarded by mode).
- Reconcile the `py2` separate schema with canonical.
- Retire the duplicated `py2` models once the canonical writer is proven in all
  domains; keep a single parser per domain.
