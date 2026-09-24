"""PHASE A/C/D runner: environment check, fresh-DB verification, DDL execution.

Safety: only ever connects to the dedicated test database (name-prefixed) plus
the `postgres` maintenance DB used solely to CREATE the test database.

Run (test venv python):
    python canonical_postgres_v1_2_1/tests/run_ddl.py
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _db  # noqa: E402

SQL_DIR = _db.BASE / "sql"
RESULTS = _db.BASE / "test_results"
RESULTS.mkdir(exist_ok=True)

SQL_ORDER = [
    "001_extensions.sql",
    "010_core.sql",
    "020_ingestion.sql",
    "030_raw.sql",
    "040_fundamentals.sql",
    "050_market.sql",
    "060_auth.sql",
    "070_portfolio.sql",
    "080_analytics.sql",
    "090_indexes.sql",
]


def user_objects(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog','information_schema')
              AND table_type IN ('BASE TABLE','VIEW')
            ORDER BY table_schema, table_name
            """
        )
        return cur.fetchall()


def main() -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ---- PHASE A: environment ----
    maint = _db.connect(_db.maintenance_params(), autocommit=True)
    with maint.cursor() as cur:
        cur.execute("SHOW server_version")
        server_version = cur.fetchone()[0]
        cur.execute("SHOW server_version_num")
        svnum = cur.fetchone()[0]
        cur.execute("SELECT current_database()")
        cur_db = cur.fetchone()[0]
        cur.execute("SELECT datname FROM pg_database ORDER BY datname")
        dbs = [r[0] for r in cur.fetchall()]

    created = False
    if _db.TEST_DB not in dbs:
        maint.execute(f'CREATE DATABASE "{_db.TEST_DB}"')
        created = True

    p = _db.server_params()
    (RESULTS / "environment.md").write_text(
        "\n".join([
            "# Test Environment (PHASE A)",
            "",
            f"- generated_at (UTC): {now}",
            f"- isolation method: **local PostgreSQL instance, brand-new dedicated database**",
            f"- docker: **not available** (fallback branch used)",
            f"- PostgreSQL server_version: {server_version} (num {svnum})",
            f"- host: {p['host']}",
            f"- port: {p['port']}",
            f"- maintenance user: (redacted)",
            f"- maintenance database (used only for CREATE DATABASE): {cur_db}",
            f"- **test database: {_db.TEST_DB}**",
            f"- test database newly created in this run: {created}",
            f"- credentials: NOT stored (never printed)",
            "",
            "## Safety confirmation",
            f"- The py2 production database `postgres` is **never** used for DDL/DML.",
            f"- All DDL/DML below target only `{_db.TEST_DB}`.",
            f"- A name guard rejects any target DB not starting with `company_financial_test_`.",
            f"- No SQL Server connection is made.",
            "",
        ]),
        encoding="utf-8",
    )
    maint.close()

    # ---- PHASE C: fresh DB verification ----
    tconn = _db.connect_test(autocommit=True)
    existing = user_objects(tconn)
    with open(RESULTS / "database_before.txt", "w", encoding="utf-8") as fh:
        if existing:
            fh.write("UNEXPECTED EXISTING USER OBJECTS:\n")
            fh.write("\n".join(f"{s}.{t}" for s, t in existing))
        else:
            fh.write("(empty — no user-defined tables/views before schema creation)\n")
    tconn.close()

    if existing:
        print("FAIL: test database is not empty (application objects already exist).")
        return 2

    # ---- PHASE D: execute DDL ----
    lines = [
        "# DDL Execution (PHASE D)",
        "",
        f"- generated_at (UTC): {now}",
        f"- database: {_db.TEST_DB}",
        "- mode: stop-on-error (first failing file halts the run)",
        "",
        "| file | started | duration_ms | status |",
        "| --- | --- | --- | --- |",
    ]
    failures = []
    for name in SQL_ORDER:
        path = SQL_DIR / name
        sql = path.read_text(encoding="utf-8")
        conn = _db.connect_test(autocommit=True)
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        t0 = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            status = "PASS"
        except Exception as exc:  # noqa: BLE001
            status = "FAIL"
            failures.append((name, exc))
        duration = int((time.perf_counter() - t0) * 1000)
        conn.close()
        lines.append(f"| {name} | {started} | {duration} | {status} |")
        print(f"  {name}: {status} ({duration} ms)")
        if failures:
            break

    if failures:
        name, exc = failures[0]
        lines += [
            "",
            "## Failure",
            f"- file: {name}",
            "```",
            str(exc),
            "```",
        ]
        (RESULTS / "ddl_execution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"DDL_FAILED at {name}: {exc}")
        return 3

    (RESULTS / "ddl_execution.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("DDL: all 10 files PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
