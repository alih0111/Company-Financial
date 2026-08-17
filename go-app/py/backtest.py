# -*- coding: utf-8 -*-
"""
بک‌تست فاز ۱ برای اعتبارسنجی QuantScore (نسخه v3.x از vw_AIStockMetrics)

فاز ۱ = فقط فاکتورهایی که از داده‌ی تاریخی موجود قابل محاسبه‌اند:
  - miandore2 (گزارش‌های فصلی تجمعی از ۱۳۹۸): Product1, EPS, OperatingProfit*, Revenue*, FinanceCosts, OtherNonOp
  - mahane (فروش ماهانه)
  - MarketPriceHistory (قیمت روزانه)
فاکتورهای v3.2 (ROE/CashConversion/اهرم/نسبت جاری/PB) به‌خاطر نبود داده‌ی
تاریخی ترازنامه در این فاز نیستند — بعد از بک‌فیل گزارش‌های سالانه اضافه می‌شوند.

روش:
  - rebalance در پایان هر ماه شمسی ۱۳۹۹/۰۱ تا ۱۴۰۴/۱۲
  - point-in-time: گزارش فقط وقتی در دسترس است که ۴۵ روز از پایان دوره‌اش گذشته باشد
  - رتبه‌بندی صدکی درون‌تاریخ (همان فرمول midrank ویو) + وزن‌ها/جریمه‌های ویو
  - بازده آینده ۳/۶/۱۲ ماهه با قیمت تعدیل‌شده (خنثی‌سازی افزایش سرمایه از روی
    گپ شبانه FirstPrice/Close)
  - پرتفوی Top10/Top20 هم‌وزن در برابر میانگین هم‌وزن کل جهان
  - IC (همبستگی رتبه‌ای اسپیرمن) هر فاکتور با بازده ۳ ماهه آینده

محدودیت‌ها (صادقانه):
  - survivorship: فقط شرکت‌های موجود در دیتابیس فعلی (حذف‌شده‌ها نیستند)
  - تأخیر CODAL ساده‌شده = ۴۵ روز برای همه‌ی گزارش‌ها
  - سود نقدی تقسیمی در بازده لحاظ نشده (فقط خنثی‌سازی افزایش سرمایه)
  - فاکتورهای ترازنامه‌ای/نقدی غایب‌اند → حداکثر امتیاز ≈ DQ×۸۱ به‌جای DQ×۱۰۴
"""
import json
import math
import os
import sys
from bisect import bisect_right
from datetime import date, timedelta

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

for _line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"), encoding="utf-8-sig"):
    _line = _line.strip()
    if _line and "=" in _line and not _line.startswith("#"):
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k, _v)

import jdatetime  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyodbc  # noqa: E402

# ----------------------------------------------------------------------------
# تنظیمات
# ----------------------------------------------------------------------------
PUBLISH_DELAY_DAYS = 45
START_JY, START_JM = 1399, 1
END_JY, END_JM = 1404, 12
HORIZONS = [3, 6, 12]
TOP_NS = [10, 20]
MIN_UNIVERSE = 30
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backtest_output")

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


# ----------------------------------------------------------------------------
# تقویم جلالی
# ----------------------------------------------------------------------------
def jalali_month_end_g(jy, jm):
    """تاریخ میلادی پایان ماه شمسی"""
    if jm <= 6:
        d = 31
    elif jm <= 11:
        d = 30
    else:
        d = (jdatetime.date(jy + 1, 1, 1) - jdatetime.timedelta(days=1)).day
    return jdatetime.date(jy, jm, d).togregorian()


def add_months(jy, jm, h):
    t = (jy * 12 + jm - 1) + h
    return t // 12, t % 12 + 1


def jalali_now_g_to_key(gdate):
    """تقریب «الان شمسی» به‌صورت jy*12+jm (مثل ویو)"""
    j = jdatetime.date.fromgregorian(date=gdate)
    return j.year * 12 + j.month


_JALALI_CACHE = {}


def parse_jalali(s):
    """'1398/06/31' -> (jy, jm, jday) یا None"""
    if s is None:
        return None
    if s in _JALALI_CACHE:
        return _JALALI_CACHE[s]
    try:
        parts = str(s).replace("-", "/").strip().split("/")
        out = (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        out = None
    _JALALI_CACHE[s] = out
    return out


def jalali_to_g(jy, jm, jd):
    try:
        return jdatetime.date(jy, jm, jd).togregorian()
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# بارگذاری داده
# ----------------------------------------------------------------------------
def load_data():
    conn = pyodbc.connect(CONN_STR)
    reports = pd.read_sql(
        """
        SELECT CompanyID, CompanyName, ReportDate, Num1_Value1, Product1,
               OperatingProfitNew, OperatingProfitLastYear, FinanceCostsNew,
               OtherNonOpNew, RevenueNew, RevenueLastYear
        FROM dbo.miandore2
        WHERE CompanyID IS NOT NULL
        """,
        conn,
    )
    sales = pd.read_sql(
        """
        SELECT CompanyID, ReportDate, Value3
        FROM dbo.mahane
        WHERE CompanyID IS NOT NULL AND TRY_CONVERT(FLOAT, Value3) IS NOT NULL
        """,
        conn,
    )
    market = pd.read_sql(
        """
        SELECT CompanyID, Symbol, GregorianDate, ClosingPrice, FirstPrice,
               TradeValue
        FROM dbo.MarketPriceHistory
        WHERE CompanyID IS NOT NULL AND GregorianDate IS NOT NULL
          AND TRY_CONVERT(FLOAT, ClosingPrice) IS NOT NULL
        """,
        conn,
    )
    conn.close()

    for df, cols in ((reports, ["Num1_Value1", "Product1", "OperatingProfitNew",
                                "OperatingProfitLastYear", "FinanceCostsNew",
                                "OtherNonOpNew", "RevenueNew", "RevenueLastYear"]),
                     (sales, ["Value3"]),
                     (market, ["ClosingPrice", "FirstPrice", "TradeValue"])):
        for c in cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return reports, sales, market


def norm_op(op_raw, rev, eps, p1):
    """یکسان‌سازی واحد سود عملیاتی (per-share → مطلق) مثل ویو؛ فقط با داده‌ی خود سطر"""
    if op_raw is None or (isinstance(op_raw, float) and math.isnan(op_raw)):
        return np.nan
    eps_ok = eps is not None and not math.isnan(eps) and eps > 0
    p1_ok = p1 is not None and not math.isnan(p1) and p1 > 0
    if rev is not None and not math.isnan(rev) and abs(rev) > 0 and eps_ok and p1_ok:
        if abs(op_raw) < 0.001 * abs(rev):
            return op_raw * p1 / eps
        return op_raw
    if eps_ok and p1_ok:
        if 0.05 * p1 > abs(op_raw) >= 0.05 * eps and abs(op_raw) < 100.0 * eps:
            return op_raw * p1 / eps
    return op_raw


def build_structures(reports, sales, market):
    """ساختارهای per-company برای دسترسی سریع point-in-time"""
    rep_by_cid = {}
    for r in reports.itertuples(index=False):
        pj = parse_jalali(r.ReportDate)
        if pj is None:
            continue
        jy, jm, jd = pj
        g = jalali_to_g(jy, jm, jd)
        if g is None:
            continue
        eps = float(r.Num1_Value1) if pd.notna(r.Num1_Value1) else np.nan
        p1 = float(r.Product1) if pd.notna(r.Product1) else np.nan
        op_raw = float(r.OperatingProfitNew) if pd.notna(r.OperatingProfitNew) else np.nan
        op_ly_raw = float(r.OperatingProfitLastYear) if pd.notna(r.OperatingProfitLastYear) else np.nan
        rev = float(r.RevenueNew) if pd.notna(r.RevenueNew) else np.nan
        rev_ly = float(r.RevenueLastYear) if pd.notna(r.RevenueLastYear) else np.nan
        fin = float(r.FinanceCostsNew) if pd.notna(r.FinanceCostsNew) else np.nan
        nonop = float(r.OtherNonOpNew) if pd.notna(r.OtherNonOpNew) else np.nan
        row = {
            "jy": jy, "jm": jm, "kidx": jy * 12 + jm,
            "pub": (g + timedelta(days=PUBLISH_DELAY_DAYS)).toordinal(),
            "eps": eps, "p1": p1, "rev": rev, "rev_ly": rev_ly,
            "fin": fin, "nonop": nonop,
            "op_abs": norm_op(op_raw, rev, eps, p1),
            "op_ly_abs": norm_op(op_ly_raw, rev_ly, eps, p1),
        }
        rep_by_cid.setdefault(r.CompanyID, []).append(row)
    for rows in rep_by_cid.values():
        rows.sort(key=lambda x: x["kidx"])

    sales_by_cid = {}
    for r in sales.itertuples(index=False):
        pj = parse_jalali(r.ReportDate)
        if pj is None:
            continue
        kidx = pj[0] * 12 + pj[1]
        d = sales_by_cid.setdefault(r.CompanyID, {})
        v = float(r.Value3)
        d[kidx] = d.get(kidx, 0.0) + v  # اگر ماه تکراری بود جمع می‌شود (نادر)
    sales_by_cid = {
        cid: (np.array(sorted(d.keys())), np.array([d[k] for k in sorted(d.keys())], float))
        for cid, d in sales_by_cid.items()
    }

    market = market.sort_values(["CompanyID", "GregorianDate", "TradeValue"])
    market = market.drop_duplicates(["CompanyID", "GregorianDate"], keep="last")
    price_by_cid = {}
    sym_by_cid = {}
    for cid, g in market.groupby("CompanyID", sort=False):
        g = g.sort_values("GregorianDate")
        dates = np.array([d.toordinal() for d in g.GregorianDate], dtype=np.int64)
        close = g.ClosingPrice.to_numpy(float)
        first = g.FirstPrice.to_numpy(float)
        tv = np.nan_to_num(g.TradeValue.to_numpy(float), nan=0.0)
        prev_close = np.concatenate([[np.nan], close[:-1]])
        with np.errstate(invalid="ignore", divide="ignore"):
            overnight = np.where(prev_close > 0, first / prev_close, np.nan)
            raw_ret = np.where(prev_close > 0, close / prev_close - 1.0, 0.0)
            ev = np.isfinite(overnight) & (overnight < 0.85)
        adj_ret = np.where(ev & np.isfinite(first) & (first > 0),
                           close / np.where(first > 0, first, np.nan) - 1.0, raw_ret)
        # FirstPrice غایب ولی افت بزرگ قیمت پایانی → احتمالاً افزایش سرمایه
        ev2 = ~np.isfinite(overnight) & (raw_ret < -0.15)
        adj_ret = np.where(ev2, 0.0, adj_ret)
        adj_ret = np.where(np.isfinite(adj_ret), adj_ret, 0.0)
        adj_idx = np.cumprod(1.0 + adj_ret)
        price_by_cid[cid] = {"dates": dates, "close": close, "idx": adj_idx,
                             "tv": tv, "ret": adj_ret * 100.0}
        sym_by_cid[cid] = (g.Symbol.iloc[-1] if pd.notna(g.Symbol.iloc[-1]) else "")
    return rep_by_cid, sales_by_cid, price_by_cid, sym_by_cid


# ----------------------------------------------------------------------------
# رتبه‌بندی صدکی (همان فرمول midrank ویو)
# ----------------------------------------------------------------------------
def pct_rank(vals, invert=False, neutral=0.30):
    v = np.asarray(vals, float)
    out = np.full(v.shape, neutral)
    m = np.isfinite(v)
    x = v[m]
    n = len(x)
    if n >= 2:
        order = np.argsort(x, kind="mergesort")
        sx = x[order]
        left = np.searchsorted(sx, sx, side="left")
        right = np.searchsorted(sx, sx, side="right")
        p = (2.0 * left + (right - left - 1)) / (2.0 * (n - 1))
        ranks = np.empty(n)
        ranks[order] = p
        if invert:
            ranks = 1.0 - ranks
        out[m] = ranks
    elif n == 1:
        out[m] = 0.5
    return out


def guard_ratio(a, b, lo, hi):
    """نسبت a/b فقط اگر هر دو finite و غیرصفر و |نتیجه| در بازه باشد؛ else NaN"""
    if not (np.isfinite(a) and np.isfinite(b)) or b == 0:
        return np.nan
    r = a / b
    return r if lo <= abs(r) <= hi else np.nan  # noqa: SIM108


# ----------------------------------------------------------------------------
# فاکتورهای یک شرکت در تاریخ D
# ----------------------------------------------------------------------------
def company_factors(rep_rows, pub_ord_list, sales_keys, sales_vals, price, D_ord, D_jkey):
    """خروجی: دیکشنری فاکتورهای خام یا None اگر شرکت در جهان نیست"""
    if price is None:
        return None
    i = bisect_right(price["dates"], D_ord) - 1
    if i < 0:
        return None
    p_close = price["close"][i]
    if not np.isfinite(p_close) or p_close <= 0:
        return None

    # --- آخرین گزارشِ منتشرشده ---
    n_avail = bisect_right(pub_ord_list, D_ord)
    if n_avail == 0:
        return None
    A = rep_rows[n_avail - 1]
    by_kidx = {r["kidx"]: r for r in rep_rows[:n_avail]}

    def get(jy, jm):
        return by_kidx.get(jy * 12 + jm)

    fy1 = get(A["jy"] - 1, 12)
    lyp = get(A["jy"] - 1, A["jm"])
    fy2 = get(A["jy"] - 2, 12)
    lyp2 = get(A["jy"] - 2, A["jm"])

    report_age_m = D_jkey - A["kidx"]

    f = {
        "eps": A["eps"], "p1": A["p1"],
        "price": p_close,
        "report_age_m": report_age_m,
        "price_age_d": D_ord - int(price["dates"][i]),
        "n_profit_reports": n_avail,
        "n_market_days": i + 1,
    }

    # --- رشد سود خالص TTM (Product1، scale-free با گاردهای واحد) ---
    ttm_np = np.nan
    ttm_np_prev = np.nan
    unit_ok = True
    if fy1 is not None and fy2 is not None and np.isfinite(fy1["p1"]) and np.isfinite(fy2["p1"]):
        r = guard_ratio(fy1["p1"], fy2["p1"], 0.02, 50.0)
        if not np.isfinite(r):
            unit_ok = False
    if unit_ok:
        if A["jm"] == 12:
            ttm_np = A["p1"]
            ttm_np_prev = fy1["p1"] if fy1 else np.nan
        elif fy1 and lyp and all(np.isfinite(x) for x in (A["p1"], fy1["p1"], lyp["p1"])):
            ttm_np = A["p1"] + fy1["p1"] - lyp["p1"]
            if fy2 and lyp2 and all(np.isfinite(x) for x in (lyp["p1"], fy2["p1"], lyp2["p1"])):
                ttm_np_prev = lyp["p1"] + fy2["p1"] - lyp2["p1"]
    f["ttm_np"] = ttm_np
    g = guard_ratio(ttm_np - ttm_np_prev, abs(ttm_np_prev), 0.0, 300.0) if np.isfinite(ttm_np_prev) and ttm_np_prev != 0 else np.nan
    f["npg"] = g * 100.0 if np.isfinite(g) else np.nan

    # --- رشد سود عملیاتی TTM (با نرمال‌سازی واحد + گارد ۱۰۰x) ---
    ttm_op = np.nan
    ttm_op_prev = np.nan
    if A["jm"] == 12:
        ttm_op = A["op_abs"]
        ttm_op_prev = lyp["op_abs"] if lyp else np.nan
    else:
        if fy1 and lyp and all(np.isfinite(x) for x in (A["op_abs"], fy1["op_abs"], lyp["op_abs"])):
            mags = [abs(fy1["op_abs"]), abs(A["op_abs"]), abs(lyp["op_abs"])]
            if max(mags) <= 100.0 * max(min(mags), 1e-12) or min(mags) == 0:
                ttm_op = A["op_abs"] + fy1["op_abs"] - lyp["op_abs"]
        if fy2 and lyp2 and lyp and all(np.isfinite(x) for x in (lyp["op_abs"], fy2["op_abs"], lyp2["op_abs"])):
            mags = [abs(lyp["op_abs"]), abs(fy2["op_abs"]), abs(lyp2["op_abs"])]
            if max(mags) <= 100.0 * max(min(mags), 1e-12) or min(mags) == 0:
                ttm_op_prev = lyp["op_abs"] + fy2["op_abs"] - lyp2["op_abs"]
    g = guard_ratio(ttm_op - ttm_op_prev, abs(ttm_op_prev), 0.0, 250.0) if np.isfinite(ttm_op_prev) and ttm_op_prev != 0 else np.nan
    f["opg"] = g * 100.0 if np.isfinite(g) else np.nan

    # --- رشد درآمد هم‌منبع (همان سطر) ---
    if np.isfinite(A["rev"]) and np.isfinite(A["rev_ly"]) and A["rev_ly"] != 0:
        f["rg"] = (A["rev"] - A["rev_ly"]) / abs(A["rev_ly"]) * 100.0
    else:
        f["rg"] = np.nan

    # --- فروش ماهانه: رشد ۱۲ماهه/۳ماهه + ثبات ---
    f["sg12"] = np.nan
    f["sg3"] = np.nan
    f["stability"] = np.nan
    n_sales = 0
    if sales_keys is not None and len(sales_keys) > 0:
        j = bisect_right(sales_keys, D_jkey)
        n_sales = j
        vals_hist = sales_vals[:j]
        if j >= 24:
            f["sg12"] = (vals_hist[-12:].sum() / vals_hist[-24:-12].sum() - 1.0) * 100.0 \
                if vals_hist[-24:-12].sum() != 0 else np.nan
        if j >= 6:
            f["sg3"] = (vals_hist[-3:].sum() / vals_hist[-6:-3].sum() - 1.0) * 100.0 \
                if vals_hist[-6:-3].sum() != 0 else np.nan
        if j >= 12:
            m = np.mean(vals_hist[-12:])
            s = np.std(vals_hist[-12:], ddof=1)
            if m != 0:
                f["stability"] = 1.0 - s / abs(m)
    f["n_sales_reports"] = n_sales

    # --- حاشیه‌ها (هم‌منبع، همان سطر؛ گارد ±۲۰۰٪) ---
    if np.isfinite(A["op_abs"]) and np.isfinite(A["rev"]) and A["rev"] != 0:
        m = A["op_abs"] / abs(A["rev"]) * 100.0
        f["om"] = m if abs(m) <= 200.0 else np.nan
    else:
        f["om"] = np.nan
    if np.isfinite(A["p1"]) and np.isfinite(A["rev"]) and A["rev"] != 0:
        m = A["p1"] / abs(A["rev"]) * 100.0
        f["nm"] = m if abs(m) <= 200.0 else np.nan
    else:
        f["nm"] = np.nan
    om_ly = np.nan
    if np.isfinite(A["op_ly_abs"]) and np.isfinite(A["rev_ly"]) and A["rev_ly"] != 0:
        m = A["op_ly_abs"] / abs(A["rev_ly"]) * 100.0
        om_ly = m if abs(m) <= 200.0 else np.nan
    f["mt"] = f["om"] - om_ly if np.isfinite(f["om"]) and np.isfinite(om_ly) else np.nan

    # پوشش بهره
    if np.isfinite(A["op_abs"]) and np.isfinite(A["fin"]) and A["fin"] != 0:
        ic = A["op_abs"] / abs(A["fin"])
        f["ic"] = ic if 0 < ic <= 10000.0 else np.nan
    else:
        f["ic"] = np.nan

    # سهم غیرعملیاتی
    if np.isfinite(A["nonop"]) and np.isfinite(A["op_abs"]) and A["op_abs"] != 0:
        f["eq"] = min(abs(A["nonop"]) / abs(A["op_abs"]) * 100.0, 150.0)
    else:
        f["eq"] = np.nan

    # --- TTM درآمد (برای حاشیه ۱۲ماهه/PS) ---
    ttm_rev = np.nan
    if A["jm"] == 12:
        ttm_rev = A["rev"]
    elif fy1 and lyp and all(np.isfinite(x) for x in (A["rev"], fy1["rev"], lyp["rev"])):
        mags = [abs(A["rev"]), abs(fy1["rev"]), abs(lyp["rev"])]
        if max(mags) <= 100.0 * max(min(mags), 1e-12):
            ttm_rev = A["rev"] + fy1["rev"] - lyp["rev"]
    f["ttm_rev"] = ttm_rev
    nm12 = np.nan
    if np.isfinite(ttm_np) and np.isfinite(ttm_rev) and ttm_rev != 0:
        m = ttm_np / abs(ttm_rev) * 100.0
        nm12 = m if abs(m) <= 200.0 else np.nan
    f["nm12"] = nm12

    # --- P/E و P/S ---
    shares = A["p1"] / A["eps"] if np.isfinite(A["p1"]) and np.isfinite(A["eps"]) and A["eps"] > 0 and A["p1"] > 0 else np.nan
    ttm_eps = ttm_np / shares if np.isfinite(ttm_np) and np.isfinite(shares) and shares > 0 else np.nan
    pe = p_close / ttm_eps if np.isfinite(ttm_eps) and ttm_eps > 0 else np.nan
    f["pe"] = pe if np.isfinite(pe) and 0 < pe <= 60.0 else np.nan
    f["pe_invalid"] = not (np.isfinite(pe) and 0 < pe <= 60.0)
    ps = np.nan
    if np.isfinite(f["pe"]) and np.isfinite(nm12) and nm12 > 0:
        ps = f["pe"] * nm12 / 100.0
        if ps > 100.0:
            ps = np.nan
    f["ps"] = ps

    # --- فاکتورهای بازار (۳۰ روز معاملاتی) ---
    f["mom"] = np.nan
    f["vol"] = np.nan
    f["liq"] = np.nan
    if i >= 30:
        c0 = price["close"][i - 30]
        if c0 > 0:
            mom = (p_close / c0 - 1.0) * 100.0
            f["mom"] = min(max(mom, -50.0), 40.0)
        f["vol"] = float(np.std(price["ret"][i - 29 : i + 1], ddof=1))
        f["liq"] = float(np.mean(price["tv"][i - 29 : i + 1]))

    return f


def compute_dq(f):
    dq = 0.0
    sc, pc, mc = f["n_sales_reports"], f["n_profit_reports"], f["n_market_days"]
    dq += 0.28 if sc >= 24 else 0.16 if sc >= 12 else 0.09 if sc >= 6 else 0.0
    dq += 0.28 if pc >= 16 else 0.16 if pc >= 8 else 0.09 if pc >= 4 else 0.0
    dq += 0.21 if mc >= 90 else 0.13 if mc >= 30 else 0.06 if mc >= 10 else 0.0
    if np.isfinite(f["price"]) and f["price"] > 0:
        dq += 0.09
    if f["report_age_m"] is not None:
        dq += 0.08 if f["report_age_m"] <= 5 else 0.045 if f["report_age_m"] <= 8 else 0.0
    if f["price_age_d"] is not None:
        dq += 0.06 if f["price_age_d"] <= 7 else 0.035 if f["price_age_d"] <= 14 else 0.0
    return dq


def score_universe(rows):
    """رتبه‌بندی + زیرامتیازها + QuantScore (وزن‌های فاز ۱ = زیرمجموعه v3.x)"""
    n = len(rows)
    keys = ["sg12", "sg3", "rg", "opg", "npg", "om", "nm", "mt", "ic", "eq",
            "pe", "ps", "liq", "stability", "vol", "mom"]

    def col(k):
        return np.array([r[k] if r[k] is not None and np.isfinite(r[k]) else np.nan for r in rows])

    caps = {"sg12": 150, "sg3": 150, "rg": 200, "opg": 250, "npg": 300,
            "om": 80, "nm": 60, "mt": 25, "ic": 20, "eq": 150,
            "mom": None, "vol": None, "liq": None, "stability": None,
            "pe": None, "ps": None}
    vals = {}
    for k in keys:
        v = col(k)
        cap = caps[k]
        if cap is not None:
            v = np.clip(v, -cap, cap)
        if k == "ic":
            v = np.where(np.isfinite(v) & (v <= 0), -999999.0, v)
        vals[k] = v

    # رتبه‌ها (NULL→خنثی؛ پوشش بهره/کیفیت سود خنثی ۰.۵ مثل ویو)
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

    growth = (9.0 * r_sg12 + 4.0 * r_sg3 + 5.0 * r_rg + 8.0 * r_opg + 10.0 * r_npg)
    prof = (4.0 * r_om + 3.0 * r_nm + 3.0 * r_mt + 3.0 * r_ic + 4.0 * r_eq)
    valn = (10.0 * r_pe + 3.0 * r_ps)
    markt = (6.0 * r_lq + 3.0 * r_st + 3.0 * r_lv + 3.0 * r_mo)

    pen_g = np.zeros(n)
    pen_g += 6.0 * (np.isfinite(vals["sg12"]) & (vals["sg12"] < -20))
    pen_g += 5.0 * (np.isfinite(vals["opg"]) & (vals["opg"] < -25))
    pen_p = np.zeros(n)
    ttm_np = np.array([r["ttm_np"] for r in rows])
    pen_p += 10.0 * (np.isfinite(ttm_np) & (ttm_np < 0))
    pen_p += 4.0 * (np.isfinite(vals["ic"]) & (vals["ic"] < 1.5))
    pen_p += 3.0 * (np.isfinite(vals["mt"]) & (vals["mt"] < -2))
    eq_raw = vals["eq"]
    pen_p += np.where(np.isfinite(eq_raw),
                      np.clip((eq_raw - 20.0) / 80.0, 0.0, 1.0) * 8.0, 0.0)
    pe_inv = np.array([r["pe_invalid"] for r in rows], bool)
    pen_v = 8.0 * pe_inv
    pen_m = np.zeros(n)
    pad = np.array([r["price_age_d"] for r in rows], float)
    ram = np.array([r["report_age_m"] for r in rows], float)
    pen_m += 4.0 * (np.isfinite(pad) & (pad > 14))
    pen_m += 3.0 * (np.isfinite(ram) & (ram > 8))

    g_s = np.maximum(growth - pen_g, 0.0)
    p_s = np.maximum(prof - pen_p, 0.0)
    v_s = np.maximum(valn - pen_v, 0.0)
    m_s = np.maximum(markt - pen_m, 0.0)
    dq = np.array([compute_dq(r) for r in rows])
    total = dq * (g_s + p_s + v_s + m_s)

    out = []
    for i, r in enumerate(rows):
        d = dict(r)
        d.update({"growth_s": g_s[i], "prof_s": p_s[i], "val_s": v_s[i],
                  "mkt_s": m_s[i], "dq": dq[i], "score": total[i]})
        out.append(d)
    return out


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("بارگذاری داده...", flush=True)
    reports, sales, market = load_data()
    rep_by_cid, sales_by_cid, price_by_cid, sym_by_cid = build_structures(reports, sales, market)
    print(f"شرکت‌ها: گزارش={len(rep_by_cid)} فروش ماهانه={len(sales_by_cid)} قیمت={len(price_by_cid)}", flush=True)

    # تاریخ‌های rebalance
    dates = []
    jy, jm = START_JY, START_JM
    while (jy, jm) <= (END_JY, END_JM):
        dates.append((jy, jm, jalali_month_end_g(jy, jm)))
        jy, jm = add_months(jy, jm, 1)

    all_rows = []
    port_rows = []
    ic_factor_cols = ["sg12", "sg3", "rg", "opg", "npg", "om", "nm", "mt", "ic",
                      "eq", "pe", "ps", "liq", "stability", "vol", "mom",
                      "growth_s", "prof_s", "val_s", "mkt_s", "dq", "score"]
    ic_series = {c: [] for c in ic_factor_cols}

    for jy, jm, gdate in dates:
        D_ord = gdate.toordinal()
        D_jkey = jy * 12 + jm
        rows = []
        for cid, price in price_by_cid.items():
            rep_rows = rep_by_cid.get(cid)
            if not rep_rows:
                continue
            pub_list = [r["pub"] for r in rep_rows]
            sk, sv = sales_by_cid.get(cid, (None, None))
            f = company_factors(rep_rows, pub_list, sk, sv, price, D_ord, D_jkey)
            if f is None:
                continue
            # فیلتر جهان: حداقل داده مثل HasEnoughData ویو
            if f["n_profit_reports"] < 1 or f["n_market_days"] < 30 or f["n_sales_reports"] < 12:
                continue
            f["cid"] = cid
            f["symbol"] = sym_by_cid.get(cid, "")
            rows.append(f)
        if len(rows) < MIN_UNIVERSE:
            continue
        scored = score_universe(rows)

        # بازده‌های آینده
        for r in scored:
            p = price_by_cid[r["cid"]]
            i0 = bisect_right(p["dates"], D_ord) - 1
            base = p["idx"][i0]
            for h in HORIZONS:
                hy, hm = add_months(jy, jm, h)
                tgt = jalali_month_end_g(hy, hm).toordinal()
                i1 = bisect_right(p["dates"], tgt) - 1
                # قیمت کهنه (بیش از ~۳ ماه交易日 غیبت) → بازده نامعتبر
                ok = i1 >= 0 and (tgt - int(p["dates"][i1])) <= 100
                r[f"fwd{h}"] = p["idx"][i1] / base - 1.0 if ok else np.nan

        # IC با بازده ۳ ماهه
        df = pd.DataFrame(scored)
        fwd = df["fwd3"]
        valid_fwd = fwd.notna() & np.isfinite(fwd)
        if valid_fwd.sum() >= 20:
            y = fwd[valid_fwd]
            for c in ic_factor_cols:
                x = pd.to_numeric(df[c][valid_fwd], errors="coerce")
                m = np.isfinite(x)
                if m.sum() >= 10 and x[m].nunique() > 1:
                    ic_series[c].append(float(x[m].rank().corr(y[m].rank())))

        # پرتفوی
        for h in HORIZONS:
            sub = df[["symbol", "score", f"fwd{h}"]].dropna(subset=[f"fwd{h}"])
            if len(sub) < MIN_UNIVERSE:
                continue
            ordered = sub.sort_values("score", ascending=False)
            bench = float(sub[f"fwd{h}"].mean())
            rec = {"jy": jy, "jm": jm, "h": h, "n": len(sub), "bench": bench}
            for N in TOP_NS:
                top = ordered.head(N)
                rec[f"top{N}"] = float(top[f"fwd{h}"].mean())
                rec[f"top{N}_excess"] = rec[f"top{N}"] - bench
            port_rows.append(rec)

        for r in scored:
            r["jy"], r["jm"] = jy, jm
        cols_keep = ["jy", "jm", "cid", "symbol"] + ic_factor_cols + ["ttm_np", "pe_invalid"] + [f"fwd{h}" for h in HORIZONS]
        all_rows.extend([{k: r.get(k) for k in cols_keep} for r in scored])

    # ---------------- تجمیع ----------------
    port_df = pd.DataFrame(port_rows)
    cross = pd.DataFrame(all_rows)
    cross.to_csv(os.path.join(OUT_DIR, "crosssections.csv"), index=False, encoding="utf-8-sig")
    port_df.to_csv(os.path.join(OUT_DIR, "portfolio_by_date.csv"), index=False, encoding="utf-8-sig")

    summary = {"phase": 1, "publish_delay_days": PUBLISH_DELAY_DAYS,
               "start": f"{START_JY}/{START_JM:02d}", "end": f"{END_JY}/{END_JM:02d}",
               "n_dates": int(port_df.groupby(["jy", "jm"]).ngroups),
               "avg_universe": int(port_df[port_df.h == 3].n.mean()) if len(port_df) else 0,
               "limitations": ["survivorship-bias", "CODAL-delay-45d-simplified",
                               "no-dividend-return", "no-v3.2-balance-sheet-factors"],
               "portfolios": {}, "ic": {}}

    print("\n" + "=" * 78)
    print(f"بک‌تست فاز ۱ | {summary['start']} تا {summary['end']} | {summary['n_dates']} ماه | جهان≈{summary['avg_universe']} شرکت")
    print("=" * 78)

    for h in HORIZONS:
        ph = port_df[port_df.h == h]
        if not len(ph):
            continue
        print(f"\n--- افق {h} ماهه ---")
        print(f"{'':16}{'بازده':>10}{'اضافه‌بازده':>12}{'نرخ برد':>10}")
        summary["portfolios"][h] = {}
        for N in TOP_NS:
            r = ph[f"top{N}"]
            ex = ph[f"top{N}_excess"]
            bench = ph["bench"]
            hit = float((ex > 0).mean())
            # ترکیب غیرهم‌پوشان: هر h ماه یکبار
            sub = ph.iloc[::h]
            ch_port = float(np.prod(1.0 + sub[f"top{N}"]) - 1.0)
            ch_bench = float(np.prod(1.0 + sub["bench"]) - 1.0)
            ann = (1.0 + ch_port) ** (12.0 / (h * max(len(sub), 1))) - 1.0
            ann_b = (1.0 + ch_bench) ** (12.0 / (h * max(len(sub), 1))) - 1.0
            print(f"Top{N:<10}{r.mean()*100:>9.1f}%{ex.mean()*100:>11.1f}%{hit*100:>9.0f}%"
                  f"  | مجموع غیرهم‌پوشان: {ch_port*100:.0f}% در برابر بنچمارک {ch_bench*100:.0f}%"
                  f"  | CAGR: {ann*100:.1f}% در برابر {ann_b*100:.1f}%")
            summary["portfolios"][h][f"top{N}"] = {
                "mean_ret": float(r.mean()), "mean_excess": float(ex.mean()),
                "hit_rate": hit, "bench_mean": float(bench.mean()),
                "nonoverlap_total": ch_port, "nonoverlap_bench": ch_bench,
                "cagr": ann, "cagr_bench": ann_b}

    print(f"\n--- IC (همبستگی رتبه‌ای با بازده ۳ ماهه آینده) ---")
    print(f"{'فاکتور':>12}{'IC میانگین':>12}{'t-stat':>9}{'% مثبت':>9}")
    names = {"sg12": "رشد فروش۱۲م", "sg3": "رشد فروش۳م", "rg": "رشد درآمد",
             "opg": "رشد عملیاتی", "npg": "رشد خالص", "om": "حاشیه عملیاتی",
             "nm": "حاشیه خالص", "mt": "روند حاشیه", "ic": "پوشش بهره",
             "eq": "کیفیت سود(ضد)", "pe": "P/E(ضد)", "ps": "P/S(ضد)",
             "liq": "نقدشوندگی", "stability": "ثبات فروش", "vol": "نوسان(ضد)",
             "mom": "مومنتوم", "growth_s": "امتیاز رشد", "prof_s": "امتیاز سودآوری",
             "val_s": "امتیاز ارزش", "mkt_s": "امتیاز بازار", "dq": "کیفیت داده",
             "score": "QuantScore"}
    for c in ic_factor_cols:
        s = ic_series[c]
        if len(s) >= 6:
            arr = np.array(s)
            t = float(arr.mean() / (arr.std(ddof=1) / math.sqrt(len(arr)))) if arr.std(ddof=1) > 0 else 0.0
            summary["ic"][c] = {"mean": float(arr.mean()), "t": t,
                                "pct_pos": float((arr > 0).mean()), "n": len(arr)}
            print(f"{names.get(c, c):>12}{arr.mean():>12.3f}{t:>9.2f}{(arr > 0).mean()*100:>8.0f}%")

    with open(os.path.join(OUT_DIR, "backtest_results.json"), "w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False, indent=2)
    print(f"\nخروجی‌ها در {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
