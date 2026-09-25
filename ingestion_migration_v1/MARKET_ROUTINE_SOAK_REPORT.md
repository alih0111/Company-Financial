# MARKET ROUTINE SOAK REPORT (Part A)

Routine MARKET_PRICE canonical-primary soak, real BRS source, SQL Server mirror
enabled, `CDF_MARKET_INGESTION_AUTHORITY=canonical`.

## Cycles

5 real cycles (symbols کیمیا/غاذر/سباقر/دقاضی/دارو), driver
`drivers/run_market_routine_soak.py`; artifact `output/market_routine_soak.csv`.

| Metric | Value |
| --- | --- |
| cycles | 5 |
| genuinely new observations inserted | **1** |
| skipped (idempotent) | rest |
| reconciliation | `EXACT_EQUIVALENT` 25, mismatches **0** |
| legacy mirror | success every cycle |
| retry backlog | **0** |
| health | **HEALTHY** |
| latest source / canonical trade date | 2026-09-25 (caught up) |

A genuinely new market observation was available and inserted under
canonical-primary; repeat cycles inserted nothing (duplicate prevention).
`collected_at` remains actual collection time. No CANONICAL_MISSING /
IDENTITY_MISMATCH / NUMERIC_MISMATCH / DATE_MISMATCH / WRITE_ERROR /
UNCLASSIFIED.

## Gate: `MARKET_ROUTINE_SOAK_PASS`
