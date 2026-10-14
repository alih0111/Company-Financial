import datetime as dt
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("qvt_forward", Path(__file__).parents[1] / "forward.py")
forward = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forward)
policy = forward.read(Path(__file__).parents[1] / "policy.json")


def candidate(rank, industry="A", **overrides):
    row = {"company_id": str(rank), "symbol": str(rank), "industry": industry, "rank": rank,
           "score": 90 - rank, "status": "buy_review", "full_coverage": True, "model_family": "industrial",
           "risk_gate_status": "review_required", "critical": False, "conditional": False,
           "negative_operating_profit": False}
    for a in ("q", "v", "t"):
        row[a] = {"scored_factors": ["one"], "missing_factors": []}
    row.update(overrides)
    return row


def test_caps_preserve_cash_instead_of_forcing_ten_names():
    rows = [candidate(i) for i in range(1, 6)] + [candidate(6, industry="B", critical=True)]
    selected, skipped = forward.choose(rows, policy)
    assert [r["rank"] for r in selected] == [1, 2, 3]
    assert abs(sum(r["weight"] for r in selected) - .3) < 1e-9
    assert len(skipped) == 3


def test_missing_data_and_negative_profit_cannot_enter():
    missing = candidate(1)
    missing["q"]["missing_factors"] = [{"kind": "missing"}]
    excluded = candidate(2)
    excluded["q"]["missing_factors"] = [{"kind": "policy_excluded"}]
    selected, _ = forward.choose([missing, excluded, candidate(3, negative_operating_profit=True)], policy)
    assert [r["rank"] for r in selected] == [2]


def test_calendar_uses_market_breadth_and_excludes_weekend():
    rows = {"2026-10-14": {"pClosing": 100, "qTotTran5J": 10},
            "2026-10-15": {"pClosing": 100, "qTotTran5J": 10}}
    assert forward.sessions({str(i): rows for i in range(29)}) == []
    assert forward.sessions({str(i): rows for i in range(30)}) == ["2026-10-14"]


def test_no_carry_forward_or_fake_corporate_action_return():
    panel = {"2026-10-14": {"pClosing": 100, "priceYesterday": 99, "qTotTran5J": 10},
             "2026-10-17": {"pClosing": 55, "priceYesterday": 50, "qTotTran5J": 10}}
    assert forward.reference_return(panel, "2026-10-14", "2026-10-17", list(panel)) == (None, "corporate_action_review")
    del panel["2026-10-17"]
    assert forward.reference_return(panel, "2026-10-14", "2026-10-17", list(panel)) == (None, "missing_exact_session")


def test_observation_cannot_backfill_decision_day(tmp_path):
    decision = {"decision_id": "test", "decision_date": "2026-10-13", "frozen_at": "2026-10-13T10:00:00Z",
                "universe": {"one": {"ins_code": "123"}}}
    rows = [{"date": "2026-10-13", "raw": {"insCode": "123", "dEven": 20261013,
            "pClosing": 100, "priceYesterday": 99, "qTotTran5J": 100}}]
    forward.save(tmp_path / "observations/test/20261014/one.json", {
        "company_id": "one", "ins_code": "123", "collected_at": "2026-10-14T10:00:00Z",
        "rows": rows, "payload_sha256": forward.digest(rows)})
    assert forward.collect_evidence(decision, tmp_path) == {"one": {}}


def test_future_or_old_snapshot_cannot_create_decision(tmp_path):
    import pytest
    now = dt.datetime(2026, 10, 13, 10, tzinfo=dt.timezone.utc)
    for ranking in ({"as_of": "2026-10-12", "cutoff": "2026-10-12T10:00:00Z"},
                    {"as_of": "2026-10-13", "cutoff": "2026-10-13T11:00:00Z"}):
        with pytest.raises(ValueError, match="same-day"):
            forward.freeze(ranking, policy, now, tmp_path)


def test_forward_decision_immutable_and_net_cost_accounting(tmp_path, monkeypatch):
    now = dt.datetime(2026, 10, 13, 10, tzinfo=dt.timezone.utc)
    rows = [candidate(i, status="buy_review" if i == 1 else "wait") for i in range(1, 31)]
    ranking = {"as_of": "2026-10-13", "cutoff": "2026-10-13T09:00:00Z", "ranked": rows,
               "sources": {a: {"sha256": a * 64} for a in ("q", "v", "t")}}
    monkeypatch.setattr(forward, "canonical_identities", lambda: {str(i): (str(i), str(i)) for i in range(1, 31)})
    monkeypatch.setattr(forward, "checked_cache", lambda cid: {
        "company_id": cid, "security_id": cid, "ins_code": cid, "symbol": cid,
        "payload_sha256": "a" * 64, "collected_at": "2026-10-13T08:00:00Z",
        "rows": [{"date": "2026-10-12", "raw": {"pClosing": 100}}]})
    decision = forward.freeze(ranking, policy, now, tmp_path)
    path = tmp_path / "decisions/2026-10/decision.json"
    frozen_bytes = path.read_bytes()
    ranking["ranked"][0]["status"] = "weak"
    second = forward.freeze(ranking, policy, now, tmp_path)
    assert second == decision
    assert path.read_bytes() == frozen_bytes
    assert forward.observe(decision, tmp_path)["return_pct"] is None
    for cid in decision["universe"]:
        days = [{"date": date, "raw": {"insCode": cid, "dEven": int(date.replace("-", "")),
                 "pClosing": close, "priceYesterday": 100, "qTotTran5J": 100}}
                for date, close in (("2026-10-14", 100), ("2026-10-17", 110))]
        forward.save(tmp_path / f"observations/{decision['decision_id']}/20261017/{cid}.json", {
            "company_id": cid, "ins_code": cid, "collected_at": "2026-10-17T10:00:00Z",
            "rows": days, "payload_sha256": forward.digest(days)})
    summary = forward.observe(decision, tmp_path)
    expected = 100 * .1 * (1.1 * .995 / 1.005 - 1)
    assert abs(summary["return_pct"] - expected) < 1e-9
    assert abs(summary["benchmark_return_pct"] - 10) < 1e-9
    assert summary["completed_cycles"] == 0  # Three days cannot become a full cycle.
    assert summary["real_orders"] == 0
