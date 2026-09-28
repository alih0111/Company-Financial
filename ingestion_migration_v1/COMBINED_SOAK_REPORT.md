# COMBINED INGESTION SOAK REPORT

**Gate: `CANONICAL_INGESTION_COMBINED_SOAK_PASS`**

- Generated: 2026-09-25T17:12:00Z
- Mode: `dual_write`
- Canonical DB: `company_financial_analytics_shadow_v121` (schema 1.2.1)
- Harness: `ingestion_migration_v1/drivers/run_combined_soak.py`
- Cycles: 3 (all four domains exercised per cycle, in one process)
- Machine-readable: `output/combined_ingestion_soak.csv`, `output/combined_ingestion_soak.json`,
  `output/combined_soak_table_counts.csv`, `output/canonical_ingestion_status.json`

This is an operational soak of the already-completed ingestion layer. No migration,
schema change or redesign was performed. SQL Server was used read-only as the
reconcile/reference source; canonical writes went only through the approved
`go-app/py2/src/canonical_ingest` writer via `go-app/py/canonical_hook.py`.

## Domain authority (re-asserted live)

All four authority flags were set to `canonical` for the soak and asserted by the
harness before any write:

| Domain | Authority | Retry backlog | Quarantine | Health |
| --- | --- | --- | --- | --- |
| MARKET_PRICE | CANONICAL | 0 | 0 | HEALTHY |
| MONTHLY_ACTIVITY | CANONICAL | 0 | 18 | HEALTHY |
| FINANCIAL_STATEMENT | CANONICAL | 0 | 24 | HEALTHY |
| CODAL | CANONICAL | 0 | 28 | HEALTHY |

Quarantine counts are classified identity conflicts only; no canonical entity was
fabricated to reduce them (`ingestion.data_quality_issues`, `issue_code='identity_conflict'`).

## Reconciliation (canonical vs legacy source, read-only)

| Domain | Classifications |
| --- | --- |
| MARKET_PRICE | `EXACT_EQUIVALENT=5` |
| MONTHLY_ACTIVITY | `EXPECTED_UNIT_CONVERSION=4` |
| FINANCIAL_STATEMENT | `EXACT_EQUIVALENT=40`, `EXPECTED_UNIT_CONVERSION=127` |
| CODAL | controlled-semantics invariants (below) |

**Unexplained mismatches: 0.** `EXPECTED_UNIT_CONVERSION` is the documented
million-IRR (reported) vs IRR (canonical) presentation difference, not a defect.

## Idempotency

`total_inserted = 0` across all three cycles: every replayed source row was
recognised as already-canonical and skipped. Table counts were constant across
cycles for all append-only fact tables (see `combined_soak_table_counts.csv`).

## CODAL lineage invariants (DB-verified)

Each controlled `source_report_id` yields:

| Invariant | Value |
| --- | --- |
| report_versions | 2 (v1, v2) |
| max version_no | 2 |
| parse_runs | 3 (parser rerun creates a parse run, not a version) |
| raw payloads | 2 (content-hash dedup) |
| identical content → new version | 0 |
| changed content → new version | 1 |
| parser rerun → new parse_run, no new version | true |
| partial / in-progress parse runs | 0 |

Live Codal feed was reachable (`network=ok`): 5 letters/cycle, all classified
quarantine (`EXPECTED_SCOPE_EXCLUSION` / `ALIAS_MAPPING_REQUIRED`), zero writes,
zero fabricated entities. This satisfies "do not require a genuinely new source
event in every domain".

## Freshness

| Domain | Latest canonical | Rows |
| --- | --- | --- |
| MARKET_PRICE | collected 2026-09-25 19:25 +03:30 / trade_date 2026-09-25 | 706,058 |
| MONTHLY_ACTIVITY | period 2026-09-22 | 12,075 |
| FINANCIAL_STATEMENT | period 2026-08-22 / write 2026-09-25 | 71,361 facts |
| CODAL | latest report write 2026-09-25 20:41 +03:30 | 19,009 reports |

## Cross-domain interference

- `analytics.score_runs` unchanged (4 → 4): ingestion did **not** silently refresh
  analytics. New canonical data does not imply a fresh score run.
- `ingestion.parse_runs` non-decreasing, **0 partial** runs.
- All tracked table counts non-decreasing; deltas confined to
  `ingestion.reports (+3)` and `ingestion.parse_runs (+9)` from the codal
  controlled-semantics probes. No fact-table churn.

## Mirror / SQL Server status

Domain health is `HEALTHY`. `legacy_mirror_status` is `not_attempted` in this
harness because the real legacy scripts already write SQL Server first and the
soak deliberately avoided redundant mirror writes. Mirror correctness is instead
evidenced by the read-side reconciliation above (canonical equals the SQL Server
source for every compared row). SQL Server remains retained as mirror/fallback/
rollback and was **not** modified or deleted.

## Result

`CANONICAL_INGESTION_COMBINED_SOAK_PASS` — the ingestion layer is structurally
complete under a single combined operational cycle with no unexplained mismatch,
no partial writes, no cross-domain interference and no retry backlog. Broad Go
canonical read migration may proceed.
