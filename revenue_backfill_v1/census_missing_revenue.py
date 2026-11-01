#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""سرشماری شرکت‌های دارای زنجیره درآمد ناقص (بک‌فیل فروش — گام ۱).

موتور امتیازدهی (compute_metrics) پنج فاکتور «رشد درآمد دقیق، حاشیه عملیاتی،
حاشیه خالص، روند حاشیه، P/S» را از revenue_ttm می‌سازد و revenue_ttm از
زنجیره گزارش‌های کدال. جایی که فکت‌های درآمد (RevenueNew و خانواده‌اش در
منبع legacy) غایب باشند، این پنج فاکتور «بدون داده → ۳۰٪» می‌شوند.

این اسکریپت فقط‌خواندنی است: از آخرین اجرای سرو (analytics.score_runs با
run_kind='serving') نمادهای دارای OperatingMargin بدون مقدار خام را برمی‌دارد
و فایل ورودی بک‌فیل (نمادها، سطر به سطر) و گزارش JSON می‌سازد.

اجرا:
    python revenue_backfill_v1/census_missing_revenue.py
خروجی:
    revenue_backfill_v1/output/symbols_for_backfill.txt
    revenue_backfill_v1/output/census_report.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "canonical_postgres_v1_2_1" / "migration_tools"))

os.environ.setdefault("CDF_PILOT_DB", "company_financial_analytics_shadow_v121")
from common import pg_pilot_conn  # noqa: E402

OUT = Path(__file__).resolve().parent / "output"

# فاکتورهایی که همگی از revenue_ttm مشتق می‌شوند؛ با نبودِ هر کدام در یک
# شرکت، زنجیره درآمد همان شرکت ناقص است.
REVENUE_DERIVED_FACTORS = (
    "OperatingMargin", "NetMargin", "MarginTrend", "RevenueGrowth", "PS",
)


def latest_serving_run(cur):
    cur.execute(
        """
        SELECT id::text, run_seq, as_of_date::text, completed_at::text
        FROM analytics.score_runs
        WHERE run_kind = 'serving' AND status = 'completed'
        ORDER BY run_seq DESC LIMIT 1
        """
    )
    return cur.fetchone()


def census(cur, run_id):
    """نمادهایی که حداقل یکی از فاکتورهای مشتق درآمد در آن‌ها بی‌مقدار است."""
    placeholders = ", ".join("%s" for _ in REVENUE_DERIVED_FACTORS)
    cur.execute(
        f"""
        SELECT DISTINCT c.display_name
        FROM analytics.factor_scores fs
        JOIN core.companies c ON c.id::text = fs.company_id::text
        WHERE fs.run_id = %s
          AND fs.factor_code IN ({placeholders})
          AND fs.raw_value IS NULL
        ORDER BY c.display_name
        """,
        (run_id, *REVENUE_DERIVED_FACTORS),
    )
    return [r[0] for r in cur.fetchall()]


def per_factor_counts(cur, run_id):
    cur.execute(
        """
        SELECT fs.factor_code,
               count(*) FILTER (WHERE fs.raw_value IS NOT NULL),
               count(*) FILTER (WHERE fs.raw_value IS NULL)
        FROM analytics.factor_scores fs
        WHERE fs.run_id = %s
          AND fs.factor_code = ANY(%s)
        GROUP BY fs.factor_code ORDER BY fs.factor_code
        """,
        (run_id, list(REVENUE_DERIVED_FACTORS)),
    )
    return {r[0]: {"with_value": r[1], "missing": r[2]} for r in cur.fetchall()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pg = pg_pilot_conn(autocommit=True)
    cur = pg.cursor()
    run = latest_serving_run(cur)
    if not run:
        print("هیچ اجرای سرو کاملی پیدا نشد")
        return 1
    run_id, run_seq, as_of, completed = run
    print(f"آخرین اجرای سرو: #{run_seq} · as_of={as_of} · {completed}")

    missing = census(cur, run_id)
    counts = per_factor_counts(cur, run_id)

    symbols_path = OUT / "symbols_for_backfill.txt"
    symbols_path.write_text("\n".join(missing) + ("\n" if missing else ""), encoding="utf-8")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "serving_run": {"id": run_id, "run_seq": run_seq, "as_of": as_of},
        "factor_coverage": counts,
        "affected_symbols": missing,
        "affected_count": len(missing),
        "symbols_file": str(symbols_path),
    }
    (OUT / "census_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    for code, c in sorted(counts.items()):
        print(f"  {code}: {c['with_value']} دارای مقدار · {c['missing']} بدون مقدار")
    print(f"نمادهای نیازمند بک‌فیل: {len(missing)} → {symbols_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
