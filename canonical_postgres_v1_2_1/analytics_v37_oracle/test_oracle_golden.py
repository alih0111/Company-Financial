"""Golden Regression Oracle test.

Fails if the frozen compat semantics change without an intentional
``freeze_oracle.py`` update (which rewrites golden_hash.txt).

Run:
    python -m pytest canonical_postgres_v1_2_1/analytics_v37_oracle -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "analytics_v37_compat"))
sys.path.insert(0, str(BASE / "migration_tools"))

import compute_v37_legacy_full as V  # noqa: E402

GOLDEN_HASH = (HERE / "golden_hash.txt").read_text(encoding="utf-8").strip()


def test_population_is_exactly_276():
    metrics = V.build_metrics()
    assert len(metrics) == 276
    ref = list(V.csv.DictReader(open(BASE / "analytics_parity/reference/v37_full_snapshot.csv", encoding="utf-8-sig")))
    assert {r["CompanyID"] for r in ref} == set(metrics.keys())


def test_golden_hash_stable():
    metrics = V.build_metrics()
    assert V.golden_hash(metrics) == GOLDEN_HASH, (
        "v3.7 oracle output changed. If intentional, re-run "
        "analytics_v37_oracle/freeze_oracle.py; otherwise a frozen semantic regressed."
    )


def test_golden_output_shape():
    payload = json.loads((HERE / "golden_output.json").read_text(encoding="utf-8"))
    assert len(payload) == 276
    sample = next(iter(payload.values()))
    for f in ("QuantScore", "TTMNetProfit", "SalesGrowth12M", "PERank"):
        assert f in sample
    assert len(V.FACTOR_RANKS) == 21
