# -*- coding: utf-8 -*-
"""
بک‌تست فاز ۲ — تست فاکتورهای v3.2 (ترازنامه/جریان نقدی/حاشیه‌های واقعی)

داده: ۱۰ نماد بک‌فیل‌شده (سباقر، شمواد، غکورش، غپینو، کاما، غمینو، دجابر،
دلقما، غاذر، قاسم) که برای تمام گزارش‌های ۱۳۹۸+ ستون‌های درآمد/ترازنامه/
جریان نقدی/FYPrev کامل شده‌اند.

محدودیت مهم: مقطعِ تنها ۱۰ نمایی است → ICها نوفه‌ی بیشتری دارند و نتیجه‌ها
«جهت‌دار» تلقی می‌شوند نه قطعی. هدف: تشخیص اینکه کدام فاکتور v3.2 اصلاً
سیگنال دارد و وزنش در ویو توجیه می‌شود یا نه.

تست‌ها:
  ۱) IC تک‌تک فاکتورهای جدید: ROE، اهرم(وارونه)، نسبت جاری، کیفیت نقدی،
     P/B(وارونه)، حاشیه عملیاتی۱۲م، حاشیه خالص۱۲م، پوشش بهره، کیفیت سود(وارونه)
  ۲) IC و پرتفوی: score_v1 (فاز ۱ = وزن‌های v3.4 بدون فاکتورهای v3.2)
     در برابر score_v2 (کامل: +ROE 5, CC 4, اهرم 4, نسبت جاری 3, P/B 3)
  ۳) پرتفوی: Top-5 هر امتیاز در برابر میانگین هم‌وزن ۱۰ نماد، افق ۳ و ۶ ماهه
"""
import json
import math
import os
import sys
from bisect import bisect_right

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from backtest import (  # noqa: E402
    OUT_DIR,
    PUBLISH_DELAY_DAYS,
    add_months,
    build_structures,
    company_factors,
    jalali_month_end_g,
    load_data,
    norm_op,
    parse_jalali,
    pct_rank,
    jalali_to_g,
)
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyodbc  # noqa: E402
from datetime import timedelta  # noqa: E402

IMPORTANT = ["شمواد", "سباقر", "غکورش", "غپینو", "کاما", "غمینو",
             "دجابر", "دلقما", "غاذر", "قاسم"]
HORIZONS = [3, 6]
MIN_CROSS_N = 6
TRAIN_MAX_JY = 1402

CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};SERVER="
    + os.environ["DB_SERVER"]
    + ";DATABASE="
    + os.environ["DB_NAME"]
    + ";UID="
    + os.environ["DB_USER"]
    + ";PWD="
    + os.environ["DB_PASSWORD"]
    + ";TrustServerCertificate=yes;"
)

NEW_FACTOR_NAMES = {
    "roe": "ROE", "lev": "اهرم(ضد)", "cr": "نسبت جاری", "cc": "کیفیت نقدی",
    "pb": "P/B(ضد)", "om12": "حاشیه عملیاتی۱۲م", "nm12": "حاشیه خالص۱۲م",
    "ic": "پوشش بهره", "eq": "کیفیت سود(ضد)", "ps": "P/S(ضد)",
}


def load_v2_reports():
    """miandore2 با همه‌ی ستون‌های v3.2 + نگاشت نام→CompanyID"""
    conn = pyodbc.connect(CONN_STR)
    cur = conn.cursor()
    qmarks = ",".join("?" * len(IMPORTANT))
    cur.execute(
        f"SELECT DISTINCT CompanyID, CompanyName FROM dbo.miandore2 WHERE CompanyName IN ({qmarks})",
        IMPORTANT,
    )
    name2cid = {n: c for c, n in cur.fetchall()}
    df = pd.read_sql(
        """
        SELECT CompanyID, CompanyName, ReportDate, Num1_Value1, Product1,
               OperatingProfitNew, OperatingProfitLastYear, FinanceCostsNew,
               OtherNonOpNew, RevenueNew, RevenueLastYear,
               NetProfitAmount, NetProfitAmountLY, NetProfitAmountFYPrev,
               OperatingProfitFYPrev, RevenueFYPrev,
               OperatingCashFlow, OperatingCashFlowLY, OperatingCashFlowFYPrev,
               TotalAssets, CurrentAssets, TotalLiabilities, CurrentLiabilities, TotalEquity
        FROM dbo.miandore2
        WHERE CompanyID IS NOT NULL
        """,
        conn,
    )
    conn.close()
    num_cols = [c for c in df.columns if c not in ("CompanyID", "CompanyName", "ReportDate")]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df, name2cid


def build_rep_v2(df):
    """ردیف‌های گزارش با همه‌ی فیلدهای v3.2 (مرتب بر اساس kidx)"""
    out = {}
    for r in df.itertuples(index=False):
        pj = parse_jalali(r.ReportDate)
        if pj is None:
            continue
        jy, jm, jd = pj
        g = jalali_to_g(jy, jm, jd)
        if g is None:
            continue

        def f(x):
            return float(getattr(r, x)) if pd.notna(getattr(r, x)) else np.nan

        eps, p1 = f("Num1_Value1"), f("Product1")
        rev, rev_ly = f("RevenueNew"), f("RevenueLastYear")
        row = {
            "jy": jy, "jm": jm, "kidx": jy * 12 + jm,
            "pub": (g + timedelta(days=PUBLISH_DELAY_DAYS)).toordinal(),
            "eps": eps, "p1": p1, "rev": rev, "rev_ly": rev_ly,
            "fin": f("FinanceCostsNew"), "nonop": f("OtherNonOpNew"),
            "op_abs": norm_op(f("OperatingProfitNew"), rev, eps, p1),
            "op_ly_abs": norm_op(f("OperatingProfitLastYear"), rev_ly, eps, p1),
            "op_raw": f("OperatingProfitNew"), "op_ly_raw": f("OperatingProfitLastYear"),
            # v3.2
            "npa": f("NetProfitAmount"), "npa_ly": f("NetProfitAmountLY"),
            "npa_fyp": f("NetProfitAmountFYPrev"), "op_fyp": f("OperatingProfitFYPrev"),
            "rev_fyp": f("RevenueFYPrev"),
            "ocf": f("OperatingCashFlow"), "ocf_ly": f("OperatingCashFlowLY"),
            "ocf_fyp": f("OperatingCashFlowFYPrev"),
            "ta": f("TotalAssets"), "ca": f("CurrentAssets"),
            "tl": f("TotalLiabilities"), "tcl": f("CurrentLiabilities"),
            "te": f("TotalEquity"),
        }
        out.setdefault(r.CompanyID, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda x: x["kidx"])
    return out


def v32_factors(f, A):
    """فاکتورهای v3.2 از آخرین گزارشِ منتشرشده (فرمول‌های ویو + گاردها)"""
    def ttm(cur, fyp, ly, jm):
        if not all(np.isfinite(x) for x in (cur, fyp, ly)):
            return np.nan
        return cur if jm == 12 else cur + fyp - ly

    sr_np = ttm(A["npa"], A["npa_fyp"], A["npa_ly"], A["jm"])
    sr_op = ttm(A["op_raw"], A["op_fyp"], A["op_ly_raw"], A["jm"])
    sr_rev = ttm(A["rev"], A["rev_fyp"], A["rev_ly"], A["jm"])
    sr_ocf = ttm(A["ocf"], A["ocf_fyp"], A["ocf_ly"], A["jm"])

    # ROE (±۳۰۰٪)
    if np.isfinite(sr_np) and np.isfinite(A["te"]) and A["te"] > 0:
        roe = sr_np / A["te"] * 100.0
        f["roe"] = roe if abs(roe) <= 300.0 else np.nan
    else:
        f["roe"] = np.nan

    # اهرم (≤۵۰)
    if np.isfinite(A["tl"]) and A["tl"] >= 0 and np.isfinite(A["te"]) and A["te"] > 0:
        lev = A["tl"] / A["te"]
        f["lev"] = lev if lev <= 50.0 else np.nan
    else:
        f["lev"] = np.nan

    # نسبت جاری (≤۱۵)
    if np.isfinite(A["ca"]) and A["ca"] >= 0 and np.isfinite(A["tcl"]) and A["tcl"] > 0:
        cr = A["ca"] / A["tcl"]
        f["cr"] = cr if cr <= 15.0 else np.nan
    else:
        f["cr"] = np.nan

    # کیفیت نقدی (−۲..۵، سود مثبت)
    if np.isfinite(sr_ocf) and np.isfinite(sr_np) and sr_np > 0:
        cc = sr_ocf / sr_np
        f["cc"] = cc if -2.0 <= cc <= 5.0 else np.nan
    else:
        f["cc"] = np.nan

    # P/B = PE × ROE/۱۰۰ (معتبر ≤۳۰؛ نامعتبر→NaN ولی پرچم)
    pe = f.get("pe")
    if np.isfinite(f.get("roe", np.nan)) and f["roe"] > 0 and pe is not None and np.isfinite(pe):
        pb = pe * f["roe"] / 100.0
        f["pb"] = pb if pb <= 30.0 else np.nan
    else:
        f["pb"] = np.nan
    f["pb_invalid"] = not (np.isfinite(f.get("pb", np.nan)) and f["pb"] > 0)

    # حاشیه‌های ۱۲ماهه واقعی (کراپ کلید رتبه‌بندی مثل ویو: OM ±۸۰، NM ±۶۰)
    if np.isfinite(sr_op) and np.isfinite(sr_rev) and sr_rev != 0:
        m = sr_op / abs(sr_rev) * 100.0
        f["om12"] = m if abs(m) <= 200.0 else np.nan
    else:
        f["om12"] = np.nan
    if np.isfinite(sr_np) and np.isfinite(sr_rev) and sr_rev != 0:
        m = sr_np / abs(sr_rev) * 100.0
        f["nm12"] = m if abs(m) <= 200.0 else np.nan
    else:
        f["nm12"] = np.nan
    return f


def score_full(rows, include_v32):
    """امتیاز با وزن‌های v3.4؛ include_v32=True فاکتورهای v3.2 را هم می‌افزاید"""
    n = len(rows)

    def col(k, default=np.nan):
        return np.array([r.get(k, default) if r.get(k) is not None and np.isfinite(r.get(k, default)) else np.nan for r in rows])

    vals = {
        "sg12": np.clip(col("sg12"), -150, 150), "sg3": np.clip(col("sg3"), -150, 150),
        "rg": np.clip(col("rg"), -200, 200), "opg": np.clip(col("opg"), -250, 250),
        "npg": np.clip(col("npg"), -300, 300), "om": np.clip(col("om"), -80, 80),
        "nm": np.clip(col("nm"), -60, 60), "mt": np.clip(col("mt"), -25, 25),
        "eq": np.clip(col("eq"), 0, 150),
    }
    ic_v = col("ic")
    vals["ic"] = np.where(np.isfinite(ic_v) & (ic_v <= 0), -999999.0, np.where(ic_v > 20, 20.0, ic_v))
    vals["pe"] = col("pe")
    vals["ps"] = col("ps")
    vals["liq"] = col("liq")
    vals["stability"] = col("stability")
    vals["vol"] = col("vol")
    vals["mom"] = col("mom")

    r_sg12 = pct_rank(vals["sg12"]); r_sg3 = pct_rank(vals["sg3"])
    r_rg = pct_rank(vals["rg"]); r_opg = pct_rank(vals["opg"]); r_npg = pct_rank(vals["npg"])
    r_om = pct_rank(vals["om"]); r_nm = pct_rank(vals["nm"]); r_mt = pct_rank(vals["mt"])
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

    growth = (10 * r_sg12 + 6 * r_sg3 + 5 * r_rg + 5 * r_opg + 10 * r_npg)
    prof = (4 * r_om + 4 * r_nm + 3 * r_mt + 3 * r_ic + 4 * r_eq)  # v3.5: NetMargin 3→4
    valn = 11 * r_pe + 3 * r_ps
    markt = 6 * r_lq + 1 * r_st + 5 * r_lv + 1 * r_mo

    if include_v32:
        r_roe = pct_rank(col("roe"))
        r_cc = pct_rank(col("cc"))
        r_lev = pct_rank(col("lev"), invert=True)
        r_cr = pct_rank(col("cr"))
        pbv = col("pb")
        pb_valid = np.isfinite(pbv) & (pbv > 0)
        r_pb = np.where(pb_valid, pct_rank(pbv, invert=True), 0.0)
        prof = prof + 6 * r_roe + 2 * r_cc   # v3.5
        markt = markt + 2 * r_lev + 2 * r_cr  # v3.5
        valn = valn + 2 * r_pb                # v3.5

    pen_g = np.zeros(n)
    pen_g += 6.0 * (np.isfinite(vals["sg12"]) & (vals["sg12"] < -20))
    pen_g += 5.0 * (np.isfinite(vals["opg"]) & (vals["opg"] < -25))
    ttm_np = np.array([r["ttm_np"] for r in rows])
    pen_p = 10.0 * (np.isfinite(ttm_np) & (ttm_np < 0))
    pen_p += 4.0 * (np.isfinite(vals["ic"]) & (vals["ic"] < 1.5))
    pen_p += 3.0 * (np.isfinite(vals["mt"]) & (vals["mt"] < -2))
    pen_p += np.where(np.isfinite(vals["eq"]), np.clip((vals["eq"] - 20) / 80, 0, 1) * 8.0, 0.0)
    pe_inv = np.array([r["pe_invalid"] for r in rows], bool)
    pen_v = 8.0 * pe_inv

    dq = np.array([r["dq"] for r in rows])
    return dq * (np.maximum(growth - pen_g, 0) + np.maximum(prof - pen_p, 0)
                 + np.maximum(valn - pen_v, 0) + np.maximum(markt, 0))


def ic_t(a):
    a = np.asarray(a, float)
    if len(a) < 3 or a.std(ddof=1) == 0:
        return 0.0
    return float(a.mean() / (a.std(ddof=1) / math.sqrt(len(a))))


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("بارگذاری...", flush=True)
    reports, sales, market = load_data()
    df2, name2cid = load_v2_reports()
    rep_v2 = build_rep_v2(df2)
    _, sales_by_cid, price_by_cid, _ = build_structures(reports, sales, market)
    cids = [name2cid[n] for n in IMPORTANT if n in name2cid]
    print(f"نمادهای فاز ۲: {len(cids)}", flush=True)

    dates = []
    jy, jm = 1399, 1
    while (jy, jm) <= (1404, 12):
        dates.append((jy, jm, jalali_month_end_g(jy, jm)))
        jy, jm = add_months(jy, jm, 1)

    port_rows, ic_recs = [], []
    factor_cols = list(NEW_FACTOR_NAMES) + ["score_v1", "score_v2"]
    cov = {k: 0 for k in NEW_FACTOR_NAMES}

    for jy, jm, gdate in dates:
        D_ord = gdate.toordinal()
        D_jkey = jy * 12 + jm
        rows = []
        for cid in cids:
            rep_rows = rep_v2.get(cid)
            price = price_by_cid.get(cid)
            if not rep_rows or price is None:
                continue
            pub_list = [r["pub"] for r in rep_rows]
            sk, sv = sales_by_cid.get(cid, (None, None))
            f = company_factors(rep_rows, pub_list, sk, sv, price, D_ord, D_jkey)
            if f is None:
                continue
            f["dq"] = 0.0  # داخل score_full با compute_dq واقعی جایگزین می‌شود
            from backtest import compute_dq
            f["dq"] = compute_dq(f)
            n_avail = bisect_right(pub_list, D_ord)
            if n_avail:
                f = v32_factors(f, rep_rows[n_avail - 1])
            else:
                for k in NEW_FACTOR_NAMES:
                    f[k] = np.nan
                f["pb_invalid"] = True
            # بازده آینده
            i0 = bisect_right(price["dates"], D_ord) - 1
            base = price["idx"][i0]
            for h in HORIZONS:
                hy, hm = add_months(jy, jm, h)
                tgt = jalali_month_end_g(hy, hm).toordinal()
                i1 = bisect_right(price["dates"], tgt) - 1
                ok = i1 >= 0 and (tgt - int(price["dates"][i1])) <= 100
                f[f"fwd{h}"] = price["idx"][i1] / base - 1.0 if ok and base > 0 else np.nan
            f["cid"] = cid
            rows.append(f)
        if len(rows) < MIN_CROSS_N:
            continue

        s1 = score_full(rows, include_v32=False)
        s2 = score_full(rows, include_v32=True)
        for i, r in enumerate(rows):
            r["score_v1"], r["score_v2"] = s1[i], s2[i]

        for k in NEW_FACTOR_NAMES:
            n_have = sum(1 for r in rows if r.get(k) is not None and np.isfinite(r.get(k)))
            if n_have >= MIN_CROSS_N:
                cov[k] += 1

        y = np.array([r.get("fwd3", np.nan) for r in rows])
        valid = np.isfinite(y)
        if valid.sum() >= MIN_CROSS_N:
            yv = pd.Series(y[valid]).rank()
            for c in factor_cols:
                x = np.array([r.get(c, np.nan) for r in rows])[valid]
                m = np.isfinite(x)
                if m.sum() >= MIN_CROSS_N and len(set(x[m])) > 1:
                    ic = float(pd.Series(x[m]).rank().corr(yv[m]))
                    if not math.isnan(ic):
                        ic_recs.append({"jy": jy, "jm": jm, "factor": c, "ic": ic})

        for h in HORIZONS:
            vals = [(r["symbol"] if "symbol" in r else r["cid"], r.get(f"fwd{h}", np.nan)) for r in rows]
            vals = [(s, v) for s, v in vals if np.isfinite(v)]
            if len(vals) < MIN_CROSS_N:
                continue
            bench = float(np.mean([v for _, v in vals]))
            fwd_map = dict(vals)
            rec = {"jy": jy, "jm": jm, "h": h, "bench": bench}
            for sc in ("score_v1", "score_v2"):
                cand = sorted(((r[sc], fwd_map[r["cid"]]) for r in rows if r["cid"] in fwd_map),
                              key=lambda t: -t[0])
                top5 = [v for _, v in cand[:5]]
                rec[f"{sc}_top5"] = float(np.mean(top5))
                rec[f"{sc}_top5_exc"] = rec[f"{sc}_top5"] - bench
            port_rows.append(rec)

    ic_df = pd.DataFrame(ic_recs)
    port = pd.DataFrame(port_rows)
    ic_df.to_csv(os.path.join(OUT_DIR, "phase2_ic.csv"), index=False, encoding="utf-8-sig")
    port.to_csv(os.path.join(OUT_DIR, "phase2_portfolio.csv"), index=False, encoding="utf-8-sig")

    summary = {"n_symbols": len(cids), "factors": {}, "portfolios": {}}
    print()
    print("=" * 80)
    print(f"فاز ۲ | {len(cids)} نماد کامل | مقطع ~۱۰تایی | توجه: نوفه‌ی بالا")
    print("=" * 80)
    print(f"\n{'فاکتور':>18}{'IC':>8}{'t':>7}{'%مثبت':>7}{'ماه‌های قابل‌محاسبه':>12}")
    for k, label in NEW_FACTOR_NAMES.items():
        sub = ic_df[ic_df.factor == k] if len(ic_df) else []
        if len(sub):
            arr = sub.ic.to_numpy()
            inv = "(ضد)" in label
            t = ic_t(arr)
            summary["factors"][k] = {"mean": float(arr.mean()), "t": t,
                                     "pct_pos": float((arr > 0).mean()), "n": len(arr)}
            print(f"{label:>18}{arr.mean():>8.3f}{t:>7.2f}{(arr > 0).mean()*100:>6.0f}%{cov[k]:>10}/{len(sub)}")
    for sc, label in [("score_v1", "امتیاز فاز۱"), ("score_v2", "امتیاز کامل v3.2")]:
        sub = ic_df[ic_df.factor == sc] if len(ic_df) else []
        if len(sub):
            arr = sub.ic.to_numpy()
            t = ic_t(arr)
            summary["factors"][sc] = {"mean": float(arr.mean()), "t": t,
                                      "pct_pos": float((arr > 0).mean()), "n": len(arr)}
            print(f"{label:>18}{arr.mean():>8.3f}{t:>7.2f}{(arr > 0).mean()*100:>6.0f}%")

    for h in HORIZONS:
        ph = port[port.h == h]
        if not len(ph):
            continue
        print(f"\n--- افق {h} ماهه | Top-5 در برابر میانگین هم‌وزن ۱۰ نماد ---")
        summary["portfolios"][h] = {}
        for sc in ("score_v1", "score_v2"):
            ex = ph[f"{sc}_top5_exc"]
            sub = ph.iloc[::h]
            tot = float(np.prod(1 + sub[f"{sc}_top5"]) - 1)
            ben = float(np.prod(1 + sub["bench"]) - 1)
            summary["portfolios"][h][sc] = {"mean_excess": float(ex.mean()),
                                            "hit": float((ex > 0).mean()),
                                            "total": tot, "bench": ben}
            print(f"  {sc}: اضافه‌بازده {ex.mean()*100:+.1f}%/دوره | برد {(ex > 0).mean()*100:.0f}%"
                  f" | مجموع {tot*100:.0f}% vs بنچمارک {ben*100:.0f}%")

    with open(os.path.join(OUT_DIR, "phase2_results.json"), "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
    print(f"\nخروجی‌ها در {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
