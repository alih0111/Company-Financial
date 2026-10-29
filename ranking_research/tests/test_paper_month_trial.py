import datetime as dt
import json
from pathlib import Path
from ranking_research.future_eval_v12_30 import paper_month_trial as trial
from ranking_research.future_eval_v12_30 import experimental_paper as exp


def make_valid_account(home, method, price_date="2026-10-01"):
    account_home = home / method
    account_home.mkdir(parents=True, exist_ok=True)
    ranking = account_home / "ranking.json"
    ranking.write_text("fixture ranking", encoding="utf-8")
    event_time = f"{price_date}T10:00:00+03:30"
    account = {
        "account_id": f"fixture-{method}", "cash_toman": 90, "initial_capital_toman": 100,
        "realized_pnl_toman": 0, "external_flows_toman": 0,
        "holdings": [{"symbol": "TEST", "company_id": "test-company", "purchase_at_utc": event_time,
            "last_price_date": price_date, "price_status": "MARK_APPLIED", "shares": 1,
            "cost_basis_toman": 10, "fee_toman": 0, "market_value_toman": 10,
            "unrealized_pnl_toman": 0, "purchase_price_rial": 1000,
            "purchase_price_toman": 100, "last_price_rial": 1000}],
        "event_log": [{"event_id": f"buy-{method}", "type": "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE",
            "at_utc": event_time, "reason": "fixture buy", "details": "assumed_fee_toman=0"}],
        "accounting": {"holdings_value_toman": 10, "total_value_toman": 100, "profit_loss_toman": 0},
        "profile": exp.PROFILE, "real_order_submitted": False, "paper_method": method,
        "experimental_inputs": {"ranking_path": str(ranking), "ranking_file_sha256": exp.sha(ranking)},
    }
    exp.write(account_home / "account.json", account)
    return account_home / "account.json"


def test_p3_real_initialization_pins_p3_score_and_method(tmp_path):
    home=tmp_path/'P3'; home.mkdir(); run=tmp_path/'run'; run.mkdir()
    exp.initialize(home, exp.DEFAULT_RANKING, run, 'P3')
    a=exp.profile_account(home)
    ranking=exp.load(exp.DEFAULT_RANKING)
    top=next(r for r in ranking['rows'] if r['methods']['P3']['rank']==1)
    assert a['paper_method']=='P3' and a['contract']['weight_id']=='w0'
    assert a['active_decision']['candidate']['score']==top['methods']['P3']['score']
    assert a['paper_order']['company_id']==top['company_id']
    assert a['cash_toman']==100000000 and not a['holdings']


def test_ended_trial_never_acquires_or_trades_and_writes_final(tmp_path,monkeypatch):
    home=tmp_path/'trial'; home.mkdir()
    instant=dt.datetime(2026,12,1,tzinfo=dt.timezone.utc)
    exp.write(home/'config.json',{'started_at_utc':'2026-10-27T00:00:00+00:00','ends_at_utc':'2026-11-26T00:00:00+00:00','methods':['P1','P3'],'ranking':str(exp.DEFAULT_RANKING),'ranking_sha256':exp.sha(exp.DEFAULT_RANKING)})
    for m in ['P1','P3']:
        (home/m).mkdir(); exp.write(home/m/'account.json',{'method':m})
    monkeypatch.setattr(exp,'now',lambda:instant)
    monkeypatch.setattr(exp,'acquire',lambda *a: (_ for _ in ()).throw(AssertionError('network after end')))
    monkeypatch.setattr(exp,'publish',lambda h,o:{'outcome':o,'account':exp.load(h/'account.json')})
    monkeypatch.setattr(trial,'PUBLIC',tmp_path/'public.json')
    result=trial.cycle(home)
    assert result['state']=='ENDED' and (home/'final-report.json').exists()
    assert all(x['outcome']['status']=='TRIAL_ENDED' for x in result['accounts'].values())


def test_one_method_failure_does_not_skip_other_or_report_success(tmp_path,monkeypatch):
    home=tmp_path/'trial'; home.mkdir(); instant=exp.now()
    exp.write(home/'config.json',{'started_at_utc':instant.isoformat(),'ends_at_utc':(instant+dt.timedelta(days=30)).isoformat(),'methods':['P1','P3'],'ranking':str(exp.DEFAULT_RANKING),'ranking_sha256':exp.sha(exp.DEFAULT_RANKING)})
    for m in ['P1','P3']:
        (home/m).mkdir(); exp.write(home/m/'account.json',{'method':m})
    visits=[]
    def acquire(h,*args):
        visits.append(h.name)
        if h.name=='P1':raise ValueError('offline')
        return 'evidence','calendar'
    monkeypatch.setattr(exp,'acquire',acquire)
    monkeypatch.setattr(exp,'update',lambda *a:{'status':'NO_NEW_SESSION'})
    monkeypatch.setattr(exp,'publish',lambda h,o:{'outcome':o,'account':exp.load(h/'account.json')})
    monkeypatch.setattr(trial,'PUBLIC',tmp_path/'public.json')
    result=trial.cycle(home)
    assert visits==['P1','P3'] and result['state']=='DAILY_ERRORS'
    assert result['accounts']['P3']['outcome']['status']=='NO_NEW_SESSION'


def test_ended_cycle_preserves_holdings_and_ledger_and_replay_is_account_idempotent(tmp_path, monkeypatch):
    home = tmp_path / "trial"; home.mkdir()
    instant = dt.datetime(2026, 12, 1, 12, tzinfo=dt.timezone.utc)
    ranking = tmp_path / "ranking.json"; ranking.write_text("fixture", encoding="utf-8")
    exp.write(home / "config.json", {"started_at_utc": "2026-10-27T00:00:00+00:00",
        "ends_at_utc": "2026-11-26T00:00:00+00:00", "methods": ["P1", "P3"],
        "initial_capital_per_method_toman": 100, "ranking": str(ranking),
        "ranking_sha256": exp.sha(ranking)})
    paths = {m: make_valid_account(home, m) for m in ("P1", "P3")}
    before = {m: paths[m].read_bytes() for m in paths}
    monkeypatch.setattr(exp, "now", lambda: instant)
    monkeypatch.setattr(exp, "ROOT", tmp_path)
    monkeypatch.setattr(trial, "PUBLIC", tmp_path / "public" / "trial.json")
    monkeypatch.setattr(exp, "acquire", lambda *args: (_ for _ in ()).throw(AssertionError("network after end")))

    first = trial.cycle(home)
    final_doc = exp.load(home / "final-report.json")
    for method, path in paths.items():
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert path.read_bytes() == before[method]
        assert saved["cash_toman"] == 90 and len(saved["holdings"]) == 1
        assert len(saved["event_log"]) == 1
        summary = first["analysis"]["accounts"][method]
        assert summary["last_price_is_stale"] is True
        assert summary["last_price_age_calendar_days"] > 0
        assert final_doc["analysis"]["accounts"][method]["last_price_is_stale"] is True
        assert first["accounts"][method]["outcome"]["status"] == "TRIAL_ENDED"
    assert first["analysis"]["period"]["forced_liquidation"] is False

    second = trial.cycle(home)
    assert all(paths[m].read_bytes() == before[m] for m in paths)
    assert second["analysis"]["period"]["forced_liquidation"] is False
    assert all(len(exp.load(paths[m])["event_log"]) == 1 for m in paths)


def test_corrupt_run_and_missed_slot_recover_into_reconciled_public_report(tmp_path, monkeypatch):
    home = tmp_path / "trial"; home.mkdir()
    instant = dt.datetime(2026, 10, 28, 16, tzinfo=dt.timezone(dt.timedelta(hours=3, minutes=30)))
    ranking = tmp_path / "ranking.json"; ranking.write_text("fixture", encoding="utf-8")
    policy = {"id": "fixture-daily", "timezone": "Asia/Tehran", "daily_local_times": ["13:30"],
        "days": "every_calendar_day", "matching_tolerance_minutes": 10, "late_grace_minutes": 10}
    exp.write(home / "config.json", {"started_at_utc": "2026-10-28T13:00:00+03:30",
        "ends_at_utc": "2026-10-28T15:00:00+03:30", "methods": ["P1", "P3"],
        "initial_capital_per_method_toman": 100, "ranking": str(ranking),
        "ranking_sha256": exp.sha(ranking), "observation_schedule_policy": policy})
    account_paths = {m: make_valid_account(home, m, price_date="2026-10-27") for m in ("P1", "P3")}
    account_bytes = {m: p.read_bytes() for m, p in account_paths.items()}
    corrupt = home / "runs" / "lost-or-corrupt" / "daily.json"
    corrupt.parent.mkdir(parents=True); corrupt.write_text("{truncated", encoding="utf-8")
    monkeypatch.setattr(exp, "now", lambda: instant)
    monkeypatch.setattr(exp, "ROOT", tmp_path)
    monkeypatch.setattr(trial, "PUBLIC", tmp_path / "public" / "trial.json")
    acquire_calls = []
    def unexpected_acquire(*args):
        acquire_calls.append(args)
        raise AssertionError("no network after end")
    monkeypatch.setattr(exp, "acquire", unexpected_acquire)

    public_trial_path = tmp_path / "public" / "trial.json"
    public_analysis_path = tmp_path / "client" / "public" / "research" / "paper-experimental" / "analysis.json"
    result = trial.cycle(home, public_trial_path=public_trial_path,
        public_analysis_path=public_analysis_path)
    analysis = result["analysis"]
    assert result["state"] == "ENDED"
    assert not acquire_calls
    assert all(result["accounts"][m]["outcome"]["status"] == "TRIAL_ENDED" for m in ("P1", "P3"))
    assert analysis["history_integrity"]["status"] == "ISSUES"
    assert analysis["history_integrity"]["malformed_run_count"] == 1
    coverage = analysis["observation_schedule_coverage"]
    assert coverage["scheduled_slots"] == 1
    assert coverage["observed_slots"] == 0 and coverage["missed_slots"] == 1
    assert coverage["pending_slots"] == 0

    latest = (home / "latest.json").read_bytes()
    public_trial = public_trial_path.read_bytes()
    final = (home / "final-report.json").read_bytes()
    assert latest == public_trial == final
    assert public_analysis_path.read_bytes() == (home / "latest-analysis.json").read_bytes()
    report_doc = json.loads(latest)
    for method in ("P1", "P3"):
        assert account_paths[method].read_bytes() == account_bytes[method]
        assert report_doc["accounts"][method]["account_sha256"] == exp.sha(account_paths[method])
        assert report_doc["accounts"][method]["account"]["event_log"] == json.loads(account_bytes[method])["event_log"]


def test_temporary_cycle_cannot_write_outside_injected_tmp_outputs(tmp_path, monkeypatch):
    home = tmp_path / "isolated"; home.mkdir()
    instant = dt.datetime(2026, 12, 1, 12, tzinfo=dt.timezone.utc)
    ranking = tmp_path / "ranking.json"; ranking.write_text("fixture", encoding="utf-8")
    exp.write(home / "config.json", {"started_at_utc": "2026-10-27T00:00:00+00:00",
        "ends_at_utc": "2026-11-26T00:00:00+00:00", "methods": ["P1", "P3"],
        "initial_capital_per_method_toman": 100, "ranking": str(ranking),
        "ranking_sha256": exp.sha(ranking)})
    for method in ("P1", "P3"):
        make_valid_account(home, method)
    monkeypatch.setattr(exp, "now", lambda: instant)
    allowed_root = tmp_path.resolve()
    original_write = exp.write
    writes = []

    def confined_write(path, value):
        resolved = Path(path).resolve()
        assert resolved.is_relative_to(allowed_root), f"write escaped fixture temp: {resolved}"
        writes.append(resolved)
        return original_write(resolved, value)

    monkeypatch.setattr(exp, "write", confined_write)
    public_trial = tmp_path / "public" / "trial.json"
    public_analysis = tmp_path / "public" / "analysis.json"
    result = trial.cycle(home, public_trial_path=public_trial,
        public_analysis_path=public_analysis)
    assert result["state"] == "ENDED"
    assert public_trial.is_file() and public_analysis.is_file()
    assert writes and all(path.is_relative_to(allowed_root) for path in writes)
