"""Routine analytics refresh job (scheduler entry point).

Nothing in the ingestion path triggers scoring, so a score only becomes current when
something runs `RUN_IF_STALE`. This is that something: a thin, idempotent wrapper
around orchestrate_refresh for a scheduled task.

Behaviour:
  * runs `RUN_IF_STALE` (never FORCE_RUN — a schedule must not fabricate runs),
  * appends one JSON line per invocation to output/refresh_job_log.jsonl,
  * exits 0 when the score is fresh (NOT_STALE) or a run was completed,
  * exits 1 when it could not refresh (blocked on degraded ingestion, incomplete run)
    so a scheduler can surface it,
  * exits 2 on an unexpected exception.

Run:
    python canonical_postgres_v1_2_1/analytics_canonical_v1/run_refresh_job.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")

import orchestrate_refresh as orf  # noqa: E402

LOG = HERE / "output" / "refresh_job_log.jsonl"


def main() -> int:
    ts = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        result = orf.orchestrate("RUN_IF_STALE", orf.SCORE_VERSION, False, None)
    except Exception as exc:  # noqa: BLE001
        _log({"at": ts, "action": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
        print(f"refresh job failed: {exc}", file=sys.stderr)
        return 2

    record = {
        "at": ts,
        "action": result.get("action"),
        "stale": (result.get("staleness") or {}).get("stale"),
        "reasons": (result.get("staleness") or {}).get("reasons"),
        "served_run_seq": (result.get("latest_serving_run") or {}).get("run_seq"),
        "new_run_seq": None,
        "blocked_reason": result.get("blocked_reason"),
    }
    new_run = result.get("new_run") or {}
    if new_run:
        record["new_run_id"] = new_run.get("stored_run_id")
        record["new_run_completed"] = new_run.get("completed")
    _log(record)
    print(json.dumps(record, ensure_ascii=False))

    action = result.get("action")
    if action in ("NOT_STALE", "RECOMPUTED"):
        return 0
    # BLOCKED_DEGRADED_INGESTION / RECOMPUTE_INCOMPLETE: the score could not be
    # refreshed. Signal the scheduler rather than exiting quietly green.
    return 1


def _log(record: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
