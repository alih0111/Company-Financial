"""Idempotent migration of legacy SQL Server dbo.Family* tables into the
canonical PostgreSQL `family` namespace.

Preserves legacy primary keys (so holdings/prices/accounts FKs stay valid) and
resets the identity sequences afterwards. Re-running is safe (upsert by PK).

Requires SQL Server to be reachable at run time. If it is not, the family page
still works with empty tables and data can be re-entered via the UI.

Run:
    python sqlserver_retirement/migrate_family.py
"""

from __future__ import annotations

import os
import pathlib
import sys
from urllib.parse import unquote, urlparse

REPO = pathlib.Path(__file__).resolve().parents[1]
GO = REPO / "go-app"
sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(GO / ".env", override=False)
import psycopg  # noqa: E402

OUT = REPO / "sqlserver_retirement" / "output"
PILOT_DB = os.environ.get("CDF_CANONICAL_DB") or os.environ.get("CDF_PILOT_DB") or "company_financial_analytics_shadow_v121"

ALLOWED_DB_PREFIXES = (
    "company_financial_migration_pilot_",
    "company_financial_analytics_shadow_",
    "company_financial_test_",
)


def sqlserver():
    import pyodbc

    cs = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};"
        f"DATABASE={os.environ['DB_NAME']};UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
        f"TrustServerCertificate=yes;Connection Timeout=10"
    )
    return pyodbc.connect(cs, timeout=15)


def pg():
    if not PILOT_DB.startswith(ALLOWED_DB_PREFIXES):
        raise RuntimeError(f"refusing to write to {PILOT_DB!r} (not an allowed test/shadow prefix)")
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg", "postgresql")
    p = urlparse(url)
    return psycopg.connect(
        host=p.hostname,
        port=p.port or 5432,
        user=unquote(p.username),
        password=unquote(p.password),
        dbname=PILOT_DB,
    )


def rows(cn, table, columns):
    cur = cn.cursor()
    cur.execute(f"SELECT {columns} FROM dbo.{table}")
    names = [c[0] for c in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def has_table(cn, table):
    cur = cn.cursor()
    cur.execute("SELECT OBJECT_ID(?, 'U')", f"dbo.{table}")
    return cur.fetchone()[0] is not None


def migrate():
    summary = {
        "source_db": os.environ.get("DB_NAME"),
        "target_db": PILOT_DB,
        "people": 0,
        "assets": 0,
        "holdings": 0,
        "prices": 0,
        "accounts": 0,
        "cash_flows": 0,
        "history": 0,
        "tables_missing": [],
    }

    src = sqlserver()
    try:
        people = rows(src, "FamilyPeople", "PersonID, Name, SortOrder, IsActive") if has_table(src, "FamilyPeople") else []
        assets = rows(src, "FamilyAssets", "AssetID, Name, ISNULL(Symbol,'') AS Symbol, Category, CommissionRate, SortOrder, IsActive") if has_table(src, "FamilyAssets") else []
        holdings = rows(src, "FamilyHoldings", "PersonID, AssetID, Quantity, CostBasis") if has_table(src, "FamilyHoldings") else []
        prices = rows(src, "FamilyPrices", "DateKey, AssetID, Price") if has_table(src, "FamilyPrices") else []
        accounts = rows(src, "FamilyAccounts", "PersonID, CashBalance") if has_table(src, "FamilyAccounts") else []
        cash_flows = rows(src, "FamilyCashFlows", "ID, DateKey, Amount, Direction, Note") if has_table(src, "FamilyCashFlows") else []
        history = rows(src, "FamilyHistory", "DateKey, TotalValue, ChangeValue, ChangePct") if has_table(src, "FamilyHistory") else []
        for name in ("FamilyPeople", "FamilyAssets", "FamilyHoldings", "FamilyPrices", "FamilyAccounts", "FamilyCashFlows", "FamilyHistory"):
            if not has_table(src, name):
                summary["tables_missing"].append(name)
    finally:
        src.close()

    dst = pg()
    try:
        cur = dst.cursor()

        for p in people:
            cur.execute(
                """INSERT INTO family.people (person_id, name, sort_order, is_active)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (person_id) DO UPDATE SET name=EXCLUDED.name,
                       sort_order=EXCLUDED.sort_order, is_active=EXCLUDED.is_active""",
                (p["PersonID"], (p["Name"] or "").strip(), p["SortOrder"] or 0, bool(p["IsActive"])),
            )
            summary["people"] += 1

        for a in assets:
            cur.execute(
                """INSERT INTO family.assets (asset_id, name, category, commission_rate, symbol, sort_order, is_active)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (asset_id) DO UPDATE SET name=EXCLUDED.name, category=EXCLUDED.category,
                       commission_rate=EXCLUDED.commission_rate, symbol=EXCLUDED.symbol,
                       sort_order=EXCLUDED.sort_order, is_active=EXCLUDED.is_active""",
                (a["AssetID"], (a["Name"] or "").strip(), a["Category"] or "stock",
                 float(a["CommissionRate"] or 0.0088), (a["Symbol"] or "").strip() or None,
                 a["SortOrder"] or 0, bool(a["IsActive"])),
            )
            summary["assets"] += 1

        for h in holdings:
            cur.execute(
                """INSERT INTO family.holdings (person_id, asset_id, quantity, cost_basis)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (person_id, asset_id) DO UPDATE SET
                       quantity=EXCLUDED.quantity, cost_basis=EXCLUDED.cost_basis""",
                (h["PersonID"], h["AssetID"], float(h["Quantity"] or 0), float(h["CostBasis"] or 0)),
            )
            summary["holdings"] += 1

        for pr in prices:
            cur.execute(
                """INSERT INTO family.prices (date_key, asset_id, price)
                   VALUES (%s,%s,%s)
                   ON CONFLICT (date_key, asset_id) DO UPDATE SET price=EXCLUDED.price""",
                (pr["DateKey"], pr["AssetID"], float(pr["Price"] or 0)),
            )
            summary["prices"] += 1

        for acc in accounts:
            cur.execute(
                """INSERT INTO family.accounts (person_id, cash_balance)
                   VALUES (%s,%s)
                   ON CONFLICT (person_id) DO UPDATE SET cash_balance=EXCLUDED.cash_balance""",
                (acc["PersonID"], float(acc["CashBalance"] or 0)),
            )
            summary["accounts"] += 1

        for cf in cash_flows:
            cur.execute(
                """INSERT INTO family.cash_flows (id, date_key, amount, direction, note)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET date_key=EXCLUDED.date_key, amount=EXCLUDED.amount,
                       direction=EXCLUDED.direction, note=EXCLUDED.note""",
                (cf["ID"], cf["DateKey"], float(cf["Amount"] or 0), cf["Direction"], cf["Note"]),
            )
            summary["cash_flows"] += 1

        for hh in history:
            cur.execute(
                """INSERT INTO family.history (date_key, total_value, change_value, change_pct)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (date_key) DO UPDATE SET total_value=EXCLUDED.total_value,
                       change_value=EXCLUDED.change_value, change_pct=EXCLUDED.change_pct""",
                (hh["DateKey"], float(hh["TotalValue"] or 0), float(hh["ChangeValue"] or 0), float(hh["ChangePct"] or 0)),
            )
            summary["history"] += 1

        for table, col in (
            ("people", "person_id"),
            ("assets", "asset_id"),
            ("cash_flows", "id"),
        ):
            cur.execute(
                f"""SELECT setval(pg_get_serial_sequence('family.{table}', '{col}'),
                       COALESCE((SELECT MAX({col}) FROM family.{table}), 1), true)"""
            )

        dst.commit()
    finally:
        dst.close()

    OUT.mkdir(parents=True, exist_ok=True)
    import json

    (OUT / "family_migration_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    migrate()
