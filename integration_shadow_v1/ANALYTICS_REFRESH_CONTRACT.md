# ANALYTICS REFRESH CONTRACT

Defines the operational pipeline, the run-identity rule and the deterministic
staleness rule between canonical ingestion and the Go/API read path. Scoring
formulas are unchanged.

## The invariant

> The score served by the API is always the completed run computed from the newest
> available score-relevant inputs; and the system either produces such a run itself or
> reports loudly that it cannot.

Two properties make this true, and both were missing before this revision:

1. **Run selection is by run recency, not by data date.** `as_of_date` is a *data*
   visibility date, not a property of the run. Selecting by it meant a run computed
   from newer inputs could lose to a run whose `as_of` was ahead of its inputs, and
   could never supersede an out-of-band run — the score froze regardless of how much
   data arrived.
2. **Staleness is exact input comparison**, not date arithmetic. A report that arrives
   for a period *older* than the run's `as_of` (a backfill) is invisible to
   `period_end_date > as_of`; the input watermark sees it.

## Pipeline

```
canonical ingestion
  -> data freshness / ingestion health
  -> analytics recomputation (explicit as_of / source_cutoff)
  -> NEW append-only completed score_run  (run_kind='serving', input_watermark recorded)
  -> Go/API serves the newest completed serving run BY run_seq
  -> client sees score_as_of / score_computed_at / score_stale
```

Newly ingested data does **not** imply an existing score run is current, and ingestion
never triggers scoring. Orchestration is a job path, not an HTTP request path.

## Components

| Concern | Artifact |
| --- | --- |
| Ingestion health/status | `ingestion_migration_v1/output/canonical_ingestion_status.json` |
| Orchestration | `canonical_postgres_v1_2_1/analytics_canonical_v1/orchestrate_refresh.py` |
| Engine | `.../compute_metrics.py` (`Engine`, `input_watermark`, `store_run`) |
| Schema | `canonical_postgres_v1_2_1/sql/121_analytics_run_identity.sql` |
| Go freshness | `integration.PG.Metadata`, `integration.Shadow.RefreshStatus`, `GET /api/health/shadow` |
| Result artifact | `integration_shadow_v1/output/analytics_refresh_summary.json` |

## Modes (`--mode`)

| Mode | Behaviour |
| --- | --- |
| `CHECK_ONLY` (default) | report staleness; compute nothing |
| `RUN_IF_STALE` | routine intent: recompute only if stale **and** ingestion is `HEALTHY` |
| `FORCE_RUN` | explicit override; never a routine default |

`RUN_IF_STALE` is blocked with `BLOCKED_DEGRADED_INGESTION` when any ingestion domain
health is not `HEALTHY` (retry backlog) unless `--allow-degraded`. It is idempotent:
after a successful run, staleness is false and the next invocation returns `NOT_STALE`.

## Run identity

Three concepts that must not be conflated:

| Concept | Meaning | Where |
| --- | --- | --- |
| `as_of_date` | data visibility date (PIT filter + display) | `analytics.score_runs.as_of_date` |
| `run_seq` | monotonic run recency — **the selection key** | `analytics.score_runs.run_seq` |
| `run_kind` | `serving` (selectable as current) vs `pit_backfill` (never served) | `analytics.score_runs.run_kind` |

Only `orchestrate_refresh.py` writes `run_kind='serving'`. An ad-hoc or historical
invocation (`compute_metrics.py --store`, `score_v4.py --store`) defaults to
`pit_backfill`, so an out-of-band run with an arbitrary `--as-of` can never freeze the
pipeline by becoming the served score.

## Deterministic staleness rule

Given the newest completed **serving** run for the score version:

```
stale =
    no completed serving run
  OR the run has no recorded input_watermark        (pre-migration run)
  OR for any input domain:  rows    changed
  OR for any input domain:  arrival is newer
  OR for any input domain:  content digest changed
  OR for any input domain:  data date > run.as_of_date
```

Input domains: `monthly`, `financial`, `market`, `shares`, `reports`.

- Each domain stores `{date, arrival, rows, digest}`; the run records the whole
  fingerprint in `score_runs.input_watermark`.
- The fingerprint is *unbounded by cutoff*: a row that already existed by data date but
  arrived after the run's cutoff still moves it. That is what makes a same-day or
  backfilled arrival visible.
- `reasons` is always emitted, so a stale state is explainable, never silent.

### Recompute parameters

- `as_of = max(monthly_latest, financial_latest, market trade_date)`
- `source_cutoff = max(latest market collected_at, latest report created_at)`
  (falls back to wall clock only if neither exists)

`as_of` may be *earlier* than a previously served run's `as_of` (a run whose `as_of`
was ahead of its inputs should not have existed). That is safe and visible: the read
layer selects by `run_seq`, and the API reports `score_computed_at` alongside
`score_as_of`, so a fresh computation over a non-advancing data date is not mistaken
for a regression.

## Score-run selection contract (Go)

Exactly one definition, `integration.servingRunCTE`:

```sql
SELECT id, score_version FROM analytics.score_runs
WHERE score_version = $1 AND status = 'completed' AND run_kind = 'serving'
ORDER BY run_seq DESC
LIMIT 1
```

- Do **not** reintroduce `ORDER BY as_of_date DESC`; that is the bug this replaces.
- Only `completed` runs are selectable. A `running`/`failed`/incomplete run is never
  chosen; the prior completed run remains readable.
- Multiple versions (e.g. `canonical-v2-exp-*`) coexist because the version is an
  explicit predicate. Experimental versions are never a default.
- `analytics.metric_snapshots` is **run-scoped** (`UNIQUE (run_id, company_id,
  metric_code)`), so re-scoring the same `as_of` over corrected inputs stores a new row
  under the new run instead of aborting on a unique violation. PIT reads use the
  `(metric_code, as_of_date)` index.

## Freshness surface (Go)

`integration.PG.Metadata` compares the served run's `input_watermark` with the current
cheap fingerprint (date / arrival / rows per domain) and sets:

- `score_as_of` — the run's data visibility date
- `score_computed_at` — when the run finished
- `score_run_seq` — the selection key
- `score_stale` — inputs moved since the run
- `score_stale_reasons` — which domains moved
- `analytics_status` — `HEALTHY` | `STALE` | `NO_COMPLETED_RUN`

The content digest is computed by the orchestrator and is authoritative for the
recompute decision; the badge uses the cheap fields so it never runs a multi-second
content scan on a request path. The domain keys are mirrored in
`compute_metrics.INPUT_DOMAIN_AGGREGATES` and `integration.cheapWatermarkSQL`; keep them
in sync.

## Failure behaviour (required)

| Failure | Behaviour |
| --- | --- |
| engine computation error | no row inserted; prior serving run stays selected |
| partial run | run row never marked `completed`; not selectable; `stale` stays true |
| DB failure | orchestration returns error; canonical reads unaffected |
| stale input | `CHECK_ONLY`/`RUN_IF_STALE` report it; no silent serving of stale as current |
| ingestion retry backlog | `RUN_IF_STALE` blocked unless `--allow-degraded` |
| repeated `RUN_IF_STALE` | `NOT_STALE`; no duplicate run |
| same-`as_of` recompute | storable (run-scoped snapshots); served by `run_seq` |
| ad-hoc / PIT run | `run_kind='pit_backfill'`; never served as current |

## Operational requirement

`RUN_IF_STALE` must run on a schedule after the ingestion jobs (see
`canonical_postgres_v1_2_1/analytics_canonical_v1/run_refresh_job.py` and
`integration_shadow_v1/REFRESH_SCHEDULING.md`). Nothing in the ingestion path calls it.
Without a schedule the score is correct but only as fresh as the last invocation —
which is now visible as `score_stale=true` instead of silently wrong.

## Gate
`ANALYTICS_REFRESH_READY`
