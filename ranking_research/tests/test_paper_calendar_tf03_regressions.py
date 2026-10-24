"""TF-03 integration regressions against real CLI entrypoints and temp paths."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv/Scripts/python.exe"
HARNESS = ROOT / "docs/paper_portfolio_delivery/task-tf03/run_offline_lifecycle.py"
EVIDENCE = ROOT / "docs/paper_portfolio_delivery/task-tf03/offline/lifecycle-evidence.json"


def test_subprocess_public_cycle_fill_mark_replay_isolated_and_network_blocked():
    run = subprocess.run([str(PYTHON), "-X", "utf8", str(HARNESS)], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=180)
    assert run.returncode == 0, run.stdout + run.stderr
    output = json.loads(run.stdout.strip().splitlines()[-1])
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert output["result"] == "PASS"
    assert "patches socket connect/create_connection" in evidence["network_block"]
    expected_failures = {case["case"]: case["expected_error"]
                         for case in evidence["preview_scenarios"] if case["expected_error"]}
    for stage in evidence["stages"]:
        case_name = next((case for case in expected_failures
                          if stage["name"] == case + "_preview"), None)
        if case_name:
            assert stage["exit_code"] != 0
            assert expected_failures[case_name] in stage["stderr"] + stage["stdout"]
        else:
            assert stage["exit_code"] == 0 and stage["stderr"] == "", stage
    assert evidence["cycle_wrapper_preview_bytes_unchanged"] is True
    assert evidence["preview_bytes_unchanged"] is True
    assert evidence["replay_before_mark_idempotent"] is True
    assert evidence["replay_after_mark_idempotent"] is True
    assert evidence["fill_event_count"] == 1
    assert evidence["fill_debit_toman"] == 99_957
    assert evidence["fill_receipt"]["shares"] == 806
    assert evidence["account_path"].startswith(str(ROOT / "docs/paper_portfolio_delivery/task-tf03/offline"))
    assert len(evidence["preview_scenarios"]) == 6
    assert all(case["account_unchanged"] for case in evidence["preview_scenarios"])


def test_inactive_public_draft_creator_is_append_only_and_temp_only(tmp_path):
    account = tmp_path / "draft" / "paper.json"
    rules = tmp_path / "draft" / "rules.json"
    run = subprocess.run([str(PYTHON), "-X", "utf8",
        str(ROOT / "ranking_research/future_eval_v12_30/create_public_paper_account.py"),
        "--ranking", str(ROOT / "client/public/research/v12-36/latest-ranking.json"),
        "--output-account", str(account), "--output-rules", str(rules),
        "--account-id", "TF03-TEST-DRAFT"], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    draft = json.loads(account.read_text(encoding="utf-8"))
    rule_doc = json.loads(rules.read_text(encoding="utf-8"))
    assert draft["status"] == "INACTIVE_PUBLIC_PAPER_DRAFT"
    assert draft["active_decision"] is None and draft["paper_order"] is None
    assert draft["cash_toman"] == draft["initial_capital_toman"] == 100_000_000
    assert draft["calendar_policy"] == rule_doc["calendar_policy"]
    assert draft["ranking"]["status"] == "PREPARATION_UNCONFIRMED"
