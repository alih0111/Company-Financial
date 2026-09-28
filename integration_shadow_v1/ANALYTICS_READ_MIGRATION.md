# ANALYTICS READ MIGRATION

Status: **SHADOW validated, 0 unexplained mismatch.** Legacy response remains
authoritative; no broad cutover.

Endpoint: `GET /api/summary` (and the symbol/company UI score reads), feeding the
React client's `AIStockMetric` shape.

## Principle

Go **consumes** canonical analytics outputs and never recomputes the scoring
model. No TTM, percentile, weight or category arithmetic exists in Go
(enforced by `TestGuardNoAnalyticsFormulaDuplication`).

## Canonical analytics sources

| Source | Canonical table | Consumed by |
| --- | --- | --- |
| score runs | `analytics.score_runs` | `SelectScoreRun`, `Metadata` |
| company/category/quant scores | `analytics.company_scores` | `ScoresByLegacyIDs` |
| factor scores | `analytics.factor_scores` | `FactorScoresByLegacyIDs` |
| metric snapshots | `analytics.metric_snapshots` | `MetricSnapshotsByLegacyIDs` |

`raw_value`, `percentile`, `weight`, `weighted_score` (factor scores) and
`quant_score` + category scores are returned **verbatim** as stored.

## Score version selection

- Version is selected by `CDF_CANONICAL_SCORE_VERSION` (default
  `canonical-v1-dev`), passed explicitly to every read.
- `SelectScoreRun` chooses the latest **completed** run for the version by
  `as_of_date DESC, started_at DESC`.
- Experimental v2 is never a default (it does not exist in the selected path).
- Test `TestShadowScoreVersionDeterministic` proves the requested version reaches
  the source unchanged.

## Freshness / stale-score metadata

`Metadata(ctx, version)` and `GET /api/health/shadow` expose:

| Field | Meaning |
| --- | --- |
| `score_version` | selected canonical model version |
| `score_run_id` | UUID of the selected completed run |
| `score_as_of` | `analytics.score_runs.as_of_date` |
| `source_cutoff_at` | PIT cutoff the run was computed from |
| `data_as_of` | latest canonical fundamentals period (`max(period_end_date)`) |
| `score_stale` | true when canonical market/fundamentals data is newer than the run's `source_cutoff_at` |

**Newly ingested data does not automatically refresh a score run.** The
application can therefore detect stale score state before displaying it. Live
soak/validation shows `score_stale=true` because canonical market data
(2026-09-25) is newer than the selected run cutoff (2026-09-24 20:41) — an
intended, visible signal, not an error.

Operational pipeline (documented, not changed):

```
canonical ingestion -> canonical freshness check -> analytics computation
  -> versioned score_run -> Go read (version + as_of + data_as_of) -> React
```

## Live SHADOW comparison (`GET /api/summary`, 2026-09-25)

| Metric | Value |
| --- | --- |
| legacy rows | 20 |
| canonical rows | 20 |
| matched | 20 |
| exact fields | 77 |
| expected canonical semantic changes | 83 (quant/growth/profitability/valuation/market) |
| order-only difference | 1 |
| unexpected | **0** |
| errors | 0 |
| legacy latency | 4973.8 ms |
| canonical latency | 22.2 ms |

`EXPECTED_CANONICAL_SEMANTIC_CHANGE` is the documented canonical-v1 vs legacy
v3.7 model difference; canonical data is **not** deformed to imitate the legacy
heuristic. Machine-readable: `output/analytics_shadow_comparison.csv`.

Because the legacy `vw_AIStockMetrics` summary read costs ~5 s while the canonical
set-based read costs ~22 ms (≈225× faster), `/api/summary` is a strong future
canary candidate — **but its score semantics intentionally differ**, so it stays
SHADOW-only in this task and is not proposed for direct serving until the product
accepts the canonical v1 semantics.

## Score list endpoints (Phase 9)

`/api/AllCompanyScores` and `/api/CompanyScores` now have canonical SHADOW paths
(`PG.AllScoresCanonical`, `PG.CompanyScoreByLegacyID`,
`Shadow.CompareAllCompanyScores`, `Shadow.CompareCompanyScores`). Both are single
indexed queries with a lateral latest-price lookup; Go performs no scoring
arithmetic.

| Endpoint | legacy/canon/matched | expected | unexpected | legacy ms → canonical ms |
| --- | --- | --- | --- | --- |
| AllCompanyScores | 276/268/267 | 1089 | **0** | 112.0 → 44.7 |
| CompanyScores | 12/9/9 | 27 | **0** | 3780.1 → 60.5 |

`CompanyScores` runs `Metadata` per request; metadata is cached for 60 s to avoid
the full `max(trade_date)` scan (3.6 s → 60 ms).

## Refresh pipeline and post-refresh state

The refresh contract is `ANALYTICS_REFRESH_CONTRACT.md`. After the executed
`RUN_IF_STALE` proof, Go selects the new completed run
`489a6df0-2d37-44de-a0c5-ef0d5daa7191` (`score_as_of=2026-09-25`) and
`score_stale=false`. Post-refresh SHADOW totals remain **0 unexpected / 0 errors**.

## Gaps / explicit missing-data behaviour

- `analytics.metric_snapshots` is **empty** in the current canonical run. The Go
  reader returns no rows (never fabricated); the symbol-page report surfaces
  `metric_snapshots_not_materialized`.
- Base metrics (revenue, net profit, EPS, capital) are read from canonical
  fundamentals, not duplicated from analytics.
