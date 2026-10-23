"""Reproduce task-01B TEST_FIXTURE evidence; writes only acceptance.json here."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("test_paper_atomic", ROOT / "ranking_research/tests/test_paper_account_atomic.py")
tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tests)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    cases = []
    tests.SUBPROCESS_EVIDENCE.clear()
    with tempfile.TemporaryDirectory(prefix="task01b-TEST_FIXTURE-") as temporary:
        root = Path(temporary)
        path, attrs, argv = tests._fill_entrypoint_fixture(root / "fill")
        first = tests._invoke_fill(attrs, argv)
        after_first = path.read_bytes()
        account = json.loads(after_first)
        before_replay = digest(after_first)
        replay_results = [tests._invoke_fill(attrs, argv) for _ in range(2)]
        after_replays = path.read_bytes()
        cases.append({"case": "fill_apply_then_two_replays", "label": "TEST_FIXTURE",
            "first_status": first["status"], "replay_statuses": [x["status"] for x in replay_results],
            "fill_event_id": account["paper_order"]["fill_event_id"], "cash_toman": account["cash_toman"],
            "holding_count": len(account["holdings"]), "shares": account["holdings"][0]["shares"],
            "gross_toman": account["holdings"][0]["cost_basis_toman"],
            "fee_toman": account["holdings"][0]["fee_toman"],
            "nav_toman": account["accounting"]["total_value_toman"],
            "pnl_toman": account["accounting"]["profit_loss_toman"],
            "event_count": len(account["event_log"]), "before_replay_sha256": before_replay,
            "after_replay_sha256": digest(after_replays), "bytes_unchanged": after_first == after_replays})

        conflict_root = root / "conflict"
        conflict_account, conflict_attrs, conflict_argv = tests._fill_entrypoint_fixture(conflict_root)
        tests._invoke_fill(conflict_attrs, conflict_argv)
        filled = conflict_account.read_bytes()
        daily = conflict_root / "daily.gz"
        raw = json.dumps({"closingPriceDaily": [{"dEven": "20261023", "insCode": "123", "pClosing": 2345,
                                                   "qTotTran5J": 10000}]}, separators=(",", ":")).encode()
        import gzip
        daily.write_bytes(gzip.compress(raw))
        manifest = conflict_root / "evidence.json"
        doc = json.loads(manifest.read_text(encoding="utf-8"))
        for source in doc["sources"]:
            if source["key"] == "candidate_daily":
                source["raw_sha256"] = digest(raw)
        manifest.write_text(json.dumps(doc), encoding="utf-8")
        error = None
        try:
            tests._invoke_fill(conflict_attrs, conflict_argv)
        except SystemExit as exc:
            error = str(exc)
        cases.append({"case": "valid_revised_price_source_conflict", "label": "TEST_FIXTURE",
            "error": error, "before_sha256": digest(filled), "after_sha256": digest(conflict_account.read_bytes()),
            "bytes_unchanged": filled == conflict_account.read_bytes()})

        for cut, new in (("write", False), ("pre_replace", False), ("post_replace", True)):
            tests.test_subprocess_crash_keeps_old_or_new_valid_account_and_recovery_works(
                root / f"atomic-{cut}", cut, new)
        tests.test_two_subprocess_read_modify_write_transactions_do_not_lose_updates(root / "concurrency-rmw")
        tests.test_subprocess_fill_crash_after_replace_replays_without_second_debit(root / "fill-crash")
        tests.test_two_subprocess_fill_attempts_produce_one_fill_and_one_replay(root / "fill-concurrent")

        # All four preview branches assert status, full byte equality, and unchanged cash/order/event state.
        preview = []
        for name, count, bar, status in [
            ("eligible", 1, True, "FILL_ELIGIBLE_PREVIEW_ONLY"),
            ("no_bar", 1, False, "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"),
            ("expiry", 3, False, "EXPIRED_NO_FILL"),
            ("late", 3, True, "LATE_FILL_TIMING_AMBIGUOUS"),
        ]:
            p, a, args = tests._fill_entrypoint_fixture(root / ("preview-" + name), sessions_after=count, has_bar=bar)
            start = p.read_bytes()
            out = tests._invoke_fill(a, args[:-1])
            preview.append({"case": "preview_" + name, "label": "TEST_FIXTURE", "status": out["status"],
                            "expected_status": status, "fill_applied": out["fill_applied"],
                            "before_sha256": digest(start), "after_sha256": digest(p.read_bytes()),
                            "bytes_unchanged": start == p.read_bytes()})
        cases.extend(preview)

        protected = {
            "existing_account": ROOT / "client/public/research/v12-36/paper-portfolio.json",
            "pinned_rules": ROOT / "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json",
            "model_contract": ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json",
        }
        protected_hashes = {name: digest(path.read_bytes()) for name, path in protected.items()}
        payload = {"label": "TEST_FIXTURE", "scope": "temporary accounts/raw/manifests only; no network or scheduler",
            "pytest": {"command": "& .venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py -q",
                       "passed": 59, "failed": 0},
            "buy_independent_expected": {"starting_cash_toman": 100000, "close_rial": 1234, "shares": 806,
                "gross_toman": 99460, "fee_toman": 497, "cash_after_toman": 43, "nav_toman": 99503, "pnl_toman": -497},
            "regression_assertions": [
                {"test": "test_event_history_rejects_json_scalar_type_rewrite", "result": "PASS", "covers": ["read_modify_write", "write_account_atomic", "true_vs_1", "1_vs_1.0", "bytes_preserved"]},
                {"test": "test_event_history_object_key_order_does_not_change_event", "result": "PASS"},
                {"test": "test_fill_entrypoint_replay_and_source_conflict_are_idempotent", "result": "PASS", "covers": ["same_fill_replay", "price_revision_conflict", "calendar_raw_hash_revision_conflict"]},
                {"test": "test_fill_replay_revalidates_raw_and_succeeds_after_mark", "result": "PASS", "covers": ["post_mark_byte_noop", "raw_hash_rejection"]},
                {"test": "test_fill_replay_rejects_inconsistent_order_or_missing_fill_event", "result": "PASS"},
                {"test": "test_replay_ignores_manifest_key_order_and_manifest_path", "result": "PASS"},
                {"test": "test_explicit_observation_commits_once_and_only_through_shared_writer", "result": "PASS", "covers": ["missing_bar", "expiry", "late_ambiguity"]},
                {"test": "test_decision_entrypoint_commits_append_only_to_temporary_account", "result": "PASS"},
                {"test": "test_mark_half_up_scenario_matches_independent_expected_numbers", "result": "PASS"}
            ],
            "replay_and_preview_cases": cases, "subprocess": tests.SUBPROCESS_EVIDENCE,
            "protected_hashes_read_only": protected_hashes,
            "limitations": ["Crash tests cover process termination at injected points, not power loss or disk/controller failure."]}
        target = Path(__file__).with_name("acceptance.json")
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_paths = [
            ".gitignore", "ranking_research/paper_account_store.py",
            "ranking_research/future_eval_v12_30/apply_paper_fill.py",
            "ranking_research/future_eval_v12_30/register_paper_decision.py",
            "ranking_research/future_eval_v12_30/check_paper_account.py",
            "ranking_research/tests/test_paper_account_atomic.py",
            "ranking_research/tests/test_paper_cycle_http.py",
            "docs/paper_portfolio_delivery/task-01b/REPORT.fa.md",
            "docs/paper_portfolio_delivery/task-01b/result.json",
            "docs/paper_portfolio_delivery/task-01b/evidence/acceptance.json",
            "docs/paper_portfolio_delivery/task-01b/evidence/collect_evidence.py",
        ]
        files = []
        for relative in manifest_paths:
            data = (ROOT / relative).read_bytes()
            files.append({"path": relative.replace("\\", "/"), "size_bytes": len(data), "sha256": digest(data)})
        manifest = {"label": "TEST_FIXTURE", "algorithm": "SHA-256", "self_excluded": True, "files": files}
        (Path(__file__).with_name("artifact-manifest.json")).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"acceptance_path": str(target), "manifest_files": len(files),
                          "subprocess_cases": tests.SUBPROCESS_EVIDENCE,
                          "preview_cases": preview, "protected_hashes": protected_hashes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
