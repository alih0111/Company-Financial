"""Analytics refresh orchestration (append-only).

This module does NOT redesign or change the analytics engine. It only:

  1. reads canonical ingestion freshness/health,
  2. determines whether recomputation is required (deterministic staleness rule),
  3. executes the existing canonical-v1 metric engine for an explicit
     as_of/source_cutoff,
  4. writes a NEW append-only score run (never overwrites),
  5. validates completion, and
  6. leaves the new completed run visible to Go reads.

Modes (CLI ``--mode``):
  * CHECK_ONLY    (default) report staleness, compute nothing
  * RUN_IF_STALE  routine intent: recompute only when stale and ingestion is healthy
  * FORCE_RUN     explicit override (never a routine default)

Usage:
  set CDF_PILOT_DB=company_financial_analytics_shadow_v121
  python orchestrate_refresh.py --mode CHECK_ONLY
  python orchestrate_refresh.py --mode RUN_IF_STALE
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE.parent

# Select the canonical database BEFORE importing the engine (common.py reads
# CDF_PILOT_DB at import time).
os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
sys.path.insert(0, str(HERE))

from compute_metrics import Engine, SCORE_VERSION, store_run  # noqa: E402
from common import pg_pilot_conn as pg_conn  # noqa: E402  (path set by compute_metrics)

INGESTION_STATUS = REPO / "ingestion_migration_v1" / "output" / "canonical_ingestion_status.json"
OUT = REPO / "integration_shadow_v1" / "output"


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def read_ingestion_health() -> dict:
    """Read the combined ingestion status artifact (no secrets)."""
    if not INGESTION_STATUS.exists():
        return {"available": False, "degraded": False, "domains": {}}
    try:
        doc = json.loads(INGESTION_STATUS.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "degraded": False, "error": str(exc), "domains": {}}
    domains = doc.get("domains", {})
    degraded = any(d.get("health") not in ("HEALTHY",) for d in domains.values())
    return {"available": True, "degraded": degraded, "domains": domains,
            "generated_at": doc.get("generated_at")}


def latest_completed_run(cur, version: str):
    cur.execute(
        """SELECT id::text, as_of_date, source_cutoff_at, completed_at, status, code_version
           FROM analytics.score_runs
           WHERE score_version=%s AND status='completed'
           ORDER BY as_of_date DESC, started_at DESC
           LIMIT 1""", (version,))
    return cur.fetchone()


def canonical_data_cutoffs(cur) -> dict:
    return {
        "monthly_latest": _one(cur, "SELECT max(period_end_date) FROM fundamentals.monthly_activities"),
        "financial_latest": _one(cur, "SELECT max(period_end_date) FROM fundamentals.financial_statements"),
        "market_latest_trade_date": _one(cur, "SELECT max(trade_date) FROM market.price_observations"),
        "market_latest_collected_at": _one(cur, "SELECT max(collected_at) FROM market.price_observations"),
        "reports_latest_collected_at": _one(cur, "SELECT max(created_at) FROM ingestion.reports"),
    }


def _as_date(v):
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v)[:10])


def _as_dt(v):
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=dt.timezone.utc)
    if isinstance(v, dt.date):
        return dt.datetime(v.year, v.month, v.day, tzinfo=dt.timezone.utc)
    text = str(v).replace(" ", "T")
    return dt.datetime.fromisoformat(text)


def evaluate_staleness(run, cutoffs: dict) -> dict:
    """Deterministic staleness rule (see ANALYTICS_REFRESH_CONTRACT.md)."""
    reasons = []
    if run is None:
        return {"stale": True, "usable_run": False, "reasons": ["no_completed_run"]}

    run_as_of = _as_date(run[1])
    run_cutoff = _as_dt(run[2])

    month = _as_date(cutoffs.get("monthly_latest"))
    fin = _as_date(cutoffs.get("financial_latest"))
    market_date = _as_date(cutoffs.get("market_latest_trade_date"))
    market_dt = _as_dt(cutoffs.get("market_latest_collected_at"))
    reports_dt = _as_dt(cutoffs.get("reports_latest_collected_at"))

    if month and run_as_of and month > run_as_of:
        reasons.append(f"monthly {month} > run as_of {run_as_of}")
    if fin and run_as_of and fin > run_as_of:
        reasons.append(f"financial {fin} > run as_of {run_as_of}")
    if market_date and run_as_of and market_date > run_as_of:
        reasons.append(f"market trade_date {market_date} > run as_of {run_as_of}")
    if market_dt and run_cutoff and market_dt > run_cutoff:
        reasons.append("market collected_at > source_cutoff_at")
    if reports_dt and run_cutoff and reports_dt > run_cutoff:
        reasons.append("reports created_at > source_cutoff_at")

    return {"stale": bool(reasons), "usable_run": True, "reasons": reasons,
            "run_as_of": str(run_as_of) if run_as_of else None,
            "run_source_cutoff_at": str(run_cutoff) if run_cutoff else None}


def choose_as_of_cutoff(cutoffs: dict):
    candidates = [
        _as_date(cutoffs.get("monthly_latest")),
        _as_date(cutoffs.get("financial_latest")),
        _as_date(cutoffs.get("market_latest_trade_date")),
    ]
    candidates = [c for c in candidates if c is not None]
    as_of = max(candidates) if candidates else dt.date.today()

    cutoff_candidates = [
        _as_dt(cutoffs.get("market_latest_collected_at")),
        _as_dt(cutoffs.get("reports_latest_collected_at")),
    ]
    cutoff_candidates = [c for c in cutoff_candidates if c is not None]
    cutoff = max(cutoff_candidates) if cutoff_candidates else dt.datetime.now(dt.timezone.utc)
    return as_of, cutoff


def run_engine(cur, as_of: dt.date, cutoff: dt.datetime, version: str, store: bool):
    eng = Engine(as_of, cutoff)
    metrics = eng.compute()
    digest = eng.digest()
    run_id = None
    if store:
        store_run(eng, metrics, as_of, cutoff, digest)
        # store_run is append-only; the newly inserted run is the most recent one.
        cur.execute(
            """SELECT id::text FROM analytics.score_runs
               WHERE score_version=%s AND status='completed'
               ORDER BY started_at DESC, as_of_date DESC LIMIT 1""", (version,))
        row = cur.fetchone()
        run_id = row[0] if row else None
    return {"population": len(metrics), "digest": digest, "stored_run_id": run_id}


def summarize_run(cur, run_id: str) -> dict:
    if not run_id:
        return {}
    cur.execute(
        """SELECT status, completed_at, code_version FROM analytics.score_runs WHERE id=%s""",
        (run_id,))
    row = cur.fetchone()
    cur.execute("SELECT count(*) FROM analytics.company_scores WHERE run_id=%s", (run_id,))
    comp = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM analytics.factor_scores WHERE run_id=%s", (run_id,))
    fac = cur.fetchone()[0]
    return {"status": row[0] if row else None,
            "completed": bool(row and row[0] == "completed" and row[1] is not None),
            "code_version": row[2] if row else None,
            "company_scores": comp, "factor_scores": fac}


def orchestrate(mode: str, version: str, allow_degraded: bool, json_out: Path | None):
    health = read_ingestion_health()
    conn = pg_conn()
    try:
        cur = conn.cursor()
        run = latest_completed_run(cur, version)
        cutoffs = canonical_data_cutoffs(cur)
        staleness = evaluate_staleness(run, cutoffs)
        result = {
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "mode": mode,
            "score_version": version,
            "ingestion_health": health,
            "latest_completed_run": {
                "id": run[0] if run else None,
                "as_of_date": str(run[1]) if run else None,
                "source_cutoff_at": str(run[2]) if run else None,
            },
            "data_cutoffs": {k: (str(v) if v is not None else None) for k, v in cutoffs.items()},
            "staleness": staleness,
            "action": "CHECK_ONLY",
            "recomputed": False,
            "new_run": None,
            "blocked_reason": None,
        }

        if mode == "CHECK_ONLY":
            result["action"] = "CHECK_ONLY"
        elif mode == "RUN_IF_STALE":
            if not staleness["stale"]:
                result["action"] = "NOT_STALE"
            elif health.get("degraded") and not allow_degraded:
                result["action"] = "BLOCKED_DEGRADED_INGESTION"
                result["blocked_reason"] = "canonical ingestion health is not HEALTHY"
            else:
                result["action"] = "RECOMPUTE"
        elif mode == "FORCE_RUN":
            result["action"] = "RECOMPUTE"
        else:
            raise SystemExit(f"unknown mode {mode!r}")

        if result["action"] == "RECOMPUTE":
            as_of, cutoff = choose_as_of_cutoff(cutoffs)
            result["recompute_as_of"] = str(as_of)
            result["recompute_cutoff"] = str(cutoff)
            outcome = run_engine(cur, as_of, cutoff, version, store=True)
            result["recomputed"] = True
            result["new_run"] = {**outcome, **summarize_run(cur, outcome.get("stored_run_id"))}
            result["action"] = "RECOMPUTED" if result["new_run"].get("completed") else "RECOMPUTE_INCOMPLETE"
        return result
    finally:
        conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="orchestrate_refresh")
    ap.add_argument("--mode", default="CHECK_ONLY",
                    choices=["CHECK_ONLY", "RUN_IF_STALE", "FORCE_RUN"])
    ap.add_argument("--score-version", default=SCORE_VERSION)
    ap.add_argument("--allow-degraded", action="store_true")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    result = orchestrate(args.mode, args.score_version, args.allow_degraded, None)
    out = Path(args.json_out) if args.json_out else OUT / "analytics_refresh_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
