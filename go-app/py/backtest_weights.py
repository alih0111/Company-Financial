# -*- coding: utf-8 -*-
"""
مقایسه‌ی وزن‌های فعلی (v3.x) با وزن‌های پیشنهادیِ برآمده از IC فاز ۱

دو پیکربندی در همان گذر ماهانه و همان جهان/رتبه‌ها امتیازدهی می‌شوند؛
تفاوت‌ها فقط در وزن فاکتورها و حذف جریمه‌ی دوگانه‌ی کهنگی است.

تفکیک: درون‌نمونه ۱۳۹۹-۱۴۰۲ | برون‌نمونه ۱۴۰۳-۱۴۰۴ | کل دوره
افق‌های عملیاتی: ۳ و ۶ ماهه | پرتفوی Top10/Top20 هم‌وزن
"""
import json
import math
import os
import sys
from bisect import bisect_right

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backtest import (  # noqa: E402
    MIN_UNIVERSE,
    OUT_DIR,
    add_months,
    build_structures,
    company_factors,
    compute_dq,
    jalali_month_end_g,
    load_data,
    pct_rank,
)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# ----------------------------------------------------------------------------
# پیکربندی وزن‌ها
# ----------------------------------------------------------------------------
W_OLD = dict(sg12=9, sg3=4, rg=5, opg=8, npg=10,
             om=4, nm=3, mt=3, ic=3, eq=4,
             pe=10, ps=3,
             liq=6, st=3, lv=3, mo=3,
             stale_pen=True)

W_NEW = dict(sg12=10, sg3=6, rg=5, opg=5, npg=10,
             om=4, nm=3, mt=3, ic=3, eq=4,
             pe=11, ps=3,
             liq=6, st=1, lv=5, mo=1,
             stale_pen=False)

CONFIGS = {"old": W_OLD, "new": W_NEW}
HORIZONS = [3, 6]
TOP_NS = [10, 20]
TRAIN_MAX_JY = 1402

CAPS = {"sg12": 150, "sg3": 150, "rg": 200, "opg": 250, "npg": 300,
        "om": 80, "nm": 60, "mt": 25, "ic": 20, "eq": 150}


def score_with_weights(rows, w):
    """امتیاز کل با پیکربندی وزن w (رتبه‌بندی و جریمه‌ها مثل فاز ۱)"""
    n = len(rows)

    def col(k):
        return np.array([r[k] if r[k] is not None and np.isfinite(r[k]) else np.nan for r in rows])

    vals = {}
    for k in CAPS:
        v = np.clip(col(k), -CAPS[k], CAPS[k])
        if k == "ic":
            v = np.where(np.isfinite(v) & (v <= 0), -999999.0, v)
        vals[k] = v
    for k in ["pe", "ps", "liq", "stability", "vol", "mom"]:
        vals[k] = col(k)

    r_sg12 = pct_rank(vals["sg12"])
    r_sg3 = pct_rank(vals["sg3"])
    r_rg = pct_rank(vals["rg"])
    r_opg = pct_rank(vals["opg"])
    r_npg = pct_rank(vals["npg"])
    r_om = pct_rank(vals["om"])
    r_nm = pct_rank(vals["nm"])
    r_mt = pct_rank(vals["mt"])
    r_ic = pct_rank(vals["ic"], neutral=0.50)
    r_eq = pct_rank(vals["eq"], invert=True, neutral=0.50)
    pe_valid = np.isfinite(vals["pe"])
    r_pe = np.where(pe_valid, pct_rank(vals["pe"], invert=True), 0.0)
    ps_valid = np.isfinite(vals["ps"])
    r_ps = np.where(ps_valid, pct_rank(vals["ps"], invert=True), 0.0)
    r_lq = pct_rank(vals["liq"], neutral=0.0)
    r_st = pct_rank(vals["stability"])
    r_lv = pct_rank(vals["vol"], invert=True)
    r_mo = pct_rank(vals["mom"])

    growth = (w["sg12"] * r_sg12 + w["sg3"] * r_sg3 + w["rg"] * r_rg
              + w["opg"] * r_opg + w["npg"] * r_npg)
    prof = (w["om"] * r_om + w["nm"] * r_nm + w["mt"] * r_mt
            + w["ic"] * r_ic + w["eq"] * r_eq)
    valn = w["pe"] * r_pe + w["ps"] * r_ps
    markt = (w["liq"] * r_lq + w["st"] * r_st + w["lv"] * r_lv + w["mo"] * r_mo)

    # جریمه‌ها: رشد/سودآوری/ارزش در هر دو یکسان؛ کهنگی فقط در old
    pen_g = np.zeros(n)
    pen_g += 6.0 * (np.isfinite(vals["sg12"]) & (vals["sg12"] < -20))
    pen_g += 5.0 * (np.isfinite(vals["opg"]) & (vals["opg"] < -25))
    pen_p = np.zeros(n)
    ttm_np = np.array([r["ttm_np"] for r in rows])
    pen_p += 10.0 * (np.isfinite(ttm_np) & (ttm_np < 0))
    pen_p += 4.0 * (np.isfinite(vals["ic"]) & (vals["ic"] < 1.5))
    pen_p += 3.0 * (np.isfinite(vals["mt"]) & (vals["mt"] < -2))
    pen_p += np.where(np.isfinite(vals["eq"]),
                      np.clip((vals["eq"] - 20.0) / 80.0, 0.0, 1.0) * 8.0, 0.0)
    pe_inv = np.array([r["pe_invalid"] for r in rows], bool)
    pen_v = 8.0 * pe_inv
    pen_m = np.zeros(n)
    if w["stale_pen"]:
        pad = np.array([r["price_age_d"] for r in rows], float)
        ram = np.array([r["report_age_m"] for r in rows], float)
        pen_m += 4.0 * (np.isfinite(pad) & (pad > 14))
        pen_m += 3.0 * (np.isfinite(ram) & (ram > 8))

    dq = np.array([compute_dq(r) for r in rows])
    total = dq * (np.maximum(growth - pen_g, 0.0) + np.maximum(prof - pen_p, 0.0)
                  + np.maximum(valn - pen_v, 0.0) + np.maximum(markt - pen_m, 0.0))
    return total


def ic_tstat(arr):
    a = np.asarray(arr, float)
    if len(a) < 3 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / (a.std(ddof=1) / math.sqrt(len(a))))


def port_compound(sub, col, h):
    """ترکیب غیرهم‌پوشان: هر h ماه یکبار از ابتدای پنجره"""
    s = sub.iloc[::h]
    if not len(s):
        return np.nan
    return float(np.prod(1.0 + s[col]) - 1.0)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("بارگذاری داده...", flush=True)
    reports, sales, market = load_data()
    rep_by_cid, sales_by_cid, price_by_cid, sym_by_cid = build_structures(reports, sales, market)
    pub_lists = {cid: [r["pub"] for r in rows] for cid, rows in rep_by_cid.items()}
    print(f"شرکت‌ها: قیمت={len(price_by_cid)} گزارش={len(rep_by_cid)}", flush=True)

    dates = []
    jy, jm = 1399, 1
    while (jy, jm) <= (1404, 12):
        dates.append((jy, jm, jalali_month_end_g(jy, jm)))
        jy, jm = add_months(jy, jm, 1)

    port_rows = []          # یک رکورد در هر (تاریخ، افق)
    ic_recs = []            # IC هر تاریخ به تفکیک پیکربندی
    n_dates = 0

    for jy, jm, gdate in dates:
        D_ord = gdate.toordinal()
        D_jkey = jy * 12 + jm
        rows = []
        for cid, price in price_by_cid.items():
            rep_rows = rep_by_cid.get(cid)
            if not rep_rows:
                continue
            sk, sv = sales_by_cid.get(cid, (None, None))
            f = company_factors(rep_rows, pub_lists[cid], sk, sv, price, D_ord, D_jkey)
            if f is None:
                continue
            if f["n_profit_reports"] < 1 or f["n_market_days"] < 30 or f["n_sales_reports"] < 12:
                continue
            f["cid"] = cid
            f["symbol"] = sym_by_cid.get(cid, "")
            rows.append(f)
        if len(rows) < MIN_UNIVERSE:
            continue
        n_dates += 1

        scores = {cfg: score_with_weights(rows, w) for cfg, w in CONFIGS.items()}

        # بازده آینده + IC
        fwd_cols = {}
        for r in rows:
            p = price_by_cid[r["cid"]]
            i0 = bisect_right(p["dates"], D_ord) - 1
            base = p["idx"][i0]
            for h in HORIZONS:
                hy, hm = add_months(jy, jm, h)
                tgt = jalali_month_end_g(hy, hm).toordinal()
                i1 = bisect_right(p["dates"], tgt) - 1
                ok = i1 >= 0 and (tgt - int(p["dates"][i1])) <= 100
                r[f"fwd{h}"] = p["idx"][i1] / base - 1.0 if ok else np.nan

        for h in HORIZONS:
            idx_map = {r["cid"]: r.get(f"fwd{h}") for r in rows}
            valid_cids = [c for c, v in idx_map.items() if v is not None and np.isfinite(v)]
            if len(valid_cids) < MIN_UNIVERSE:
                continue
            bench = float(np.mean([idx_map[c] for c in valid_cids]))
            rec = {"jy": jy, "jm": jm, "h": h, "bench": bench}
            for cfg in CONFIGS:
                cand = [(scores[cfg][i], idx_map[r["cid"]]) for i, r in enumerate(rows)
                        if r["cid"] in valid_cids]
                cand.sort(key=lambda t: -t[0])
                for N in TOP_NS:
                    top = [v for _, v in cand[:N]]
                    ret = float(np.mean(top))
                    rec[f"{cfg}_top{N}"] = ret
                    rec[f"{cfg}_top{N}_exc"] = ret - bench
            port_rows.append(rec)

        # IC (سپرمن با بازده ۳ ماهه)
        xs = {cfg: [] for cfg in CONFIGS}
        for i, r in enumerate(rows):
            v = r.get("fwd3")
            if v is None or not np.isfinite(v):
                continue
            for cfg in CONFIGS:
                xs[cfg].append((scores[cfg][i], v))
        for cfg in CONFIGS:
            arr = np.array(xs[cfg], float)
            if len(arr) >= 20:
                s_rank = pd.Series(arr[:, 0]).rank()
                y_rank = pd.Series(arr[:, 1]).rank()
                ic = float(s_rank.corr(y_rank))
                if not math.isnan(ic):
                    ic_recs.append({"jy": jy, "jm": jm, "cfg": cfg, "ic": ic})

    port = pd.DataFrame(port_rows)
    ic_df = pd.DataFrame(ic_recs)
    port.to_csv(os.path.join(OUT_DIR, "weights_portfolio.csv"), index=False, encoding="utf-8-sig")

    periods = [("train", 1399, TRAIN_MAX_JY, "درون‌نمونه ۹۹-۰۲"),
               ("test", TRAIN_MAX_JY + 1, 1404, "برون‌نمونه ۰۳-۰۴"),
               ("all", 1399, 1404, "کل دوره ۹۹-۰۴")]

    summary = {"configs": {k: {kk: vv for kk, vv in v.items()} for k, v in CONFIGS.items()},
               "n_dates": n_dates, "periods": {}}

    print()
    print("=" * 96)
    print(f"مقایسه‌ی وزن‌ها | {n_dates} ماه | جهان = فیلتر فاز ۱ | بنچمارک = میانگین هم‌وزن")
    print("=" * 96)

    for pid, y_lo, y_hi, plabel in periods:
        print(f"\n■ {plabel}")
        summary["periods"][pid] = {}
        for h in HORIZONS:
            ph = port[(port.h == h) & (port.jy >= y_lo) & (port.jy <= y_hi)]
            if not len(ph):
                continue
            print(f"  ─ افق {h} ماهه ({len(ph)} ریبالنس، غیرهم‌پوشان {len(ph.iloc[::h])}) ")
            summary["periods"][pid][h] = {}
            for cfg in CONFIGS:
                summary["periods"][pid][h][cfg] = {}
                for N in TOP_NS:
                    exc = ph[f"{cfg}_top{N}_exc"]
                    tot = port_compound(ph, f"{cfg}_top{N}", h)
                    ben = port_compound(ph, "bench", h)
                    hit = float((exc > 0).mean())
                    summary["periods"][pid][h][cfg][f"top{N}"] = {
                        "mean_excess": float(exc.mean()), "hit_rate": hit,
                        "nonoverlap_total": tot, "nonoverlap_bench": ben}
                    print(f"    {cfg:>3} Top{N:<3} اضافه‌بازده {exc.mean()*100:>6.1f}%/ماه | برد {hit*100:>3.0f}%"
                          f" | مجموع {tot*100:>6.0f}% vs بنچمارک {ben*100:>6.0f}%")

        # IC per config
        for cfg in CONFIGS:
            sub = ic_df[(ic_df.cfg == cfg) & (ic_df.jy >= y_lo) & (ic_df.jy <= y_hi)]
            if len(sub):
                icm = float(sub.ic.mean())
                t = ic_tstat(sub.ic)
                pp = float((sub.ic > 0).mean())
                summary["periods"][pid].setdefault("ic", {})[cfg] = {
                    "mean": icm, "t": t, "pct_pos": pp, "n": len(sub)}
                print(f"  IC {cfg}: {icm:+.3f} | t={t:+.1f} | مثبت در {pp*100:.0f}%")

    # برنده‌ی برون‌نمونه
    if "test" in summary["periods"]:
        t6 = summary["periods"]["test"].get(6, {})
        for N in TOP_NS:
            o = t6.get("old", {}).get(f"top{N}", {})
            nw = t6.get("new", {}).get(f"top{N}", {})
            if o and nw:
                better = nw["mean_excess"] > o["mean_excess"]
                print(f"\nبرون‌نمونه ۶ماهه Top{N}: new {'بهتر از' if better else 'ضعیف‌تر از'} old"
                      f" ({nw['mean_excess']*100:+.1f}% vs {o['mean_excess']*100:+.1f}%)")

    with open(os.path.join(OUT_DIR, "weights_comparison.json"), "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
    print(f"\nخروجی‌ها در {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
