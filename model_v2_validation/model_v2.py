"""Model v2 experimentation under the frozen OOS protocol.

Consumes the frozen Phase-3 PIT signal snapshot
(`canonical_postgres_v1_2_1/backtesting_v1/output/phase3_signals.csv`), which was
computed **before** any forward return and is never recomputed here. canonical-v1
(`quant_score`) stays frozen as the baseline; all candidates are new version ids.

No production writes. File-based deterministic artifacts under output/.

Design (see MODEL_V2_PROTOCOL.md):
  * Model A `canonical-v2-exp-a` Robust Core       -> robust factors only
  * Model B `canonical-v2-exp-b` Coverage-Aware    -> broad set, missing-normalized
  * Model C `canonical-v2-exp-c` Category-Balanced -> category-first, missing-normalized
  * Baseline `canonical-v1-dev`                    -> frozen quant_score column

All directions are as stored (higher rank = better); direction-unstable factors
are held, never flipped. Weights are predeclared in MODEL_REGISTRY (no holdout
tuning; no tuning against 2024 beyond the predeclared candidate set).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIGNALS = REPO / "canonical_postgres_v1_2_1" / "backtesting_v1" / "output" / "phase3_signals.csv"
OUT = HERE / "output"

HORIZONS = (5, 21, 63)
PRIMARY = 21
TOP_N = 20
COST_BPS_PER_SIDE = 10.0
COVERAGE_LOW, COVERAGE_HIGH = 7, 14

PERIODS = {
    "development": (2021, 2023),
    "validation": (2024, 2024),
    "holdout": (2025, 2025),
    "forward": (2026, 2026),
}

ALL_FACTORS = [
    "SalesGrowthRank", "SalesGrowth3MRank", "RevenueGrowthRank",
    "OperatingProfitGrowthRank", "NetProfitGrowthRank",
    "OperatingMarginRank", "NetMarginRank", "MarginTrendRank",
    "InterestCoverageRank", "EarningsQualityRank",
    "PERank", "PSRank", "PBRank",
    "LiquidityRank", "LeverageRank", "CurrentRatioRank",
    "StabilityRank", "LowVolatilityRank", "MomentumRank",
    "ROERank", "CashConversionRank",
]

CATEGORY_FACTORS = {
    "growth": ["SalesGrowthRank", "SalesGrowth3MRank", "RevenueGrowthRank",
               "OperatingProfitGrowthRank", "NetProfitGrowthRank"],
    "profitability": ["OperatingMarginRank", "NetMarginRank", "ROERank",
                      "MarginTrendRank", "InterestCoverageRank",
                      "CashConversionRank", "EarningsQualityRank"],
    "valuation": ["PERank", "PSRank", "PBRank"],
    "market": ["LiquidityRank", "LeverageRank", "CurrentRatioRank",
               "StabilityRank", "LowVolatilityRank", "MomentumRank"],
}


@dataclass(frozen=True)
class ModelConfig:
    model_version: str
    implementation_revision: str
    kind: str                       # "robust" | "coverage" | "category"
    factors: dict                   # code -> weight (robust/coverage)
    category_weights: dict = None   # category -> weight (category)
    missing_policy: str = "drop_unavailable_renormalize"
    created_at: str = "2026-09-25"

    def payload(self) -> dict:
        return {
            "model_version": self.model_version,
            "implementation_revision": self.implementation_revision,
            "kind": self.kind,
            "factors": {k: self.factors[k] for k in sorted(self.factors)},
            "category_weights": ({k: self.category_weights[k] for k in sorted(self.category_weights)}
                                 if self.category_weights else {}),
            "missing_policy": self.missing_policy,
            "horizons": list(HORIZONS),
            "primary_horizon": PRIMARY,
            "top_n": TOP_N,
            "cost_bps_per_side": COST_BPS_PER_SIDE,
            "coverage_buckets": [COVERAGE_LOW, COVERAGE_HIGH],
        }

    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.payload(), sort_keys=True).encode()).hexdigest()


MODELS = {
    "canonical-v2-exp-a": ModelConfig(
        model_version="canonical-v2-exp-a",
        implementation_revision="model-v2-robust-core-v1",
        kind="robust",
        factors={
            "PERank": 0.35, "SalesGrowthRank": 0.20, "RevenueGrowthRank": 0.15,
            "LowVolatilityRank": 0.15, "SalesGrowth3MRank": 0.08, "EarningsQualityRank": 0.07,
        },
    ),
    "canonical-v2-exp-b": ModelConfig(
        model_version="canonical-v2-exp-b",
        implementation_revision="model-v2-coverage-aware-v1",
        kind="coverage",
        factors={
            "PERank": 0.18, "SalesGrowthRank": 0.12, "RevenueGrowthRank": 0.10,
            "LowVolatilityRank": 0.10, "SalesGrowth3MRank": 0.06, "EarningsQualityRank": 0.06,
            "OperatingProfitGrowthRank": 0.05, "MarginTrendRank": 0.04,
            "InterestCoverageRank": 0.04, "PSRank": 0.04, "PBRank": 0.03,
            "LiquidityRank": 0.03, "StabilityRank": 0.03, "MomentumRank": 0.03,
            "NetProfitGrowthRank": 0.03, "OperatingMarginRank": 0.02,
            "NetMarginRank": 0.02, "ROERank": 0.02, "LeverageRank": 0.01,
            "CurrentRatioRank": 0.01, "CashConversionRank": 0.01,
        },
    ),
    "canonical-v2-exp-c": ModelConfig(
        model_version="canonical-v2-exp-c",
        implementation_revision="model-v2-category-balanced-v1",
        kind="category",
        factors={},  # derived from CATEGORY_FACTORS
        category_weights={"growth": 0.35, "profitability": 0.20,
                          "valuation": 0.30, "market": 0.15},
    ),
}

BASELINE_VERSION = "canonical-v1-dev"


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------
def score_robust_like(cfg: ModelConfig, ranks: dict, avail: dict):
    num = den = 0.0
    for code, w in cfg.factors.items():
        if avail.get(code) and ranks.get(code) is not None:
            num += w * float(ranks[code])
            den += w
    if den == 0:
        return None
    return num / den


def score_category(cfg: ModelConfig, ranks: dict, avail: dict):
    total = 0.0
    den = 0.0
    for cat, w in cfg.category_weights.items():
        codes = CATEGORY_FACTORS[cat]
        vals = [float(ranks[c]) for c in codes if avail.get(c) and ranks.get(c) is not None]
        if not vals:
            continue
        total += w * (sum(vals) / len(vals))
        den += w
    if den == 0:
        return None
    return total / den


def score_row(cfg: ModelConfig, ranks: dict, avail: dict):
    if cfg.kind == "category":
        return score_category(cfg, ranks, avail)
    return score_robust_like(cfg, ranks, avail)


# --------------------------------------------------------------------------
# data loading / periods
# --------------------------------------------------------------------------
def load_signals(path: Path = SIGNALS) -> list:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            try:
                ranks = json.loads(r["factor_rank"]) if r.get("factor_rank") else {}
                avail = json.loads(r["factor_available"]) if r.get("factor_available") else {}
            except Exception:
                continue
            rec = {
                "signal_date": r["signal_date"],
                "year": int(r["signal_date"][:4]),
                "company_id": r["company_id"],
                "n_factors_available": int(r["n_factors_available"] or 0),
                "quant_score": _f(r.get("quant_score")),
                "ranks": ranks,
                "avail": avail,
            }
            for h in HORIZONS:
                rec[f"ret_{h}"] = _f(r.get(f"ret_{h}"))
            rows.append(rec)
    return rows


def _f(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def period_rows(rows, period):
    lo, hi = PERIODS[period]
    return [r for r in rows if lo <= r["year"] <= hi]


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------
def _rankdata(a: np.ndarray) -> np.ndarray:
    order = np.argsort(a, kind="mergesort")
    ranks = np.empty(len(a), dtype=float)
    ranks[order] = np.arange(1, len(a) + 1)
    # average ties
    sa = a[order]
    i = 0
    while i < len(sa):
        j = i + 1
        while j < len(sa) and sa[j] == sa[i]:
            j += 1
        if j - i > 1:
            ranks[order[i:j]] = (i + 1 + j) / 2.0
        i = j
    return ranks


def spearman(x, y) -> float:
    if len(x) < 3:
        return None
    rx, ry = _rankdata(np.asarray(x, dtype=float)), _rankdata(np.asarray(y, dtype=float))
    rx, ry = rx - rx.mean(), ry - ry.mean()
    denom = np.sqrt((rx * rx).sum() * (ry * ry).sum())
    if denom == 0:
        return None
    return float((rx * ry).sum() / denom)


def pearson(x, y):
    if len(x) < 3:
        return None
    x, y = np.asarray(x, float), np.asarray(y, float)
    x, y = x - x.mean(), y - y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return None if d == 0 else float((x * y).sum() / d)


def _md(values):
    v = [x for x in values if x is not None]
    if not v:
        return 0.0
    a = np.sort(np.array(v))
    n = len(a)
    return float(a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2.0)


def _p95(values):
    v = sorted(x for x in values if x is not None)
    if not v:
        return 0.0
    return float(v[int(0.95 * (len(v) - 1))])


def _max_drawdown(chained):
    peak = -1e18
    mdd = 0.0
    for v in chained:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return mdd


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def _cross_sections(rows, score_fn):
    """Build {signal_date: [(score, ret_21, ret_5, ret_63, n_avail, company)]}."""
    by_date = {}
    for r in rows:
        s = score_fn(r)
        if s is None:
            continue
        by_date.setdefault(r["signal_date"], []).append(
            (s, r.get("ret_21"), r.get("ret_5"), r.get("ret_63"),
             r["n_factors_available"], r["company_id"]))
    return by_date


def evaluate(rows, name, score_fn):
    cs = _cross_sections(rows, score_fn)
    dates = sorted(cs)
    ic = {h: [] for h in HORIZONS}
    top_bottom = []
    monthly = []
    bench = []
    turns = []
    coverage_corr = []
    prev_top = set()
    for d in dates:
        secs = cs[d]
        # tuple layout: (score, ret_21, ret_5, ret_63, n_avail, company)
        for h, pos in ((21, 1), (5, 2), (63, 3)):
            pairs = [(a[0], a[pos]) for a in secs if a[pos] is not None]
            if len(pairs) >= 5:
                ic[h].append(spearman([p[0] for p in pairs], [p[1] for p in pairs]))
        pairs21 = [(a[0], a[1]) for a in secs if a[1] is not None]
        if len(pairs21) >= 5:
            vals = sorted(pairs21, key=lambda x: x[0])
            q = max(1, len(vals) // 5)
            bottom = np.mean([v for _, v in vals[:q]])
            top = np.mean([v for _, v in vals[-q:]])
            top_bottom.append(float(top - bottom))
        # portfolio
        elig = sorted([a for a in secs if a[1] is not None], key=lambda a: -a[0])
        if elig:
            sel = elig[:TOP_N]
            cur = {a[5] for a in sel}
            if prev_top:
                union = len(cur | prev_top)
                turns.append(1.0 - (len(cur & prev_top) / union if union else 0.0))
            prev_top = cur
            monthly.append(float(np.mean([a[1] for a in sel])))
            bench.append(float(np.mean([a[1] for a in elig])))
        # coverage bias
        if len(secs) >= 5:
            coverage_corr.append(pearson([a[0] for a in secs], [a[4] for a in secs]))

    def _ic_summary(vals):
        v = [x for x in vals if x is not None]
        if not v:
            return {"n": 0, "mean": 0.0, "median": 0.0, "positive_fraction": 0.0, "std": 0.0, "t_stat": 0.0}
        a = np.array(v)
        sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
        t = float(a.mean() / (sd / np.sqrt(len(a)))) if sd > 0 else 0.0
        return {"n": len(a), "mean": float(a.mean()), "median": float(np.median(a)),
                "positive_fraction": float((a > 0).mean()), "std": sd, "t_stat": t}

    def _compound(rets, cost_bps=0.0):
        if not rets:
            return {"cumulative_return": 0.0, "max_drawdown": 0.0, "volatility": 0.0, "n": 0}
        chained = []
        v = 1.0
        for i, r in enumerate(rets):
            c = (turns[i] * 2 * cost_bps / 10000.0) if (cost_bps and i < len(turns)) else 0.0
            v *= (1.0 + r - c)
            chained.append(v)
        arr = np.array(rets)
        return {
            "cumulative_return": float(v - 1.0),
            "max_drawdown": float(_max_drawdown(chained)),
            "volatility": float(arr.std(ddof=1)) if len(arr) > 1 else 0.0,
            "mean_monthly": float(arr.mean()),
            "n": len(arr),
        }

    top_bottom_mean = float(np.mean(top_bottom)) if top_bottom else 0.0
    return {
        "model": name,
        "n_dates": len(dates),
        "n_signals": sum(len(v) for v in cs.values()),
        "ic": {f"ret_{h}": _ic_summary(ic[h]) for h in HORIZONS},
        "quantile_top_minus_bottom_21": top_bottom_mean,
        "portfolio_raw": _compound(monthly, 0.0),
        "portfolio_cost": _compound(monthly, COST_BPS_PER_SIDE),
        "benchmark_raw": _compound(bench, 0.0),
        "turnover_mean": float(np.mean(turns)) if turns else 0.0,
        "coverage_score_correlation": float(np.mean([c for c in coverage_corr if c is not None]))
        if coverage_corr else 0.0,
        "n_eligible_mean": float(np.mean([len(v) for v in cs.values()])) if cs else 0.0,
    }


def yearly(rows, name, score_fn):
    out = []
    for year in sorted({r["year"] for r in rows}):
        sub = [r for r in rows if r["year"] == year]
        ev = evaluate(sub, name, score_fn)
        out.append({"year": year, "model": name,
                    "mean_ic_21": ev["ic"]["ret_21"]["mean"],
                    "positive_ic_fraction": ev["ic"]["ret_21"]["positive_fraction"],
                    "top_minus_bottom_21": ev["quantile_top_minus_bottom_21"],
                    "portfolio_raw": ev["portfolio_raw"]["cumulative_return"],
                    "n_dates": ev["n_dates"], "n_signals": ev["n_signals"]})
    return out


def coverage_strata(rows, name, score_fn):
    strata = {"low": (0, COVERAGE_LOW), "medium": (COVERAGE_LOW + 1, COVERAGE_HIGH),
              "high": (COVERAGE_HIGH + 1, 10**9)}
    out = []
    for label, (lo, hi) in strata.items():
        sub = [r for r in rows if lo <= r["n_factors_available"] <= hi]
        ev = evaluate(sub, name, score_fn)
        out.append({"model": name, "stratum": label,
                    "n_signals": ev["n_signals"], "n_dates": ev["n_dates"],
                    "mean_ic_21": ev["ic"]["ret_21"]["mean"],
                    "top_minus_bottom_21": ev["quantile_top_minus_bottom_21"],
                    "portfolio_raw": ev["portfolio_raw"]["cumulative_return"]})
    return out


# --------------------------------------------------------------------------
# selection (dev + validation ONLY; holdout never consulted)
# --------------------------------------------------------------------------
SELECTION_WEIGHTS = {"mean_ic": 0.5, "stability": 0.2, "coverage": 0.2, "risk": 0.1}


def selection_score(dev_ev, val_ev):
    ic = 0.5 * dev_ev["ic"]["ret_21"]["mean"] + 0.5 * val_ev["ic"]["ret_21"]["mean"]
    pos = 0.5 * dev_ev["ic"]["ret_21"]["positive_fraction"] + 0.5 * val_ev["ic"]["ret_21"]["positive_fraction"]
    cov = abs(0.5 * dev_ev["coverage_score_correlation"] + 0.5 * val_ev["coverage_score_correlation"])
    dd = abs(0.5 * dev_ev["portfolio_raw"]["max_drawdown"] + 0.5 * val_ev["portfolio_raw"]["max_drawdown"])
    return {
        "mean_ic": ic, "positive_fraction": pos, "coverage_bias": cov, "drawdown": dd,
        "score": SELECTION_WEIGHTS["mean_ic"] * ic
        + SELECTION_WEIGHTS["stability"] * pos
        - SELECTION_WEIGHTS["coverage"] * cov
        - SELECTION_WEIGHTS["risk"] * dd,
    }


# --------------------------------------------------------------------------
# io
# --------------------------------------------------------------------------
def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = fields or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def config_registry():
    reg = {}
    for mid, cfg in MODELS.items():
        reg[mid] = {
            "model_version": cfg.model_version,
            "implementation_revision": cfg.implementation_revision,
            "kind": cfg.kind,
            "factor_list": sorted(cfg.factors) if cfg.factors else sorted(
                f for fs in CATEGORY_FACTORS.values() for f in fs),
            "factor_directions": {c: "higher_is_better" for c in (sorted(cfg.factors) if cfg.factors else ALL_FACTORS)},
            "weights": {k: cfg.factors[k] for k in sorted(cfg.factors)} if cfg.factors else {},
            "category_weights": cfg.category_weights or {},
            "missing_policy": cfg.missing_policy,
            "development_period": "2021-2023",
            "validation_period": "2024",
            "holdout_period": "2025",
            "created_at": cfg.created_at,
            "config_hash": cfg.config_hash(),
        }
    reg[BASELINE_VERSION] = {
        "model_version": BASELINE_VERSION,
        "implementation_revision": "canonical-v1-dev+report-chain-ttm",
        "kind": "baseline_frozen",
        "factor_list": ALL_FACTORS,
        "factor_directions": {c: "higher_is_better" for c in ALL_FACTORS},
        "weights": "baseline_weights_v37 (frozen, not validated)",
        "missing_policy": "canonical-v1 neutral 0.3",
        "development_period": "2021-2023",
        "validation_period": "2024",
        "holdout_period": "2025",
        "created_at": "2026-09-25",
        "config_hash": "frozen-canonical-v1",
    }
    return reg


def main():
    rows = load_signals()
    score_fns = {mid: (lambda r, cfg=cfg: score_row(cfg, r["ranks"], r["avail"]))
                 for mid, cfg in MODELS.items()}
    score_fns[BASELINE_VERSION] = lambda r: r["quant_score"]

    candidates, ic_rows, port_rows, yearly_rows, cov_rows = [], [], [], [], []
    for mid in list(MODELS) + [BASELINE_VERSION]:
        fn = score_fns[mid]
        for period in PERIODS:
            sub = period_rows(rows, period)
            ev = evaluate(sub, mid, fn)
            port_rows.append({
                "model": mid, "period": period,
                "cumulative_return_raw": ev["portfolio_raw"]["cumulative_return"],
                "cumulative_return_cost": ev["portfolio_cost"]["cumulative_return"],
                "benchmark_raw": ev["benchmark_raw"]["cumulative_return"],
                "max_drawdown": ev["portfolio_raw"]["max_drawdown"],
                "volatility": ev["portfolio_raw"]["volatility"],
                "turnover": ev["turnover_mean"], "n_dates": ev["n_dates"],
            })
            candidates.append({"model": mid, "period": period, **{
                "mean_ic_5": ev["ic"]["ret_5"]["mean"], "mean_ic_21": ev["ic"]["ret_21"]["mean"],
                "mean_ic_63": ev["ic"]["ret_63"]["mean"],
                "median_ic_21": ev["ic"]["ret_21"]["median"],
                "positive_ic_fraction_21": ev["ic"]["ret_21"]["positive_fraction"],
                "t_stat_21": ev["ic"]["ret_21"]["t_stat"],
                "top_minus_bottom_21": ev["quantile_top_minus_bottom_21"],
                "portfolio_raw": ev["portfolio_raw"]["cumulative_return"],
                "portfolio_cost": ev["portfolio_cost"]["cumulative_return"],
                "benchmark_raw": ev["benchmark_raw"]["cumulative_return"],
                "max_drawdown": ev["portfolio_raw"]["max_drawdown"],
                "volatility": ev["portfolio_raw"]["volatility"],
                "turnover": ev["turnover_mean"],
                "n_eligible_mean": ev["n_eligible_mean"],
                "coverage_score_correlation": ev["coverage_score_correlation"],
                "n_dates": ev["n_dates"], "n_signals": ev["n_signals"]}})
            for h in HORIZONS:
                ic_rows.append({"model": mid, "period": period, "horizon": h,
                                **ev["ic"][f"ret_{h}"]})
            if period in ("development", "validation", "holdout"):
                for row in coverage_strata(sub, mid, fn):
                    cov_rows.append({"period": period, **row})
        for row in yearly(rows, mid, fn):
            yearly_rows.append(row)

    # selection using dev+val only
    dev = {c["model"]: c for c in candidates if c["period"] == "development"}
    val = {c["model"]: c for c in candidates if c["period"] == "validation"}
    evidence = {}
    for mid in MODELS:
        ev = selection_score(
            _ev_view(dev[mid], rows, mid, score_fns[mid], "development"),
            _ev_view(val[mid], rows, mid, score_fns[mid], "validation"))
        evidence[mid] = ev
    selected = max(evidence, key=lambda m: (evidence[m]["score"], -len(MODELS[m].factors)
                                            if MODELS[m].factors else -99))

    registry = config_registry()
    write_csv(OUT / "model_v2_candidates.csv", candidates)
    write_csv(OUT / "model_v2_ic.csv", ic_rows)
    write_csv(OUT / "model_v2_portfolio.csv", port_rows)
    write_csv(OUT / "model_v2_yearly.csv", yearly_rows)
    write_csv(OUT / "model_v2_coverage.csv", cov_rows)
    # holdout rows for all frozen candidates (each evaluated once)
    holdout = [c for c in candidates if c["period"] == "holdout"]
    write_csv(OUT / "model_v2_holdout.csv", holdout)
    summary = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "protocol": "frozen_chronological_2021_2023_2024_2025_2026",
        "baseline_version": BASELINE_VERSION,
        "selection_rule": "dev+validation only; weights "
                          f"{SELECTION_WEIGHTS}; holdout never consulted",
        "selection_evidence": evidence,
        "selected_candidate": selected,
        "selected_config_hash": registry[selected]["config_hash"],
        "candidates": registry,
        "holdout": {c["model"]: {k: c[k] for k in ("mean_ic_21", "positive_ic_fraction_21",
                                                   "top_minus_bottom_21", "portfolio_raw",
                                                   "max_drawdown", "turnover")}
                    for c in holdout},
    }
    (OUT / "model_v2_summary.json").write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (HERE / "MODEL_REGISTRY.json").write_text(
        json.dumps(registry, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"selected": selected, "config_hash": registry[selected]["config_hash"],
                      "evidence": evidence}, indent=2, default=str))
    return summary


def _ev_view(cand, rows, mid, fn, period):
    """Re-evaluate a candidate on a period to get the full evidence structure."""
    return evaluate(period_rows(rows, period), mid, fn)


if __name__ == "__main__":
    main()
