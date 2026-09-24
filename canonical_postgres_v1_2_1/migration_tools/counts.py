"""Print target row counts (pilot DB)."""
from __future__ import annotations
import json
import sys
from common import PILOT_DIR, pg_pilot_conn

TABLES = [
    "core.companies", "core.securities", "core.security_aliases", "core.legacy_entity_map",
    "ingestion.reports", "ingestion.report_versions", "ingestion.parse_runs",
    "fundamentals.monthly_activities", "fundamentals.financial_statements",
    "fundamentals.financial_facts", "market.price_observations",
]


def snapshot():
    c = pg_pilot_conn(autocommit=True)
    out = {}
    with c.cursor() as cur:
        for t in TABLES:
            cur.execute(f"SELECT count(*) FROM {t}")
            out[t] = cur.fetchone()[0]
    c.close()
    return out


if __name__ == "__main__":
    snap = snapshot()
    name = sys.argv[1] if len(sys.argv) > 1 else None
    if name:
        (PILOT_DIR / f"_counts_{name}.json").write_text(json.dumps(snap), encoding="utf-8")
    print(json.dumps(snap, indent=2))
