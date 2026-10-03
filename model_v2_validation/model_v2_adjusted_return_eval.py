"""PHASE 11: re-run the frozen factor/model evaluation on ADJUSTED returns.

Uses the SAME frozen harness, factors, weights, missing policy, TOP_N, costs,
periods and the preregistered R1-R4 gate — nothing is retuned. The ONLY change
is the forward-return target: FORWARD_RETURN_ADJUSTED_V1 (Mode-1 adjusted,
event-factored) instead of the legacy vendor-based levels.

Worlds evaluated on adjusted returns:
  legacy-perank  (frozen CSV factor ranks)
  direct-perank-v2 (PERank_DIRECT_V2 substitution, identical to the V2 rebaseline)

Holdout 2025 / Forward 2026 are computed descriptively only. Output:
  output/model_v2_adjusted_return_eval.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_v2 as M  # noqa: E402
from model_v2_direct_rebaseline_v2 import (  # noqa: E402  frozen machinery
    EXP_NAMES, V21_NAMES, direct_ranks, gate, rows_with_direct, run, symbol_map)

ADJUSTED = Path(r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\backtesting_v1\output\phase3_signals_adjusted_v1.csv")
PREV = HERE / "output" / "model_v2_direct_perank_rebaseline_v2.json"
OUT = HERE / "output" / "model_v2_adjusted_return_eval.json"
VERSION = "MODEL_V2_ADJUSTED_RETURN_EVAL"


def perank_factor_ic(rows, dmap, smap, horizon="ret_63"):
    """Cross-sectional Spearman(PERank_DIRECT_V2, fwd ret) per frozen period."""
    from model_v2 import spearman
    PERIODS = M.PERIODS
    per = {p: [] for p in PERIODS}
    by_date = {}
    for r in rows:
        sym = smap.get((r["company_id"], r["signal_date"]))
        v = dmap.get((sym, r["signal_date"]))
        ret = r.get(horizon)
        if v is None or ret is None:
            continue
        by_date.setdefault(r["signal_date"], []).append((v, ret))
    for ds, pairs in by_date.items():
        if len(pairs) < 5:
            continue
        y = int(ds[:4])
        for p, (a, b) in PERIODS.items():
            if a <= y <= b:
                per[p].append(spearman([x[0] for x in pairs], [x[1] for x in pairs]))
                break
    return {p: {"n": len(v), "mean": float(np.mean(v)) if v else None} for p, v in per.items()}


def main() -> int:
    rows_adj = M.load_signals(ADJUSTED)
    dmap = direct_ranks()
    smap = symbol_map()
    rows_direct_adj, hit, lost = rows_with_direct(rows_adj, dmap, smap)
    print(f"rows={len(rows_adj)} direct_PERank_hits={hit} legacy_perank_lost={lost}")

    ev_l, cfg_l = run(rows_adj, "legacy-perank+adjusted-returns")
    ev_d, cfg_d = run(rows_direct_adj, "direct-perank-v2+adjusted-returns")
    g_l, g_d = gate(ev_l, V21_NAMES), gate(ev_d, V21_NAMES)
    g_exp_l, g_exp_d = gate(ev_l, EXP_NAMES), gate(ev_d, EXP_NAMES)

    v21_elig = [n for n in V21_NAMES if g_d["candidates"][n]["eligible"]]
    exp_elig = [n for n in EXP_NAMES if g_exp_d["candidates"][n]["eligible"]]
    exp_near = [n for n in EXP_NAMES if g_exp_d["candidates"][n]["rules_passed"] >= 3]

    # factor IC of PERank_DIRECT_V2 under both targets
    ic_adj = perank_factor_ic(rows_adj, dmap, smap, "ret_63")
    rows_raw = M.load_signals()
    ic_raw = perank_factor_ic(rows_raw, dmap, smap, "ret_63")

    doc = {
        "version": VERSION,
        "return_target": "FORWARD_RETURN_ADJUSTED_V1 (raw x event factors; capital + dividends)",
        "perank_source": "PERank_DIRECT_V2 (Stage-4 ambiguity-resolved)",
        "missing_policy": "drop_unavailable_renormalize (unchanged)",
        "periods": M.PERIODS,
        "coverage": {"rows": len(rows_adj), "direct_perank_rows": hit, "legacy_perank_lost": lost},
        "factor_ic_perank_direct_v2": {"ret_63_adjusted": ic_adj, "ret_63_legacy_target": ic_raw},
        "metrics": {"legacy_perank": ev_l, "direct_perank_v2": ev_d},
        "gate": {"legacy_perank_v2.1": g_l, "direct_perank_v2.1": g_d,
                 "legacy_perank_exp": g_exp_l, "direct_perank_v2_exp": g_exp_d},
        "designations": {
            "eligible_v2.1_direct_adjusted": v21_elig,
            "eligible_exp_direct_adjusted": exp_elig,
            "exp_near_miss": exp_near,
        },
    }
    # delta vs the raw-return direct world (same PERank_DIRECT_V2 substitution)
    if PREV.exists():
        prev = json.loads(PREV.read_text(encoding="utf-8"))
        cmp_block = {}
        for n in V21_NAMES:
            b = prev.get("gate", {}).get("direct_v2.1", {}).get("candidates", {}).get(n)
            a = g_d["candidates"][n]
            if not b:
                continue
            cmp_block[n] = {
                "dev_ic21": {"raw": b["dev_ic21"], "adjusted": a["dev_ic21"], "delta": a["dev_ic21"] - b["dev_ic21"]},
                "val_ic21": {"raw": b["val_ic21"], "adjusted": a["val_ic21"], "delta": a["val_ic21"] - b["val_ic21"]},
                "dev_pos_frac": {"raw": b["dev_pos_frac"], "adjusted": a["dev_pos_frac"]},
                "val_pos_frac": {"raw": b["val_pos_frac"], "adjusted": a["val_pos_frac"]},
                "dev_turnover": {"raw": b["dev_turn"], "adjusted": a["dev_turn"]},
                "val_turnover": {"raw": b["val_turn"], "adjusted": a["val_turn"]},
                "rules_failed_raw": [k for k in ("R1", "R2", "R3", "R4") if not b[k]],
                "rules_failed_adjusted": [k for k in ("R1", "R2", "R3", "R4") if not a[k]],
            }
        doc["comparison_raw_vs_adjusted_direct_world"] = cmp_block
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    base = g_d["baseline"]
    print(f"baseline direct+adjusted: dev={base['dev_ic21']:.4f} val={base['val_ic21']:.4f}")
    for n in V21_NAMES:
        c = g_d["candidates"][n]
        print(f"  {n:20} dev={c['dev_ic21']:+.4f} val={c['val_ic21']:+.4f} pos={c['dev_pos_frac']:.2f}/{c['val_pos_frac']:.2f} "
              f"turn={c['dev_turn']:.3f}/{c['val_turn']:.3f} rules_passed={c['rules_passed']}")
    for n in EXP_NAMES:
        c = g_exp_d["candidates"][n]
        print(f"  {n:20} dev={c['dev_ic21']:+.4f} val={c['val_ic21']:+.4f} rules_passed={c['rules_passed']}")
    print(f"eligible v2.1 (direct+adjusted): {v21_elig}")
    print("wrote model_v2_adjusted_return_eval.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
