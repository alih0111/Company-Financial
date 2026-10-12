#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۹ / P3 — بازیابی واقعی پوشش با منابع موجود (فقط‌خواندنی، بدون backfill).

الف) ۳۲ شرکت Q+V بدون T: علت دقیق نقص T را از خود آرتیفکت + بازپخش ریاضی
    پنجرهٔ T روی market.price_observations (جلسه فقط‌خواندنی، PIT ≤ cutoff)
    استخراج می‌کند و می‌سنجد آیا با همان دادهٔ موجود، مومنتوم معتبر قابل
    محاسبه است یا مانع ماهوی (کهنه/gap مشکوک/تاریخچهٔ کوتاه) هست.

ب) ۱۷۰ شرکت با مشکل equity: جدا می‌کند «واقعاً فاقد ترازنامه» از «ترازنامه
    موجود اما حل‌نشده» با شمارش واقعی جدول‌های fundamentals.

هیچ نوشتنی در DB انجام نمی‌شود؛ هیچ داده‌ای جایگزین/حدس نمی‌شود.
خروجی: provenance_v1/output/recovery_2k9_<TAG>.json
"""

import datetime as dt
import json
import math
import os
import re
from collections import Counter

import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)

# ثابت‌های رسمی قرارداد T (از score_v2_t_raw.py) — تکرار نمی‌شوند، فقط خوانده می‌شوند
PRICE_FLOOR = 100.0
STALE_DAYS = 14
JUMP_BAND = 0.21
VOL_WINDOW_CLOSES = 31
VOL_MIN_RETURNS = 10
LIQ_WINDOW_OBS = 30
LIQ_MIN_OBS = 10
WINDOW_MAX_SPAN_DAYS = 60


def build_dsn():
    txt = open(os.path.join(ROOT, "go-app", ".env"), encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


def months_back(d, months):
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(d.day, last))


cov = json.load(open(os.path.join(OUT, f"coverage_full_2k9_{TAG}.json"), encoding="utf-8"))
by_state = {}
for r in cov["per_company"]:
    by_state.setdefault(r["state"], []).append(r)
ttf = by_state.get("TTF", [])
equity_ids = [r for r in cov["per_company"]
              if not r["v_eligible"] and any(b["code"] in ("equity_missing_pb", "equity_and_earnings_missing")
                                             for b in r["blockers"])]

conn = psycopg.connect(build_dsn(), connect_timeout=20)
conn.execute("SET default_transaction_read_only = on")


def primary_security(cid):
    r = conn.execute("""
        SELECT s.id::text FROM core.securities s
        WHERE s.company_id = %s AND s.is_active
        ORDER BY s.is_primary DESC,
                 (SELECT count(*) FROM market.price_observations p0 WHERE p0.security_id = s.id) DESC,
                 s.id::text DESC LIMIT 1""", (cid,)).fetchone()
    return r[0] if r else None


def load_price_rows(sid):
    rows = conn.execute("""
        SELECT trade_date, closing_price_rial, trade_value_rial, collected_at
        FROM market.price_observations
        WHERE security_id = %s AND collected_at <= %s
        ORDER BY trade_date DESC, collected_at DESC""", (sid, CUTOFF)).fetchall()
    seen = {}
    for td, c, tv, ca in rows:
        if td in seen:
            continue
        seen[td] = (float(c) if c is not None else None, float(tv) if tv is not None else None)
    days = [{"date": d, "close": v[0], "tv": v[1]} for d, v in sorted(seen.items())]
    return days


def t_diagnosis(days):
    """بازپخش دقیق دروازه‌های T روی سری قیمت یک شرکت → علت قطعی رد."""
    valid = [(r["date"], r["close"]) for r in days
             if r["close"] is not None and math.isfinite(r["close"]) and r["close"] >= PRICE_FLOOR]
    d = {"n_rows": len(days), "n_valid_closes": len(valid)}
    if not valid:
        d["cause"] = "no_price_history"
        return d
    last_d, last_c = valid[-1]
    age = (AS_OF - last_d).days
    d["last_trade_date"] = str(last_d)
    d["price_age_days"] = age
    span_all = (valid[-1][0] - valid[0][0]).days
    d["history_span_days"] = span_all
    causes = []
    if age > STALE_DAYS:
        causes.append("price_stale")
    # مومنتوم ۶ماهه و ۳ماهه
    for fid, months in (("momentum_6m_rel", 6), ("momentum_3m_rel", 3)):
        ref = months_back(AS_OF, months)
        base = None
        for dd, cc in valid:
            if dd <= ref:
                base = (dd, cc)
            else:
                break
        if base is None:
            causes.append(f"insufficient_history_{months}m(ref={ref})")
            d[f"{fid}_base_date"] = None
            continue
        chain = valid[valid.index(base):]
        gaps = []
        for (d1, c1), (d2, c2) in zip(chain, chain[1:]):
            r = c2 / c1 - 1.0 if c1 > 0 else None
            if r is not None and abs(r) >= JUMP_BAND:
                gaps.append({"date": str(d2), "ret": round(r, 4)})
        d[f"{fid}_base_date"] = str(base[0])
        if gaps:
            causes.append(f"suspected_unadjusted_gap_{months}m")
            d[f"{fid}_gaps"] = gaps[:3]
    # پنجرهٔ نوسان
    vc = valid[-VOL_WINDOW_CLOSES:]
    vspan = (vc[-1][0] - vc[0][0]).days if len(vc) >= 2 else None
    d["vol_span_days"] = vspan
    d["vol_n_closes"] = len(vc)
    if vspan is not None and vspan > WINDOW_MAX_SPAN_DAYS:
        causes.append("vol_window_overlong")
    # پنجرهٔ نقدشوندگی
    win = days[-LIQ_WINDOW_OBS:]
    tvs = [r["tv"] for r in win if r["tv"] is not None and r["tv"] >= 0]
    lspan = (win[-1]["date"] - win[0]["date"]).days if len(win) >= 2 else None
    d["liq_sessions"] = len(win)
    d["liq_valid_tvs"] = len(tvs)
    d["liq_span_days"] = lspan
    if len(tvs) < LIQ_MIN_OBS:
        causes.append("liquidity_insufficient_obs")
    if lspan is not None and lspan > WINDOW_MAX_SPAN_DAYS:
        causes.append("liq_window_overlong")
    d["causes"] = causes
    d["cause"] = causes[0] if causes else "would_be_valid"
    # آیا تنها مانع، کهنگی است و با snapshot تازه‌تر رفع می‌شود؟
    d["blocking_is_only_staleness"] = (causes == ["price_stale"])
    d["blocking_is_gap"] = any("gap" in c for c in causes)
    d["blocking_is_short_history"] = any("insufficient_history" in c for c in causes)
    return d


# ── الف) ۳۲ شرکت Q+V بدون T ────────────────────────────────────────────────
t_rows = []
cause_counter = Counter()
for r in ttf:
    cid = r["company_id"]
    sid = primary_security(cid)
    rec = {"company_id": cid, "symbol": r["symbol"], "industry": r["industry"],
           "artifact_state": r["state"], "primary_security": sid}
    if not sid:
        rec["cause"] = "no_active_security"
        t_rows.append(rec)
        cause_counter["no_active_security"] += 1
        continue
    diag = t_diagnosis(load_price_rows(sid))
    rec.update(diag)
    t_rows.append(rec)
    cause_counter[diag["cause"]] += 1

# کنترل ریاضی: نمونه‌ای از ۶۲ شرکت واجد T باید «would_be_valid» بدهد
t_pilot = json.load(open(os.path.join(ART, "v2_t_pilot.json"), encoding="utf-8"))
tc = t_pilot["t_observed_report"]["companies"]
triple_ids = [cid for cid in tc if tc[cid].get("pilot_eligible")]
control = []
for cid in triple_ids[:6]:
    sid = primary_security(cid)
    diag = t_diagnosis(load_price_rows(sid)) if sid else {"cause": "no_active_security"}
    control.append({"company_id": cid, "symbol": tc[cid].get("symbol"),
                    "our_cause": diag.get("cause"),
                    "artifact_t_eligible": True})
control_ok = all(c["our_cause"] == "would_be_valid" for c in control)

# ── ب) ۱۷۰ شرکت با مشکل equity ──────────────────────────────────────────────
eq_rows = []
eq_class = Counter()
for r in equity_ids:
    cid = r["company_id"]
    n_bs = conn.execute("""SELECT count(*) FROM fundamentals.financial_statements
                           WHERE company_id=%s AND statement_type='balance_sheet'""", (cid,)).fetchone()[0]
    n_te = conn.execute("""SELECT count(*) FROM fundamentals.financial_facts f
                           JOIN fundamentals.financial_statements s ON s.id=f.statement_id
                           WHERE s.company_id=%s AND f.metric_code='total_equity'""", (cid,)).fetchone()[0]
    n_is = conn.execute("""SELECT count(*) FROM fundamentals.financial_statements
                           WHERE company_id=%s AND statement_type='income_statement'""", (cid,)).fetchone()[0]
    if n_te > 0:
        klass = "total_equity_fact_present"
    elif n_bs > 0:
        klass = "balance_sheet_present_no_equity_fact"
    elif n_is > 0:
        klass = "only_income_statement"
    else:
        klass = "no_financial_statements"
    eq_class[klass] += 1
    eq_rows.append({"company_id": cid, "symbol": r["symbol"], "industry": r["industry"],
                    "n_balance_sheets": n_bs, "n_total_equity_facts": n_te,
                    "n_income_statements": n_is, "class": klass})
# پیش‌نمایش sandbox برای شرکت‌هایی که ترازنامه/فکت equity در مخزن دارند اما
# در آرتیفکت V حل نشده‌اند: آیا قابل بازیابی از دادهٔ موجودند؟
metrics = json.load(open(os.path.join(ART, "canonical_v1_metrics.json"), encoding="utf-8"))
BALANCE_SHEET_STALE_DAYS = 366  # از construction.freshness_policy آرتیفکت V
preview = []
for r in eq_rows:
    if r["class"] == "only_income_statement":
        continue
    cid = r["company_id"]
    te = conn.execute("""
        SELECT s.period_end_date, f.canonical_value FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements s ON s.id = f.statement_id
        WHERE s.company_id=%s AND f.metric_code='total_equity'
        ORDER BY s.period_end_date DESC""", (cid,)).fetchall()
    bs = conn.execute("""SELECT max(period_end_date) FROM fundamentals.financial_statements
        WHERE company_id=%s AND statement_type='balance_sheet'""", (cid,)).fetchone()[0]
    period = te[0][0] if te else bs
    age = (AS_OF - period).days if period else None
    vals = sorted({float(v) for _, v in te if v is not None})
    mc = (metrics.get(cid) or {}).get("market_cap")
    pb_ind = None
    if vals and mc and vals[-1] > 0:
        pb_ind = round(mc / vals[-1], 4)
    preview.append({
        "company_id": cid, "symbol": r["symbol"], "class": r["class"],
        "latest_period_end": str(period) if period else None,
        "period_age_days": age,
        "within_balance_sheet_staleness_policy": (age is not None and age <= BALANCE_SHEET_STALE_DAYS),
        "n_distinct_equity_values_same_or_prior": len(vals),
        "equity_conflict": len(vals) > 1,
        "equity_latest": vals[-1] if vals else None,
        "indicative_pb_sandbox": pb_ind,
        "vintage_note": "ارزش دفتری از مخزن fundamentals (به‌روز)؛ market_cap از canonical_v1_metrics (وینتیج متفاوت) — فقط پیش‌نمایش، نه انتشار",
    })
eq_preview = {
    "recoverable_now_from_existing_data": [
        p for p in preview if p["within_balance_sheet_staleness_policy"]],
    "n_recoverable_now": sum(1 for p in preview if p["within_balance_sheet_staleness_policy"]),
    "n_truly_missing": eq_class.get("only_income_statement", 0),
    "rows": preview,
}

out = {
    "artifact": "recovery_2k9",
    "version": "2k9-recovery-v1",
    "snapshot_tag": TAG,
    "read_only": True,
    "db_writes": 0,
    "source": "market.price_observations + fundamentals.financial_statements/facts (session: default_transaction_read_only=on)",
    "as_of": str(AS_OF), "cutoff": CUTOFF.isoformat(),
    "priority1_T_recovery": {
        "n_targets": len(ttf),
        "cause_counts": dict(cause_counter),
        "recoverable_now_with_existing_data": sum(1 for r in t_rows if r.get("cause") == "would_be_valid"),
        "needs_price_data_or_corporate_action": sum(1 for r in t_rows if r.get("blocking_is_gap") or r.get("blocking_is_short_history")),
        "needs_only_fresher_snapshot": sum(1 for r in t_rows if r.get("blocking_is_only_staleness")),
        "control_matches_artifact": control_ok,
        "control_sample": control,
        "rows": t_rows,
        "note": "علت قطعی هر شرکت از بازپخش دقیق همان دروازه‌های قرارداد T روی دادهٔ موجود است؛ "
                "جمع anyCause ≥ n_targets چون یک شرکت می‌تواند چند مانع داشته باشد.",
    },
    "priority2_equity_recovery": {
        "n_targets": len(equity_ids),
        "class_counts": dict(eq_class),
        "rows": eq_rows,
        "db_wide_facts": {
            "n_balance_sheet_statements_total": conn.execute(
                "SELECT count(*) FROM fundamentals.financial_statements WHERE statement_type='balance_sheet'").fetchone()[0],
            "n_total_equity_facts_total": conn.execute(
                "SELECT count(*) FROM fundamentals.financial_facts WHERE metric_code='total_equity'").fetchone()[0],
        },
        "note": "شمارش واقعی جداول؛ «truly missing» = نه ترازنامه و نه فکت equity در مخزن.",
        "equity_recovery_preview": eq_preview,
    },
}
p = os.path.join(OUT, f"recovery_2k9_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print("wrote:", p, os.path.getsize(p), "bytes")
print("T targets:", len(ttf), "| causes:", dict(cause_counter))
print("T control matches artifact:", control_ok, "|", [(c["symbol"], c["our_cause"]) for c in control])
print("equity targets:", len(equity_ids), "| classes:", dict(eq_class))
