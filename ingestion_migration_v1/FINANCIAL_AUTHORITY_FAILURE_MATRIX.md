# FINANCIAL AUTHORITY FAILURE MATRIX

No distributed transaction. Canonical PostgreSQL authoritative; SQL Server mirror.
Canonical write is one transaction (report → version → parse_run → statement →
facts), so partial canonical state cannot commit.

| # | Case | Authoritative state | Recovery | Retry | Duplicate prevention |
| --- | --- | --- | --- | --- | --- |
| 1 | canonical committed / legacy mirror failed | canonical | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`; health `DEGRADED_LEGACY_MIRROR`; re-mirror | mirror-only | facts `ON CONFLICT (statement_id, metric_code, period_order)` |
| 2 | canonical failed / legacy fallback succeeds | legacy continuity; domain not caught up | `CANONICAL_FAILED_LEGACY_FALLBACK_USED`; retry queued; health `CANONICAL_ERROR`/`CANONICAL_BEHIND` | replay via shared manifest (canonical-only) | canonical statement `(parse_run, type)` + fact unique key |
| 3 | unresolved identity | no fabrication | `quarantined` + DQ; health `IDENTITY_QUARANTINE` | operator mapping, then replay | no fake company/security |
| 4 | duplicate / retry | canonical idempotent | second run inserts 0 | replay same keys | logical statement dedup + parse_run uniqueness |
| 5 | process crash between canonical and mirror | canonical | next cycle or manual re-mirror | none for canonical | canonical unique keys; mirror upsert idempotent |
| 6 | reconciliation failure | canonical retained; flagged | reclassify from canonical semantics (no silent normalize) | replay if canonical wrong | — |
| 7 | invalid metric / constraint failure | canonical rolled back (all-or-nothing) | `canonical_error`; fallback/retry | replay after fix | FK/unique constraints |
| 8 | parser failure | canonical rolled back | `PARSER_ERROR`; legacy continuity | parser rerun creates new parse_run | no fake version |

Retry distinguishes **retry** (replay same keys, no new version) from
**intentional reparse** (new parse_run, no new source version).
