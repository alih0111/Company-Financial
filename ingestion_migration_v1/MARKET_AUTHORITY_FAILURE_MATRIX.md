# MARKET AUTHORITY FAILURE MATRIX

No 2PC between PostgreSQL and SQL Server. In canonical-primary mode the canonical
transaction is authoritative; the SQL Server write is a mirror.

| # | Crash window | Authoritative state | Recovery action | Retry behavior | Duplicate prevention |
| --- | --- | --- | --- | --- | --- |
| A | source fetched, nothing written | none | next cycle re-fetches; idempotent if canonical later | none needed | natural-key/hash |
| B | canonical committed, legacy mirror not written | **canonical** (correct) | degraded; mirror repaired by next cycle or manual mirror | no canonical retry needed | canonical ON CONFLICT + natural key |
| C | canonical committed, legacy mirror write fails | **canonical** | outcome `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`; health `DEGRADED_LEGACY_MIRROR`; retry mirror | mirror-only replay; canonical untouched | canonical idempotent; mirror upsert idempotent |
| D | canonical failed, legacy fallback written | legacy continuity only; domain **NOT** caught up | outcome `CANONICAL_FAILED_LEGACY_FALLBACK_USED`; retry queued; health `CANONICAL_ERROR`/`CANONICAL_BEHIND` | `retry_market.py` re-reads legacy rows and writes canonical-only | canonical natural-key/hash + legacy upsert |
| E | process exits before reconciliation | canonical authoritative; mirror may lag | next cycle reconciles; freshness shows backlog/lag | retry manifest if canonical failed | idempotent writes |

## Notes

- Canonical commit is single-transaction (`ingestion.reports` chain +
  `fundamentals`/`market` rows) — partial canonical state cannot be committed.
- A canonical failure never deletes or alters legacy; a legacy mirror failure
  never alters canonical.
- The retry manifest records `domain`, `keys` and `error`; replay restores
  canonical state without destructive legacy replay.
- Crash between canonical commit and `_record` only loses a diagnostic row, not
  data; the next cycle re-confirms idempotently.
