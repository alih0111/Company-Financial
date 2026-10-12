# -*- coding: utf-8 -*-
"""P0-2k4: read-only probe of stored published_at offsets in ingestion.reports."""
import re
import sys

import psycopg

ENV = r"D:\RFA\Company-Financial\go-app\.env"


def build_dsn():
    txt = open(ENV, encoding="utf-8-sig").read()

    def grab(k):
        m = re.search(rf'^{k}\s*=\s*"?([^"\n#]+)"?', txt, re.M)
        return m.group(1).strip() if m else None

    url = grab("DATABASE_URL").replace("postgresql+psycopg://", "postgresql://")
    ov = grab("CDF_CANONICAL_DB")
    if ov:
        url = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                     r"postgresql://\g<1>/" + ov.strip() + r"\g<2>", url)
    return url


conn = psycopg.connect(build_dsn(), connect_timeout=15)
cur = conn.cursor()
cur.execute("SET default_transaction_read_only = on")
cur.execute("SELECT current_setting('TimeZone')")
print("session TimeZone:", cur.fetchone()[0])
cur.execute(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema='ingestion' AND table_name='reports' AND column_name='published_at'")
print("column:", cur.fetchone())
print("--- newest source='codal' rows (raw text) ---")
cur.execute(
    """SELECT published_at::text, source_report_id FROM ingestion.reports
       WHERE source='codal' AND published_at IS NOT NULL
       ORDER BY published_at DESC LIMIT 6""")
for r in cur.fetchall():
    print(r)
print("--- distinct offset suffixes by source ---")
cur.execute(
    """SELECT source, right(published_at::text,6) AS off, count(*),
              min(published_at)::text, max(published_at)::text
       FROM ingestion.reports
       WHERE published_at IS NOT NULL
       GROUP BY 1,2 ORDER BY 1,3 DESC LIMIT 20""")
for r in cur.fetchall():
    print(r)
conn.rollback()
conn.close()
