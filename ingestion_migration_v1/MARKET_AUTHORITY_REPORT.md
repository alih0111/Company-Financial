# MARKET AUTHORITY REPORT — Phase 4

MARKET_PRICE promoted to canonical-primary for newly ingested market
observations, in the shadow environment, reversibly. SQL Server retained as
mirror/fallback. No global cutover; monthly/financial/CODAL unchanged.

## 1. Authority mode

`CDF_MARKET_INGESTION_AUTHORITY=canonical` + `CDF_INGESTION_MODE=dual_write` +
`CDF_MARKET_FALLBACK_LEGACY=true`. Rollback: set authority to `legacy`.

## 2. Real cycles (`market_authority_cycles.csv`)

Real `brs_prices` market path (live BRS, drawn symbols) via
`_persist_market` → `ingest_market_authoritative`:

| Cycle | Outcome | canonical inserted | canonical skipped | legacy mirror |
| --- | --- | --- | --- | --- |
| 1 (new/current) | `CANONICAL_SUCCESS_LEGACY_SUCCESS` | 0 | 4 | success |
| 2 (repeat/idempotent) | `CANONICAL_SUCCESS_LEGACY_SUCCESS` | 0 | 4 | success |
| 3 (no-change/fresh) | `CANONICAL_SUCCESS_LEGACY_SUCCESS` | 0 | 4 | success |

Inserted 0 because the day's observations were already ingested in Phase 3;
cycles remain idempotent (no duplicates, no overwrite). New-observation insertion
under canonical-primary is the same code path validated in Phase 2/3.

## 3. Reconciliation (`market_authority_reconciliation.csv`)

`EXACT_EQUIVALENT` 4; `LEGACY_MIRROR_MISSING`, `CANONICAL_MISSING`,
`IDENTITY_MISMATCH`, `NUMERIC_MISMATCH`, `DATE_MISMATCH`, `WRITE_ERROR`,
`UNCLASSIFIED` = **0**. Canonical authority has no unexplained mismatch.

## 4. Failure injection

| Scenario | Outcome | Health |
| --- | --- | --- |
| Canonical PostgreSQL unavailable | `CANONICAL_FAILED_LEGACY_FALLBACK_USED` (legacy continuity written), retry queued | `CANONICAL_ERROR` |
| SQL Server mirror fails | `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`; canonical status **success** (authoritative) | `DEGRADED_LEGACY_MIRROR` |

Mirror failure does not invalidate the canonical authoritative write; canonical
failure is visible and queues recovery.

## 5. Retry / backlog

`drivers/retry_market.py` replayed the pending MARKET_PRICE retry (re-reading
legacy rows, canonical-only) and marked it done. Freshness then reported
`retry_backlog=0`, `health=HEALTHY`. Replay is idempotent and does not re-run
legacy writes.

## 6. Freshness / authority state

`output/market_authority_freshness.json`: `authority=CANONICAL`,
latest source collection/trade date, latest canonical observation/trade date,
canonical rows, retry backlog, health. Final state after recovery: HEALTHY.

## 7. Go read-path end-to-end

Go canonical price-history read (`cmd/canarycheck`, `integration.FetchPriceHistoryCanonical`)
for کیمیا/غاذر/سباقر/دقاضی: canonical reachable, 30 rows each, 210 exact /
0 unexpected — the canonical read path sees the canonical market data. (Read
rollout percentage unchanged.)

## 8. Analytics visibility

Canonical market observations are visible to canonical read/analytics surfaces
(`market.daily_prices`); existing score runs were **not** rerun or overwritten.

## 9. Other domains

MONTHLY_ACTIVITY, FINANCIAL_STATEMENT, CODAL remain legacy-authoritative /
DUAL_WRITE as before; no accidental global cutover (authority flag is
market-only).

## 10. Gate

**`MARKET_CANONICAL_AUTHORITY_READY`** — SQL Server is retained.
