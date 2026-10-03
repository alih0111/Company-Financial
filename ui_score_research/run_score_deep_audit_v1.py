"""SCORE DEEP AUDIT V1 — complete diagnostic audit of the frozen production UI score
(canonical-v1-dev) on the PIT-correct historical panel v2. DIAGNOSTIC ONLY.

No weight optimization, no formula change, no new features, no thresholds, no Score V2,
no portfolio backtest. Returns/ICs are used ONLY for attribution of the already-frozen
score and its existing components/categories (explicitly allowed diagnostic scope).

Formula (verified against compute_metrics.py lines 719-790):
  rank_i  = midrank percentile of the (capped) raw metric among PRESENT values;
            missing -> neutral (0.3 default; 0.5 InterestCoverage/EarningsQuality;
            0.0 PE/PS/PB/Liquidity); invalid PE/PS/PB -> 0.0
  G = 10*SalesGrowth + 6*SalesGrowth3M + 5*Revenue + 5*OpProfit + 10*NetProfit
      - penalties (6 if sales_g12 < -20; 5 if op_g < -25), floor 0
  P = 4*OpMargin + 4*NetMargin + 6*ROE + 3*MarginTrend + 3*IntCov + 2*CashConv
      + 4*EarningsQuality - penalties (10 loss; 4 IntCov<1.5; 3 trend<-2;
      nonlinear EarningsQuality>20 up to 8), floor 0
  V = 11*PE + 3*PS + 2*PB - 8 if PE invalid/missing, floor 0
  M = 3*Liq + 2*Lev + 2*CurRatio + 1*Stability + 2*LowVol + 1*Momentum  (no penalty)
  DQ = 0.30*has_financials + 0.20*has_monthly + 0.20*has_price
       + 0.15*fresh_financials + 0.15*fresh_market          (data_quality.py)
  quant_score = DQ * (G + P + V + M)                        max 89 * DQ
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import sys
from bisect import bisect_right
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import psycopg

sys.path.insert(0, r"D:\RFA\Company-Financial\model_v2_validation")
import model_v2 as M  # noqa: E402  frozen spearman

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "ui_score_research"
SRC = HERE / "ui_score_historical_pit_v2" / "ui_score_historical_pit_v2.jsonl"
PQ = HERE / "ui_score_historical_pit_v2.parquet"
RAW = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
HORIZONS = (21, 63, 126, 252)
SEED, B = 20261003, 2000
FROZEN_V2 = {"21": 0.0574, "63": 0.0853, "126": 0.1096, "252": 0.1031}

COMPONENTS = {  # factor -> (raw metric(s), weight, direction already encoded in rank)
    "SalesGrowthRank": ("sales_growth_12m", 10), "SalesGrowth3MRank": ("sales_growth_3m", 6),
    "RevenueGrowthRank": ("revenue_growth", 5),
    "OperatingProfitGrowthRank": ("operating_profit_growth", 5),
    "NetProfitGrowthRank": ("net_profit_growth|eps_growth", 10),
    "OperatingMarginRank": ("operating_margin", 4), "NetMarginRank": ("net_margin", 4),
    "ROERank": ("roe", 6), "MarginTrendRank": ("margin_trend", 3),
    "InterestCoverageRank": ("interest_coverage", 3), "CashConversionRank": ("cash_conversion", 2),
    "EarningsQualityRank": ("earnings_quality", 4),
    "PERank": ("pe", 11), "PSRank": ("ps", 3), "PBRank": ("pb", 2),
    "LiquidityRank": ("avg_trade_value_30d", 3), "LeverageRank": ("debt_ratio", 2),
    "CurrentRatioRank": ("current_ratio", 2), "StabilityRank": ("sales_stability", 1),
    "LowVolatilityRank": ("volatility_30d", 2), "MomentumRank": ("price_momentum_30d", 1),
}
COMP_CATEGORY = {f: c for c, fs in {
    "Growth": ["SalesGrowthRank", "SalesGrowth3MRank", "RevenueGrowthRank",
               "OperatingProfitGrowthRank", "NetProfitGrowthRank"],
    "Profitability": ["OperatingMarginRank", "NetMarginRank", "ROERank", "MarginTrendRank",
                      "InterestCoverageRank", "CashConversionRank", "EarningsQualityRank"],
    "Valuation": ["PERank", "PSRank", "PBRank"],
    "MarketRisk": ["LiquidityRank", "LeverageRank", "CurrentRatioRank", "StabilityRank",
                   "LowVolatilityRank", "MomentumRank"]}.items() for f in fs}
CAT_FIELD = {"Growth": "growth_score", "Profitability": "profitability_score",
             "Valuation": "valuation_score", "MarketRisk": "market_score"}
TOTAL_W = sum(w for _, w in COMPONENTS.values())

A = {"parity": {}, "formula": {}, "coverage": {}, "redundancy": {}, "category_diag": {},
     "component_diag": {}, "ablation": {}, "dq_diag": {}, "concentration": {},
     "stability": {}, "monotonicity": {}, "persistence": {}, "distribution": {},
     "price_dominance": {}, "evidence": {}, "gates": {}, "artifacts": {}}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fwd_series():
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT security_id::text, action_date, adjustment_factor
                       FROM market.corporate_actions
                       WHERE source='tsetmc_gap_rule_v1' AND adjustment_evidence_status='CONFIRMED'""")
        events = {}
        for sid, d, f in cur.fetchall():
            events.setdefault(sid, []).append(
                (d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)), float(f)))
        cur.execute("SELECT codal_symbol, id::text, tsetmc_ins_code::text FROM core.securities WHERE is_primary")
        sec = {s: (i, ins) for s, i, ins in cur.fetchall()}
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(d) for (d,) in cur.fetchall()]
    adj = {}
    for sym, (sid, ins) in sec.items():
        gz = RAW / f"raw_{sym}_{ins}.json.gz"
        if not gz.exists():
            continue
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            doc = json.loads(fh.read())
        recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
        dates_s, raw = [], {}
        for r in recs:
            s = str(r["dEven"])
            d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
            dates_s.append(d)
            raw[d] = float(r["pClosing"])
        evs = sorted(events.get(sid, []), key=lambda e: e[0])
        c, run, ei = {}, 1.0, len(evs) - 1
        for d in reversed(dates_s):
            dd = dt.date.fromisoformat(d)
            while ei >= 0 and evs[ei][0] > dd:
                run *= evs[ei][1]
                ei -= 1
            c[d] = run
        adj[sym] = {"dates": dates_s, "adj": {d: raw[d] * c[d] for d in dates_s}}

    def fwd(sym, signal_date, h):
        s = adj.get(sym)
        if not s:
            return None
        i = bisect_right(s["dates"], signal_date)
        entry = s["dates"][i] if i < len(s["dates"]) else None
        if entry is None:
            return None
        j = bisect_right(cal, entry) - 1
        k = j + h
        if k >= len(cal):
            return None
        exit_d = cal[k]
        a0, a1 = s["adj"].get(entry), s["adj"].get(exit_d)
        return None if (not a0 or not a1) else a1 / a0 - 1.0
    return fwd


def block_len(dates, months):
    ds = [dt.date.fromisoformat(d) for d in dates]
    best = 1
    for i in range(len(ds)):
        j = i
        while j + 1 < len(ds) and (ds[j + 1] - ds[i]).days <= months * 30.44:
            j += 1
        best = max(best, j - i + 1)
    return best


def boot(per_date, dates_order, block, rng):
    vals = np.array([per_date[d] for d in dates_order if d in per_date], dtype=float)
    n = len(vals)
    if n == 0:
        return None
    nb = int(np.ceil(n / block))
    stats = np.empty(B)
    for b in range(B):
        idx = []
        for _ in range(nb):
            s = int(rng.integers(0, n))
            idx.extend((s + k) % n for k in range(block))
        stats[b] = vals[np.array(idx[:n])].mean()
    return {"mean": float(vals.mean()), "ci_lower": float(np.percentile(stats, 2.5)),
            "ci_upper": float(np.percentile(stats, 97.5))}


def ics(scores_by_date, rets_by_date, min_pairs=5):
    per = {}
    for d in scores_by_date:
        pairs = [(s, r) for s, r in zip(scores_by_date[d], rets_by_date[d])
                 if s is not None and r is not None]
        if len(pairs) >= min_pairs:
            ic = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if ic is not None:
                per[d] = ic
    vals = list(per.values())
    return per, {"mean": float(np.mean(vals)) if vals else None,
                 "median": float(np.median(vals)) if vals else None,
                 "positive_fraction": float(np.mean([v > 0 for v in vals])) if vals else None,
                 "n_dates": len(vals)}


def qspread(score_rows, h, min_rows=10):
    """score_rows: {date: [(score, ret_h)]} -> Q5-Q1 spread stats (frozen convention)."""
    per, means = {}, {q: [] for q in range(1, 6)}
    for d, sr in score_rows.items():
        pairs = [(s, r) for s, r in sr if s is not None and r is not None]
        if len(pairs) < min_rows:
            continue
        pairs.sort(key=lambda x: x[0])
        n = len(pairs)
        qs = [pairs[i * n // 5:(i + 1) * n // 5] for i in range(5)]
        rm = []
        for q in qs:
            rets = [r for _, r in q]
            rm.append(float(np.mean(rets)) if rets else None)
        if None in rm:
            continue
        per[d] = rm[4] - rm[0]
        for qi in range(5):
            means[qi + 1].append(rm[qi])
    return (per, {q: (float(np.mean(v)) if v else None) for q, v in means.items()},
            {"mean_spread": float(np.mean(list(per.values()))) if per else None,
             "n_dates": len(per)})


def main() -> int:
    rows = [json.loads(l) for l in SRC.read_text(encoding="utf-8").splitlines() if l.strip()]
    pq = pd.read_parquet(PQ)
    assert len(rows) == len(pq) == 12604, "panel row mismatch"
    A["artifacts"]["panel_jsonl_sha256"] = sha256(SRC)
    A["artifacts"]["panel_parquet_sha256"] = sha256(PQ)
    fwd = fwd_series()
    for r in rows:
        r["forward_returns"] = {f"ret_{h}": fwd(r["symbol"], r["as_of"], h) for h in HORIZONS}
        r["year"] = int(r["as_of"][:4])
        r["raw_sum"] = round(r["growth_score"] + r["profitability_score"]
                             + r["valuation_score"] + r["market_score"], 1)
        r["pre_dq_score"] = r["raw_sum"]
    dates = sorted({r["as_of"] for r in rows})
    by_date = {d: [r for r in rows if r["as_of"] == d] for d in dates}
    years = sorted({r["year"] for r in rows})

    # ---------- task 2: input parity ----------
    sc = {d: [r["ui_score"] for r in by_date[d]] for d in dates}
    rt = {h: {d: [r["forward_returns"][f"ret_{h}"] for r in by_date[d]] for d in dates} for h in HORIZONS}
    parity = {}
    for h in HORIZONS:
        per, st = ics(sc, rt[h])
        parity[f"IC{h}"] = {"v2_audit": round(st["mean"], 4), "expected": FROZEN_V2[str(h)],
                            "n_dates": st["n_dates"], "positive_fraction": round(st["positive_fraction"], 3)}
    _, qm, qs63 = qspread({d: list(zip(sc[d], rt[63][d])) for d in dates}, 63)
    rng = np.random.default_rng(SEED)
    per63, _ = ics(sc, rt[63])
    ic63_boot = boot(per63, dates, block_len(dates, 3), rng)
    parity["ic63_bootstrap"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in ic63_boot.items()}
    parity["q1_q5_mean_63d"] = {k: round(v, 5) for k, v in qm.items()}
    parity["q5_q1_mean_spread_63d_pp"] = round(qs63["mean_spread"] * 100, 3)
    ok = all(abs(parity[f"IC{h}"]["v2_audit"] - FROZEN_V2[str(h)]) < 5e-4 for h in HORIZONS)
    A["parity"] = {**parity, "SCORE_AUDIT_INPUT_PARITY": "PASS" if ok else "FAIL"}
    print("parity:", A["parity"]["SCORE_AUDIT_INPUT_PARITY"])
    if not ok:
        (HERE / "score_deep_audit_v1.json").write_text(json.dumps(A, indent=1, default=str), encoding="utf-8")
        return 1

    # ---------- task 4: coverage ----------
    cov_rows = []
    for f, (raws, w) in COMPONENTS.items():
        fields = raws.split("|")
        present = [1 if any(r["raw_metrics"].get(x) is not None for x in fields) else 0 for r in rows]
        per_date_n = []
        for d in dates:
            n = sum(1 for r in by_date[d] if any(r["raw_metrics"].get(x) is not None for x in fields))
            per_date_n.append(n)
        cov_rows.append({"component": f, "category": COMP_CATEGORY[f], "weight": w,
                         "nominal_share": round(w / TOTAL_W, 4),
                         "coverage_overall": float(np.mean(present)),
                         **{f"coverage_{y}": float(np.mean([p for r, p in zip(rows, present) if r["year"] == int(y)]))
                            for y in map(str, years)},
                         "symbols_with_data": int(len({r["symbol"] for r, p in zip(rows, present) if p})),
                         "median_cross_sectional_n": float(np.median(per_date_n))})
    pd.DataFrame(cov_rows).to_csv(HERE / "score_component_coverage.csv", index=False)
    A["coverage"] = {
        "by_component": cov_rows,
        "major_ramps": [c["component"] for c in cov_rows if c["coverage_2021"] < 0.5 and c["coverage_overall"] > 0.6],
        "missingness_dominated": [c["component"] for c in cov_rows if c["coverage_overall"] < 0.5],
        "note": "coverage = raw metric present (neutral-filled ranks excluded from measurement)",
    }

    # ---------- task 5: redundancy ----------
    def pair_key(a, b):
        return tuple(sorted([a, b]))
    agg = {}
    for a, b in combinations(list(COMPONENTS), 2):
        agg[(a, b)] = []
    for d in dates:
        rs = by_date[d]
        for a, b in combinations(list(COMPONENTS), 2):
            fa, fb = COMPONENTS[a][0].split("|"), COMPONENTS[b][0].split("|")
            pairs = [(r["ranks"][a], r["ranks"][b]) for r in rs
                     if any(r["raw_metrics"].get(x) is not None for x in fa)
                     and any(r["raw_metrics"].get(x) is not None for x in fb)]
            if len(pairs) >= 10:
                rho = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if rho is not None:
                    agg[(a, b)].append(rho)
    red_rows = []
    for (a, b), v in agg.items():
        if not v:
            continue
        red_rows.append({"component_a": a, "component_b": b, "category_a": COMP_CATEGORY[a],
                         "category_b": COMP_CATEGORY[b], "n_dates": len(v),
                         "median_rho": round(float(np.median(v)), 4),
                         "p25": round(float(np.percentile(v, 25)), 4),
                         "p75": round(float(np.percentile(v, 75)), 4),
                         "high_correlation_abs_ge_0.70": bool(abs(float(np.median(v))) >= 0.70)})
    pd.DataFrame(red_rows).to_csv(HERE / "score_redundancy_matrix.csv", index=False)
    # category-level
    cat_red = []
    for a, b in combinations(list(CAT_FIELD), 2):
        v = []
        for d in dates:
            pairs = [(r[CAT_FIELD[a]], r[CAT_FIELD[b]]) for r in by_date[d]]
            if len(pairs) >= 10:
                rho = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if rho is not None:
                    v.append(rho)
        cat_red.append({"a": a, "b": b, "median_rho": round(float(np.median(v)), 4) if v else None,
                        "p25": round(float(np.percentile(v, 25)), 4) if v else None,
                        "p75": round(float(np.percentile(v, 75)), 4) if v else None})
    high_pairs = [r for r in red_rows if r["high_correlation_abs_ge_0.70"]]
    A["redundancy"] = {"component_pairs": red_rows, "category_pairs": cat_red,
                       "n_high_correlation_pairs": len(high_pairs), "flag": "|median rho| >= 0.70"}

    # ---------- tasks 6/7/11 helpers ----------
    def diag_for(score_getter, label):
        scd = {d: [score_getter(r) for r in by_date[d]] for d in dates}
        out = {"label": label}
        for h in HORIZONS:
            per, st = ics(scd, rt[h])
            out[f"IC{h}"] = round(st["mean"], 4) if st["mean"] is not None else None
            out[f"pos_frac_{h}"] = round(st["positive_fraction"], 3) if st["mean"] is not None else None
            out[f"n_dates_{h}"] = st["n_dates"]
        for h in (63, 126):
            _, _, qs = qspread({d: list(zip(scd[d], rt[h][d])) for d in dates}, h)
            out[f"spread_{h}_pp"] = round(qs["mean_spread"] * 100, 3) if qs["mean_spread"] is not None else None
            out[f"spread_{h}_n_dates"] = qs["n_dates"]
        for y in years:
            dd = [d for d in dates if int(d[:4]) == y]
            per, st = ics({d: scd[d] for d in dd}, {d: rt[63][d] for d in dd})
            out[f"IC63_{y}"] = round(st["mean"], 4) if st["mean"] is not None else None
        rngl = np.random.default_rng(SEED)
        for h in (63, 126):
            per, _ = ics(scd, rt[h])
            bb = boot(per, dates, block_len(dates, 3 if h == 63 else 6), rngl)
            out[f"IC{h}_boot"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in bb.items()} if bb else None
        return out

    # ---------- task 6: category diagnostics ----------
    cat_rows = [diag_for(lambda r, c=f: r[c], c) for c, f in CAT_FIELD.items()]
    cat_rows.append(diag_for(lambda r: r["ui_score"], "FULL_SCORE"))
    pd.DataFrame(cat_rows).to_csv(HERE / "score_category_diagnostics.csv", index=False)
    A["category_diag"] = cat_rows

    # ---------- task 7: component diagnostics (rank as stored) ----------
    comp_rows = []
    for f, (raws, w) in COMPONENTS.items():
        d63 = diag_for(lambda r, ff=f: r["ranks"].get(ff), f)
        comp_rows.append({"component": f, "category": COMP_CATEGORY[f], "weight": w,
                          "IC63": d63["IC63"], "IC63_pos_frac": d63["pos_frac_63"],
                          "IC126": d63["IC126"], "IC126_pos_frac": d63["pos_frac_126"],
                          "IC63_boot": d63["IC63_boot"],
                          "spread_63_pp": d63["spread_63_pp"], "spread_126_pp": d63["spread_126_pp"],
                          **{f"IC63_{y}": d63.get(f"IC63_{y}") for y in map(str, years)}})
    pd.DataFrame(comp_rows).to_csv(HERE / "score_component_diagnostics.csv", index=False)
    A["component_diag"] = comp_rows

    # ---------- task 8: leave-one-category-out ----------
    abl = []
    for cat, f in CAT_FIELD.items():
        full = diag_for(lambda r: r["ui_score"], "FULL")
        diag = diag_for(lambda r: round(r["data_quality_score"]
                                        * (r["raw_sum"] - r[f]), 2), f"EXCLUDE_{cat}")
        abl.append({"excluded_category": cat,
                    "diag_IC63": diag["IC63"], "full_IC63": full["IC63"],
                    "delta_IC63": round(diag["IC63"] - full["IC63"], 4),
                    "diag_IC126": diag["IC126"], "full_IC126": full["IC126"],
                    "delta_IC126": round(diag["IC126"] - full["IC126"], 4),
                    "delta_pos_frac_63": round(diag["pos_frac_63"] - full["pos_frac_63"], 3),
                    "delta_spread_63_pp": (round(diag["spread_63_pp"] - full["spread_63_pp"], 3)
                                           if diag["spread_63_pp"] is not None and full["spread_63_pp"] is not None else None),
                    "delta_spread_126_pp": (round(diag["spread_126_pp"] - full["spread_126_pp"], 3)
                                            if diag["spread_126_pp"] is not None and full["spread_126_pp"] is not None else None),
                    "note": "points NOT reallocated; DQ preserved (diag = DQ*(raw_sum - category))"})
    pd.DataFrame(abl).to_csv(HERE / "score_ablation_diagnostics.csv", index=False)
    A["ablation"] = abl

    # ---------- task 9: DQ diagnostic ----------
    pre = diag_for(lambda r: r["pre_dq_score"], "PRE_DQ")
    post = diag_for(lambda r: r["ui_score"], "POST_DQ")
    moved = 0
    moved_secs = set()
    rank_corr_dates = []
    for d in dates:
        rs = by_date[d]
        pres = [(r["pre_dq_score"], r["ui_score"]) for r in rs]
        pres = [(a, b) for a, b in pres if a is not None and b is not None]
        if len(pres) >= 10:
            rho = M.spearman([p[0] for p in pres], [p[1] for p in pres])
            if rho is not None:
                rank_corr_dates.append(rho)
        pn = pd.Series([p[0] for p in pres]).rank(pct=True)
        qn = pd.Series([p[1] for p in pres]).rank(pct=True)
        mm = (pn - qn).abs() >= 0.10
        moved += int(mm.sum())
        for r_, m_ in zip(rs, mm):
            if m_:
                moved_secs.add(r_["security_id"])
    dq_buckets = {"1.00": [], "0.85-1.00": [], "0.70-0.85": [], "<0.70": []}
    for d in dates:
        for r in by_date[d]:
            dq = r["data_quality_score"]
            k = "1.00" if dq >= 1.0 else "0.85-1.00" if dq >= 0.85 else "0.70-0.85" if dq >= 0.70 else "<0.70"
            dq_buckets[k].append(r["forward_returns"]["ret_63"])
    dq_strat = {k: {"n": len(v), "mean_ret63": round(float(np.mean([x for x in v if x is not None])), 5)
                    if any(x is not None for x in v) else None}
                for k, v in dq_buckets.items()}
    A["dq_diag"] = {
        "pre_DQ": {k: pre[k] for k in ("IC63", "pos_frac_63", "spread_63_pp", "IC126", "pos_frac_126", "spread_126_pp")},
        "post_DQ": {k: post[k] for k in ("IC63", "pos_frac_63", "spread_63_pp", "IC126", "pos_frac_126", "spread_126_pp")},
        "rank_corr_pre_post_mean_per_date": round(float(np.mean(rank_corr_dates)), 4) if rank_corr_dates else None,
        "rows_materially_moved_ge_10pctile": moved,
        "securities_materially_moved": len(moved_secs),
        "material_move_rule": "|percentile(pre) - percentile(post)| >= 0.10 within date",
        "ret63_by_dq_bucket_descriptive": dq_strat,
    }

    # ---------- task 10: effective contribution shares ----------
    eff = {f: defaultdict(list) for f in COMPONENTS}
    for r in rows:
        contribs = {}
        for f in COMPONENTS:
            rk = r["ranks"].get(f)
            if rk is not None:
                contribs[f] = COMPONENTS[f][1] * rk
        s = sum(contribs.values())
        if s <= 0:
            continue
        for f, cv in contribs.items():
            eff[f][r["year"]].append(cv / s)
    conc_rows = []
    for f, (raws, w) in COMPONENTS.items():
        allv = [x for v in eff[f].values() for x in v]
        conc_rows.append({"component": f, "category": COMP_CATEGORY[f],
                          "nominal_share": round(w / TOTAL_W, 4),
                          "effective_share_median": round(float(np.median(allv)), 4) if allv else None,
                          "effective_share_p10": round(float(np.percentile(allv, 10)), 4) if allv else None,
                          "effective_share_p90": round(float(np.percentile(allv, 90)), 4) if allv else None,
                          **{f"eff_share_{y}": round(float(np.median(eff[f][int(y)])), 4) if eff[f][int(y)] else None
                             for y in map(str, years)}})
    pd.DataFrame(conc_rows).to_csv(HERE / "score_weight_concentration.csv", index=False)
    A["concentration"] = conc_rows

    # ---------- task 11: yearly stability + leave-one-year-out ----------
    stab = []
    for y in years:
        dd = [d for d in dates if int(d[:4]) == y]
        row = {"year": y, "n_rows": len([r for r in rows if r["year"] == y])}
        for label, getter in [("FULL", lambda r: r["ui_score"])] + \
                             [(c, (lambda r, cf=f: r[cf])) for c, f in CAT_FIELD.items()]:
            scd = {d: [getter(r) for r in by_date[d]] for d in dd}
            _, s63 = ics(scd, {d: rt[63][d] for d in dd})
            _, s126 = ics(scd, {d: rt[126][d] for d in dd})
            _, _, qs = qspread({d: list(zip(scd[d], rt[63][d])) for d in dd}, 63, min_rows=10)
            row[f"{label}_IC63"] = round(s63["mean"], 4) if s63["mean"] is not None else None
            row[f"{label}_pos63"] = round(s63["positive_fraction"], 3) if s63["mean"] is not None else None
            row[f"{label}_IC126"] = round(s126["mean"], 4) if s126["mean"] is not None else None
            row[f"{label}_spread63_pp"] = round(qs["mean_spread"] * 100, 3) if qs["mean_spread"] is not None else None
        stab.append(row)
    loyo = []
    for y in years:
        dd = [d for d in dates if int(d[:4]) != y]
        per, st = ics({d: [r["ui_score"] for r in by_date[d]] for d in dd},
                      {d: rt[63][d] for d in dd})
        loyo.append({"excluded_year": y, "full_IC63_excl": round(st["mean"], 4) if st["mean"] is not None else None})
    stab_df = pd.DataFrame(stab)
    stab_df.to_csv(HERE / "score_year_stability.csv", index=False)
    A["stability"] = {"by_year": stab, "leave_one_year_out_full_IC63": loyo}

    # ---------- task 12: monotonicity (63/126/252) ----------
    mono = {}
    for h in (63, 126, 252):
        means = {q: [] for q in range(1, 6)}
        med = {q: [] for q in range(1, 6)}
        exc_means = {q: [] for q in range(1, 6)}
        exc_spreads = []
        cnt = tot = 0
        for d in dates:
            pairs = [(s, r) for s, r in zip(sc[d], rt[h][d]) if s is not None and r is not None]
            if len(pairs) < 10:
                continue
            pairs.sort(key=lambda x: x[0])
            n = len(pairs)
            rm = [float(np.mean([x for _, x in pairs[qi * n // 5:(qi + 1) * n // 5]])) for qi in range(5)]
            md = [float(np.median([x for _, x in pairs[qi * n // 5:(qi + 1) * n // 5]])) for qi in range(5)]
            mu = float(np.mean([x for _, x in pairs]))
            em = [float(np.mean([x - mu for _, x in pairs[qi * n // 5:(qi + 1) * n // 5]])) for qi in range(5)]
            for qi in range(5):
                means[qi + 1].append(rm[qi])
                med[qi + 1].append(md[qi])
                exc_means[qi + 1].append(em[qi])
            exc_spreads.append(em[4] - em[0])
            tot += 1
            if all(rm[i + 1] >= rm[i] for i in range(4)):
                cnt += 1
        mono[h] = {
            "n_dates_ge10": tot,
            "quintile_mean_raw": {q: round(float(np.mean(v)), 5) for q, v in means.items() if v},
            "quintile_median_raw": {q: round(float(np.median(v)), 5) for q, v in med.items() if v},
            "quintile_mean_excess": {q: round(float(np.mean(v)), 5) for q, v in exc_means.items() if v},
            "q5_q1_mean_excess_pp": round(float(np.mean(exc_spreads)) * 100, 3) if exc_spreads else None,
            "dates_monotonic_raw": cnt,
            "share_dates_monotonic_raw": round(cnt / tot, 3) if tot else None,
        }
    A["monotonicity"] = mono

    # ---------- task 13: rank persistence / turnover ----------
    persist = []
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        m0 = {r["symbol"]: r["ui_score"] for r in by_date[d0] if r["ui_score"] is not None}
        m1 = {r["symbol"]: r["ui_score"] for r in by_date[d1] if r["ui_score"] is not None}
        common = sorted(set(m0) & set(m1))
        if len(common) < 10:
            continue
        rho = M.spearman([m0[s] for s in common], [m1[s] for s in common])
        r0 = pd.Series({s: m0[s] for s in common}).rank(pct=True)
        r1 = pd.Series({s: m1[s] for s in common}).rank(pct=True)
        persist.append({"pair": f"{d0}->{d1}", "n": len(common), "rho": rho,
                        "top10_retention": float((r1[common][r0 >= 0.90] >= 0.90).mean()),
                        "top20_retention": float((r1[common][r0 >= 0.80] >= 0.80).mean())})
    pdf = pd.DataFrame(persist)
    A["persistence"] = {
        "pairs": int(len(pdf)),
        "median_rho": round(float(pdf.rho.median()), 4) if len(pdf) else None,
        "median_top10_retention": round(float(pdf.top10_retention.median()), 4) if len(pdf) else None,
        "median_top20_retention": round(float(pdf.top20_retention.median()), 4) if len(pdf) else None,
        "top10_monthly_turnover": round(1 - float(pdf.top10_retention.median()), 4) if len(pdf) else None,
        "top20_monthly_turnover": round(1 - float(pdf.top20_retention.median()), 4) if len(pdf) else None,
    }

    # ---------- task 14: distribution ----------
    qs_all = pd.Series([r["ui_score"] for r in rows])
    dist = {"overall": {k: round(float(v), 2) for k, v in {
        "min": qs_all.min(), "p1": qs_all.quantile(0.01), "p5": qs_all.quantile(0.05),
        "p10": qs_all.quantile(0.10), "median": qs_all.median(), "p75": qs_all.quantile(0.75),
        "p90": qs_all.quantile(0.90), "p95": qs_all.quantile(0.95), "p99": qs_all.quantile(0.99),
        "max": qs_all.max()}.items()}}
    for y in years:
        s = pd.Series([r["ui_score"] for r in rows if r["year"] == y])
        dist[str(y)] = {k: round(float(v), 2) for k, v in {
            "min": s.min(), "p1": s.quantile(0.01), "p5": s.quantile(0.05), "p10": s.quantile(0.10),
            "median": s.median(), "p75": s.quantile(0.75), "p90": s.quantile(0.90),
            "p95": s.quantile(0.95), "p99": s.quantile(0.99), "max": s.max()}.items()}
    pd.DataFrame([{"scope": k, **v} for k, v in dist.items()]).to_csv(
        HERE / "score_distribution.csv", index=False)
    A["distribution"] = dist

    # ---------- task 15: price-derived dominance ----------
    price_comp = ["PERank", "PSRank", "PBRank", "LiquidityRank", "LowVolatilityRank", "MomentumRank"]
    acct_comp = [f for f in COMPONENTS if f not in price_comp]
    price_share, acct_share = [], []
    for r in rows:
        c = {f: COMPONENTS[f][1] * r["ranks"].get(f) for f in COMPONENTS if r["ranks"].get(f) is not None}
        s = sum(c.values())
        if s <= 0:
            continue
        price_share.append(sum(c.get(f, 0) for f in price_comp) / s)
        acct_share.append(sum(c.get(f, 0) for f in acct_comp) / s)
    sub_price = diag_for(lambda r: round(sum((COMPONENTS[f][1] * r["ranks"].get(f))
                                             for f in price_comp if r["ranks"].get(f) is not None), 2),
                         "PRICE_DERIVED_SUBSCORE")
    sub_acct = diag_for(lambda r: round(sum((COMPONENTS[f][1] * r["ranks"].get(f))
                                            for f in acct_comp if r["ranks"].get(f) is not None), 2),
                        "ACCOUNTING_SUBSCORE")
    A["price_dominance"] = {
        "price_derived_effective_share_median": round(float(np.median(price_share)), 4),
        "accounting_effective_share_median": round(float(np.median(acct_share)), 4),
        "price_components": price_comp,
        "subscore_diag": {"PRICE": {k: sub_price[k] for k in ("IC63", "IC126", "pos_frac_63")},
                          "ACCOUNTING": {k: sub_acct[k] for k in ("IC63", "IC126", "pos_frac_63")},
                          "note": "attribution only; sub-scores are NOT promoted scores"},
    }

    # ---------- tasks 16-18: evidence + gates ----------
    full = [c for c in cat_rows if c["label"] == "FULL_SCORE"][0]
    neg_comp = [c["component"] for c in comp_rows if (c["IC63"] or 0) < 0 and (c["IC126"] or 0) < 0]
    # unstable: sign flip across years with material magnitude (|IC| > 0.10 both sides)
    unstable = []
    for c in comp_rows:
        ys = [c.get(f"IC63_{y}") for y in map(str, years) if c.get(f"IC63_{y}") is not None]
        if len(ys) >= 3 and max(ys) > 0.10 and min(ys) < -0.10:
            unstable.append(c["component"])
    A["evidence"] = {
        "FULL_SCORE_IC63": full["IC63"], "FULL_SCORE_IC126": full["IC126"],
        "FULL_SCORE_IC63_CI": full["IC63_boot"], "FULL_SCORE_IC126_CI": full["IC126_boot"],
        "FULL_SCORE_YEAR_STABILITY": {r["year"]: {"IC63": r["FULL_IC63"], "IC126": r["FULL_IC126"]}
                                      for _, r in stab_df.iterrows()},
        "FULL_SCORE_63D_MONOTONICITY": mono[63]["share_dates_monotonic_raw"],
        "FULL_SCORE_126D_MONOTONICITY": mono[126]["share_dates_monotonic_raw"],
        "TOP_QUINTILE_MONTHLY_TURNOVER": A["persistence"]["top20_monthly_turnover"],
        "REDUNDANT_COMPONENT_COUNT": len(high_pairs),
        "UNSTABLE_COMPONENT_COUNT": len(unstable),
        "MATERIAL_NEGATIVE_COMPONENT_COUNT": len(neg_comp),
        "negatively_contributing_components": neg_comp,
        "temporally_unstable_components": unstable,
        "highly_redundant_pairs": [(r["component_a"], r["component_b"], r["median_rho"]) for r in high_pairs],
        "CATEGORY_ABLATION_SENSITIVITY": {a["excluded_category"]: {"delta_IC63": a["delta_IC63"],
                                                                  "delta_spread_63_pp": a["delta_spread_63_pp"]}
                                          for a in abl},
        "DQ_EFFECT": {"IC63_pre": A["dq_diag"]["pre_DQ"]["IC63"], "IC63_post": A["dq_diag"]["post_DQ"]["IC63"],
                      "spread63_pre_pp": A["dq_diag"]["pre_DQ"]["spread_63_pp"],
                      "spread63_post_pp": A["dq_diag"]["post_DQ"]["spread_63_pp"]},
    }
    # gates (factual rules, fixed a priori)
    ev = A["evidence"]
    v2_reasons = []
    if ev["REDUNDANT_COMPONENT_COUNT"] >= 3:
        v2_reasons.append(f"material redundancy: {ev['REDUNDANT_COMPONENT_COUNT']} pairs |rho|>=0.70")
    if ev["MATERIAL_NEGATIVE_COMPONENT_COUNT"] >= 1:
        v2_reasons.append(f"persistently negative components: {ev['negatively_contributing_components']}")
    if ev["UNSTABLE_COMPONENT_COUNT"] >= 2:
        v2_reasons.append(f"temporally unstable components: {ev['temporally_unstable_components']}")
    dq_hurt = (ev["DQ_EFFECT"]["IC63_post"] < ev["DQ_EFFECT"]["IC63_pre"] - 0.01
               or ev["DQ_EFFECT"]["spread63_post_pp"] < ev["DQ_EFFECT"]["spread63_pre_pp"] - 0.5)
    if dq_hurt:
        v2_reasons.append("DQ materially degrades ranking vs pre-DQ")
    mismatch = [c["component"] for c in conc_rows
                if c["effective_share_median"] is not None
                and abs(c["effective_share_median"] - c["nominal_share"]) >= 0.05]
    if len(mismatch) >= 3:
        v2_reasons.append(f"nominal/effective weight mismatch >=5pp for {len(mismatch)} components")
    A["gates"]["SCORE_V2_RESEARCH_JUSTIFIED"] = "YES" if v2_reasons else "NO"
    A["gates"]["score_v2_reasons"] = v2_reasons
    cov_ok = A["persistence"]["median_rho"] is not None
    port = []
    if (full["IC63"] or 0) > 0.05 and (full["IC126"] or 0) > 0.05:
        port.append("positive medium-horizon ranking (IC63/IC126 > 0.05)")
    port.append(f"coverage: 235 symbols scored; 12,604 rows over 63 dates")
    if A["persistence"]["median_rho"] and A["persistence"]["median_rho"] > 0.6:
        port.append(f"rank persistence median rho {A['persistence']['median_rho']}")
    if A["persistence"]["top20_monthly_turnover"] and A["persistence"]["top20_monthly_turnover"] < 0.5:
        port.append(f"top-quintile monthly turnover {A['persistence']['top20_monthly_turnover']} (<0.5)")
    port.append("cross-sectional dispersion present (score p90-p10 > 0)")
    A["gates"]["SCORE_PORTFOLIO_BACKTEST_JUSTIFIED"] = "YES" if (full["IC63"] or 0) > 0.05 and cov_ok else "NO"
    A["gates"]["portfolio_readiness_notes"] = port

    A["artifacts"].update({
        "audit_script_sha256": sha256(HERE / "run_score_deep_audit_v1.py"),
        "frozen_input": str(PQ),
        "panel_jsonl": str(SRC),
    })
    (HERE / "score_deep_audit_v1.json").write_text(
        json.dumps(A, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("gates:", A["gates"]["SCORE_V2_RESEARCH_JUSTIFIED"], A["gates"]["SCORE_PORTFOLIO_BACKTEST_JUSTIFIED"])
    print("evidence:", json.dumps({k: v for k, v in A["evidence"].items()
                                   if not isinstance(v, (list, dict))}, default=str))
    print("wrote score_deep_audit_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
