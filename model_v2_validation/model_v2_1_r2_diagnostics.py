"""MODEL V2.1 CLOSEOUT — R2 root-cause diagnostics on DEVELOPMENT ONLY (2021-2023).

Purpose: EXPLANATION, not tuning. Uses only the final frozen world:
  rows     = phase3_signals_adjusted_v1.csv (FORWARD_RETURN_ADJUSTED_V1, pClosing basis)
  PERank   = PERank_DIRECT_V2 substitution (identical to the V2 rebaseline)
  scorer   = canonical-v2.1-a (equal weights over the frozen robust six)
Dev-only breakdowns: per-date IC21, sign counts, clustering, cross-sectional size,
missingness, turnover, per-factor IC, LOO diagnostics, pairwise rank redundancy,
block bootstrap / rolling / yearly stability. Holdout/Forward are NOT touched.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_v2 as M  # noqa: E402
import model_v2_1 as V  # noqa: E402
from model_v2_direct_rebaseline_v2 import direct_ranks, rows_with_direct, symbol_map  # noqa: E402

ADJUSTED = Path(r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\backtesting_v1\output\phase3_signals_adjusted_v1.csv")
OUT = HERE / "output" / "model_v2_1_r2_diagnostics.json"
DEV = "development"
NEAR_ZERO = 0.02


def per_date_cs(rows, score_fn):
    by_date = {}
    for r in rows:
        s = score_fn(r)
        if s is None:
            continue
        by_date.setdefault(r["signal_date"], []).append(
            (s, r.get("ret_21"), r["n_factors_available"], r["company_id"], r["ranks"], r["avail"]))
    return dict(sorted(by_date.items()))


def sp(x, y):
    return M.spearman(x, y)


def main() -> int:
    rows = M.load_signals(ADJUSTED)
    dmap, smap = direct_ranks(), symbol_map()
    rows_direct, hit, lost = rows_with_direct(rows, dmap, smap)
    a_w = {f: 1.0 / len(V.ROBUST) for f in V.ROBUST}
    scorer = V.weighted_scorer(a_w)
    dev = M.period_rows(rows_direct, DEV)
    cs = per_date_cs(dev, scorer)

    # ---------- per-date IC21 + turnover ----------
    dates = sorted(cs)
    per_date = []
    prev_top = set()
    for d in dates:
        secs = cs[d]
        pairs = [(a[0], a[1]) for a in secs if a[1] is not None]
        ic = sp([p[0] for p in pairs], [p[1] for p in pairs]) if len(pairs) >= 5 else None
        elig = sorted([a for a in secs if a[1] is not None], key=lambda a: -a[0])
        top = {a[3] for a in elig[:20]}
        turn = (1.0 - len(top & prev_top) / len(top | prev_top)) if prev_top and top else None
        prev_top = top
        y, m = int(d[:4]), int(d[5:7])
        per_date.append({"date": d, "year": y, "quarter": f"{y}Q{(m - 1)//3 + 1}",
                         "n_scored": len(secs), "n_with_ret": len(pairs),
                         "mean_n_factors": round(float(np.mean([a[2] for a in secs])), 3),
                         "ic21": None if ic is None else round(float(ic), 6),
                         "turnover": None if turn is None else round(float(turn), 6)})
    ics = [p["ic21"] for p in per_date if p["ic21"] is not None]
    pos = [p for p in per_date if p["ic21"] is not None and p["ic21"] > 0]
    neg = [p for p in per_date if p["ic21"] is not None and p["ic21"] < 0]
    near = [p for p in per_date if p["ic21"] is not None and abs(p["ic21"]) < NEAR_ZERO]
    srt = sorted([p for p in per_date if p["ic21"] is not None], key=lambda p: p["ic21"])
    # clustering: longest consecutive negative run (chronological)
    best_run = run = 0
    neg_quarters, neg_years = {}, {}
    for p in per_date:
        if p["ic21"] is not None and p["ic21"] < 0:
            run += 1
            best_run = max(best_run, run)
            neg_quarters[p["quarter"]] = neg_quarters.get(p["quarter"], 0) + 1
            neg_years[p["year"]] = neg_years.get(p["year"], 0) + 1
        else:
            run = 0
    by_year = {}
    for y in (2021, 2022, 2023):
        ys = [p["ic21"] for p in per_date if p["year"] == y and p["ic21"] is not None]
        by_year[y] = {"n": len(ys), "positive": sum(1 for v in ys if v > 0),
                      "mean": float(np.mean(ys)) if ys else None}
    by_quarter = {}
    for p in per_date:
        if p["ic21"] is None:
            continue
        q = by_quarter.setdefault(p["quarter"], [])
        q.append(p["ic21"])
    by_quarter = {k: {"n": len(v), "positive": sum(1 for x in v if x > 0), "mean": float(np.mean(v))}
                  for k, v in sorted(by_quarter.items())}
    # size / missingness terciles
    sizes = sorted(p["n_scored"] for p in per_date)
    t1, t2 = sizes[len(sizes)//3], sizes[2*len(sizes)//3]
    small = [p["ic21"] for p in per_date if p["ic21"] is not None and p["n_scored"] <= t1]
    big = [p["ic21"] for p in per_date if p["ic21"] is not None and p["n_scored"] > t2]
    mid_nf = np.median([p["mean_n_factors"] for p in per_date])
    lowavail = [p["ic21"] for p in per_date if p["ic21"] is not None and p["mean_n_factors"] <= mid_nf]
    highavail = [p["ic21"] for p in per_date if p["ic21"] is not None and p["mean_n_factors"] > mid_nf]

    # ---------- factor-level diagnostics (Dev only) ----------
    avail_frac, fac_ic = {}, {}
    for f in V.ROBUST:
        per = {}
        for d in dates:
            pairs = [(a[4].get(f), a[1]) for a in cs[d]
                     if a[5].get(f) and a[4].get(f) is not None and a[1] is not None]
            if len(pairs) >= 5:
                per[d] = sp([p[0] for p in pairs], [p[1] for p in pairs])
        vals = list(per.values())
        fac_ic[f] = {"mean": float(np.mean(vals)), "median": float(np.median(vals)),
                     "std": float(np.std(vals, ddof=1)), "positive_fraction": float(np.mean([v > 0 for v in vals])),
                     "n_dates": len(vals)}
        got = tot = 0
        for r in dev:
            tot += 1
            got += bool(r["avail"].get(f) and r["ranks"].get(f) is not None)
        avail_frac[f] = round(got / tot, 4)
    corr = {}
    for i, f in enumerate(V.ROBUST):
        for g in V.ROBUST[i+1:]:
            per = []
            for d in dates:
                pairs = [(a[4].get(f), a[4].get(g)) for a in cs[d]
                         if a[5].get(f) and a[5].get(g) and a[4].get(f) is not None and a[4].get(g) is not None]
                if len(pairs) >= 5:
                    per.append(sp([p[0] for p in pairs], [p[1] for p in pairs]))
            corr[f"{f}|{g}"] = round(float(np.mean(per)), 4) if per else None
    loo = {}
    for f in V.ROBUST:
        w = {g: 1.0 / (len(V.ROBUST) - 1) for g in V.ROBUST if g != f}
        fn = V.weighted_scorer(w)
        vals = []
        for d in dates:
            pairs = [(fn({"ranks": a[4], "avail": a[5]}), a[1]) for a in cs[d] if a[1] is not None]
            if len(pairs) >= 5:
                vals.append(sp([p[0] for p in pairs], [p[1] for p in pairs]))
        loo[f] = {"loo_mean_ic21": float(np.mean(vals)), "loo_positive_fraction": float(np.mean([v > 0 for v in vals])),
                  "delta_vs_full": float(np.mean(vals) - np.mean(ics))}

    # ---------- stability ----------
    rng = random.Random(20211001)
    quarters = sorted({p["quarter"] for p in per_date if p["ic21"] is not None})
    q_ics = {q: [p["ic21"] for p in per_date if p["quarter"] == q and p["ic21"] is not None] for q in quarters}
    B = 2000
    boot = []
    for _ in range(B):
        samp = []
        for _b in range(len(quarters)):
            samp += q_ics[rng.choice(quarters)]
        boot.append(sum(1 for v in samp if v > 0) / len(samp))
    boot.sort()
    roll = []
    for i in range(len(ics) - 5):
        w = ics[i:i+6]
        roll.append(round(sum(1 for v in w if v > 0) / 6, 4))
    flips_needed = 0.75 * len(ics) - len(pos)
    stability = {
        "positive_dates": len(pos), "negative_dates": len(neg), "near_zero_dates_lt_0.02": len(near),
        "pos_frac": round(len(pos) / len(ics), 4), "required": 0.75,
        "additional_positive_dates_needed": max(0, int(np.ceil(flips_needed - 1e-9))),
        "min_abs_ic_among_negative_dates": min(abs(p["ic21"]) for p in neg) if neg else None,
        "negative_dates_within_0.02_of_zero": [p["date"] for p in neg if abs(p["ic21"]) < NEAR_ZERO],
        "block_bootstrap_quarter_B2000": {"p05": boot[int(0.05*B)], "p50": boot[B//2],
                                          "p95": boot[int(0.95*B)],
                                          "p_boot_posfrac_ge_0.75": sum(1 for b in boot if b >= 0.75)/B},
        "rolling6_positive_fraction": roll, "by_year": by_year, "by_quarter": by_quarter,
        "longest_consecutive_negative_run": best_run,
        "negative_dates_by_year": {str(k): v for k, v in sorted(neg_years.items())},
        "negative_dates_by_quarter": {k: v for k, v in sorted(neg_quarters.items())},
        "ic_tercile_by_cross_sectional_size": {"small_third_mean": float(np.mean(small)) if small else None,
                                               "large_third_mean": float(np.mean(big)) if big else None},
        "ic_by_mean_factor_availability": {"below_median_mean": float(np.mean(lowavail)) if lowavail else None,
                                           "above_median_mean": float(np.mean(highavail)) if highavail else None},
    }
    doc = {
        "world": {"returns": "FORWARD_RETURN_ADJUSTED_V1", "perank": "PERank_DIRECT_V2",
                  "scorer": "canonical-v2.1-a (equal-weight robust six)", "period": "development 2021-2023 ONLY",
                  "regime_labels": "none exist in the codebase (checked); year/quarter used instead"},
        "per_date": per_date,
        "summary": {"n_dates": len(ics), "mean_ic21": float(np.mean(ics)),
                    "strongest_positive": srt[-5:][::-1], "strongest_negative": srt[:5],
                    "ic_quartiles": [round(float(np.quantile(ics, q)), 4) for q in (0.25, 0.5, 0.75)]},
        "stability": stability,
        "factor_diagnostics": {"availability_fraction": avail_frac, "ic_by_factor": fac_ic,
                               "pairwise_mean_rank_correlation": corr,
                               "leave_one_out_DIAGNOSTIC_ONLY": loo},
    }
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"dates={len(ics)} pos={len(pos)} neg={len(neg)} near0={len(near)} pos_frac={len(pos)/len(ics):.4f}")
    print(f"flips_needed={stability['additional_positive_dates_needed']} "
          f"min|IC| among negatives={stability['min_abs_ic_among_negative_dates']:.4f}")
    print(f"bootstrap pos-frac p05/p50/p95 = {boot[int(0.05*B)]:.3f}/{boot[B//2]:.3f}/{boot[int(0.95*B)]:.3f} "
          f"P(>=0.75)={sum(1 for b in boot if b >= 0.75)/B:.3f}")
    print("by_year:", json.dumps({str(k): v for k, v in by_year.items()}))
    print("neg by quarter:", json.dumps({k: v for k, v in sorted(neg_quarters.items())}))
    print("factor IC:", json.dumps({f: {"mean": round(v['mean'],4), "pf": round(v['positive_fraction'],3)} for f, v in fac_ic.items()}))
    print("availability:", json.dumps(avail_frac))
    print("LOO delta:", json.dumps({f: round(v['delta_vs_full'], 4) for f, v in loo.items()}))
    print("top pairwise corr:", json.dumps(dict(sorted(corr.items(), key=lambda kv: -(kv[1] or 0))[:4])))
    print("strongest negative dates:", json.dumps(srt[:5]))
    print("wrote model_v2_1_r2_diagnostics.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
