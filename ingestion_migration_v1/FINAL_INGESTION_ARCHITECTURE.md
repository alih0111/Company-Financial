# FINAL INGESTION ARCHITECTURE

## Target (unambiguous)

```
Codal / BRS / TSETMC
  -> source adapters
  -> raw capture            (raw.report_payloads for reports; source metadata for prices)
  -> canonical identity resolution   (core.companies / core.securities / aliases / legacy_entity_map)
  -> canonical normalizer   (one implementation; no competing semantics)
  -> PostgreSQL canonical   (core / ingestion / raw / fundamentals / market)
  -> analytics              (versioned, PIT/as_of)
```

SQL Server is **transitional compatibility/mirror only**. The approved PostgreSQL
writer is `canonical_ingest` against `canonical_postgres_v1_2_1`.

## Domain authority (as of this phase)

| Domain | Destination | Authority | Mirror/rollback |
| --- | --- | --- | --- |
| MARKET_PRICE | `market.price_observations` | CANONICAL | SQL Server mirror; `CDF_MARKET_INGESTION_AUTHORITY=legacy` rollback |
| MONTHLY_ACTIVITY | `fundamentals.monthly_activities` | CANONICAL | SQL Server mirror; `CDF_MONTHLY_INGESTION_AUTHORITY=legacy` |
| FINANCIAL_STATEMENT | `fundamentals.financial_statements` + `financial_facts` | CANONICAL | SQL Server mirror; `CDF_FINANCIAL_INGESTION_AUTHORITY=legacy` |
| CODAL | `ingestion.*` + `raw.report_payloads` | CANONICAL | legacy registry mirror; `CDF_CODAL_INGESTION_AUTHORITY=legacy` |

Global `CDF_INGESTION_MODE` (`legacy_only` default / `dual_write` /
`canonical_only`) gates canonical writes; per-domain authority flags select the
authoritative destination.

## Contracts preserved

Company ≠ Security; UUID identity; `tsetmc_ins_code` on Security; explicit legacy
mapping; monetary IRR (`numeric`); EPS `rial_per_share`; no Product1/2/3,
NPUnitRatio, OpK, OpAmt; Gregorian business dates; `timestamptz` events;
report/version/parse separation; append-only lineage; actual source
`collected_at`.

## py2 status

- `canonical_ingest` = **CANONICAL_V121_COMPATIBLE** (the only approved canonical writer).
- `codal_ingestor` (models/repository/Alembic) = **CONFLICTING_SCHEMA**, now
  carrying a deprecation guard; not used by any canonical path; not deleted.

## Operational guarantees

- Canonical writes idempotent (content hash, natural-key, logical dedup).
- Failures isolated and recorded; shared retry manifest per domain for
  canonical-only replay.
- Freshness/status observable per domain (`canonical_ingestion_status.json`).
- Rollback is a single config flip per domain; SQL Server never deleted in this
  program.
