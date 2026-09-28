"""Idempotent migration of legacy SQL Server Users -> canonical PostgreSQL auth.users,
and legacy Users.Portfolio JSON -> portfolio.portfolios/assets/positions.

Never prints password hashes. Never mutates an existing PostgreSQL password_hash.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import uuid

REPO = pathlib.Path(__file__).resolve().parents[1]
GO = REPO / "go-app"
sys.path.insert(0, str(GO / "py2" / "src"))
os.chdir(GO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(GO / ".env", override=False)
import pyodbc  # noqa: E402
import psycopg  # noqa: E402

OUT = REPO / "sqlserver_retirement" / "output"
PILOT_DB = os.environ.get("CDF_CANONICAL_DB") or os.environ.get("CDF_PILOT_DB") or "company_financial_analytics_shadow_v121"


def sqlserver():
    cs = (f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={os.environ['DB_SERVER']};"
          f"DATABASE={os.environ['DB_NAME']};UID={os.environ['DB_USER']};PWD={os.environ['DB_PASSWORD']};"
          f"TrustServerCertificate=yes;Connection Timeout=10")
    return pyodbc.connect(cs, timeout=15)


def pg():
    import urllib.parse
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg", "postgresql")
    p = urllib.parse.urlparse(url)
    return psycopg.connect(host=p.hostname, port=p.port or 5432,
                           user=urllib.parse.unquote(p.username),
                           password=urllib.parse.unquote(p.password), dbname=PILOT_DB)


def read_users():
    cn = sqlserver()
    try:
        cur = cn.cursor()
        cur.execute("SELECT UserName, Email, Password, IsAdmin, Portfolio FROM dbo.Users")
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        cn.close()


def resolve_security(cur, legacy_key):
    if not legacy_key:
        return None
    cur.execute("""SELECT target_uuid FROM core.legacy_entity_map
                   WHERE entity_type='security' AND legacy_key=%s LIMIT 1""", (legacy_key,))
    row = cur.fetchone()
    return row[0] if row else None


def migrate():
    users = read_users()
    auth_summary = {"users_in_source": len(users), "inserted": 0, "updated": 0, "unchanged": 0, "usernames": []}
    port_summary = {"portfolios": 0, "positions": 0, "unresolved_security": 0, "users_with_portfolio": 0}

    cn = pg()
    try:
        cur = cn.cursor()
        for u in users:
            uname = (u.get("UserName") or "").strip()
            if not uname:
                continue
            email = (u.get("Email") or "").strip() or None
            is_admin = bool(u.get("IsAdmin"))
            pwd = u.get("Password") or ""
            auth_summary["usernames"].append(uname)
            cur.execute("SELECT id::text, password_hash, is_admin FROM auth.users WHERE username=%s", (uname,))
            row = cur.fetchone()
            if row is None:
                cur.execute("""INSERT INTO auth.users (id, username, email, password_hash, is_admin, is_active, created_at, updated_at)
                               VALUES (%s,%s,%s,%s,%s,true,now(),now())""",
                            (str(uuid.uuid4()), uname, email, pwd, is_admin))
                auth_summary["inserted"] += 1
            else:
                # Update non-secret metadata; never overwrite an existing hash.
                cur.execute("""UPDATE auth.users SET email=COALESCE(%s,email), is_admin=%s, updated_at=now()
                               WHERE username=%s""", (email, is_admin, uname))
                auth_summary["updated"] += 1

            # Portfolio
            raw = u.get("Portfolio")
            if raw and raw.strip() not in ("", "[]", "null"):
                try:
                    holdings = json.loads(raw)
                except Exception:
                    holdings = []
                if holdings:
                    port_summary["users_with_portfolio"] += 1
                    cur.execute("SELECT id::text FROM portfolio.portfolios WHERE user_id=(SELECT id FROM auth.users WHERE username=%s) AND name='default' LIMIT 1", (uname,))
                    pr = cur.fetchone()
                    if pr:
                        portfolio_id = pr[0]
                    else:
                        portfolio_id = str(uuid.uuid4())
                        cur.execute("""INSERT INTO portfolio.portfolios (id, user_id, name, portfolio_type, base_currency, is_active, created_at, updated_at)
                                       VALUES (%s,(SELECT id FROM auth.users WHERE username=%s),'default','personal','IRR',true,now(),now())""",
                                    (portfolio_id, uname))
                        port_summary["portfolios"] += 1
                    for h in holdings:
                        sec = resolve_security(cur, h.get("company_id"))
                        if not sec:
                            port_summary["unresolved_security"] += 1
                        qty = float(h.get("quantity") or 0)
                        cost = float(h.get("buy_price") or 0)
                        name = h.get("company_name") or h.get("symbol") or "asset"
                        symbol = h.get("symbol")
                        if sec:
                            cur.execute("SELECT id::text FROM portfolio.assets WHERE security_id=%s", (sec,))
                            ar = cur.fetchone()
                            if ar:
                                asset_id = ar[0]
                            else:
                                asset_id = str(uuid.uuid4())
                                cur.execute("""INSERT INTO portfolio.assets (id, security_id, asset_type, name, symbol, pricing_source, is_active, created_at, updated_at)
                                               VALUES (%s,%s,'stock',%s,%s,'market',true,now(),now())""",
                                            (asset_id, sec, name, symbol))
                        else:
                            asset_id = str(uuid.uuid4())
                            safe_name = (name or symbol or "asset").strip() or "asset"
                            cur.execute("""INSERT INTO portfolio.assets (id, security_id, asset_type, name, symbol, pricing_source, is_active, created_at, updated_at)
                                           VALUES (%s,NULL,'other',%s,%s,'manual',true,now(),now())""",
                                        (asset_id, safe_name, symbol))
                        cur.execute("""INSERT INTO portfolio.positions (portfolio_id, asset_id, quantity, avg_cost_rial, cost_basis_rial, as_of_at, computed_from_tx_count)
                                       VALUES (%s,%s,%s,%s,%s,now(),0)
                                       ON CONFLICT (portfolio_id, asset_id) DO UPDATE
                                       SET quantity=EXCLUDED.quantity, avg_cost_rial=EXCLUDED.avg_cost_rial,
                                           cost_basis_rial=EXCLUDED.cost_basis_rial, as_of_at=now()""",
                                    (portfolio_id, asset_id, qty, cost, qty * cost))
                        port_summary["positions"] += 1
        cn.commit()
    finally:
        cn.close()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "auth_migration_summary.json").write_text(json.dumps(auth_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "portfolio_migration_summary.json").write_text(json.dumps(port_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"auth": auth_summary, "portfolio": port_summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    migrate()
