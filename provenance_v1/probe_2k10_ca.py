#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""گام ۲-ک-۱۰ — آیا شکاف‌های قیمت ۲۶ شرکت با اقدام شرکتی واقعی توضیح‌پذیرند؟ (فقط‌خواندنی)"""
import datetime as dt
import json
import os
import re
import psycopg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "provenance_v1", "output")
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
recov = json.load(open(os.path.join(OUT, f"recovery_2k9_{TAG}.json"), encoding="utf-8"))
gaps = [x for x in recov["priority1_T_recovery"]["rows"] if x.get("blocking_is_gap")]

tot = 0
explained = 0
for x in gaps:
    sid = x["primary_security"]
    dates = []
    for g in (x.get("momentum_6m_rel_gaps") or []) + (x.get("momentum_3m_rel_gaps") or []):
        dates.append(dt.date.fromisoformat(g["date"]))
    dates = sorted(set(dates))
    lines = []
    for gd in dates:
        ca = conn.execute("""
            SELECT action_date, action_type, adjustment_factor, is_confirmed,
                   detected_heuristically, event_semantics_status, adjustment_evidence_status
            FROM market.corporate_actions
            WHERE security_id=%s AND action_date BETWEEN %s AND %s ORDER BY action_date""",
            (sid, gd - dt.timedelta(days=10), gd + dt.timedelta(days=10))).fetchall()
        conf = [c for c in ca if c[3]]
        markers = [f"{c[0]} {c[1]} f={c[2]} conf={c[3]} heur={c[4]} sem={c[5]} ev={c[6]}" for c in ca]
        lines.append({"gap_date": gd.isoformat(), "n_all": len(ca), "n_confirmed": len(conf),
                      "actions": markers})
        tot += 1
        if conf:
            explained += 1
    print(f"{x['symbol']:>10} gaps={[d.isoformat() for d in dates]}")
    for l in lines:
        print(f"     {l['gap_date']}: all={l['n_all']} conf={l['n_confirmed']}")
        for m in l["actions"][:6]:
            print("        ", m)

print(f"\nTOTAL gap-events={tot} gap-events-with-confirmed-action={explained}")
