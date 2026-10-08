# REFRESH SCHEDULING

Nothing in the ingestion path triggers analytics scoring, and `orchestrate_refresh.py`
is a job — not an HTTP request path (see `ANALYTICS_REFRESH_CONTRACT.md`). Without a
schedule the served score is only as fresh as the last manual invocation.

## What to schedule

```
canonical_postgres_v1_2_1/analytics_canonical_v1/run_refresh_job.py
```

It runs `RUN_IF_STALE` (never `FORCE_RUN`), is idempotent (a second run reports
`NOT_STALE` and writes nothing), appends one JSON line per invocation to
`analytics_canonical_v1/output/refresh_job_log.jsonl`, and exits:

| exit | meaning |
| --- | --- |
| 0 | fresh (`NOT_STALE`) or a run was completed (`RECOMPUTED`) |
| 1 | could not refresh: `BLOCKED_DEGRADED_INGESTION` or `RECOMPUTE_INCOMPLETE` |
| 2 | unexpected error |

Order the job **after** the ingestion jobs for the same window, so the fingerprint it
sees includes the newly ingested rows.

## Registering the task (Windows)

Daily at 09:00 (adjust to your ingestion window), running as the current user:

```powershell
schtasks /Create /TN "RFA Analytics Refresh" /SC DAILY /ST 09:00 ^
  /TR "D:\RFA\Company-Financial\.venv\Scripts\python.exe D:\RFA\Company-Financial\canonical_postgres_v1_2_1\analytics_canonical_v1\run_refresh_job.py"
```

Hourly instead of daily:

```powershell
schtasks /Create /TN "RFA Analytics Refresh" /SC HOURLY /MO 1 ^
  /TR "D:\RFA\Company-Financial\.venv\Scripts\python.exe D:\RFA\Company-Financial\canonical_postgres_v1_2_1\analytics_canonical_v1\run_refresh_job.py"
```

Remove with `schtasks /Delete /TN "RFA Analytics Refresh" /F`.

## Monitoring

Two independent signals, both cheap:

1. **`GET /api/health/shadow`** — `score_stale` is `true` when the served run's input
   fingerprint no longer matches the current inputs, and `score_stale_reasons` names the
   domains that moved. `analytics_status` is `HEALTHY` | `STALE` | `NO_COMPLETED_RUN`.
   Alert when `score_stale` is true for longer than a refresh interval.
2. **`output/refresh_job_log.jsonl`** — one line per job invocation; any non-zero exit
   is written to the scheduler's task history and to the log as an `ERROR`/blocked
   record.

## Verification (dry run)

```bash
python canonical_postgres_v1_2_1/analytics_canonical_v1/run_refresh_job.py
curl -s http://127.0.0.1:5000/api/health/shadow
```

Expected: the job prints `NOT_STALE` (or `RECOMPUTED` once), and the health payload
shows `score_stale:false` with the run's `score_run_seq` / `score_computed_at`.
