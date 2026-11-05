import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ranking_research.future_eval_v12_28.engine import AppendOnlyLedger, EvaluationError, HISTORICAL_CALENDAR_SHA256, canonical_json, sha256_bytes, snapshot_content_hash, validate_snapshot


CONTRACT = "a" * 64
NOW = datetime.fromisoformat("2026-10-22T08:00:00+00:00")


def make_snapshot(snapshot_id="future-1", day="2026-10-22", index=1197, received="2026-10-22T10:00:00+03:30", cutoff="2026-10-22T10:30:00+03:30"):
    end = datetime.fromisoformat(day).date()
    count = index - 1165
    dates = [(end - timedelta(days=n)).isoformat() for n in range(count - 1, -1, -1)]
    rows = []
    for symbol, ix, p1, p3 in [("ب", 1, 10.0, 7.0), ("الف", 0, 10.0, 8.0), ("پ", 2, 2.0, 11.0)]:
        rows.append({"symbol": symbol, "symbol_index": ix, "methods": {
            "P1": {"score": p1, "financial_coverage": 0.0, "raw_factors": {"f": 1.0}, "defaulted_factors": [], "masked_factors": [], "dq": 1.0},
            "P3": {"score": p3, "financial_coverage": 0.0, "raw_factors": {"f": 2.0}, "defaulted_factors": [], "masked_factors": [], "dq": 1.0},
        }})
    snap = {"schema_version": 1, "data_scope": "TEST_FIXTURE", "environment": "TEST_FIXTURE", "snapshot_id": snapshot_id,
            "effective_date": day, "received_at": received, "decision_cutoff_at": cutoff, "timezone": "Asia/Tehran", "contract_sha256": CONTRACT,
            "calendar": {"anchor_date": "2021-04-03", "anchor_index": 0, "session_index": index, "session_date": day,
                         "complete_through_effective_date": True, "history_prefix_sha256": HISTORICAL_CALENDAR_SHA256, "additional_session_dates": dates,
                         "calendar_sha256": sha256_bytes(canonical_json({"history_prefix_sha256": HISTORICAL_CALENDAR_SHA256, "additional_session_dates": dates})),
                         "calendar_source_sha256": "d" * 64, "next_session_open_at": "2026-10-23T09:00:00+03:30"},
            "expected_history_calendar_sha256": HISTORICAL_CALENDAR_SHA256,
            "score_provenance": {"uses_only_snapshot_inputs": True, "scorer_contract_sha256": CONTRACT, "raw_input_sha256": "c" * 64, "scorer_version":"v12.28-test-fixture"}, "universe": rows}
    snap["snapshot_sha256"] = snapshot_content_hash(snap)
    return snap


class FutureEvaluationTests(unittest.TestCase):
    def test_o00_anchor_and_63_session_grid_preserved(self):
        self.assertEqual(validate_snapshot(make_snapshot(), CONTRACT, NOW, allow_test_fixture=True)["session_index"], 1197)
        bad = make_snapshot(index=1196)
        bad["snapshot_sha256"] = snapshot_content_hash(bad)
        with self.assertRaisesRegex(EvaluationError, "NOT_AN_O00_REVIEW_SESSION"):
            validate_snapshot(bad, CONTRACT, NOW, allow_test_fixture=True)

    def test_incomplete_calendar_rejected_without_date_guess(self):
        s = make_snapshot(); s["calendar"]["complete_through_effective_date"] = False; s["snapshot_sha256"] = snapshot_content_hash(s)
        with self.assertRaisesRegex(EvaluationError, "CALENDAR_INCOMPLETE"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)

    def test_received_time_not_confused_with_effective_date(self):
        s = make_snapshot(received="2026-10-22T11:00:00+03:30", cutoff="2026-10-22T10:30:00+03:30"); s["snapshot_sha256"] = snapshot_content_hash(s)
        with self.assertRaisesRegex(EvaluationError, "DATA_RECEIVED_AFTER_DECISION_CUTOFF"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)

    def test_later_data_does_not_mutate_prior_snapshot_decision(self):
        first = make_snapshot("s1"); second = make_snapshot("s2"); second["universe"][0]["methods"]["P1"]["score"] = 999; second["snapshot_sha256"] = snapshot_content_hash(second)
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            self.assertEqual(ledger.record_decisions(first, "ACTIVE", NOW), ["APPENDED", "APPENDED"])
            prior = json.dumps(ledger.events(), ensure_ascii=False, sort_keys=True)
            prior_count = len(ledger.events())
            self.assertEqual(ledger.record_decisions(second, "ACTIVE", NOW), ["APPENDED", "APPENDED"])
            after = ledger.events()
            self.assertEqual(json.dumps(after[:prior_count], ensure_ascii=False, sort_keys=True), prior)
            p1 = [e for e in after if e.get("event_type") == "DECISION" and e["snapshot_id"] == "s1"][0]
            self.assertEqual(p1["selected_symbol"], "الف")

    def test_wrong_snapshot_contract_and_nonfuture_inputs_are_rejected(self):
        s = make_snapshot(); s["contract_sha256"] = "d" * 64; s["score_provenance"]["scorer_contract_sha256"] = "d" * 64; s["snapshot_sha256"] = snapshot_content_hash(s)
        with self.assertRaisesRegex(EvaluationError, "CONTRACT_HASH_MISMATCH"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)
        s = make_snapshot(); s["data_scope"] = "HISTORICAL_REPLAY"; s["snapshot_sha256"] = snapshot_content_hash(s)
        with self.assertRaisesRegex(EvaluationError, "NON_PROSPECTIVE_DATA_REJECTED"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)

    def test_test_fixture_cannot_enter_official_ledger_path(self):
        with tempfile.TemporaryDirectory() as d:
            official_path = Path(d) / "return_v12_28" / "official_event_ledger.jsonl"
            ledger = AppendOnlyLedger(official_path, CONTRACT, official_path=True)
            with self.assertRaisesRegex(EvaluationError, "NON_PROSPECTIVE_DATA_REJECTED"):
                ledger.record_decisions(make_snapshot(), "ACTIVE", NOW)
            self.assertFalse(official_path.exists())

    def test_corrupt_and_incomplete_snapshot_rejected(self):
        s = make_snapshot(); s["snapshot_sha256"] = "0" * 64
        with self.assertRaisesRegex(EvaluationError, "SNAPSHOT_HASH_MISMATCH"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)
        s = make_snapshot(); s["universe"][0]["methods"].pop("P3"); s["snapshot_sha256"] = snapshot_content_hash(s)
        with self.assertRaisesRegex(EvaluationError, "BOTH_LOCKED_METHODS_REQUIRED"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)

    def test_repeat_snapshot_is_idempotent_and_conflicting_id_fails(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            s = make_snapshot()
            self.assertEqual(ledger.register_snapshot(s, NOW), "APPENDED")
            self.assertEqual(ledger.register_snapshot(s, NOW), "DUPLICATE_NOOP")
            changed = copy.deepcopy(s); changed["universe"][0]["methods"]["P1"]["score"] = 55; changed["snapshot_sha256"] = snapshot_content_hash(changed)
            with self.assertRaisesRegex(EvaluationError, "SNAPSHOT_ID_CONFLICT_DIFFERENT_CONTENT"):
                ledger.register_snapshot(changed, NOW)

    def test_waiting_state_blocks_official_decision_and_accounts_are_independent(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            with self.assertRaisesRegex(EvaluationError, "OFFICIAL_START_NOT_ACTIVE"):
                ledger.record_decisions(make_snapshot(), "WAITING_FOR_DATA", NOW)
            ledger.record_decisions(make_snapshot(), "ACTIVE", NOW)
            decisions = [e for e in ledger.events() if e.get("event_type") == "DECISION"]
            self.assertEqual({x["method_id"] for x in decisions}, {"P1", "P3"})
            self.assertEqual(decisions[0]["state_pre"]["cash_toman"], 100_000_000)
            self.assertEqual(decisions[1]["state_pre"]["cash_toman"], 100_000_000)
            self.assertEqual(decisions[0]["pending_order_created"]["symbol"], "الف")
            self.assertEqual(decisions[1]["pending_order_created"]["symbol"], "پ")

    def test_execution_after_eligible_time_partial_fill_and_no_fill(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            snapshot = make_snapshot()
            ledger.record_decisions(snapshot, "ACTIVE", NOW)
            with self.assertRaisesRegex(EvaluationError, "EXECUTION_BEFORE_FIRST_ELIGIBLE_TIME"):
                ledger.record_fill("f0", "future-1:P1:entry:الف", "P1", "الف", 1, 100, 1, "2026-10-22T10:45:00+03:30", "2026-10-23T09:00:00+03:30")
            fixture_now = datetime.fromisoformat("2026-10-23T06:00:00+00:00")
            self.assertEqual(ledger.record_fill("f1", "future-1:P1:entry:الف", "P1", "الف", 2, 100, 2, "2026-10-23T09:10:00+03:30", "2026-10-23T09:00:00+03:30", "PARTIAL", price_source="local execution fixture", corporate_action_status="VERIFIED", execution_constraints="RECORDED", now=fixture_now), "APPENDED")
            self.assertEqual(ledger.record_fill("f2", "future-1:P3:entry:پ", "P3", "پ", 0, 0, 0, "2026-10-23T09:10:00+03:30", "2026-10-23T09:00:00+03:30", "NOT_EXECUTED", reason="no eligible quote", now=fixture_now), "APPENDED")
            with self.assertRaisesRegex(EvaluationError, "EXECUTION_EVENT_TIME_IN_FUTURE"):
                ledger.record_fill("f3", "future-1:P1:entry:الف", "P1", "الف", 1, 100, 1, "2026-10-24T09:10:00+03:30", "2026-10-23T09:00:00+03:30", "PARTIAL", price_source="local execution fixture", corporate_action_status="VERIFIED", execution_constraints="RECORDED", now=fixture_now)
            execution = [e for e in ledger.events() if e.get("event_type") == "ORDER_EXECUTION"]
            self.assertEqual(execution[0]["cash_delta_toman"], -202)
            self.assertEqual(execution[1]["cash_delta_toman"], 0)
            self.assertEqual(execution[0]["state_post"]["cash_toman"], 99_999_798)
            self.assertEqual(execution[0]["state_post"]["nav_toman"], 99_999_998)
            self.assertEqual(ledger.record_fill("f1", "future-1:P1:entry:الف", "P1", "الف", 2, 100, 2, "2026-10-23T09:10:00+03:30", "2026-10-23T09:00:00+03:30", "PARTIAL", price_source="local execution fixture", corporate_action_status="VERIFIED", execution_constraints="RECORDED"), "DUPLICATE_NOOP")
            valuation_args = {"event_id":"v1","method_id":"P1","snapshot_id":"valuation-1","snapshot_sha256":"e"*64,
                              "effective_at":"2026-10-23T09:30:00+03:30","received_at":"2026-10-23T10:00:00+03:30","decision_cutoff_at":"2026-10-23T10:15:00+03:30",
                              "prices_toman_per_share":{"الف":110},"price_source":"local actual-share mark fixture","corporate_action_status":"VERIFIED",
                              "now":datetime.fromisoformat("2026-10-23T07:00:00+00:00")}
            self.assertEqual(ledger.record_valuation(**valuation_args), "APPENDED")
            self.assertEqual(ledger.record_valuation(**valuation_args), "DUPLICATE_NOOP")
            valued = [e for e in ledger.events() if e.get("event_type") == "VALUATION"][-1]
            self.assertEqual(valued["state_post"]["nav_toman"], 100_000_018)
            self.assertEqual(valued["state_post"]["net_profit_toman"], 18)
            missing = dict(valuation_args, event_id="v2", prices_toman_per_share={})
            self.assertEqual(ledger.record_valuation(**missing), "APPENDED")
            self.assertIsNone(ledger.events()[-1]["state_post"]["nav_toman"])
            self.assertEqual(ledger.events()[-1]["missing_symbols"], ["الف"])

    def test_late_future_cutoff_and_out_of_order_ledger_are_rejected(self):
        s = make_snapshot(); s["decision_cutoff_at"] = "2026-10-24T10:30:00+03:30"; s["snapshot_sha256"] = snapshot_content_hash(s)
        with self.assertRaisesRegex(EvaluationError, "DECISION_CUTOFF_IN_FUTURE"):
            validate_snapshot(s, CONTRACT, NOW, allow_test_fixture=True)
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            common = {"snapshot_id":"s","snapshot_sha256":"c"*64,"effective_date":"2026-10-22","received_at":"2026-10-22T10:00:00+03:30","decision_cutoff_at":"2026-10-22T10:30:00+03:30"}
            ledger.append({"event_id":"a","event_type":"UNSPECIFIED_TEST_EVENT","recorded_at":"2026-10-22T10:00:00+00:00",**common})
            with self.assertRaisesRegex(EvaluationError, "EVENT_RECORDING_TIME_REVERSED"):
                ledger.append({"event_id":"b","event_type":"UNSPECIFIED_TEST_EVENT","recorded_at":"2026-10-22T09:00:00+00:00",**common})

    def test_correction_is_a_new_linked_event_and_does_not_mutate_target(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            snapshot = make_snapshot()
            ledger.record_decisions(snapshot, "ACTIVE", NOW)
            target_id = f"decision:{snapshot['snapshot_id']}:P1"
            before = next(e for e in ledger.events() if e["event_id"] == target_id)
            self.assertEqual(ledger.append_correction("corr-1", target_id, {"field":"note","value":"clarified"}, "2026-10-23T12:00:00+00:00"), "APPENDED")
            after = next(e for e in ledger.events() if e["event_id"] == target_id)
            correction = next(e for e in ledger.events() if e["event_id"] == "corr-1")
            self.assertEqual(before, after)
            self.assertEqual(correction["supersedes_event_id"], target_id)
            self.assertTrue(correction["corrects_without_mutating_target"])

    def test_actual_accounting_rejects_invalid_money_and_unknown_order(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = AppendOnlyLedger(Path(d) / "events.jsonl", CONTRACT)
            with self.assertRaisesRegex(EvaluationError, "ORDER_NOT_FOUND_IN_EVENT_LEDGER"):
                ledger.record_fill("e","missing","P1","الف",1,100,1,"2026-10-23T09:10:00+03:30","2026-10-23T09:00:00+03:30")


if __name__ == "__main__":
    unittest.main()
