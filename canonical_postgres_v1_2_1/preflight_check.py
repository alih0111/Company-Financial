#!/usr/bin/env python3
"""Static preflight checks for canonical_postgres_v1_2_1.

No database connection required. Read-only. Exit code non-zero on any failure.

Checks:
  * all expected SQL files exist and are in the 001..090 sequence
  * no duplicate CREATE INDEX / TABLE / VIEW / TRIGGER / FUNCTION object names
  * integrity test IDs are unique and match the count declared in README.md
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
SQL_DIR = BASE / "sql"

EXPECTED_SQL = [
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

OBJECT_PATTERNS = {
    "TABLE": re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w.]*)", re.I),
    "VIEW": re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([A-Za-z_][\w.]*)", re.I),
    "INDEX": re.compile(r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w.]*)", re.I),
    "TRIGGER": re.compile(r"\bCREATE\s+TRIGGER\s+([A-Za-z_][\w.]*)", re.I),
    "FUNCTION": re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+([A-Za-z_][\w.]*)", re.I),
}

TEST_ID_RE = re.compile(r"^\|\s*([PCSMAL]\d{2})\s*\|")
README_COUNT_RE = re.compile(r"Test count \(auto\):\s*(\d+)")

errors: list[str] = []
warnings: list[str] = []


def strip_comments(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


# 1) file presence and order -------------------------------------------------
print("== SQL files ==")
present = sorted(p.name for p in SQL_DIR.glob("*.sql"))
for name in EXPECTED_SQL:
    if not (SQL_DIR / name).exists():
        errors.append(f"missing SQL file: {name}")
extra = [n for n in present if n not in EXPECTED_SQL]
if extra:
    warnings.append(f"unexpected SQL files: {', '.join(extra)}")
print(f"  found {len(present)} sql files; expected {len(EXPECTED_SQL)}")

# 2) duplicate object names ---------------------------------------------------
print("== duplicate object names ==")
objects: dict[str, dict[str, list[str]]] = {k: defaultdict(list) for k in OBJECT_PATTERNS}
for name in EXPECTED_SQL:
    path = SQL_DIR / name
    if not path.exists():
        continue
    code = strip_comments(path.read_text(encoding="utf-8"))
    for kind, pat in OBJECT_PATTERNS.items():
        for m in pat.finditer(code):
            objects[kind][m.group(1).lower()].append(name)

for kind, table in objects.items():
    dups = {k: v for k, v in table.items() if len(v) > 1}
    for k, files in sorted(dups.items()):
        errors.append(f"duplicate {kind} '{k}' in: {', '.join(files)}")
    print(f"  {kind}: {len(table)} unique names, {len(dups)} duplicates")

# 3) integrity test IDs -------------------------------------------------------
print("== integrity tests ==")
plan = (BASE / "integrity_test_plan.md").read_text(encoding="utf-8")
ids = [m.group(1) for line in plan.splitlines() if (m := TEST_ID_RE.match(line))]
seen: dict[str, int] = defaultdict(int)
for i in ids:
    seen[i] += 1
dup_ids = {k: v for k, v in seen.items() if v > 1}
for k, v in sorted(dup_ids.items()):
    errors.append(f"duplicate test id {k} (x{v})")
unique_count = len(seen)
print(f"  unique test ids: {unique_count}, duplicate ids: {len(dup_ids)}")

# 4) README declared count matches -------------------------------------------
readme = (BASE / "README.md").read_text(encoding="utf-8")
m = README_COUNT_RE.search(readme)
if not m:
    errors.append("README.md missing 'Test count (auto): N' marker")
else:
    declared = int(m.group(1))
    print(f"  README declares: {declared}")
    if declared != unique_count:
        errors.append(f"README test count {declared} != actual {unique_count}")

# 5) summary -----------------------------------------------------------------
print("\n== preflight summary ==")
for w in warnings:
    print(f"  WARN: {w}")
if errors:
    for e in errors:
        print(f"  FAIL: {e}")
    print(f"\nPREFLIGHT: FAIL ({len(errors)} error(s))")
    sys.exit(1)
print("PREFLIGHT: PASS")
sys.exit(0)
