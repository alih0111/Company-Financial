# INGESTION RECONCILIATION REPORT — Phase 1

Bounded dual-write sample over 10 heterogeneous legacy companies
(strong/sparse fundamentals, monthly activity, alias case, market observations,
unmapped identity). SQL Server was read-only; canonical target was
`company_financial_analytics_shadow_v121`.

## 1. Sample

Names: قاسم، تاصیکو، کسرا، زگلدشت، افق، دکپسول، هجرت، چخزر، بفجر، خاهن.
- 9 resolved to canonical companies; خاهن is canonical-unmapped (scope
  exclusion) → quarantined (4 rows).
- Per company: up to 6 monthly periods, 4 financial periods, up to 30 market
  observations.

## 2. Idempotency (two consecutive runs, after cleanup)

| Run | written | quarantined | inserted | skipped (idempotent) |
| --- | --- | --- | --- | --- |
| A | 82 | 4 | 73 | 914 |
| B | 82 | 4 | **0** | **987** |

Run B inserted **0** rows: report/version/parse_run idempotent, monthly
deduplicated by `(company_id, period_end_date)`, statements/facts by
`(company_id, period_end_date, statement_type)` and
`(statement_id, metric_code, period_order)`, observations by content hash.

## 3. Reconciliation classifications

| Classification | Count |
| --- | --- |
| `EXPECTED_UNIT_CONVERSION` | 73 |
| `EXACT_EQUIVALENT` | 9 |
| `MISSING_CANONICAL` | 0 |
| `IDENTITY_MISMATCH` | 0 |
| `NUMERIC_MISMATCH` | 0 |
| `DATE_MISMATCH` | 0 |
| `WRITE_ERROR` | 0 |
| `UNCLASSIFIED` | 0 |

- Monthly and financial money rows classify as `EXPECTED_UNIT_CONVERSION`
  (`sales_amount_rial = reported_sales_amount × 1e6`; canonical_value in IRR).
- EPS and market price rows are `EXACT_EQUIVALENT`.
- No unexplained mismatch.

Machine-readable: `output/dual_write_results.csv`,
`output/ingestion_reconciliation.csv`.

## 4. Failure isolation

| Scenario | Result |
| --- | --- |
| Unresolved identity (خاهن) | `quarantined`; `identity_conflict` recorded; no fabricated company |
| Canonical constraint failure (invalid metric_code) | `canonical_error`; canonical transaction rolled back; no statement persisted |
| PostgreSQL unavailable / disallowed DB | `canonical_error`; legacy path untouched |
| Parser error | transaction rolls back; `canonical_error` returned |

The legacy SQL Server path is independent and was not blocked by any canonical
outcome. A canonical failure is never reported as ingestion success.

## 5. Market `collected_at`

New market observations store the **source** `CollectedAt`
(`MarketPriceHistory.CollectedAt`, +03:30), verified by test
(`2026-09-24 17:01:00`), not migration time. Append-only dedup by
`(security_id, trade_date, source, price_series, observation_hash)`.

## 6. Known limitations

- The full-universe shadow DB already contains migrated rows; the content hash
  used by this writer differs from the migration's historical hash for some
  market observations, so cross-migration dedup of market revisions relies on
  the writer's own deterministic hash. New ingestion is idempotent per writer.
- `py2`'s separate schematic remains non-canonical (Phase 3 decision).
- CODAL_REPORT raw capture/parser runs are implemented but not yet wired into
  `sync_codal.py`.

## 7. Phase 2 — real-script batches

Real legacy scripts (`brs_prices` live BRS; monthly/financial hook with real
legacy keys) were dual-written. Market run 1: inserted 4, skipped 0; run 2:
inserted 0, skipped 4. Monthly/financial: idempotent (inserted 0). Classification:
`EXACT_EQUIVALENT` 14, `EXPECTED_UNIT_CONVERSION` 41, all mismatch classes 0.
Details in `PHASE2_REAL_SCRIPT_REPORT.md` and
`output/phase2_reconciliation.csv`.

## 8. Phase 3 — sustained soak

15 real DUAL_WRITE cycles (3 market, 6 monthly, 6 financial): canonical inserted
6 (new monthly periods), skipped 378, canonical errors 0, quarantined 0,
unexplained mismatches 0. Market cycles idempotent (inserted 0 on reruns);
financial cycles reused statements/facts. Reconciliation per cycle
(`output/phase3_reconciliation.csv`) had no mismatch class. Details:
`PHASE3_SOAK_REPORT.md`.

## 9. Phase 4 — MARKET_PRICE canonical-primary

3 real canonical-authoritative cycles: all `CANONICAL_SUCCESS_LEGACY_SUCCESS`,
idempotent; reconciliation `EXACT_EQUIVALENT` 4, all mismatch classes 0.
Failure injection: canonical unavailable → `CANONICAL_FAILED_LEGACY_FALLBACK_USED`
(retry queued); SQL Server mirror failure → `CANONICAL_SUCCESS_LEGACY_MIRROR_FAILED`
(canonical status success, mirror degraded only). Retry replay returned
`retry_backlog=0`, `health=HEALTHY`. Details: `MARKET_AUTHORITY_REPORT.md`.

## 10. Phase 6 — monthly routine soak + financial canonical-primary

Monthly routine soak: 16 cycles, HEALTHY, backlog 0, 0 mismatch. Financial
authority: 20 cycles, reconciliation `EXACT_EQUIVALENT` 40 +
`EXPECTED_UNIT_CONVERSION` 127, 0 mismatch; facts/statements reused; parser rerun
new parse_run without new version; no Product/NPUnitRatio/OpK/OpAmt facts.
Details: `MONTHLY_ROUTINE_SOAK_REPORT.md`, `FINANCIAL_AUTHORITY_REPORT.md`.
