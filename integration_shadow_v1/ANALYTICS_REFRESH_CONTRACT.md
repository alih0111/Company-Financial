# ANALYTICS REFRESH CONTRACT

Defines the operational pipeline and the deterministic staleness rule between
canonical ingestion and the Go/API read path. Scoring formulas are unchanged.

## Pipeline

```
canonical ingestion
  -> data freshness / ingestion health
  -> analytics recomputation (explicit as_of / source_cutoff)
  -> NEW append-only completed score_run
  -> Go/API serves latest approved score version
  -> client sees score freshness (score_as_of / data_as_of / score_stale)
```

Newly ingested data does **not** imply an existing score run is current.

## Components

| Concern | Artifact |
| --- | --- |
| Ingestion health/status | `ingestion_migration_v1/output/canonical_ingestion_status.json` |
| Orchestration | `canonical_postgres_v1_2_1/analytics_canonical_v1/orchestrate_refresh.py` |
| Engine (unchanged) | `.../compute_metrics.py` (`Engine`, `store_run`) |
| Go freshness metadata | `integration.PG.Metadata`, `integration.Shadow.RefreshStatus`, `GET /api/health/shadow`, `cmd/readstatus` |
| Result artifact | `integration_shadow_v1/output/analytics_refresh_summary.json` |

## Modes (`--mode`)

| Mode | Behaviour |
| --- | --- |
| `CHECK_ONLY` (default) | report staleness; compute nothing |
| `RUN_IF_STALE` | routine intent: recompute only if stale **and** ingestion is `HEALTHY` |
| `FORCE_RUN` | explicit override; never a routine default |

`RUN_IF_STALE` is blocked with `BLOCKED_DEGRADED_INGESTION` when any ingestion
domain health is not `HEALTHY` (retry backlog) unless `--allow-degraded`.
Orchestration is a job path; it is **not** wired to HTTP requests.

## Deterministic staleness rule

Given the latest **completed** run for the explicit score version:

```
stale =
    no completed run
  OR monthly_latest.period_end_date      > run.as_of_date
  OR financial_latest.period_end_date    > run.as_of_date
  OR market_latest.trade_date            > run.as_of_date
  OR market_latest.collected_at          > run.source_cutoff_at
  OR reports_latest.created_at           > run.source_cutoff_at
```

- Date comparisons use canonical **data dates** (not the wall clock).
- `collected_at`/`created_at` comparisons catch intra-day arrivals on the same
  business date.
- Reasons are always emitted (`staleness.reasons`) so a stale state is
  explainable, never silent.

### Recompute parameters
- `as_of = max(monthly_latest, financial_latest, market trade_date)`
- `source_cutoff = max(latest market collected_at, latest report created_at)`
  (falls back to wall clock only if neither exists)

## Append-only guarantee

- `store_run` always **inserts** a new `analytics.score_runs` row; existing runs
  are never overwritten.
- Company/factor rows use `ON CONFLICT (run_id, company_id[, factor_code]) DO
  NOTHING`, so a rerun cannot mutate a prior run.
- `RUN_IF_STALE` is idempotent: after a successful run, staleness becomes false
  and the next invocation returns `NOT_STALE` (no new run).

## Score-run selection contract (Go)

`analytics.score_runs` selection is deterministic and never "max id":

```sql
WHERE score_version = <explicit version> AND status = 'completed'
ORDER BY as_of_date DESC, started_at DESC
LIMIT 1
```

- Only `completed` runs are selectable. A `running`/`failed`/incomplete run is
  never chosen; the prior completed run remains readable.
- Multiple versions (e.g. future `canonical-v2-exp-*`) coexist because the
  version is an explicit predicate. Experimental versions are never a default.
- Tie-break: `as_of_date DESC`, then `started_at DESC`.

## Failure behaviour (required)

| Failure | Behaviour |
| --- | --- |
| engine computation error | no row inserted; prior completed run stays selected |
| partial run | run row never marked `completed`; not selectable; `stale` stays true |
| DB failure | orchestration returns error; canonical reads unaffected |
| stale input | `CHECK_ONLY`/`RUN_IF_STALE` report it; no silent serving of stale as current |
| ingestion retry backlog | `RUN_IF_STALE` blocked unless `--allow-degraded` |
| repeated `RUN_IF_STALE` | `NOT_STALE`; no duplicate run |
| score run created but incomplete | excluded by `status='completed'`; prior run remains |

## End-to-end freshness proof (executed)

```
1. newer canonical data exists      market trade_date 2026-09-25 (run as_of 2026-09-24)
2. stale detected                   CHECK_ONLY: stale=true, reasons listed
3. RUN_IF_STALE                     -> RECOMPUTED
4. new append-only score run        489a6df0-2d37-44de-a0c5-ef0d5daa7191, status=completed,
                                    as_of=2026-09-25, 267 company_scores, 5607 factor_scores
5. Go selects the new run           cmd/readstatus: score_run_id=489a6df0..., score_as_of=2026-09-25
6. score_stale=false                Metadata: market_as_of 2026-09-25 <= source_cutoff_at
7. prior run preserved              c6cb1579-... remains in analytics.score_runs
8. RUN_IF_STALE again               NOT_STALE, no new run (idempotent)
```

No market/fundamental data was fabricated; the existing newer canonical market
data was sufficient.

## Gate
`ANALYTICS_REFRESH_READY`
