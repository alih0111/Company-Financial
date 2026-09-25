# MONTHLY AUTHORITY FAILURE MATRIX

No distributed transaction. Canonical PostgreSQL is authoritative; SQL Server is
a mirror.

| # | Case | Authoritative state | Recovery | Retry | Duplicate prevention |
| --- | --- | --- | --- | --- | --- |
| 1 | canonical committed / legacy mirror failed | canonical (correct) | outcome `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`; health `DEGRADED_LEGACY_MIRROR`; re-mirror | mirror-only | canonical logical `(company, period)` dedup + `ON CONFLICT (parse_run_id)` |
| 2 | canonical failed / legacy fallback succeeds | legacy continuity only; domain NOT caught up | `CANONICAL_FAILED_LEGACY_FALLBACK_USED`; retry queued; health `CANONICAL_ERROR`/`CANONICAL_BEHIND` | replay via retry manifest (canonical-only) | canonical dedup; legacy `(CompanyID, ReportDate)` check |
| 3 | unresolved identity | neither fabricated; legacy row may exist | `quarantined` + DQ row; health `IDENTITY_QUARANTINE` | operator alias-mapping decision, then replay | no fake entity; identity via `legacy_entity_map`/aliases |
| 4 | duplicate / retry | canonical idempotent | second run inserts 0 | replay same keys | `find_monthly_activity(company, period)` + parse_run uniqueness |
| 5 | process crash between canonical and mirror | canonical | next cycle or manual re-mirror | none needed for canonical | canonical dedup; mirror upsert idempotent |
| 6 | reconciliation failure | canonical retained; flagged | investigate classification (no silent normalize) | replay if canonical wrong | — |

Notes: canonical write is one transaction (report chain + monthly row); partial
canonical state cannot commit. Canonical failure never alters legacy; mirror
failure never alters canonical. Retry replay does not re-run scrapers.
