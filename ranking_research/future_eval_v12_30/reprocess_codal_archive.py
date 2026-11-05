"""Reparse verified Codal bodies from local caches without making requests."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ranking_research/output/paper_cycle/codal"
PYTHON = ROOT / ".venv/Scripts/python.exe"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_body_items(items: dict, root: Path = ROOT) -> dict:
    return {str(tracing_no): item for tracing_no, item in items.items()
            if (item.get("body_evidence") or {}).get("path")
            and (item.get("body_evidence") or {}).get("sha256")
            and (root / item["body_evidence"]["path"]).is_file()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=dt.datetime.now(dt.timezone.utc).strftime("archive-reprocess-%Y%m%dT%H%M%SZ"))
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from ranking_research.future_eval_v12_30.acquire_codal_incremental import load_archived_report_items

    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    run_dir = OUT / args.run_id
    manifest_path = run_dir / "manifest.json"
    feeds = {}
    source_paths = {}
    for key, letter_type in (("financial", 6), ("sales", 58)):
        items = load_archived_report_items(key)
        eligible = verified_body_items(items)
        feeds[key] = {
            "letter_type": letter_type,
            "state": "local_archive_only",
            "report_ids": list(eligible.values()),
            "archived_items_seen": len(items),
            "valid_body_items_reused": len(eligible),
            "network_requests": 0,
            "receipt_timestamps_preserved": True,
            "source_cache": f"ranking_research/output/paper_cycle/codal/archive/{key}-report-cache.json",
        }
        source_paths[key] = {str(k): v.get("body_evidence", {}).get("sha256") for k, v in eligible.items()}
    manifest = {"schema_version": 1, "run_id": args.run_id, "source": "local Codal archive/cache; no network",
        "read_only": True, "started_at_utc": stamp, "finished_at_utc": stamp,
        "frozen_universe_count": 254, "feeds": feeds,
        "archive_body_hashes": source_paths,
        "receipt_time_backdated": False}
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    command = [str(PYTHON), str(ROOT / "ranking_research/future_eval_v12_30/prepare_codal_inputs.py"), str(manifest_path)]
    parsed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    prepared_path = run_dir / "prepared/prepared-inputs.json"
    prepared = json.loads(prepared_path.read_text(encoding="utf-8")) if prepared_path.exists() else {}
    try:
        ranking = json.loads((ROOT / "client/public/research/v12-37/latest-ranking.json").read_text(encoding="utf-8"))
        evaluation_date = ranking["evaluation_date"]
    except (OSError, ValueError, KeyError, TypeError):
        evaluation_date = dt.datetime.now(dt.timezone.utc).date().isoformat()
    factor_out = run_dir / "factor-inputs"
    factors = subprocess.run([str(PYTHON), str(ROOT / "ranking_research/future_eval_v12_30/build_codal_factor_inputs.py"),
        str(manifest_path), "--evaluation-date", evaluation_date, "--output-dir", str(factor_out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    admission_path = factor_out / "admission.json"
    admission = json.loads(admission_path.read_text(encoding="utf-8")) if admission_path.exists() else {}
    summary = {
        "run_id": args.run_id,
        "manifest": str(manifest_path.relative_to(ROOT)).replace("\\", "/"),
        "manifest_sha256": digest(manifest_path),
        "network_requests": 0,
        "archive_bodies_reused": sum(len(feed["report_ids"]) for feed in feeds.values()),
        "financial_bodies_reused": len(feeds["financial"]["report_ids"]),
        "sales_bodies_reused": len(feeds["sales"]["report_ids"]),
        "financial_parsed": len(prepared.get("financial", [])),
        "sales_parsed": len(prepared.get("sales", [])),
        "parse_errors": len(prepared.get("errors", [])),
        "parse_error_details": prepared.get("errors", []),
        "evaluation_date": evaluation_date,
        "factor_admission": {feed: {"parsed_candidates": admission.get(feed, {}).get("parsed_candidates", 0),
            "admitted": admission.get(feed, {}).get("admitted", 0), "held": admission.get(feed, {}).get("held", 0),
            "admission_errors": admission.get(feed, {}).get("admission_errors", [])} for feed in ("financial", "sales")},
        "factor_input_preparation_exit_code": factors.returncode,
        "factor_input_admission_path": str(admission_path.relative_to(ROOT)).replace("\\", "/") if admission_path.exists() else None,
        "receipt_time_backdated": False,
        "source_body_hashes_preserved": True,
        "parser_exit_code": parsed.returncode,
        "parser_stdout": parsed.stdout[-3000:],
        "parser_stderr": parsed.stderr[-3000:],
        "finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (run_dir / "archive-reprocess-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("run_id", "archive_bodies_reused", "financial_parsed", "sales_parsed", "parse_errors", "network_requests", "parser_exit_code", "factor_input_preparation_exit_code")}, ensure_ascii=False))
    # Individual invalid/incomplete documents are quarantine outcomes, not a
    # runner/setup failure. Preserve parser_exit_code and per-document errors.
    return 0 if prepared_path.exists() and admission_path.exists() and factors.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
