import subprocess
import sys
import time
import json
import os
from pathlib import Path

import pytest

from ranking_research.future_eval_v12_30 import apply_paper_fill
from ranking_research.future_eval_v12_30.paper_cycle import acquire_cycle_lock


def test_account_state_replaced_atomically_in_one_file(tmp_path, monkeypatch):
    account = tmp_path / "paper-account.json"
    account.write_text('{"cash": 100}\n', encoding="utf-8")
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", account)
    apply_paper_fill.write_account_atomic({"cash": 75, "event": "fill"})
    assert account.read_text(encoding="utf-8") == '{\n  "cash": 75,\n  "event": "fill"\n}\n'
    assert not account.with_suffix(".json.tmp").exists()


def test_expiry_is_checked_after_designated_session_evidence():
    outcome = apply_paper_fill.expiry_outcome(3, 3, first_session_fill_eligible=True)
    assert outcome == "late_fill_timing_ambiguous"
    assert apply_paper_fill.expiry_outcome(3, 3, first_session_fill_eligible=False) == "expire"
    assert apply_paper_fill.expiry_outcome(2, 3, first_session_fill_eligible=True) == "continue"


def test_short_or_truncated_calendar_cannot_expire_order():
    complete_window = [{"DEven": f"202609{i:02d}"} for i in range(1, 21)]
    assert apply_paper_fill.calendar_covers_order_window(complete_window, "20260920")
    assert not apply_paper_fill.calendar_covers_order_window(complete_window[:19], "20260920")
    assert not apply_paper_fill.calendar_covers_order_window(complete_window, "20260831")


def test_order_window_observation_is_append_only_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", tmp_path / "paper-account.json")
    account = {"cash_toman": 100_000_000, "holdings": [], "event_log": []}
    order = {"order_id": "isolated-test-order", "eligible_session_count_observed": 0}
    apply_paper_fill.record_order_observation(account, order, "20261023", 1, "20261023")
    apply_paper_fill.record_order_observation(account, order, "20261023", 1, "20261023")
    saved = json.loads((tmp_path / "paper-account.json").read_text(encoding="utf-8"))
    assert len(saved["event_log"]) == 1
    assert saved["paper_order"]["eligible_session_count_observed"] == 1
    assert saved["cash_toman"] == 100_000_000
    assert saved["holdings"] == []


@pytest.mark.parametrize("filled", [True, False])
def test_existing_fill_or_holding_blocks_duplicate_debit(tmp_path, monkeypatch, filled):
    rules = tmp_path / "rules.json"
    rules.write_text('{"locked": true}', encoding="utf-8")
    account_path = tmp_path / "paper-account.json"
    account = {
        "active_decision": {"execution_rules": {"sha256": apply_paper_fill.sha(rules)}},
        "paper_order": {"order_id": "existing-order", "fill_event_id": "existing-fill" if filled else None,
                        "status": "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE" if filled else "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"},
        "holdings": [{"symbol": "TEST", "shares": 1}] if not filled else [],
    }
    account_path.write_text(json.dumps(account), encoding="utf-8")
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", account_path)
    monkeypatch.setattr(apply_paper_fill, "RULES", rules)
    monkeypatch.setattr("sys.argv", ["apply_paper_fill.py", "--session-calendar-manifest", str(tmp_path / "unused.json"),
                                      "--evidence-manifest", str(tmp_path / "unused-evidence.json"), "--apply-fill"])
    with pytest.raises(SystemExit, match="ORDER_ALREADY_FILLED_OR_HOLDING_EXISTS"):
        apply_paper_fill.main()
    assert json.loads(account_path.read_text(encoding="utf-8")) == account


def test_cycle_lock_skips_live_owner_and_reclaims_dead_owner(tmp_path):
    lock = tmp_path / "cycle.lock"
    fd = acquire_cycle_lock(lock)
    assert fd is not None
    try:
        assert acquire_cycle_lock(lock) is None
    finally:
        os.close(fd)
        lock.unlink()
    lock.write_text("2147483647 2020-01-01T00:00:00+00:00", encoding="ascii")
    recovered = acquire_cycle_lock(lock)
    assert recovered is not None
    os.close(recovered)
    lock.unlink()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows byte-range lock is the scheduler runtime")
def test_second_process_cannot_write_during_account_commit(tmp_path):
    account = tmp_path / "paper-account.json"
    module_file = Path(apply_paper_fill.__file__).resolve()
    child = (
        "import importlib.util,sys,time; from pathlib import Path; "
        f"s=importlib.util.spec_from_file_location('paper_fill',r'{module_file}'); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "m.ACCOUNT=Path(sys.argv[1]); "
        "ctx=m.account_write_lock(); ctx.__enter__(); print('LOCK_HELD',flush=True); "
        "time.sleep(1.5); ctx.__exit__(None,None,None)"
    )
    proc = subprocess.Popen([sys.executable, "-c", child, str(account)], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout and proc.stdout.readline().strip() == "LOCK_HELD"
        with pytest.raises(SystemExit, match="PAPER_ACCOUNT_LOCKED"):
            with apply_paper_fill.account_write_lock():
                pass
    finally:
        proc.wait(timeout=5)
    assert proc.returncode == 0
