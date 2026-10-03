"""MODEL_V2_1_ROBUST_SET — pre-registered experiment runner (frozen protocol).

See MODEL_V2_1_PREREGISTRATION.md.  Order of operations is enforced:
  1. Dev/Val metrics for baseline + candidates
  2. FROZEN decision rule (Dev+Val only) -> selection persisted
  3. Holdout 2025 evaluated once, then Forward 2026 as a separate diagnostic
No tuning, no direction flips, no canonical writes.
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

OUT = HERE / "output"
ROBUST = ["PERank", "NetProfitGrowthRank", "SalesGrowthRank",
          "SalesGrowth3MRank", "RevenueGrowthRank", "LowVolatilityRank"]
ABLATION_DROP = "NetProfitGrowthRank"

DECISION = {
    "R1": "dev_ic21 > baseline_dev_ic21 AND val_ic21 >= baseline_val_ic21",
    "R2": "ic21 positive_fraction >= 0.75 in dev and val",
    "R3": "coverage_score_correlation <= 0.30 in dev and val",
    "R4": "turnover_mean <= 0.65 in dev and val",
    "select": "highest (dev_ic21 + val_ic21)/2 among eligible; else MODEL_V2_1_VALIDATION_WEAK",
}


def _sha(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def factor_ic_series(rows, factor, ret="ret_21"):
    by = {}
    for r in rows:
        by.setdefault(r["signal_date"], []).append(r)
    out = []
    for d in sorted(by):
        xs = [x["ranks"].get(factor) for x in by[d]]
        ys = [x.get(ret) for x in by[d]]
        v = M.spearman(xs, ys)
        if v is not None:
            out.append(v)
    return out


def dev_stat_weights(rows) -> dict:
    """v2.1-b weights: ∝ max(0, Dev IC21 mean) over the robust set (Dev rows only)."""
    dev = [r for r in rows if 2021 <= int(r["signal_date"][:4]) <= 2023]
    raw = {f: max(0.0, float(np.mean(factor_ic_series(dev, f))) if factor_ic_series(dev, f) else 0.0)
           for f in ROBUST}
    s = sum(raw.values())
    return ({f: raw[f] / s for f in ROBUST} if s > 0 else {f: 1.0 / len(ROBUST) for f in ROBUST}), raw


def beta_coverage(rows, score_fn) -> float:
    """Frozen β for v2.1-c from Development rows only."""
    dev = [r for r in rows if 2021 <= int(r["signal_date"][:4]) <= 2023]
    xs, ys = [], []
    for r in dev:
        s = score_fn(r)
        if s is None:
            continue
        xs.append(float(r["n_factors_available"])); ys.append(float(s))
    if len(xs) < 10:
        return 0.0
    x = np.array(xs); y = np.array(ys)
    v = float(np.var(x))
    return float(np.cov(x, y, ddof=0)[0, 1] / v) if v > 0 else 0.0


def weighted_scorer(weights, beta=0.0):
    def fn(r):
        ranks, avail = r["ranks"], r["avail"]
        num = den = 0.0
        for code, w in weights.items():
            if avail.get(code) and ranks.get(code) is not None:
                num += w * float(ranks[code]); den += w
        if den == 0:
            return None
        s = num / den
        if beta:
            s = s - beta * float(r["n_factors_available"])
        return s
    return fn


def main():
    rows = M.load_signals()
    print("signals:", len(rows))

    # ---- frozen candidate definitions ----
    a_w = {f: 1.0 / len(ROBUST) for f in ROBUST}
    b_w, b_raw = dev_stat_weights(rows)
    abl_w = {f: 1.0 / (len(ROBUST) - 1) for f in ROBUST if f != ABLATION_DROP}
    beta_c = beta_coverage(rows, weighted_scorer(a_w))

    scorers = {
        "canonical-v1-dev": lambda r: r.get("quant_score"),
        "canonical-v2.1-a": weighted_scorer(a_w),
        "canonical-v2.1-b": weighted_scorer(b_w),
        "canonical-v2.1-c": weighted_scorer(a_w, beta=beta_c),
        "canonical-v2.1-a-NPGX": weighted_scorer(abl_w),
    }
    config = {
        "family": "MODEL_V2_1_ROBUST_SET",
        "preregistration": "MODEL_V2_1_PREREGISTRATION.md",
        "robust_factors": ROBUST,
        "candidates": {
            "canonical-v2.1-a": {"weights": a_w, "kind": "equal"},
            "canonical-v2.1-b": {"weights": b_w, "kind": "dev_stat", "dev_raw_ic": b_raw},
            "canonical-v2.1-c": {"weights": a_w, "kind": "coverage_neutral", "beta": beta_c},
            "canonical-v2.1-a-NPGX": {"weights": abl_w, "kind": "ablation"},
        },
        "missing_policy": "drop_unavailable_renormalize",
        "cost_bps_per_side": M.COST_BPS_PER_SIDE,
        "top_n": M.TOP_N,
        "primary_horizon": M.PRIMARY,
        "periods": M.PERIODS,
        "decision": DECISION,
        "return_convention": "raw_price_return (RETURN_SERIES_NOT_PROMOTION_GRADE)",
    }
    config["config_hash"] = _sha(config)
    (OUT / "model_v2_1_config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print("config hash:", config["config_hash"])
    print("v2.1-b weights:", {k: round(v, 4) for k, v in b_w.items()})
    print("v2.1-c beta:", round(beta_c, 6))

    # ---- evaluation ----
    periods = ("development", "validation", "holdout", "forward")
    ev = {}
    for p in periods:
        sub = M.period_rows(rows, p)
        ev[p] = {name: M.evaluate(sub, name, fn) for name, fn in scorers.items()}

    def ic(p, model):
        return ev[p][model]["ic"]["ret_21"]
    def cov(p, model):
        return ev[p][model]["coverage_score_correlation"]
    def turn(p, model):
        return ev[p][model]["turnover_mean"]

    b_dev, b_val = ic("development", "canonical-v1-dev")["mean"], ic("validation", "canonical-v1-dev")["mean"]

    # ---- frozen decision (Dev+Val ONLY) ----
    evidence, eligible = {}, {}
    for k in ("canonical-v2.1-a", "canonical-v2.1-b", "canonical-v2.1-c"):
        d, v = ic("development", k), ic("validation", k)
        ok = (d["mean"] is not None and v["mean"] is not None and b_dev is not None and b_val is not None
              and d["mean"] > b_dev and v["mean"] >= b_val
              and d["positive_fraction"] >= 0.75 and v["positive_fraction"] >= 0.75
              and 0 < cov("development", k) <= 0.30 and 0 <= cov("validation", k) <= 0.30
              and turn("development", k) <= 0.65 and turn("validation", k) <= 0.65)
        eligible[k] = bool(ok)
        evidence[k] = {"dev_ic21": d["mean"], "val_ic21": v["mean"],
                       "dev_posfrac": d["positive_fraction"], "val_posfrac": v["positive_fraction"],
                       "dev_coverage_corr": cov("development", k), "val_coverage_corr": cov("validation", k),
                       "dev_turnover": turn("development", k), "val_turnover": turn("validation", k),
                       "dev_spread": ev["development"][k]["quantile_top_minus_bottom_21"],
                       "val_spread": ev["validation"][k]["quantile_top_minus_bottom_21"],
                       "dev_signals": ev["development"][k]["n_signals"],
                       "val_signals": ev["validation"][k]["n_signals"],
                       "dev_eligible_mean": ev["development"][k]["n_eligible_mean"],
                       "val_eligible_mean": ev["validation"][k]["n_eligible_mean"],
                       "eligible": bool(ok)}
    selected = None
    if any(eligible.values()):
        selected = max((k for k, v in eligible.items() if v),
                       key=lambda k: (ic("development", k)["mean"] + ic("validation", k)["mean"]) / 2)
    selection = {"family": "MODEL_V2_1_ROBUST_SET", "config_hash": config["config_hash"],
                 "rule": DECISION, "baseline": {"dev_ic21": b_dev, "val_ic21": b_val},
                 "evidence": evidence, "selected": selected}
    (OUT / "model_v2_1_selection.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FROZEN SELECTION (dev+val only):", selected)

    # ---- reporting ----
    out = []
    for p in periods:
        for name in scorers:
            e = ev[p][name]
            out.append({
                "period": p, "model": name,
                "ic21_mean": e["ic"]["ret_21"]["mean"], "ic21_posfrac": e["ic"]["ret_21"]["positive_fraction"],
                "ic21_t": e["ic"]["ret_21"]["t_stat"], "ic5_mean": e["ic"]["ret_5"]["mean"],
                "ic63_mean": e["ic"]["ret_63"]["mean"],
                "top_bottom_21": e["quantile_top_minus_bottom_21"],
                "turnover": e["turnover_mean"],
                "portfolio_raw": e["portfolio_raw"]["cumulative_return"],
                "portfolio_cost": e["portfolio_cost"]["cumulative_return"],
                "benchmark_raw": e["benchmark_raw"]["cumulative_return"],
                "max_drawdown": e["portfolio_cost"]["max_drawdown"],
                "volatility": e["portfolio_cost"]["volatility"],
                "coverage_score_correlation": e["coverage_score_correlation"],
                "n_eligible_mean": e["n_eligible_mean"], "n_signals": e["n_signals"], "n_dates": e["n_dates"],
            })
    with (OUT / "model_v2_1_results.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

    # coverage strata (missingness/coverage distribution)
    strata_rows = []
    for p in periods:
        sub = M.period_rows(rows, p)
        for name in ("canonical-v1-dev", "canonical-v2.1-a", "canonical-v2.1-b", "canonical-v2.1-c"):
            for row in M.coverage_strata(sub, name, scorers[name]):
                strata_rows.append({"period": p, **row})
    if strata_rows:
        with (OUT / "model_v2_1_coverage_strata.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(strata_rows[0].keys())); w.writeheader(); w.writerows(strata_rows)

    # ---- NetProfitGrowth ablation (dev/val first) ----
    abl = []
    for p in periods:
        a, x = ev[p]["canonical-v2.1-a"], ev[p]["canonical-v2.1-a-NPGX"]
        abl.append({
            "period": p,
            "d_ic21": a["ic"]["ret_21"]["mean"] - x["ic"]["ret_21"]["mean"],
            "d_ic63": a["ic"]["ret_63"]["mean"] - x["ic"]["ret_63"]["mean"],
            "d_spread": a["quantile_top_minus_bottom_21"] - x["quantile_top_minus_bottom_21"],
            "d_turnover": a["turnover_mean"] - x["turnover_mean"],
            "d_coverage_corr": a["coverage_score_correlation"] - x["coverage_score_correlation"],
            "d_n_eligible": a["n_eligible_mean"] - x["n_eligible_mean"],
            "with_ic21": a["ic"]["ret_21"]["mean"], "without_ic21": x["ic"]["ret_21"]["mean"],
        })
    with (OUT / "model_v2_1_ablation.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(abl[0].keys())); w.writeheader(); w.writerows(abl)

    gate = "MODEL_V2_1_READY_FOR_PROMOTION" if selected else "MODEL_V2_1_VALIDATION_WEAK"
    summary = {
        "family": "MODEL_V2_1_ROBUST_SET", "config_hash": config["config_hash"],
        "robust_factors": ROBUST, "candidates": config["candidates"],
        "selection": selection, "results": out, "ablation": abl,
        "return_convention": "raw_price_return", "return_grade": "RETURN_SERIES_NOT_PROMOTION_GRADE",
        "gate": gate,
    }
    (OUT / "model_v2_1_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    for p in periods:
        print(f"\n=== {p.upper()} ===")
        for r in out:
            if r["period"] == p:
                print(f"  {r['model']:<24} ic21={r['ic21_mean']:.4f} posfrac={r['ic21_posfrac']:.2f} "
                      f"turn={r['turnover']:.3f} cov={r['coverage_score_correlation']:.3f} "
                      f"spread={r['top_bottom_21']:.4f} port_net={r['portfolio_cost']:.3f}")
    print("\nablation (with - without NetProfitGrowth):")
    for r in abl:
        print(f"  {r['period']:<12} d_ic21={r['d_ic21']:+.4f} d_spread={r['d_spread']:+.4f} d_cov={r['d_coverage_corr']:+.3f}")
    print("\nGATE:", gate)


if __name__ == "__main__":
    main()
