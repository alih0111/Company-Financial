"""Read-only SQL Server inventory extractor for the `codal` database.

This script only issues SELECT statements against system catalog views and
INFORMATION_SCHEMA. It never performs INSERT/UPDATE/DELETE/DDL and never
modifies the database.

Credentials are read from go-app/.env and are NEVER written to the output.
Sensitive sample values (password/token/secret/hash/salt/email) are masked.

Run:
    python database_inventory/extract_inventory.py
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    import pyodbc
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pyodbc is required: pip install pyodbc") from exc

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
ENV_FILE = REPO_ROOT / "go-app" / ".env"

SQL_VIEWS_DIR = BASE_DIR / "sql" / "views"
SQL_FUNCS_DIR = BASE_DIR / "sql" / "functions"
SAMPLES_DIR = BASE_DIR / "12_samples"

SENSITIVE_RE = re.compile(r"(password|passwd|pwd|token|secret|hash|salt|email)", re.I)

SOURCE_ROOTS = [REPO_ROOT / "go-app"]
SOURCE_EXTS = {".go", ".py", ".sql", ".json"}
SOURCE_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "chromium-profile",
    ".browser_profile",
    "chromedriver-win32",
    "__pycache__",
    ".ruff_cache",
    "dist",
    "backtest_output",
    ".zcode",
    ".vscode",
}
OBJECTS = [
    "CodalReports",
    "CodalSyncState",
    "FamilyAccounts",
    "FamilyAssets",
    "FamilyCashFlows",
    "FamilyHistory",
    "FamilyHoldings",
    "FamilyPeople",
    "FamilyPrices",
    "FullPE",
    "mahane",
    "miandore",
    "miandore2",
    "statements",
    "StockData",
    "StockPrices",
    "TrackedTickers",
    "Users",
    "MarketPriceHistory",
    "vw_AIStockMetrics",
    "vw_AIStockMetrics2",
    "vw_AIStockMetrics3",
    "fn_JalaliKey",
]

OP_KEYWORDS = ["SELECT", "INSERT", "UPDATE", "DELETE", "FROM", "INTO", "JOIN", "MERGE", "EXEC"]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
def connect() -> "pyodbc.Connection":
    if load_dotenv is not None:
        load_dotenv(ENV_FILE)
    else:
        for line in ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    cs = (
        "DRIVER={ODBC Driver 17 for SQL Server};"
        f"SERVER={os.getenv('DB_SERVER')};"
        f"DATABASE={os.getenv('DB_NAME')};"
        f"UID={os.getenv('DB_USER')};"
        f"PWD={os.getenv('DB_PASSWORD')};"
        "TrustServerCertificate=yes"
    )
    return pyodbc.connect(cs, timeout=15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def q(cur: "pyodbc.Cursor", sql: str, *params: Any) -> list[tuple]:
    cur.execute(sql, *params)
    return cur.fetchall()


def md_table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(v: Any) -> str:
        if v is None:
            return ""
        text = str(v).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
        return text

    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for r in rows:
        out.append("| " + " | ".join(cell(v) for v in r) + " |")
    return "\n".join(out)


def write(name: str, content: str) -> None:
    path = BASE_DIR / name
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    print(f"  wrote {path.relative_to(REPO_ROOT)}")


def fmt_type(ty: str, max_length: int, precision: int, scale: int) -> str:
    tl = (ty or "").lower()
    if tl in ("varchar", "char", "varbinary", "binary"):
        return f"{ty}({'max' if max_length == -1 else max_length})"
    if tl in ("nvarchar", "nchar"):
        return f"{ty}({'max' if max_length == -1 else max_length // 2})"
    if tl in ("decimal", "numeric"):
        return f"{ty}({precision},{scale})"
    if tl in ("datetime2", "datetimeoffset", "time"):
        return f"{ty}({scale})"
    if tl == "float":
        return f"float({precision})"
    return ty


def fmt_value(v: Any) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (bytes, bytearray)):
        if len(v) > 32:
            return f"0x{bytes(v[:32]).hex()}...({len(v)} bytes)"
        return "0x" + bytes(v).hex()
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat()
    s = str(v)
    return s if len(s) <= 300 else s[:300] + "..."


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def extract(cur: "pyodbc.Cursor") -> dict[str, Any]:
    facts: dict[str, Any] = {"generated_at": _dt.datetime.now().isoformat(timespec="seconds")}

    # -- 01 schemas --------------------------------------------------------
    schemas = q(
        cur,
        """
        SELECT s.name, s.schema_id,
               (SELECT COUNT(*) FROM sys.objects o WHERE o.schema_id = s.schema_id
                  AND o.type IN ('U','V','P','FN','IF','TF','TR')) AS obj_count
        FROM sys.schemas s
        ORDER BY s.schema_id
        """,
    )
    facts["schemas"] = [list(r) for r in schemas]
    lines = ["# 01 — Schemas\n", f"Database: `{os.getenv('DB_NAME')}`  |  generated: {facts['generated_at']}\n"]
    lines.append(md_table(["schema", "schema_id", "user_object_count"], schemas))
    write("01_schemas.md", "\n".join(lines))

    # -- 02 tables ---------------------------------------------------------
    tables = q(
        cur,
        """
        SELECT s.name AS schema_name, t.name AS table_name, t.object_id,
               t.create_date, t.modify_date,
               ISNULL((SELECT SUM(p.rows) FROM sys.partitions p
                       WHERE p.object_id = t.object_id AND p.index_id IN (0,1)), 0) AS row_count
        FROM sys.tables t
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        ORDER BY s.name, t.name
        """,
    )
    facts["tables"] = [
        {
            "schema": r[0],
            "name": r[1],
            "object_id": r[2],
            "create_date": r[3].isoformat(sep=" ") if r[3] else None,
            "modify_date": r[4].isoformat(sep=" ") if r[4] else None,
            "row_count": int(r[5]),
        }
        for r in tables
    ]
    lines = ["# 02 — Tables\n", f"Total user tables: **{len(tables)}**\n"]
    lines.append(
        md_table(
            ["schema", "table", "row_count (approx)", "create_date", "modify_date"],
            [[r[0], r[1], r[5], r[3], r[4]] for r in tables],
        )
    )
    write("02_tables.md", "\n".join(lines))

    # -- 05 indexes + column constraint flags (needed by 03) ---------------
    constraint_cols: dict[tuple[int, int], str] = {}
    for r in q(
        cur,
        """
        SELECT i.object_id, ic.column_id, i.is_primary_key, i.is_unique_constraint
        FROM sys.indexes i
        JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id
        WHERE (i.is_primary_key = 1 OR i.is_unique_constraint = 1) AND ic.is_included_column = 0
        """,
    ):
        oid, cid, is_pk, is_uq = r
        flags = []
        if is_pk:
            flags.append("PK")
        if is_uq:
            flags.append("UQ")
        existing = constraint_cols.get((oid, cid), "")
        merged = existing
        for f in flags:
            if f not in merged:
                merged = (merged + "/" + f) if merged else f
        constraint_cols[(oid, cid)] = merged

    # -- 03 columns --------------------------------------------------------
    cols = q(
        cur,
        """
        SELECT s.name AS schema_name, t.name AS table_name, t.object_id,
               c.column_id, c.name AS column_name,
               ty.name AS data_type, c.max_length, c.precision, c.scale,
               c.is_nullable, c.is_identity, c.is_computed,
               c.collation_name,
               dc.name AS default_name, dc.definition AS default_definition,
               cc.definition AS computed_definition
        FROM sys.columns c
        JOIN sys.tables t ON t.object_id = c.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        JOIN sys.types ty ON ty.user_type_id = c.user_type_id
        LEFT JOIN sys.default_constraints dc
               ON dc.parent_object_id = c.object_id AND dc.parent_column_id = c.column_id
        LEFT JOIN sys.computed_columns cc
               ON cc.object_id = c.object_id AND cc.column_id = c.column_id
        ORDER BY s.name, t.name, c.column_id
        """,
    )
    by_table: dict[str, list] = {}
    for r in cols:
        key = f"{r[0]}.{r[1]}"
        by_table.setdefault(key, []).append(r)

    lines = ["# 03 — Columns\n", "Per-table column definition.\n"]
    for key, rows in by_table.items():
        lines.append(f"\n## {key}\n")
        table_rows = []
        for r in rows:
            (schema, tname, oid, cid, cname, dtype, maxlen, prec, scale,
             nullable, identity, computed, collation, dname, ddef, cdef) = r
            flags = constraint_cols.get((oid, cid), "")
            table_rows.append([
                cid,
                cname,
                fmt_type(dtype, maxlen, prec, scale),
                "NULL" if nullable else "NOT NULL",
                "YES" if identity else "",
                "YES" if computed else "",
                flags,
                (ddef or cdef or "").strip(),
                collation or "",
            ])
        lines.append(
            md_table(
                ["#", "column", "type", "nullability", "identity", "computed", "key", "default/expr", "collation"],
                table_rows,
            )
        )
    write("03_columns.md", "\n".join(lines))
    facts["column_count"] = len(cols)

    # -- 04 foreign keys ---------------------------------------------------
    fks = q(
        cur,
        """
        SELECT fk.name AS fk_name,
               ps.name AS parent_schema, pt.name AS parent_table, pc.name AS parent_column,
               rs.name AS ref_schema, rt.name AS ref_table, rc.name AS ref_column,
               fk.delete_referential_action_desc, fk.update_referential_action_desc
        FROM sys.foreign_keys fk
        JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
        JOIN sys.tables pt ON pt.object_id = fkc.parent_object_id
        JOIN sys.schemas ps ON ps.schema_id = pt.schema_id
        JOIN sys.columns pc ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
        JOIN sys.tables rt ON rt.object_id = fkc.referenced_object_id
        JOIN sys.schemas rs ON rs.schema_id = rt.schema_id
        JOIN sys.columns rc ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
        ORDER BY fk.name
        """,
    )
    lines = ["# 04 — Foreign Keys\n"]
    if not fks:
        lines.append("**No foreign keys defined.** Referential integrity is enforced at the application layer.\n")
    else:
        lines.append(md_table(
            ["fk", "parent", "column", "ref_table", "ref_column", "on_delete", "on_update"],
            [[r[0], f"{r[1]}.{r[2]}", r[3], f"{r[4]}.{r[5]}", r[6], r[7], r[8]] for r in fks],
        ))
    write("04_foreign_keys.md", "\n".join(lines))
    facts["fk_count"] = len(fks)

    # -- 05 indexes --------------------------------------------------------
    idx_meta = q(
        cur,
        """
        SELECT s.name AS schema_name, t.name AS table_name, t.object_id,
               i.index_id, i.name AS index_name, i.type_desc,
               i.is_unique, i.is_primary_key, i.is_unique_constraint,
               i.has_filter, i.filter_definition
        FROM sys.indexes i
        JOIN sys.tables t ON t.object_id = i.object_id
        JOIN sys.schemas s ON s.schema_id = t.schema_id
        WHERE NOT (i.index_id = 0 AND i.name IS NULL)
        ORDER BY s.name, t.name, i.index_id
        """,
    )
    idx_cols: dict[tuple[int, int], dict[str, list]] = {}
    for r in q(
        cur,
        """
        SELECT ic.object_id, ic.index_id, ic.key_ordinal, ic.is_included_column,
               ic.is_descending_key, c.name
        FROM sys.index_columns ic
        JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
        """,
    ):
        oid, iid, ordinal, is_incl, is_desc, name = r
        bucket = idx_cols.setdefault((oid, iid), {"key": [], "incl": []})
        if is_incl:
            bucket["incl"].append(name)
        else:
            bucket["key"].append((ordinal, name, is_desc))
    for bucket in idx_cols.values():
        bucket["key"].sort()
        bucket["key"] = [f"{n}{' DESC' if d else ''}" for _, n, d in bucket["key"]]

    lines = ["# 05 — Indexes\n"]
    for r in idx_meta:
        (schema, tname, oid, iid, iname, itype, unique, is_pk, is_uq, has_filter, filt) = r
        bucket = idx_cols.get((oid, iid), {"key": [], "incl": []})
        lines.append(f"\n### {schema}.{tname} :: {iname or '(heap)'}")
        rows = [
            ["type", itype],
            ["unique", "YES" if unique else "NO"],
            ["primary_key", "YES" if is_pk else "NO"],
            ["unique_constraint", "YES" if is_uq else "NO"],
            ["key_columns", ", ".join(bucket["key"]) or "(none)"],
            ["included_columns", ", ".join(bucket["incl"]) or "(none)"],
            ["filtered", (f"YES — {filt}" if has_filter else "NO")],
        ]
        lines.append(md_table(["property", "value"], rows))
    write("05_indexes.md", "\n".join(lines))
    facts["index_count"] = len(idx_meta)

    # -- 06 views ----------------------------------------------------------
    views = q(
        cur,
        """
        SELECT s.name AS schema_name, v.name AS view_name, v.object_id,
               v.create_date, v.modify_date, m.definition
        FROM sys.views v
        JOIN sys.schemas s ON s.schema_id = v.schema_id
        LEFT JOIN sys.sql_modules m ON m.object_id = v.object_id
        ORDER BY s.name, v.name
        """,
    )
    deps = q(
        cur,
        """
        SELECT sed.referencing_id, sed.referenced_id, sed.referenced_entity_name,
               sed.referenced_class_desc
        FROM sys.sql_expression_dependencies sed
        """,
    )
    referenced_by: dict[int, list[str]] = {}
    references_from: dict[int, list[str]] = {}
    for r in deps:
        rid, refid, refname, refclass = r
        references_from.setdefault(rid, []).append(refname or "")
        if refid is not None:
            referenced_by.setdefault(refid, []).append(refname or "")

    lines = ["# 06 — Views\n"]
    for r in views:
        schema, vname, oid, cdate, mdate, definition = r
        fname = f"{schema}.{vname}.sql"
        (SQL_VIEWS_DIR / fname).write_text(definition or "-- (no definition)\n", encoding="utf-8")
        deps_out = sorted(set(x for x in references_from.get(oid, []) if x))
        dependents = sorted(set(x for x in referenced_by.get(oid, []) if x))
        lines.append(f"\n## {schema}.{vname}")
        lines.append(f"- create_date: {cdate}")
        lines.append(f"- modify_date: {mdate}")
        lines.append(f"- full definition: `database_inventory/sql/views/{fname}`")
        lines.append(f"- **depends on (tables/views)**: {', '.join(deps_out) or '(none parsed)'}")
        lines.append(f"- **depended on by**: {', '.join(dependents) or '(none)'}")
    writer_note = "\n\n> Note: dependency parsing is based on `sys.sql_expression_dependencies` which relies on " \
                  "non-schema-bound references. Cross-database references may not appear.\n"
    lines.append(writer_note)
    write("06_views.md", "\n".join(lines))
    facts["view_count"] = len(views)

    # -- 07 procedures -----------------------------------------------------
    procs = q(
        cur,
        """
        SELECT s.name, p.name, m.definition
        FROM sys.procedures p
        JOIN sys.schemas s ON s.schema_id = p.schema_id
        LEFT JOIN sys.sql_modules m ON m.object_id = p.object_id
        ORDER BY s.name, p.name
        """,
    )
    lines = ["# 07 — Stored Procedures\n"]
    if not procs:
        lines.append("**No stored procedures defined in this database.**\n")
    else:
        for r in procs:
            lines.append(f"\n## {r[0]}.{r[1]}\n```sql\n{r[2]}\n```")
    write("07_procedures.md", "\n".join(lines))
    facts["proc_count"] = len(procs)

    # -- 08 functions ------------------------------------------------------
    funcs = q(
        cur,
        """
        SELECT s.name, o.name, o.type_desc, o.create_date, o.modify_date, m.definition
        FROM sys.objects o
        JOIN sys.schemas s ON s.schema_id = o.schema_id
        LEFT JOIN sys.sql_modules m ON m.object_id = o.object_id
        WHERE o.type IN ('FN','IF','TF','FS','FT','AF')
        ORDER BY o.name
        """,
    )
    lines = ["# 08 — Functions\n"]
    if not funcs:
        lines.append("**No user functions defined.**\n")
    else:
        for r in funcs:
            schema, name, tdesc, cdate, mdate, definition = r
            fname = f"{schema}.{name}.sql"
            (SQL_FUNCS_DIR / fname).write_text(definition or "-- (no definition)\n", encoding="utf-8")
            lines.append(f"\n## {schema}.{name}")
            lines.append(f"- type: {tdesc}")
            lines.append(f"- create_date: {cdate}")
            lines.append(f"- modify_date: {mdate}")
            lines.append(f"- full definition: `database_inventory/sql/functions/{fname}`")
    write("08_functions.md", "\n".join(lines))
    facts["func_count"] = len(funcs)

    # -- 09 triggers -------------------------------------------------------
    triggers = q(
        cur,
        """
        SELECT s.name AS schema_name, t.name AS table_name, tr.name AS trigger_name,
               tr.is_disabled, m.definition
        FROM sys.triggers tr
        LEFT JOIN sys.tables t ON t.object_id = tr.parent_id
        LEFT JOIN sys.schemas s ON s.schema_id = t.schema_id
        LEFT JOIN sys.sql_modules m ON m.object_id = tr.object_id
        ORDER BY tr.name
        """,
    )
    lines = ["# 09 — Triggers\n"]
    if not triggers:
        lines.append("**No triggers defined in this database.**\n")
    else:
        for r in triggers:
            lines.append(f"\n## {r[0]}.{r[1]} :: {r[2]} (disabled={r[3]})\n```sql\n{r[4]}\n```")
    write("09_triggers.md", "\n".join(lines))
    facts["trigger_count"] = len(triggers)

    # -- 10 other objects --------------------------------------------------
    seqs = q(cur, "SELECT s.name, sq.name, ty.name, sq.start_value, sq.increment FROM sys.sequences sq JOIN sys.schemas s ON s.schema_id=sq.schema_id JOIN sys.types ty ON ty.user_type_id=sq.user_type_id")
    syns = q(cur, "SELECT s.name, sy.name, sy.base_object_name FROM sys.synonyms sy JOIN sys.schemas s ON s.schema_id=sy.schema_id")
    checks = q(cur, "SELECT s.name, t.name, cc.name, cc.definition FROM sys.check_constraints cc JOIN sys.tables t ON t.object_id=cc.parent_object_id JOIN sys.schemas s ON s.schema_id=t.schema_id")
    queues = q(cur, "SELECT name FROM sys.service_queues WHERE is_ms_shipped=0")
    lines = ["# 10 — Other Objects\n"]
    lines.append(f"\n## Sequences ({len(seqs)})\n")
    lines.append(md_table(["schema", "name", "type", "start", "increment"], [list(r) for r in seqs]) if seqs else "None.")
    lines.append(f"\n## Synonyms ({len(syns)})\n")
    lines.append(md_table(["schema", "name", "base_object"], [list(r) for r in syns]) if syns else "None.")
    lines.append(f"\n## Check Constraints ({len(checks)})\n")
    lines.append(md_table(["schema", "table", "name", "definition"], [list(r) for r in checks]) if checks else "None.")
    lines.append(f"\n## Service Queues ({len(queues)})\n")
    lines.append(md_table(["name"], [list(r) for r in queues]) if queues else "None.")
    write("10_other_objects.md", "\n".join(lines))
    facts["sequence_count"] = len(seqs)
    facts["synonym_count"] = len(syns)
    facts["check_count"] = len(checks)

    # -- 11 dependency graph ----------------------------------------------
    graph = q(
        cur,
        """
        SELECT sed.referencing_id, ro.name AS referencing_name, ro.type_desc AS referencing_type,
               sed.referenced_id, sed.referenced_entity_name, sed.referenced_class_desc,
               sed.referenced_schema_name
        FROM sys.sql_expression_dependencies sed
        LEFT JOIN sys.objects ro ON ro.object_id = sed.referencing_id
        WHERE sed.referenced_id IS NOT NULL
        ORDER BY referencing_type, referencing_name, referenced_entity_name
        """,
    )
    lines = ["# 11 — Dependency Graph\n", "`referencing -> referenced` (from sys.sql_expression_dependencies).\n"]
    if not graph:
        lines.append("No schema-bound dependencies recorded.\n")
    else:
        lines.append(md_table(
            ["referencing object", "referencing type", "-> referenced", "referenced type"],
            [[r[1], r[2], f"{r[6] or ''}.{r[4]}" if r[6] else r[4], r[5]] for r in graph],
        ))
        lines.append("\n## Text graph\n")
        for r in graph:
            ref = f"{r[6]}.{r[4]}" if r[6] else r[4]
            lines.append(f"- {r[1]} ({r[2]})  ->  {ref} ({r[5]})")
    write("11_dependency_graph.md", "\n".join(lines))
    facts["dependency_edges"] = len(graph)

    # -- 12 samples --------------------------------------------------------
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    sample_index = ["# 12 — Sample Rows (max 5, sensitive columns masked)\n"]
    facts["samples"] = {}
    for trow in facts["tables"]:
        schema, tname, oid, row_count = trow["schema"], trow["name"], trow["object_id"], trow["row_count"]
        full = f"{schema}.{tname}"
        col_rows = [r for r in cols if r[2] == oid]
        col_names = [r[4] for r in col_rows]
        masked = [c for c in col_names if SENSITIVE_RE.search(c)]
        if row_count == 0:
            body = "_Table is empty._"
            sample_index.append(f"\n## {full}\n\nRow count: 0 — {body}")
            (SAMPLES_DIR / f"{full}.md").write_text(f"# {full}\n\nEmpty table.\n", encoding="utf-8")
            facts["samples"][full] = {"row_count": 0, "masked_columns": masked}
            continue
        try:
            data = q(cur, f"SELECT TOP 5 * FROM [{schema}].[{tname}]")
        except Exception as exc:  # noqa: BLE001
            (SAMPLES_DIR / f"{full}.md").write_text(f"# {full}\n\nCould not sample: {exc}\n", encoding="utf-8")
            facts["samples"][full] = {"row_count": row_count, "error": str(exc)}
            continue
        out_rows = []
        for data_row in data:
            out = []
            for cname, val in zip(col_names, data_row):
                if SENSITIVE_RE.search(cname):
                    out.append("***MASKED***")
                else:
                    out.append(fmt_value(val))
            out_rows.append(out)
        content = [f"# {full}\n", f"Row count (approx): {row_count}", f"Masked columns: {', '.join(masked) or '(none)'}\n"]
        content.append(md_table(col_names, out_rows))
        (SAMPLES_DIR / f"{full}.md").write_text("\n".join(content), encoding="utf-8")
        sample_index.append(f"\n## {full}\n\nRow count: {row_count} — masked: {', '.join(masked) or '(none)'} — see `12_samples/{full}.md`")
        facts["samples"][full] = {"row_count": row_count, "masked_columns": masked, "rows": len(data)}
    write("12_samples.md", "\n".join(sample_index))
    print("  wrote samples per table under 12_samples/")

    return facts


# ---------------------------------------------------------------------------
# Source usage scan (item 14)
# ---------------------------------------------------------------------------
def scan_sources() -> dict[str, Any]:
    usage: dict[str, list[dict[str, Any]]] = {o: [] for o in OBJECTS}
    patterns = {o: re.compile(r"\b" + re.escape(o) + r"\b", re.I) for o in OBJECTS}

    for root in SOURCE_ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SOURCE_EXTS:
                continue
            parts = {p.lower() for p in path.parts}
            if parts & SOURCE_EXCLUDE_DIRS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            lines = text.splitlines()
            for idx, line in enumerate(lines, 1):
                for obj, pat in patterns.items():
                    if pat.search(line):
                        upper = line.upper()
                        ops = [k for k in OP_KEYWORDS if re.search(r"\b" + k + r"\b", upper)]
                        usage[obj].append({
                            "file": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                            "line": idx,
                            "ops": ops,
                            "snippet": line.strip()[:160],
                        })
    for obj in usage:
        usage[obj].sort(key=lambda x: (x["file"], x["line"]))
    return usage


def write_source_usage(usage: dict[str, Any], facts: dict[str, Any]) -> None:
    lines = [
        "# 14 — Source Usage Map",
        "",
        "Search scope: `go-app/`, `go-app/py/`, `go-app/py2/` (`.go`, `.py`, `.sql`, `.json`).",
        "Operation keywords are heuristics derived from the same line (SELECT/INSERT/UPDATE/DELETE/FROM/INTO/JOIN/MERGE/EXEC).",
        "",
        "> Caveat: common English words (e.g. `statements`, `Users`, `TrackedTickers`) may produce",
        "> false positives. Review each hit in context.",
        "",
    ]
    counts: dict[str, dict[str, int]] = {}
    for obj in OBJECTS:
        hits = usage.get(obj, [])
        files: dict[str, int] = {}
        ops: dict[str, int] = {}
        for h in hits:
            files[h["file"]] = files.get(h["file"], 0) + 1
            for op in h["ops"]:
                ops[op] = ops.get(op, 0) + 1
        counts[obj] = {"hits": len(hits), "files": len(files)}
        lines.append(f"\n## {obj}\n")
        if not hits:
            lines.append("No references found in source.")
            continue
        lines.append(f"References: **{len(hits)}** across **{len(files)}** files. "
                     f"Op keywords: {', '.join(f'{k}={v}' for k, v in sorted(ops.items())) or '(none)'}\n")
        rows = [[h["file"], h["line"], "/".join(h["ops"]) or "-", h["snippet"]] for h in hits]
        lines.append(md_table(["file", "line", "op", "snippet"], rows))
    write("14_source_usage.md", "\n".join(lines))
    facts["source_usage_counts"] = counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    SQL_VIEWS_DIR.mkdir(parents=True, exist_ok=True)
    SQL_FUNCS_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    print("Connecting (read-only)...")
    cn = connect()
    try:
        cur = cn.cursor()
        print("Extracting database metadata...")
        facts = extract(cur)
    finally:
        cn.close()

    print("Scanning source for object usage...")
    usage = scan_sources()
    write_source_usage(usage, facts)

    (BASE_DIR / "_facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print("Done. Facts written to database_inventory/_facts.json")


if __name__ == "__main__":
    main()
