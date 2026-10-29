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


def test_selected_financial_max_rows_are_timezone_sorted_and_traced(tmp_path):
    v36 = tool.assess(V36, tmp_path / "v36-max", V36M)
    max36 = v36["panel_provenance"]["selected_financial_max_row"]
    assert max36["symbol"] == "تپمپی"
    assert max36["financial_lineage"][-1]["tracing_no"] == "1608939"
    cutoff = v36["panel_provenance"]["extraction_manifest"]["consistency_checks"]["publication_cutoff_comparison"]
    assert cutoff["difference_microseconds"] == 1 and not cutoff["same_tehran_boundary_within_1us"]
    assert cutoff["display_boundary_difference"] is True
    v37 = tool.assess(V37, tmp_path / "v37-max", V37M)
    max37 = v37["panel_provenance"]["selected_financial_max_row"]
    assert max37["symbol"] == "تاصیکو"
    assert max37["financial_factor_lineage"][0]["tracing_no"] == "1601930"


def test_positive_latest_cycle_snapshot_in_isolated_output(tmp_path):
    result = tool.assess(V37, tmp_path / "assessment", V37M)
    assert result["diagnostic_success"]
    assert result["validator"]["status"] == "PASS"
    assert result["controls"]["calculation_valid"]
    assert result["controls"]["identity_universe_match"]["status"] == "PASS"
    assert result["controls"]["source_panel_hash_matches"]
    assert result["panel_provenance"]["extraction_manifest"]["consistency_checks"]["archive_financial_stat_matches_file_and_hash"] is True
    assert result["panel_provenance"]["extraction_manifest"]["consistency_checks"]["selected_panel_financial_latest_within_cutoff"] is True
    assert result["controls"]["extraction_manifest_matches_snapshot"] is False  # real fixed metadata/date mismatch remains visible
    assert result["panel_provenance"]["financial_date_scopes"]["archive_actual_max_utc"] != result["panel_provenance"]["financial_date_scopes"]["selected_panel_max"]
    assert result["controls"]["lineage_status"] == "INCOMPLETE"  # fixed v12-35 metadata still mismatches
    assert "UPSTREAM_EXTRACTION_MANIFEST_METADATA_MISMATCH" in result["blocked_reasons"]
    assert result["controls"]["receipt_evidence_status"] == "SOURCE_RECEIPT_NOT_VERIFIED"
    assert result["controls"]["freshness_status"] == "UNKNOWN"
    assert result["controls"]["public_paper_decision_ready"] is False
    assert result["controls"]["official_future_evaluation_ready"] is False
    assert result["panel_provenance"]["received_at"]["nonnull"] == 0
    assert result["panel_provenance"]["price_date"]["max"] == "2026-10-24"
    assert result["panel_provenance"]["top_p1_source_lineage"]["financial_factor_lineage"]


@pytest.mark.parametrize(("received", "decision", "expected"), [
    (None, "2026-10-25T16:00:00+00:00", "UNKNOWN_NO_RECEIPT"),
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


def test_timezone_equivalence_and_invalid_receipt_times():
    assert tool.temporal_receipt_status("2026-10-25T19:30:00+03:30", "2026-10-25T16:00:00Z") == "BEFORE_OR_AT_DECISION"
    assert tool.temporal_receipt_status("2026-10-25T19:30:00", "2026-10-25T16:00:00Z") == "INVALID_OR_TIMEZONE_MISSING"
    assert tool.temporal_receipt_status("not-a-time", "2026-10-25T16:00:00Z") == "INVALID_OR_TIMEZONE_MISSING"
    assert tool.temporal_receipt_status("2026-10-25T17:00:00Z", None) == "NOT_CHECKED_NO_DECISION_TIME"
    assert tool.cutoff_comparison("2026-10-22T00:00:00+03:30", "2026-10-21T20:30:00Z")["same_instant"]
    boundary = tool.cutoff_comparison("2026-10-22T00:00:00+03:30", "2026-10-21T20:29:59.999999Z")
    assert not boundary["same_tehran_boundary_within_1us"] and not boundary["exact_inclusive_exclusive_boundary_equivalent"] and boundary["difference_microseconds"] == 1
    assert boundary["display_boundary_difference"] is True
    within_day = tool.cutoff_comparison("2026-10-21T12:00:00.000001Z", "2026-10-21T12:00:00Z")
    assert not within_day["same_tehran_boundary_within_1us"]
    assert not tool.cutoff_comparison("2026-10-23T00:00:00+03:30", "2026-10-21T20:30:00Z")["same_tehran_boundary_within_1us"]


def test_assess_exposes_real_time_evidence_and_no_decision_state(tmp_path):
    result = tool.assess(V37, tmp_path / "time-assessment", V37M)
    assert result["time_evidence"]["observed_at_utc"]
    assert result["time_evidence"]["hypothetical_decision_at"] is None
    assert result["time_evidence"]["financial_lineage_receipt_count"] > 0
    lineage_receipts = result["time_evidence"]["financial_lineage_receipts"]
    assert lineage_receipts and all(not x["source_provenance_valid"] for x in lineage_receipts)
    assert result["time_evidence"]["market_receipt"]["manifest_sha256"]
    assert result["time_evidence"]["market_receipt"]["registration_hash_matches_declaration"] is True


def test_assess_reports_hash_bound_market_receipt_after_hypothetical_decision(tmp_path):
    result = tool.assess(V37, tmp_path / "decision-assessment", V37M,
                         decision_at="2026-10-24T18:00:00Z")
    market_time = result["time_evidence"]["market_receipt"]["timestamp"]
    assert market_time["relative_to_hypothetical_decision"] == "AFTER_DECISION"
    assert market_time["source_provenance_valid"]
    assert result["time_evidence"]["market_receipt"]["registration_hash_matches_declaration"]


def test_actual_assess_rejects_panel_tampering(tmp_path):
    import pandas as pd
    panel = ROOT / "ranking_research/output/return_v12_37/v12_37_daily_paper-cycle-20261024T190004112005Z-d1278aa0/normalized_raw_factor_panel.parquet"
    assert panel.is_file()
    altered = tmp_path / "altered.parquet"
    frame = pd.read_parquet(panel)
    frame.loc[0, "company_id"] = "tampered-company-id"
    frame.to_parquet(altered, index=False)
    result = tool.assess(V37, tmp_path / "panel-assessment", V37M, altered)
    assert result["validator"]["status"] == "FAIL"
    assert result["controls"]["calculation_valid"] is False
    assert result["controls"]["identity_universe_match"]["status"] == "NOT_VERIFIED"
    assert result["controls"]["scoreability_rule_verification"] == "NOT_VERIFIED"


def test_identity_mismatch_is_not_reported_pass_when_validation_fails(tmp_path):
    doc = json.loads(V37.read_text(encoding="utf-8-sig"))
    doc["rows"][0]["symbol"] += "-tampered"
    path = tmp_path / "changed-ranking.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    result = tool.assess(path, tmp_path / "bad-ranking", V37M)
    assert result["validator"]["status"] == "NOT_RUN"  # canonical tamper refuses locked validation
    assert result["controls"]["identity_universe_match"]["status"] == "NOT_VERIFIED"
    assert result["controls"]["scoreability_rule_verification"] == "NOT_VERIFIED"
