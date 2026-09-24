"""Build the explicit universe manifest from dbo.TrackedTickers (READ ONLY).

Outputs:
  analytics_parity/universe_manifest.csv
  analytics_parity/universe_companies.json   (consumable by pilot_migrate)
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))

from common import sqlserver_conn  # noqa: E402

PARITY = BASE / "analytics_parity"


def main() -> int:
    cn = sqlserver_conn()
    cur = cn.cursor()

    cur.execute("SELECT Symbol, Source, IsActive FROM dbo.TrackedTickers ORDER BY Symbol")
    tracked = cur.fetchall()

    manifest_rows = []
    # group legacy company ids by ins code
    ins_groups = {}
    for (symbol, source, is_active) in tracked:
        cur.execute("""
            SELECT DISTINCT CompanyID, CompanyName, InstrumentCode, BrsName
            FROM dbo.MarketPriceHistory WHERE Symbol = ?
        """, (symbol,))
        rows = cur.fetchall()
        if not rows:
            manifest_rows.append({
                "symbol": symbol, "company_name": "", "legacy_company_ids": "", "instrument_code": "",
                "canonical_company_candidate": "", "canonical_security_candidate": "",
                "include": "no" if not is_active else "yes", "exclusion_reason": "no_price_rows",
            })
            continue
        cids = sorted({r[0] for r in rows})
        names = sorted({r[1] for r in rows if r[1]})
        ins_set = sorted({str(r[2]) for r in rows if r[2] is not None})
        ins = ins_set[0] if ins_set else None
        include = "yes" if (is_active and ins) else "no"
        reason = "" if include == "yes" else ("inactive" if not is_active else "no_instrument_code")
        manifest_rows.append({
            "symbol": symbol, "company_name": " | ".join(names),
            "legacy_company_ids": " | ".join(cids), "instrument_code": ins or "",
            "canonical_company_candidate": f"ins:{ins}" if ins else "",
            "canonical_security_candidate": f"ins:{ins}" if ins else "",
            "include": include, "exclusion_reason": reason,
        })
        if include == "yes":
            g = ins_groups.setdefault(ins, {"symbol": symbol, "cids": set(), "names": set()})
            g["cids"] |= set(cids)
            g["names"] |= set(names)

    with (PARITY / "universe_manifest.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)

    companies = []
    for ins, g in sorted(ins_groups.items()):
        companies.append({
            "label": g["symbol"],
            "symbol": g["symbol"],
            "company_ids": sorted(g["cids"]),
            "criteria": ["universe"],
        })
    (PARITY / "universe_companies.json").write_text(
        json.dumps({"note": "auto-generated from TrackedTickers + MarketPriceHistory",
                    "companies": companies}, ensure_ascii=False, indent=2), encoding="utf-8")
    cn.close()

    included = sum(1 for r in manifest_rows if r["include"] == "yes")
    print(f"tracked={len(tracked)} manifest_rows={len(manifest_rows)} included={included} "
          f"clusters={len(companies)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
