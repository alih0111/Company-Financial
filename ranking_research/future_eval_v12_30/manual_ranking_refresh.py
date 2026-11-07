"""Fast admin ranking refresh from data already collected by Quick Sync.

No Codal or TSETMC request is made here.  The command reads canonical
PostgreSQL, reuses the last complete market package, and publishes a new
V12.37 artifact with the unchanged P1/P3 scorers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path(os.environ.get("CDF_PYTHON") or sys.executable)
STATUS = ROOT / ".runtime/ranking-refresh-status.json"
TEHRAN = ZoneInfo("Asia/Tehran")


def write_status(**values) -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    current = {}
    if STATUS.exists():
        try:
            current = json.loads(STATUS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = {}
    current.update(values)
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STATUS)


def latest_complete_market_pack() -> Path:
    manifests = sorted((ROOT / "ranking_research/output/paper_cycle/market").glob("*/manifest.json"),
                       key=lambda path: path.stat().st_mtime, reverse=True)
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("completed_count", 0)) == 254 and int(data.get("failed_count", 1)) == 0:
            return path.parent
    raise RuntimeError("بستهٔ کامل قیمت برای ۲۵۴ نماد پیدا نشد")


def latest_codal_manifest() -> Path:
    manifests = sorted((ROOT / "ranking_research/output/paper_cycle/codal").glob("paper-cycle-*/manifest.json"),
                       key=lambda path: path.stat().st_mtime, reverse=True)
    if not manifests:
        raise RuntimeError("مانیفست محلی کدال پیدا نشد")
    return manifests[0]


def run(command: list[str], *, env: dict | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    evaluation_date = now.astimezone(TEHRAN).date().isoformat()
    run_root = ROOT / "ranking_research/output/paper_cycle" / args.run_id
    factor_dir = run_root / "factor-inputs"
    ranking_dir = ROOT / "ranking_research/output/return_v12_37" / args.run_id
    try:
        write_status(state="Running", stage="preparing_inputs", latest_run_id=args.run_id,
                     cycle_status="LOCAL_CANONICAL_REFRESH_RUNNING", ranking_stage_status="preparing_inputs",
                     fresh_financial_reports=False, fresh_monthly_sales=False,
                     started_at_utc=now.isoformat(), finished_at_utc=None, error=None,
                     message="در حال خواندن داده‌های جمع‌آوری‌شده و آماده‌سازی ورودی رتبه‌بندی…")
        market_pack = latest_complete_market_pack()
        codal_manifest = latest_codal_manifest()
        factor_dir.mkdir(parents=True, exist_ok=False)
        run([str(PYTHON), str(ROOT / "ranking_research/future_eval_v12_30/build_codal_factor_inputs.py"),
             str(codal_manifest), "--evaluation-date", evaluation_date,
             "--output-dir", str(factor_dir), "--dynamic-store-dir", str(factor_dir / "raw")])
        admission = json.loads((factor_dir / "admission.json").read_text(encoding="utf-8"))
        financial_count = int(admission.get("financial", {}).get("admitted", 0))
        sales_count = int(admission.get("sales", {}).get("admitted", 0))

        write_status(stage="ranking_p1_p3", ranking_stage_status="calculating",
                     fresh_financial_reports=financial_count > 0, fresh_monthly_sales=sales_count > 0,
                     message="ورودی‌های تازه آماده شد؛ در حال محاسبهٔ P1 و P3…")
        env = os.environ.copy()
        env.update({
            "V1237_MARKET_PACK": str(market_pack), "V1237_RANKING_DATE": evaluation_date,
            "V1237_DATASET_ID": f"v12_37_canonical_quick_sync_{evaluation_date.replace('-', '')}",
            "V1237_OUTPUT_DIR": str(ranking_dir),
            "V1237_PUBLIC_DIR": str(ROOT / "client/public/research/v12-37"),
            "V1237_REPORTS_PATH": str(factor_dir / "input_reports.json"),
            "V1237_COMPARATIVES_PATH": str(factor_dir / "comparative_lineage.json"),
            "V1237_OWNER_LINEAGE_PATH": str(factor_dir / "current_live_lineage.json"),
            "V1237_EVENTS_PATH": str(factor_dir / "monthly_sales_events.parquet"),
            "V1237_FRESH_FINANCIAL_IDS_PATH": str(factor_dir / "fresh-financial-ids.json"),
        })
        env.pop("V1237_ISOLATED_OUTPUT", None)
        run([str(PYTHON), str(ROOT / "ranking_research/future_eval_v12_30/build_latest_supported_v12_37.py")], env=env)
        artifact = json.loads((ROOT / "client/public/research/v12-37/latest-ranking.json").read_text(encoding="utf-8"))
        finished = dt.datetime.now(dt.timezone.utc)
        write_status(state="Ready", stage="completed", cycle_status="LOCAL_CANONICAL_REFRESH_COMPLETE",
                     ranking_stage_status="rebuilt_with_canonical_quick_sync_inputs",
                     last_run_time=finished.isoformat(), last_task_result=0,
                     evaluation_date=artifact.get("evaluation_date"),
                     scored_count=artifact.get("scored_count"), finished_at_utc=finished.isoformat(),
                     message=f"رتبه‌بندی با {financial_count} ورودی مالی و {sales_count} ورودی فروش محلی بازسازی شد.")
        return 0
    except Exception as exc:
        finished = dt.datetime.now(dt.timezone.utc)
        write_status(state="Failed", stage="failed", cycle_status="LOCAL_CANONICAL_REFRESH_FAILED",
                     ranking_stage_status="failed", last_run_time=finished.isoformat(), last_task_result=1,
                     finished_at_utc=finished.isoformat(), error=str(exc),
                     message="بازسازی رتبه‌بندی ناموفق بود؛ گزارش اجرای محلی را بررسی کنید.")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
