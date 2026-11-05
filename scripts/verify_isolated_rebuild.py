"""Verify a restored V12.37 build without modifying any source or account."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def strict_json(path: Path):
    def reject(value):
        raise ValueError("NONSTANDARD_JSON_CONSTANT:" + value)
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def verify(output: Path, public: Path, source_root: Path, reference: Path | None = None) -> dict:
    output, public, source_root = output.resolve(), public.resolve(), source_root.resolve()
    extraction = strict_json(output / "extraction_manifest.json")
    ranking_dir = output / "ranking"
    rank = strict_json(ranking_dir / "latest-ranking.json")
    manifest = strict_json(ranking_dir / "manifest.json")
    inputs = dict(extraction["source_sha256"])
    for name, digest in extraction["market_package"]["daily_file_sha256"].items():
        if name in inputs and inputs[name] != digest:
            raise ValueError("INPUT_MANIFEST_CONFLICT")
        inputs[name] = digest
    for name, digest in inputs.items():
        path = Path(name)
        path = path if path.is_absolute() else source_root / path
        if not path.is_file() or file_sha(path) != digest:
            raise ValueError("INPUT_HASH_MISMATCH:" + name)
    panel_path = output / "normalized_raw_factor_panel.parquet"
    if file_sha(panel_path) != extraction["panel_sha256"]:
        raise ValueError("PANEL_HASH_MISMATCH")
    for key, path in {
        "json_sha256": ranking_dir / "latest-ranking.json",
        "csv_sha256": ranking_dir / "latest-ranking.csv",
        "public_json_sha256": public / "latest-ranking.json",
        "public_csv_sha256": public / "latest-ranking.csv",
    }.items():
        if file_sha(path) != manifest[key]:
            raise ValueError("RANKING_FILE_HASH_MISMATCH:" + key)
    if (ranking_dir / "latest-ranking.json").read_bytes() != (public / "latest-ranking.json").read_bytes():
        raise ValueError("PUBLIC_RANKING_DIFFERS")
    payload = dict(rank)
    claimed = payload.pop("artifact_sha256")
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != claimed or manifest["artifact_sha256"] != claimed:
        raise ValueError("RANKING_ARTIFACT_HASH_MISMATCH")
    panel = pd.read_parquet(panel_path)
    panel_ids = panel["company_id"].astype(str)
    rank_ids = [str(row["company_id"]) for row in rank["rows"]]
    if panel_ids.duplicated().any() or len(set(rank_ids)) != len(rank_ids) or set(panel_ids) != set(rank_ids):
        raise ValueError("RANKING_IDENTITY_MISMATCH")
    for value in panel["sales_lineage"]:
        json.loads(value, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONSTANDARD_SALES_JSON:" + value)))
    for factor, count in extraction["factors"]["factor_observed_counts"].items():
        observed = int(np.isfinite(pd.to_numeric(panel[factor], errors="coerce").to_numpy(dtype=float)).sum())
        if observed != count:
            raise ValueError("FACTOR_COUNT_MISMATCH:" + factor)
    provenance = rank["source_provenance"]
    if (provenance["financial_archive"]["source"] != extraction["financial"]["reports_path"]
            or provenance["financial_archive"]["comparative_facts"] != extraction["financial"]["verified_comparative_facts"]
            or provenance["financial_archive"]["source"] not in inputs
            or provenance["monthly_sales_archive"]["source"] not in inputs
            or provenance["monthly_sales_archive"]["latest_event_period"] != extraction["source_dates"]["monthly_sales_latest_event_month"]
            or inputs.get(provenance["TSETMC"]["source_manifest"]) != extraction["official_tsetmc_source_manifest_sha256"]
            or provenance["monthly_sales_archive"]["received_at"] is not None):
        raise ValueError("RANKING_PROVENANCE_MISMATCH")
    result = {"input_hashes_verified": len(inputs), "rows": len(panel), "artifact_sha256": claimed,
              "scored_count": rank["scored_count"], "comparative_facts": extraction["financial"]["verified_comparative_facts"],
              "receipt_status": provenance["monthly_sales_archive"]["received_at_status"]}
    if reference is not None:
        previous = pd.read_parquet(reference / "normalized_raw_factor_panel.parquet").set_index("company_id")
        current = panel.set_index("company_id").reindex(previous.index)
        if len(previous) != len(panel) or set(previous.index) != set(panel["company_id"]):
            raise ValueError("REFERENCE_IDENTITY_MISMATCH")
        differences = {}
        for factor in extraction["factors"]["factor_observed_counts"]:
            a = pd.to_numeric(previous[factor], errors="coerce").to_numpy(dtype=float)
            b = pd.to_numeric(current[factor], errors="coerce").to_numpy(dtype=float)
            changed = int((~np.isclose(a, b, rtol=1e-10, atol=1e-8, equal_nan=True)).sum())
            if changed:
                differences[factor] = changed
        result["reference_factor_differences"] = differences
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.output, args.public, args.source_root, args.reference), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
