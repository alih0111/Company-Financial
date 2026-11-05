"""Inventory selected inputs and their retained financial evidence.

This is a financial evidence subset, not a complete market/recovery package.
Input records and manifests are read-only and are never rewritten.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def inventory(root: Path, selected_path: Path) -> dict:
    root = root.resolve()
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    by_path: dict[str, dict] = {}

    def add(path: Path, *, expected: str | None = None) -> None:
        path = path.resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("FINANCIAL_EVIDENCE_MISSING_OR_OUTSIDE_ROOT")
        relative = path.relative_to(root).as_posix()
        if relative in by_path:
            if expected is not None and by_path[relative]["sha256"] != expected:
                raise ValueError("FINANCIAL_EVIDENCE_HASH_MISMATCH")
            return
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
                count += len(chunk)
        actual = digest.hexdigest()
        if expected is not None and actual != expected:
            raise ValueError("FINANCIAL_EVIDENCE_HASH_MISMATCH")
        by_path[relative] = {"name": "financial_evidence", "path": relative,
                             "present": True, "bytes": count, "sha256": actual}

    for item in selected["artifacts"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or item["path"] == "EXTERNAL_PATH_REDACTED":
            raise ValueError("FINANCIAL_EVIDENCE_UNSAFE_PATH")
        add(root / relative, expected=item["sha256"])
    registration = json.loads((root / "ranking_research/output/owner_current_market_2026-10-15/registration.json").read_text(encoding="utf-8"))
    features = Path(registration["financial_path"])
    add(features, expected=registration.get("source_manifest", {}).get(str(features)))
    reports = json.loads((features.parent / "input_reports.json").read_text(encoding="utf-8"))
    dynamic_count = legacy_count = 0
    for report in reports:
        if report.get("dynamic_manifest_path"):
            dynamic_count += 1
            manifest_path = Path(report["dynamic_manifest_path"])
            add(manifest_path, expected=report["dynamic_manifest_sha256"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for page in manifest.get("pages", []):
                add(Path(page["path"]), expected=page["sha256"])
            native = manifest.get("native_export")
            if native:
                add(Path(native["path"]), expected=native["sha256"])
                original = root / "qvt_backtest/output/financial_history/reports" / f"{report['company_id']}_{report['tracing_no']}.json"
                add(original, expected=native["original_record_sha256"])
        else:
            legacy_count += 1
            name = f"{report['symbol']}_{report['tracing_no']}.html"
            candidates = [root / "provenance_v1/output/coverage_verified/raw" / name,
                          root / "provenance_v1/output/exp_2k13_codal/raw" / name]
            source = next((path for path in candidates if path.is_file()), None)
            if source is None:
                raise ValueError("FINANCIAL_LEGACY_BODY_MISSING")
            add(source)
    return {"scope": "Selected inputs and referenced financial evidence only; not a full recovery package or atomic cross-file snapshot.",
            "dynamic_report_records": dynamic_count, "legacy_report_records": legacy_count,
            "artifacts": [by_path[key] for key in sorted(by_path)]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--selected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root, args.selected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(f"OK: {len(result['artifacts'])} files; financial evidence subset only")


if __name__ == "__main__":
    main()
