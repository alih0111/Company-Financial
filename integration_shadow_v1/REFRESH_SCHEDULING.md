# REFRESH SCHEDULING

Nothing in the ingestion path triggers analytics scoring, and `orchestrate_refresh.py`
is a **job**, not a hot path (see `ANALYTICS_REFRESH_CONTRACT.md`). New Codal reports
and new monthly activities therefore do not move the screen score by themselves.

## Current policy: manual, no timer (2026-10-30)

The hourly Windows task (`RFA Analytics Refresh`) was **removed on purpose**. Nothing
checks the score every hour anymore. Recomputation happens only when an admin presses
**«به‌روزرسانی امتیازها»** on the «غربال بازار» page (`/Table`).

| Piece | Where |
| --- | --- |
| Button (admin only) | `client/src/components/BigDataTable.tsx` |
| Endpoint | `POST /api/admin/analytics/refresh` (`go-app/handlers/analytics_refresh.go`) |
| Orchestrator | `canonical_postgres_v1_2_1/analytics_canonical_v1/orchestrate_refresh.py --mode RUN_IF_STALE` |
| CLI equivalent | `run_refresh_job.py` (same `RUN_IF_STALE` wrapper) |
| Server log of the last run | `go-app/.runtime/analytics-refresh.log` |
| Last JSON result | `go-app/.runtime/analytics-refresh-summary.json` |

Behaviour of the endpoint:

- admin only (`isAdmin` claim); non-admin gets 403;
- single-flight: a second click while a recompute runs gets 409;
- `RUN_IF_STALE` (never `FORCE_RUN`): if no input moved, it answers `NOT_STALE` and
  appends nothing — pressing the button twice does not create duplicate runs;
- a real recompute appends a **new serving run**; old runs stay readable;
- the client reloads the table rows and the freshness badge after `recomputed: true`.

## Manual CLI (fallback / operations)

```powershell
.\.venv\Scripts\python.exe canonical_postgres_v1_2_1\analytics_canonical_v1\orchestrate_refresh.py --mode CHECK_ONLY
.\.venv\Scripts\python.exe canonical_postgres_v1_2_1\analytics_canonical_v1\orchestrate_refresh.py --mode RUN_IF_STALE
```

`CHECK_ONLY` only reports staleness; it never writes. `RUN_IF_STALE` is idempotent and
also appends a JSON line to `analytics_canonical_v1/output/refresh_job_log.jsonl` when
invoked through `run_refresh_job.py`.

## Do not re-add a schedule

If a timer is ever reintroduced it must run `RUN_IF_STALE` (never `FORCE_RUN`) and stay
out of the request path. The product decision as of 2026-10-30 is that freshness is a
human decision: the score is frozen until an admin asks for a recompute, and the badge
says so (`score_stale` + reasons).

## Monitoring

1. **`GET /api/health/shadow`** — `score_stale` is `true` when the served run's input
   fingerprint no longer matches current inputs; `score_stale_reasons` names the domains
   that moved. This stays a read-only check; it never triggers work.
2. **`output/refresh_job_log.jsonl`** — one line per `run_refresh_job.py` invocation.

## Verification

```bash
python canonical_postgres_v1_2_1/analytics_canonical_v1/run_refresh_job.py
curl -s http://127.0.0.1:5000/api/health/shadow
```

Expected: `NOT_STALE` (or `RECOMPUTED` once), and the health payload shows
`score_stale:false` with the run's `score_run_seq` / `score_computed_at`.
