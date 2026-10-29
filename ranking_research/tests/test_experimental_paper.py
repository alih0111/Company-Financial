"""Real paper entrypoints; artificial isolated market, never a live request."""
import copy
import datetime as dt
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ranking_research import paper_account_store as store
from ranking_research.tests import test_paper_calendar_interface as f
from ranking_research.tests import test_paper_calendar_tf02a_regressions as a
from ranking_research.future_eval_v12_30 import experimental_paper as exp


def save(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def setup(tmp_path):
    account, rules, root = f._public_account_fixture(tmp_path / "account")
    doc = json.loads(account.read_text(encoding="utf-8"))
    rule_doc = json.loads(rules.read_text(encoding="utf-8"))
    binding = {"id": f.POLICY["policy_id"], "sha256": f.POLICY_SHA, "provider": f.POLICY["provider"], "version": f.POLICY["version"]}
    rule_doc["calendar_policy"] = binding
    save(rules, rule_doc)
    doc["calendar_policy"] = binding
    doc["active_decision"]["calendar_policy"] = binding
    doc["active_decision"]["execution_rules"]["sha256"] = exp.sha(rules)
    doc["paper_order"]["calendar_policy"] = binding
    doc.update(profile=exp.PROFILE, real_order_submitted=False, realized_pnl_toman=0,
               ranking={"top_candidate": {"symbol": "TEST", "company_id": "fixture-company"}},
               official_future_evaluation_ledger_linked=False)
    save(account, doc)
    ev = f._public_evidence(root)
    evidence = json.loads(ev.read_text(encoding="utf-8"))
    for source in evidence["sources"]:
        source["raw_path"] = str(root / source["raw_path"])
    save(ev, evidence)
    cal, digest, _ = a._short_package(tmp_path / "calendar")
    return account, rules, root, ev, cal, digest


def cli(script, args):
    p = subprocess.run([sys.executable, "-B", "-X", "utf8", str(exp.SCRIPTS / script), *map(str, args)],
                       capture_output=True, encoding="utf-8", cwd=exp.ROOT, timeout=40)
    return p


def fill(account, rules, evidence, cal, *, apply=True, clock=None):
    args = ["--account", account, "--rules", rules, "--evidence-manifest", evidence,
            "--session-calendar-manifest", cal, "--calendar-manifest-sha256", exp.sha(cal),
            "--calendar-provider", "public", "--reference-now-utc", (clock or f.NOW + dt.timedelta(minutes=5)).isoformat()]
    if apply:
        args.append("--apply-fill")
    result = cli("apply_paper_fill.py", args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def sell_setup(tmp_path):
    account, rules, root, ev, cal, _ = setup(tmp_path)
    assert fill(account, rules, ev, cal)["status"] == "FILL_APPLIED"
    ranking = root / "ranking.json"
    save(ranking, {"artifact_sha256": "a" * 64, "artifact_id": "fixture", "dataset_id": "fixture", "evaluation_date": "2026-09-05",
                   "status": "TEST_ONLY", "scored_count": {"P1": 1}, "universe_count": 1, "rows": []})
    basis = root / "basis.json"
    save(basis, {"candidate": {"symbol": "TEST", "company_id": "fixture-company"}})
    result = cli("register_paper_decision.py", ["--account", account, "--rules", rules, "--ranking", ranking,
        "--evidence", basis, "--calendar-provider", "public", "--side", "SELL", "--fixture", "--fixture-clock", "2026-09-05T17:00:00+00:00"])
    assert result.returncode == 0, result.stderr
    sellcal, _, _ = f.public_package(tmp_path / "sell-calendar", primary=["20260905", "20260906"],
        secondary=["20260905", "20260906"], watermark="20260906;20260906", window_start="20260905")
    # Distinct immutable buy/sell evidence, shared real parser.
    sellroot = tmp_path / "sell-evidence"
    sellroot.mkdir()
    sellev = f._public_evidence(sellroot, bar_day="20260906")
    d = json.loads(sellev.read_text(encoding="utf-8"))
    for source in d["sources"]:
        source["raw_path"] = str(sellroot / source["raw_path"])
    save(sellev, d)
    return account, rules, ev, cal, sellev, sellcal


def test_real_cli_buy_sell_accounting_preview_and_next_day_replay(tmp_path):
    account, rules, buy_ev, buy_cal, ev, cal = sell_setup(tmp_path)
    before = account.read_bytes()
    p = fill(account, rules, ev, cal, apply=False)
    assert p["status"] == "FILL_ELIGIBLE_PREVIEW_ONLY" and account.read_bytes() == before
    assert fill(account, rules, ev, cal)["status"] == "FILL_APPLIED"
    sold = json.loads(account.read_text(encoding="utf-8"))
    # Independent arithmetic: 806*123.4=99460.4 -> 99460, fee 497 each side.
    assert sold["cash_toman"] == 99006
    assert sold["holdings"] == [] and sold["realized_pnl_toman"] == -994
    assert sold["accounting"]["profit_loss_toman"] == -994
    assert sold["order_history"][0]["order"]["fill_receipt"]["shares"] == 806
    assert len([e for e in sold["event_log"] if e["type"] == "PAPER_SELL_DAILY_CLOSE_LIMITED_QUEUE"]) == 1
    final_bytes = account.read_bytes()
    assert fill(account, rules, ev, cal, clock=f.NOW + dt.timedelta(days=1))["status"] == "FILL_ALREADY_APPLIED"
    assert account.read_bytes() == final_bytes
    store.validate_account(sold)


def test_sell_rejects_raw_corruption_without_mutation(tmp_path):
    account, rules, _, _, ev, cal = sell_setup(tmp_path)
    before = account.read_bytes()
    raw = Path(json.loads(ev.read_text(encoding="utf-8"))["sources"][0]["raw_path"])
    raw.write_bytes(gzip.compress(b'{"closingPriceDaily":[]}'))
    result = cli("apply_paper_fill.py", ["--account", account, "--rules", rules,
        "--evidence-manifest", ev, "--session-calendar-manifest", cal, "--calendar-manifest-sha256", exp.sha(cal),
        "--calendar-provider", "public", "--reference-now-utc", (f.NOW + dt.timedelta(minutes=5)).isoformat(), "--apply-fill"])
    assert result.returncode != 0 and "HASH_MISMATCH" in result.stderr
    assert account.read_bytes() == before


def test_next_buy_preserves_realized_loss_and_order_history(tmp_path):
    account, rules, _, _, ev, cal = sell_setup(tmp_path)
    fill(account, rules, ev, cal)
    root = account.parent
    ranking = json.loads((root / "ranking.json").read_text(encoding="utf-8"))
    ranking["rows"] = [{"company_id": "fixture-company", "symbol": "TEST", "methods": {"P1": {"rank": 1, "score": 55, "financial_factor_coverage": 1}}}]
    save(root / "ranking.json", ranking)
    registered = cli("register_paper_decision.py", ["--account", account, "--rules", rules, "--ranking", root / "ranking.json",
        "--evidence", root / "basis.json", "--calendar-provider", "public", "--fixture", "--fixture-clock", "2026-09-06T17:00:00+00:00"])
    assert registered.returncode == 0, registered.stderr
    cal2, _, _ = f.public_package(tmp_path / "next-calendar", primary=["20260906", "20260907"],
        secondary=["20260906", "20260907"], watermark="20260907;20260907", window_start="20260906")
    evroot = tmp_path / "next-evidence"; evroot.mkdir()
    ev2 = f._public_evidence(evroot, bar_day="20260907")
    e = json.loads(ev2.read_text(encoding="utf-8"))
    for source in e["sources"]:
        source["raw_path"] = str(evroot / source["raw_path"])
    save(ev2, e)
    fill(account, rules, ev2, cal2)
    result = json.loads(account.read_text(encoding="utf-8"))
    assert len(result["order_history"]) == 2
    assert result["holdings"][0]["shares"] == 798
    assert result["cash_toman"] == 41 and result["realized_pnl_toman"] == -994
    assert result["accounting"]["profit_loss_toman"] == -1486
    assert result["accounting"]["total_value_toman"] == 98514
    before = account.read_bytes()
    fill(account, rules, ev2, cal2, clock=f.NOW + dt.timedelta(days=1))
    assert account.read_bytes() == before


def test_failed_bootstrap_does_not_leave_an_unusable_account(tmp_path, monkeypatch):
    home, run = tmp_path / "home", tmp_path / "run"
    home.mkdir(); run.mkdir()
    monkeypatch.setattr(exp, "run", lambda *args: (_ for _ in ()).throw(ValueError("simulated child failure")))
    with pytest.raises(ValueError, match="simulated child failure"):
        exp.initialize(home, exp.DEFAULT_RANKING, run)
    assert not (home / "account.json").exists() and not (home / "rules.json").exists()


def test_sell_requires_profile_and_matching_holding(tmp_path):
    account, rules, _, _, ev, cal = sell_setup(tmp_path)
    doc = json.loads(account.read_text(encoding="utf-8"))
    doc.pop("profile")
    save(account, doc)
    before = account.read_bytes()
    result = a._fill_invoke(account, rules, exp.ROOT, cal, exp.sha(cal), evidence_path=ev)
    assert result["error"] == "SELL_REQUIRES_EXPERIMENTAL_ACCOUNT"
    assert account.read_bytes() == before


def test_share_change_since_purchase_blocks_sell_even_before_sell_decision(tmp_path):
    account, rules, _, _, ev, cal = sell_setup(tmp_path)
    doc = json.loads(ev.read_text(encoding="utf-8"))
    source = next(s for s in doc["sources"] if s["key"] == "candidate_share_changes")
    body = json.dumps({"instrumentShareChange": [{"insCode": f.fx.CANDIDATE_INS, "dEven": 20260905,
                  "numberOfShareOld": 100, "numberOfShareNew": 200}]}).encode()
    Path(source["raw_path"]).write_bytes(gzip.compress(body))
    source["raw_sha256"] = hashlib.sha256(body).hexdigest()
    save(ev, doc)
    before = account.read_bytes()
    result = fill(account, rules, ev, cal)
    assert result["eligibility"] == "CORPORATE_ACTION_REQUIRES_MANUAL_RESOLUTION"
    assert account.read_bytes() == before


def test_real_snapshot_pin_rejects_modified_rank(tmp_path):
    path, rank = exp.pin_ranking(exp.DEFAULT_RANKING, tmp_path)
    assert rank["scored_count"] == {"P1": 167, "P3": 225}
    assert path.read_bytes() == exp.DEFAULT_RANKING.read_bytes()
    rank["rows"][0]["symbol"] = "changed"
    broken = tmp_path / "tampered.json"
    save(broken, rank)
    with pytest.raises(ValueError, match="RANKING_HASH_MISMATCH"):
        exp.pin_ranking(broken, tmp_path)


def test_start_real_subprocess_uses_real_time_and_keeps_strict_gate_blocked(tmp_path):
    # initialize's children are real CLI calls; no acquisition is invoked.
    home = tmp_path / "home"
    home.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    before = exp.now()
    with store.account_write_lock(home / "controller"):
        exp.initialize(home, exp.DEFAULT_RANKING, run)
    account = exp.profile_account(home)
    assert before <= dt.datetime.fromisoformat(account["active_decision"]["decided_at_utc"]) <= exp.now()
    assert account["cash_toman"] == 100000000 and account["holdings"] == []
    assert account["strict_decision_authorized"] is False
    assert account["ranking"]["status"] == "PREPARATION_UNCONFIRMED"
    assert account["paper_order"]["symbol"] == "غاذر"
    before_bytes = (home / "account.json").read_bytes()
    with pytest.raises(ValueError, match="ACCOUNT_ALREADY_EXISTS"):
        exp.initialize(home, exp.DEFAULT_RANKING, run)
    assert (home / "account.json").read_bytes() == before_bytes


def test_mark_real_raw_and_calendar_preview_repeat_and_identity(tmp_path, monkeypatch):
    account, rules, root, ev, cal, _ = setup(tmp_path)
    fill(account, rules, ev, cal)
    doc = json.loads(account.read_text(encoding="utf-8"))
    (root / "ranking.json").write_text("{}", encoding="utf-8")
    doc["experimental_inputs"] = {"ranking_file_sha256": exp.sha(root / "ranking.json")}
    save(account, doc)
    (root / "account.json").write_bytes(account.read_bytes())
    sources = json.loads(ev.read_text(encoding="utf-8"))
    daily = sources["sources"][0]
    body = json.dumps({"closingPriceDaily": [{"dEven": "20260905", "insCode": f.fx.CANDIDATE_INS, "pClosing": 1240, "qTotTran5J": 10000}]}).encode()
    Path(daily["raw_path"]).write_bytes(gzip.compress(body)); daily["raw_sha256"] = hashlib.sha256(body).hexdigest()
    save(ev, sources)
    monkeypatch.setattr(exp, "now", lambda: f.NOW + dt.timedelta(minutes=5))
    before = account.read_bytes()
    assert exp.mark_verified(root, ev, cal, False)["accounting"]["profit_loss_toman"] == -13
    assert account.read_bytes() == before
    assert exp.mark_verified(root, ev, cal, True)["status"] == "MARK_APPLIED"
    marked = account.read_bytes()
    assert exp.mark_verified(root, ev, cal, True)["status"] == "NO_NEW_MARK"
    assert account.read_bytes() == marked
    sources["candidate"]["company_id"] = "wrong"
    save(ev, sources)
    with pytest.raises(ValueError, match="MARK_IDENTITY_MISMATCH"):
        exp.mark_verified(root, ev, cal, True)
    assert account.read_bytes() == marked
