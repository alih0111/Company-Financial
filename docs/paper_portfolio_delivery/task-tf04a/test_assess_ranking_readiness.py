from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = Path(__file__).with_name("assess_ranking_readiness.py")
SPEC = importlib.util.spec_from_file_location("assess_ranking_readiness", TOOL)
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
V36 = ROOT / "ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01/ranking/latest-ranking.json"
V36M = V36.with_name("manifest.json")
V37 = ROOT / "ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261024T190004112005Z-d1278aa0/ranking/latest-ranking.json"
V37M = V37.with_name("manifest.json")


def test_lock_review_validation_fixture_and_unscored_reasons():
    validation = json.loads((ROOT / "docs/paper_portfolio_delivery/task-tf03/review-finish/ranking-check/validation.json").read_text(encoding="utf-8-sig"))
    assert validation["status"] == "PASS"
    info = tool.inspect_snapshot(V36, V36M)
    assert info["canonical_hash_matches"] and info["manifest"]["matches_snapshot"]
    assert info["counts"]["unique_company_ids"] == 254
    assert info["counts"]["scored"] == {"P1": 166, "P3": 225}
    assert sum(info["unscored_reason_counts"]["P1"].values()) == 88
    assert sum(info["unscored_reason_counts"]["P3"].values()) == 29
    assert info["top_candidates"]["P1"][0]["symbol"] == "غاذر"


def test_positive_latest_cycle_snapshot_in_isolated_output(tmp_path):
    result = tool.assess(V37, tmp_path / "assessment", V37M)
    assert result["diagnostic_success"]
    assert result["validator"]["status"] == "PASS"
    assert result["controls"]["calculation_valid"]
    assert result["controls"]["source_panel_hash_matches"]
    assert result["controls"]["extraction_manifest_matches_snapshot"] is False
    assert result["controls"]["lineage_status"] == "INCOMPLETE"
    assert "UPSTREAM_EXTRACTION_MANIFEST_METADATA_MISMATCH" in result["blocked_reasons"]
    assert result["controls"]["receipt_evidence_status"] == "PARTIAL_MARKET_RECEIPT_FINANCIAL_RECEIPT_INCOMPLETE"
    assert result["controls"]["freshness_status"] == "UNKNOWN"
    assert result["controls"]["public_paper_decision_ready"] is False
    assert result["controls"]["official_future_evaluation_ready"] is False
    assert result["panel_provenance"]["received_at"]["nonnull"] == 0
    assert result["panel_provenance"]["price_date"]["max"] == "2026-10-24"
    assert result["panel_provenance"]["top_p1_source_lineage"]["financial_factor_lineage"]


@pytest.mark.parametrize(("received", "decision", "expected"), [
    (None, "2026-10-25T16:00:00+00:00", "UNKNOWN"),
    ("2026-10-25T17:00:00+00:00", "2026-10-25T16:00:00+00:00", "AFTER_DECISION"),
    ("2026-10-25T15:00:00+00:00", "2026-10-25T16:00:00+00:00", "BEFORE_OR_AT_DECISION"),
    ("2026-10-26T00:00:00+00:00", "2026-10-25T16:00:00+00:00", "AFTER_DECISION"),
])
def test_receipt_temporal_fixture(received, decision, expected):
    assert tool.temporal_receipt_status(received, decision) == expected


def test_modified_ranking_bytes_fail_canonical_check(tmp_path):
    doc = json.loads(V37.read_text(encoding="utf-8-sig"))
    doc["rows"][0]["symbol"] += "-altered"
    mutated = tmp_path / "mutated.json"
    mutated.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    info = tool.inspect_snapshot(mutated, V37M)
    assert not info["canonical_hash_matches"]
    assert not info["manifest"]["matches_snapshot"]


def test_nonempty_output_is_refused(tmp_path):
    destination = tmp_path / "not-empty"
    destination.mkdir()
    (destination / "prior.json").write_text("preserve", encoding="utf-8")
    with pytest.raises(ValueError, match="OUTPUT_DIR_NOT_EMPTY"):
        tool.assess(V37, destination, V37M)
    assert (destination / "prior.json").read_text(encoding="utf-8") == "preserve"
