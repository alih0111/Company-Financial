"""Phase 3 — Factor and Model Validation.

VALIDATION ONLY. Does not mutate canonical-v1 (no weights/directions/missing-policy
changes), no production writes, no Go/Python changes. All multivariate/decomposition
outputs are DIAGNOSTIC_ONLY_NOT_MODEL.

Reuses the validated Phase-2 PIT backtesting infrastructure.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
for p in (str(HERE), str(BASE / "analytics_canonical_v1"), str(BASE / "migration_tools")):
    sys.path.insert(0, p)

from config import BacktestConfig, frozen_model_identifiers  # noqa: E402
from calendar import TradingCalendar, rebalance_dates  # noqa: E402
from market_data import load_price_store  # noqa: E402
from snapshot_builder import build_snapshot  # noqa: E402
from universe import evaluate_universe  # noqa: E402
from forward_returns import compute_forward_returns  # noqa: E402
import diagnostics as DG  # noqa: E402
from assess_readiness import FACTOR_SOURCE, CATEGORY  # noqa: E402
import compute_metrics as CM  # noqa: E402

OUT = HERE / "output"
SEED = 20240601
WEIGHTS = CM.BASELINE_WEIGHTS_V37
FACTOR_TO_CAT = {f: cat for cat, fs in CATEGORY.items() for f in fs}
FACTORS = list(FACTOR_SOURCE.keys())
# weight registry key per factor rank column (weights are keyed by short factor name)
WEIGHT_KEY = {
    "SalesGrowthRank": "SalesGrowth", "SalesGrowth3MRank": "SalesGrowth3M",
    "RevenueGrowthRank": "RevenueGrowth", "OperatingProfitGrowthRank": "OperatingProfitGrowth",
    "NetProfitGrowthRank": "NetProfitGrowth", "OperatingMarginRank": "OperatingMargin",
    "NetMarginRank": "NetMargin", "MarginTrendRank": "MarginTrend",
    "InterestCoverageRank": "InterestCoverage", "CashConversionRank": "CashConversion",
    "EarningsQualityRank": "EarningsQuality", "PERank": "PE", "PSRank": "PS", "PBRank": "PB",
    "LiquidityRank": "Liquidity", "LeverageRank": "Leverage", "CurrentRatioRank": "CurrentRatio",
    "StabilityRank": "Stability", "LowVolatilityRank": "LowVolatility", "MomentumRank": "Momentum",
    "ROERank": "ROERank",
}
WEIGHT_BY_RANK = {f: WEIGHTS.get(WEIGHT_KEY.get(f, f)) for f in FACTORS}
EXPECTED_DIRECTION = {f: "+" for f in FACTORS}   # ranks oriented higher-better by construction


def sha(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()


def wcsv(path, rows, fields=None):
    if not rows:
        path.write_text("", encoding="utf-8"); return
    fields = fields or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def block_bootstrap_ci(values, seed=SEED, n=1000):
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return {"mean": mean(vals), "ci_low": None, "ci_high": None, "n": len(vals)}
    rng = random.Random(seed)
    ms = []
    for _ in range(n):
        s = [vals[rng.randrange(len(vals))] for _ in range(len(vals))]
        ms.append(sum(s) / len(s))
    ms.sort()
    return {"mean": mean(vals), "ci_low": ms[25], "ci_high": ms[974], "n": len(vals)}


def ols(X, Y, ridge=1e-6):
    """X: list of rows (no intercept), Y: list. Returns (intercept + coefs)."""
    if not X:
        return None
    pts = [(x, y) for x, y in zip(X, Y) if all(v is not None for v in x) and y is not None]
    if len(pts) < len(X[0]) + 2:
        return None
    p = len(X[0]); n = len(pts)
    A = [[0.0] * (p + 1) for _ in range(p + 1)]
    b = [0.0] * (p + 1)
    for xi, y in pts:
        row = [1.0] + list(xi)
        for i in range(p + 1):
            b[i] += row[i] * y
            for j in range(p + 1):
                A[i][j] += row[i] * row[j]
    for i in range(p + 1):
        A[i][i] += ridge
    for c in range(p + 1):
        piv = max(range(c, p + 1), key=lambda r: abs(A[r][c]))
        if abs(A[piv][c]) < 1e-12:
            return None
        A[c], A[piv] = A[piv], A[c]; b[c], b[piv] = b[piv], b[c]
        pv = A[c][c]
        A[c] = [v / pv for v in A[c]]; b[c] /= pv
        for r in range(p + 1):
            if r != c and A[r][c]:
                f = A[r][c]
                A[r] = [A[r][k] - f * A[c][k] for k in range(p + 1)]
                b[r] -= f * b[c]
    return b  # [intercept, coef...]


# ---------------------------------------------------------------- signal cache
def build_signals():
    cfg = BacktestConfig()
    price_store = load_price_store()
    cal = TradingCalendar(price_store.dates)
    start = dt.date.fromisoformat(cfg.start_date); end = dt.date.fromisoformat(cfg.end_date)
    reb = rebalance_dates(cal, cfg.rebalance_freq, start, end)
    rows = []
    for T in reb:
        snap = build_snapshot(T)
        exec_date = cal.next_trading_day(T)
        uni = evaluate_universe(snap["signals"], price_store, exec_date)
        for s in uni["tradable"]:
            rows.append({
                "signal_date": str(T), "company_id": s["company_id"], "security_id": s.get("security_id"),
                "symbol": s.get("symbol"), "quant_score": s.get("quant_score"),
                "growth_score": s.get("growth_score"), "profitability_score": s.get("profitability_score"),
                "valuation_score": s.get("valuation_score"), "market_score": s.get("market_score"),
                "data_quality_score": s.get("data_quality_score"), "n_factors_available": s.get("n_factors_available"),
                "factor_rank": s.get("factor_rank"), "factor_available": s.get("factor_available"),
                "category_available": s.get("category_available"), "execution_date": str(exec_date)})
    # forward returns for all signals
    sigs = [{"company_id": r["company_id"], "security_id": r["security_id"], "symbol": r["symbol"],
             "signal_date": dt.date.fromisoformat(r["signal_date"])} for r in rows]
    fwd = compute_forward_returns(price_store, cal.dates, sigs, [5, 21, 63])
    fwd_by = {(r["company_id"], str(r["signal_date"])): r for r in fwd}
    for r in rows:
        fr = fwd_by.get((r["company_id"], r["signal_date"]), {})
        r["ret_5"] = fr.get("ret_5"); r["ret_21"] = fr.get("ret_21"); r["ret_63"] = fr.get("ret_63")
    return rows


def load_or_build_signals():
    cache = OUT / "phase3_signals.csv"
    cfg = BacktestConfig()
    build_sig = sha({"cfg": cfg.hash(), "rev": frozen_model_identifiers()["implementation_revision"]})
    if cache.exists():
        head = cache.read_text(encoding="utf-8-sig").splitlines()[:1]
        # simple signature check via sidecar
        sigf = OUT / "phase3_signals.sig"
        if sigf.exists() and sigf.read_text() == build_sig:
            rows = []
            for r in csv.DictReader(open(cache, encoding="utf-8-sig")):
                for k in ("factor_rank", "factor_available", "category_available"):
                    r[k] = json.loads(r[k]) if r.get(k) else {}
                for k in ("quant_score", "growth_score", "profitability_score", "valuation_score",
                          "market_score", "data_quality_score", "n_factors_available", "ret_5", "ret_21", "ret_63"):
                    r[k] = float(r[k]) if r.get(k) not in (None, "", "None") else None
                r["n_factors_available"] = int(r["n_factors_available"]) if r["n_factors_available"] is not None else 0
                rows.append(r)
            print("loaded cached signals:", len(rows)); return rows
    rows = build_signals()
    wcsv(cache, rows)
    (OUT / "phase3_signals.sig").write_text(build_sig, encoding="utf-8")
    print("built signals:", len(rows))
    return rows


# ---------------------------------------------------------------- diagnostics
def stratum(n):
    return "low" if n <= 7 else ("high" if n >= 15 else "medium")


def per_date_factor_ic(rows, factor, ret="ret_21"):
    by = {}
    for r in rows:
        by.setdefault(r["signal_date"], []).append(r)
    out = []
    for d in sorted(by):
        xs = [x["factor_rank"].get(factor) for x in by[d]]
        ys = [x.get(ret) for x in by[d]]
        out.append((d, DG.spearman(xs, ys)))
    return out


def within_stratum_factor_ic(rows, factor, ret="ret_21"):
    by = {}
    for r in rows:
        by.setdefault(r["signal_date"], []).append(r)
    ics = []
    for d in sorted(by):
        for st in ("low", "medium", "high"):
            seg = [x for x in by[d] if stratum(x["n_factors_available"]) == st]
            v = DG.spearman([x["factor_rank"].get(factor) for x in seg], [x.get(ret) for x in seg])
            if v is not None:
                ics.append(v)
    return ics


def factor_quantile_monotonicity(rows, factor, ret="ret_21", q=5):
    by = {}
    for r in rows:
        by.setdefault(r["signal_date"], []).append(r)
    bucket_means = [[] for _ in range(q)]
    for d in sorted(by):
        cs = [x for x in by[d] if x.get(ret) is not None and x["factor_rank"].get(factor) is not None]
        if len(cs) < q:
            continue
        cs.sort(key=lambda x: x["factor_rank"][factor])
        for i in range(q):
            lo = int(i * len(cs) / q); hi = int((i + 1) * len(cs) / q) if i < q - 1 else len(cs)
            bucket_means[i].append(mean([x[ret] for x in cs[lo:hi]]))
    bm = [mean(b) for b in bucket_means]
    trend = DG.spearman(list(range(q)), bm) if all(v is not None for v in bm) else None
    return bm, trend


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = load_or_build_signals()
    by_date = {}
    for r in rows:
        by_date.setdefault(r["signal_date"], []).append(r)
    dates = sorted(by_date)

    # ---------------- per-factor validation ----------------
    factor_rows = []
    for f in FACTORS:
        pd_ic = {d: v for d, v in per_date_factor_ic(rows, f)}
        ics21 = [pd_ic[d] for d in dates]
        controlled = within_stratum_factor_ic(rows, f)
        avail = sum(1 for r in rows if r["factor_available"].get(f))
        # horizons
        hics = {}
        for h in (5, 21, 63):
            vals = [v for _, v in per_date_factor_ic(rows, f, ret=f"ret_{h}")]
            hics[f"ic_{h}d"] = mean(vals)
        # subperiods
        def sub(years):
            vals = [pd_ic[d] for d in dates if d[:4] in years]
            return mean(vals), len([v for v in vals if v is not None])
        s1, n1 = sub({"2021", "2022", "2023"}); s2, n2 = sub({"2024", "2025"})
        # concentration: max period share of sum of |IC contributions|
        icv = [pd_ic[d] for d in dates if pd_ic[d] is not None]
        tot = sum(abs(v) for v in icv)
        conc_period = (max(abs(v) for v in icv) / tot) if tot else None
        # missingness: returns present vs absent
        pres = [r["ret_21"] for r in rows if r["factor_available"].get(f) and r.get("ret_21") is not None]
        absn = [r["ret_21"] for r in rows if not r["factor_available"].get(f) and r.get("ret_21") is not None]
        bm, mono = factor_quantile_monotonicity(rows, f)
        raw_ic = mean(ics21)
        ctrl_ic = mean(controlled)
        ci = block_bootstrap_ci(ics21)
        factor_rows.append({
            "factor_code": f, "category": FACTOR_TO_CAT.get(f), "current_weight": WEIGHT_BY_RANK.get(f),
            "coverage_pct": round(avail / len(rows) * 100, 2), "sample_count": sum(1 for r in rows if r["factor_available"].get(f)),
            "raw_ic": raw_ic, "controlled_ic": ctrl_ic, "ic_ci_low": ci["ci_low"], "ic_ci_high": ci["ci_high"],
            "ic_hit_rate": (sum(1 for v in icv if v > 0) / len(icv)) if icv else None,
            "median_ic": statistics.median(icv) if icv else None,
            "ic_std": statistics.pstdev(icv) if len(icv) > 1 else None, "n_periods": len(icv),
            "ic_5d": hics["ic_5d"], "ic_21d": hics["ic_21d"], "ic_63d": hics["ic_63d"],
            "ic_2021_2023": s1, "ic_2024_2025": s2,
            "period_concentration": conc_period,
            "mean_ret_present": mean(pres), "mean_ret_absent": mean(absn),
            "monotonicity_trend": mono,
            "expected_direction": EXPECTED_DIRECTION[f],
        })

    # classifications (pre-declared priority)
    def classify(r):
        if (r["coverage_pct"] or 0) < 5 or (r["n_periods"] or 0) < 24:
            return "INSUFFICIENT_DATA"
        raw, ctrl = r["raw_ic"], r["controlled_ic"]
        s1, s2 = r["ic_2021_2023"], r["ic_2024_2025"]
        if ctrl is None or raw is None:
            return "INSUFFICIENT_DATA"
        # direction conflict
        if ctrl <= -0.02:
            return "DIRECTION_UNSTABLE"
        if raw * ctrl < 0 and abs(ctrl) < 0.01:
            return "COVERAGE_CONFOUNDED"
        if s1 is not None and s2 is not None and s1 * s2 < 0 and abs(s2) > 0.02:
            return "TIME_UNSTABLE"
        if abs(ctrl) >= 0.03 and raw * ctrl > 0:
            return "ROBUST_SIGNAL"
        if abs(ctrl) >= 0.015 and raw * ctrl > 0:
            return "WEAK_BUT_CONSISTENT"
        return "NO_MEASURABLE_SIGNAL"

    for r in factor_rows:
        r["evidence_classification"] = classify(r)
        r["direction_status"] = "DIRECTION_REVIEW_REQUIRED" if (r["controlled_ic"] is not None and r["controlled_ic"] <= -0.02) else "OK"
    wcsv(OUT / "factor_validation.csv", factor_rows)

    # ---------------- incremental value: per-date multivariate OLS ----------------
    coefs = {f: [] for f in FACTORS}
    for d in dates:
        cs = [x for x in by_date[d] if x.get("ret_21") is not None]
        if len(cs) < len(FACTORS) + 5:
            continue
        X = [[x["factor_rank"].get(f) or 0.0 for f in FACTORS] for x in cs]
        Y = [x["ret_21"] for x in cs]
        b = ols(X, Y)
        if b:
            for i, f in enumerate(FACTORS):
                coefs[f].append(b[i + 1])
    inc_rows = []
    for f in FACTORS:
        c = coefs[f]
        inc_rows.append({"factor_code": f, "mean_incremental_coef": mean(c),
                         "incremental_coef_std": statistics.pstdev(c) if len(c) > 1 else None,
                         "n_dates": len(c), "label": "DIAGNOSTIC_ONLY_NOT_MODEL"})
    wcsv(OUT / "factor_incremental_value.csv", inc_rows)

    # ---------------- redundancy matrix ----------------
    pairs = []
    for i, f1 in enumerate(FACTORS):
        for f2 in FACTORS[i + 1:]:
            xs, ys = [], []
            for r in rows:
                if r["factor_available"].get(f1) and r["factor_available"].get(f2):
                    xs.append(r["factor_rank"].get(f1)); ys.append(r["factor_rank"].get(f2))
            pairs.append({"factor_a": f1, "factor_b": f2, "rank_corr": DG.spearman(xs, ys), "n": len(xs)})
    wcsv(OUT / "factor_redundancy.csv", pairs)
    top_redundant = sorted([p for p in pairs if p["rank_corr"] is not None], key=lambda p: -abs(p["rank_corr"]))[:10]

    # ---------------- leave-one-factor-out diagnostic QuantScore ----------------
    def diag_quant(r, drop=None):
        cats = {}
        for cat in CATEGORY:
            s = 0.0
            for f in CATEGORY[cat]:
                if f == drop:
                    continue
                s += (WEIGHT_BY_RANK.get(f) or 0.0) * (r["factor_rank"].get(f) or 0.0)
            cats[cat] = max(0.0, s)
        return (r.get("data_quality_score") or 0.0) * sum(cats.values())

    def ic_of(score_fn):
        vals = []
        for d in dates:
            xs = [score_fn(r) for r in by_date[d]]
            ys = [r.get("ret_21") for r in by_date[d]]
            v = DG.spearman(xs, ys)
            if v is not None:
                vals.append(v)
        return mean(vals)

    baseline_ic = ic_of(lambda r: diag_quant(r))
    loo_rows = [{"dropped_factor": "(none)", "variant_ic": baseline_ic, "ic_delta_vs_baseline": 0.0,
                 "label": "DIAGNOSTIC_ONLY_NOT_MODEL"}]
    for f in FACTORS:
        v = ic_of(lambda r, f=f: diag_quant(r, drop=f))
        loo_rows.append({"dropped_factor": f, "variant_ic": v,
                         "ic_delta_vs_baseline": (v - baseline_ic) if (v is not None and baseline_ic is not None) else None,
                         "label": "DIAGNOSTIC_ONLY_NOT_MODEL"})
    wcsv(OUT / "leave_one_factor_out.csv", loo_rows)

    # ---------------- category validation ----------------
    def cat_ic_series(cat, ret="ret_21", years=None, st=None):
        out = []
        for d in dates:
            if years and d[:4] not in years:
                continue
            cs = by_date[d] if st is None else [r for r in by_date[d] if stratum(r["n_factors_available"]) == st]
            v = DG.spearman([r.get(f"{cat}_score") for r in cs], [r.get(ret) for r in cs])
            if v is not None:
                out.append(v)
        return out

    cat_rows = []
    for cat in CATEGORY:
        raw = cat_ic_series(cat)
        ctrl = []
        for st in ("low", "medium", "high"):
            ctrl.extend(cat_ic_series(cat, st=st))
        cat_rows.append({
            "category": cat, "raw_ic": mean(raw), "controlled_ic": mean(ctrl),
            "ic_ci_low": block_bootstrap_ci(raw)["ci_low"], "ic_ci_high": block_bootstrap_ci(raw)["ci_high"],
            "ic_5d": mean(cat_ic_series(cat, "ret_5")), "ic_21d": mean(raw),
            "ic_63d": mean(cat_ic_series(cat, "ret_63")),
            "ic_2021_2023": mean(cat_ic_series(cat, years=("2021", "2022", "2023"))),
            "ic_2024_2025": mean(cat_ic_series(cat, years=("2024", "2025")))})
    wcsv(OUT / "category_validation.csv", cat_rows)

    # ---------------- weight evidence ----------------
    weight_rows = []
    for r in factor_rows:
        f = r["factor_code"]; cls = r["evidence_classification"]; w = WEIGHT_BY_RANK.get(f) or 0
        ctrl = r["controlled_ic"]
        if cls in ("NO_MEASURABLE_SIGNAL", "INSUFFICIENT_DATA") and w >= 5:
            status = "OVERWEIGHTED_RELATIVE_TO_EVIDENCE"
        elif cls in ("NO_MEASURABLE_SIGNAL", "INSUFFICIENT_DATA", "COVERAGE_CONFOUNDED", "TIME_UNSTABLE"):
            status = "INSUFFICIENT_EVIDENCE"
        elif cls in ("ROBUST_SIGNAL", "WEAK_BUT_CONSISTENT") and w <= 3 and ctrl is not None and ctrl >= 0.03:
            status = "UNDERWEIGHTED_RELATIVE_TO_EVIDENCE"
        elif cls in ("ROBUST_SIGNAL", "WEAK_BUT_CONSISTENT"):
            status = "SUPPORTED_BY_EVIDENCE"
        else:
            status = "INSUFFICIENT_EVIDENCE"
        weight_rows.append({"factor_code": f, "current_weight": w, "evidence_classification": cls,
                            "controlled_ic": ctrl, "incremental_coef": next(
                                (x["mean_incremental_coef"] for x in inc_rows if x["factor_code"] == f), None),
                            "weight_status": status})
    wcsv(OUT / "weight_evidence.csv", weight_rows)

    # ---------------- explicit 21-row decision table ----------------
    red_max = {}
    for p in pairs:
        if p["rank_corr"] is None:
            continue
        for f in (p["factor_a"], p["factor_b"]):
            red_max[f] = max(red_max.get(f, 0.0), abs(p["rank_corr"]))
    inc_map = {x["factor_code"]: x["mean_incremental_coef"] for x in inc_rows}
    wmap = {x["factor_code"]: x for x in weight_rows}
    next_exp = {
        "ROBUST_SIGNAL": "keep; validate in OOS",
        "WEAK_BUT_CONSISTENT": "keep; monitor in OOS",
        "COVERAGE_CONFOUNDED": "exp-C missingness/data-coverage experiment",
        "TIME_UNSTABLE": "exp-B/exp-C review; re-validate in OOS",
        "DIRECTION_UNSTABLE": "exp-B direction review; do NOT flip in place",
        "INSUFFICIENT_DATA": "exp-C re-ingestion/coverage; cannot validate historically",
        "NO_MEASURABLE_SIGNAL": "exp-A drop candidate (diagnostic only)",
    }
    decision = []
    for r in factor_rows:
        f = r["factor_code"]; s1, s2 = r["ic_2021_2023"], r["ic_2024_2025"]
        if s1 is None or s2 is None:
            tstab = "unknown"
        elif s1 != 0 and s2 != 0 and s1 * s2 > 0:
            tstab = "stable" if min(abs(s1), abs(s2)) >= 0.01 else "weak"
        elif abs(s1) < 0.01 and s2 is not None and abs(s2) >= 0.03:
            tstab = "2024_2025_only"
        else:
            tstab = "unstable"
        hs = [r["ic_5d"], r["ic_21d"], r["ic_63d"]]
        hs = [h for h in hs if h is not None]
        if len(hs) == 3 and all(h > 0 for h in hs):
            hstab = "persists_all_horizons"
        elif len(hs) >= 1 and all(h <= 0 for h in hs):
            hstab = "negative_all_horizons"
        elif len(hs) >= 1 and hs[0] > 0 and (len(hs) < 3 or hs[-1] <= 0):
            hstab = "short_only"
        else:
            hstab = "mixed"
        decision.append({
            "factor": f, "category": r["category"], "current_weight": r["current_weight"],
            "coverage_pct": r["coverage_pct"], "raw_ic": r["raw_ic"], "controlled_ic": r["controlled_ic"],
            "ci": f"[{r['ic_ci_low']},{r['ic_ci_high']}]" if r["ic_ci_low"] is not None else "",
            "time_stability": tstab, "horizon_stability": hstab,
            "incremental_value": inc_map.get(f), "missingness_confounding": r["evidence_classification"] == "COVERAGE_CONFOUNDED",
            "max_redundancy": red_max.get(f), "direction_status": r["direction_status"],
            "evidence_classification": r["evidence_classification"],
            "weight_status": wmap[f]["weight_status"],
            "recommended_next_experiment": next_exp.get(r["evidence_classification"], "review"),
        })
    wcsv(OUT / "FACTOR_DECISION_TABLE.csv", decision)

    # ---------------- QuantScore decomposition ----------------
    def ic_series(score_fn):
        return [DG.spearman([score_fn(r) for r in by_date[d]], [r.get("ret_21") for r in by_date[d]]) for d in dates]
    qs_ic = mean([v for v in ic_series(lambda r: r.get("quant_score")) if v is not None])
    nf_ic = mean([v for v in ic_series(lambda r: r.get("n_factors_available")) if v is not None])
    cat_ic = mean([v for v in ic_series(lambda r: (r.get("growth_score") or 0) + (r.get("profitability_score") or 0)
                                        + (r.get("valuation_score") or 0) + (r.get("market_score") or 0)) if v is not None])
    mkt_ic = mean([v for v in ic_series(lambda r: r.get("market_score")) if v is not None])
    dq_ic = mean([v for v in ic_series(lambda r: r.get("data_quality_score")) if v is not None])
    decomposition = {"quant_score_ic": qs_ic, "category_sum_ic": cat_ic, "n_factors_ic": nf_ic,
                     "market_score_ic": mkt_ic, "data_quality_ic": dq_ic,
                     "note": "diagnostic decomposition; not a replacement score"}

    # ---------------- OOS protocol (frozen) ----------------
    oos = {
        "protocol": "chronological", "development": ["2021", "2022", "2023"],
        "validation": ["2024"], "holdout": ["2025"], "forward_monitoring": ["2026"],
        "holdout_used_for_selection": False,
        "rules": ["no hyperparameter/weight selection on holdout",
                  "model selection only on development+validation",
                  "holdout evaluated once per experiment version",
                  "2026 treated as monitoring only (n=2 in-sample here)"],
        "return_convention": "raw_price_return", "rebalance": "M",
        "frozen": True,
    }
    (OUT / "oos_protocol.json").write_text(json.dumps(oos, indent=2), encoding="utf-8")

    # ---------------- model v2 experiment plan (paper) ----------------
    weak = [r["factor_code"] for r in factor_rows if r["evidence_classification"] in
            ("NO_MEASURABLE_SIGNAL", "INSUFFICIENT_DATA")]
    confounded = [r["factor_code"] for r in factor_rows if r["evidence_classification"] == "COVERAGE_CONFOUNDED"]
    robust = [r["factor_code"] for r in factor_rows if r["evidence_classification"] == "ROBUST_SIGNAL"]
    v2 = {
        "canonical-v2-exp-A": {"hypothesis": "remove factors with NO_MEASURABLE_SIGNAL/INSUFFICIENT_DATA",
                               "drop": weak, "keep_rules": "otherwise identical to canonical-v1"},
        "canonical-v2-exp-B": {"hypothesis": "reweight robust factors up / weak down (grid only on dev+val)",
                               "robust": robust, "note": "no holdout tuning"},
        "canonical-v2-exp-C": {"hypothesis": "alternative missingness policy (new model/version)",
                               "focus": confounded, "note": "does not mutate canonical-v1"},
    }
    (OUT / "model_v2_experiment_plan.json").write_text(json.dumps(v2, indent=2, default=str), encoding="utf-8")

    # ---------------- summary + hashes ----------------
    summary = {
        "baseline": frozen_model_identifiers(),
        "n_signals": len(rows), "n_dates": len(dates),
        "classification_counts": {c: sum(1 for r in factor_rows if r["evidence_classification"] == c)
                                  for c in set(r["evidence_classification"] for r in factor_rows)},
        "direction_review_required": [r["factor_code"] for r in factor_rows if r["direction_status"] != "OK"],
        "top_redundant_pairs": top_redundant,
        "baseline_diag_ic": baseline_ic,
        "category": cat_rows,
        "decomposition": decomposition,
        "oos": oos,
        "v2_plan": v2,
        "hashes": {},
    }
    summary["hashes"]["factor_validation"] = sha(factor_rows)
    summary["hashes"]["incremental"] = sha(inc_rows)
    summary["hashes"]["loo"] = sha(loo_rows)
    summary["hashes"]["redundancy"] = sha(pairs)
    summary["hashes"]["category"] = sha(cat_rows)
    summary["hashes"]["weight_evidence"] = sha(weight_rows)
    summary["hashes"]["summary"] = sha({k: v for k, v in summary.items() if k != "hashes"})
    (OUT / "phase3_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("classes:", summary["classification_counts"])
    print("baseline diag IC", baseline_ic, "QS IC", qs_ic, "cat-sum IC", cat_ic, "nfactors IC", nf_ic)
    print("summary hash", summary["hashes"]["summary"])
    return summary


if __name__ == "__main__":
    main()
