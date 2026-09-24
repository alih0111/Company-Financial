"""PHASE E: introspect the test database catalog and write schema_introspection.md."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _db  # noqa: E402

RESULTS = _db.BASE / "test_results"
SCHEMAS = ("core", "ingestion", "raw", "fundamentals", "market", "analytics", "portfolio", "auth")


def rows(conn, sql, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchall()


def main() -> int:
    conn = _db.connect_test(autocommit=True)
    out = []
    out.append("# Schema Introspection (PHASE E)")
    out.append("")
    out.append(f"- database: {_db.TEST_DB}")
    out.append("")

    schemas = rows(conn, """
        SELECT nspname FROM pg_namespace
        WHERE nspname = ANY(%s) ORDER BY nspname
    """, (list(SCHEMAS),))
    out.append("## Schemas")
    out.append(", ".join(s[0] for s in schemas))
    out.append("")

    tables = rows(conn, """
        SELECT schemaname, tablename FROM pg_tables
        WHERE schemaname = ANY(%s) ORDER BY 1,2
    """, (list(SCHEMAS),))
    views = rows(conn, """
        SELECT schemaname, viewname FROM pg_views
        WHERE schemaname = ANY(%s) ORDER BY 1,2
    """, (list(SCHEMAS),))
    funcs = rows(conn, """
        SELECT n.nspname, p.proname, p.prokind
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s) ORDER BY 1,2
    """, (list(SCHEMAS),))
    triggers = rows(conn, """
        SELECT n.nspname, c.relname, t.tgname
        FROM pg_trigger t
        JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE NOT t.tgisinternal AND n.nspname = ANY(%s)
        ORDER BY 1,2,3
    """, (list(SCHEMAS),))
    indexes = rows(conn, """
        SELECT schemaname, COUNT(*) FROM pg_indexes
        WHERE schemaname = ANY(%s) GROUP BY schemaname ORDER BY 1
    """, (list(SCHEMAS),))
    pks = rows(conn, """
        SELECT tc.table_schema, tc.table_name, tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema = ANY(%s)
        ORDER BY 1,2
    """, (list(SCHEMAS),))
    fks = rows(conn, """
        SELECT tc.table_schema, tc.table_name, tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema = ANY(%s)
        ORDER BY 1,2
    """, (list(SCHEMAS),))
    uqs = rows(conn, """
        SELECT tc.table_schema, tc.table_name, tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.constraint_type='UNIQUE' AND tc.table_schema = ANY(%s)
        ORDER BY 1,2
    """, (list(SCHEMAS),))
    checks = rows(conn, """
        SELECT tc.table_schema, tc.table_name, tc.constraint_name
        FROM information_schema.table_constraints tc
        WHERE tc.constraint_type='CHECK' AND tc.table_schema = ANY(%s)
        ORDER BY 1,2
    """, (list(SCHEMAS),))
    generated = rows(conn, """
        SELECT table_schema, table_name, column_name, generation_expression
        FROM information_schema.columns
        WHERE is_generated='ALWAYS' AND table_schema = ANY(%s)
        ORDER BY 1,2,3
    """, (list(SCHEMAS),))

    def section(title, items, fmt=lambda x: ".".join(str(v) for v in x)):
        out.append(f"## {title} ({len(items)})")
        for it in items:
            out.append(f"- {fmt(it)}")
        out.append("")

    section("Tables", tables, lambda r: f"{r[0]}.{r[1]}")
    section("Views", views, lambda r: f"{r[0]}.{r[1]}")
    section("Functions", funcs, lambda r: f"{r[0]}.{r[1]} [{r[2]}]")
    section("Triggers", triggers, lambda r: f"{r[0]}.{r[1]} :: {r[2]}")
    out.append(f"## Indexes per schema\n")
    for s, c in indexes:
        out.append(f"- {s}: {c}")
    out.append("")
    section("Primary keys", pks, lambda r: f"{r[0]}.{r[1]} :: {r[2]}")
    section("Foreign keys", fks, lambda r: f"{r[0]}.{r[1]} :: {r[2]}")
    section("Unique constraints", uqs, lambda r: f"{r[0]}.{r[1]} :: {r[2]}")
    section("Check constraints", checks, lambda r: f"{r[0]}.{r[1]} :: {r[2]}")
    section("Generated columns", generated, lambda r: f"{r[0]}.{r[1]}.{r[2]} = {r[3]}")

    total_indexes = sum(c for _, c in indexes)
    out.append("## Static vs catalog counts")
    out.append("")
    out.append("| object | static (preflight) | catalog | note |")
    out.append("| --- | --- | --- | --- |")
    out.append(f"| tables | 33 | {len(tables)} | equal if 33 |")
    out.append(f"| views | 4 | {len(views)} | 33? expected 4 |")
    out.append(f"| functions | 14 | {len(funcs)} | +trigger functions included |")
    out.append(f"| triggers | 28 | {len(triggers)} | user triggers only |")
    out.append(f"| explicit indexes (static) | 89 | {total_indexes} (catalog total) | catalog adds PK/UNIQUE constraint indexes |")
    out.append("")
    out.append("> Catalog index count is larger than the static CREATE INDEX count because")
    out.append("> PRIMARY KEY and UNIQUE constraints also create backing indexes, which are")
    out.append("> not written as explicit `CREATE INDEX` statements in the DDL.")
    out.append("")

    (RESULTS / "schema_introspection.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"tables={len(tables)} views={len(views)} funcs={len(funcs)} triggers={len(triggers)} indexes={total_indexes}")
    print(f"pk={len(pks)} fk={len(fks)} unique={len(uqs)} check={len(checks)} generated={len(generated)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
