"""Sync TSETMC market metadata (industry category, shares, market cap) into canonical.

Source: Api.BrsApi.ir/Tsetmc/AllSymbols.php (1 request/day — generous limit).
Match:  BRS `id` == core.securities.tsetmc_ins_code.

Writes:
  core.company_classification — current category with PIT validity
      (category change → previous row closed with valid_to, new row inserted).
  core.share_structure        — daily snapshot (shares_count, market_value_rial,
      eps_rial); same-day re-runs are idempotent via (security_id, as_of_date).

Usage:
  python py/sync_market_meta.py            # daily sync
  python py/sync_market_meta.py --dry-run  # match report without writes
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
for p in (REPO / "go-app" / ".env", REPO / "canonical_postgres_v1_2_1" / "migration_tools" / ".." / "go-app" / ".env"):
    pass
try:
    from dotenv import load_dotenv

    load_dotenv(REPO / "go-app" / ".env")
except Exception:
    pass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "https://Api.BrsApi.ir/Tsetmc"
CANONICAL_DB = os.getenv("CDF_CANONICAL_DB", "company_financial_analytics_shadow_v121")
HTTP_TIMEOUT = 60


def db_url() -> str:
    url = os.getenv("DATABASE_URL", "").replace("postgresql+psycopg", "postgresql")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    return re.sub(r"/([^/?]+)(\?|$)", rf"/{CANONICAL_DB}\2", url, count=1)


def fetch_all_symbols(key: str):
    url = f"{API_BASE}/AllSymbols.php?key={key}"
    req = urllib.request.Request(url, headers={"User-Agent": "rfa-market-meta/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.getenv("BRS_API_KEY", "").strip()
    if not key:
        raise SystemExit("BRS_API_KEY is not set")

    rows = fetch_all_symbols(key)
    today = dt.date.today().isoformat()
    print(f"fetched {len(rows)} instruments from BRS")

    import psycopg  # after env load

    matched_cls, matched_ss, unmatched = 0, 0, []
    with psycopg.connect(db_url(), autocommit=not args.dry_run) as pg, pg.cursor() as cur:
        for r in rows:
            ins = str(r.get("id") or "").strip()
            if not ins:
                continue
            cur.execute(
                """SELECT s.id::text, c.id::text FROM core.securities s
                   LEFT JOIN core.companies c ON c.id = s.company_id
                   WHERE s.tsetmc_ins_code = %s LIMIT 1""",
                (ins,),
            )
            hit = cur.fetchone()
            if not hit:
                unmatched.append(str(r.get("l18") or ins))
                continue
            sec_id, comp_id = hit
            category = str(r.get("cs") or "").strip()
            cat_id = r.get("cs_id")
            shares = r.get("z")
            mv = r.get("mv")
            eps = r.get("eps")

            if args.dry_run:
                matched_cls += 1
                matched_ss += 1
                continue

            if category:
                # PIT: close the current row when the category changed.
                cur.execute(
                    """SELECT category FROM core.company_classification
                       WHERE company_id = %s AND valid_to IS NULL LIMIT 1""",
                    (comp_id,),
                )
                prev = cur.fetchone()
                if prev is None:
                    cur.execute(
                        """INSERT INTO core.company_classification
                           (company_id, security_id, tsetmc_ins_code, category, category_id)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (comp_id, sec_id, ins, category, cat_id),
                    )
                    matched_cls += 1
                elif prev[0] != category:
                    cur.execute(
                        """UPDATE core.company_classification SET valid_to = current_date
                           WHERE company_id = %s AND valid_to IS NULL""",
                        (comp_id,),
                    )
                    cur.execute(
                        """INSERT INTO core.company_classification
                           (company_id, security_id, tsetmc_ins_code, category, category_id)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (comp_id, sec_id, ins, category, cat_id),
                    )
                    matched_cls += 1

            if shares:
                cur.execute(
                    """INSERT INTO core.share_structure
                       (security_id, company_id, shares_count, market_value_rial, eps_rial, as_of_date)
                       VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (security_id, as_of_date) DO UPDATE SET
                         shares_count = EXCLUDED.shares_count,
                         market_value_rial = EXCLUDED.market_value_rial,
                         eps_rial = EXCLUDED.eps_rial,
                         collected_at = now()""",
                    (sec_id, comp_id, shares, mv, eps, today),
                )
                matched_ss += 1

    outcome = {
        "fetched": len(rows),
        "classification_upserts": matched_cls,
        "share_structure_upserts": matched_ss,
        "unmatched": len(unmatched),
        "unmatched_sample": unmatched[:10],
        "as_of_date": today,
        "dry_run": bool(args.dry_run),
    }
    print("RESULT|" + json.dumps(outcome, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
