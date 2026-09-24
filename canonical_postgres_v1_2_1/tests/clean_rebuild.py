"""PHASE R: clean rebuild reproducibility test.

Drops ONLY the dedicated disposable test database (name-guarded), recreates it,
re-runs all 10 DDL files, then runs the full pytest suite. Writes clean_rebuild.md.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _db  # noqa: E402

BASE = _db.BASE
RESULTS = BASE / "test_results"
SQL_DIR = BASE / "sql"
SQL_ORDER = [
    "001_extensions.sql", "010_core.sql", "020_ingestion.sql", "030_raw.sql",
    "040_fundamentals.sql", "050_market.sql", "060_auth.sql", "070_portfolio.sql",
    "080_analytics.sql", "090_indexes.sql",
]


def main() -> int:
    # SAFETY: never drop anything that is not clearly the disposable test DB.
    if not _db.TEST_DB.startswith(_db.TEST_DB_PREFIX):
        print("SKIPPED_WITH_SAFETY_REASON: target DB name is not a test DB")
        (RESULTS / "clean_rebuild.md").write_text(
            "# Clean Rebuild (PHASE R)\n\nSKIPPED_WITH_SAFETY_REASON: DB name guard failed.\n",
            encoding="utf-8")
        return 0

    maint = _db.connect(_db.maintenance_params(), autocommit=True)
    # terminate connections to the test DB, then drop + recreate
    maint.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()", (_db.TEST_DB,))
    maint.execute(f'DROP DATABASE IF EXISTS "{_db.TEST_DB}"')
    maint.execute(f'CREATE DATABASE "{_db.TEST_DB}"')
    maint.close()
    print(f"dropped + recreated {_db.TEST_DB}")

    ddl_status = []
    for name in SQL_ORDER:
        conn = _db.connect_test(autocommit=True)
        try:
            with conn.cursor() as cur:
                cur.execute((SQL_DIR / name).read_text(encoding="utf-8"))
            ddl_status.append((name, "PASS"))
        except Exception as exc:  # noqa: BLE001
            ddl_status.append((name, f"FAIL: {exc}"))
        finally:
            conn.close()

    # run pytest
    py = sys.executable
    proc = subprocess.run(
        [py, "-m", "pytest", str(BASE / "tests"), "-q", "--no-header", "-p", "no:cacheprovider"],
        capture_output=True, text=True,
    )

    lines = [
        "# Clean Rebuild (PHASE R)",
        "",
        f"- generated_at (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- database: {_db.TEST_DB} (dropped and recreated from zero)",
        "",
        "## DDL",
        "",
        "| file | status |",
        "| --- | --- |",
    ]
    lines += [f"| {n} | {s} |" for n, s in ddl_status]
    lines += ["", "## pytest", "", "```", proc.stdout.strip().splitlines()[-1] if proc.stdout else "", "```", ""]
    all_ddl = all(s == "PASS" for _, s in ddl_status)
    passed = proc.returncode == 0
    lines.append(f"RESULT: {'PASS' if all_ddl and passed else 'FAIL'}")
    (RESULTS / "clean_rebuild.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"DDL all PASS: {all_ddl}; pytest rc={proc.returncode}")
    print(proc.stdout.strip().splitlines()[-1] if proc.stdout else "")
    return 0 if (all_ddl and passed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
