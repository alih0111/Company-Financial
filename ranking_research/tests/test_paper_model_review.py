"""user-auto-rotation-v1 review logic; hermetic fixtures, no network."""
import datetime as dt
import json
import pytest
from pathlib import Path

from ranking_research.future_eval_v12_30 import experimental_paper as exp
from ranking_research.future_eval_v12_30 import paper_model_review as rv

BINDING = {"id": "public-paper-v1", "provider": "public-index", "version": 1, "sha256": "b" * 64}
POLICY = {"id": "user-auto-rotation-v1", "cadence_sessions": 1,
          "ranking_source": "fixture/latest-ranking.json", "max_ranking_age_days": 7}


def sha(path):
    return exp.sha(path)


def make_home(tmp_path, *, side="BUY", holdings=True, filled=True):
    home = tmp_path / "home"
    home.mkdir()
    ranking = home / "ranking.json"
    ranking.write_text("{}", encoding="utf-8")
    rules = home / "rules.json"
    rules.write_text(json.dumps({"rule_id": "fixture-rules", "calendar_policy": BINDING}), encoding="utf-8")
    hold = [{"symbol": "TEST", "company_id": "fixture-company", "purchase_at_utc": "2026-01-03 close",
             "last_price_date": "2026-01-02", "price_status": "fixture", "shares": 1,
             "cost_basis_toman": 10, "fee_toman": 0, "market_value_toman": 10,
             "unrealized_pnl_toman": 0, "purchase_price_rial": 1000.0,
             "purchase_price_toman": 100.0, "last_price_rial": 1000.0}] if holdings else []
    order = {"order_id": "paper-order-fixture", "decision_id": "paper-decision-fixture",
             "side": side, "symbol": "TEST",
             "company_id": "fixture-company", "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
             "created_at_utc": "2026-01-01T17:00:00+00:00", "expires_after_official_sessions": 3,
             "calendar_policy": BINDING,
             "fill_event_id": None, "designated_execution_session": None}
    if filled:
        order.update(status="PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE",
                     designated_execution_session="20260102",
                     fill_event_id="paper-fill-paper-order-fixture-20260102",
                     fill_receipt={"calendar": {"validated_at_utc": "2026-01-03T10:00:00+00:00"}})
    account = {
        "account_id": "fixture-review", "cash_toman": 90 if holdings else 100,
        "initial_capital_toman": 100, "realized_pnl_toman": 0, "external_flows_toman": 0,
        "holdings": hold, "profile": exp.PROFILE, "real_order_submitted": False,
        "paper_method": "P1",
        "experimental_inputs": {"ranking_path": str(ranking), "ranking_file_sha256": sha(ranking)},
        "calendar_policy": BINDING,
        "active_decision": {"decision_id": "paper-decision-fixture",
            "decided_at_utc": "2026-01-01T17:00:00+00:00", "decision_local_date": "2026-01-01",
            "calendar_policy": BINDING,
            "execution_rules": {"rule_id": "fixture-rules", "sha256": sha(rules)}},
        "paper_order": order,
        "event_log": [{"event_id": "seed", "type": "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE",
            "at_utc": "2026-01-03T10:00:00+00:00", "reason": "fixture buy", "details": "x"}],
        "accounting": {"holdings_value_toman": 10 if holdings else 0,
                       "total_value_toman": 100, "profit_loss_toman": 0},
    }
    (home / "account.json").write_text(json.dumps(account), encoding="utf-8")
    return home


def sessions_answer(days):
    return {"readiness": {"calendar_ready": True, "blocking_reasons": []},
            "sessions_after_decision": {"sessions": ["20260102"] + list(days)}}


def rank_doc(evaluation="2026-01-04", top="TEST"):
    company = "fixture-company" if top == "TEST" else "newco-company"
    rows = [{"company_id": company, "symbol": top,
             "methods": {"P1": {"rank": 1, "score": 50, "financial_factor_coverage": 1}}}]
    rows.append({"company_id": "other-company", "symbol": "OTHER",
                 "methods": {"P1": {"rank": 2, "score": 40, "financial_factor_coverage": 1}}})
    return {"evaluation_date": evaluation, "artifact_sha256": "c" * 64, "rows": rows}


def patch_world(monkeypatch, tmp_path, *, days, top="TEST", evaluation="2026-01-04", today=dt.date(2026, 1, 4)):
    decisions = []
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(rv, "_calendar_answer", lambda *a, **k: sessions_answer(days))
    monkeypatch.setattr(rv, "_today", lambda: today)
    monkeypatch.setattr(exp, "pin_ranking", lambda source, home, method="P1": (snapshot, rank_doc(evaluation, top)))
    monkeypatch.setattr(exp, "decide", lambda home, side, run_dir, ranking_source=None:
                        decisions.append((side, str(ranking_source))) or {"decision": {"side": side}})
    return decisions, snapshot


def test_no_policy_disables_review(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, _ = patch_world(monkeypatch, tmp_path, days=["20260103"])
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {})
    assert result is None and decisions == []


def test_unfilled_order_skips_review(tmp_path, monkeypatch):
    home = make_home(tmp_path, filled=False)
    decisions, _ = patch_world(monkeypatch, tmp_path, days=["20260103"])
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    assert result["status"] == "REVIEW_SKIPPED" and result["reason"] == "ORDER_NOT_FILLED"
    assert decisions == []


def test_waiting_before_cadence_touches_nothing(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, _ = patch_world(monkeypatch, tmp_path, days=[])
    before = (home / "account.json").read_bytes()
    config = {"review_policy": {**POLICY, "cadence_sessions": 3}}
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", config)
    assert result["status"] == "REVIEW_WAITING" and result["sessions_since_fill"] == 0
    assert decisions == [] and (home / "account.json").read_bytes() == before


def test_future_dated_ranking_cannot_trigger_rotation(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, _ = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEW",
                               evaluation="2026-01-05", today=dt.date(2026, 1, 4))
    before = (home / "account.json").read_bytes()
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    assert result["status"] == "REVIEW_RANKING_INVALID"
    assert result["reason"] == "RANKING_DATE_IN_FUTURE"
    assert decisions == [] and (home / "account.json").read_bytes() == before


def test_hold_review_records_one_idempotent_event(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, _ = patch_world(monkeypatch, tmp_path, days=["20260103"])
    config = {"review_policy": POLICY}
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", config)
    assert result["status"] == "REVIEW_HOLD" and result["candidate"] == "TEST"
    assert decisions == []
    doc = json.loads((home / "account.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in doc["event_log"]].count("PAPER_MODEL_REVIEW_HOLD") == 1
    after = (home / "account.json").read_bytes()
    again = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", config)
    assert again["status"] == "REVIEW_ALREADY_RECORDED"
    assert (home / "account.json").read_bytes() == after


def test_changed_candidate_records_sell_and_pending_buy(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO")
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal",
                           {"review_policy": POLICY})
    assert result["status"] == "REVIEW_ROTATE_SELL_RECORDED"
    assert result["sold"] == "TEST" and result["new"] == "NEWCO"
    assert decisions and decisions[0][0] == "SELL"
    state = exp.load(rv.state_path(home))
    assert state["pending_buy"]["symbol"] == "NEWCO"
    assert state["pending_buy"]["ranking_snapshot"] == str(snapshot)
    doc = json.loads((home / "account.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in doc["event_log"]].count("PAPER_MODEL_REVIEW_ROTATE") == 1


@pytest.mark.parametrize("crash_after_sell", [False, True])
def test_rotation_intent_survives_interruption_without_duplicate_sell(tmp_path, monkeypatch, crash_after_sell):
    home = make_home(tmp_path)
    patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO")
    calls = []
    def decide(_home, side, _run, ranking_source=None):
        calls.append(side)
        if not crash_after_sell and len(calls) == 1:
            raise RuntimeError("fixture interruption before account write")
        account = exp.load(home / "account.json")
        previous = dict(account["paper_order"])
        account.setdefault("order_history", []).append({"order": previous})
        account["paper_order"].update(side="SELL", order_id="sale-order", fill_event_id=None,
            status="PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", source_manifest=str(_run / "decision-basis.json"))
        exp.write(home / "account.json", account)
        if crash_after_sell and len(calls) == 1:
            raise RuntimeError("fixture interruption after account write")
        return {"decision": {"side": side}}
    monkeypatch.setattr(exp, "decide", decide)
    args = (home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    with pytest.raises(RuntimeError, match="fixture interruption"):
        rv.run_review(*args)
    intent = exp.load(rv.state_path(home))["pending_buy"]
    assert intent["symbol"] == "NEWCO" and intent["phase"] == "SELL_INTENT"
    result = rv.run_review(*args)
    assert result["status"] == ("REVIEW_SKIPPED" if crash_after_sell else "REVIEW_ROTATE_SELL_RECOVERED")
    assert len(calls) == (1 if crash_after_sell else 2)
    again = rv.run_review(*args)
    assert again["status"] == "REVIEW_SKIPPED"
    assert len(calls) == (1 if crash_after_sell else 2)
    assert sum(e["type"] == "PAPER_MODEL_REVIEW_ROTATE" for e in exp.load(home / "account.json")["event_log"]) == 1


def test_rotation_recovery_rejects_stale_pinned_ranking(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO",
                                      evaluation="2025-01-01", today=dt.date(2026, 1, 4))
    exp.write(rv.state_path(home), {"pending_buy": {"phase": "SELL_INTENT", "sell_order_id": "paper-order-fixture",
        "sold_company_id": "fixture-company", "company_id": "newco-company", "symbol": "NEWCO",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64}, "history": []})
    before = (home / "account.json").read_bytes()
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    assert result["status"] == "REVIEW_RECOVERY_REQUIRED" and result["reason"] == "PINNED_RANKING_NOT_FRESH"
    assert not decisions and (home / "account.json").read_bytes() == before


def test_stale_ranking_holds_without_rotation(tmp_path, monkeypatch):
    home = make_home(tmp_path)
    decisions, _ = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO",
                               evaluation="2020-01-01", today=dt.date(2026, 1, 4))
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal",
                           {"review_policy": POLICY})
    assert result["status"] == "REVIEW_HOLD_RANKING_STALE" and decisions == []
    assert not rv.state_path(home).exists()


def test_rebuy_recorded_after_sell_settles(tmp_path, monkeypatch):
    home = make_home(tmp_path, side="SELL", holdings=False)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO")
    exp.write(rv.state_path(home), {"pending_buy": {"symbol": "NEWCO", "company_id": "newco-company",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64}, "history": []})
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal",
                           {"review_policy": POLICY})
    assert result["status"] == "REVIEW_REBUY_RECORDED" and result["symbol"] == "NEWCO"
    assert decisions and decisions[0][0] == "BUY" and decisions[0][1] == str(snapshot)
    state = exp.load(rv.state_path(home))
    assert state["pending_buy"] is None and len(state["history"]) == 1
    doc = json.loads((home / "account.json").read_text(encoding="utf-8"))
    assert [e["type"] for e in doc["event_log"]].count("PAPER_MODEL_REVIEW_REBUY") == 1


def test_pending_buy_with_unsettled_holdings_waits(tmp_path, monkeypatch):
    home = make_home(tmp_path, side="SELL", holdings=True)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"])
    exp.write(rv.state_path(home), {"pending_buy": {"symbol": "NEWCO", "company_id": "newco",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64}, "history": []})
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal",
                           {"review_policy": POLICY})
    assert result["status"] == "REVIEW_SKIPPED" and result["reason"] == "SELL_FILL_NOT_SETTLED"
    assert decisions == [] and exp.load(rv.state_path(home))["pending_buy"]["symbol"] == "NEWCO"


def test_stale_pending_buy_is_not_recorded_after_sell(tmp_path, monkeypatch):
    home = make_home(tmp_path, side="SELL", holdings=False)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO",
                                      evaluation="2025-01-01", today=dt.date(2026, 1, 4))
    exp.write(rv.state_path(home), {"pending_buy": {"symbol": "NEWCO", "company_id": "newco-company",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64}, "history": []})
    before = (home / "account.json").read_bytes()
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    assert result["status"] == "REVIEW_RECOVERY_REQUIRED" and result["reason"] == "PINNED_RANKING_NOT_FRESH"
    assert not decisions and (home / "account.json").read_bytes() == before


def test_unrelated_sell_cannot_consume_rotation_intent(tmp_path, monkeypatch):
    home = make_home(tmp_path, side="SELL", holdings=False)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO")
    account = exp.load(home / "account.json")
    account["order_history"] = [{"order": {"order_id": "original-buy", "side": "BUY"}}]
    account["paper_order"]["source_manifest"] = "unrelated-decision-basis.json"
    exp.write(home / "account.json", account)
    exp.write(rv.state_path(home), {"pending_buy": {"phase": "SELL_INTENT", "sell_order_id": "original-buy",
        "sold_company_id": "fixture-company", "symbol": "NEWCO", "company_id": "newco-company",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64, "sell_basis_path": "expected-basis.json"}, "history": []})
    before = (home / "account.json").read_bytes()
    result = rv.run_review(home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    assert result["status"] == "REVIEW_RECOVERY_REQUIRED" and result["reason"] == "PENDING_SELL_ORDER_MISMATCH"
    assert not decisions and (home / "account.json").read_bytes() == before


def test_interruption_after_buy_decision_does_not_repeat_buy(tmp_path, monkeypatch):
    home = make_home(tmp_path, side="SELL", holdings=False)
    _, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO")
    exp.write(rv.state_path(home), {"pending_buy": {"symbol": "NEWCO", "company_id": "newco-company",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64}, "history": []})
    calls = []
    def decide(_home, side, _run, ranking_source=None):
        calls.append(side)
        account = exp.load(home / "account.json")
        account["paper_order"].update(side="BUY", order_id="new-buy-order", fill_event_id=None,
                                      status="PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE")
        exp.write(home / "account.json", account)
        raise RuntimeError("fixture interruption after buy decision")
    monkeypatch.setattr(exp, "decide", decide)
    args = (home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    with pytest.raises(RuntimeError, match="fixture interruption"):
        rv.run_review(*args)
    assert exp.load(rv.state_path(home))["pending_buy"]["symbol"] == "NEWCO"
    assert rv.run_review(*args)["status"] == "REVIEW_SKIPPED"
    assert calls == ["BUY"]


@pytest.mark.parametrize("matching", [True, False])
def test_interrupted_rebuy_is_reconciled_only_with_matching_order_history(tmp_path, monkeypatch, matching):
    home = make_home(tmp_path, side="SELL", holdings=False)
    decisions, snapshot = patch_world(monkeypatch, tmp_path, days=["20260103"], top="NEWCO")
    account = exp.load(home / "account.json")
    basis_path = str(tmp_path / "original-run" / "decision-basis.json")
    sale = dict(account["paper_order"], order_id="sale-order", side="SELL", company_id="fixture-company", source_manifest=basis_path)
    account["order_history"] = [{"order": {"order_id": "paper-order-fixture", "side": "BUY"}}, {"order": sale}]
    account["paper_order"].update(order_id="new-buy-order", side="BUY", company_id="newco-company" if matching else "other-company", fill_event_id=None)
    account["active_decision"]["ranking"] = {"artifact_sha256": "c" * 64}
    exp.write(home / "account.json", account)
    exp.write(rv.state_path(home), {"pending_buy": {"phase": "SELL_INTENT", "sell_order_id": "paper-order-fixture",
        "sold_company_id": "fixture-company", "symbol": "NEWCO", "company_id": "newco-company",
        "ranking_snapshot": str(snapshot), "ranking_sha256": "c" * 64, "sell_basis_path": basis_path}, "history": []})
    args = (home, "P1", tmp_path / "run", tmp_path / "evidence", tmp_path / "cal", {"review_policy": POLICY})
    before = (home / "account.json").read_bytes()
    result = rv.run_review(*args)
    assert not decisions
    if matching:
        assert result["status"] == "REVIEW_REBUY_RECOVERED"
        assert exp.load(rv.state_path(home))["pending_buy"] is None
        assert sum(e["event_id"] == "paper-review-rebuy-sale-order" for e in exp.load(home / "account.json")["event_log"]) == 1
        assert rv.run_review(*args)["status"] == "REVIEW_SKIPPED"
    else:
        assert result["status"] == "REVIEW_RECOVERY_REQUIRED"
        assert (home / "account.json").read_bytes() == before
        assert exp.load(rv.state_path(home))["pending_buy"] is not None
