#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۱۰ / P2 — بازیابی واقعی equity برای شرکت‌های دارای ترازنامه (فقط‌خواندنی).

۱) توضیح اختلاف ۱۷۰ (۲-ک-۸) و ۱۷۲ (۲-ک-۹): تفکیک دقیق کدهای مانع V.
۲) برای ۱۰ شرکت نامزد: آیا equity با قاعدهٔ اعتبار (دوره، کهنگی، علامت) از
   منابع رسمی موجود واقعاً قابل بازیابی است؟ دو مسیر:
     - فکت رسمی total_equity با period_order=1
     - اشتقاق equity = total_assets − total_liabilities (فقط اگر فکت‌های رسمی
       هر دو موجود و هم‌دوره باشند) ← نیازمند مجوز رسمی؛ اینجا فقط پیش‌نمایش
۳) محاسبهٔ sandbox P/B = market_cap / equity و اثر واقعی بر پوشش V.

هیچ نوشتن DB؛ هیچ backfill؛ هیچ مقدار حدسی.
"""

import datetime as dt
import json
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
BS_STALE_DAYS = 366


def build_dsn():
    txt = open(os.path.join(ROOT, "go-app", ".env"), encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


conn = psycopg.connect(build_dsn(), connect_timeout=20)
conn.execute("SET default_transaction_read_only = on")

cov = json.load(open(os.path.join(OUT, f"coverage_full_2k9_{TAG}.json"), encoding="utf-8"))
c8 = json.load(open(os.path.join(OUT, f"coverage_analysis_2k8_{TAG}.json"), encoding="utf-8"))
metrics = json.load(open(os.path.join(ART, "canonical_v1_metrics.json"), encoding="utf-8"))
p1 = json.load(open(os.path.join(OUT, f"p1_valuation_reconciliation_2k10_{TAG}.json"), encoding="utf-8"))
p1_price = {r["company_id"]: r for r in p1["rows"]}
v_art = json.load(open(os.path.join(ART, "v2_value_pilot.json"), encoding="utf-8"))["v_observed_report"]["companies"]
q_art = json.load(open(os.path.join(ART, "v2_q_observed_report.json"), encoding="utf-8"))
q_comps = q_art.get("companies") or q_art.get("q_observed_report", {}).get("companies", {})

# ── ۱) تفکیک کدهای مانع V ───────────────────────────────────────────────────
v_block_codes = Counter()
for r in cov["per_company"]:
    for b in r["blockers"]:
        if b["axis"] == "v":
            v_block_codes[b["code"]] += 1
equity_related = {"equity_missing_pb", "equity_and_earnings_missing"}
n_equity_related = sum(v_block_codes[c] for c in equity_related)

# ── ۲) ۱۰ نامزد ─────────────────────────────────────────────────────────────
targets = [r for r in cov["per_company"]
           if not r["v_eligible"] and any(b["code"] in equity_related for b in r["blockers"])]
print("n targets:", len(targets))


def latest_price_shares(cid):
    sid = conn.execute("""SELECT s.id::text FROM core.securities s WHERE s.company_id=%s AND s.is_active
        ORDER BY s.is_primary DESC, (SELECT count(*) FROM market.price_observations p WHERE p.security_id=s.id) DESC LIMIT 1""",
        (cid,)).fetchone()
    if not sid:
        return None, None, None
    sid = sid[0]
    px = conn.execute("""SELECT closing_price_rial, last_price_rial FROM market.price_observations
        WHERE security_id=%s AND collected_at<=%s ORDER BY trade_date DESC, collected_at DESC LIMIT 1""",
        (sid, CUTOFF)).fetchone()
    sh = conn.execute("""SELECT shares_count FROM market.tsetmc_current_shares WHERE security_id=%s
        ORDER BY collected_at DESC LIMIT 1""", (sid,)).fetchone()
    if not sh:
        sh = conn.execute("""SELECT shares_count FROM core.share_structure WHERE company_id=%s
            ORDER BY as_of_date DESC, collected_at DESC LIMIT 1""", (cid,)).fetchone()
    price = float(px[1] or px[0]) if px else None
    shares = float(sh[0]) if sh else None
    return price, shares, sid


def equity_fact(cid):
    r = conn.execute("""SELECT st.period_end_date, f.canonical_value, rv.collected_at
        FROM fundamentals.financial_facts f JOIN fundamentals.financial_statements st ON st.id=f.statement_id
        JOIN ingestion.report_versions rv ON rv.id=st.report_version_id
        WHERE st.company_id=%s AND f.metric_code='total_equity' AND f.period_order=1 AND rv.collected_at<=%s
        ORDER BY st.period_end_date DESC LIMIT 1""", (cid, CUTOFF)).fetchone()
    return r


def derive_facts(cid):
    rows = conn.execute("""SELECT f.metric_code, f.period_order, f.canonical_value, st.period_end_date
        FROM fundamentals.financial_facts f JOIN fundamentals.financial_statements st ON st.id=f.statement_id
        JOIN ingestion.report_versions rv ON rv.id=st.report_version_id
        WHERE st.company_id=%s AND st.statement_type='balance_sheet' AND rv.collected_at<=%s
          AND f.metric_code IN ('total_assets','total_liabilities','total_equity')
        ORDER BY st.period_end_date DESC, f.period_order""", (cid, CUTOFF)).fetchall()
    return rows


def bs_metric_census(cid):
    return conn.execute("""SELECT f.metric_code, count(*)
        FROM fundamentals.financial_facts f JOIN fundamentals.financial_statements st ON st.id=f.statement_id
        WHERE st.company_id=%s AND st.statement_type='balance_sheet' GROUP BY 1 ORDER BY 2 DESC LIMIT 8""",
        (cid,)).fetchall()


rows = []
triple_after = []
for r in targets:
    cid = r["company_id"]
    price, shares, sid = latest_price_shares(cid)
    ef = equity_fact(cid)
    eq_val = float(ef[1]) if ef else None
    eq_period = ef[0] if ef else None
    age = (AS_OF - eq_period).days if eq_period else None
    mcap = (price * shares) if (price and shares) else None
    pb = round(mcap / eq_val, 4) if (mcap and eq_val and eq_val > 0) else None
    derived = None
    if eq_val is None:
        dr = derive_facts(cid)
        assets = next((float(x[2]) for x in dr if x[0] == "total_assets" and x[1] == 1), None)
        liab = next((float(x[2]) for x in dr if x[0] == "total_liabilities" and x[1] == 1), None)
        same_period = len({x[3] for x in dr}) == 1 if dr else False
        if assets is not None and liab is not None:
            derived = {"total_assets": assets, "total_liabilities": liab,
                       "equity_derived": assets - liab, "same_period": same_period}
    vf = (v_art.get(cid) or {}).get("factors") or {}
    pb_art = (vf.get("pb") or {}).get("raw_status")
    if pb is not None and pb_art != "valid":
        verdict = "resolver_gap_pb_recoverable_in_sandbox"
    elif pb_art == "valid":
        verdict = "already_resolved_pb_not_the_blocker"
    elif derived and derived.get("equity_derived", 0) > 0 and derived.get("same_period"):
        verdict = "derivation_requires_permission"
    else:
        verdict = "not_recoverable_no_valid_equity_data"
    # اثر بر پوشش: با بازیابی Q و V، آیا سه‌محوری می‌شود؟ (T کلید باقی‌مانده)
    triple_if_qv = bool(r["t_eligible"]) and verdict in (
        "resolver_gap_pb_recoverable_in_sandbox", "already_resolved_pb_not_the_blocker")
    if triple_if_qv:
        triple_after.append(r["symbol"])
    rows.append({
        "company_id": cid, "symbol": r["symbol"], "industry": r["industry"],
        "state": r["state"], "q_eligible": r["q_eligible"], "t_eligible": r["t_eligible"],
        "v_blockers": [b["code"] for b in r["blockers"] if b["axis"] == "v"],
        "price": price, "shares": shares, "market_cap": mcap,
        "equity_fact": eq_val, "equity_period": str(eq_period) if eq_period else None,
        "equity_age_days": age, "within_bs_stale_policy": (age is not None and age <= BS_STALE_DAYS),
        "sandbox_pb": pb, "artifact_pb_status": pb_art, "derivation": derived,
        "balance_sheet_metric_census": {m: n for m, n in bs_metric_census(cid)},
        "verdict": verdict,
        "would_make_triple_with_qv": triple_if_qv,
    })

vc = Counter(x["verdict"] for x in rows)
out = {
    "artifact": "p2_equity_recovery_2k10", "version": "2k10-p2-v1",
    "read_only": True, "db_writes": 0, "snapshot_tag": TAG,
    "as_of": str(AS_OF), "cutoff": CUTOFF.isoformat(),
    "discrepancy_170_vs_172": {
        "2k8_v_store_facts_n_equity_missing": c8["v_store_facts"]["n_equity_missing"],
        "2k8_v_blockers": c8["v_blockers"],
        "2k9_equity_related_blocker_count": n_equity_related,
        "v_block_code_counts": dict(v_block_codes),
        "explanation": ("۲-ک-۸ عدد ۱۷۰ را برای «pb مفقود به‌علت نبود equity» شمرد؛ "
                        "۲-ک-۹ هر شرکتی را که among blockerهایش equity_missing_pb یا "
                        "equity_and_earnings_missing باشد و V-eligible نباشد شمرد (۱۷۲). "
                        "اختلاف ۲ = شرکت‌هایی که نبود equity همراه با مانع دیگر (مثلاً earnings) ثبت شده."),
    },
    "targets": rows,
    "verdict_counts": dict(vc),
    "n_resolver_gap_pb": sum(1 for x in rows if x["verdict"] == "resolver_gap_pb_recoverable_in_sandbox"),
    "n_already_resolved_pb": sum(1 for x in rows if x["verdict"] == "already_resolved_pb_not_the_blocker"),
    "triple_if_qv_recovered": triple_after,
    "note": ("«resolver_gap_pb_recoverable_in_sandbox» = فکت رسمی total_equity (period_order=1) درون "
             "سیاست کهنگی موجود است و P/B در sandbox محاسبه می‌شود، اما آرتیفکت V آن را حل نکرده "
             "(شکاف resolver). «already_resolved» = P/B در آرتیفکت هست و equity مانع نبوده. "
             "«derivation» = اشتقاق assets−liabilities نیازمند مجوز رسمی. هیچ برآورد/حدسی ثبت نشده. "
             "هیچ‌یک از این ۱۷۲ شرکت با بازیابی equity به سه‌محوری تبدیل نمی‌شود مگر T نیز موجود باشد."),
}
p = os.path.join(OUT, f"p2_equity_recovery_2k10_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("wrote", p)
print("v_block_code_counts:", dict(v_block_codes), "| n_equity_related:", n_equity_related, "| 2k8 said", c8["v_store_facts"]["n_equity_missing"])
print("verdicts:", dict(vc))
for x in rows:
    print(f"{x['symbol']:>8} eq={x['equity_fact']} age={x['equity_age_days']} pb={x['sandbox_pb']} der={bool(x['derivation'])} -> {x['verdict']}")
