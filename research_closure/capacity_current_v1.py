"""PARTS 8-9: capacity grid + current production V1 Top20% liquidity check.

READ-ONLY: Postgres SELECT-only (frozen section 20 allowance), certified technicals
chain, no production table is written, no selection altered. Snapshot = latest
completed non-fixture production run (same selection rule as the frozen V3 preview).

Risk class mapping per LIQUIDITY_GUARD_DEFS_FROZEN.md section 6b:
  HIGH     iff any current V1 Top20% name has capacity ratio > 5% at 1B toman,
           or fails L1, L2, or L3 at the snapshot date;
  MODERATE iff any name has capacity ratio > 1% at 1B toman;
  LOW      otherwise.
Capacity ratio (name, size) := (size / n_prod) / TV30_toman.  TV30 in RIAL from raw
qTotCap (TSETMC), toman = rial / 10 (stated assumption).

Outputs -> research_closure/: part9_current_v1_liquidity.csv, part8_capacity_grid.csv,
part9_summary.json
"""
from __future__ import annotations
import json, sys
from bisect import bisect_right
import numpy as np
import pandas as pd

ROOT = r"D:\RFA\Company-Financial"
HERE = ROOT + r"\research_closure"
AUD = ROOT + r"\score_v3_minimal_research"
sys.path.insert(0, AUD)
import v3lib as L  # noqa: E402
import v2lib as V  # noqa: E402

FIXTURE_RUNS = {"e5998f6d-93ab-4577-b13a-7b2f89c39c02"}
FACTOR_OF = {"SalesGrowthRank": "SalesGrowth", "SalesGrowth3MRank": "SalesGrowth3M",
             "NetProfitGrowthRank": "NetProfitGrowth", "StabilityRank": "Stability"}
SIZES_TOMAN = {"100M": 1e8, "500M": 5e8, "1B": 1e9, "5B": 5e9, "10B": 1e10}
THRESHOLDS = (0.01, 0.02, 0.05, 0.10)

info = L.verify_inputs()
assert info["pit_status"] == "PASS"

import psycopg
with psycopg.connect(V.DSN) as pg, pg.cursor() as cur:
    cur.execute("""SELECT id::text, as_of_date::text FROM analytics.score_runs
                   WHERE status='completed' ORDER BY completed_at DESC LIMIT 12""")
    runs = [r for r in cur.fetchall() if r[0] not in FIXTURE_RUNS]
    run_id, as_of = runs[0]
    cur.execute("""SELECT company_id::text, primary_security_id::text, quant_score,
                          data_quality_score FROM analytics.company_scores WHERE run_id=%s""",
                (run_id,))
    cs = pd.DataFrame(cur.fetchall(), columns=["company_id", "security_id",
                                               "quant_score", "dq"])
    cur.execute("""SELECT fs.company_id::text, fs.factor_code, fs.percentile
                   FROM analytics.factor_scores fs WHERE fs.run_id=%s""", (run_id,))
    fs = pd.DataFrame(cur.fetchall(), columns=["company_id", "factor_code", "percentile"])
    cur.execute("""SELECT id::text, codal_symbol FROM core.securities WHERE is_primary""")
    secs = pd.DataFrame(cur.fetchall(), columns=["security_id", "symbol"])
print("latest production run:", run_id, "as_of", as_of, "| universe rows:", len(cs))

cs = cs.merge(secs, on="security_id", how="left")
c2s = cs.dropna(subset=["symbol"]).drop_duplicates("company_id").set_index("company_id")["symbol"]
fs["symbol"] = fs["company_id"].map(c2s)
fpiv = fs.pivot_table(index="company_id", columns="factor_code", values="percentile",
                      aggfunc="first")
universe = cs.copy()
n_prod = int(len(universe) * 0.20)
universe["v1_rank"] = pd.to_numeric(universe["quant_score"], errors="coerce")\
    .rank(ascending=False, pct=True)

# ---------------- certified technicals at as_of for all universe symbols ----------
ref = V.load_reference_data()
syms = sorted(universe["symbol"].dropna().unique())
md = V.MarketData(ref, symbols=syms)
rows = []
for sym in syms:
    if sym not in md.data:
        rows.append({"symbol": sym, "tv30_rial": np.nan, "td60": np.nan,
                     "vol_60": np.nan, "mdd_60": np.nan})
        continue
    k = md.idx_at(sym, as_of)
    if k < 0 or k + 1 < V.MIN_SESSIONS:
        rows.append({"symbol": sym, "tv30_rial": np.nan, "td60": np.nan,
                     "vol_60": np.nan, "mdd_60": np.nan})
        continue
    tf = V.compute_symbol_technicals(md, sym).iloc[k]
    rows.append({"symbol": sym, "tv30_rial": float(tf["t_trade_value_30d"]),
                 "td60": float(tf["t_traded_days_ratio_60"]),
                 "vol_60": float(tf["t_vol_60"]), "mdd_60": float(tf["t_mdd_60"])})
tech = pd.DataFrame(rows)
tech["tv30_toman"] = tech["tv30_rial"] / 10.0
uni = universe.merge(tech, on="symbol", how="left")
print("technicals computed for", int(tech["tv30_rial"].notna().sum()), "of", len(syms),
      "symbols at", as_of)

# cross-sectional percentiles within the production universe (guard flag base)
uni["pct_tv30"] = V.midrank_pct(uni["tv30_rial"].to_numpy(float), True)
uni["pct_td60"] = V.midrank_pct(uni["td60"].to_numpy(float), True)
uni["fail_L1"] = uni["pct_td60"].isna() | (uni["pct_td60"] < 0.10)
uni["fail_L2"] = uni["pct_tv30"].isna() | (uni["pct_tv30"] < 0.10)
uni["fail_L3"] = (uni["pct_td60"].isna() | uni["pct_tv30"].isna()
                  | ((uni["pct_td60"] < 0.15) & (uni["pct_tv30"] < 0.15)))

# ---------------- V1 Top20% (production selection, untouched) ---------------------
v1sel = uni.nsmallest(n_prod, "v1_rank").copy()   # v1_rank ascending = best first
v1sel["target_weight"] = 1.0 / len(v1sel)
for sz_name, sz in SIZES_TOMAN.items():
    v1sel[f"cap_ratio_{sz_name}"] = (sz / len(v1sel)) / v1sel["tv30_toman"]

# ---------------- V3 (frozen B-W1) Top20% at the same snapshot (diagnostic) -------
W3 = {"SalesGrowthRank": 5.0, "SalesGrowth3MRank": 12.5, "NetProfitGrowthRank": 12.5,
      "StabilityRank": 12.5, "vol_60": 12.5, "mdd_60": 12.5}
R = np.zeros(len(uni))
for f, fc in FACTOR_OF.items():
    col = uni["company_id"].map(fpiv[fc]) if fc in fpiv.columns else \
        pd.Series(np.nan, index=uni.index)
    R += W3[f] * pd.to_numeric(col, errors="coerce").fillna(0.5).to_numpy()
for f, raw in (("vol_60", "vol_60"), ("mdd_60", "mdd_60")):
    rr = V.midrank_pct(pd.to_numeric(uni[raw], errors="coerce").to_numpy(float), True)
    R += W3[f] * np.where(np.isfinite(rr), rr, 0.5)
uni["v3_score"] = pd.to_numeric(uni["dq"], errors="coerce").fillna(0.0).to_numpy() * 100.0 * R
v3sel = uni.nlargest(n_prod, "v3_score").copy()
v3sel["target_weight"] = 1.0 / len(v3sel)
for sz_name, sz in SIZES_TOMAN.items():
    v3sel[f"cap_ratio_{sz_name}"] = (sz / len(v3sel)) / v3sel["tv30_toman"]

# ---------------- PART 9 table -----------------------------------------------------
p9 = v1sel[["symbol", "quant_score", "v1_rank", "target_weight", "td60", "tv30_rial",
            "tv30_toman", "pct_tv30", "pct_td60", "fail_L1", "fail_L2", "fail_L3",
            "cap_ratio_100M", "cap_ratio_500M", "cap_ratio_1B", "cap_ratio_5B",
            "cap_ratio_10B"]].copy()
p9.insert(0, "snapshot_as_of", as_of)
p9.sort_values("v1_rank").to_csv(HERE + r"\part9_current_v1_liquidity.csv", index=False,
                                 encoding="utf-8-sig")

# ---------------- PART 8 grid ------------------------------------------------------
def exceed_fracs(df: pd.DataFrame, n: int) -> dict:
    out = {}
    for sz_name, sz in SIZES_TOMAN.items():
        ratio = (sz / n) / df["tv30_toman"]
        for th in THRESHOLDS:
            key = f"{sz_name}_gt_{int(th*1000)}ppm"
            out[key] = float(np.nanmean(ratio > th))
        out[f"{sz_name}_median_ratio"] = float(np.nanmedian(ratio))
    return out

grid_rows = [{"model": "V1_top20pct", "n_names": len(v1sel), **exceed_fracs(v1sel, len(v1sel))},
             {"model": "V3_BW1_top20pct", "n_names": len(v3sel), **exceed_fracs(v3sel, len(v3sel))}]
grid = pd.DataFrame(grid_rows)
grid.to_csv(HERE + r"\part8_capacity_grid.csv", index=False, encoding="utf-8-sig")

# ---------------- 6b risk class + summary -----------------------------------------
r1B = (1e9 / len(v1sel)) / v1sel["tv30_toman"]
fails = v1sel[["fail_L1", "fail_L2", "fail_L3"]].any(axis=1)
if bool((r1B > 0.05).any() or fails.any()):
    risk = "HIGH"
elif bool((r1B > 0.01).any()):
    risk = "MODERATE"
else:
    risk = "LOW"
prev = json.load(open(AUD + r"\v3_preview_explainability.json"))
summary = {
    "snapshot_as_of": as_of, "run_id": run_id,
    "universe_size": int(len(uni)), "n_prod_top20pct": int(n_prod),
    "frozen_preview_run_id": prev.get("run_id"), "frozen_preview_as_of": str(prev.get("snapshot_as_of")),
    "same_run_as_frozen_preview": bool(prev.get("run_id") == run_id),
    "CURRENT_V1_HAS_LIQUIDITY_RISK": risk,
    "n_names_fail_any_guard": int(fails.sum()),
    "names_failing_guards": sorted(v1sel.loc[fails, "symbol"].tolist()),
    "n_names_cap_gt_1pct_1B": int((r1B > 0.01).sum()),
    "n_names_cap_gt_5pct_1B": int((r1B > 0.05).sum()),
    "max_cap_ratio_1B": float(np.nanmax(r1B)),
    "names_max_capacity": str(v1sel["symbol"].to_numpy()[int(np.nanargmax(r1B.to_numpy()))]),
    "missing_tv30_in_top20pct": int(v1sel["tv30_toman"].isna().sum()),
    "v1sel_median_tv30_toman": float(np.nanmedian(v1sel["tv30_toman"])),
    "v3sel_median_tv30_toman": float(np.nanmedian(v3sel["tv30_toman"])),
    "v1sel_median_td60": float(np.nanmedian(v1sel["td60"])),
    "v1sel_share_fail_L1": float(v1sel["fail_L1"].mean()),
    "v1sel_share_fail_L2": float(v1sel["fail_L2"].mean()),
    "v1sel_share_fail_L3": float(v1sel["fail_L3"].mean()),
    "assumption": "TV30 = mean raw qTotCap (rial) over last 30 sessions; toman = rial/10",
}
json.dump(summary, open(HERE + r"\part9_summary.json", "w", encoding="utf-8"),
          indent=1, ensure_ascii=False, default=str)
print(json.dumps(summary, indent=1, ensure_ascii=False, default=str))
print("\nV1 Top20% capacity table (head by worst capacity at 1B):")
print(p9.sort_values("cap_ratio_1B", ascending=False).head(12).to_string(index=False))
print("\nPARTS 8-9 DONE")
