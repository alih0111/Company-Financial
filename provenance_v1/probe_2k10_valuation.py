#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
گام ۲-ک-۱۰ / P1 — کاوش فقط‌خواندنی منابع زنجیرهٔ ارزش‌گذاری
(قیمت ← تاریخ ← سهام ← اقدامات شرکتی ← نسبت‌ها). هیچ نوشتنی انجام نمی‌شود.

هدف: پیش از هر ادعای «قابل اثبات»، واقعاً ببینیم چه جدول‌ها/ردیف‌هایی برای
سهام، رویداد سرمایه و اقدامات شرکتی در مخزن canonical وجود دارد.
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

tables = [
    "core.share_structure", "market.tsetmc_current_shares",
    "core.share_events", "core.share_intervals", "market.corporate_actions",
    "market.price_observations",
]
res = {"tables": {}}
for t in tables:
    try:
        n = conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    except Exception as e:
        res["tables"][t] = {"exists": False, "err": str(e).splitlines()[0][:120]}
        conn.rollback()
        continue
    cols = conn.execute("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position""",
        tuple(t.split("."))).fetchall()
    res["tables"][t] = {"exists": True, "rows": n,
                        "columns": [f"{c}:{d}" for c, d in cols]}

# شناسه شرکت‌ها
metrics = json.load(open(os.path.join(ART, "canonical_v1_metrics.json"), encoding="utf-8"))
sym2id = {v.get("symbol"): k for k, v in metrics.items()}
res["n_metrics_companies"] = len(metrics)
res["boali_id"] = sym2id.get("بوعلی")
res["zob_id"] = sym2id.get("ذوب")
res["shspa_id"] = sym2id.get("شسپا")

# نمونهٔ بوعلی: سهام، قیمت، رویدادها
if res["boali_id"]:
    cid = res["boali_id"]
    res["boali_share_structure"] = conn.execute("""
        SELECT as_of_date, shares_count, source, collected_at FROM core.share_structure
        WHERE company_id=%s ORDER BY as_of_date DESC, collected_at DESC LIMIT 8""", (cid,)).fetchall()
    res["boali_tsetmc_shares"] = conn.execute("""
        SELECT t.collected_at, t.shares_count, t.source FROM market.tsetmc_current_shares t
        JOIN core.securities s ON s.id=t.security_id WHERE s.company_id=%s
        ORDER BY t.collected_at DESC LIMIT 8""", (cid,)).fetchall()
    res["boali_share_events"] = conn.execute("""
        SELECT * FROM core.share_events WHERE company_id=%s ORDER BY 1""", (cid,)).fetchall() \
        if conn.execute("SELECT to_regclass('core.share_events')").fetchone()[0] else []
    res["boali_securities"] = conn.execute("""
        SELECT id::text, is_active, is_primary FROM core.securities WHERE company_id=%s""", (cid,)).fetchall()

# آیا هیچ ردیفی در رویداد/اقدام شرکتی برای کل ۲۷۱ جامعه هست؟
uni = [r["company_id"] for r in json.load(
    open(os.path.join(OUT, f"coverage_full_2k9_{TAG}.json"), encoding="utf-8"))["per_company"]]
if res["tables"].get("core.share_events", {}).get("exists"):
    res["share_events_in_universe"] = conn.execute("""
        SELECT count(*) FROM core.share_events WHERE company_id = ANY(%s)""", (uni,)).fetchone()[0]
if res["tables"].get("market.corporate_actions", {}).get("exists"):
    res["corp_actions_in_universe"] = conn.execute("""
        SELECT count(*) FROM market.corporate_actions ca
        JOIN core.securities s ON s.id=ca.security_id WHERE s.company_id = ANY(%s)""", (uni,)).fetchone()[0]
    res["corp_actions_columns_sample"] = conn.execute("""
        SELECT action_type, is_confirmed, detected_heuristically, event_semantics_status,
               adjustment_evidence_status, count(*)
        FROM market.corporate_actions GROUP BY 1,2,3,4,5 ORDER BY 6 DESC LIMIT 20""").fetchall()

# share_intervals
if res["tables"].get("core.share_intervals", {}).get("exists"):
    res["share_intervals_in_universe"] = conn.execute("""
        SELECT count(*) FROM core.share_intervals WHERE company_id = ANY(%s)""", (uni,)).fetchone()[0]

def _ser(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, bytes):
        return o.decode("utf-8", "replace")
    return str(o)

res["boali_share_events"] = [list(map(_ser, r)) for r in res.get("boali_share_events", [])]
res["boali_share_structure"] = [list(map(_ser, r)) for r in res.get("boali_share_structure", [])]
res["boali_tsetmc_shares"] = [list(map(_ser, r)) for r in res.get("boali_tsetmc_shares", [])]
res["boali_securities"] = [list(map(_ser, r)) for r in res.get("boali_securities", [])]
res["corp_actions_columns_sample"] = [list(map(_ser, r)) for r in res.get("corp_actions_columns_sample", [])]

p = os.path.join(OUT, f"probe_2k10_valuation_{TAG}.json")
json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=_ser)
print("wrote", p)

print("\n=== TABLES ===")
for t, v in res["tables"].items():
    if v.get("exists"):
        print(f"{t}: rows={v['rows']}")
        print("   cols:", ", ".join(v["columns"]))
    else:
        print(f"{t}: MISSING ({v['err']})")
print("\nboali_id:", res["boali_id"])
print("share_structure rows:", res["boali_share_structure"])
print("tsetmc shares rows:", res["boali_tsetmc_shares"])
print("securities:", res["boali_securities"])
print("share_events_in_universe:", res.get("share_events_in_universe"))
print("corp_actions_in_universe:", res.get("corp_actions_in_universe"))
print("share_intervals_in_universe:", res.get("share_intervals_in_universe"))
print("corp sample:", res.get("corp_actions_columns_sample"))
