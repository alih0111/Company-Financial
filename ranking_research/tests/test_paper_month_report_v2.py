import datetime as dt
import json

from ranking_research.future_eval_v12_30 import paper_month_report as report


def payload(at, *, price_date=None, policy=None):
    config = {"started_at_utc": "2026-10-28T09:00:00+03:30",
        "ends_at_utc": "2026-11-27T09:00:00+03:30", "methods": ["P1", "P3"],
        "initial_capital_per_method_toman": 1000}
    if policy:
        config["observation_schedule_policy"] = policy
    account = {"cash_toman": 1000, "holdings": ([{"symbol": "XYZ", "shares": 1,
        "last_price_date": price_date}] if price_date is not False else []),
        "accounting": {"total_value_toman": 1000, "holdings_value_toman": 0},
        "paper_order": {"symbol": "XYZ"}, "event_log": []}
    return {"updated_at_utc": at, "config": config,
        "accounts": {m: {"outcome": {"status": "NO_NEW_MARK"}, "account": account} for m in ("P1", "P3")}}


def schedule(start, end, generated, *, times=("13:30", "22:30"), tolerance=30, grace=30, observations=()):
    config = {"started_at_utc": start, "ends_at_utc": end,
        "observation_schedule_policy": {"id": "fixture", "timezone": "Asia/Tehran",
            "daily_local_times": list(times), "days": "every_calendar_day",
            "matching_tolerance_minutes": tolerance, "late_grace_minutes": grace}}
    docs = [{"updated_at_utc": at} for at in observations]
    return report._schedule_coverage(docs, config, generated)


def test_coverage_unknown_without_persisted_schedule_policy(tmp_path):
    instant = "2026-10-28T14:00:00+03:30"
    result = report.summarize(tmp_path, payload(instant), False)
    assert result["schema_version"] == 2
    assert result["observation_schedule_coverage"]["status"] == "UNKNOWN"
    assert "scheduled_runs" not in result["accounts"]["P1"]


def test_duplicate_snapshots_count_unique_days_and_expose_stale_market_date(tmp_path):
    run = tmp_path / "runs" / "a"; run.mkdir(parents=True)
    first = payload("2026-10-28T13:35:00+03:30", price_date="2026-10-27")
    second = payload("2026-10-28T13:45:00+03:30", price_date="2026-10-27")
    (run / "daily.json").write_text(json.dumps(first), encoding="utf-8")
    current = payload("2026-10-28T13:45:00+03:30", price_date="2026-10-27")
    result = report.summarize(tmp_path, current, False)
    p1 = result["accounts"]["P1"]
    assert p1["observed_points"] == 2 and p1["unique_observation_days"] == 1
    assert p1["last_price_market_date"] == "2026-10-27"
    assert p1["last_price_is_stale"] is True and p1["last_price_age_calendar_days"] == 1
    # Two missing-price observations on one day count as one day without price.
    current = payload("2026-10-28T13:45:00+03:30", price_date=None)
    result = report.summarize(tmp_path, current, False)
    assert result["accounts"]["P1"]["unique_days_without_valid_price"] == 1


def test_recorded_schedule_counts_slots_not_snapshots(tmp_path):
    policy = {"id": "fixture", "timezone": "Asia/Tehran",
        "daily_local_times": ["13:30", "22:30"], "days": "every_calendar_day",
        "matching_tolerance_minutes": 30, "late_grace_minutes": 30}
    current = payload("2026-10-28T14:00:00+03:30", policy=policy)
    result = report.summarize(tmp_path, current, False)
    coverage = result["observation_schedule_coverage"]
    assert coverage["status"] == "KNOWN" and coverage["scheduled_slots"] == 1
    assert coverage["observed_slots"] == 1 and coverage["fraction"] == 1


def test_schedule_bounds_exclude_slots_before_start_and_after_generated():
    coverage = schedule("2026-10-27T23:41:00+03:30", "2026-11-26T23:41:00+03:30",
        "2026-10-28T14:00:00+03:30",
        observations=("2026-10-27T23:40:00+03:30", "2026-10-28T14:00:01+03:30"))
    assert coverage["scheduled_slots"] == 1
    assert coverage["observed_slots"] == 0 and coverage["pending_slots"] == 1
    assert coverage["missed_slots"] == 0


def test_midday_period_end_and_generation_after_end_keep_exact_bounds():
    coverage = schedule("2026-10-28T10:00:00+03:30", "2026-10-28T14:00:00+03:30",
        "2026-10-29T09:00:00+03:30", observations=("2026-10-28T14:01:00+03:30",))
    assert coverage["scheduled_slots"] == 1
    assert coverage["observed_slots"] == 0 and coverage["missed_slots"] == 1
    assert coverage["pending_slots"] == 0


def test_unmatched_slot_is_pending_until_delay_grace_expires():
    start, end = "2026-10-28T13:00:00+03:30", "2026-10-28T15:00:00+03:30"
    within = schedule(start, end, "2026-10-28T13:50:00+03:30", times=("13:30",), tolerance=30)
    expired = schedule(start, end, "2026-10-28T14:00:01+03:30", times=("13:30",), tolerance=30)
    assert (within["pending_slots"], within["missed_slots"]) == (1, 0)
    assert (expired["pending_slots"], expired["missed_slots"]) == (0, 1)


def test_one_observation_matches_at_most_one_close_slot_and_out_of_period_runs_are_ignored():
    coverage = schedule("2026-10-28T13:00:00+03:30", "2026-10-28T14:00:00+03:30",
        "2026-10-28T14:00:00+03:30", times=("13:30", "13:40"), tolerance=10,
        observations=("2026-10-28T13:35:00+03:30", "2026-10-28T14:00:01+03:30"))
    assert coverage["scheduled_slots"] == 2
    assert coverage["observed_slots"] == 1 and coverage["pending_slots"] == 1
    assert coverage["missed_slots"] == 0
    assert len(coverage["observed_slot_times_utc"]) == 1


def test_invalid_schedule_policy_stays_unknown():
    coverage = schedule("2026-10-28T10:00:00+03:30", "2026-10-29T10:00:00+03:30",
        "2026-10-28T14:00:00+03:30", times=("25:99",))
    assert coverage["status"] == "UNKNOWN"
    assert coverage["scheduled_slots"] is None and coverage["pending_slots"] is None
    incomplete = {"started_at_utc": "2026-10-28T10:00:00+03:30",
        "ends_at_utc": "2026-10-29T10:00:00+03:30",
        "observation_schedule_policy": {"id": "old", "timezone": "Asia/Tehran",
            "daily_local_times": ["13:30"], "matching_tolerance_minutes": 30}}
    incomplete_result = report._schedule_coverage([], incomplete, "2026-10-28T14:00:00+03:30")
    assert incomplete_result["status"] == "UNKNOWN"
    assert incomplete_result["reason"] == "RECORDED_OBSERVATION_SCHEDULE_POLICY_INCOMPLETE"


def test_malformed_daily_run_is_reported_and_not_silently_ignored(tmp_path):
    run = tmp_path / "runs" / "bad"; run.mkdir(parents=True)
    bad = run / "daily.json"; bad.write_text("{truncated", encoding="utf-8")
    result = report.summarize(tmp_path, payload("2026-10-28T14:00:00+03:30"), False)
    assert result["history_integrity"]["status"] == "ISSUES"
    assert result["history_integrity"]["malformed_run_count"] == 1
    assert result["history_integrity"]["malformed_runs"][0]["sha256"]
