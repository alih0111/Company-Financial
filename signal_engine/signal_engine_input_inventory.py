"""SIGNAL ENGINE preregistration — INPUT INVENTORY ONLY (no signals, no model, no returns).

For each allowed input class (PHASE 3 of the preregistration), computes availability over
the frozen 63-date x 238-symbol research grid from the cached raw pClosing series and the
frozen UI-score reconstruction. Availability = the feature is computable ex ante at the
signal date (all lookbacks end at or before the signal date). No ICs, no forward returns,
no signal values are produced here.
"""
from __future__ import annotations

import bisect
import csv
import datetime as dt
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
SIG = Path(r"D:\RFA\Company-Financial\canonical_postgres_v1_2_1\backtesting_v1\output\phase3_signals.csv")
UI = HERE / "ui_score_historical_v1" / "ui_score_historical_v1.jsonl"
RAW = HERE / "output" / "raw_closing_universe"
IDX = HERE / "output" / "tsetmc_share" / "index.json"
OUT = HERE / "signal_engine" / "input_inventory.json"
OUT.parent.mkdir(exist_ok=True)


def main() -> int:
    grid = {}
    with open(SIG, encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            grid.setdefault(r["signal_date"], set()).add(r["symbol"])
    dates = sorted(grid)
    ui = {}
    for line in UI.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            ui[(r["as_of"], r["symbol"])] = r
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    series = {}
    for sym in sorted({s for d in dates for s in grid[d]}):
        ins = (idx.get(sym) or {}).get("ins_code")
        gz = RAW / f"raw_{sym}_{ins}.json.gz"
        if not gz.exists():
            continue
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            doc = json.loads(fh.read())
        recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
        ds, ps, tv = [], [], []
        for r in recs:
            s = str(r["dEven"])
            ds.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
            ps.append(float(r["pClosing"]))
            tv.append(float(r.get("qTotCap") or 0) if r.get("qTotCap") else None)
        series[sym] = (ds, ps, tv)

    # per-input availability counters over the grid
    feats = ["mom_20", "mom_30", "mom_60", "mom_90", "dist_high60", "drawdown_60",
             "vol_30", "downside_vol_30", "liq_30", "mkt_breadth", "mkt_disp21",
             "mkt_vol_level", "ui_score", "cat_growth", "cat_profit", "cat_valuation", "cat_market"]
    avail = {f: 0 for f in feats}
    rows_total = 0
    first_usable = {f: None for f in feats}
    per_date_n = []
    for d in dates:
        dd = dt.date.fromisoformat(d)
        counts = {f: 0 for f in feats}
        n_rows = 0
        # market-state (cross-sectional, computed from the covered universe)
        r21s, disp_rets = [], []
        for sym in grid[d]:
            s = series.get(sym)
            if not s:
                continue
            ds, ps, tv = s
            i = bisect.bisect_right(ds, d) - 1
            if i < 0:
                continue
            n_rows += 1
            def ret(k):
                return ps[i] / ps[i - k] - 1.0 if i >= k and ps[i - k] > 0 and ps[i] > 0 else None
            if i >= 21 and ps[i - 21] > 0:
                r21s.append(ret(21))
                rets = [ps[j] / ps[j - 1] - 1.0 for j in range(i - 20, i + 1) if ps[j - 1] > 0]
                if len(rets) == 21:
                    counts["vol_30"] += 1
                    dn = [x for x in rets if x < 0]
                    if len(dn) >= 2:
                        counts["downside_vol_30"] += 1
            for k, f in ((20, "mom_20"), (30, "mom_30"), (60, "mom_60"), (90, "mom_90")):
                if i >= k and ps[i - k] > 0 and ps[i] > 0:
                    counts[f] += 1
            if i >= 60 and ps[i] > 0:
                hi = max(ps[i - 59:i + 1])
                if hi > 0:
                    counts["dist_high60"] += 1
                draw = ps[i] / max(ps[i - 59:i + 1]) - 1.0
                if draw <= 0:
                    counts["drawdown_60"] += 1
            # liquidity 30d: mean qTotCap (trade value) over the last 30 raw rows
            tvs = [ps_val for ps_val in []]  # placeholder
            tv_vals = []
            try:
                pass
            except Exception:
                pass
            if i >= 29 and tv[i - 29:i + 1] and all(x is not None for x in tv[i - 29:i + 1]):
                counts["liq_30"] += 1
            u = ui.get((d, sym))
            if u and u.get("ui_score") is not None:
                counts["ui_score"] += 1
                for cat, f in (("growth_score", "cat_growth"), ("profitability_score", "cat_profit"),
                               ("valuation_score", "cat_valuation"), ("market_score", "cat_market")):
                    if u.get(cat) is not None:
                        counts[f] += 1
        if len(r21s) >= 10:
            counts["mkt_breadth"] = len(r21s)
            counts["mkt_disp21"] = len(r21s)
            counts["mkt_vol_level"] = len(r21s)
        rows_total += n_rows
        for f in feats:
            avail[f] += counts[f]
            if counts[f] > 0 and first_usable[f] is None:
                first_usable[f] = d
        per_date_n.append({"date": d, "universe_rows": n_rows, **{f: counts[f] for f in feats}})
    doc = {"purpose": "INPUT INVENTORY ONLY — availability of allowed Signal Engine inputs "
                      "over the frozen grid; no signal values, no ICs, no forward returns",
           "grid": {"dates": len(dates), "rows_total": rows_total},
           "availability_of_grid_rows": {f: {"count": avail[f],
                                             "pct_of_rows": round(avail[f] / rows_total * 100, 2)}
                                         for f in feats},
           "first_usable_date": first_usable,
           "per_date": per_date_n}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("rows_total:", rows_total)
    for f in feats:
        print(f"  {f:18} {avail[f]:6} ({avail[f]/rows_total*100:5.1f}%)  first={first_usable[f]}")
    print("wrote input_inventory.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
