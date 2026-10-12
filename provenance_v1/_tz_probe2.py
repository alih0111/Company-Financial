# -*- coding: utf-8 -*-
"""P0-2k4 decisive probe: stored UTC instant vs raw Codal wall clock (read-only)."""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import psycopg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
TAG = "2026-10-08_q9499e3bb_v7786e01a_tdcfd3840"
CACHE_DIR = os.path.join("historical_codal_backfill", "output", "pub_backfill")
TRACINGS = {"789108", "921951", "939705", "749580", "780488", "884648", "904200"}


def build_dsn():
    txt = open("go-app/.env", encoding="utf-8").read()
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    return d


# raw wall clocks from the pub_backfill cache (Jalali text, unzoned)
raw = {}
for fn in os.listdir(CACHE_DIR):
    if not fn.endswith(".json"):
        continue
    try:
        doc = json.load(open(os.path.join(CACHE_DIR, fn), encoding="utf-8"))
    except Exception:
        continue
    letters = doc.get("letters") or doc.get("rows") or []
    if isinstance(doc, dict) and not letters and "tracing_no" in doc:
        letters = [doc]
    for L in letters:
        tn = str(L.get("tracing_no") or L.get("TracingNo") or "").strip()
        if tn in TRACINGS and tn not in raw:
            raw[tn] = {
                "publish_datetime": L.get("publish_datetime") or L.get("PublishDateTime"),
                "file": fn,
            }

print("raw wall clocks found:", len(raw))
conn = psycopg.connect(build_dsn(), connect_timeout=15)
cur = conn.cursor()
cur.execute("SET default_transaction_read_only = on")
TEHRAN = ZoneInfo("Asia/Tehran")
FIXED = timezone(timedelta(hours=3, minutes=30))
persian = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
import jdatetime

for tn, info in sorted(raw.items()):
    raws = str(info["publish_datetime"]).strip().translate(persian)
    cur.execute(
        """SELECT published AT TIME ZONE 'UTC', published::text FROM (
             SELECT published_at AS published FROM ingestion.reports
             WHERE source='codal' AND source_report_id=%s AND published_at IS NOT NULL) t""",
        (tn,))
    row = cur.fetchone()
    if not row:
        print(tn, "no DB row")
        continue
    utc_wall, disp = row
    # parse raw Jalali wall clock
    dp, _, tp = raws.partition(" ")
    y, m, d = (int(x) for x in dp.split("/")[:3])
    bits = [int(x) for x in tp.split(":") if x != ""]
    hh = bits[0] if bits else 0
    mm = bits[1] if len(bits) > 1 else 0
    ss = bits[2] if len(bits) > 2 else 0
    g = jdatetime.date(y, m, d).togregorian()
    wall_naive = datetime(g.year, g.month, g.day, hh, mm, ss)
    true_off = wall_naive.replace(tzinfo=TEHRAN).utcoffset()
    fixed = wall_naive.replace(tzinfo=FIXED).astimezone(timezone.utc)
    true_utc = wall_naive.replace(tzinfo=TEHRAN).astimezone(timezone.utc)
    db_utc = utc_wall.replace(tzinfo=timezone.utc)
    print(f"tracing {tn}: raw={raws} db_utc={db_utc.strftime('%H:%M:%S')} "
          f"fixed330_utc={fixed.strftime('%H:%M:%S')} true_utc={true_utc.strftime('%H:%M:%S')} "
          f"true_off={true_off} db==fixed:{db_utc==fixed} db==true:{db_utc==true_utc} "
          f"disp={disp} file={os.path.basename(info['file'])}")
conn.rollback()
conn.close()
