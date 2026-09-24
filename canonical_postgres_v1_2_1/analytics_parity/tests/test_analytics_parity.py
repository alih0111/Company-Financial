"""Analytics parity safety tests (run against the shadow DB).

Run:
    $env:CDF_PILOT_DB="company_financial_analytics_shadow_v121"
    python -m pytest analytics_parity/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn  # noqa: E402

CTX = json.loads((BASE / "analytics_parity" / "reference_context.json").read_text(encoding="utf-8"))


def _one(sql, params=()):
    c = pg_pilot_conn(autocommit=True)
    try:
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0]
    finally:
        c.close()


def test_reference_context_frozen():
    assert CTX["analysis_cutoff_at_utc"] == CTX["captured_at_utc"]
    assert CTX["production_view_score_version"] == "v3.7"
    assert CTX["reference_row_count"] > 0


def test_point_in_time_no_future_observations_after_cutoff():
    cutoff = CTX["analysis_cutoff_at_utc"]
    future = _one("SELECT count(*) FROM market.price_observations WHERE collected_at > %s", (cutoff,))
    assert future == 0, f"{future} observations after cutoff would leak into analytics"


def test_canonical_units_are_rial():
    bad = _one("SELECT count(*) FROM fundamentals.financial_facts WHERE canonical_unit NOT IN ('rial','rial_per_share')")
    assert bad == 0


def test_analytics_outputs_immutable_flag_row_exists():
    n = _one("SELECT count(*) FROM analytics.score_runs WHERE score_version='v3.7-compat'")
    assert n >= 1
