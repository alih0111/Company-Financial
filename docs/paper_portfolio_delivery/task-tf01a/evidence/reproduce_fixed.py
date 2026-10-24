"""TF-01A adapted probe: the review's defective cases against the fixed code.

Synthetic fixtures, no network, no account writes. This file adapts
task-tf01/review/reproduce.py (left untouched) to schema v2 and documents the
mapping from each proven defect to its fixed behaviour. Exit code zero means
evidence collection completed, not product PASS.
"""
from pathlib import Path
import datetime as dt
import gzip
import hashlib
import json
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from ranking_research.tests import test_public_market_calendar as fixtures
from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf


def compact(result):
    return {"quality": result["quality"],
            "readiness_state": result["readiness"]["state"],
            "completion": result["completion"]["state"],
            "completion_observation": result["completion"]["watermark_observation"],
            "assumed_completion": (result["completion"]["assumed_completion"] or {}).get("value"),
            "decision_sessions": result["sessions_after_decision"],
            "candidate_state": (result["candidate"] or {}).get("state"),
            "source_health": result["source_health"],
            "problems": result["problems"]}


def run():
    cases = []
    for name, change in [
        ("candidate_payload_missing",
         lambda s: s["candidate_instrument"].update(doc={"instrumentInfo": None})),
        ("candidate_wrong_inscode",
         lambda s: s["candidate_instrument"]["doc"]["instrumentInfo"].update(insCode="999")),
        ("completion_source_network_failure",
         lambda s: s.update(last_possible={"state": "FETCH_FAILED",
                                           "error_code": "NETWORK_ERROR"})),
    ]:
        source = fixtures.make_sources()
        change(source)
        result = fixtures.evaluate(source)
        cases.append({"id": name,
                      "accepted_as_corroborated": result["quality"] == "CORROBORATED_PUBLIC",
                      "blocking_quality": result["quality"],
                      "session_count": result["sessions_after_decision"]["session_count"],
                      "actual": compact(result)})

    source = fixtures.make_sources(primary_dates=["20261019", "20261020", "20261021"],
                                   secondary_dates=[], watermark="20261021;20261021")
    result = fixtures.evaluate(source, window_start="20261022")
    cases.append({"id": "empty_secondary_before_decision",
                  "actual_quality": result["quality"],
                  "coverage_reasons": [p["reason"] for p in
                                       result["problems"].get("INSUFFICIENT_COVERAGE", [])],
                  "single_source_sessions_marked_confirmed": sum(
                      x["within_assumed_completion"] and not x["in_secondary"]
                      for x in result["observed_sessions"]),
                  "session_count": result["sessions_after_decision"]["session_count"]})

    source = fixtures.make_sources(primary_dates=["20260901", "20260902", "20260905"],
                                   secondary_dates=["20260905"],
                                   watermark="20260905;20260905")
    result = fixtures.evaluate(source, window_start="20260902")
    cases.append({"id": "secondary_has_no_anchor_before_decision",
                  "actual_quality": result["quality"],
                  "anchor_problems": [p for p in
                                      result["problems"].get("INSUFFICIENT_COVERAGE", [])
                                      if p["reason"] == "source_missing_decision_anchor"]})

    source = fixtures.make_sources(primary_dates=["20260901", "20260905"],
                                   secondary_dates=["20260905"],
                                   watermark="20260905;20260905")
    result = fixtures.evaluate(source, window_start="20260902")
    cases.append({"id": "secondary_starts_after_decision_but_no_exact_day_row",
                  "actual_quality": result["quality"],
                  "anchor_problems": [p for p in
                                      result["problems"].get("INSUFFICIENT_COVERAGE", [])
                                      if p["reason"] == "source_missing_decision_anchor"],
                  "session_count": result["sessions_after_decision"]["session_count"],
                  "first_session": result["sessions_after_decision"]["first_assumed_session"]})

    source = fixtures.make_sources(by_symbol={"TEST": fixtures.BASE_SESSIONS})
    result = fixtures.evaluate(source)
    cases.append({"id": "candidate_traded_all_sessions",
                  "trade_status": result["candidate"]["trade_status"],
                  "actual_missing_trade_sessions": result["candidate"]["no_positive_trade_sessions"],
                  "expected_missing_trade_sessions": []})

    with tempfile.TemporaryDirectory(prefix="tf01a-probe-") as directory:
        tmp = Path(directory)
        rows = [{"insCode": "123", "dEven": 20260910, "qTotTran5J": 100}]
        body = json.dumps({"closingPriceDaily": rows}).encode()
        raw = tmp / "foreign.gz"
        raw.write_bytes(gzip.compress(body))
        manifest = {"records": [
            {"symbol": "TSE_OK", "ins_code": "123",
             "sources": {"daily": {"raw_path": str(raw),
                                   "raw_sha256": hashlib.sha256(body).hexdigest()}}},
            {"symbol": "TEST_IFB", "ins_code": "123",
             "sources": {"daily": {"raw_path": str(raw),
                                   "raw_sha256": hashlib.sha256(body).hexdigest()}}},
        ]}
        (tmp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        identity_map = {
            "TSE_OK": {"flowTitle": "بازار بورس",
                       "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
                       "evidence_source": "probe fixture"},
            "TEST_IFB": {"flowTitle": "بازار فرابورس",
                         "cgrValCotTitle": "بازار دوم فرابورس",
                         "evidence_source": "probe fixture"},
        }
        stock = tf.load_stock_cross(tmp, window_start="20260901",
                                    market_scope="TSE", identity_map=identity_map)
        result = fixtures.evaluate(fixtures.make_sources(by_symbol=stock["by_symbol"]))
        cases.append({"id": "foreign_market_non_equity_archive_not_filtered",
                      "eligible_symbols": sorted(stock["by_symbol"]),
                      "skipped": [{s["symbol"]: s["reason"]} for s in stock["skipped"]],
                      "counts": stock["counts"],
                      "calendar_quality": result["quality"],
                      "conflicts": result["conflicts"]})

        # replay provenance: the pinned repo live manifest keeps its timestamps
        live_path = ROOT / ("ranking_research/output/public_market_calendar_tf01/"
                            "manifest.20261023T210632330575Z.json")
        live = json.loads(live_path.read_text(encoding="utf-8"))
        replay = tf.sources_from_records(live["sources"])
        cases.append({"id": "offline_drops_source_provenance",
                      "live_retrieved_sources": sum(bool(x.get("retrieved_at_utc"))
                                                    for x in live["sources"]),
                      "replay_retrieved_sources": sum(
                          bool(replay[k].get("retrieved_at_utc")) for k in replay)})

        # CLI replay must not touch the current account or the default snapshot
        def sentinel(args):
            raise RuntimeError("PROBE_SENTINEL_CURRENT_STATE_UNEXPECTEDLY_REQUIRED")
        out_dir = tmp / "replayed"
        with patch.object(sys, "argv", ["collector", "--from-manifest", str(live_path),
                                        "--output-dir", str(out_dir)]), \
             patch.object(tf, "ACCOUNT", tmp / "nonexistent-account.json"), \
             patch.object(tf, "DEFAULT_SNAPSHOT", tmp / "nonexistent-snapshot"), \
             patch.object(tf, "resolve_candidate", sentinel):
            try:
                tf.main()
                outcome = {"replayed_from_pinned": True,
                           "mode": json.loads((out_dir / "latest-manifest.json")
                                              .read_text(encoding="utf-8"))["run_id"]
                           and "replay"}
            except SystemExit as exc:
                outcome = {"replayed_from_pinned": False, "error": str(exc)}
        cases.append({"id": "offline_cli_depends_on_current_account", "actual": outcome})

    results = {
        "fixture_scope": ("TEST_FIXTURE except the read-only pinned repo live manifest "
                          "used by the CLI replay case; raw re-verification is read-only"),
        "network_requests": 0,
        "adapted_from": "docs/paper_portfolio_delivery/task-tf01/review/reproduce.py (untouched)",
        "schema": "v2 (parser tsetmc_public_index_calendar_v1@1.1.0)",
        "cases": cases,
    }
    (Path(__file__).parent / "reproduce_fixed.results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_count": len(cases),
                      "ids": [c["id"] for c in cases]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
