#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""گام ۲-ک-۱۳ — راستی‌آزمایی پارسر کدال در برابر فکت‌های legacy (فقط‌خواندنی).

برای نمادهایی که از قبل ترازنامه/درآمد رسمی دارند، مقدار پارس‌شدهٔ کدال را با
فکت canonical موجود مقایسه می‌کند: canonical_codal = value_kodal × 1e6
(به‌جز eps/operating_eps که ریال بر سهم‌اند). اختلاف تلورانس‌دار = عدم تطابق.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP = ROOT / "provenance_v1" / "output" / "exp_2k13_codal"
CACHE = SNAP / "cache"
MULT = 1_000_000.0
PER_SHARE = {"eps", "operating_eps"}


def conn():
    import psycopg
    txt = (ROOT / "go-app" / ".env").read_text(encoding="utf-8")
    d = re.search(r'^DATABASE_URL\s*=\s*"?([^"\n#]+)"?', txt, re.M).group(1).strip()
    d = d.replace("postgresql+psycopg://", "postgresql://")
    ov = re.search(r'^CDF_CANONICAL_DB\s*=\s*"?([^"\n#]+)"?', txt, re.M)
    if ov:
        d = re.sub(r"postgresql://([^/]+)/[^/?]+(\?.*)?$",
                   r"postgresql://\g<1>/" + ov.group(1).strip() + r"\g<2>", d)
    cn = psycopg.connect(d, connect_timeout=20)
    cn.execute("SET default_transaction_read_only = on")
    return cn


def main(symbols: list[str]):
    sys.stdout.reconfigure(encoding="utf-8")
    cn = conn()
    c = cn.cursor()
    summary = []
    for sym in symbols:
        f = CACHE / f"{sym}.json"
        if not f.exists():
            print(f"{sym}: no cache"); continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        cid = rec["company_id"]
        c.execute("""SELECT st.period_end_date, f.metric_code, f.period_order, f.canonical_value
                     FROM fundamentals.financial_facts f
                     JOIN fundamentals.financial_statements st ON st.id=f.statement_id
                     WHERE st.company_id=%s""", (cid,))
        legacy = {}
        for pe, mc, po, cv in c.fetchall():
            legacy[(pe, mc, int(po))] = float(cv)
        checked = matched = mismatched = missing_ref = 0
        mism = []
        for fact in rec.get("facts", []):
            pe = dt.date.fromisoformat(fact["period_end_date"]) if isinstance(fact["period_end_date"], str) else fact["period_end_date"]
            mc, po, v = fact["metric_code"], int(fact["period_order"]), float(fact["value"])
            key = (pe, mc, po)
            if key not in legacy:
                continue
            checked += 1
            want = v if mc in PER_SHARE else v * MULT
            got = legacy[key]
            if abs(want - got) <= max(1.0, abs(got) * 1e-9):
                matched += 1
            else:
                mismatched += 1
                if len(mism) < 8:
                    mism.append({"period": str(pe), "metric": mc, "order": po,
                                 "kodal_canonical": want, "legacy_canonical": got})
        # پوشش کل: چند نماد legacy این شرکت رفتار می‌شود
        summary.append({"symbol": sym, "checked": checked, "matched": matched,
                        "mismatched": mismatched, "mismatches": mism})
        print(f"{sym:10s} checked={checked:3d} matched={matched:3d} mismatched={mismatched} "
              + (f"  sample_mismatch={mism[:2]}" if mism else ""))
    (SNAP / "parser_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    tot_c = sum(s["checked"] for s in summary)
    tot_m = sum(s["matched"] for s in summary)
    print(f"\nTOTAL: checked={tot_c} matched={tot_m} "
          f"({100.0*tot_m/tot_c:.1f}%) mismatched={tot_c-tot_m}")
    print(f"-> {SNAP/'parser_validation.json'}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["غاذر", "کاما", "دجابر", "فباهنر"])
