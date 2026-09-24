"""Build the exact v3.7 compatibility scoring population (276 legacy subjects).

COMPATIBILITY_ONLY_NOT_CANONICAL.

Creates an isolated model separate from canonical identity:
  * analytics_parity_debug/v37_scoring_subjects.csv        (276 subjects)
  * analytics_parity_debug/reference/legacy_v37_financial_inputs.csv
  * analytics_parity_debug/reference/legacy_v37_monthly_inputs.csv
  * analytics_parity_debug/population_exact_diff.csv
  * shadow table compat_v37.scoring_subjects (disposable)

SQL Server is SELECT-only. The only writes are to
company_financial_analytics_shadow_v121 (compat_v37 schema).
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(BASE / "migration_tools"))
from common import pg_pilot_conn, sqlserver_conn, PILOT_DB  # noqa: E402

if not PILOT_DB.startswith("company_financial_analytics_shadow_"):
    raise SystemExit(f"Refusing: compat_v37 writes only allowed to a shadow DB (got {PILOT_DB!r})")

OUT = BASE / "analytics_parity_debug"
REF = OUT / "reference"

FIN_COLS = ["ReportDate", "Num1_Value1", "Num1_Value2", "Num1_Value3",
            "Num2_Value1", "Num2_Value2", "Num2_Value3", "Product1",
            "OperatingProfitNew", "OperatingProfitLastYear", "OperatingProfitFYPrev",
            "RevenueNew", "RevenueLastYear", "RevenueFYPrev",
            "FinanceCostsNew", "OtherNonOpNew",
            "NetProfitAmount", "NetProfitAmountLY", "NetProfitAmountFYPrev",
            "OperatingCashFlow", "OperatingCashFlowLY", "OperatingCashFlowFYPrev",
            "TotalAssets", "CurrentAssets", "TotalLiabilities",
            "CurrentLiabilities", "TotalEquity"]

COMPAT_DDL = """
CREATE SCHEMA IF NOT EXISTS compat_v37;
-- COMPATIBILITY_ONLY_NOT_CANONICAL: disposable parity/test state.
CREATE TABLE IF NOT EXISTS compat_v37.scoring_subjects (
    legacy_subject_id     text PRIMARY KEY,
    legacy_company_id     text NOT NULL,
    company_name          text,
    symbol                text,
    instrument_code       text,
    canonical_company_id  uuid,
    canonical_security_id uuid,
    has_monthly           boolean NOT NULL,
    has_financial         boolean NOT NULL,
    has_market_price      boolean NOT NULL,
    appears_in_v37        boolean NOT NULL,
    subject_origin        text,
    notes                 text
);
"""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    REF.mkdir(parents=True, exist_ok=True)
    sc = sqlserver_conn().cursor()

    # ---- exact v3.7 population ----
    sc.execute("""
        SELECT CompanyID FROM dbo.mahane WHERE CompanyID IS NOT NULL
        UNION
        SELECT CompanyID FROM dbo.miandore2 WHERE CompanyID IS NOT NULL
        ORDER BY CompanyID""")
    cids = [r[0] for r in sc.fetchall()]
    print("v3.7 population (mahane UNION miandore2):", len(cids))
    assert len(cids) == 276, f"expected 276, got {len(cids)}"

    ph = ",".join("?" for _ in cids)

    def fetch(sql, params):
        sc.execute(sql, params)
        cols = [c[0] for c in sc.description]
        return [dict(zip(cols, r)) for r in sc.fetchall()]

    names = fetch(f"SELECT CompanyID, MAX(CompanyName) AS nm FROM dbo.mahane WHERE CompanyID IN ({ph}) GROUP BY CompanyID", cids)
    names2 = fetch(f"SELECT CompanyID, MAX(CompanyName) AS nm FROM dbo.miandore2 WHERE CompanyID IN ({ph}) GROUP BY CompanyID", cids)
    name_by = {r["CompanyID"]: r["nm"] for r in names}
    for r in names2:
        name_by.setdefault(r["CompanyID"], r["nm"])

    market = fetch(f"""SELECT CompanyID, MAX(CompanyName) AS nm, MAX(Symbol) AS sym,
                              MAX(InstrumentCode) AS ic
                       FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph})
                       GROUP BY CompanyID""", cids)
    mkt_by = {r["CompanyID"]: r for r in market}

    has_monthly = {r["CompanyID"] for r in fetch(f"SELECT DISTINCT CompanyID FROM dbo.mahane WHERE CompanyID IN ({ph})", cids)}
    has_fin = {r["CompanyID"] for r in fetch(f"SELECT DISTINCT CompanyID FROM dbo.miandore2 WHERE CompanyID IN ({ph})", cids)}
    has_price = {r["CompanyID"] for r in fetch(f"SELECT DISTINCT CompanyID FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph})", cids)}

    # canonical mapping via legacy_entity_map (many-to-one allowed)
    pg = pg_pilot_conn()
    pc = pg.cursor()
    pc.execute("""
        SELECT legacy_key, entity_type, target_uuid::text
        FROM core.legacy_entity_map
        WHERE source_table IN ('mahane','miandore2','MarketPriceHistory')""")
    canon = {}
    for lk, et, tgt in pc.fetchall():
        canon.setdefault(lk, {}).setdefault(et, set()).add(tgt)

    rows = []
    for cid in cids:
        cmap = canon.get(cid, {})
        comp = sorted(cmap.get("company", []))
        sec = sorted(cmap.get("security", []))
        mk = mkt_by.get(cid, {})
        origins = []
        if cid in has_monthly:
            origins.append("mahane")
        if cid in has_fin:
            origins.append("miandore2")
        rows.append({
            "legacy_subject_id": f"legacy:{cid}",
            "legacy_company_id": cid,
            "company_name": name_by.get(cid) or (mk.get("nm") if mk else "") or "",
            "symbol": (mk.get("sym") if mk else "") or "",
            "instrument_code": (str(mk.get("ic")) if mk and mk.get("ic") is not None else ""),
            "canonical_company_id": comp[0] if comp else "",
            "canonical_security_id": sec[0] if sec else "",
            "has_monthly": cid in has_monthly,
            "has_financial": cid in has_fin,
            "has_market_price": cid in has_price,
            "appears_in_v37": True,
            "subject_origin": "+".join(origins),
            "notes": ("many-to-one canonical mapping" if len(comp) > 1 else
                      ("no canonical mapping" if not comp else "")),
        })

    with (OUT / "v37_scoring_subjects.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("wrote v37_scoring_subjects.csv:", len(rows),
          "| mapped:", sum(1 for r in rows if r["canonical_company_id"]),
          "| unmapped:", sum(1 for r in rows if not r["canonical_company_id"]))

    # ---- frozen legacy financial inputs (READ ONLY snapshot) ----
    fin = fetch(f"SELECT CompanyID, {','.join(FIN_COLS)} FROM dbo.miandore2 WHERE CompanyID IN ({ph}) ORDER BY CompanyID, ReportDate", cids)
    with (REF / "legacy_v37_financial_inputs.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["legacy_company_id"] + FIN_COLS)
        for r in fin:
            w.writerow([r["CompanyID"]] + [r[c] for c in FIN_COLS])
    print("wrote legacy_v37_financial_inputs.csv rows:", len(fin))

    # ---- frozen legacy monthly inputs ----
    mon = fetch(f"SELECT CompanyID, ReportDate, Value1, Value2, Value3 FROM dbo.mahane WHERE CompanyID IN ({ph}) ORDER BY CompanyID, ReportDate", cids)
    with (REF / "legacy_v37_monthly_inputs.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["legacy_company_id", "ReportDate", "Value1", "Value2", "Value3"])
        for r in mon:
            w.writerow([r["CompanyID"], r["ReportDate"], r["Value1"], r["Value2"], r["Value3"]])
    print("wrote legacy_v37_monthly_inputs.csv rows:", len(mon))

    # ---- frozen legacy market inputs (per legacy CompanyID) ----
    mcols = ["GregorianDate", "JalaliDate", "ClosingPrice", "LastPrice", "HighPrice",
             "LowPrice", "TradeValue", "Volume", "TradeCount", "CollectedAt"]
    mkt = fetch(f"SELECT CompanyID, {','.join(mcols)} FROM dbo.MarketPriceHistory WHERE CompanyID IN ({ph}) ORDER BY CompanyID, GregorianDate, CollectedAt", cids)
    with (REF / "legacy_v37_market_inputs.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["legacy_company_id"] + mcols)
        for r in mkt:
            w.writerow([r["CompanyID"]] + [r[c] for c in mcols])
    print("wrote legacy_v37_market_inputs.csv rows:", len(mkt))

    # ---- shadow compat schema/table ----
    pc.execute(COMPAT_DDL)
    pc.execute("TRUNCATE compat_v37.scoring_subjects")
    for r in rows:
        pc.execute("""INSERT INTO compat_v37.scoring_subjects
            (legacy_subject_id, legacy_company_id, company_name, symbol, instrument_code,
             canonical_company_id, canonical_security_id, has_monthly, has_financial,
             has_market_price, appears_in_v37, subject_origin, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (r["legacy_subject_id"], r["legacy_company_id"], r["company_name"], r["symbol"],
             r["instrument_code"], r["canonical_company_id"] or None, r["canonical_security_id"] or None,
             r["has_monthly"], r["has_financial"], r["has_market_price"], r["appears_in_v37"],
             r["subject_origin"], r["notes"]))
    pg.commit()
    print("loaded compat_v37.scoring_subjects:", len(rows))

    # ---- exact population diff ----
    pc.execute("SELECT legacy_company_id FROM compat_v37.scoring_subjects")
    compat_set = {r[0] for r in pc.fetchall()}
    ss_set = set(cids)
    only_ss = sorted(ss_set - compat_set)
    only_compat = sorted(compat_set - ss_set)
    with (OUT / "population_exact_diff.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["side", "legacy_company_id"])
        for c in only_ss:
            w.writerow(["only_in_sqlserver", c])
        for c in only_compat:
            w.writerow(["only_in_compat", c])
    print("only_in_sqlserver:", len(only_ss), "only_in_compat:", len(only_compat))
    gate = (len(compat_set) == 276 and len(ss_set) == 276 and not only_ss and not only_compat)
    print("v3.7 subjects =", len(ss_set), "compat_v37 subjects =", len(compat_set))
    print("POPULATION_PARITY_" + ("PASS" if gate else "FAIL"))
    sc.close()
    pg.close()
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
