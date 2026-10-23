import subprocess
import sys
import json
import os
import copy
import datetime as dt
import gzip
import hashlib
import io
import queue
import threading
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pytest

from ranking_research.future_eval_v12_30 import apply_paper_fill
from ranking_research.future_eval_v12_30.paper_cycle import acquire_cycle_lock, is_weekly_stock_market_closure
from ranking_research import paper_account_store

SUBPROCESS_EVIDENCE = []


def test_account_state_replaced_atomically_in_one_file(tmp_path, monkeypatch):
    account = tmp_path / "paper-account.json"
    original = valid_account()
    account.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", account)
    updated = valid_account()
    updated["status"] = "test-replaced"
    apply_paper_fill.write_account_atomic(updated)
    assert json.loads(account.read_text(encoding="utf-8"))["status"] == "test-replaced"
    assert not account.with_suffix(".json.tmp").exists()


def valid_account(with_holding=True):
    holding = {"symbol": "TEST", "company_id": "fixture-1", "shares": 1,
        "purchase_price_rial": 1000, "purchase_price_toman": 100,
        "purchase_at_utc": "TEST_FIXTURE", "cost_basis_toman": 100, "fee_toman": 1,
        "last_price_rial": 1005, "last_price_date": "2026-10-23", "market_value_toman": 101,
        "unrealized_pnl_toman": 0, "price_status": "TEST_FIXTURE"}
    event = {"event_id": "fixture-init", "type": "TEST_FIXTURE", "at_utc": "TEST_FIXTURE",
        "reason": "TEST_FIXTURE", "details": {"nested": {"value": 1}}}
    return {"account_id": "TEST_FIXTURE", "cash_toman": 99899 if with_holding else 100000,
        "initial_capital_toman": 100000, "holdings": [holding] if with_holding else [],
        "event_log": [event], "accounting": {"holdings_value_toman": 101 if with_holding else 0,
            "total_value_toman": 100000, "profit_loss_toman": 0, "last_price_status": "TEST_FIXTURE"}}


def test_shared_store_rejects_invalid_account_without_replacing_old_bytes(tmp_path):
    path = tmp_path / "paper-account.json"
    original = (json.dumps(valid_account(), ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(original)
    invalid = valid_account()
    invalid["cash_toman"] = -1
    with pytest.raises(ValueError, match="PAPER_ACCOUNT_NEGATIVE_CASH"):
        paper_account_store.write_account_atomic(path, invalid)
    assert path.read_bytes() == original


def test_toman_rounding_is_explicit_half_up():
    assert paper_account_store.money("10.5") == 11
    assert paper_account_store.money("10.49") == 10
    assert paper_account_store.rial_to_toman(1005) == 101


@pytest.mark.parametrize("break_account, error", [
    (lambda a: a["accounting"].update(profit_loss_toman=123456789), "PAPER_ACCOUNT_PNL_MISMATCH"),
    (lambda a: a.update(cash_toman=-0.5), "PAPER_ACCOUNT_INVALID_CASH"),
    (lambda a: a.update(cash_toman=True), "PAPER_ACCOUNT_INVALID_CASH"),
    (lambda a: a.update(cash_toman="99899"), "PAPER_ACCOUNT_INVALID_CASH"),
    (lambda a: a.update(cash_toman=99899.5), "PAPER_ACCOUNT_INVALID_CASH"),
    (lambda a: a.update(cash_toman=float("nan")), "PAPER_ACCOUNT_INVALID_CASH"),
    (lambda a: a.update(cash_toman=float("inf")), "PAPER_ACCOUNT_INVALID_CASH"),
    (lambda a: a.pop("accounting"), "PAPER_ACCOUNT_REQUIRED_FIELD_MISSING"),
    (lambda a: a.pop("cash_toman"), "PAPER_ACCOUNT_REQUIRED_FIELD_MISSING"),
    (lambda a: a["accounting"].pop("profit_loss_toman"), "PAPER_ACCOUNT_ACCOUNTING_FIELD_MISSING:profit_loss_toman"),
    (lambda a: a["accounting"].update(total_value_toman=99999), "PAPER_ACCOUNT_NAV_MISMATCH"),
    (lambda a: a["holdings"][0].update(shares=1.5), "PAPER_ACCOUNT_INVALID_SHARE_COUNT"),
    (lambda a: a["holdings"][0].update(last_price_rial=float("inf")), "PAPER_ACCOUNT_INVALID_PRICE:last_price_rial"),
    (lambda a: a["holdings"][0].pop("market_value_toman"), "PAPER_ACCOUNT_INVALID_HOLDING_MONEY:market_value_toman"),
    (lambda a: a["event_log"][0].update(event_id=""), "PAPER_ACCOUNT_INVALID_EVENT_ID"),
])
def test_invalid_single_field_preserves_previous_account_bytes(tmp_path, break_account, error):
    path = tmp_path / "paper-account.json"
    original = (json.dumps(valid_account(), ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(original)
    invalid = valid_account()
    break_account(invalid)
    with pytest.raises(ValueError, match=error):
        paper_account_store.write_account_atomic(path, invalid)
    assert path.read_bytes() == original


@pytest.mark.parametrize("mutation, name", [
    (lambda account: account["event_log"][0]["details"]["nested"].update(value=999), "nested"),
    (lambda account: account["event_log"].pop(), "delete"),
    (lambda account: account["event_log"].reverse(), "reorder"),
])
def test_transaction_rejects_old_event_nested_mutation_delete_or_reorder(tmp_path, mutation, name):
    path = tmp_path / "paper-account.json"
    source = valid_account()
    if name == "reorder":
        source["event_log"].append({"event_id": "fixture-second", "type": "TEST_FIXTURE",
            "at_utc": "TEST_FIXTURE", "reason": "TEST_FIXTURE", "details": "second"})
    path.write_text(json.dumps(source), encoding="utf-8")
    before = path.read_bytes()
    def mutate(account):
        mutation(account)
    with pytest.raises(ValueError, match="PAPER_ACCOUNT_EVENT_HISTORY_REWRITE_FORBIDDEN"):
        paper_account_store.read_modify_write(path, mutate)
    assert path.read_bytes() == before


def test_transaction_allows_appending_a_valid_event(tmp_path):
    path = tmp_path / "paper-account.json"
    path.write_text(json.dumps(valid_account()), encoding="utf-8")
    def mutate(account):
        account["event_log"].append({"event_id": "fixture-next", "type": "TEST_FIXTURE",
            "at_utc": "TEST_FIXTURE", "reason": "TEST_FIXTURE", "details": "append"})
    paper_account_store.read_modify_write(path, mutate)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [e["event_id"] for e in saved["event_log"]] == ["fixture-init", "fixture-next"]


@pytest.mark.parametrize("mode", ["transaction", "direct"])
@pytest.mark.parametrize("replacement", [True, 1.0])
def test_event_history_rejects_json_scalar_type_rewrite(tmp_path, mode, replacement):
    path = tmp_path / "typed.json"
    original = valid_account()
    raw = (json.dumps(original, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="PAPER_ACCOUNT_EVENT_HISTORY_REWRITE_FORBIDDEN"):
        if mode == "transaction":
            paper_account_store.read_modify_write(
                path, lambda account: account["event_log"][0]["details"]["nested"].update(value=replacement))
        else:
            changed = copy.deepcopy(original)
            changed["event_log"][0]["details"]["nested"]["value"] = replacement
            paper_account_store.write_account_atomic(path, changed)
    assert path.read_bytes() == raw


def test_event_history_object_key_order_does_not_change_event(tmp_path):
    path = tmp_path / "key-order.json"
    account = valid_account()
    account["event_log"][0]["details"] = {"nested": {"value": 1, "other": "TEST_FIXTURE"}}
    path.write_text(json.dumps(account), encoding="utf-8")
    original_event = copy.deepcopy(account["event_log"][0])
    def reorder_keys(updated):
        event = updated["event_log"][0]
        event["details"]["nested"] = dict(reversed(list(event["details"]["nested"].items())))
        updated["event_log"][0] = dict(reversed(list(event.items())))
    paper_account_store.read_modify_write(path, reorder_keys)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["event_log"][0] == original_event


def test_mark_half_up_scenario_matches_independent_expected_numbers():
    from ranking_research.future_eval_v12_30.check_paper_account import apply_mark
    holding = valid_account()["holdings"][0]
    accounting = apply_mark(holding, 99899, 1005, "2026-10-23")
    # Independent arithmetic: 1,005 rials / 10 = 100.5 tomans -> 101;
    # cash 99,899 + value 101 = NAV 100,000; 100,000 - capital = P&L 0.
    assert holding["market_value_toman"] == 101
    assert accounting["total_value_toman"] == 100000
    assert accounting["profit_loss_toman"] == 0
    account = valid_account()
    account["holdings"][0] = holding
    account["accounting"] = accounting
    paper_account_store.validate_account(account)


def test_small_buy_independent_accounting_fixture_remains_consistent():
    # Independent Decimal arithmetic for 1,234 rial = 123.4 toman per share.
    capital, price, fee_rate = 100000, Decimal("123.4"), Decimal("0.005")
    shares = int(Decimal(capital) / (price * (Decimal(1) + fee_rate)))
    gross = int((price * shares).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    fee = int((Decimal(gross) * fee_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    cash = capital - gross - fee
    nav = cash + gross
    assert (shares, gross, fee, cash, nav, nav - capital) == (806, 99460, 497, 43, 99503, -497)


def _fill_entrypoint_fixture(root, price=1234, sessions_after=1, has_bar=True):
    root.mkdir(parents=True, exist_ok=True)
    def put(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    def raw(key, value):
        data = json.dumps(value, separators=(",", ":")).encode()
        path = root / (key + ".gz")
        path.write_bytes(gzip.compress(data))
        return {"key": key, "raw_path": path.name, "raw_sha256": hashlib.sha256(data).hexdigest(),
                "retrieved_at_utc": "2026-10-26T13:00:00+00:00"}
    rules, account_path = root / "rules.json", root / "account.json"
    put(rules, {"rule_id": "paper-execution-rules/1.2.0-TEST_FIXTURE"})
    account = {"label": "TEST_FIXTURE", "account_id": "TEST_FIXTURE", "initial_capital_toman": 100000,
        "cash_toman": 100000, "holdings": [], "event_log": [],
        "accounting": {"holdings_value_toman": 0, "total_value_toman": 100000, "profit_loss_toman": 0},
        "active_decision": {"decision_id": "fixture-decision", "decided_at_utc": "2026-10-22T10:00:00+00:00",
            "decision_local_date": "2026-10-22", "execution_rules": {"sha256": hashlib.sha256(rules.read_bytes()).hexdigest()}},
        "paper_order": {"order_id": "fixture-order", "decision_id": "fixture-decision", "company_id": "fixture-company",
            "symbol": "TEST", "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "expires_after_official_sessions": 3,
            "eligible_session_count_observed": 0, "fill_event_id": None}}
    put(account_path, account)
    end_day = 22 + sessions_after
    session_rows = [{"DEven": f"202610{d:02d}", "HEven": 120000, "NSCEnd": "1"}
                    for d in range(end_day - 19, end_day + 1)]
    calraw = raw("calendar", {"label": "TEST_FIXTURE", "Data": session_rows})
    calendar = root / "calendar.json"
    put(calendar, {**calraw, "source": "TSETMC documented API MarketInfo/NSCStart", "sessions": session_rows,
                   "label": "TEST_FIXTURE"})
    daily = raw("daily", {"closingPriceDaily": ([{"dEven": "20261023", "insCode": "123", "pClosing": price,
                                                       "qTotTran5J": 10000}] if has_bar else [])})
    daily["key"] = "candidate_daily"
    daily["url"] = "https://example.invalid/123/0"
    shares = raw("shares", {"instrumentShareChange": []}); shares["key"] = "candidate_share_changes"
    last = raw("last", {"label": "TEST_FIXTURE"}); last.update(key="last_possible_session", reported_last_possible_session=f"202610{end_day:02d}")
    evidence = root / "evidence.json"
    put(evidence, {"label": "TEST_FIXTURE", "ins_code": "123", "candidate": {"company_id": "fixture-company"},
                   "sources": [daily, shares, last]})
    return account_path, {"ROOT": root, "ACCOUNT": account_path, "RULES": rules}, [
        "--session-calendar-manifest", str(calendar), "--evidence-manifest", str(evidence), "--apply-fill"]


@pytest.mark.parametrize("name,sessions_after,has_bar,status", [
    ("eligible", 1, True, "FILL_ELIGIBLE_PREVIEW_ONLY"),
    ("no_bar", 1, False, "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"),
    ("expired", 3, False, "EXPIRED_NO_FILL"),
    ("late", 3, True, "LATE_FILL_TIMING_AMBIGUOUS"),
])
def test_four_preview_outcomes_keep_account_bytes_and_state(tmp_path, name, sessions_after, has_bar, status):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / name, sessions_after=sessions_after, has_bar=has_bar)
    argv = argv[:-1]
    before = path.read_bytes()
    result = _invoke_fill(attrs, argv)
    assert result["status"] == status and result["fill_applied"] is False
    assert path.read_bytes() == before
    account = json.loads(before)
    assert account["cash_toman"] == 100000 and account["holdings"] == []
    assert account["paper_order"]["status"] == "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"
    assert account["paper_order"]["eligible_session_count_observed"] == 0
    assert account["event_log"] == []


@pytest.mark.parametrize("name,sessions_after,has_bar,status", [
    ("observe_missing", 1, False, "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"),
    ("observe_expiry", 3, False, "EXPIRED_NO_FILL"),
    ("observe_late", 3, True, "LATE_FILL_TIMING_AMBIGUOUS"),
])
def test_explicit_observation_commits_once_and_only_through_shared_writer(tmp_path, name, sessions_after, has_bar, status):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / name, sessions_after=sessions_after, has_bar=has_bar)
    args = argv[:-1] + ["--observe-order-state"]
    output = _invoke_fill(attrs, args)
    assert output["status"] == status and output["fill_applied"] is False
    once = path.read_bytes()
    state = json.loads(once)
    assert len(state["event_log"]) == 1 and state["cash_toman"] == 100000 and not state["holdings"]
    _invoke_fill(attrs, args)
    twice = json.loads(path.read_text(encoding="utf-8"))
    assert len(twice["event_log"]) == 1
    assert twice["event_log"][0]["event_id"] == state["event_log"][0]["event_id"]


def _invoke_fill(attrs, argv):
    output = io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        for key, value in attrs.items():
            patch.setattr(apply_paper_fill, key, value)
        patch.setattr("sys.argv", ["apply_paper_fill.py", *argv])
        with __import__("contextlib").redirect_stdout(output):
            apply_paper_fill.main()
    return json.loads(output.getvalue())


def _readline_timeout(stream, timeout=10):
    result = queue.Queue(maxsize=1)
    threading.Thread(target=lambda: result.put(stream.readline()), daemon=True).start()
    return result.get(timeout=timeout).strip()


def test_fill_entrypoint_replay_and_source_conflict_are_idempotent(tmp_path):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / "fill")
    first = _invoke_fill(attrs, argv)
    original = path.read_bytes()
    before = json.loads(original)
    assert first["status"] == "FILL_APPLIED"
    assert (before["cash_toman"], before["holdings"][0]["shares"], len(before["event_log"])) == (43, 806, 1)
    for _ in range(2):
        replay = _invoke_fill(attrs, argv)
        assert replay["status"] == "FILL_ALREADY_APPLIED" and replay["fill_applied"] is False
        assert replay["fill_event_id"] == before["paper_order"]["fill_event_id"]
        assert path.read_bytes() == original
    # Revise price raw and its declared hash, so this is a valid source revision.
    daily = tmp_path / "fill" / "daily.gz"
    content = json.dumps({"closingPriceDaily": [{"dEven": "20261023", "insCode": "123", "pClosing": 2345,
                                                    "qTotTran5J": 10000}]}, separators=(",", ":")).encode()
    daily.write_bytes(gzip.compress(content))
    manifest = tmp_path / "fill" / "evidence.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    for source in doc["sources"]:
        if source["key"] == "candidate_daily":
            source["raw_sha256"] = hashlib.sha256(content).hexdigest()
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SystemExit, match="FILL_REPLAY_CONFLICT"):
        _invoke_fill(attrs, argv)
    assert path.read_bytes() == original

    calendar_case = tmp_path / "calendar-conflict"
    calendar_account, calendar_attrs, calendar_argv = _fill_entrypoint_fixture(calendar_case)
    _invoke_fill(calendar_attrs, calendar_argv)
    calendar_filled = calendar_account.read_bytes()
    calendar_path = calendar_case / "calendar.json"
    caldoc = json.loads(calendar_path.read_text(encoding="utf-8"))
    raw_path = calendar_case / caldoc["raw_path"]
    rawdoc = json.loads(gzip.decompress(raw_path.read_bytes()))
    rawdoc["Data"][0]["HEven"] += 1
    rawbytes = json.dumps(rawdoc, separators=(",", ":")).encode()
    raw_path.write_bytes(gzip.compress(rawbytes))
    caldoc["raw_sha256"] = hashlib.sha256(rawbytes).hexdigest()
    caldoc["sessions"] = rawdoc["Data"]
    calendar_path.write_text(json.dumps(caldoc), encoding="utf-8")
    with pytest.raises(SystemExit, match="FILL_REPLAY_CONFLICT"):
        _invoke_fill(calendar_attrs, calendar_argv)
    assert calendar_account.read_bytes() == calendar_filled


def test_fill_replay_revalidates_raw_and_succeeds_after_mark(tmp_path):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / "fill")
    _invoke_fill(attrs, argv)
    # A mark changes the current account valuation but must not alter the fill receipt basis.
    account = json.loads(path.read_text(encoding="utf-8"))
    holding = account["holdings"][0]
    from ranking_research.future_eval_v12_30.check_paper_account import apply_mark
    account["accounting"] = apply_mark(holding, account["cash_toman"], 1235, "2026-10-24")
    paper_account_store.write_account_atomic(path, account)
    marked = path.read_bytes()
    assert _invoke_fill(attrs, argv)["status"] == "FILL_ALREADY_APPLIED"
    assert path.read_bytes() == marked
    raw = tmp_path / "fill" / "daily.gz"
    raw.write_bytes(gzip.compress(b'{"closingPriceDaily":[]}'))
    with pytest.raises(SystemExit, match="OFFICIAL_RAW_HASH_MISMATCH:candidate_daily"):
        _invoke_fill(attrs, argv)
    assert path.read_bytes() == marked


def test_fill_replay_rejects_inconsistent_order_or_missing_fill_event(tmp_path):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / "fill")
    _invoke_fill(attrs, argv)
    original = path.read_bytes()
    account = json.loads(original)
    account["event_log"].clear()
    path.write_text(json.dumps(account), encoding="utf-8")
    broken = path.read_bytes()
    with pytest.raises(SystemExit, match="FILL_REPLAY_STATE_CONFLICT"):
        _invoke_fill(attrs, argv)
    assert path.read_bytes() == broken
    account["event_log"] = json.loads(original)["event_log"]
    account["paper_order"]["fill_event_id"] = "wrong-event-id"
    path.write_text(json.dumps(account), encoding="utf-8")
    broken = path.read_bytes()
    with pytest.raises(SystemExit, match="FILL_REPLAY_STATE_CONFLICT"):
        _invoke_fill(attrs, argv)
    assert path.read_bytes() == broken


def test_replay_ignores_manifest_key_order_and_manifest_path(tmp_path):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / "fill")
    _invoke_fill(attrs, argv)
    original = path.read_bytes()
    evidence_path = Path(argv[argv.index("--evidence-manifest") + 1])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    reordered = {key: evidence[key] for key in reversed(list(evidence))}
    reordered["sources"] = list(reversed(reordered["sources"]))
    moved = tmp_path / "fill" / "moved" / "renamed-manifest.json"
    moved.parent.mkdir()
    moved.write_text(json.dumps(reordered, ensure_ascii=False), encoding="utf-8")
    replay_argv = list(argv)
    replay_argv[replay_argv.index("--evidence-manifest") + 1] = str(moved)
    assert _invoke_fill(attrs, replay_argv)["status"] == "FILL_ALREADY_APPLIED"
    assert path.read_bytes() == original


@pytest.mark.parametrize("cut,expect_new", [("write", False), ("pre_replace", False), ("post_replace", True)])
def test_subprocess_crash_keeps_old_or_new_valid_account_and_recovery_works(tmp_path, cut, expect_new):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"crash-{cut}.json"
    original = valid_account()
    path.write_text(json.dumps(original), encoding="utf-8")
    old_bytes = path.read_bytes()
    child = r'''import json,os,sys
from pathlib import Path
from ranking_research import paper_account_store as s
p=Path(sys.argv[1]); cut=sys.argv[2]
real_open=Path.open; real_replace=os.replace
if cut == "write":
 class Proxy:
  def __init__(self, f): self.f=f
  def __enter__(self): return self
  def __exit__(self,*a): return self.f.__exit__(*a)
  def write(self, value): self.f.write(value[:max(1,len(value)//2)]); self.f.flush(); os._exit(71)
  def __getattr__(self,n): return getattr(self.f,n)
 def intercepted(self,*a,**k):
  f=real_open(self,*a,**k)
  return Proxy(f) if str(self).endswith('.tmp') else f
 Path.open=intercepted
elif cut == "pre_replace":
 os.replace=lambda *a,**k: os._exit(72)
else:
 def after(*a,**k): real_replace(*a,**k); os._exit(73)
 os.replace=after
a=json.loads(p.read_text()); a['status']='new'
a['event_log'].append({'event_id':'crash-new','type':'TEST_FIXTURE','at_utc':'TEST_FIXTURE','reason':'TEST_FIXTURE','details':{'value':2}})
s.write_account_atomic(p,a)
'''
    result = subprocess.run([sys.executable, "-c", child, str(path), cut], cwd=Path.cwd(),
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == {"write": 71, "pre_replace": 72, "post_replace": 73}[cut]
    saved_bytes = path.read_bytes()
    saved = json.loads(saved_bytes)
    paper_account_store.validate_account(saved)
    assert (saved_bytes != old_bytes) is expect_new
    if expect_new:
        assert len(saved["event_log"]) == 2 and saved["status"] == "new"
    else:
        assert saved_bytes == old_bytes
    SUBPROCESS_EVIDENCE.append({"case": f"atomic_crash_{cut}", "exit_code": result.returncode,
        "cut_point": cut, "old_sha256": hashlib.sha256(old_bytes).hexdigest(),
        "post_crash_sha256": hashlib.sha256(saved_bytes).hexdigest(), "cash_toman": saved["cash_toman"],
        "holding_count": len(saved["holdings"]), "event_count": len(saved["event_log"]),
        "json_valid": True, "recoverable": True})
    # Fresh process-independent transaction must replace any abandoned temp and append.
    paper_account_store.read_modify_write(path, lambda a: a.update(recovered=True))
    recovered = json.loads(path.read_text(encoding="utf-8"))
    assert recovered["recovered"] is True


def test_two_subprocess_read_modify_write_transactions_do_not_lose_updates(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "concurrent.json"
    path.write_text(json.dumps(valid_account()), encoding="utf-8")
    child1 = r'''import json,sys
from pathlib import Path
from ranking_research import paper_account_store as s
p=Path(sys.argv[1])
with s.account_write_lock(p):
 a=json.loads(p.read_text()); print('LOCK_HELD',flush=True)
 if sys.stdin.readline().strip()!='GO': raise SystemExit(9)
 a['event_log'].append({'event_id':'process-one','type':'TEST_FIXTURE','at_utc':'TEST_FIXTURE','reason':'TEST_FIXTURE','details':1})
 s.write_account_atomic(p,a)
'''
    child2 = r'''import json,sys
from pathlib import Path
from ranking_research import paper_account_store as s
p=Path(sys.argv[1])
try:
 s.read_modify_write(p,lambda a:a['event_log'].append({'event_id':'process-two','type':'TEST_FIXTURE','at_utc':'TEST_FIXTURE','reason':'TEST_FIXTURE','details':2}))
 print('COMMITTED')
except SystemExit as e: print(str(e))
'''
    first = subprocess.Popen([sys.executable, "-c", child1, str(path)], cwd=Path.cwd(), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert first.stdout and _readline_timeout(first.stdout) == "LOCK_HELD"
        second = subprocess.run([sys.executable, "-c", child2, str(path)], cwd=Path.cwd(),
                                capture_output=True, text=True, timeout=15)
        assert second.returncode == 0
        if "PAPER_ACCOUNT_LOCKED" in second.stdout:
            assert "no account event was written" in second.stdout
        else:
            assert "COMMITTED" in second.stdout
        assert first.stdin
        first.stdin.write("GO\n"); first.stdin.flush()
        assert first.wait(timeout=15) == 0
        if "PAPER_ACCOUNT_LOCKED" in second.stdout:
            retry = subprocess.run([sys.executable, "-c", child2, str(path)], cwd=Path.cwd(),
                                   capture_output=True, text=True, timeout=15)
            assert "COMMITTED" in retry.stdout and retry.returncode == 0
            retry_output, retry_code = retry.stdout.strip(), retry.returncode
        else:
            retry_output, retry_code = None, None
        SUBPROCESS_EVIDENCE.append({"case": "concurrent_rmw", "first_exit_code": first.returncode,
            "second_exit_code": second.returncode, "second_result": second.stdout.strip(),
            "retry_exit_code": retry_code, "retry_result": retry_output,
            "final_event_ids": [e["event_id"] for e in json.loads(path.read_text(encoding="utf-8"))["event_log"]]})
    finally:
        if first.poll() is None:
            first.kill(); first.wait(timeout=5)
    saved = json.loads(path.read_text(encoding="utf-8"))
    paper_account_store.validate_account(saved)
    assert {e["event_id"] for e in saved["event_log"]} >= {"process-one", "process-two"}


def test_subprocess_fill_crash_after_replace_replays_without_second_debit(tmp_path):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / "fill-crash")
    child = r'''import os,sys
from pathlib import Path
from ranking_research.future_eval_v12_30 import apply_paper_fill as m
m.ROOT=Path(sys.argv[1]); m.ACCOUNT=Path(sys.argv[2]); m.RULES=Path(sys.argv[3])
args=sys.argv[4:]; sys.argv=['apply_paper_fill.py',*args]
real=os.replace
def die_after_replace(*a,**k): real(*a,**k); os._exit(74)
os.replace=die_after_replace
m.main()
'''
    result = subprocess.run([sys.executable, "-c", child, str(attrs["ROOT"]), str(path), str(attrs["RULES"]),
                             *argv], cwd=Path.cwd(), capture_output=True, text=True, timeout=15)
    assert result.returncode == 74
    saved_bytes = path.read_bytes()
    saved = json.loads(saved_bytes)
    paper_account_store.validate_account(saved)
    assert saved["cash_toman"] == 43 and len(saved["event_log"]) == 1
    replay = _invoke_fill(attrs, argv)
    assert replay["status"] == "FILL_ALREADY_APPLIED" and replay["fill_applied"] is False
    assert path.read_bytes() == saved_bytes
    SUBPROCESS_EVIDENCE.append({"case": "fill_crash_post_replace", "child_exit_code": result.returncode,
        "cut_point": "after os.replace before CLI success", "recovery_status": replay["status"],
        "before_replay_sha256": hashlib.sha256(saved_bytes).hexdigest(),
        "after_replay_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "cash_toman": saved["cash_toman"], "holding_count": len(saved["holdings"]),
        "event_count": len(saved["event_log"])})


def test_two_subprocess_fill_attempts_produce_one_fill_and_one_replay(tmp_path):
    path, attrs, argv = _fill_entrypoint_fixture(tmp_path / "fill-concurrent")
    child = r'''import sys
from pathlib import Path
from ranking_research.future_eval_v12_30 import apply_paper_fill as m
m.ROOT=Path(sys.argv[1]); m.ACCOUNT=Path(sys.argv[2]); m.RULES=Path(sys.argv[3]); args=sys.argv[4:]
with m.account_write_lock():
 print('LOCK_HELD',flush=True)
 if sys.stdin.readline().strip()!='GO': raise SystemExit(9)
 sys.argv=['apply_paper_fill.py',*args]; m.main()
'''
    child2 = r'''import sys
from pathlib import Path
from ranking_research.future_eval_v12_30 import apply_paper_fill as m
m.ROOT=Path(sys.argv[1]); m.ACCOUNT=Path(sys.argv[2]); m.RULES=Path(sys.argv[3]); sys.argv=['apply_paper_fill.py',*sys.argv[4:]]
m.main()
'''
    first = subprocess.Popen([sys.executable, "-c", child, str(attrs["ROOT"]), str(path), str(attrs["RULES"]),
                              *argv], cwd=Path.cwd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert first.stdout and _readline_timeout(first.stdout) == "LOCK_HELD"
        retry_needed = False
        second = subprocess.run([sys.executable, "-c", child2,
                                 str(attrs["ROOT"]), str(path), str(attrs["RULES"]), *argv], cwd=Path.cwd(),
                                capture_output=True, text=True, timeout=15)
        if second.returncode != 0:
            retry_needed = "PAPER_ACCOUNT_LOCKED" in (second.stdout + second.stderr)
            assert retry_needed
        assert first.stdin
        first.stdin.write("GO\n"); first.stdin.flush()
        assert first.wait(timeout=15) == 0
        if retry_needed:
            second = subprocess.run([sys.executable, "-c", child2,
                                     str(attrs["ROOT"]), str(path), str(attrs["RULES"]), *argv], cwd=Path.cwd(),
                                    capture_output=True, text=True, timeout=15)
            assert second.returncode == 0
        assert "FILL_ALREADY_APPLIED" in second.stdout
    finally:
        if first.poll() is None:
            first.kill(); first.wait(timeout=5)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["cash_toman"] == 43 and len(saved["event_log"]) == 1
    SUBPROCESS_EVIDENCE.append({"case": "concurrent_fill", "first_exit_code": first.returncode,
        "second_exit_code": second.returncode, "second_result": second.stdout.strip(),
        "lock_retry": retry_needed, "cash_toman": saved["cash_toman"],
        "holding_count": len(saved["holdings"]), "event_count": len(saved["event_log"])})


def test_decision_entrypoint_commits_append_only_to_temporary_account(tmp_path, monkeypatch):
    from ranking_research.future_eval_v12_30 import register_paper_decision as register
    candidate = {"symbol": "TEST", "company_id": "fx1", "rank": 1, "score": 99.0, "coverage": 1.0}
    account = valid_account(with_holding=False)
    account["ranking"] = {"dataset_id": "TEST_FIXTURE", "artifact_sha256": "a" * 64,
        "evaluation_date": "2026-10-22", "top_candidate": candidate}
    account["official_future_evaluation_ledger_linked"] = False
    account_path = tmp_path / "paper-account.json"
    ranking_path = tmp_path / "ranking.json"
    rules_path = tmp_path / "rules.json"
    evidence_path = tmp_path / "evidence.json"
    ranking = {"artifact_sha256": "a" * 64, "artifact_id": "rank-fx", "dataset_id": "TEST_FIXTURE",
        "evaluation_date": "2026-10-22", "status": "TEST_FIXTURE", "scored_count": {"P1": 1},
        "rows": [{"company_id": "fx1", "methods": {"P1": {"rank": 1}}}]}
    rules = {"rule_id": "paper-execution-rules/1.2.0-TEST_FIXTURE"}
    evidence = {"candidate": {"symbol": "TEST", "company_id": "fx1"}}
    account_path.write_text(json.dumps(account), encoding="utf-8")
    original_bytes = account_path.read_bytes()
    ranking_path.write_text(json.dumps(ranking), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(register, "ROOT", tmp_path)
    monkeypatch.setattr(register, "ACCOUNT", account_path)
    monkeypatch.setattr(register, "RANKING", ranking_path)
    monkeypatch.setattr(register, "RULES", rules_path)
    monkeypatch.setattr(register, "EVIDENCE", evidence_path)
    before_events = copy.deepcopy(account["event_log"])
    register.main()
    saved = json.loads(account_path.read_text(encoding="utf-8"))
    assert saved["cash_toman"] == 100000
    assert saved["event_log"][:len(before_events)] == before_events
    assert [event["type"] for event in saved["event_log"][-2:]] == [
        "PAPER_BUY_DECISION_RECORDED", "PAPER_ORDER_PENDING"]
    paper_account_store.validate_account(saved)


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


def test_thursday_and_friday_are_weekly_closure_but_saturday_is_not_proven_open():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Asia/Tehran")
    assert is_weekly_stock_market_closure(dt.datetime(2026, 10, 22, 12, tzinfo=zone))
    assert is_weekly_stock_market_closure(dt.datetime(2026, 10, 23, 12, tzinfo=zone))
    assert not is_weekly_stock_market_closure(dt.datetime(2026, 10, 24, 12, tzinfo=zone))


def test_order_observation_does_not_require_a_new_decision_date(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", tmp_path / "paper-account.json")
    account = valid_account(with_holding=False)
    order = {"order_id": "existing-v12-38", "eligible_session_count_observed": 0}
    apply_paper_fill.record_order_observation(account, order, "20261024", 1, "20261024")
    assert account["paper_order"]["eligible_session_count_observed"] == 1
    assert account["event_log"][-1]["type"] == "PAPER_ORDER_SESSION_EVIDENCE_OBSERVED"
    assert account["cash_toman"] == 100000
    assert not account["holdings"]


def test_order_window_observation_is_append_only_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", tmp_path / "paper-account.json")
    account = valid_account(with_holding=False)
    order = {"order_id": "isolated-test-order", "eligible_session_count_observed": 0}
    apply_paper_fill.record_order_observation(account, order, "20261023", 1, "20261023")
    apply_paper_fill.record_order_observation(account, order, "20261023", 1, "20261023")
    saved = json.loads((tmp_path / "paper-account.json").read_text(encoding="utf-8"))
    assert len(saved["event_log"]) == 2
    assert saved["event_log"][-1]["type"] == "PAPER_ORDER_SESSION_EVIDENCE_OBSERVED"
    assert saved["paper_order"]["eligible_session_count_observed"] == 1
    assert saved["cash_toman"] == 100000
    assert saved["holdings"] == []


@pytest.mark.parametrize("filled", [True, False])
def test_existing_fill_or_holding_blocks_duplicate_debit(tmp_path, monkeypatch, filled):
    rules = tmp_path / "rules.json"
    rules.write_text('{"locked": true}', encoding="utf-8")
    account_path = tmp_path / "paper-account.json"
    account = valid_account(with_holding=not filled)
    account["active_decision"] = {"decision_id": "fixture-decision", "execution_rules": {"sha256": apply_paper_fill.sha(rules)}}
    account["paper_order"] = {"order_id": "existing-order", "decision_id": "fixture-decision",
        "fill_event_id": "existing-fill" if filled else None,
        "status": "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE" if filled else "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"}
    account_path.write_text(json.dumps(account), encoding="utf-8")
    original_bytes = account_path.read_bytes()
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", account_path)
    monkeypatch.setattr(apply_paper_fill, "RULES", rules)
    monkeypatch.setattr("sys.argv", ["apply_paper_fill.py", "--session-calendar-manifest", str(tmp_path / "unused.json"),
                                      "--evidence-manifest", str(tmp_path / "unused-evidence.json"), "--apply-fill"])
    with pytest.raises(SystemExit):
        apply_paper_fill.main()
    assert account_path.read_bytes() == original_bytes


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
def test_second_process_cannot_write_during_account_commit(tmp_path, monkeypatch):
    account = tmp_path / "paper-account.json"
    account.write_text(json.dumps(valid_account()), encoding="utf-8")
    monkeypatch.setattr(apply_paper_fill, "ACCOUNT", account)
    module_file = Path(apply_paper_fill.__file__).resolve()
    child = (
        "import importlib.util,sys; from pathlib import Path; "
        f"s=importlib.util.spec_from_file_location('paper_fill',r'{module_file}'); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "m.ACCOUNT=Path(sys.argv[1]); "
        "ctx=m.account_write_lock(); ctx.__enter__(); print('LOCK_HELD',flush=True); "
        "assert sys.stdin.readline().strip()=='GO'; ctx.__exit__(None,None,None)"
    )
    proc = subprocess.Popen([sys.executable, "-c", child, str(account)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout and _readline_timeout(proc.stdout) == "LOCK_HELD"
        with pytest.raises(SystemExit, match="PAPER_ACCOUNT_LOCKED"):
            with apply_paper_fill.account_write_lock():
                pass
        assert proc.stdin
        proc.stdin.write("GO\n"); proc.stdin.flush()
    finally:
        if proc.poll() is None:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
    assert proc.returncode == 0
