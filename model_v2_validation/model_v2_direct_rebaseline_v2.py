"""MODEL_V2 / V2.1 REBASELINE with PERank_DIRECT_V2 (Stage-4 ambiguity resolution).

The frozen harness is used unchanged: same factors, weights, transformations,
missing-data policy (drop_unavailable_renormalize), rebalance logic, horizons,
costs, periods and decision rule (R1-R4 on Dev+Validation only).

The ONLY change vs the v1 rebaseline is the PERank source: ranks["PERank"] is
replaced by PERank_DIRECT_V2 (pe_direct_universe_v2.jsonl) where a PIT-safe
direct value exists; where it does not, PERank stays MISSING - no fallback to
the legacy (contaminated) PERank.

This run also closes the previously unexecuted older Model v2 direct
rebaseline: canonical-v2-exp-a (Robust Core) and canonical-v2-exp-b
(Coverage-Aware) are scored from M.MODELS with M.score_row, in the legacy world
and the direct world. The preregistered v2.1 candidates (a/b/c + NPGX ablation)
run with b-weights/beta_c recomputed under their original frozen rules.

Designations (reporting labels, gate math unchanged):
  MODEL_V2_DIRECT_REBASELINE     PASS  if >=1 of exp-a/exp-b eligible under R1-R4
                                 PARTIAL if none eligible but >=1 passes 3 of 4
                                 FAIL  otherwise
  MODEL_V2_1_DIRECT_REBASELINE   PASS if any v2.1 candidate eligible, else FAIL
  MODEL_V2_1_PREREGISTERED_GATE  PASS if the preregistered selection found an
                                 eligible candidate in the direct world, else FAIL

Holdout/Forward are computed descriptively only; they never feed selection.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_v2 as M  # noqa: E402  frozen harness
import model_v2_1 as V  # noqa: E402  frozen preregistered candidates

OUT = HERE / "output"
DIRECT = Path(r"D:\RFA\Company-Financial\historical_codal_backfill\output\pe_direct_universe_v2.jsonl")
CALC = "perank-direct-v2+tsetmc-shares+codal-knowledge+ambiguity-resolved"
VERSION = "MODEL_V2_DIRECT_PERANK_REBASELINE_V2"
PREV = OUT / "model_v2_direct_perank_rebaseline.json"

EXP_NAMES = ["canonical-v2-exp-a", "canonical-v2-exp-b"]
V21_NAMES = ["canonical-v2.1-a", "canonical-v2.1-b", "canonical-v2.1-c"]


def direct_ranks():
    out = {}
    for line in DIRECT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        v = r.get("PERank_DIRECT_V2")
        if v is not None:
            out[(r["symbol"], r["signal_date"])] = float(v)
    return out


def symbol_map():
    sm = {}
    with M.SIGNALS.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            sm[(r["company_id"], r["signal_date"])] = r.get("symbol")
    return sm


def rows_with_direct(rows, dmap, smap):
    out, hit, lost = [], 0, 0
    for r in rows:
        sym = smap.get((r["company_id"], r["signal_date"]))
        c = {**r, "ranks": dict(r["ranks"]), "avail": dict(r["avail"])}
        was = bool(c["avail"].get("PERank")) and c["ranks"].get("PERank") is not None
        v = dmap.get((sym, r["signal_date"]))
        if v is not None:
            c["ranks"]["PERank"] = v
            c["avail"]["PERank"] = True
            hit += 1
        else:
            c["ranks"].pop("PERank", None)
            c["avail"]["PERank"] = False
            if was:
                lost += 1
                c["n_factors_available"] = max(0, c["n_factors_available"] - 1)
        out.append(c)
    return out, hit, lost


def run(rows, label):
    a_w = {f: 1.0 / len(V.ROBUST) for f in V.ROBUST}
    b_w, b_raw = V.dev_stat_weights(rows)
    abl_w = {f: 1.0 / (len(V.ROBUST) - 1) for f in V.ROBUST if f != V.ABLATION_DROP}
    beta_c = V.beta_coverage(rows, V.weighted_scorer(a_w))
    exp_a = M.MODELS["canonical-v2-exp-a"]
    exp_b = M.MODELS["canonical-v2-exp-b"]
    scorers = {
        "canonical-v1-dev": lambda r: r.get("quant_score"),
        "canonical-v2-exp-a": lambda r: M.score_row(exp_a, r["ranks"], r["avail"]),
        "canonical-v2-exp-b": lambda r: M.score_row(exp_b, r["ranks"], r["avail"]),
        "canonical-v2.1-a": V.weighted_scorer(a_w),
        "canonical-v2.1-b": V.weighted_scorer(b_w),
        "canonical-v2.1-c": V.weighted_scorer(a_w, beta=beta_c),
        "canonical-v2.1-a-NPGX": V.weighted_scorer(abl_w),
    }
    ev = {p: {n: M.evaluate(M.period_rows(rows, p), n, fn) for n, fn in scorers.items()}
          for p in ("development", "validation", "holdout", "forward")}
    return ev, {"a_w": a_w, "b_w": b_w, "beta_c": beta_c, "label": label}


def gate(ev, names, base="canonical-v1-dev"):
    """Frozen decision rule R1-R4, evaluated on Dev+Validation only."""
    b_dev = ev["development"][base]["ic"]["ret_21"]["mean"]
    b_val = ev["validation"][base]["ic"]["ret_21"]["mean"]
    res = {}
    for name in names:
        d = ev["development"][name]
        v = ev["validation"][name]
        r1 = d["ic"]["ret_21"]["mean"] > b_dev and v["ic"]["ret_21"]["mean"] >= b_val
        r2 = (d["ic"]["ret_21"]["positive_fraction"] >= 0.75
              and v["ic"]["ret_21"]["positive_fraction"] >= 0.75)
        r3 = (abs(d["coverage_score_correlation"]) <= 0.30
              and abs(v["coverage_score_correlation"]) <= 0.30)
        r4 = (d["turnover_mean"] <= 0.65 and v["turnover_mean"] <= 0.65)
        res[name] = {"R1": bool(r1), "R2": bool(r2), "R3": bool(r3), "R4": bool(r4),
                     "rules_passed": int(r1) + int(r2) + int(r3) + int(r4),
                     "eligible": bool(r1 and r2 and r3 and r4),
                     "dev_ic21": d["ic"]["ret_21"]["mean"], "val_ic21": v["ic"]["ret_21"]["mean"],
                     "dev_pos_frac": d["ic"]["ret_21"]["positive_fraction"],
                     "val_pos_frac": v["ic"]["ret_21"]["positive_fraction"],
                     "dev_cov": d["coverage_score_correlation"],
                     "val_cov": v["coverage_score_correlation"],
                     "dev_turn": d["turnover_mean"], "val_turn": v["turnover_mean"],
                     "selection_score": (d["ic"]["ret_21"]["mean"] + v["ic"]["ret_21"]["mean"]) / 2}
    elig = {k: x for k, x in res.items() if x["eligible"]}
    sel = max(elig, key=lambda k: elig[k]["selection_score"]) if elig else None
    return {"baseline": {"dev_ic21": b_dev, "val_ic21": b_val}, "candidates": res,
            "selected": sel or "MODEL_V2_1_VALIDATION_WEAK"}


def compare_to_v1(g_v21_new, hit):
    """Quantify the ambiguity-resolution effect vs the v1 direct rebaseline."""
    if not PREV.exists():
        return None
    prev = json.loads(PREV.read_text(encoding="utf-8"))
    out = {"prev_version": prev.get("version"),
           "prev_direct_perank_rows": prev.get("coverage", {}).get("direct_perank_rows"),
           "direct_perank_rows": hit, "coverage_gain": hit - prev.get("coverage", {}).get("direct_perank_rows", 0),
           "candidates": {}}
    for n in V21_NAMES:
        b = prev.get("gate", {}).get("direct", {}).get("candidates", {}).get(n)
        a = g_v21_new["candidates"][n]
        if not b:
            continue
        out["candidates"][n] = {
            "dev_ic21": {"before": b["dev_ic21"], "after": a["dev_ic21"],
                         "delta": a["dev_ic21"] - b["dev_ic21"]},
            "val_ic21": {"before": b["val_ic21"], "after": a["val_ic21"],
                         "delta": a["val_ic21"] - b["val_ic21"]},
            "dev_pos_frac": {"before": b["dev_pos_frac"], "after": a["dev_pos_frac"],
                             "delta": a["dev_pos_frac"] - b["dev_pos_frac"]},
            "val_pos_frac": {"before": b["val_pos_frac"], "after": a["val_pos_frac"],
                             "delta": a["val_pos_frac"] - b["val_pos_frac"]},
            "dev_turnover": {"before": b["dev_turn"], "after": a["dev_turn"],
                             "delta": a["dev_turn"] - b["dev_turn"]},
            "val_turnover": {"before": b["val_turn"], "after": a["val_turn"],
                             "delta": a["val_turn"] - b["val_turn"]},
            "rules_failed_before": [k for k in ("R1", "R2", "R3", "R4") if not b[k]],
            "rules_failed_after": [k for k in ("R1", "R2", "R3", "R4") if not a[k]],
        }
    return out


def main():
    rows_legacy = M.load_signals()
    dmap = direct_ranks()
    smap = symbol_map()
    rows_direct, hit, lost = rows_with_direct(rows_legacy, dmap, smap)
    print(f"rows={len(rows_legacy)} direct_PERank_hits={hit} legacy_perank_lost={lost}")

    ev_l, cfg_l = run(rows_legacy, "legacy")
    ev_d, cfg_d = run(rows_direct, "direct")
    g_l, g_d = gate(ev_l, V21_NAMES), gate(ev_d, V21_NAMES)
    g_exp_l, g_exp_d = gate(ev_l, EXP_NAMES), gate(ev_d, EXP_NAMES)

    exp_elig = [n for n in EXP_NAMES if g_exp_d["candidates"][n]["eligible"]]
    exp_near = [n for n in EXP_NAMES if g_exp_d["candidates"][n]["rules_passed"] >= 3]
    model_v2_designation = ("PASS" if exp_elig else "PARTIAL" if exp_near else "FAIL")
    v21_elig = [n for n in V21_NAMES if g_d["candidates"][n]["eligible"]]
    model_v21_designation = "PASS" if v21_elig else "FAIL"
    prereg_designation = "FAIL" if g_d["selected"] == "MODEL_V2_1_VALIDATION_WEAK" else "PASS"

    doc = {
        "version": VERSION,
        "calculation_version": CALC,
        "preregistration": "MODEL_V2_1_PREREGISTRATION.md (frozen 2026-10-01)",
        "protocol": "MODEL_V2_PROTOCOL.md",
        "robust_factors": V.ROBUST,
        "perank_source": {"legacy": "phase3_signals.factor_rank.PERank (EPS-based, contaminated)",
                          "rebaseline": "PERank_DIRECT_V2 (Stage-4 ambiguity-resolved)"},
        "missing_policy": "drop_unavailable_renormalize (unchanged; no legacy fallback)",
        "periods": M.PERIODS,
        "return_convention": "raw_price_return — RETURN_SERIES_NOT_PROMOTION_GRADE",
        "coverage": {"rows": len(rows_legacy), "direct_perank_rows": hit,
                     "legacy_perank_rows_dropped": lost},
        "weights": {"legacy": {"a": cfg_l["a_w"], "b": cfg_l["b_w"], "beta_c": cfg_l["beta_c"]},
                    "direct": {"a": cfg_d["a_w"], "b": cfg_d["b_w"], "beta_c": cfg_d["beta_c"]}},
        "metrics": {"legacy": ev_l, "direct": ev_d},
        "gate": {"legacy_v2.1": g_l, "direct_v2.1": g_d,
                 "legacy_exp": g_exp_l, "direct_exp": g_exp_d},
        "designations": {"MODEL_V2_DIRECT_REBASELINE": model_v2_designation,
                         "MODEL_V2_1_DIRECT_REBASELINE": model_v21_designation,
                         "MODEL_V2_1_PREREGISTERED_GATE": prereg_designation,
                         "eligible_v2.1": v21_elig, "eligible_exp": exp_elig},
        "comparison_to_v1_rebaseline": compare_to_v1(g_d, hit),
    }
    doc["input_hash"] = hashlib.sha256(json.dumps(
        {"direct": CALC, "rows": len(rows_legacy)}, sort_keys=True).encode()).hexdigest()[:16]
    (OUT / "model_v2_direct_perank_rebaseline_v2.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("designations:", json.dumps(doc["designations"], ensure_ascii=False))
    print("wrote model_v2_direct_perank_rebaseline_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
