"""SCORE EXPANSION RESEARCH V1 — PART 13 current-universe snapshot (RESEARCH PREVIEW).

READ-ONLY Postgres (SELECT only; no writes to analytics.*), certified MarketData path.
Applies the FROZEN candidate formulas (spec_frozen.json SHA 0ec9a4f4...) to the latest
completed non-fixture production run of canonical-v1-dev. UI exposure: NONE.
Outputs: part13_snapshot.csv, part8_current_capacity.csv, snapshot_meta.json.
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
sys.path.insert(0, str(HERE))
import v2lib as V  # noqa: E402
import run_score_expansion as R  # noqa: E402  (frozen SPECS + transforms)

FIXTURE_RUNS = {"e5998f6d-93ab-4577-b13a-7b2f89c39c02"}
SIZES_TOMAN = R.SIZES_TOMAN


def col(df, name):
    return df[name] if name in df.columns else pd.Series(np.nan, index=df.index)

FACTOR_MAP = {  # factor_code -> spec feature id
    "SalesGrowth": "sg12", "SalesGrowth3M": "sg3", "RevenueGrowth": "rev",
    "OperatingProfitGrowth": "opg", "NetProfitGrowth": "npg", "MarginTrend": "mt",
    "CashConversion": "cash_conv", "EarningsQuality": "earnq",
    "InterestCoverage": "icov", "Stability": "stab", "Leverage": "lev",
    "CurrentRatio": "cr", "OperatingMargin": "om", "NetMargin": "nm",
}


def main() -> int:
    import psycopg
    with psycopg.connect(V.DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT id::text, as_of_date::text FROM analytics.score_runs
                       WHERE score_version='canonical-v1-dev' AND status='completed'
                       ORDER BY as_of_date DESC, started_at DESC LIMIT 12""")
        runs = [r for r in cur.fetchall() if r[0] not in FIXTURE_RUNS]
        run_id, run_asof = runs[0]
        cur.execute("""SELECT cs.company_id::text, cs.quant_score, cs.data_quality_score,
                              s.codal_symbol
                       FROM analytics.company_scores cs
                       LEFT JOIN core.securities s ON s.id = cs.primary_security_id
                       WHERE cs.run_id=%s""", (run_id,))
        cs = pd.DataFrame(cur.fetchall(),
                          columns=["company_id", "quant_score", "dq", "symbol"])
        cur.execute("""SELECT fs.company_id::text, fs.factor_code, fs.raw_value
                       FROM analytics.factor_scores fs WHERE fs.run_id=%s""", (run_id,))
        fs = pd.DataFrame(cur.fetchall(), columns=["company_id", "factor_code", "raw_value"])
    print(f"snapshot run {run_id} as_of {run_asof} | universe rows {len(cs)}")
    cs = cs.dropna(subset=["symbol"]).drop_duplicates("company_id")
    raw_cur = fs.pivot(index="company_id", columns="factor_code", values="raw_value")
    raw_cur = raw_cur.rename(columns={k: f"cur_{FACTOR_MAP.get(k, k)}" for k in raw_cur.columns})
    uni = cs.merge(raw_cur, left_on="company_id", right_index=True, how="left")

    # ---- history rows from the certified base panel (raw fundamentals) ------
    base = pd.read_parquet(ROOT / "ui_score_research" / "ui_score_historical_pit_v2.parquet")
    T = dt.date.fromisoformat(run_asof)
    anchor_vals = {}
    for sym, g in base.groupby("symbol", sort=False):
        g = g.sort_values("as_of")
        dates = [dt.date.fromisoformat(d) for d in g["as_of"]]
        recs = g.to_dict("records")
        fv = {}

        def anchor(a: int, b: int):
            for k in range(len(recs) - 1, -1, -1):
                gap = (T - dates[k]).days
                if b <= gap <= a:
                    return recs[k]
                if gap > a:
                    break
            return None

        p1, p2, p3 = anchor(100, 70), anchor(200, 170), anchor(300, 270)
        for k, r in ((1, p1), (2, p2), (3, p3)):
            if r is not None:
                fv[f"p{k}_sg12"] = r.get("sales_growth_12m")
                fv[f"p{k}_om"] = r.get("operating_margin")
                fv[f"p{k}_nm"] = r.get("net_margin")
                fv[f"p{k}_npg"] = (r.get("net_profit_growth")
                                   if r.get("net_profit_growth") is not None
                                   else r.get("eps_growth"))
        fv["n_history_rows"] = len(recs)
        anchor_vals[sym] = fv
    A = pd.DataFrame(anchor_vals).T
    uni = uni.merge(A, left_on="symbol", right_index=True, how="left")

    num = lambda s: pd.to_numeric(s, errors="coerce")
    cur_sg12 = num(col(uni, "cur_sg12"))
    # acceleration: current raw minus anchor raw (frozen windows, <=quarterly spacing)
    uni["sg_accel"] = cur_sg12 - num(col(uni, "p1_sg12"))
    uni["pg_accel"] = num(col(uni, "cur_npg")) - num(col(uni, "p1_npg"))
    uni["om_delta"] = num(col(uni, "cur_om")) - num(col(uni, "p1_om"))
    for c, xs in (("pg_cons", ["cur_npg", "p1_npg", "p2_npg", "p3_npg"]),
                  ("nm_stab", ["cur_nm", "p1_nm", "p2_nm", "p3_nm"])):
        X = pd.concat([num(col(uni, c_)) for c_ in xs], axis=1)
        uni[c] = -X.std(axis=1, ddof=0).where(X.notna().all(axis=1))

    # ---- market features at latest session <= today (certified path) --------
    ref = V.load_reference_data()
    md = V.MarketData(ref, symbols=sorted(uni["symbol"].dropna().unique()))
    today = dt.date.today().isoformat()
    rows = []
    for sym in uni["symbol"]:
        s = md.data.get(sym)
        if not s:
            rows.append({})
            continue
        k = V.MarketData.idx_at(md, sym, today)
        if k < 0 or k + 1 < V.MIN_SESSIONS:
            rows.append({"market_ok": False})
            continue
        c = md.adj(sym, "c")
        rets = np.full(len(c), np.nan)
        rets[1:] = c[1:] / c[:-1] - 1.0
        ma60 = pd.Series(c).rolling(60, min_periods=60).mean().to_numpy()
        w = s["tval"][k - 59: k + 1].astype(float)
        m = float(np.nanmean(w))
        sd = float(np.nanstd(w, ddof=1))
        rows.append({
            "market_ok": True,
            "sg12_mkt": np.nan,  # fundamentals come from the run, not market
            "t_mom_20": c[k] / c[k - 19] - 1.0 if k >= 19 else np.nan,
            "t_mom_60": c[k] / c[k - 59] - 1.0 if k >= 59 else np.nan,
            "t_mom_120": c[k] / c[k - 119] - 1.0 if k >= 119 else np.nan,
            "t_ma60_slope": ma60[k] / ma60[k - 20] - 1.0 if k >= 79 else np.nan,
            "t_price_vs_ma60": c[k] / ma60[k] - 1.0,
            "t_dist_high_60": c[k] / np.nanmax(c[k - 59: k + 1]) - 1.0,
            "t_vol_60": float(np.nanstd(rets[k - 59: k + 1], ddof=1)),
            "t_traded_days_ratio_60": float(np.mean(s["tcnt"][k - 59: k + 1] > 0)),
            "t_trade_value_30d": float(np.nanmean(s["tval"][k - 29: k + 1])),
            "tval_cv60": sd / m if m else np.nan,
        })
    MK = pd.DataFrame(rows, index=uni.index)
    uni = pd.concat([uni, MK], axis=1)
    uni["vam60"] = uni["t_mom_60"] / (uni["t_vol_60"] + 1e-12)

    # ---- frozen formulas (SPECS imported from the runner) -------------------
    COLRENAME = {"sg_accel": "f_sales_growth_accel", "pg_accel": "f_profit_growth_accel",
                 "pg_cons": "f_profit_growth_consistency", "om_delta": "f_operating_margin_delta",
                 "nm_stab": "f_earnings_margin_stability"}
    out = uni.copy()
    for a, b in COLRENAME.items():
        out[b] = col(out, a)
    for f in ("sg12", "sg3", "rev", "opg", "npg", "mt", "cash_conv", "earnq", "icov",
              "stab", "lev", "cr"):
        out[f] = col(out, f"cur_{f}")
    out["icov"] = num(out["icov"]).where(num(out["icov"]) > 0, -999999.0)

    ALIAS = {"sales_growth_12m": "sg12", "sales_growth_3m": "sg3", "revenue_growth": "rev",
             "operating_profit_growth": "opg", "net_profit_growth|eps_growth": "npg",
             "margin_trend": "mt", "cash_conversion": "cash_conv", "earnings_quality": "earnq",
             "interest_coverage": "icov", "sales_stability": "stab", "debt_ratio": "lev",
             "current_ratio": "cr"}
    for sc, spec in R.SPECS.items():
        pct_cols = []
        for fid, colspec, dirn, caps, pre in spec["feats"]:
            fcol = {"__tval_cv60__": "tval_cv60", "__vam60__": "vam60"}.get(colspec, colspec)
            fcol = ALIAS.get(colspec, fcol)
            if "|" in fcol:
                a, b = fcol.split("|")
                x = num(col(out, a)).where(num(col(out, a)).notna(), num(col(out, b)))
            else:
                x = num(col(out, fcol))
            if pre == "x<=0 -> -999999":
                x = x.where(x > -999998.0, -999999.0)
                x = x.where(x <= -999998.0, x.clip(caps[0], caps[1]))
            elif pre == "min(abs,150)":
                x = x.abs().clip(upper=150.0)
            elif pre == "min(x,50)":
                x = x.clip(upper=50.0)
            elif caps:
                x = x.clip(caps[0], caps[1])
            pc = V.midrank_pct(x.to_numpy(float), dirn > 0)
            out[f"pct_{sc}::{fid}"] = pc
            pct_cols.append(f"pct_{sc}::{fid}")
        P = out[pct_cols].to_numpy(float)
        ok = np.isfinite(P)
        cnt = ok.sum(axis=1)
        smean = np.where(cnt > 0, np.where(ok, P, 0.0).sum(axis=1) / np.maximum(cnt, 1), np.nan)
        smean[cnt < spec["min_feats"]] = np.nan
        out[sc] = 100.0 * smean
        out[f"n_avail_{sc}"] = cnt

    snap_cols = ["symbol", "quant_score", "dq",
                 "FUNDAMENTAL_MOMENTUM_SCORE", "EARNINGS_QUALITY_RESILIENCE_SCORE",
                 "LIQUIDITY_CAPACITY_SCORE", "TECHNICAL_CONFIRMATION_SCORE",
                 "n_avail_FUNDAMENTAL_MOMENTUM_SCORE", "n_avail_EARNINGS_QUALITY_RESILIENCE_SCORE",
                 "n_avail_LIQUIDITY_CAPACITY_SCORE", "n_avail_TECHNICAL_CONFIRMATION_SCORE",
                 "market_ok", "n_history_rows"]
    snap = out[snap_cols].sort_values("quant_score", ascending=False)
    snap.to_csv(HERE / "part13_snapshot.csv", index=False, encoding="utf-8-sig")

    # ---- current V1 Top-20% capacity (Part 8 current view) ------------------
    sel = snap.dropna(subset=["quant_score"]).copy()
    n_prod = max(2, round(0.20 * len(sel)))
    sel = sel.head(n_prod).merge(out[["symbol", "t_trade_value_30d", "t_traded_days_ratio_60"]],
                                 on="symbol", how="left")
    rows8 = []
    for _, r in sel.iterrows():
        tv_toman = (r["t_trade_value_30d"] or np.nan) / 10.0
        row = {"symbol": r["symbol"], "quant_score": r["quant_score"],
               "td60": r["t_traded_days_ratio_60"], "tv30_toman": tv_toman}
        for sz_name, sz in SIZES_TOMAN.items():
            row[f"cap_ratio_{sz_name}"] = (sz / n_prod) / tv_toman if tv_toman else np.inf
        rows8.append(row)
    cap = pd.DataFrame(rows8)
    cap.to_csv(HERE / "part8_current_capacity.csv", index=False, encoding="utf-8-sig")

    meta = {"run_id": run_id, "run_as_of": run_asof, "universe_rows": int(len(cs)),
            "snapshot_symbols": int(len(snap)),
            "market_session": today,
            "candidate_defined": {sc: int(out[sc].notna().sum()) for sc in R.SPECS},
            "cap_1B_median": float(cap["cap_ratio_1B"].replace(np.inf, np.nan).median()),
            "cap_1B_frac_gt_5pct": float(np.mean(cap["cap_ratio_1B"] > 0.05)),
            "writes_to_production": "NONE"}
    (HERE / "snapshot_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
