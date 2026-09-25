"""Report-chain TTM tests (canonical-only, Class-B recovery).

Run:
    set CDF_PILOT_DB=company_financial_analytics_shadow_v121
    python -m pytest canonical_postgres_v1_2_1/analytics_canonical_v1/tests -q
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
PKG = BASE / "analytics_canonical_v1"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(BASE / "migration_tools"))

import compute_metrics as CM  # noqa: E402
import report_chain_ttm as RC  # noqa: E402


def _rep():
    # latest 1405/06 cumulative 100; prior annual 1404/12 = 90; prior interim 1404/06 = 40
    return {
        (1405, 6): {"operating_profit": {1: 100.0}},
        (1404, 12): {"operating_profit": {1: 90.0}},
        (1404, 6): {"operating_profit": {1: 40.0}},
    }


def test_formula_correctness():
    assert RC.chain_ttm(_rep(), "operating_profit", 1405, 6)[0] == 150.0  # 90 + 100 - 40


def test_full_year_direct_and_chain():
    rep = {(1405, 12): {"operating_profit": {1: 120.0}}}
    assert RC.direct_ttm(rep, "operating_profit", 1405, 12)[0] == 120.0
    assert RC.resolve_ttm(rep, "operating_profit", 1405, 12)[0] == 120.0


def test_direct_wins_when_valid():
    rep = {(1405, 6): {"operating_profit": {1: 100.0, 2: 30.0, 3: 80.0}},
           (1404, 12): {"operating_profit": {1: 999.0}},
           (1404, 6): {"operating_profit": {1: 999.0}}}
    v, prov = RC.resolve_ttm(rep, "operating_profit", 1405, 6)
    assert v == 150.0 and prov == RC.PROV_DIRECT       # 100 + 80 - 30, chain ignored


def test_missing_leg_returns_null_and_reason():
    rep = {(1405, 6): {"operating_profit": {1: 100.0}}, (1404, 6): {"operating_profit": {1: 40.0}}}
    v, prov = RC.resolve_ttm(rep, "operating_profit", 1405, 6)
    assert v is None and prov == RC.PROV_NO_ANNUAL
    rep2 = {(1405, 6): {"operating_profit": {1: 100.0}}, (1404, 12): {"operating_profit": {1: 90.0}}}
    v2, prov2 = RC.resolve_ttm(rep2, "operating_profit", 1405, 6)
    assert v2 is None and prov2 == RC.PROV_NO_COMPARABLE


def test_stock_metric_cannot_chain():
    rep = {(1405, 6): {"total_equity": {1: 100.0}}, (1404, 12): {"total_equity": {1: 90.0}},
           (1404, 6): {"total_equity": {1: 40.0}}}
    assert RC.chain_ttm(rep, "total_equity", 1405, 6)[0] is None
    v, prov = RC.resolve_ttm(rep, "total_equity", 1405, 6)
    assert v is None and prov == RC.PROV_INSUFFICIENT


def test_zero_and_negative_values():
    rep = {(1405, 9): {"net_profit": {1: 0.0}}, (1404, 12): {"net_profit": {1: -50.0}},
           (1404, 9): {"net_profit": {1: -30.0}}}
    assert RC.chain_ttm(rep, "net_profit", 1405, 9)[0] == -20.0


def test_no_forbidden_dependency_in_report_chain():
    out = []
    with open(PKG / "report_chain_ttm.py", "r", encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    code = " ".join(out)
    for tok in ["Product1", "NPUnitRatio", "compat_v37", "sqlserver", "legacy_v37_"]:
        assert tok not in code
    for tok in (r"\bOpK\b", r"\bOpAmt\b", r"\bOpAbs\b"):
        assert not re.search(tok, code)


def test_units_contract_still_irr():
    spec = json.loads((PKG / "metric_spec.json").read_text(encoding="utf-8"))
    assert spec["units_contract"]["monetary"] == "IRR"
    assert "STOCK_POINT_IN_TIME" in spec["flow_types"]
    assert "total_equity" in spec["flow_types"]["REPORT_CHAIN_TTM"]["forbidden_for"]


def _engine():
    return CM.Engine(dt.date(2026, 9, 24), dt.datetime.fromisoformat("2026-09-24T20:41:02+00:00"))


def test_pit_cutoff_excludes_future_reports():
    eng = _engine()
    eng.load()
    for st in eng.stmt:
        assert st["period_end_date"] <= eng.as_of, "future report leaked into report index"


def test_superseded_reports_excluded():
    eng = _engine()
    eng.stmt = [
        {"company_id": "c1", "statement_type": "income_statement", "period_end_date": dt.date(2026, 6, 21),
         "fiscal_year": 1405, "fiscal_month": 3, "is_restated": False, "version_no": 1,
         "collected_at": None, "metric_code": "operating_profit", "period_order": 1,
         "canonical_value": 100.0, "canonical_unit": "rial", "report_id": "old"},
        {"company_id": "c1", "statement_type": "income_statement", "period_end_date": dt.date(2026, 6, 21),
         "fiscal_year": 1405, "fiscal_month": 3, "is_restated": False, "version_no": 2,
         "collected_at": None, "metric_code": "operating_profit", "period_order": 1,
         "canonical_value": 111.0, "canonical_unit": "rial", "report_id": "new"},
    ]
    eng.superseded = {"old"}
    idx = eng.report_index()
    assert idx["c1"][(1405, 3)]["operating_profit"][1] == 111.0


def test_deterministic_repeated_run_after_chain():
    a = _engine(); a.compute()
    b = _engine(); b.compute()
    assert a.digest() == b.digest()
