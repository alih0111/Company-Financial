"""Read-only Decision #1 readiness check (V1.1 §2, §9).

Enumerates every completed analytics.score_runs row after the V1.1 freeze
(2026-10-03T19:40:34Z) and reports whether any could satisfy the frozen
Decision #1 rule. Writes nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import psycopg

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
FREEZE = "2026-10-03 19:40:34+00"

with psycopg.connect(DSN) as conn:
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM analytics.score_runs "
        "WHERE completed_at > %s::timestamptz ORDER BY completed_at",
        (FREEZE,),
    )
    cols = [d.name for d in cur.description]
    post = [dict(zip(cols, r)) for r in cur.fetchall()]

    # any completed canonical-v1-dev runs at all (latest 12, for context)
    cur.execute(
        "SELECT id AS run_id, score_version, status, as_of_date, completed_at "
        "FROM analytics.score_runs "
        "WHERE score_version = 'canonical-v1-dev' AND status = 'completed' "
        "ORDER BY completed_at DESC LIMIT 12"
    )
    recent = [
        dict(zip(("run_id", "score_version", "status", "as_of_date", "completed_at"), r))
        for r in cur.fetchall()
    ]

print(f"post_freeze_completed_runs: {len(post)}")
for r in post:
    slim = {
        k: (str(v) if hasattr(v, "isoformat") else v)
        for k, v in r.items()
        if k in (
            "id", "score_version", "status", "as_of_date", "completed_at",
            "code_version", "source_cutoff_at", "parameters",
        )
    }
    print(json.dumps(slim, ensure_ascii=False, default=str))

print(f"recent_completed_canonical_v1_dev: {len(recent)}")
for r in recent:
    print(f"  {r['completed_at']}  as_of={r['as_of_date']}  run={r['run_id']}")
