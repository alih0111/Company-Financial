#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۱۰ / P1 (نسخهٔ کامل) — مصالحهٔ زنجیرهٔ قیمت↔سهام↔ارزش‌گذاری (فقط‌خواندنی).

الف) برای همهٔ ۲۷۱ شرکت (و به‌طور تفکیکی ۶۲ سهمحوری): آیا مبنای «قیمت × سهام»
    در این snapshot *قابل اثبات* است؟
    - تعداد رصدهای سهام و پایداری آن‌ها
    - فاصلهٔ تاریخ آخرین سهام تا تاریخ قیمت
    - اقدام شرکتی تأییدشده در آن فاصله (market.corporate_actions)
    - حکم: consistent_verified / unresolved_capital_change / unresolved_no_snapshot

ب) کارت جزءبه‌جزء بوعلی: منبع، تاریخ مؤثر، تاریخ انتشار و سطح اعتبار هر جزء +
    بازمحاسبهٔ مستقل P/E·P/B·P/S و مقایسه با آرتیفکت V.

هیچ نوشتن DB؛ هیچ جایگزینی قیمت/سهم با مقدار امروز؛ هیچ ضریب حدسی.
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

metrics = json.load(open(os.path.join(ART, "canonical_v1_metrics.json"), encoding="utf-8"))
cov = json.load(open(os.path.join(OUT, f"coverage_full_2k9_{TAG}.json"), encoding="utf-8"))
v_art = json.load(open(os.path.join(ART, "v2_value_pilot.json"), encoding="utf-8"))["v_observed_report"]["companies"]

triple = {x["company_id"] for x in cov["per_company"] if x["in_triple"]}
v_elig = {x["company_id"] for x in cov["per_company"] if x["v_eligible"]}


def prim_security(cid):
    r = conn.execute("""
        SELECT s.id::text FROM core.securities s
        WHERE s.company_id=%s AND s.is_active
        ORDER BY s.is_primary DESC,
                 (SELECT count(*) FROM market.price_observations p WHERE p.security_id=s.id) DESC,
                 s.id::text DESC LIMIT 1""", (cid,)).fetchone()
    return r[0] if r else None


def basis(cid):
    sid = prim_security(cid)
    if not sid:
        return {"verdict": "no_active_security"}
    px = conn.execute("""SELECT trade_date, closing_price_rial, last_price_rial, price_series, is_adjusted
        FROM market.price_observations WHERE security_id=%s AND collected_at<=%s
        ORDER BY trade_date DESC, collected_at DESC LIMIT 1""", (sid, CUTOFF)).fetchone()
    shares = conn.execute("""SELECT 'core.share_structure', as_of_date, shares_count FROM core.share_structure
        WHERE company_id=%s ORDER BY as_of_date DESC, collected_at DESC LIMIT 6""", (cid,)).fetchall() \
        + conn.execute("""SELECT 'market.tsetmc_current_shares', collected_at::date, shares_count
        FROM market.tsetmc_current_shares WHERE security_id=%s ORDER BY collected_at DESC LIMIT 3""", (sid,)).fetchall()
    shares = [s for s in shares if s[2] is not None]
    shares_sorted = sorted(shares, key=lambda x: (x[1], ), reverse=True)
    if not px or not shares_sorted:
        return {"verdict": "unresolved_no_snapshot",
                "has_price": bool(px), "n_share_obs": len(shares)}
    latest_share_date = shares_sorted[0][1]
    vals = {float(s[2]) for s in shares}
    gap = (px[0] - latest_share_date).days
    ca_conf = []
    if gap >= 0:
        ca_conf = conn.execute("""SELECT action_date, action_type, adjustment_factor
            FROM market.corporate_actions WHERE security_id=%s AND action_date>%s AND action_date<=%s
              AND is_confirmed""", (sid, latest_share_date, px[0])).fetchall()
    stable = len(vals) == 1
    # حکم محافظه‌کارانه: نبود اقدام ثبت‌شده در پنجرهٔ کوتاه «اثبات نبود اقدام» نیست.
    if ca_conf:
        verdict = "unresolved_capital_change_evidence"
    elif not stable:
        verdict = "unresolved_share_instability"
    else:
        verdict = "no_contradiction_short_window"
    m = metrics.get(cid, {})
    m_price = m.get("latest_price")
    latest_close = float(px[1]) if px[1] is not None else None
    latest_last = float(px[2]) if px[2] is not None else None
    stale = None
    if m_price and (latest_close is not None or latest_last is not None):
        best = max([v for v in (latest_close, latest_last) if v is not None])
        stale = abs(float(m_price) - best) > 1e-6
    return {"verdict": verdict, "price_date": str(px[0]), "price_close": latest_close,
            "price_last": latest_last, "price_series": px[3],
            "share_latest_date": str(latest_share_date),
            "n_share_obs": len(shares), "n_distinct_share_values": len(vals),
            "share_value": sorted(vals)[-1], "share_price_gap_days": gap,
            "n_confirmed_actions_in_gap": len(ca_conf),
            "metrics_latest_price": float(m_price) if m_price else None,
            "metrics_price_differs_from_latest_PIT": stale}


rows = []
for x in cov["per_company"]:
    cid = x["company_id"]
    b = basis(cid)
    b.update({"company_id": cid, "symbol": x["symbol"], "in_triple": cid in triple,
              "v_eligible": cid in v_elig})
    rows.append(b)

verdict_counts = Counter(r["verdict"] for r in rows)
verdict_counts_triple = Counter(r["verdict"] for r in rows if r["in_triple"])
verdict_counts_v = Counter(r["verdict"] for r in rows if r["v_eligible"])
n_stale = sum(1 for r in rows if r.get("metrics_price_differs_from_latest_PIT") is True)
n_stale_triple = sum(1 for r in rows if r.get("metrics_price_differs_from_latest_PIT") is True and r["in_triple"])
share_obs_dist = Counter(r.get("n_share_obs") for r in rows)
gap_dist = Counter(r.get("share_price_gap_days") for r in rows if r.get("share_price_gap_days") is not None)

# ── کارت بوعلی ──────────────────────────────────────────────────────────────
boali = next((r for r in rows if r["symbol"] == "بوعلی"), None)
bcard = None
if boali:
    cid = boali["company_id"]
    sid = prim_security(cid)
    px = conn.execute("""SELECT trade_date, closing_price_rial, last_price_rial, price_series,
               is_adjusted, adjustment_method, collected_at
        FROM market.price_observations WHERE security_id=%s AND collected_at<=%s
        ORDER BY trade_date DESC, collected_at DESC LIMIT 1""", (sid, CUTOFF)).fetchone()
    sh = conn.execute("""SELECT src, d, shares_count, collected_at FROM (
            SELECT 'core.share_structure' src, as_of_date d, shares_count, collected_at
              FROM core.share_structure WHERE company_id=%s
            UNION ALL
            SELECT 'market.tsetmc_current_shares', collected_at::date, shares_count, collected_at
              FROM market.tsetmc_current_shares WHERE security_id=%s) t
        ORDER BY d DESC, collected_at DESC LIMIT 6""", (cid, sid)).fetchall()
    eq = conn.execute("""SELECT st.period_end_date, f.canonical_value, f.canonical_unit, rv.collected_at, rv.version_no, f.period_order
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id=f.statement_id
        JOIN ingestion.report_versions rv ON rv.id=st.report_version_id
        WHERE st.company_id=%s AND f.metric_code='total_equity' AND rv.collected_at<=%s AND f.period_order=1
        ORDER BY st.period_end_date DESC LIMIT 4""", (cid, CUTOFF)).fetchall()
    eq_prior = conn.execute("""SELECT st.period_end_date, f.canonical_value, f.period_order
        FROM fundamentals.financial_facts f
        JOIN fundamentals.financial_statements st ON st.id=f.statement_id
        JOIN ingestion.report_versions rv ON rv.id=st.report_version_id
        WHERE st.company_id=%s AND f.metric_code='total_equity' AND rv.collected_at<=%s AND f.period_order=2
        ORDER BY st.period_end_date DESC LIMIT 2""", (cid, CUTOFF)).fetchall()
    mc = metrics.get(cid, {})
    mcap = mc.get("market_cap")
    np_ttm = mc.get("net_profit_ttm")
    rev_ttm = mc.get("revenue_ttm")
    mcap_price_shares = (boali["price_close"] or 0) * (boali["share_value"] or 0)
    equity_current = float(eq[0][1]) if eq else None
    def safe_div(a, b):
        return round(a / b, 4) if a and b else None
    bcard = {
        "company_id": cid,
        "price_component": {"source": "market.price_observations", "trade_date": str(px[0]),
                            "close_rial": float(px[1]) if px[1] else None,
                            "last_rial": float(px[2]) if px[2] else None,
                            "price_series": px[3], "is_adjusted": px[4],
                            "adjustment_method": px[5], "collected_at": str(px[6]),
                            "note": "آخرین ردیف معتبر PIT؛ ستون قیمت = سری تعدیل‌شدهٔ فروشنده"},
        "shares_component": [{"source": s[0], "date": str(s[1]), "shares": float(s[2]),
                              "collected_at": str(s[3])} for s in sh],
        "equity_component_period_order_1": [{"period_end": str(e[0]), "value": float(e[1]), "unit": e[2],
                              "collected_at": str(e[3]), "version": e[4], "period_order": e[5]} for e in eq],
        "equity_component_prior_year": [{"period_end": str(e[0]), "value": float(e[1]),
                              "period_order": e[2]} for e in eq_prior],
        "corporate_actions_in_gap": [],
        "market_cap_from_components": mcap_price_shares,
        "market_cap_in_artifact_metrics": float(mcap) if mcap else None,
        "metrics_latest_price": float(mc.get("latest_price")) if mc.get("latest_price") else None,
        "metrics_price_vs_latest_PIT_close": (
            None if not mc.get("latest_price") else
            round(float(mc["latest_price"]) - (boali["price_close"] or 0), 1)),
        "recompute_from_canonical_metrics": {
            "net_profit_ttm": float(np_ttm) if np_ttm else None,
            "revenue_ttm": float(rev_ttm) if rev_ttm else None,
            "pe": safe_div(mcap_price_shares, np_ttm),
            "ps": safe_div(mcap_price_shares, rev_ttm),
            "pb": safe_div(mcap_price_shares, equity_current),
        },
        "artifact_v_raw": {fid: (v_art.get(cid, {}).get("factors", {}).get(fid) or {}).get("raw_value")
                           for fid in ("pe", "pb", "ps")},
        "artifact_v_metrics_pe_pb_ps": {"pe": mc.get("pe"), "pb": mc.get("pb"), "ps": mc.get("ps")},
        "artifact_v_warnings": {fid: (v_art.get(cid, {}).get("factors", {}).get(fid) or {}).get("warnings")
                                for fid in ("pe", "pb", "ps")},
        "valuation_prov": mc.get("_valuation_prov"),
    }
    if boali.get("share_latest_date"):
        ca = conn.execute("""SELECT action_date, action_type, is_confirmed, adjustment_evidence_status
            FROM market.corporate_actions WHERE security_id=%s AND action_date>%s AND action_date<=%s
            ORDER BY action_date""", (sid, dt.date.fromisoformat(boali["share_latest_date"]), px[0])).fetchall()
        bcard["corporate_actions_in_gap"] = [{"date": str(c[0]), "type": c[1], "confirmed": c[2],
                                              "evidence": c[3]} for c in ca]

out = {
    "artifact": "p1_valuation_reconciliation_2k10", "version": "2k10-p1-v2",
    "read_only": True, "db_writes": 0, "snapshot_tag": TAG,
    "as_of": str(AS_OF), "cutoff": CUTOFF.isoformat(),
    "method": ("for each company: latest PIT price (collected_at<=cutoff), all share observations, "
               "share stability, gap days, and CONFIRMED corporate actions inside the gap; "
               "verdict consistent_verified only if share value is stable across all observations "
               "AND no confirmed capital action in the gap"),
    "universe_verdict_counts": dict(verdict_counts),
    "triple62_verdict_counts": dict(verdict_counts_triple),
    "v_eligible_verdict_counts": dict(verdict_counts_v),
    "metrics_snapshot_price_stale_vs_latest_PIT": {"universe": n_stale, "triple62": n_stale_triple},
    "share_observation_count_distribution": {str(k): v for k, v in sorted(share_obs_dist.items(), key=lambda kv: (kv[0] is None, kv[0]))},
    "share_price_gap_days_distribution": {str(k): v for k, v in sorted(gap_dist.items(), key=lambda kv: kv[0])},
    "method_caveat": ("«no_contradiction_short_window» فقط یعنی: در فاصلهٔ ثبت‌شدهٔ سهام تا قیمت "
                      "(۱ تا چند روز) هیچ اقدام شرکتی *ثبت‌شدهٔ تأییدشده* در market.corporate_actions "
                      "وجود ندارد و مقادیر سهام رصدشده ناسازگار نیستند. این «اثبات نبود اقدام» نیست؛ "
                      "زیرا رصدهای سهام تُنُک‌اند و اقدام ثبت‌نشده با این منابع قابل رد نیست."),
    "rows": rows,
    "boali_card": bcard,
}
p = os.path.join(OUT, f"p1_valuation_reconciliation_2k10_{TAG}.json")
json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)

print("wrote", p)
print("universe verdicts:", dict(verdict_counts))
print("triple62 verdicts:", dict(verdict_counts_triple))
print("v-eligible verdicts:", dict(verdict_counts_v))
print("metrics-snapshot price stale vs latest PIT:", n_stale, "| triple:", n_stale_triple)
print()
print("=== بوعلی card ===")
print(json.dumps(bcard, ensure_ascii=False, indent=1, default=str)[:2600])
