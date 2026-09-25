# MARKET QUERY PROFILE — Canonical `/api/price-history`

Shadow/test database only: `company_financial_analytics_shadow_v121`.
No production index was created. All timings are local, single-node.

## 1. Symptom

Phase 1 measured canonical price-history shadow latency at ~3280 ms for 6
requests (~547 ms each/symbol) versus legacy ~422 ms for the same 6 requests.

## 2. Original query shape

```sql
WITH sec AS (
  SELECT security_id FROM core.security_aliases WHERE alias_value = $1
  UNION
  SELECT id FROM core.securities WHERE codal_symbol = $1 OR brs_name = $1
)
SELECT ...
FROM market.daily_prices dp          -- DISTINCT ON view
JOIN sec ON sec.security_id = dp.security_id
ORDER BY dp.trade_date DESC
LIMIT $2;
```

`market.daily_prices` is:
```sql
SELECT DISTINCT ON (security_id, trade_date) ...
FROM market.price_observations
WHERE price_series = 'adjusted'
ORDER BY security_id, trade_date, collected_at DESC, id DESC;
```

## 3. EXPLAIN (ANALYZE, BUFFERS) — original

Representative plan (`symbol = 'کیمیا'`, limit 30):

```
Limit  (actual time=786.5..786.6 rows=30)
  -> Sort  (top-N heapsort)  Sort Key: price_observations.trade_date DESC
       Buffers: shared hit=1340 read=18835
       -> Merge Join  (actual time=779.5..785.7 rows=2354)
            Merge Cond: (price_observations.security_id = security_aliases.security_id)
            -> Unique  (actual time=0.1..760.1 rows=331156)
                 -> Incremental Sort  (actual time=0.1..710.4 rows=331249)
                      Sort Key: security_id, trade_date, collected_at DESC, id DESC
                      Full-sort Groups: 10352
                      -> Index Scan using ix_price_observations_security_date
                         Filter: (price_series = 'adjusted')
                         actual rows=331265
            -> Unique  (security_aliases)  rows=1
Execution Time: 786.978 ms
```

## 4. Root cause classification

| Cause | Applies |
| --- | --- |
| `VIEW_EXPANSION` | **Yes — primary** |
| `QUERY_SHAPE` | **Yes — primary** |
| `EXCESS_DATA_FETCH` | Yes (reads 331,265 of 705,812 rows) |
| `MISSING_INDEX` | No (a matching index already exists) |
| `TYPE_CAST` | No |
| `SORT_COST` | Secondary (Incremental Sort over 10,352 groups) |
| `IDENTITY_LOOKUP` | No (alias lookup is trivial: 547 rows) |
| `BAD_ESTIMATE` | No (estimate 705,815 vs actual 331,265, same order) |
| `REVISION_RESOLUTION` | Not the dominant cost |

The security equality predicate is applied **after** the view has already
computed `DISTINCT ON (security_id, trade_date)` across the entire table. The
planner therefore ranks/`Unique`s hundreds of thousands of rows and only then
restricts to the one security.

## 5. Fix applied (query shape only, no schema/index change)

1. Resolve the security UUID **once** (`ResolveSecurityID`).
2. Read the append-only `market.price_observations` directly, scoped to that
   security, with `DISTINCT ON (trade_date)`.
3. Preserve the view's deterministic selection exactly:
   `ORDER BY trade_date DESC, collected_at DESC, id DESC` (latest adjusted
   observation; ties by insertion id).

```sql
SELECT DISTINCT ON (po.trade_date) ...
FROM market.price_observations po
WHERE po.security_id = $1
  AND po.price_series = 'adjusted'
ORDER BY po.trade_date DESC, po.collected_at DESC, po.id DESC
LIMIT $2;
```

The existing index `ix_price_observations_cutoff (security_id, trade_date, collected_at)`
serves this plan. No new index is required or proposed.

## 6. EXPLAIN (ANALYZE, BUFFERS) — optimized

```
Limit  (actual time=2.861..2.873 rows=30)
  -> Unique  (actual time=2.860..2.870 rows=30)
       -> Sort  Sort Key: po.trade_date DESC, po.collected_at DESC, po.id DESC
            -> Nested Loop
                 -> Limit (resolved security)  rows=1
                 -> Bitmap Heap Scan on price_observations po
                      Filter: (price_series = 'adjusted')
                      Heap Blocks: exact=165
                      -> Bitmap Index Scan on ix_price_observations_cutoff
                         Index Cond: (security_id = security_aliases.security_id)
                         actual rows=2354
Execution Time: 3.075 ms
```

## 7. Multi-sample timing (15 iterations each, same session)

| Query | median | p95 | min | max |
| --- | --- | --- | --- | --- |
| Original view query | 655.60 ms | 700.94 ms | 597.01 ms | 763.83 ms |
| Optimized direct query | 1.80 ms | 6.78 ms | 1.46 ms | 15.97 ms |

Median improvement ≈ **364×** (p95 ≈ 103×).

End-to-end shadow measurement (6 symbols × 30 sessions):

| | Phase 1 canonical | Phase 2 canonical |
| --- | --- | --- |
| aggregate | 3280.4 ms | 71.1 ms |
| per symbol | ~547 ms | ~12 ms |

## 8. Correctness equivalence

For 30 sessions of `کیمیا`, the original and optimized result sets were compared
with `EXCEPT` in both directions over `(trade_date, closing_price_rial, observation_id)`:

```
cur_rows | opt_rows | cur_minus_opt | opt_minus_cur
       30 |       30 |             0 |             0
```

The Phase-2 shadow run re-confirmed this at the endpoint level: price-history
remains **1260 exact matches, 0 expected, 0 unexpected, 0 errors**. Same rows,
dates, prices, ordering and revision-selection semantics. No PIT regression, no
duplicates, no skipped observations.

## 9. Notes / residual

- A non-DDL index `ix_price_observations_latest_covering` exists in the shadow DB
  (not part of canonical `090_indexes.sql`). It was not required for the fix.
- `market.daily_prices` is left unchanged; the optimization is application-side.
- If a future CANONICAL cutover exposes this endpoint, the same query shape
  should be used in the canonical repository.
