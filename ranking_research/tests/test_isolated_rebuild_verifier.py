import hashlib
import json

import pandas as pd
import pytest

from scripts.verify_isolated_rebuild import verify


def test_rebuild_verifier_checks_lineage_hashes_and_detects_changed_input(tmp_path):
    root = tmp_path / "source"
    out = root / "output"
    ranking_dir = out / "ranking"
    public = tmp_path / "public"
    ranking_dir.mkdir(parents=True)
    public.mkdir()
    source = root / "reports.json"
    source.write_bytes(b"financial fixture")
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    panel = out / "normalized_raw_factor_panel.parquet"
    pd.DataFrame({"company_id": ["one"], "factor": [1.5],
                  "sales_lineage": ['{"latest_period":null}']}).to_parquet(panel)
    extraction = {"source_sha256": {"reports.json": sha(source)},
                  "market_package": {"daily_file_sha256": {}}, "panel_sha256": sha(panel),
                  "factors": {"factor_observed_counts": {"factor": 1}},
                  "financial": {"reports_path": "reports.json", "verified_comparative_facts": 1},
                  "source_dates": {"monthly_sales_latest_event_month": "1405-06"},
                  "official_tsetmc_source_manifest_sha256": sha(source)}
    (out / "extraction_manifest.json").write_text(json.dumps(extraction), encoding="utf-8")
    rank = {"rows": [{"company_id": "one"}], "scored_count": {"P1": 1},
            "source_provenance": {"financial_archive": {"source": "reports.json", "comparative_facts": 1},
                                  "TSETMC": {"source_manifest": "reports.json"},
                                  "monthly_sales_archive": {"source": "reports.json", "latest_event_period": "1405-06",
                                                            "received_at": None, "received_at_status": "UNKNOWN_IN_ARCHIVE"}}}
    canonical = json.dumps(rank, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    rank["artifact_sha256"] = hashlib.sha256(canonical).hexdigest()
    for directory in (ranking_dir, public):
        (directory / "latest-ranking.json").write_text(json.dumps(rank), encoding="utf-8")
        (directory / "latest-ranking.csv").write_text("fixture\n", encoding="utf-8")
    manifest = {"artifact_sha256": rank["artifact_sha256"],
                "json_sha256": sha(ranking_dir / "latest-ranking.json"),
                "csv_sha256": sha(ranking_dir / "latest-ranking.csv"),
                "public_json_sha256": sha(public / "latest-ranking.json"),
                "public_csv_sha256": sha(public / "latest-ranking.csv")}
    (ranking_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify(out, public, root)["input_hashes_verified"] == 1
    source.write_bytes(b"changed fixture")
    with pytest.raises(ValueError, match="INPUT_HASH_MISMATCH"):
        verify(out, public, root)
