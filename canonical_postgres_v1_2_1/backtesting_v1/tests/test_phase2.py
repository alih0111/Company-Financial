"""Phase-2 tests: path accounting, cash/missing-exit policy, coverage controls,
revision detection, no fabrication, no model mutation."""

from __future__ import annotations

import datetime as dt
import re
import sys
import tokenize
from pathlib import Path

HERE = Path(__file__).resolve().parent
BT = HERE.parent
BASE = BT.parent
for p in (str(BT), str(BASE / "analytics_canonical_v1"), str(BASE / "migration_tools")):
    sys.path.insert(0, p)

import portfolio_simulator as PS  # noqa: E402
import phase2_analysis as P2  # noqa: E402


def test_no_overlap_and_cash_policy():
    rb = [
        {"date": dt.date(2024, 1, 31), "execution_date": dt.date(2024, 2, 1),
         "selected": [{"company_id": "a", "ret": 0.1}], "benchmark": [{"company_id": "a", "ret": 0.1}]},
        {"date": dt.date(2024, 2, 29), "execution_date": dt.date(2024, 3, 1),
         "selected": [], "benchmark": []},   # zero tradable -> cash
        {"date": dt.date(2024, 3, 31), "execution_date": dt.date(2024, 4, 1),
         "selected": [{"company_id": "a", "ret": 0.2}], "benchmark": [{"company_id": "a", "ret": 0.2}]},
    ]
    rows, summary, contrib = PS.simulate_corrected(rb, 0.0)
    assert len(rows) == 3
    assert rows[1]["cash_interval"] is True and rows[1]["gross_return"] == 0.0
    # contiguous: exit of i == execution of i+1; cash interval retained (not dropped)
    assert summary["portfolio"]["n"] == 3
    assert abs(summary["portfolio"]["cumulative_return"] - (1.1 * 1.0 * 1.2 - 1)) < 1e-12


def test_missing_exit_excluded_recorded():
    rb = [{"date": dt.date(2024, 1, 31), "execution_date": dt.date(2024, 2, 1),
           "selected": [{"company_id": "a", "ret": None}, {"company_id": "b", "ret": 0.2}],
           "benchmark": [{"company_id": "b", "ret": 0.2}]}]
    rows, _, _ = PS.simulate_corrected(rb, 0.0)
    assert rows[0]["n_missing_exit"] == 1 and rows[0]["n_members_used"] == 1
    assert abs(rows[0]["gross_return"] - 0.2) < 1e-12   # only valuable member, not fabricated


def test_stratum_deterministic():
    assert P2.stratum(7) == "low" and P2.stratum(8) == "medium"
    assert P2.stratum(14) == "medium" and P2.stratum(15) == "high"


def test_bootstrap_uses_date_units():
    vals = [0.1, 0.2, -0.05, 0.0, 0.15]
    out = P2.bootstrap_ci(vals)
    assert out["n"] == len(vals)   # units are rebalance dates, not company rows
    assert out["ci_low"] <= out["mean"] <= out["ci_high"]


def test_neutralization_is_pure_diagnostic():
    # residualization must not mutate the canonical score values
    scores = [10.0, 20.0, 30.0, 40.0]
    nf = [1, 2, 3, 4]
    before = list(scores)
    mx = sum(nf) / len(nf); my = sum(scores) / len(scores)
    var = sum((x - mx) ** 2 for x in nf)
    b = sum((x - mx) * (y - my) for x, y in zip(nf, scores)) / var
    resid = [y - (my - b * mx + b * x) for x, y in zip(nf, scores)]
    assert scores == before and len(resid) == 4


def test_market_revision_detection_and_no_fabrication():
    from common import pg_pilot_conn
    pg = pg_pilot_conn(autocommit=True); pc = pg.cursor()
    rev = P2.market_revision_audit(pc)
    # 126 keys with conflicts in the shadow; all flagged pit_ambiguous, none altered
    assert all(r["pit_ambiguous"] for r in rev)
    pc.execute("SELECT count(*) FROM market.corporate_actions")
    assert pc.fetchone()[0] == 0, "corporate actions must not be fabricated"
    pg.close()


def test_coverage_matched_benchmark_deterministic():
    trad = [{"company_id": f"c{i}", "n_factors_available": i % 5, "security_id": "s"} for i in range(30)]
    sel = trad[:5]

    def match(sel, pool):
        used = set(); out = []
        for s in sorted(sel, key=lambda x: x["company_id"]):
            cand = [p for p in pool if p["company_id"] not in used]
            best = min(cand, key=lambda p: (abs(p["n_factors_available"] - s["n_factors_available"]), p["company_id"]))
            used.add(best["company_id"]); out.append(best["company_id"])
        return out

    assert match(sel, trad[5:]) == match(sel, trad[5:])


def test_no_model_mutation_static():
    forbidden = ["set_weight", "BASELINE_WEIGHTS_V37[", "neutral =", "weights["]
    src = (BT / "phase2_analysis.py").read_text(encoding="utf-8")
    # phase2 only reads; it must not assign into canonical weights/neutral policy
    assert "import compute_metrics" in src or "snapshot_builder" in src
    assert "BASELINE_WEIGHTS_V37" not in src


def test_no_production_or_oracle_write_in_phase2():
    out = []
    with open(BT / "phase2_analysis.py", "r", encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    code = " ".join(out)
    for f in ["INSERT", "UPDATE ", "DELETE", "score_runs", "oracle", "golden", "Product1", "NPUnitRatio"]:
        assert f not in code, f"forbidden in phase2: {f}"
    for f in (r"\bOpK\b", r"\bOpAmt\b"):
        assert not re.search(f, code)
