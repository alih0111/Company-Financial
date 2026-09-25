"""Canonical v1 regression tests.

Run:
    set CDF_PILOT_DB=company_financial_analytics_shadow_v121
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests -q
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
PKG = BASE / "analytics_canonical_v1"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(BASE / "migration_tools"))

import compute_metrics as CM  # noqa: E402
from data_quality import DQ  # noqa: E402


def _code_tokens(path: Path) -> str:
    """Source with comments/docstrings removed, so static checks ignore prose."""
    import io
    import tokenize
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    return " ".join(out)


def test_no_sqlserver_or_legacy_dependency():
    code = _code_tokens(PKG / "compute_metrics.py")
    forbidden = ["sqlserver_conn", "Product1", "Product2", "Product3",
                 "NPUnitRatio", "compat_v37", "legacy_v37_"]
    for tok in forbidden:
        assert tok not in code, f"forbidden legacy dependency {tok!r} found in engine code"
    for tok in (r"\bOpK\b", r"\bOpAmt\b", r"\bOpAbs\b", r"\bOpRaw\b"):
        assert not re.search(tok, code), f"forbidden legacy heuristic {tok} found in engine code"


def test_units_contract_declared():
    import json
    spec = json.loads((PKG / "metric_spec.json").read_text(encoding="utf-8"))
    assert spec["units_contract"]["scale_detection"] == "FORBIDDEN"
    assert spec["units_contract"]["monetary"] == "IRR"
    assert spec["score_version"] == "canonical-v1-dev"


def test_ttm_edge_cases():
    eng = CM.Engine(dt.date(2026, 9, 24), dt.datetime.fromisoformat("2026-09-24T20:41:02+00:00"))
    rep = {(1405, 6): {"net_profit": {1: 100.0, 2: 40.0, 3: 90.0}}}
    assert eng.ttm(rep, "net_profit", 1405, 6) == 150.0          # 100 + 90 - 40
    assert eng.ttm(rep, "net_profit", 1405, 7) is None            # missing period
    rep12 = {(1404, 12): {"net_profit": {1: 70.0, 2: 50.0, 3: 45.0}}}
    assert eng.ttm(rep12, "net_profit", 1404, 12) == 70.0         # month 12 => current
    assert eng.ttm(rep, "revenue", 1405, 6) is None               # metric absent


def test_dq_score_and_severity():
    dq = DQ()
    dq.add("missing_price")
    dq.add("unresolved_identity")
    assert dq.score(True, True, False, True, False) == 0.65
    assert dq.as_dict()["max_severity"] == "critical"
    assert dq.flags == ["missing_price", "unresolved_identity"]


def _engine():
    return CM.Engine(dt.date(2026, 9, 24),
                     dt.datetime.fromisoformat("2026-09-24T20:41:02+00:00"))


def test_deterministic_run():
    a = _engine(); a.compute()
    b = _engine(); b.compute()
    assert a.digest() == b.digest()


def test_population_policy_and_funds_excluded():
    eng = _engine(); m = eng.compute()
    assert len(m) > 200
    # funds (no income statement, no monthly) must not be subjects
    pg = __import__("common").pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    cur.execute("SELECT id::text FROM core.securities WHERE codal_symbol IN ('مثقال','یاقوت')")
    for (sid,) in cur.fetchall():
        cur.execute("SELECT company_id::text FROM core.securities WHERE id=%s", (sid,))
        cid = cur.fetchone()[0]
        assert cid not in m, "fund must be excluded from default equity population"
    pg.close()


def test_pit_cutoff_excludes_future_market_observations():
    eng = _engine(); eng.load()
    for p in eng.prices:
        assert p["collected_at"] <= eng.cutoff
