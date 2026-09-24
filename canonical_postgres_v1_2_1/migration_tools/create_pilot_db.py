"""Create (or recreate) the isolated pilot PostgreSQL database and apply schema v1.2.1.

Safety:
  * Only touches the dedicated pilot database (name-guarded prefix).
  * Never connects to SQL Server; never touches production PostgreSQL (`postgres`).
    `postgres` maintenance DB is used solely for CREATE/DROP DATABASE.
"""

from __future__ import annotations

import sys

from common import PILOT_DB, SQL_DIR, SQL_ORDER, pg_maintenance_conn, pg_pilot_conn


def main() -> int:
    recreate = "--recreate" in sys.argv
    maint = pg_maintenance_conn()
    if recreate:
        maint.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid<>pg_backend_pid()", (PILOT_DB,))
        maint.execute(f'DROP DATABASE IF EXISTS "{PILOT_DB}"')
    with maint.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (PILOT_DB,))
        exists = cur.fetchone() is not None
    if not exists:
        maint.execute(f'CREATE DATABASE "{PILOT_DB}"')
        print(f"created database {PILOT_DB}")
    else:
        print(f"database {PILOT_DB} already exists")
    maint.close()

    status = []
    for name in SQL_ORDER:
        conn = pg_pilot_conn(autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute((SQL_DIR / name).read_text(encoding="utf-8"))
            status.append((name, "PASS"))
        except Exception as exc:  # noqa: BLE001
            status.append((name, f"FAIL: {exc}"))
            conn.close()
            break
        finally:
            try:
                conn.close()
            except Exception:
                pass
    for n, s in status:
        print(f"  {n}: {s}")
    ok = all(s == "PASS" for _, s in status)
    print("SCHEMA:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
