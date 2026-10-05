"""SCORE EXPANSION RESEARCH V1 — single-pass runner (RESEARCH ONLY).

Executes the FROZEN preregistration (PREREGISTRATION_SCORE_EXPANSION_V1.md,
SHA 39c43e21de02596760c77789ef2f77fc84e282ad0d7ef8e38036e749c4e017c5;
spec_frozen.json SHA 0ec9a4f470bd8f3cb69a9116405265e0561fc8f4c56f8f6d89a50fa64bde1b58)
exactly once, on the certified PIT research panel. HISTORICAL EVIDENCE SYNTHESIS —
every forward-return statistic here is descriptive historical evidence, NOT fresh
validation. Nothing is promoted; no production/shadow artifact is touched.

Usage:  python run_score_expansion.py [--skip-portfolios]
Outputs: part2..part11 CSV/JSON artifacts in score_expansion_research/.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "score_expansion_research"
sys.path.insert(0, str(ROOT / "score_v2_research"))
sys.path.insert(0, str(ROOT / "score_v3_minimal_research"))
sys.path.insert(0, str(ROOT / "model_v2_validation"))
import v2lib as V  # noqa: E402  (frozen SHAs, midrank_pct, ics, boot, qspread, fwd)
import model_v2 as M  # noqa: E402  (frozen spearman)

HORIZONS = (21, 63, 126, 252)
SEED, B = V.SEED, V.B
IC_BLOCK = 3            # frozen: 3 signal dates (monthly)
PANEL = ROOT / "score_v2_research" / "pit_feature_panel.parquet"
PIT_STATUS = ROOT / "score_v2_research" / "_pit_contract_result.json"

SPECS = {
    "FUNDAMENTAL_MOMENTUM_SCORE": {
        "min_feats": 5, "feats": [
            ("sg12", "sales_growth_12m", +1, (-150, 150), None),
            ("sg3", "sales_growth_3m", +1, (-150, 150), None),
            ("rev", "revenue_growth", +1, (-200, 200), None),
            ("opg", "operating_profit_growth", +1, (-250, 250), None),
            ("npg", "net_profit_growth|eps_growth", +1, (-300, 300), None),
            ("mt", "margin_trend", +1, (-25, 25), None),
            ("sg_accel", "f_sales_growth_accel", +1, (-150, 150), None),
            ("pg_accel", "f_profit_growth_accel", +1, (-300, 300), None),
            ("pg_cons", "f_profit_growth_consistency", +1, (-100, 100), None)]},
    "EARNINGS_QUALITY_RESILIENCE_SCORE": {
        "min_feats": 5, "feats": [
            ("cash_conv", "cash_conversion", +1, (-2, 5), None),
            ("earnq", "earnings_quality", -1, (0, 150), "min(abs,150)"),
            ("icov", "interest_coverage", +1, (0, 20), "x<=0 -> -999999"),
            ("stab", "sales_stability", +1, None, None),
            ("lev", "debt_ratio", -1, (0, 50), "min(x,50)"),
            ("cr", "current_ratio", +1, (0, 15), None),
            ("nm_stab", "f_earnings_margin_stability", +1, (-40, 40), None),
            ("om_delta", "f_operating_margin_delta", +1, (-25, 25), None)]},
    "LIQUIDITY_CAPACITY_SCORE": {
        "min_feats": 2, "feats": [
            ("td60", "t_traded_days_ratio_60", +1, None, None),
            ("tv30", "t_trade_value_30d", +1, None, None),
            ("tval_cv60", "__tval_cv60__", -1, None, None)]},
    "TECHNICAL_CONFIRMATION_SCORE": {
        "min_feats": 6, "feats": [
            ("mom20", "t_mom_20", +1, (-100, 100), None),
            ("mom60", "t_mom_60", +1, (-100, 100), None),
            ("mom120", "t_mom_120", +1, (-100, 100), None),
            ("ma60_slope", "t_ma60_slope", +1, (-50, 50), None),
            ("pvs_ma60", "t_price_vs_ma60", +1, (-80, 80), None),
            ("dist_high60", "t_dist_high_60", +1, (-1, 0), None),
            ("vam60", "__vam60__", +1, (-30, 30), None),
            ("vol60", "t_vol_60", -1, None, None)]},
}
SIZES_TOMAN = {"100M": 1e8, "500M": 5e8, "1B": 1e9, "5B": 5e9, "10B": 1e10}
COSTS = {"GROSS": 0.0, "LOW": 0.0025, "BASE": 0.005, "HIGH": 0.01}
W = lambda txt: json.dumps(txt, ensure_ascii=False)


def cap(x, lo, hi):
    return None if x is None or not np.isfinite(x) else float(min(max(x, lo), hi))


def era(d: str) -> str:
    y = int(d[:4])
    return "E1_2021_22" if y <= 2022 else ("E2_2023_24" if y <= 2024 else "E3_2025_26")


def boot_ic(per_date: dict, dates_order: list) -> dict | None:
    return V.boot(per_date, dates_order, IC_BLOCK, np.random.default_rng(SEED))


def agg_ic(per: dict) -> dict:
    vals = list(per.values())
    return {"mean": float(np.mean(vals)) if vals else None,
            "median": float(np.median(vals)) if vals else None,
            "positive_fraction": float(np.mean([v > 0 for v in vals])) if vals else None,
            "n_dates": len(vals)}


def main() -> int:
    # ---------------- stage 0: frozen input verification ----------------
    shas = V.verify_frozen_shas()
    man = json.loads((ROOT / "score_v3_minimal_research" / "_input_shas.json").read_text(encoding="utf-8"))
    got_panel = V.sha256(PANEL)
    assert got_panel == man["pit_feature_panel_sha"], f"derived panel SHA mismatch: {got_panel}"
    pit = json.loads(PIT_STATUS.read_text(encoding="utf-8"))
    pit_status = pit.get("SCORE_V2_PIT_FEATURE_CONTRACT", "UNKNOWN")
    assert pit_status == "PASS", f"PIT contract not PASS: {pit_status}"
    print("SHAs verified | PIT contract:", pit_status)

    panel = pd.read_parquet(PANEL)
    dates = sorted(panel["as_of"].unique())
    assert len(panel) == 12604 and len(dates) == 63, (panel.shape, len(dates))
    assert panel["as_of"].min() == "2021-01-31" and panel["as_of"].max() == "2026-06-30"
    for h in HORIZONS:
        assert f"ret_{h}" in panel.columns
    idx = {d: g.index.to_numpy() for d, g in panel.groupby("as_of", sort=True)}
    panel["era"] = panel["as_of"].map(era)

    # ---------------- new features (sessions<=T only; certified path) -------
    print("computing tval_cv60 from raw files (certified MarketData path)...")
    ref = V.load_reference_data()
    md = V.MarketData(ref, symbols=sorted(panel["symbol"].unique()))
    cv60 = np.full(len(panel), np.nan)
    col = panel.columns.get_loc  # noqa
    syms = panel["symbol"].to_numpy(); asofs = panel["as_of"].to_numpy()
    n_no_hist = 0
    for i in range(len(panel)):
        s = md.data.get(syms[i])
        if s is None:
            continue
        k = V.MarketData.idx_at(md, syms[i], asofs[i])
        if k + 1 < V.MIN_SESSIONS:      # identical 200-session gate as certified td60
            n_no_hist += 1
            continue
        w = s["tval"][k - 59: k + 1].astype(float)
        m = float(np.nanmean(w)) if np.isfinite(w).any() else 0.0
        sd = float(np.nanstd(w, ddof=1)) if np.isfinite(w).sum() > 1 else np.nan
        cv60[i] = sd / m if (m and np.isfinite(sd)) else np.nan
    panel["tval_cv60"] = cv60
    panel["vam60"] = panel["t_mom_60"] / (panel["t_vol_60"].replace(0.0, np.nan) + 1e-12)
    print(f"tval_cv60 defined on {int(np.isfinite(cv60).sum())} rows "
          f"({n_no_hist} rows below the 200-session gate)")

    # ---------------- candidate features -> per-date percentiles ------------
    feat_pct: dict[str, pd.Series] = {}
    feat_defined: dict[str, np.ndarray] = {}
    for sc, spec in SPECS.items():
        for fid, colspec, dirn, caps, pre in spec["feats"]:
            if colspec == "__tval_cv60__":
                raw = panel["tval_cv60"].to_numpy(float)
            elif colspec == "__vam60__":
                raw = panel["vam60"].to_numpy(float)
            elif "|" in colspec:
                a, b = colspec.split("|")
                sa, sb = panel[a].to_numpy(float), panel[b].to_numpy(float)
                raw = np.where(np.isfinite(sa), sa, sb)
            else:
                raw = panel[colspec].to_numpy(float)
            if pre == "x<=0 -> -999999":
                raw = np.where(np.isfinite(raw) & (raw <= 0), -999999.0, raw)
                if caps:
                    raw = np.where(np.isfinite(raw) & (raw > -999998.0),
                                   np.clip(raw, caps[0], caps[1]), raw)
            elif pre == "min(abs,150)":
                raw = np.where(np.isfinite(raw), np.minimum(np.abs(raw), 150.0), raw)
            elif pre == "min(x,50)":
                raw = np.where(np.isfinite(raw), np.minimum(raw, 50.0), raw)
            elif caps:
                lo, hi = caps
                raw = np.where(np.isfinite(raw), np.clip(raw, lo, hi), raw)
            pct = np.full(len(panel), np.nan)
            for d in dates:
                ii = idx[d]
                pct[ii] = V.midrank_pct(raw[ii], dirn > 0)
            key = f"{sc}::{fid}"
            feat_pct[key] = pd.Series(pct, index=panel.index)
            feat_defined[key] = np.isfinite(pct)

    # ---------------- candidate scores --------------------------------------
    scores = pd.DataFrame(index=panel.index)
    n_avail, n_total = {}, {}
    for sc, spec in SPECS.items():
        keys = [f"{sc}::{fid}" for fid, *_ in spec["feats"]]
        P = np.column_stack([feat_pct[k].to_numpy() for k in keys])
        ok = np.isfinite(P)
        cnt = ok.sum(axis=1)
        smean = np.where(cnt > 0, np.where(ok, P, 0.0).sum(axis=1) / np.maximum(cnt, 1), np.nan)
        smean[cnt < spec["min_feats"]] = np.nan
        scores[sc] = 100.0 * smean
        n_avail[sc], n_total[sc] = cnt, len(spec["feats"])
    print("scores built:",
          {sc: int(scores[sc].notna().sum()) for sc in scores.columns})

    ui = panel["ui_score"].to_numpy(float)
    panel["v1_pct"] = 0.0
    for d in dates:
        ii = idx[d]
        panel.loc[ii, "v1_pct"] = V.midrank_pct(ui[ii], True)
    v1p = panel["v1_pct"].to_numpy(float)

    # sanity anchor: V1 standalone ICs vs frozen reference (warn-only on drift)
    anchor = {}
    for h in HORIZONS:
        rv = panel[f"ret_{h}"].to_numpy(float)
        per = {}
        for d in dates:
            ii = idx[d]
            pairs = [(ui[j], rv[j]) for j in ii
                     if np.isfinite(ui[j]) and np.isfinite(rv[j])]
            if len(pairs) >= 5:
                ic = M.spearman([q[0] for q in pairs], [q[1] for q in pairs])
                if ic is not None and np.isfinite(ic):
                    per[d] = ic
        anchor[h] = agg_ic(per)["mean"]
    drift = {h: abs(anchor[h] - V.FROZEN_V1_IC[h]) for h in HORIZONS}
    assert all(v < 0.005 for v in drift.values()), f"V1 anchor drift: {drift}"

    # ---------------- PART 2: coverage audit --------------------------------
    PIT_RULE = {
        "sales_growth_12m": "proven visible_from <= knowledge_cutoff (codal published_at / latest recovered publication)",
        "sales_growth_3m": "proven visible_from <= knowledge_cutoff",
        "revenue_growth": "proven visible_from <= knowledge_cutoff",
        "operating_profit_growth": "proven visible_from <= knowledge_cutoff",
        "net_profit_growth|eps_growth": "proven visible_from <= knowledge_cutoff",
        "margin_trend": "proven visible_from <= knowledge_cutoff",
        "f_sales_growth_accel": "chain of PIT rows; anchor row in [T-100,T-70]d; both rows PIT",
        "f_profit_growth_accel": "chain of PIT rows; anchor rule as above",
        "f_profit_growth_consistency": "chain of 4 PIT rows (T..T-3q); all required",
        "cash_conversion": "proven visible_from <= knowledge_cutoff (OCF where materialized)",
        "earnings_quality": "proven visible_from <= knowledge_cutoff",
        "interest_coverage": "proven visible_from <= knowledge_cutoff",
        "sales_stability": "proven visible_from <= knowledge_cutoff",
        "debt_ratio": "balance sheet visible_from <= knowledge_cutoff",
        "current_ratio": "balance sheet visible_from <= knowledge_cutoff",
        "f_earnings_margin_stability": "chain of 4 PIT rows; all required",
        "f_operating_margin_delta": "chain of PIT rows; anchor rule",
        "t_traded_days_ratio_60": "market sessions <= T (file records), 200-session gate",
        "t_trade_value_30d": "market sessions <= T (raw qTotCap), 200-session gate",
        "tval_cv60": "NEW: raw qTotCap 60 file-records <= T; 200-session gate; no adjustment applicable",
        "t_mom_20": "adjusted closes, sessions <= T, chain-invariant",
        "t_mom_60": "adjusted closes, sessions <= T, chain-invariant",
        "t_mom_120": "adjusted closes, sessions <= T, chain-invariant",
        "t_ma60_slope": "adjusted closes, sessions <= T, chain-invariant",
        "t_price_vs_ma60": "adjusted closes, sessions <= T, chain-invariant",
        "t_dist_high_60": "adjusted closes, sessions <= T, chain-invariant",
        "vam60": "NEW: t_mom_60 / t_vol_60 (both chain-invariant windows <= T)",
        "t_vol_60": "session returns <= T, chain-invariant",
    }
    rows2 = []
    for sc, spec in SPECS.items():
        keys = [f"{sc}::{fid}" for fid, *_ in spec["feats"]]
        for (fid, colspec, *_), k in zip(spec["feats"], keys):
            dmask = feat_defined[k]
            by_date = {d: float(dmask[idx[d]].mean()) for d in dates}
            rows2.append({
                "score": sc, "feature": fid, "source_col": colspec,
                "pit_rule": PIT_RULE.get(colspec, PIT_RULE.get(fid, "see spec")),
                "direction": dict((f[0], f[2]) for f in spec["feats"])[fid],
                "coverage_median": float(np.median(list(by_date.values()))),
                "coverage_min": float(np.min(list(by_date.values()))),
                "coverage_current_2026_06_30": by_date[dates[-1]],
                "rows_defined": int(dmask.sum()), "rows_total": len(panel),
                "leak_check": "PASS (certified PIT panel or sessions<=T chain-invariant/raw)",
            })
    cov = pd.DataFrame(rows2)
    cov.to_csv(HERE / "part2_coverage_summary.csv", index=False, encoding="utf-8-sig")
    mat_rows = []
    for d in dates:
        row = {"as_of": d}
        for sc, spec in SPECS.items():
            for fid, *_ in spec["feats"]:
                row[f"{sc}::{fid}"] = float(feat_defined[f"{sc}::{fid}"][idx[d]].mean())
        mat_rows.append(row)
    pd.DataFrame(mat_rows).set_index("as_of").to_csv(
        HERE / "part2_coverage_feature_by_date.csv", encoding="utf-8-sig")

    # missingness informativeness (diagnostic): missing-indicator vs ret_63
    rows2b = []
    r63 = panel["ret_63"].to_numpy(float)
    for sc, spec in SPECS.items():
        for fid, *_ in spec["feats"]:
            k = f"{sc}::{fid}"
            miss = (~feat_defined[k]).astype(float)
            per = {}
            for d in dates:
                ii = idx[d]
                p = [(miss[j], r63[j]) for j in ii if np.isfinite(r63[j])]
                if len(p) >= 5 and len({x[0] for x in p}) > 1:
                    ic = M.spearman([x[0] for x in p], [x[1] for x in p])
                    if ic is not None and np.isfinite(ic):
                        per[d] = ic
            rows2b.append({"score": sc, "feature": fid,
                           "missing_rate": float(miss.mean()),
                           "missing_ic63_median": float(np.median(list(per.values()))) if per else None,
                           "missing_ic63_positive_fraction": float(np.mean([v > 0 for v in per.values()])) if per else None,
                           "n_dates_with_signal": len(per)})
    pd.DataFrame(rows2b).to_csv(HERE / "part2_missingness_informativeness.csv",
                                index=False, encoding="utf-8-sig")

    # ---------------- PART 3: distributions + persistence -------------------
    rows3 = []
    for sc in scores.columns:
        sv = scores[sc].to_numpy(float)
        for d in dates:
            x = sv[idx[d]]
            x = x[np.isfinite(x)]
            if len(x) == 0:
                continue
            rows3.append({"score": sc, "as_of": d, "n_defined": len(x),
                          "mean": float(np.mean(x)),
                          **{f"p{q}": float(np.percentile(x, q)) for q in (10, 25, 50, 75, 90)}})
    pd.DataFrame(rows3).to_csv(HERE / "part3_distributions.csv", index=False, encoding="utf-8-sig")

    def persist(sv: np.ndarray) -> dict:
        per = {}
        for a, b in zip(dates[:-1], dates[1:]):
            ia, ib = idx[a], idx[b]
            ib_map = {panel["symbol"].iloc[j]: j for j in ib}
            common = [j for j in ia
                      if np.isfinite(sv[j]) and panel["symbol"].iloc[j] in ib_map
                      and np.isfinite(sv[ib_map[panel["symbol"].iloc[j]]])]
            if len(common) >= 5:
                pairs = [(sv[j], sv[ib_map[panel["symbol"].iloc[j]]]) for j in common]
                ic = M.spearman([p[0] for p in pairs], [p[1] for p in pairs])
                if ic is not None and np.isfinite(ic):
                    per[a] = ic
        return per

    rows3b = []
    for sc in list(scores.columns) + ["V1_ui_score"]:
        sv = ui if sc == "V1_ui_score" else scores[sc].to_numpy(float)
        per = persist(sv)
        vals = list(per.values())
        rows3b.append({"score": sc, "persistence_mean": float(np.mean(vals)) if vals else None,
                       "persistence_median": float(np.median(vals)) if vals else None,
                       "n_pairs": len(vals)})
    pd.DataFrame(rows3b).to_csv(HERE / "part3_persistence.csv", index=False, encoding="utf-8-sig")

    # ---------------- PART 4: redundancy ------------------------------------
    comp_cols = ["growth_score", "profitability_score", "valuation_score", "market_score"]
    comps = {c: panel[c].to_numpy(float) for c in comp_cols}

    def sp_per_date(x: np.ndarray, y: np.ndarray, min_pairs=5) -> dict:
        per = {}
        for d in dates:
            ii = idx[d]
            p = [(x[j], y[j]) for j in ii if np.isfinite(x[j]) and np.isfinite(y[j])]
            if len(p) >= min_pairs:
                ic = M.spearman([p[0] for p in p], [p[1] for p in p])
                if ic is not None and np.isfinite(ic):
                    per[d] = ic
        return per

    def overlap_per_date(x: np.ndarray, y: np.ndarray, frac: float) -> list[float]:
        out = []
        for d in dates:
            ii = idx[d]
            pairs = [(x[j], y[j], j) for j in ii if np.isfinite(x[j]) and np.isfinite(y[j])]
            n = len(pairs)
            if n < 10:
                continue
            k = max(1, round(frac * n))
            top_x = {p[2] for p in sorted(pairs, key=lambda q: -q[0])[:k]}
            top_y = {p[2] for p in sorted(pairs, key=lambda q: -q[1])[:k]}
            out.append(len(top_x & top_y) / k)
        return out

    rows4 = []
    for sc in scores.columns:
        sv = scores[sc].to_numpy(float)
        for target_name, tv in [("V1_ui_score", ui)] + [(c, comps[c]) for c in comp_cols]:
            per = sp_per_date(sv, tv)
            vals = sorted(per.values())
            ov10 = overlap_per_date(sv, tv, 0.10)
            ov20 = overlap_per_date(sv, tv, 0.20)
            rows4.append({
                "score": sc, "target": target_name,
                "spearman_median": float(np.median(vals)) if vals else None,
                "spearman_p10": float(np.percentile(vals, 10)) if vals else None,
                "spearman_p25": float(np.percentile(vals, 25)) if vals else None,
                "spearman_p75": float(np.percentile(vals, 75)) if vals else None,
                "spearman_p90": float(np.percentile(vals, 90)) if vals else None,
                "spearman_last_date": per.get(dates[-1]),
                "n_dates": len(vals),
                "top10pct_overlap_mean": float(np.mean(ov10)) if ov10 else None,
                "top20pct_overlap_mean": float(np.mean(ov20)) if ov20 else None,
            })
    red = pd.DataFrame(rows4)
    red.to_csv(HERE / "part4_redundancy.csv", index=False, encoding="utf-8-sig")

    rows4b = []
    names = list(scores.columns)
    for a_i in range(len(names)):
        for b_i in range(a_i + 1, len(names)):
            per = sp_per_date(scores[names[a_i]].to_numpy(float), scores[names[b_i]].to_numpy(float))
            vals = list(per.values())
            rows4b.append({"pair": f"{names[a_i]} ~ {names[b_i]}",
                           "spearman_median": float(np.median(vals)) if vals else None,
                           "spearman_mean": float(np.mean(vals)) if vals else None,
                           "n_dates": len(vals)})
    pd.DataFrame(rows4b).to_csv(HERE / "part4_score_score.csv", index=False, encoding="utf-8-sig")

    # ---------------- PART 5: standalone ICs --------------------------------
    rows5, qrows5, ics_all = [], [], {}
    for sc in scores.columns:
        sv = scores[sc].to_numpy(float)
        for h in HORIZONS:
            rv = panel[f"ret_{h}"].to_numpy(float)
            per = {}
            for d in dates:
                ii = idx[d]
                p = [(sv[j], rv[j]) for j in ii if np.isfinite(sv[j]) and np.isfinite(rv[j])]
                if len(p) >= 5:
                    ic = M.spearman([p[0] for p in p], [p[1] for p in p])
                    if ic is not None and np.isfinite(ic):
                        per[d] = ic
            ics_all[(sc, h)] = per
            a = agg_ic(per)
            bt = boot_ic(per, dates)
            per_year = {}
            for d, v in per.items():
                per_year.setdefault(d[:4], []).append(v)
            per_era = {}
            for d, v in per.items():
                per_era.setdefault(era(d), []).append(v)
            rows5.append({
                "score": sc, "h": h, **a,
                "ci_lower": bt["ci_lower"] if bt else None,
                "ci_upper": bt["ci_upper"] if bt else None,
                "ic_by_year": W({y: round(float(np.median(v)), 4) for y, v in sorted(per_year.items())}),
                "ic_by_era_median": W({e: round(float(np.median(v)), 4) for e, v in sorted(per_era.items())}),
            })
        for h in (63, 126):
            rv = panel[f"ret_{h}"].to_numpy(float)
            sr = {d: [(sv[j], rv[j]) for j in idx[d]] for d in dates}
            _, qmeans, qsum = V.qspread(sr)
            mono = int(np.sum(np.diff([qmeans[q] for q in range(1, 6)]) > 0)) \
                if all(qmeans[q] is not None for q in range(1, 6)) else None
            qrows5.append({"score": sc, "h": h, **qsum,
                           "q1": qmeans[1], "q2": qmeans[2], "q3": qmeans[3],
                           "q4": qmeans[4], "q5": qmeans[5], "monotonic_steps": mono})
    ics5 = pd.DataFrame(rows5)
    ics5.to_csv(HERE / "part5_ic_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(qrows5).to_csv(HERE / "part5_qspread.csv", index=False, encoding="utf-8-sig")
    long5 = [{"score": s, "h": h, "as_of": d, "ic": v} for (s, h), per in ics_all.items()
             for d, v in per.items()]
    pd.DataFrame(long5).to_csv(HERE / "part5_ics_per_date.csv", index=False, encoding="utf-8-sig")

    # ---------------- PART 6: incremental vs V1 ------------------------------
    inc_rows, wq_rows, t20_rows = [], [], []
    inc_per_all = {}
    for sc in scores.columns:
        sv = scores[sc].to_numpy(float)
        sp = scores[sc].to_numpy(float)  # 0-100
        spct = np.full(len(panel), np.nan)
        for d in dates:
            ii = idx[d]
            spct[ii] = V.midrank_pct(sp[ii], True)
        for h in HORIZONS:
            rv = panel[f"ret_{h}"].to_numpy(float)
            per = {}
            for d in dates:
                ii = idx[d]
                xs, ys, rs = [], [], []
                for j in ii:
                    if np.isfinite(spct[j]) and np.isfinite(v1p[j]) and np.isfinite(rv[j]):
                        xs.append(v1p[j]); ys.append(spct[j]); rs.append(rv[j])
                if len(xs) < 5:
                    continue
                x = np.array(xs); y = np.array(ys); r = np.array(rs)
                b = np.cov(y, x, ddof=1)[0, 1] / (np.var(x, ddof=1) or 1.0)
                a_ = y.mean() - b * x.mean()
                res = y - (a_ + b * x)
                ic = M.spearman(res.tolist(), r.tolist())
                if ic is not None and np.isfinite(ic):
                    per[d] = ic
            inc_per_all[(sc, h)] = per
            a = agg_ic(per)
            bt = boot_ic(per, dates)
            inc_rows.append({"score": sc, "h": h, **a,
                             "ci_lower": bt["ci_lower"] if bt else None,
                             "ci_upper": bt["ci_upper"] if bt else None})
        # within-V1-quintile (ret_63)
        rv = panel["ret_63"].to_numpy(float)
        per_q = {q: [] for q in range(1, 6)}
        for d in dates:
            ii = idx[d]
            rows_d = [(v1p[j], sv[j], rv[j]) for j in ii
                      if np.isfinite(v1p[j]) and np.isfinite(sv[j]) and np.isfinite(rv[j])]
            if len(rows_d) < 25:
                continue
            rows_d.sort(key=lambda t: t[0])
            n = len(rows_d)
            for q in range(1, 6):
                bucket = rows_d[(q - 1) * n // 5: q * n // 5]
                if len(bucket) >= 4 and len({x[1] for x in bucket}) > 1:
                    ic = M.spearman([x[1] for x in bucket], [x[2] for x in bucket])
                    if ic is not None and np.isfinite(ic):
                        per_q[q].append(ic)
        for q in range(1, 6):
            v = per_q[q]
            wq_rows.append({"score": sc, "quintile": q,
                            "median_ic63_within": float(np.median(v)) if v else None,
                            "mean_ic63_within": float(np.mean(v)) if v else None,
                            "n_dates": len(v)})
        # V1 Top-20% conditional
        for h in (63, 126):
            rvh = panel[f"ret_{h}"].to_numpy(float)
            diffs, ic20 = [], []
            for d in dates:
                ii = idx[d]
                rows_d = [(v1p[j], sv[j], rvh[j]) for j in ii
                          if np.isfinite(v1p[j]) and np.isfinite(sv[j]) and np.isfinite(rvh[j])]
                if len(rows_d) < 10:
                    continue
                rows_d.sort(key=lambda t: -t[0])
                n20 = max(2, round(0.20 * len(rows_d)))
                top = rows_d[:n20]
                med = float(np.median([x[1] for x in top]))
                hi = [x[2] for x in top if x[1] >= med]
                lo = [x[2] for x in top if x[1] < med]
                if len(hi) >= 2 and len(lo) >= 2:
                    diffs.append(float(np.mean(hi) - np.mean(lo)))
                if len(top) >= 5 and len({x[1] for x in top}) > 1:
                    ic = M.spearman([x[1] for x in top], [x[2] for x in top])
                    if ic is not None and np.isfinite(ic):
                        ic20.append(ic)
            bt = V.boot({i: v for i, v in enumerate(diffs)}, list(range(len(diffs))),
                        IC_BLOCK, np.random.default_rng(SEED)) if len(diffs) >= 8 else None
            t20_rows.append({"score": sc, "h": h,
                             "high_minus_low_mean": float(np.mean(diffs)) if diffs else None,
                             "high_minus_low_median": float(np.median(diffs)) if diffs else None,
                             "hl_ci_lower": bt["ci_lower"] if bt else None,
                             "hl_ci_upper": bt["ci_upper"] if bt else None,
                             "n_dates": len(diffs),
                             "within_top20_ic_median": float(np.median(ic20)) if ic20 else None,
                             "within_top20_ic_mean": float(np.mean(ic20)) if ic20 else None,
                             "n_dates_ic": len(ic20)})
    inc = pd.DataFrame(inc_rows)
    inc.to_csv(HERE / "part6_incremental_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{"score": s, "h": h, "as_of": d, "ic": v}
                  for (s, h), per in inc_per_all.items() for d, v in per.items()]
                 ).to_csv(HERE / "part6_incremental_ics_per_date.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(wq_rows).to_csv(HERE / "part6_within_quintile.csv", index=False, encoding="utf-8-sig")
    t20 = pd.DataFrame(t20_rows)
    t20.to_csv(HERE / "part6_top20_conditional.csv", index=False, encoding="utf-8-sig")

    # classification (frozen rules)
    def classify(sc: str) -> dict:
        cov_ok = True
        defined_share = float(scores[sc].notna().mean())
        if defined_share < 0.5:
            return {"INCREMENTAL_INFORMATION": "INCONCLUSIVE",
                    "defined_share_of_panel": defined_share}
        out = {"defined_share_of_panel": defined_share}
        i63 = inc[(inc.score == sc) & (inc.h == 63)].iloc[0]
        i126 = inc[(inc.score == sc) & (inc.h == 126)].iloc[0]
        wq = pd.DataFrame(wq_rows)
        w5 = wq[wq.score == sc]
        n_pos_q = int((w5["median_ic63_within"] > 0).sum())
        ci63 = i63["ci_lower"] if pd.notna(i63["ci_lower"]) else None
        ci126 = i126["ci_lower"] if pd.notna(i126["ci_lower"]) else None
        if ((ci63 is not None and ci63 > 0) or (ci126 is not None and ci126 > 0)) and n_pos_q >= 4:
            out["INCREMENTAL_INFORMATION"] = "YES"
        elif (i63["median"] or 0) > 0 and (i126["median"] or 0) > 0:
            out["INCREMENTAL_INFORMATION"] = "WEAK"
        else:
            out["INCREMENTAL_INFORMATION"] = "NO"
        return out

    # ---------------- PART 7: fixed overlays (certified engine) --------------
    port_json: dict = {}
    if "--skip-portfolios" not in sys.argv:
        import v3lib as L
        RA, adj, cal, tk = L.load_engine()
        sp1 = panel[["as_of", "symbol"]].copy()
        sp1["ui_score"] = ui
        sp1 = sp1[np.isfinite(sp1["ui_score"])]
        top20_mask = {}
        for d in dates:
            ii = [j for j in idx[d] if np.isfinite(ui[j])]
            rows_d = sorted(ii, key=lambda j: -v1p[j])
            n20 = max(2, round(0.20 * len(rows_d)))
            top20_mask[d] = set(rows_d[:n20])
        overlays = {"V1_TOP20_BENCH": None}
        for sc in scores.columns:
            sv = scores[sc].to_numpy(float)
            upper_rows, lower_rows, t1_rows, t2_rows, t3_rows = [], [], [], [], []
            for d in dates:
                cands = [j for j in top20_mask[d] if np.isfinite(sv[j])]
                if len(cands) < 4:
                    continue
                cands.sort(key=lambda j: -sv[j])
                n = len(cands)
                upper_rows += [(d, panel["symbol"].iloc[j], sv[j]) for j in cands[:n // 2]]
                lower_rows += [(d, panel["symbol"].iloc[j], -sv[j]) for j in cands[:n // 2]]
                k1, k3 = n // 3, n - n // 3
                t1_rows += [(d, panel["symbol"].iloc[j], sv[j]) for j in cands[:k1]]
                t3_rows += [(d, panel["symbol"].iloc[j], -sv[j]) for j in cands[:k1]]
                t2_rows += [(d, panel["symbol"].iloc[j], sv[j]) for j in cands[k1:k3]]
            frames = {}
            for nm, lst in (("UPPER_HALF", upper_rows), ("LOWER_HALF", lower_rows),
                            ("TERTILE_TOP", t1_rows), ("TERTILE_MIDDLE", t2_rows),
                            ("TERTILE_BOTTOM", t3_rows)):
                fr = pd.DataFrame(lst, columns=["as_of", "symbol", "ui_score"])
                fr["as_of"] = fr["as_of"].astype(str)
                frames[nm] = fr
            port_json[sc] = {}
            for cname, rate in COSTS.items():
                perb, holdb, _ = RA.simulate(sp1, adj, cal, tk, 0.20, rate)
                mb = RA.metrics(perb, f"BENCH_{cname}")
                bset = {p["score_date"]: {h["symbol"] for h in holdb
                                          if h["score_date"] == p["score_date"]} for p in perb}
                out = {"bench": mb}
                retb = {p["score_date"]: p["monthly_return"] for p in perb
                        if "monthly_return" in p}
                for nm, fr in frames.items():
                    frac = 1.0 if nm == "TERTILE_MIDDLE" else (0.5 if "HALF" in nm else 1 / 3)
                    pero, holdo, _ = RA.simulate(fr, adj, cal, tk, frac, rate)
                    mo = RA.metrics(pero, f"{sc}_{nm}_{cname}")
                    reto = {p["score_date"]: p["monthly_return"] for p in pero
                            if "monthly_return" in p}
                    common_d = sorted(set(reto) & set(retb))
                    ex = np.array([reto[d] - retb[d] for d in common_d])
                    ovl = []
                    for p in pero:
                        so = {h["symbol"] for h in holdo if h["score_date"] == p["score_date"]}
                        sb = bset.get(p["score_date"], set())
                        if sb:
                            ovl.append(len(so & sb) / len(sb))
                    out[nm] = {**mo,
                               "excess_vs_bench_mean_monthly": float(np.mean(ex)) if len(ex) else None,
                               "excess_boot6": L.block6_bootstrap(ex) if len(ex) > 6 else None,
                               "selection_overlap_mean": float(np.mean(ovl)) if ovl else None,
                               "n_frames_rows": len(fr)}
                port_json[sc][cname] = out
            print("portfolios done:", sc)
        (HERE / "part7_overlays.json").write_text(json.dumps(port_json, indent=1), encoding="utf-8")

    # ---------------- PART 8: capacity (historical, panel TV30) --------------
    td60 = panel["t_traded_days_ratio_60"].to_numpy(float)
    tv30 = panel["t_trade_value_30d"].to_numpy(float)  # rial
    rows8 = []
    for d in dates:
        ii = [j for j in idx[d] if np.isfinite(ui[j])]
        rows_d = sorted(ii, key=lambda j: -v1p[j])
        n20 = max(2, round(0.20 * len(rows_d)))
        sel = rows_d[:n20]
        for split_name, members in (("V1_TOP20", sel),):
            tv_t = np.array([tv30[j] / 10.0 for j in members if np.isfinite(tv30[j]) and tv30[j] > 0])
            td = np.array([td60[j] for j in members if np.isfinite(td60[j])])
            if len(tv_t) < 3:
                continue
            n = len(tv_t)
            pct_td = V.midrank_pct(np.array([td60[j] for j in members]), True)
            pct_tv = V.midrank_pct(np.array([tv30[j] for j in members]), True)
            row = {"as_of": d, "universe": split_name, "n_names": n,
                   "missed_session_rate_mean": float(np.mean(1 - td)),
                   "fail_L1_frac": float(np.mean(pct_td < 0.10)),
                   "fail_L2_frac": float(np.mean(pct_tv < 0.10)),
                   "fail_L3_frac": float(np.mean((pct_td < 0.15) & (pct_tv < 0.15)))}
            for sz_name, sz in SIZES_TOMAN.items():
                capr = (sz / n) / tv_t
                row[f"cap_{sz_name}_median"] = float(np.median(capr))
                row[f"cap_{sz_name}_p90"] = float(np.percentile(capr, 90))
                row[f"cap_{sz_name}_frac_gt_1pct"] = float(np.mean(capr > 0.01))
                row[f"cap_{sz_name}_frac_gt_5pct"] = float(np.mean(capr > 0.05))
            rows8.append(row)
    pd.DataFrame(rows8).to_csv(HERE / "part8_capacity.csv", index=False, encoding="utf-8-sig")

    # ---------------- PART 9: technical special test --------------------------
    r_mom = np.array([r["MomentumRank"] if "MomentumRank" in r else np.nan
                      for r in panel["ranks"]], dtype=float)
    rows9 = {"tc_vs_v1_ui": None, "tc_vs_market_score": None, "tc_vs_v1_momentum_rank": None,
             "max_feature_pair_median_spearman": None, "feature_pair_matrix": []}
    tcv = scores["TECHNICAL_CONFIRMATION_SCORE"].to_numpy(float)
    for nm, tv in (("tc_vs_v1_ui", ui), ("tc_vs_market_score", comps["market_score"]),
                   ("tc_vs_v1_momentum_rank", r_mom)):
        per = sp_per_date(tcv, tv)
        vals = list(per.values())
        rows9[nm] = {"median": float(np.median(vals)) if vals else None,
                     "mean": float(np.mean(vals)) if vals else None,
                     "last": per.get(dates[-1]), "n_dates": len(vals)}
    tkeys = [f"TECHNICAL_CONFIRMATION_SCORE::{fid}" for fid, *_ in SPECS["TECHNICAL_CONFIRMATION_SCORE"]["feats"]]
    best = (None, -9)
    for a_i in range(len(tkeys)):
        for b_i in range(a_i + 1, len(tkeys)):
            xa = feat_pct[tkeys[a_i]].to_numpy(float)
            xb = feat_pct[tkeys[b_i]].to_numpy(float)
            per = sp_per_date(xa, xb, min_pairs=5)
            vals = list(per.values())
            med = float(np.median(vals)) if vals else None
            rows9["feature_pair_matrix"].append(
                {"a": tkeys[a_i].split("::")[1], "b": tkeys[b_i].split("::")[1],
                 "median_spearman": med})
            if med is not None and abs(med) > best[1]:
                best = (f"{tkeys[a_i].split('::')[1]}~{tkeys[b_i].split('::')[1]}", abs(med))
    rows9["max_feature_pair_median_spearman"] = {"pair": best[0], "abs_median": best[1]}
    (HERE / "part9_technical.json").write_text(json.dumps(rows9, indent=1), encoding="utf-8")

    # ---------------- PART 10: regimes + concentration ------------------------
    rows10 = []
    for sc in scores.columns:
        for h in (63, 126):
            per = ics_all[(sc, h)]
            vals = list(per.values())
            e_meds = {}
            for e in ("E1_2021_22", "E2_2023_24", "E3_2025_26"):
                ev = [v for d, v in per.items() if era(d) == e]
                e_meds[e] = float(np.median(ev)) if ev else None
            signs = {np.sign(v) for v in e_meds.values() if v is not None}
            absv = [abs(v) for v in e_meds.values() if v is not None]
            stable = ("BROADLY_STABLE" if len(signs) == 1 and 0 not in signs
                      and (max(absv) / min(absv) if min(absv) > 0 else 99) <= 3
                      else "REGIME_DEPENDENT")
            pos = sorted((v for v in vals if v > 0), reverse=True)
            top3_share = float(sum(pos[:3]) / sum(pos)) if pos else None
            excl3 = float(np.mean([v for v in vals if v not in pos[:3]])) if pos else None
            # Q5Q1 spread concentration
            rv = panel[f"ret_{h}"].to_numpy(float)
            sv = scores[sc].to_numpy(float)
            spreads = {}
            for d in dates:
                ii = idx[d]
                p = [(sv[j], rv[j]) for j in ii if np.isfinite(sv[j]) and np.isfinite(rv[j])]
                if len(p) >= 10:
                    p.sort(key=lambda t: t[0])
                    n = len(p)
                    q1 = np.mean([x[1] for x in p[:n // 5]])
                    q5 = np.mean([x[1] for x in p[-(n // 5):]])
                    spreads[d] = q5 - q1
            sp_pos = sorted((v for v in spreads.values() if v > 0), reverse=True)
            top10_share_sp = float(sum(sp_pos[:10]) / sum(sp_pos)) if sp_pos else None
            rows10.append({"score": sc, "h": h, **e_meds, "regime_class": stable,
                           "ic_mean_excluding_top3_positive": excl3,
                           "top3_positive_ic_share": top3_share,
                           "top10_positive_spread63_share": top10_share_sp,
                           "n_pos_dates": len(pos)})
    pd.DataFrame(rows10).to_csv(HERE / "part10_regimes.csv", index=False, encoding="utf-8-sig")

    # ---------------- scores_by_date (long) ----------------------------------
    sbd = panel[["as_of", "symbol", "ui_score"] + comp_cols + ["data_quality_score"]].copy()
    for sc in scores.columns:
        sbd[sc] = scores[sc].to_numpy()
        sbd[f"n_avail_{sc}"] = n_avail[sc]
    sbd.to_csv(HERE / "scores_by_date.csv", index=False, encoding="utf-8-sig")

    # ---------------- PART 11: score card ------------------------------------
    red_v1 = {r.score: abs(r.spearman_median) if r.spearman_median is not None else None
              for r in red[red.target == "V1_ui_score"].itertuples()}
    card = []
    for sc in scores.columns:
        cls = classify(sc)
        inc_cls = cls["INCREMENTAL_INFORMATION"]
        rv1 = red_v1.get(sc)
        red_cls = ("HIGH" if rv1 is not None and rv1 >= 0.7 else
                   "MEDIUM" if rv1 is not None and rv1 >= 0.4 else "LOW")
        s5 = ics5[(ics5.score == sc) & (ics5.h == 63)].iloc[0]
        standalone = ("HIGH" if (s5["ci_lower"] or 0) > 0
                      else "MEDIUM" if (s5["median"] or 0) > 0 else "LOW")
        r10 = [r for r in rows10 if r["score"] == sc and r["h"] == 63][0]
        reg = r10["regime_class"]
        if inc_cls == "YES" and red_cls == "LOW":
            research_value = "HIGH"
        elif inc_cls in ("YES", "WEAK") and red_cls in ("LOW", "MEDIUM"):
            research_value = "MEDIUM"
        elif inc_cls == "NO":
            research_value = "NO"
        elif standalone == "HIGH" and red_cls == "HIGH":
            research_value = "LOW"
        else:
            research_value = "LOW"
        status = ("B" if sc == "LIQUIDITY_CAPACITY_SCORE" else
                  "A" if research_value == "HIGH" else
                  "C" if red_cls == "HIGH" and inc_cls != "YES" else
                  "D" if reg == "REGIME_DEPENDENT" and research_value in ("MEDIUM", "LOW") else
                  "E" if inc_cls == "INCONCLUSIVE" else "D")
        card.append({"SCORE_NAME": sc,
                     "PIT_SAFE": "YES",
                     "COVERAGE": ("ADEQUATE" if cls["defined_share_of_panel"] >= 0.8
                                  else "PARTIAL" if cls["defined_share_of_panel"] >= 0.5
                                  else "LOW"),
                     "STANDALONE_INFORMATION": standalone,
                     "INCREMENTAL_INFORMATION_VS_V1": inc_cls,
                     "REDUNDANCY_WITH_V1": red_cls,
                     "REGIME_STABILITY": reg,
                     "TURNOVER_IMPACT": "see part7",
                     "IMPLEMENTABILITY_VALUE": "HIGH" if sc == "LIQUIDITY_CAPACITY_SCORE" else "n/a",
                     "RESEARCH_VALUE": research_value,
                     "STATUS": status,
                     "defined_share_of_panel": cls["defined_share_of_panel"]})
    card_df = pd.DataFrame(card)
    card_df.to_csv(HERE / "part11_score_card.csv", index=False, encoding="utf-8-sig")

    summary = {
        "v1_anchor_ics_this_panel": {str(h): anchor[h] for h in HORIZONS},
        "frozen_v1_ics_reference": {str(h): V.FROZEN_V1_IC[h] for h in HORIZONS},
        "score_card": card,
        "redundancy_vs_v1": {r["score"]: r["spearman_median"]
                             for r in red[red.target == "V1_ui_score"].to_dict("records")},
        "incremental_ic63_median": {r["score"]: r["median"] for r in
                                    inc[inc.h == 63].to_dict("records")},
        "incremental_ic126_median": {r["score"]: r["median"] for r in
                                     inc[inc.h == 126].to_dict("records")},
    }
    (HERE / "run_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print("\n=== SCORE CARD ===")
    print(card_df.to_string(index=False))
    print("\nDONE — artifacts in score_expansion_research/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
