"""MODEL V2.2 — EXECUTION (exactly once) of the preregistration frozen at
sha256 e4edbb781c110a584008a35a9ee36a871326d5e999e86c4c0f86f0431ae5bd25.

Runs EXACTLY the preregistered candidates (v2.2-a primary, -b/-c ablations) plus the
frozen baseline (canonical-v1-dev) and the v2.1-a reference, on the frozen inputs
(PERank_DIRECT_V2, FORWARD_RETURN_ADJUSTED_V1, pClosing basis), with the frozen
missing policy, eligibility, monthly rebalance, TOP_N 20, IC/turnover computation and
the unchanged R1-R4 gates. All historical results are EXPLORATORY_HISTORICAL.
No other candidate, weight variant, or factor is created. No tuning.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_v2 as M  # noqa: E402
import model_v2_1 as V  # noqa: E402
from model_v2_direct_rebaseline_v2 import (  # noqa: E402
    direct_ranks, gate, rows_with_direct, symbol_map)

ADJUSTED = Path(r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\backtesting_v1\output\phase3_signals_adjusted_v1.csv")
PREREG = HERE / "MODEL_V2_2_PREREGISTRATION.md"
OUT = HERE / "output" / "model_v2_2_execution.json"
VERSION = "MODEL_V2_2_EXECUTION"

PREREG_SHA256 = "e4edbb781c110a584008a35a9ee36a871326d5e999e86c4c0f86f0431ae5bd25"
GROWTH3 = ["NetProfitGrowthRank", "SalesGrowthRank", "SalesGrowth3MRank"]
GROWTH4 = GROWTH3 + ["RevenueGrowthRank"]
ROBUST5 = [f for f in V.ROBUST if f != "RevenueGrowthRank"]


def robust_score(weights):
    """Frozen missing policy drop_unavailable_renormalize over named rank factors."""
    def fn(r):
        num = den = 0.0
        for code, w in weights.items():
            if r["avail"].get(code) and r["ranks"].get(code) is not None:
                num += w * float(r["ranks"][code])
                den += w
        return num / den if den > 0 else None
    return fn


def with_composite(rows, members, field):
    out = []
    for r in rows:
        c = {**r, "ranks": dict(r["ranks"]), "avail": dict(r["avail"])}
        vals = [c["ranks"].get(m) for m in members
                if c["avail"].get(m) and c["ranks"].get(m) is not None]
        if vals:
            c["ranks"][field] = float(np.mean(vals))
            c["avail"][field] = True
        else:
            c["avail"][field] = False
        out.append(c)
    return out


def renorm_freq(rows, slots):
    """Fraction of rows where at least one weight slot is unavailable (renormalized)."""
    n = sum(1 for r in rows if not all(r["avail"].get(s) and r["ranks"].get(s) is not None for s in slots))
    return round(n / len(rows), 4)


def mean_cross_section(rows, fn):
    per = {}
    for r in rows:
        s = fn(r)
        if s is not None:
            per.setdefault(r["signal_date"], []).append(s)
    return per


def compare_models(rows_a, fn_a, rows_b, fn_b, periods=("development", "validation")):
    """Rank correlation of scores + top-20 Jaccard overlap per date, averaged."""
    cors, jacs = [], []
    for p in periods:
        prows_a = M.period_rows(rows_a, p)
        by_b = {}
        for r in M.period_rows(rows_b, p):
            by_b.setdefault(r["signal_date"], {})[r["company_id"]] = r
        by_date_a = {}
        for r in prows_a:
            by_date_a.setdefault(r["signal_date"], []).append(r)
        for d, ra in by_date_a.items():
            rb = by_b.get(d, {})
            common = [r for r in ra if r["company_id"] in rb]
            sa = [(fn_a(r), fn_b(rb[r["company_id"]])) for r in common
                  if fn_a(r) is not None and fn_b(rb[r["company_id"]]) is not None]
            if len(sa) >= 5:
                cors.append(M.spearman([x[0] for x in sa], [x[1] for x in sa]))
            ea = sorted([r for r in ra if r.get("ret_21") is not None and fn_a(r) is not None], key=lambda r: -fn_a(r))[:20]
            eb = sorted([r for r in rb.values() if r.get("ret_21") is not None and fn_b(r) is not None], key=lambda r: -fn_b(r))[:20]
            A, B = {r["company_id"] for r in ea}, {r["company_id"] for r in eb}
            if A | B:
                jacs.append(len(A & B) / len(A | B))
    return {"mean_score_rank_correlation": round(float(np.mean(cors)), 4) if cors else None,
            "mean_top20_jaccard_overlap": round(float(np.mean(jacs)), 4) if jacs else None,
            "n_dates": len(cors)}


def main() -> int:
    assert hashlib.sha256(PREREG.read_bytes()).hexdigest() == PREREG_SHA256, "preregistration hash mismatch"
    csv_hash = hashlib.sha256(ADJUSTED.read_bytes()).hexdigest()
    assert csv_hash == "bf7cc191bf907e914858df00dee8f4c6e4c594e111ef4ecc24797a5c67a6088e", "frozen input changed"

    rows = M.load_signals(ADJUSTED)
    dmap, smap = direct_ranks(), symbol_map()
    rows_direct, hit, lost = rows_with_direct(rows, dmap, smap)

    # frozen candidates (no others)
    rows_a = with_composite(rows_direct, GROWTH3, "GrowthComposite")
    rows_c = with_composite(rows_direct, GROWTH4, "GrowthComposite4")

    w3 = {"PERank": 1/3, "GrowthComposite": 1/3, "LowVolatilityRank": 1/3}
    w5 = {f: 1/5 for f in ROBUST5}
    w3c = {"PERank": 1/3, "GrowthComposite4": 1/3, "LowVolatilityRank": 1/3}
    w21a = {f: 1/6 for f in V.ROBUST}

    scorers = {
        "canonical-v1-dev": lambda r: r.get("quant_score"),
        "canonical-v2.1-a": robust_score(w21a),
        "canonical-v2.2-a": robust_score(w3),
        "canonical-v2.2-b": robust_score(w5),
        "canonical-v2.2-c": robust_score(w3c),
    }
    ev = {p: {n: M.evaluate(M.period_rows(rows, p), n, fn) for n, fn in scorers.items()}
          for p in ("development", "validation", "holdout", "forward")}

    names = ["canonical-v2.2-a", "canonical-v2.2-b", "canonical-v2.2-c"]
    g = gate(ev, names)

    elig = [n for n in names if g["candidates"][n]["eligible"]]
    sel = max(elig, key=lambda n: g["candidates"][n]["selection_score"]) if elig else None
    exploratory = "PASS" if sel else "FAIL"
    shadow_eligible = "YES" if sel else "NO"

    # PHASE 4 comparison: v2.1-a vs v2.2-a
    a21, a22 = g["candidates"].get("canonical-v2.2-a"), None
    v21a = {p: ev[p]["canonical-v2.1-a"] for p in ev}
    v22a = {p: ev[p]["canonical-v2.2-a"] for p in ev}
    cmp_block = {}
    for p in ("development", "validation"):
        cmp_block[p] = {
            "ic21": {"v2.1-a": v21a[p]["ic"]["ret_21"]["mean"], "v2.2-a": v22a[p]["ic"]["ret_21"]["mean"]},
            "pos_frac": {"v2.1-a": v21a[p]["ic"]["ret_21"]["positive_fraction"],
                         "v2.2-a": v22a[p]["ic"]["ret_21"]["positive_fraction"]},
            "turnover": {"v2.1-a": v21a[p]["turnover_mean"], "v2.2-a": v22a[p]["turnover_mean"]},
            "coverage_corr": {"v2.1-a": v21a[p]["coverage_score_correlation"],
                              "v2.2-a": v22a[p]["coverage_score_correlation"]},
        }
    rows_a_dir = rows_a  # PERank substituted + composite
    rows_v21 = rows_direct
    cmp_block["score_rank_corr_and_overlap"] = compare_models(rows_v21, scorers["canonical-v2.1-a"], rows_a_dir, scorers["canonical-v2.2-a"])
    cmp_block["renormalization_frequency"] = {
        "v2.1-a_any_slot_missing": renorm_freq(rows_v21, V.ROBUST),
        "v2.2-a_any_slot_missing": renorm_freq(rows_a_dir, list(w3.keys())),
        "v2.2-b_any_slot_missing": renorm_freq(rows_direct, ROBUST5),
        "v2.2-c_any_slot_missing": renorm_freq(rows_c, list(w3c.keys())),
        "factor_availability_fraction": {f: round(float(np.mean([bool(r["avail"].get(f)) for r in rows_direct])), 4)
                                         for f in V.ROBUST}}
    cmp_block["coverage_rows_scored_mean"] = {
        "v2.1-a": float(np.mean([len(v) for v in mean_cross_section(rows_v21, scorers["canonical-v2.1-a"]).values()])),
        "v2.2-a": float(np.mean([len(v) for v in mean_cross_section(rows_a_dir, scorers["canonical-v2.2-a"]).values()]))}

    # hypothesis verdicts (mechanical, from the frozen deltas)
    hypotheses = {
        "H1_removed_revenue_growth": {
            "tested_by": "canonical-v2.2-b vs canonical-v2.1-a",
            "renormalization_freq": {"v2.1-a": cmp_block["renormalization_frequency"]["v2.1-a_any_slot_missing"],
                                     "v2.2-b": cmp_block["renormalization_frequency"]["v2.2-b_any_slot_missing"]},
            "dev_pos_frac": {"v2.1-a": v21a["development"]["ic"]["ret_21"]["positive_fraction"],
                             "v2.2-b": ev["development"]["canonical-v2.2-b"]["ic"]["ret_21"]["positive_fraction"]}},
        "H2_growth_family_collapse": {
            "tested_by": "canonical-v2.2-a vs canonical-v2.2-b (given H1) and canonical-v2.2-c vs canonical-v2.1-a",
            "dev_pos_frac": {"v2.2-b": ev["development"]["canonical-v2.2-b"]["ic"]["ret_21"]["positive_fraction"],
                             "v2.2-a": ev["development"]["canonical-v2.2-a"]["ic"]["ret_21"]["positive_fraction"]},
            "val_pos_frac": {"v2.2-b": ev["validation"]["canonical-v2.2-b"]["ic"]["ret_21"]["positive_fraction"],
                             "v2.2-a": ev["validation"]["canonical-v2.2-a"]["ic"]["ret_21"]["positive_fraction"]}},
        "H3_lowvol instability": {
            "experimentally_tested": False,
            "note": "no preregistered candidate changes LowVolatilityRank; H3 is diagnostic context only"},
    }

    doc = {
        "version": VERSION,
        "preregistration_sha256": PREREG_SHA256,
        "frozen_inputs": {"adjusted_csv_sha256": csv_hash,
                          "return_target": "FORWARD_RETURN_ADJUSTED_V1",
                          "perank": "PERank_DIRECT_V2",
                          "price_basis": "CANONICAL_RETURN_PRICE = TSETMC pClosing"},
        "all_periods_label": "EXPLORATORY_HISTORICAL",
        "metrics": ev,
        "gate": g,
        "selection": {"eligible": elig, "primary": sel or "MODEL_V2_2_VALIDATION_WEAK",
                      "MODEL_V2_2_EXPLORATORY_GATE": exploratory,
                      "MODEL_V2_2_SHADOW_ELIGIBLE": shadow_eligible},
        "comparison_v2_1a_vs_v2_2a": cmp_block,
        "hypotheses": hypotheses,
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    b = g["baseline"]
    print(f"baseline dev/val IC21 = {b['dev_ic21']:.4f}/{b['val_ic21']:.4f}")
    for n in names:
        c = g["candidates"][n]
        print(f"{n}: dev={c['dev_ic21']:+.4f} val={c['val_ic21']:+.4f} pos={c['dev_pos_frac']:.4f}/{c['val_pos_frac']:.4f} "
              f"turn={c['dev_turn']:.4f}/{c['val_turn']:.4f} cov={c['dev_cov']:+.3f}/{c['val_cov']:+.3f} "
              f"R1={c['R1']} R2={c['R2']} R3={c['R3']} R4={c['R4']}")
    print(f"MODEL_V2_2_EXPLORATORY_GATE = {exploratory}; primary = {sel or 'MODEL_V2_2_VALIDATION_WEAK'}; "
          f"shadow_eligible = {shadow_eligible}")
    print("renormalization freq:", json.dumps(cmp_block["renormalization_frequency"]["v2.1-a_any_slot_missing"],
                                              ), "->", cmp_block["renormalization_frequency"]["v2.2-a_any_slot_missing"])
    print("overlap/rankcorr:", json.dumps(cmp_block["score_rank_corr_and_overlap"]))
    print("wrote model_v2_2_execution.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
