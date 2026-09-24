"""Faithful v3.7 compatibility re-implementation over canonical PostgreSQL.

Reads ONLY canonical tables (no mutation). This is the debugging successor to
``compute_and_compare.py``. It fixes the identified base-metric root causes:

  * monetary unit scaling (canonical rial -> v3.7 million rial, /1e6)
  * latest-report selection (max period_end_date) matching ProfitDedup rn=1
  * exact TTM logic (amount path -> Product1 path -> NULL)
  * Product1 recovery (eps x capital/1e6) inside the compat layer only
  * OperatingProfit per-share normalisation (OpK/OpAbs/OpAmt)
  * share count (capital/1e6) and LatestPrice=COALESCE(last,close)

Outputs comparison artifacts under ``analytics_parity/debug_v37/``.

Safety: SQL Server not touched here; canonical data never modified.
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import sys
from math import log10
from pathlib import Path

import jdatetime

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn  # noqa: E402

PARITY = BASE / "analytics_parity"
REF = PARITY / "reference"
OUT = PARITY / "debug_v37"
CTX = json.loads((PARITY / "reference_context.json").read_text(encoding="utf-8"))
CUTOFF = CTX["analysis_cutoff_at_utc"]
ASOF = CTX["analysis_as_of_date"]

MONETARY = {"revenue", "net_profit", "operating_profit", "finance_cost",
            "other_non_operating", "total_assets", "current_assets",
            "total_liabilities", "current_liabilities", "total_equity",
            "operating_cash_flow"}


def fnum(x):
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        return None


def scale(metric, value):
    """canonical_value -> v3.7-raw units. Monetary: rial/1e6. capital: shares
    (Num2_Value1 = capital/1e6). eps: rial_per_share unchanged."""
    v = fnum(value)
    if v is None:
        return None
    if metric == "capital":
        return v / 1e6
    if metric in MONETARY:
        return v / 1e6
    return v


def jal(y, m):
    return (y, m)


def signed_log_int_ratio(a, b):
    """v3.7 NPUnitRatio anchor: POWER(10, round(log10(|a/b|))) if a,b same sign
    and |log10(|a/b|) - round(...)| <= 0.1, else None."""
    if a is None or b is None or b == 0:
        return None
    if a * b <= 0:
        return None
    r = abs(a) / abs(b)
    lr = log10(r)
    if abs(lr - round(lr)) <= 0.1:
        return 10.0 ** round(lr)
    return None


def midrank_percentile(keys: dict, higher_better=True, neutral=0.3,
                       neutralize_invalid=None):
    """Replicates v3.7 RANK()-based midrank percentile.

    keys: sym -> key (None allowed). invalid_value: keys >= sentinel handled by
    ``neutralize_invalid`` (callable key->bool returning True => rank 0.0).
    """
    present = {k: v for k, v in keys.items() if v is not None}
    n = len(present)
    out = {k: neutral for k in keys}
    if n == 0:
        return out
    if n == 1:
        for k in present:
            out[k] = 0.5
        return out
    vals = sorted(present.values())
    from bisect import bisect_left, bisect_right
    for k, v in present.items():
        less = bisect_left(vals, v)
        tie = bisect_right(vals, v) - less
        pct = (2 * less + (tie - 1)) / (2 * (n - 1))
        out[k] = pct
    if not higher_better:
        out = {k: (1.0 - out[k] if keys[k] is not None else out[k]) for k in keys}
    if neutralize_invalid is not None:
        for k in keys:
            if colors := neutralize_invalid(keys[k]):
                out[k] = 0.0
    return out


def cap(v, lo, hi):
    if v is None:
        return None
    if v > hi:
        return hi
    if v < lo:
        return lo
    return v


class Company:
    __slots__ = ()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT.mkdir(parents=True, exist_ok=True)
    pg = pg_pilot_conn(autocommit=True)
    pc = pg.cursor()

    def rows(sql, p=()):
        pc.execute(sql, p)
        cols = [c[0] for c in pc.description]
        return [dict(zip(cols, r)) for r in pc.fetchall()]

    secs = rows("""SELECT s.id::text AS security_id, s.company_id::text AS company_id,
                          s.codal_symbol AS symbol
                   FROM core.securities s""")
    sec_by_company = {s["company_id"]: s for s in secs}

    # ---- monthly sales (million rial) ----
    monthly = rows("""
        SELECT company_id::text AS company_id, period_end_date, SUM(sales_amount_rial) AS amt
        FROM fundamentals.monthly_activities
        GROUP BY company_id, period_end_date
        ORDER BY company_id, period_end_date""")
    monthly_by = {}
    for m in monthly:
        monthly_by.setdefault(m["company_id"], []).append((m["period_end_date"], fnum(m["amt"]) / 1e6))

    # ---- facts, grouped by report (period_end_date) ----
    facts = rows("""
        SELECT st.company_id::text AS company_id, st.period_end_date AS ped,
               f.metric_code, f.period_order, f.canonical_value
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id = f.statement_id""")
    report = {}  # company -> ped -> metric -> order -> scaled value
    for f in facts:
        d = report.setdefault(f["company_id"], {}).setdefault(f["ped"], {})
        d.setdefault(f["metric_code"], {})[f["period_order"]] = scale(f["metric_code"], f["canonical_value"])

    import jdatetime
    def jyjm(ped):
        j = jdatetime.date.fromgregorian(date=ped)
        return j.year, j.month

    # per-report computed structures
    rep_info = {}  # company -> (year,month) -> dict
    for cid, periods in report.items():
        for ped, factsd in periods.items():
            y, mo = jyjm(ped)
            rep_info.setdefault(cid, {})[(y, mo)] = build_report(factsd)
    # latest report per company
    latest_period = {}
    for cid, periods in report.items():
        latest_period[cid] = max(periods.keys())

    # ---- market ----
    prices = rows("""
        SELECT security_id::text AS security_id, trade_date, collected_at,
               closing_price_rial, last_price_rial, high_price_rial, low_price_rial,
               trade_value_rial
        FROM market.price_observations
        WHERE collected_at <= %s
        ORDER BY security_id, trade_date DESC, collected_at DESC""", (CUTOFF,))
    mkt = {}
    for p in prices:
        mkt.setdefault(p["security_id"], []).append(p)

    metrics = {}
    for s in secs:
        cid = s["company_id"]
        sym = s["symbol"]
        lp = latest_period.get(cid)
        if lp is not None:
            y, mo = jyjm(lp)
            info = rep_info[cid][(y, mo)]
        else:
            y = mo = None
            info = empty_report()
        m = compute_company(sym, cid, s["security_id"], y, mo, {}, info,
                            rep_info.get(cid, {}), monthly_by.get(cid, []),
                            mkt.get(s["security_id"], []))
        metrics[sym] = m

    # ---- ranks (all 19 factors) ----
    rank_all(metrics)

    # ---- penalties + scores ----
    for sym, m in metrics.items():
        scores(m)

    compare(metrics)
    pg.close()
    return 0


def build_report(f: dict, product1_override=None) -> dict:
    """Compute derived per-report fields used by v3.7 joins.

    ``product1_override`` is the real legacy Product1 when available (frozen
    compatibility input). v3.7 uses this exact column for OpAbs/ImpliedShares;
    reconstruction eps*Num2_Value1 is only a fallback when it is missing.
    """
    def g(metric, order=1):
        return f.get(metric, {}).get(order)

    eps = g("eps")
    capital = g("capital")
    shares = capital  # already /1e6 => Num2_Value1
    if product1_override is not None:
        product1 = product1_override
    else:
        product1 = (eps * shares) if (eps is not None and shares is not None) else None

    opraw = g("operating_profit")
    np_amt = g("net_profit")
    rev = g("revenue")

    # OpK
    opk = 1.0
    if opraw is None or eps is None or eps == 0:
        opk = 1.0
    elif (np_amt is not None and abs(np_amt) > 0
          and abs(opraw) < 0.001 * abs(np_amt)
          and (rev is None or abs(rev) == 0 or abs(opraw) < 0.001 * abs(rev))):
        opk = np_amt / eps
    elif np_amt is None and rev is not None and abs(rev) > 0 and abs(opraw) < 0.001 * abs(rev):
        opk = None
    else:
        opk = 1.0

    def opamt(opval, revval):
        if opk is None or opval is None:
            return None
        if revval is not None and abs(revval) > 0 and abs(opval * opk) > 3.0 * abs(revval):
            return None
        return opval * opk

    op_amt = opamt(opraw, rev)
    op_ly_amt = opamt(g("operating_profit", 2), g("revenue", 2))
    op_fy_amt = opamt(g("operating_profit", 3), g("revenue", 3))

    def opabs(opval, revval, epsv, npv):
        if opval is None:
            return None
        if revval is not None and abs(revval) > 0:
            if abs(opval) < 0.001 * abs(revval) and epsv and epsv > 0 and npv and npv > 0:
                return opval * npv / epsv
            return opval
        if epsv and epsv > 0 and npv and npv > 0 and abs(opval) < 0.05 * npv \
                and abs(opval) < 100.0 * epsv and abs(opval) >= 0.05 * epsv:
            return opval * npv / epsv
        return opval

    opabs1 = opabs(opraw, rev, eps, product1)
    opabs_ly = opabs(g("operating_profit", 2), g("revenue", 2), eps, product1)

    return {
        "eps": eps, "capital": shares, "product1": product1,
        "opraw": opraw, "opk": opk,
        "op_amt": op_amt, "op_ly_amt": op_ly_amt, "op_fy_amt": op_fy_amt,
        "opabs": opabs1, "opabs_ly": opabs_ly,
        "np_amt": np_amt, "np_ly": g("net_profit", 2), "np_fyprev": g("net_profit", 3),
        "rev": rev, "rev_ly": g("revenue", 2), "rev_fyprev": g("revenue", 3),
        "finance": g("finance_cost"), "other_nonop": g("other_non_operating"),
        "ocf": g("operating_cash_flow"), "ocf_ly": g("operating_cash_flow", 2),
        "ocf_fyprev": g("operating_cash_flow", 3),
        "assets": g("total_assets"), "cur_assets": g("current_assets"),
        "liab": g("total_liabilities"), "cur_liab": g("current_liabilities"),
        "equity": g("total_equity"),
    }


def empty_report():
    keys = list(build_report({}).keys())
    return {k: None for k in keys}


def compute_company(sym, cid, sec_id, y, mo, base, info, rep_index, msales, mpx):
    latest = info  # info for latest report
    # ----- monthly -----
    desc = sorted(msales, key=lambda t: t[0], reverse=True)
    def ssum(a, b):
        return sum(x[1] or 0 for x in desc[a:b]) if desc[a:b] else 0
    has_monthly = bool(desc)
    SalesLast12M = sum(x[1] or 0 for x in desc[0:12]) if has_monthly else None
    SalesPrev12M = ssum(12, 24) if has_monthly else None
    SalesLast3M = ssum(0, 3) if has_monthly else None
    SalesPrev3M = ssum(3, 6) if has_monthly else None
    avg12 = [x[1] for x in desc[0:12]] if has_monthly else []
    SalesAvg12M = (sum(avg12) / len(avg12)) if avg12 else None
    SalesStd12M = statistics.stdev(avg12) if len(avg12) > 1 else None
    SalesGrowth12M = ((SalesLast12M - SalesPrev12M) / abs(SalesPrev12M) * 100.0) \
        if (SalesPrev12M and abs(SalesPrev12M) > 0 and SalesLast12M is not None) else None
    SalesGrowth3M = ((SalesLast3M - SalesPrev3M) / abs(SalesPrev3M) * 100.0) \
        if (SalesPrev3M and abs(SalesPrev3M) > 0) else None
    SalesStability = (1.0 - ((SalesStd12M or 0) / abs(SalesAvg12M))) \
        if (SalesAvg12M and abs(SalesAvg12M) > 0) else None

    price = mkt_agg(mpx)
    if mo is None:
        return _no_report_company(sym, cid, sec_id, desc, SalesLast12M, SalesPrev12M,
                                  SalesGrowth12M, SalesGrowth3M, SalesStability, price)

    # ----- TTM -----
    np1, np2, np3 = latest["np_amt"], latest["np_ly"], latest["np_fyprev"]
    amt_ttm = None
    if mo == 12 and np1 is not None:
        amt_ttm = np1
    elif np1 is not None and np3 is not None and np2 is not None:
        amt_ttm = np1 + np3 - np2

    def prod1(yy, mm):
        r = rep_index.get((yy, mm))
        return r["product1"] if r else None

    LatestNetProfitCum = latest["product1"]
    FYPrevNetProfit = prod1(y - 1, 12)
    LYPNetProfit = prod1(y - 1, mo)
    FYPrev2NetProfit = prod1(y - 2, 12)
    LYP2NetProfit = prod1(y - 2, mo)

    if mo == 12:
        p1_ttm = LatestNetProfitCum
    elif FYPrevNetProfit is not None and LYPNetProfit is not None:
        p1_ttm = LatestNetProfitCum + FYPrevNetProfit - LYPNetProfit
    else:
        p1_ttm = None
    TTMNetProfit = amt_ttm if amt_ttm is not None else p1_ttm
    TTMNetProfitP1 = p1_ttm

    if mo == 12:
        TTMNetProfitPrev = LYPNetProfit
    elif FYPrev2NetProfit is not None and LYP2NetProfit is not None and LYPNetProfit is not None:
        TTMNetProfitPrev = LYPNetProfit + FYPrev2NetProfit - LYP2NetProfit
    else:
        TTMNetProfitPrev = None

    SR_TTMNetProfit = amt_ttm

    # unit ratio
    NPUnitRatio = signed_log_int_ratio(latest["np_ly"], LYPNetProfit)
    if NPUnitRatio is None:
        NPUnitRatio = signed_log_int_ratio(np1, LatestNetProfitCum)

    # ----- operating -----
    SR_TTMOperatingProfit = None
    if mo == 12 and latest["op_amt"] is not None:
        SR_TTMOperatingProfit = latest["op_amt"]
    elif latest["op_amt"] is not None and latest["op_fy_amt"] is not None and latest["op_ly_amt"] is not None:
        SR_TTMOperatingProfit = latest["op_amt"] + latest["op_fy_amt"] - latest["op_ly_amt"]

    SR_TTMRevenue = None
    if mo == 12 and latest["rev"] is not None:
        SR_TTMRevenue = latest["rev"]
    elif latest["rev"] is not None and latest["rev_fyprev"] is not None and latest["rev_ly"] is not None:
        SR_TTMRevenue = latest["rev"] + latest["rev_fyprev"] - latest["rev_ly"]

    SR_TTMOCF = None
    if mo == 12 and latest["ocf"] is not None:
        SR_TTMOCF = latest["ocf"]
    elif latest["ocf"] is not None and latest["ocf_fyprev"] is not None and latest["ocf_ly"] is not None:
        SR_TTMOCF = latest["ocf"] + latest["ocf_fyprev"] - latest["ocf_ly"]

    def opabs_at(yy, mm):
        r = rep_index.get((yy, mm))
        return r["opabs"] if r else None

    def scale_ok(a, b, mult=100.0):
        if a is None or b is None:
            return False
        return a == 0 or b == 0 or (abs(b) <= abs(a) * mult and abs(a) <= abs(b) * mult)

    FYPrevOpAbs = opabs_at(y - 1, 12)
    LYPOpAbs = opabs_at(y - 1, mo)
    FYPrev2OpAbs = opabs_at(y - 2, 12)
    LYP2OpAbs = opabs_at(y - 2, mo)
    if mo == 12:
        TTMOperatingProfit = latest["opabs"]
    elif FYPrevOpAbs is not None and LYPOpAbs is not None and scale_ok(latest["opabs"], FYPrevOpAbs) and scale_ok(latest["opabs"], LYPOpAbs):
        TTMOperatingProfit = latest["opabs"] + FYPrevOpAbs - LYPOpAbs
    else:
        TTMOperatingProfit = None

    if mo == 12:
        TTMOperatingProfitPrev = LYPOpAbs
    elif (LYPOpAbs is not None and FYPrev2OpAbs is not None and LYP2OpAbs is not None
          and scale_ok(LYPOpAbs, FYPrev2OpAbs) and scale_ok(LYPOpAbs, LYP2OpAbs)):
        TTMOperatingProfitPrev = LYPOpAbs + FYPrev2OpAbs - LYP2OpAbs
    else:
        TTMOperatingProfitPrev = None

    def rev_at(yy, mm):
        r = rep_index.get((yy, mm))
        return r["rev"] if r else None
    if mo == 12:
        TTMRevenue = latest["rev"]
    elif latest["rev"] is not None and rev_at(y - 1, 12) is not None and rev_at(y - 1, mo) is not None:
        TTMRevenue = latest["rev"] + rev_at(y - 1, 12) - rev_at(y - 1, mo)
    else:
        TTMRevenue = None

    ImpliedShares = (latest["product1"] / latest["eps"]) if (latest["eps"] and latest["eps"] > 0 and latest["product1"] and latest["product1"] > 0) else None
    EffectiveRevenue12M = TTMRevenue if TTMRevenue is not None else SalesLast12M

    def margin(opv, revv):
        if opv is None or revv is None or abs(revv) == 0:
            return None
        r = opv / abs(revv) * 100.0
        return r if abs(r) <= 200.0 else None

    OperatingMargin12M = None
    for cand in (
        margin(SR_TTMOperatingProfit, SR_TTMRevenue),
        margin(latest["op_amt"], latest["rev"]),
        margin(TTMOperatingProfit, EffectiveRevenue12M),
    ):
        if cand is not None:
            OperatingMargin12M = cand
            break

    NetProfitMargin12M = None
    for cand in (
        margin(SR_TTMNetProfit, SR_TTMRevenue),
        margin(latest["np_amt"], latest["rev"]),
        margin(TTMNetProfit, EffectiveRevenue12M),
    ):
        if cand is not None:
            NetProfitMargin12M = cand
            break

    def trend_pair(a, b):
        return a - b

    OperatingMarginTrend = None
    if (latest["op_amt"] is not None and latest["op_ly_amt"] is not None
            and latest["rev"] is not None and latest["rev_ly"] is not None
            and abs(latest["rev"]) > 0 and abs(latest["rev_ly"]) > 0):
        m1 = margin(latest["op_amt"], latest["rev"])
        m2 = margin(latest["op_ly_amt"], latest["rev_ly"])
        if m1 is not None and m2 is not None:
            OperatingMarginTrend = m1 - m2
    if OperatingMarginTrend is None and TTMOperatingProfitPrev is not None and SalesPrev12M and abs(SalesPrev12M) > 0:
        m1 = margin(TTMOperatingProfit, EffectiveRevenue12M)
        m2 = margin(TTMOperatingProfitPrev, SalesPrev12M)
        if m1 is not None and m2 is not None:
            OperatingMarginTrend = m1 - m2

    RevenueGrowthYoY = ((latest["rev"] - latest["rev_ly"]) / abs(latest["rev_ly"]) * 100.0) \
        if (latest["rev"] is not None and latest["rev_ly"] is not None and abs(latest["rev_ly"]) > 0) else None

    InterestCoverage = (latest["op_amt"] / abs(latest["finance"])) \
        if (latest["op_amt"] is not None and latest["finance"] is not None and abs(latest["finance"]) > 0
            and latest["op_amt"] / abs(latest["finance"]) > 0
            and latest["op_amt"] / abs(latest["finance"]) <= 10000.0) else None

    NonOperatingPct = (abs(latest["other_nonop"]) / abs(latest["op_amt"]) * 100.0) \
        if (latest["other_nonop"] is not None and latest["op_amt"] is not None and abs(latest["op_amt"]) > 0) else None

    ROE = (SR_TTMNetProfit / latest["equity"] * 100.0) \
        if (SR_TTMNetProfit is not None and latest["equity"] is not None and latest["equity"] > 0
            and abs(SR_TTMNetProfit / latest["equity"] * 100.0) <= 300.0) else None

    FinancialLeverage = (latest["liab"] / latest["equity"]) \
        if (latest["liab"] is not None and latest["liab"] >= 0 and latest["equity"] is not None
            and latest["equity"] > 0 and latest["liab"] / latest["equity"] <= 50.0) else None

    CurrentRatio = (latest["cur_assets"] / latest["cur_liab"]) \
        if (latest["cur_assets"] is not None and latest["cur_assets"] >= 0
            and latest["cur_liab"] is not None and latest["cur_liab"] > 0
            and latest["cur_assets"] / latest["cur_liab"] <= 15.0) else None

    CashConversion = (SR_TTMOCF / SR_TTMNetProfit) \
        if (SR_TTMOCF is not None and SR_TTMNetProfit is not None and SR_TTMNetProfit > 0
            and -2.0 <= SR_TTMOCF / SR_TTMNetProfit <= 5.0) else None

    # ----- market -----
    price = mkt_agg(mpx)
    LatestPrice = price["latest_price"]
    LatestClosingPrice = price["latest_closing"]

    # ----- EPS / PE -----
    TTMEPS = None
    if SR_TTMNetProfit is not None and latest["np_amt"] is not None and latest["np_amt"] > 0 and (latest["eps"] or 0) > 0:
        TTMEPS = SR_TTMNetProfit * latest["eps"] / latest["np_amt"]
    elif TTMNetProfit is not None and (latest["eps"] or 0) > 0 and (LatestNetProfitCum or 0) > 0:
        TTMEPS = TTMNetProfit * latest["eps"] / LatestNetProfitCum

    PEApprox = None
    if LatestPrice is not None and LatestPrice > 0:
        if (SR_TTMNetProfit is not None and latest["np_amt"] is not None and latest["np_amt"] > 0
                and (latest["eps"] or 0) > 0):
            PEApprox = LatestPrice / (SR_TTMNetProfit * latest["eps"] / latest["np_amt"])
        elif (TTMNetProfit is not None and (latest["eps"] or 0) > 0 and (LatestNetProfitCum or 0) > 0
              and TTMNetProfit * latest["eps"] / LatestNetProfitCum > 0):
            PEApprox = LatestPrice / (TTMNetProfit * latest["eps"] / LatestNetProfitCum)

    TTMOperatingEPS = (TTMOperatingProfit * latest["eps"] / LatestNetProfitCum) \
        if (TTMOperatingProfit is not None and (latest["eps"] or 0) > 0 and (LatestNetProfitCum or 0) > 0) else None

    # ----- data quality (frozen as-of) -----
    import datetime as _dt
    asof = _dt.date.fromisoformat(ASOF)
    jt = jdatetime.date.fromgregorian(date=asof) if True else None
    today_jm = jt.year * 12 + jt.month
    ProfitReportAgeMonths = (today_jm - (y * 12 + mo)) if True else None
    return {
        "symbol": sym, "company_id": cid, "security_id": sec_id,
        "SalesReportCount": len(desc), "MarketDaysCount": price["days"],
        "SalesLast12M": SalesLast12M, "SalesPrev12M": SalesPrev12M,
        "SalesGrowth12M": SalesGrowth12M, "SalesGrowth3M": SalesGrowth3M,
        "SalesStability": SalesStability,
        "LatestEPS": TTMEPS, "TTMEPS": TTMEPS, "TTMOperatingEPS": TTMOperatingEPS,
        "LatestOperatingProfit": latest["op_amt"] if latest["op_amt"] is not None else latest["opabs"],
        "LatestOperatingProfitLastYear": latest["op_ly_amt"] if latest["op_ly_amt"] is not None else latest["opabs_ly"],
        "TTMNetProfit": TTMNetProfit, "TTMNetProfitP1": TTMNetProfitP1, "NPUnitRatio": NPUnitRatio,
        "SR_TTMNetProfit": SR_TTMNetProfit, "SourceTTMProfit": TTMNetProfit,
        "TTMNetProfitPrev": TTMNetProfitPrev, "TTMRevenue": TTMRevenue,
        "TTMOperatingProfit": TTMOperatingProfit, "TTMOperatingProfitPrev": TTMOperatingProfitPrev,
        "EffectiveRevenue12M": EffectiveRevenue12M,
        "OperatingMargin12M": OperatingMargin12M, "NetProfitMargin12M": NetProfitMargin12M,
        "OperatingMarginTrend": OperatingMarginTrend, "RevenueGrowthYoY": RevenueGrowthYoY,
        "InterestCoverage": InterestCoverage, "NonOperatingPct": NonOperatingPct,
        "ROE": ROE, "FinancialLeverage": FinancialLeverage, "CurrentRatio": CurrentRatio,
        "CashConversion": CashConversion,
        "LatestPrice": LatestPrice, "LatestClosingPrice": LatestClosingPrice, "PEApprox": PEApprox,
        "PriceReturn7D": price["ret7"], "PriceReturn30D": price["ret30"], "PriceReturn90D": price["ret90"],
        "AvgTradeValue30D": price["avgtv30"], "AvgVolume30D": price["avgvol30"],
        "AvgTradeCount30D": price["avgtc30"], "Volatility30D": price["vol30"],
        "PricePosition90D": price["pos90"],
        "LatestJYear": y, "LatestJMonth": mo,
        "ProfitReportAgeMonths": ProfitReportAgeMonths,
        "MarketDataAgeDays": price["agedays"],
        "ProfitReportCount": len(rep_index),
        "_latest": latest,
        "_lyp": LYPNetProfit, "_fyprev": FYPrevNetProfit,
        "_fyprev2": FYPrev2NetProfit, "_lyp2": LYP2NetProfit,
        "_fyop": FYPrevOpAbs, "_lyop": LYPOpAbs,
        "_fyop2": FYPrev2OpAbs, "_lyop2": LYP2OpAbs,
    }


def _no_report_company(sym, cid, sec_id, desc, s12, p12, sg, sg3, st, price):
    m = {
        "symbol": sym, "company_id": cid, "security_id": sec_id,
        "SalesReportCount": len(desc), "ProfitReportCount": 0,
        "MarketDaysCount": price["days"],
        "SalesLast12M": s12, "SalesPrev12M": p12, "SalesGrowth12M": sg,
        "SalesGrowth3M": sg3, "SalesStability": st,
        "LatestEPS": None, "TTMEPS": None, "TTMOperatingEPS": None,
        "LatestOperatingProfit": None, "LatestOperatingProfitLastYear": None,
        "TTMNetProfit": None, "TTMNetProfitP1": None, "NPUnitRatio": None,
        "SR_TTMNetProfit": None, "TTMNetProfitPrev": None, "TTMRevenue": None,
        "TTMOperatingProfit": None, "TTMOperatingProfitPrev": None,
        "EffectiveRevenue12M": s12,
        "OperatingMargin12M": None, "NetProfitMargin12M": None, "OperatingMarginTrend": None,
        "RevenueGrowthYoY": None, "InterestCoverage": None, "NonOperatingPct": None,
        "ROE": None, "FinancialLeverage": None, "CurrentRatio": None, "CashConversion": None,
        "LatestPrice": price["latest_price"], "LatestClosingPrice": price["latest_closing"],
        "PEApprox": None,
        "PriceReturn7D": price["ret7"], "PriceReturn30D": price["ret30"], "PriceReturn90D": price["ret90"],
        "AvgTradeValue30D": price["avgtv30"], "AvgVolume30D": price["avgvol30"],
        "AvgTradeCount30D": price["avgtc30"], "Volatility30D": price["vol30"],
        "PricePosition90D": price["pos90"],
        "LatestJYear": None, "LatestJMonth": None,
        "ProfitReportAgeMonths": None, "MarketDataAgeDays": price["agedays"],
        "NetProfitGrowthTTM": None, "OperatingProfitGrowthTTM": None,
        "_latest": empty_report(),
        "_lyp": None, "_fyprev": None, "_fyprev2": None, "_lyp2": None,
        "_fyop": None, "_lyop": None, "_fyop2": None, "_lyop2": None,
    }
    return m


def mkt_agg(mpx):
    out = {"latest_price": None, "latest_closing": None, "days": 0,
           "ret7": None, "ret30": None, "ret90": None,
           "avgtv30": None, "avgvol30": None, "avgtc30": None,
           "vol30": None, "pos90": None, "agedays": None}
    if not mpx:
        return out
    # mpx already sorted by trade_date desc, collected_at desc
    out["days"] = len(mpx)
    closes = [fnum(p["closing_price_rial"]) for p in mpx]
    lasts = [fnum(p["last_price_rial"]) for p in mpx]
    highs = [fnum(p["high_price_rial"]) for p in mpx]
    lows = [fnum(p["low_price_rial"]) for p in mpx]
    out["latest_closing"] = closes[0]
    out["latest_price"] = lasts[0] if lasts[0] is not None else closes[0]
    def at(i):
        return closes[i] if i < len(closes) else None
    for lag, key in ((6, "ret7"), (29, "ret30"), (89, "ret90")):
        if out["latest_closing"] is not None and at(lag) and abs(at(lag)) > 0:
            out[key] = (out["latest_closing"] - at(lag)) / abs(at(lag)) * 100.0
    # daily returns: LAG over ORDER BY trade_date DESC => previous row is the
    # MORE RECENT day. Return at rn=i uses (close_i - close_{i-1})/close_{i-1}.
    rets = []
    for i in range(1, min(30, len(closes))):
        if closes[i] is not None and closes[i - 1] and closes[i - 1] > 0:
            rets.append((closes[i] - closes[i - 1]) * 100.0 / closes[i - 1])
    if len(rets) > 1:
        out["vol30"] = statistics.stdev(rets)
    tvs = [fnum(p["trade_value_rial"]) for p in mpx[:30] if p.get("trade_value_rial") is not None]
    if tvs:
        out["avgtv30"] = sum(tvs) / len(tvs)
    hi = [h for h in highs[:90] if h is not None]
    lo = [l for l in lows[:90] if l is not None]
    if hi and lo and out["latest_price"] is not None and abs(max(hi) - min(lo)) > 0:
        out["pos90"] = (out["latest_price"] - min(lo)) / abs(max(hi) - min(lo)) * 100.0
    import datetime as _dt
    td = mpx[0]["trade_date"]
    out["agedays"] = (_dt.date.fromisoformat(ASOF) - td).days if hasattr(td, "year") else None
    return out


def rank_all(metrics):
    """Compute all factor ranks per v3.7 RankKeys/RankDists/Ranked."""
    for s, m in metrics.items():
        m["NetProfitGrowthTTM"] = npgrowth(m)
        m["OperatingProfitGrowthTTM"] = opgrowth(m)

    def rk(name, getter, neutral=0.3, higher=True, invalid=None):
        keys = {s: getter(m) for s, m in metrics.items()}
        pct = midrank_percentile(keys, higher_better=higher, neutral=neutral,
                                 neutralize_invalid=(lambda k: invalid(k)) if invalid else None)
        for s in metrics:
            metrics[s][name] = pct[s]

    rk("SalesGrowthRank", lambda m: cap(m["SalesGrowth12M"], -150, 150))
    rk("SalesGrowth3MRank", lambda m: cap(m["SalesGrowth3M"], -150, 150))
    rk("NetProfitGrowthRank", lambda m: cap(m["NetProfitGrowthTTM"], -300, 300))
    rk("OperatingProfitGrowthRank", lambda m: cap(m["OperatingProfitGrowthTTM"], -250, 250))
    rk("RevenueGrowthRank", lambda m: cap(m["RevenueGrowthYoY"], -200, 200))
    rk("OperatingMarginRank", lambda m: cap(m["OperatingMargin12M"], -80, 80))
    rk("NetMarginRank", lambda m: cap(m["NetProfitMargin12M"], -60, 60))
    rk("MarginTrendRank", lambda m: cap(m["OperatingMarginTrend"], -25, 25))

    def ic_key(m):
        ic = m["InterestCoverage"]
        if ic is None:
            return None
        if ic <= 0:
            return -999999.0
        return min(ic, 20.0)
    rk("InterestCoverageRank", ic_key, neutral=0.5)

    def eq_key(m):
        n = m["NonOperatingPct"]
        if n is None:
            return None
        return min(abs(n), 150.0)
    rk("EarningsQualityRank", eq_key, neutral=0.5, higher=False)

    def pe_key(m):
        pe = m["PEApprox"]
        return pe if (pe is not None and 0 < pe <= 60) else 999999.0
    rk("PERank", pe_key, neutral=0.0, higher=False, invalid=lambda k: k is not None and k >= 999999.0)

    def ps_key(m):
        pe = m["PEApprox"]
        nm = m["NetProfitMargin12M"]
        if pe is not None and 0 < pe <= 60 and nm is not None and nm > 0:
            return pe * (nm / 100.0)
        return 999999.0
    rk("PSRank", ps_key, neutral=0.0, higher=False, invalid=lambda k: k is not None and k >= 999999.0)

    rk("LiquidityRank", lambda m: m["AvgTradeValue30D"], neutral=0.0)
    rk("StabilityRank", lambda m: m["SalesStability"], neutral=0.3)
    rk("LowVolatilityRank", lambda m: m["Volatility30D"], neutral=0.3, higher=False)
    rk("MomentumRank", lambda m: cap(m["PriceReturn30D"], -50, 40))
    rk("ROERank", lambda m: cap(m["ROE"], -150, 150))
    rk("LeverageRank", lambda m: (min(m["FinancialLeverage"], 50.0) if m["FinancialLeverage"] is not None else None), neutral=0.3, higher=False)
    rk("CurrentRatioRank", lambda m: (min(m["CurrentRatio"], 15.0) if m["CurrentRatio"] is not None else None), neutral=0.3)
    rk("CashConversionRank", lambda m: cap(m["CashConversion"], -2, 5))

    def pb_key(m):
        pe = m["PEApprox"]
        roe = m["ROE"]
        if pe is not None and 0 < pe <= 60 and roe is not None and roe > 0 and pe * roe / 100.0 <= 30.0:
            return pe * roe / 100.0
        return 999999.0
    rk("PBRank", pb_key, neutral=0.0, higher=False, invalid=lambda k: k is not None and k >= 999999.0)


def npgrowth(m):
    lat = m["_latest"]
    sr = m["SR_TTMNetProfit"]
    if sr is not None and m["NPUnitRatio"] is not None and m["TTMNetProfitPrev"] is not None and abs(m["TTMNetProfitPrev"]) > 0:
        return (sr - m["TTMNetProfitPrev"] * m["NPUnitRatio"]) / abs(m["TTMNetProfitPrev"] * m["NPUnitRatio"]) * 100.0
    if m["TTMNetProfitP1"] is not None and m["TTMNetProfitPrev"] is not None and abs(m["TTMNetProfitPrev"]) > 0:
        return (m["TTMNetProfitP1"] - m["TTMNetProfitPrev"]) / abs(m["TTMNetProfitPrev"]) * 100.0
    # LYPNetProfit not stored; approximate via product1 join
    lyp = None
    if m.get("_lyp") is not None:
        lyp = m["_lyp"]
    if lyp is not None and abs(lyp) > 0:
        return (lat["product1"] - lyp) / abs(lyp) * 100.0
    return None


def opgrowth(m):
    if (m["TTMOperatingProfitPrev"] is not None and abs(m["TTMOperatingProfitPrev"]) > 0
            and m["TTMOperatingProfit"] is not None):
        return (m["TTMOperatingProfit"] - m["TTMOperatingProfitPrev"]) / abs(m["TTMOperatingProfitPrev"]) * 100.0
    latest_abs = m["_latest"]["opabs"]
    lyop = m["_lyop"]
    if (lyop is not None and abs(lyop) > 0 and latest_abs is not None
            and _scale_ok_strict(latest_abs, lyop)):
        return (latest_abs - lyop) / abs(lyop) * 100.0
    latest_ly = m["_latest"]["opabs_ly"]
    if (latest_ly is not None and abs(latest_ly) > 0 and latest_abs is not None
            and _scale_ok_strict(latest_abs, latest_ly)):
        return (latest_abs - latest_ly) / abs(latest_ly) * 100.0
    return None


def _scale_ok_strict(a, b, mult=100.0):
    """v3.7 OperatingProfitGrowthTTM guard: both <= 100x each other, no zero escape."""
    if a is None or b is None:
        return False
    return abs(a) != 0 and abs(b) != 0 and abs(b) <= abs(a) * mult and abs(a) <= abs(b) * mult


def scores(m):
    growth = (10 * m["SalesGrowthRank"] + 6 * m["SalesGrowth3MRank"] + 5 * m["RevenueGrowthRank"]
              + 5 * m["OperatingProfitGrowthRank"] + 10 * m["NetProfitGrowthRank"])
    gp = (6.0 if (m["SalesGrowth12M"] is not None and m["SalesGrowth12M"] < -20) else 0.0) \
        + (5.0 if (m.get("OperatingProfitGrowthTTM") is not None and m["OperatingProfitGrowthTTM"] < -25) else 0.0)
    growth = max(growth - gp, 0.0)

    prof = (4 * m["OperatingMarginRank"] + 4 * m["NetMarginRank"] + 6 * m["ROERank"] + 3 * m["MarginTrendRank"]
            + 3 * m["InterestCoverageRank"] + 2 * m["CashConversionRank"] + 4 * m["EarningsQualityRank"])
    pp = (10.0 if (m["TTMNetProfit"] is not None and m["TTMNetProfit"] < 0) else 0.0) \
        + (4.0 if (m["InterestCoverage"] is not None and m["InterestCoverage"] < 1.5) else 0.0) \
        + (3.0 if (m["OperatingMarginTrend"] is not None and m["OperatingMarginTrend"] < -2) else 0.0)
    nop = m["NonOperatingPct"]
    if nop is None:
        pass
    elif nop <= 20:
        pass
    elif nop >= 100:
        pp += 8.0
    else:
        pp += (nop - 20.0) / 80.0 * 8.0
    prof = max(prof - pp, 0.0)

    val = (11 * m["PERank"] + 3 * m["PSRank"] + 2 * m["PBRank"])
    vp = 8.0 if (m["PEApprox"] is None or m["PEApprox"] <= 0 or m["PEApprox"] > 60) else 0.0
    val = max(val - vp, 0.0)

    mkt = (3 * m["LiquidityRank"] + 2 * m["LeverageRank"] + 2 * m["CurrentRatioRank"]
           + 1 * m["StabilityRank"] + 2 * m["LowVolatilityRank"] + 1 * m["MomentumRank"])
    dq = data_quality(m)
    m["GrowthScore"] = round(growth, 1)
    m["ProfitabilityScore"] = round(prof, 1)
    m["ValuationScore"] = round(val, 1)
    m["MarketScore"] = round(mkt, 1)
    m["DataQualityScore"] = round(dq, 4)
    m["GrowthPenalty"] = round(gp, 1)
    m["ProfitabilityPenalty"] = round(pp, 1)
    m["ValuationPenalty"] = round(vp, 1)
    m["MarketPenalty"] = 0.0
    m["QuantScore"] = round(dq * (growth + prof + val + mkt), 2)


def data_quality(m):
    s = 0.0
    src = m["SalesReportCount"]
    s += 0.28 if src >= 24 else 0.16 if src >= 12 else 0.09 if src >= 6 else 0.0
    prc = m.get("ProfitReportCount") or 0
    s += 0.28 if prc >= 16 else 0.16 if prc >= 8 else 0.09 if prc >= 4 else 0.0
    mdc = m["MarketDaysCount"] or 0
    s += 0.21 if mdc >= 90 else 0.13 if mdc >= 30 else 0.06 if mdc >= 10 else 0.0
    if m["LatestPrice"] is not None and m["LatestPrice"] > 0:
        s += 0.09
    age = m["ProfitReportAgeMonths"]
    if age is not None:
        s += 0.08 if age <= 5 else 0.045 if age <= 8 else 0.0
    age_d = m["MarketDataAgeDays"]
    if age_d is not None:
        s += 0.06 if age_d <= 7 else 0.035 if age_d <= 14 else 0.0
    return s


def compare(metrics):
    ref_rows = list(csv.DictReader(open(REF / "v37_full_snapshot.csv", encoding="utf-8-sig")))
    ref = {r["Symbol"]: r for r in ref_rows}
    cols = [("SalesLast12M", "SalesLast12M"), ("SalesPrev12M", "SalesPrev12M"),
            ("SalesGrowth12M", "SalesGrowth12M"), ("TTMNetProfit", "TTMNetProfit"),
            ("PEApprox", "PEApprox"), ("QuantScore", "QuantScore"),
            ("OperatingMargin12M", "OperatingMargin12M"),
            ("NetProfitMargin12M", "NetProfitMargin12M"), ("ROE", "ROE")]
    lines = ["# Faithful v3.7 compat — metric comparison", "",
             "| reference column | compared | exact | within tol | mismatch | max abs |",
             "| --- | --- | --- | --- | --- | --- |"]
    outdir = OUT / "comparison_data"
    outdir.mkdir(parents=True, exist_ok=True)
    allrows = []
    for pk, rk in cols:
        ex = wi = mm = cmp_ = 0
        diffs = []
        for sym, m in metrics.items():
            r = ref.get(sym)
            rv_raw = r.get(rk) if r else None
            try:
                rv = float(rv_raw) if rv_raw not in (None, "", "None") else None
            except Exception:
                rv = None
            sv = m.get(pk)
            sv = float(sv) if sv is not None else None
            cmp_ += 1
            if rv is None and sv is None:
                ex += 1
            elif rv is None or sv is None:
                mm += 1
            else:
                d = abs(sv - rv)
                tol = (1e-6 * max(1.0, abs(rv))) if rk in ("SalesLast12M", "SalesPrev12M", "TTMNetProfit") else 1e-2
                if d == 0:
                    ex += 1
                elif d <= tol:
                    wi += 1
                else:
                    mm += 1
                diffs.append(d)
            allrows.append([sym, rk, rv_raw, sv, ("" if (rv is None or sv is None) else abs(sv - rv))])
        mx = max(diffs) if diffs else 0.0
        lines.append(f"| {rk} | {cmp_} | {ex} | {wi} | {mm} | {mx:.6g} |")
    lines.append("")
    lines.append(f"- canonical companies computed: {len(metrics)}; reference rows: {len(ref_rows)}")

    # ---- rank column parity (independent of QuantScore) ----
    rank_cols = [k for k in metrics[next(iter(metrics))].keys() if k.endswith("Rank")]
    rank_cols.sort()
    rlines = ["", "## Rank factor parity (v3.7 rank columns)", "",
              "| factor rank | compared | exact | within 0.01 | mismatch | max abs |",
              "| --- | --- | --- | --- | --- | --- |"]
    for rc in rank_cols:
        ex = wi = mm = cmp_ = 0
        diffs = []
        for sym, m in metrics.items():
            r = ref.get(sym)
            rv_raw = r.get(rc) if r else None
            try:
                rv = float(rv_raw) if rv_raw not in (None, "", "None") else None
            except Exception:
                rv = None
            sv = m.get(rc)
            if rv is None and sv is None:
                ex += 1; continue
            cmp_ += 1
            if rv is None or sv is None:
                mm += 1; continue
            d = abs(float(rv) - float(sv))
            if d == 0:
                ex += 1
            elif d <= 0.01:
                wi += 1
            else:
                mm += 1
            diffs.append(d)
        mx = max(diffs) if diffs else 0.0
        rlines.append(f"| {rc} | {cmp_} | {ex} | {wi} | {mm} | {mx:.4g} |")
    lines += rlines
    (OUT / "metric_comparison_faithful.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # full computed dump vs reference for deep debugging
    dump_cols = ["SalesReportCount", "MarketDaysCount", "SalesLast12M", "SalesPrev12M",
                 "SalesGrowth12M", "SalesGrowth3M", "SalesStability", "TTMNetProfit",
                 "TTMNetProfitP1", "TTMNetProfitPrev", "SR_TTMNetProfit", "NPUnitRatio",
                 "TTMOperatingProfit", "TTMOperatingProfitPrev", "OperatingMargin12M",
                 "OperatingMarginTrend", "NetProfitMargin12M", "ROE", "PEApprox", "TTMEPS",
                 "LatestPrice", "LatestClosingPrice", "PriceReturn7D", "PriceReturn30D",
                 "PriceReturn90D", "AvgTradeValue30D", "Volatility30D",
                 "NetProfitGrowthTTM", "OperatingProfitGrowthTTM",
                 "SalesGrowthRank", "NetProfitGrowthRank", "OperatingProfitGrowthRank",
                 "LowVolatilityRank", "PERank", "OperatingMarginRank", "QuantScore"]
    with (outdir / "computed_all.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol"] + [f"compat__{c}" for c in dump_cols] + [f"ref__{c}" for c in dump_cols])
        for sym in sorted(metrics):
            m = metrics[sym]
            r = ref.get(sym, {})
            def rv(c):
                x = r.get(c) if r else None
                return x if x not in (None,) else ""
            w.writerow([sym] + [m.get(c) for c in dump_cols] + [rv(c) for c in dump_cols])
    with (outdir / "comparison_faithful.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "metric", "reference", "compat", "abs_diff"])
        w.writerows(allrows)
    for ln in lines:
        print(ln)


if __name__ == "__main__":
    raise SystemExit(main())
