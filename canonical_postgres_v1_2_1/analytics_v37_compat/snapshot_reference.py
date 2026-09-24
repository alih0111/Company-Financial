"""Freeze SQL Server v3.7 reference output (READ ONLY) + reference context.

Writes:
  analytics_parity/reference/v37_full_snapshot.csv
  analytics_parity/reference_context.json
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = BASE.parent
sys.path.insert(0, str(BASE / "migration_tools"))

from common import sqlserver_conn  # noqa: E402

PARITY = BASE / "analytics_parity"
REF = PARITY / "reference"


def main() -> int:
    captured_at = datetime.now(timezone.utc)
    cn = sqlserver_conn()
    cur = cn.cursor()

    cur.execute("SELECT DB_NAME()")
    dbname = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM dbo.vw_AIStockMetrics")
    row_count = cur.fetchone()[0]
    cur.execute("SELECT DISTINCT TOP 1 ScoreVersion FROM dbo.vw_AIStockMetrics")
    sv = cur.fetchone()
    score_version = sv[0] if sv else None

    cur.execute("SELECT COUNT(*) FROM dbo.TrackedTickers")
    tracked = cur.fetchone()[0]

    def scalar(sql, default=None):
        try:
            cur.execute(sql)
            r = cur.fetchone()
            return r[0] if r else default
        except Exception:
            return default

    watermarks = {
        "max_mph_gregorian": str(scalar("SELECT MAX(GregorianDate) FROM dbo.MarketPriceHistory")),
        "max_mph_collected_at": str(scalar("SELECT MAX(CollectedAt) FROM dbo.MarketPriceHistory")),
        "max_miandore2_reportdate": str(scalar("SELECT MAX(ReportDate) FROM dbo.miandore2")),
        "max_mahane_reportdate": str(scalar("SELECT MAX(ReportDate) FROM dbo.mahane")),
        "max_codal_published": str(scalar("SELECT MAX(PublishedAt) FROM dbo.CodalReports")),
    }

    cur.execute("SELECT * FROM dbo.vw_AIStockMetrics ORDER BY QuantScore DESC")
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    REF.mkdir(parents=True, exist_ok=True)
    with (REF / "v37_full_snapshot.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if v is None else v for v in r])

    ctx = {
        "captured_at_utc": captured_at.isoformat(timespec="seconds"),
        "analysis_cutoff_at_utc": captured_at.isoformat(timespec="seconds"),
        "analysis_as_of_date": captured_at.date().isoformat(),
        "sqlserver_database": dbname,
        "production_view": "dbo.vw_AIStockMetrics",
        "production_view_score_version": score_version,
        "reference_row_count": row_count,
        "tracked_tickers_count": tracked,
        "v37_snapshot_columns": len(cols),
        "source_watermarks": watermarks,
        "view_definition_snapshot": "canonical_design_inputs/sql/vw_AIStockMetrics_production.sql",
        "note": "All PG v3.7-compat computations MUST use analysis_cutoff_at and must not read data collected after it.",
    }
    (PARITY / "reference_context.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    cn.close()
    print("captured:", ctx["captured_at_utc"], "rows:", row_count, "cols:", len(cols), "ScoreVersion:", score_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
