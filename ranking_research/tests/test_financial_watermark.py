import ast
import sqlite3
from pathlib import Path


def test_financial_watermark_excludes_superseded_periods_without_hiding_new_reports():
    source = Path(__file__).resolve().parents[2] / "canonical_postgres_v1_2_1/analytics_canonical_v1/compute_metrics.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "INPUT_DOMAINS" for target in node.targets))
    query = ast.literal_eval(assignment.value)["financial"].replace("::text", "")
    with sqlite3.connect(":memory:") as db:
        db.execute("ATTACH DATABASE ':memory:' AS fundamentals")
        db.execute("ATTACH DATABASE ':memory:' AS ingestion")
        db.execute("CREATE TABLE fundamentals.financial_statements (report_id TEXT, period_end_date TEXT)")
        db.execute("CREATE TABLE ingestion.reports (supersedes_report_id TEXT)")
        db.executemany("INSERT INTO fundamentals.financial_statements VALUES (?, ?)",
                       [("bad", "2647-12-13"), ("current", "2026-09-22"), ("old", "2025-12-31")])
        db.executemany("INSERT INTO ingestion.reports VALUES (?)", [("bad",), (None,)])
        assert db.execute(query).fetchone()[0] == "2026-09-22"
        db.execute("DELETE FROM ingestion.reports WHERE supersedes_report_id = ?", ("bad",))
        assert db.execute(query).fetchone()[0] == "2647-12-13"
