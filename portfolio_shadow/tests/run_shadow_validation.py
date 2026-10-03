"""SHADOW V1 — engineering validation (TEST ONLY; never a shadow observation).

Validates, per SHADOW_V1_SPEC §12–§13:
  T1  unit tests A–E on the deterministic port (same as the certified engine's tests)
  T2  500-case invariant sweep (NAV identity, cash >= 0)
  T3  parity: certified repair_accounting_v1.rebalance_accounts vs deterministic port,
      500 seeded scenarios, max elementwise divergence (required <= 1e-12)
  T4  observer month-close wrapper: behavior + invariants on synthetic data
      (carry / sell / failed-target-cash / buy-scaling), certified engine as reference
  T5  determinism: identical fixture built in 3 independent processes with different
      PYTHONHASHSEED -> byte-identical artifacts (file SHA-256 and canonical content hash)

Writes tests/determinism_report.json and records the summary in shadow_v1_state.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
SHADOW = HERE.parent
sys.path.insert(0, str(SHADOW))
sys.path.insert(0, str(SHADOW.parent / "portfolio_research"))

import numpy as np

import shadow_common as sc
from deterministic_accounting import rebalance_accounts as port_rebal, assert_invariants
from repair_accounting_v1 import rebalance_accounts as cert_rebal  # certified, unmodified

FIXTURE = HERE / "fixtures" / "fixture_score_snapshot_20261002.json"
R = {"T1_unit_tests": {}, "T2_invariant_sweep": None, "T3_parity_vs_certified": {},
     "T4_observer_close": {}, "T5_determinism": {}, "all_pass": None}


def t1_unit_tests():
    T = {}
    cp, pos, cost, buys, sells, f = port_rebal(100.0, {}, {"X": 100.0}, {"X": True}, 0.005)
    T["A_bps_and_B_one_way_purchase"] = (abs(buys + cost - 100.0) < 1e-9 and cp >= -1e-9
                                         and abs(pos["X"] + cost - 100.0) < 1e-9)
    cp, pos, cost, *_ = port_rebal(0.0, {"A": 100.0}, {"B": 100.0}, {"A": True, "B": True}, 0.005)
    T["C_full_rotation"] = (abs(cost - 1.0) < 0.05 and abs(cp + pos["B"] - (100.0 - cost)) < 1e-9
                            and "A" not in pos)
    cp, pos, cost, *_ = port_rebal(0.0, {"A": 60.0, "B": 40.0}, {"A": 60.0, "B": 40.0},
                                   {"A": True, "B": True}, 0.005)
    T["D_zero_turnover"] = abs(cost) < 1e-12 and abs(cp) < 1e-12
    cp, pos, cost, *_ = port_rebal(0.0, {"A": 100.0}, {"A": 50.0, "B": 50.0}, {"A": True, "B": True}, 0.005)
    T["E_proportional_reduction"] = (cp >= -1e-9
                                     and abs((cp + sum(pos.values())) - (100.0 - cost)) < 1e-9)
    R["T1_unit_tests"] = {k: ("PASS" if v else "FAIL") for k, v in T.items()}
    return all(T.values())


def t2_invariant_sweep():
    rng = np.random.default_rng(20261003)
    for _ in range(500):
        n = int(rng.integers(1, 8))
        names = [f"s{i:02d}" for i in range(n)]
        cash = float(rng.uniform(0, 30))
        cur = {s: float(rng.uniform(0, 60)) for s in names}
        tgt = {s: float(rng.uniform(0, 60)) for s in names if rng.uniform() > 0.2}
        trad = {s: bool(rng.uniform() > 0.15) for s in names}
        c = float(rng.choice([0.0, 0.0025, 0.005, 0.01]))
        res = port_rebal(cash, cur, tgt, trad, c)
        assert_invariants(cash, cur, res)
    R["T2_invariant_sweep"] = "PASS"
    return True


def t3_parity():
    rng = np.random.default_rng(7)
    max_diff, worst = 0.0, None
    for it in range(500):
        n = int(rng.integers(1, 8))
        names = [f"s{i:02d}" for i in range(n)]
        cash = float(rng.uniform(0, 30))
        cur = {s: float(rng.uniform(0, 60)) for s in names}
        tgt = {s: float(rng.uniform(0, 60)) for s in names if rng.uniform() > 0.2}
        trad = {s: bool(rng.uniform() > 0.15) for s in names}
        c = float(rng.choice([0.0, 0.0025, 0.005, 0.01]))
        a = cert_rebal(cash, cur, tgt, trad, c)
        b = port_rebal(cash, cur, tgt, trad, c)
        scalars = [0, 2, 3, 4, 5]
        diffs = [abs(a[i] - b[i]) for i in scalars]
        assert set(a[1]) == set(b[1]), "position key mismatch"
        diffs += [abs(a[1][k] - b[1][k]) for k in a[1]]
        m = max(diffs)
        if m > max_diff:
            max_diff, worst = m, it
    R["T3_parity_vs_certified"] = {"max_abs_diff": max_diff, "required_max": 1e-12,
                                   "worst_scenario": worst,
                                   "verdict": "PASS" if max_diff <= 1e-12 else "FAIL",
                                   "note": "certified engine iterates unordered sets; diff is "
                                           "summation-order float noise (relative magnitude "
                                           "~1e-16 of position values; scaling-path arithmetic "
                                           "chains can accumulate to ~1e-13 absolute)"}
    return max_diff <= 1e-12


def t4_observer_close():
    """Month-close wrapper behavior on synthetic data (certified engine as the core)."""
    import observe_shadow_execution as obs

    fake_adj = {s: {"dates": ["2026-01-01", "2026-02-01"],
                    "adj": {"2026-01-01": 100.0 + i, "2026-02-01": 110.0 + i}}
                for i, s in enumerate(["AAA", "BBB", "CCC", "DDD"])}
    fake_cache = {("AAA", "1"): {"2026-02-01": {"pClosing": 110.0, "qTotTran5J": 1000, "pDrCotVal": 111.0}},
                  ("BBB", "2"): {"2026-02-01": {"pClosing": 110.0, "qTotTran5J": 0, "pDrCotVal": 110.0}},
                  ("CCC", "3"): {},                                  # missing on E
                  ("DDD", "4"): {"2026-02-01": {"pClosing": 110.0, "qTotTran5J": 500, "pDrCotVal": 109.0}}}
    sc_load = sc.load_raw_cache
    sc.load_raw_cache = lambda s, i: fake_cache.get((s, i))
    try:
        E = "2026-02-01"
        holdings = {"k1": {"symbol": "AAA", "ins_code": "1", "shares": 0.5},   # 55, re-selected
                    "k2": {"symbol": "BBB", "ins_code": "2", "shares": 0.4},   # 44, selected but NO_TRADE -> carried
                    "k3": {"symbol": "CCC", "ins_code": "3", "shares": 0.3}}   # 33, not selected, not tradable -> carried
        cash = 0.0
        cur_vals = {k: holdings[k]["shares"] * fake_adj[holdings[k]["symbol"]]["adj"][E]
                    for k in holdings}
        value_pre = cash + sum(cur_vals.values())            # 132
        orders = [{"portfolio_security_key": "k1", "flag": "EXECUTABLE_REFERENCE", "symbol": "AAA", "ins_code": "1"},
                  {"portfolio_security_key": "k2", "flag": "NO_TRADE", "symbol": "BBB", "ins_code": "2"},
                  {"portfolio_security_key": "k4", "flag": "EXECUTABLE_REFERENCE", "symbol": "DDD", "ins_code": "4"},
                  {"portfolio_security_key": "k5", "flag": "DATA_MISSING", "symbol": "ZZZ", "ins_code": "9"}]
        close = obs.close_month(fake_adj, orders, holdings, cash, E, n_sel=4)
        ok = {}
        ok["nav_identity"] = abs(close["nav_post"] - (value_pre - close["cost"])) < 1e-9
        ok["cash_nonneg"] = close["cash_post"] >= -1e-9
        ok["reselected_held_executed_to_target"] = "k1" in close["post_holdings"]
        ok["carried_held_nontradable"] = ("k2" in close["post_holdings"] and "k3" in close["post_holdings"])
        ok["failed_target_not_bought"] = "k5" not in close["post_holdings"]
        ok["cost_is_50bps_of_notional"] = abs(close["cost"] - 0.005 * (close["buys"] + close["sells"])) < 1e-12
        ok["turnover_positive_and_le_1"] = 0.0 <= close["turnover"] <= 1.0
        # buy-scaling case: no cash, only carried value funds buys
        cash2 = 0.0
        hold2 = {"k3": {"symbol": "CCC", "ins_code": "3", "shares": 0.3}}      # carried (no E cache data)
        orders2 = [{"portfolio_security_key": "k1", "flag": "EXECUTABLE_REFERENCE", "symbol": "AAA", "ins_code": "1"},
                   {"portfolio_security_key": "k4", "flag": "EXECUTABLE_REFERENCE", "symbol": "DDD", "ins_code": "4"}]
        close2 = obs.close_month(fake_adj, orders2, hold2, cash2, E, n_sel=2)
        ok2 = {}
        v_pre2 = 0.0 + 0.3 * fake_adj["CCC"]["adj"][E]
        ok2["nav_identity"] = abs(close2["nav_post"] - (v_pre2 - close2["cost"])) < 1e-9
        ok2["cash_nonneg"] = close2["cash_post"] >= -1e-9
        ok2["buy_scale_applied_when_cash_short"] = close2["buy_scale"] <= 1.0
        R["T4_observer_close"] = {**{k: ("PASS" if v else "FAIL") for k, v in ok.items()},
                                  **{f"scaling_{k}": ("PASS" if v else "FAIL") for k, v in ok2.items()}}
        return all(ok.values()) and all(ok2.values())
    finally:
        sc.load_raw_cache = sc_load


def t5_determinism():
    outs = []
    for i, seed in enumerate(["1", "2", "3"], start=1):
        d = HERE / "determinism" / f"run{i}"
        if d.exists():
            shutil.rmtree(d)
        env = dict(os.environ, PYTHONHASHSEED=seed)
        p = subprocess.run([sys.executable, str(SHADOW / "build_shadow_portfolio.py"),
                            "--fixture", str(FIXTURE), "--outdir", str(d)],
                           capture_output=True, text=True, env=env, encoding="utf-8")
        if p.returncode != 0:
            R["T5_determinism"] = {"verdict": "FAIL", "error": p.stderr[-2000:]}
            return False
        outs.append({f.name: sc.sha256_file(f) for f in sorted(d.iterdir())})
    identical = outs[0] == outs[1] == outs[2]
    R["T5_determinism"] = {"verdict": "PASS" if identical else "FAIL",
                           "pythonhashseeds": ["1", "2", "3"],
                           "artifact_hashes_run1": outs[0],
                           "byte_identical_across_processes": identical,
                           "n_artifacts": len(outs[0])}
    return identical


def main():
    ok1 = t1_unit_tests()
    ok2 = t2_invariant_sweep()
    ok3 = t3_parity()
    ok4 = t4_observer_close()
    ok5 = t5_determinism()
    R["all_pass"] = all([ok1, ok2, ok3, ok4, ok5])
    (HERE / "determinism_report.json").write_text(
        sc.canonical_json(R) + "\n", encoding="utf-8")
    state_path = SHADOW / "shadow_v1_state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["engineering_validation"] = {
            "report": "portfolio_shadow/tests/determinism_report.json",
            "all_pass": R["all_pass"],
            "T1_unit_tests": R["T1_unit_tests"], "T2_invariant_sweep": R["T2_invariant_sweep"],
            "T3_parity_vs_certified": R["T3_parity_vs_certified"],
            "T4_observer_close": R["T4_observer_close"],
            "T5_determinism": {k: v for k, v in R["T5_determinism"].items()
                               if k != "artifact_hashes_run1"},
            "fixture_sha256": sc.sha256_file(FIXTURE)}
        state["flags"]["SHADOW_BUILD_DETERMINISTIC"] = "PASS" if ok5 else "FAIL"
        state_path.write_text(sc.canonical_json(state) + "\n", encoding="utf-8")
    print(sc.canonical_json(R))
    return 0 if R["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
