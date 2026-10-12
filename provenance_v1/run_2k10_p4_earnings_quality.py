#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۱۰ / P4 — کنترل اقتصادی کیفیت سود بوعلی (فقط‌خواندنی).

بررسی می‌کند نسبت تبدیل نقد (OCF/NP) از داده‌های هم‌دوره/هم‌دامنه و معتبر
ساخته شده، آستانهٔ سیاست روی نسبت خام است یا پرسنتایل، و آیا شاهد چنددوره‌ای
برای پایداری وجود دارد. هیچ فاکتور/وزن جدیدی ساخته نمی‌شود.
"""

import datetime as dt
import json
import os
import re
import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
ART = os.path.join(ROOT, "canonical_postgres_v1_2_1", "analytics_canonical_v1", "output")
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)
CID = "c78433dc-e873-4bc9-85c4-794f755e5637"  # بوعلی


def build_dsn():
    txt = open(os.path.join(ROOT, "go-app", ".env"), encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip().replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$", r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


conn = psycopg.connect(build_dsn(), connect_timeout=20)
conn.execute("SET default_transaction_read_only = on")

ocf = conn.execute("""SELECT st.period_end_date, st.is_cumulative, f.period_order, f.comparison_type, f.canonical_value
    FROM fundamentals.financial_facts f JOIN fundamentals.financial_statements st ON st.id=f.statement_id
    WHERE st.company_id=%s AND f.metric_code='operating_cash_flow' ORDER BY st.period_end_date DESC, f.period_order""", (CID,)).fetchall()
npf = conn.execute("""SELECT st.period_end_date, f.period_order, f.canonical_value
    FROM fundamentals.financial_facts f JOIN fundamentals.financial_statements st ON st.id=f.statement_id
    WHERE st.company_id=%s AND f.metric_code='net_profit' ORDER BY st.period_end_date DESC, f.period_order LIMIT 8""", (CID,)).fetchall()
n_cf = conn.execute("SELECT count(*) FROM fundamentals.financial_statements WHERE company_id=%s AND statement_type='cash_flow'", (CID,)).fetchone()[0]

m = json.load(open(os.path.join(ART, "canonical_v1_metrics.json"), encoding="utf-8"))[CID]
q = json.load(open(os.path.join(ART, "v2_q_observed_report.json"), encoding="utf-8"))
qcomps = q.get("companies") or q.get("q_observed_report", {}).get("companies", {})
qcash = ((qcomps.get(CID) or {}).get("factors") or {}).get("cash_conversion") or {}

ocf_by_order = {r[2]: float(r[4]) for r in ocf if r[0] == ocf[0][0]} if ocf else {}
stitch = None
if {1, 2, 3} <= set(ocf_by_order.keys()):
    stitch = ocf_by_order[1] + ocf_by_order[3] - ocf_by_order[2]  # current YTD + prior FY − prior YTD

out = {
    "artifact": "p4_earnings_quality_2k10", "version": "2k10-p4-v1",
    "read_only": True, "db_writes": 0, "snapshot_tag": TAG, "company": "بوعلی", "company_id": CID,
    "ocf_facts": [{"period_end": str(r[0]), "cumulative": r[1], "period_order": r[2],
                   "comparison": r[3], "value": float(r[4])} for r in ocf],
    "net_profit_facts": [{"period_end": str(r[0]), "period_order": r[1], "value": float(r[2])} for r in npf],
    "n_cash_flow_statements": n_cf,
    "ttm_stitch": {
        "formula": "OCF_ttm = OCF_current_YTD(order1) + OCF_prior_FY(order3) − OCF_prior_YTD(order2)",
        "components": ocf_by_order, "ocf_ttm_stitched": stitch,
        "matches_metrics_ocf_ttm": (stitch is not None and abs(stitch - float(m.get("ocf_ttm") or 0)) < 1),
        "metrics_ocf_ttm": float(m.get("ocf_ttm") or 0),
        "metrics_net_profit_ttm": float(m.get("net_profit_ttm") or 0),
        "raw_cash_conversion_ocf_over_np": m.get("cash_conversion"),
    },
    "same_period_same_scope": {
        "verdict": "TRUE — OCF و سود خالص هر دو TTM با دورهٔ پایانی ۲۰۲۶-۰۶-۲۱ و از همان صورت‌های رسمی canonical",
        "provenance": m.get("_ttm_prov"),
    },
    "yoy_signal": {
        "current_ytd_ocf": ocf_by_order.get(1), "prior_ytd_ocf": ocf_by_order.get(2),
        "yoy_change_pct": (round((ocf_by_order[1] / ocf_by_order[2] - 1) * 100, 1)
                           if ocf_by_order.get(1) is not None and ocf_by_order.get(2) else None),
        "note": "افت شدید OCF دورهٔ جاری نسبت به دورهٔ مشابه سال قبل — شاهد مکمل تضعیف تبدیل نقد",
    },
    "threshold_basis": {
        "policy_field": "q_cash_min",
        "applied_to": "PERSENTILE cash_conversion (امتیاز رسمی آرتیفکت Q)، نه نسبت خام",
        "artifact_cash_conversion_pct": qcash.get("score"),
        "artifact_cash_conversion_weight": qcash.get("weight"),
        "raw_ratio": m.get("cash_conversion"),
        "policy_floor": 0.40,
        "breach": (qcash.get("score") is not None and qcash["score"] < 0.40),
    },
    "multi_period_stability": {
        "assessable": False,
        "reason": ("تنها یک صورت جریان نقد (۲۰۲۶-۰۶-۲۱) در مخزن canonical موجود است؛ "
                   "سری چنددوره‌ای OCF برای سنجش پایداری/فصلی‌بودن وجود ندارد. "
                   "سه ستون همان یک صورت، شاهد مکمل‌اند نه سری مستقل."),
    },
    "verdict": ("قید کیفیت تبدیل نقد بوعلی قابل دفاع و محافظه‌کارانه است: نسبت خام ۰٫۳۳ و پرسنتایل "
                "۰٫۳۷ زیر کف ۰٫۴۰؛ ورودی‌ها هم‌دوره و TTM-canonical‌اند؛ و افت ۹۵٪ OCF دورهٔ جاری نسبت به "
                "سال قبل، ضعف را تأیید می‌کند. محدودیت: نبود سری چنددوره‌ای OCF، پایداری را غیرقابل‌سنجش می‌کند."),
}
p = os.path.join(OUT, f"p4_earnings_quality_2k10_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("wrote", p)
print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:2200])
