"""Thirty-day, two-method forward paper observation; no brokerage integration."""
import argparse
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ranking_research.future_eval_v12_30 import experimental_paper as exp
from ranking_research.future_eval_v12_30 import paper_month_report
from ranking_research import paper_account_store as store

DEFAULT_HOME = ROOT / "ranking_research/output/paper_month_trial"
HOME = DEFAULT_HOME
PUBLIC = ROOT / "client/public/research/paper-experimental/trial.json"
PUBLIC_ANALYSIS = ROOT / "client/public/research/paper-experimental/analysis.json"


def _public_targets(home, public_trial_path=None, public_analysis_path=None):
    """Use shared web artifacts only for the canonical trial home or explicit injection."""
    canonical = Path(home).resolve() == DEFAULT_HOME.resolve()
    trial_target = Path(public_trial_path) if public_trial_path is not None else (PUBLIC if canonical else None)
    analysis_target = (Path(public_analysis_path) if public_analysis_path is not None else
                       (PUBLIC_ANALYSIS if canonical else None))
    return trial_target, analysis_target


def cycle(home=None, start=False, *, public_trial_path=None, public_analysis_path=None):
    home = Path(home or HOME)
    public_trial, public_analysis = _public_targets(home, public_trial_path, public_analysis_path)
    home.mkdir(parents=True, exist_ok=True)
    with store.account_write_lock(home / "trial-controller"):
        config_path = home / "config.json"
        if not config_path.exists():
            if not start:
                raise ValueError("TRIAL_NOT_INITIALIZED")
            instant = exp.now()
            exp.write(config_path, {"started_at_utc": instant.isoformat(),
                "ends_at_utc": (instant + dt.timedelta(days=30)).isoformat(),
                "methods": ["P1", "P3"], "review_cadence_sessions": 63,
                "initial_capital_per_method_toman": 100000000,
                "ranking": str(exp.DEFAULT_RANKING), "ranking_sha256": exp.sha(exp.DEFAULT_RANKING),
                "observation_schedule_policy": {"id": "company-financial-paper-task-v1",
                    "timezone": "Asia/Tehran", "daily_local_times": ["13:30", "22:30"],
                    "days": "every_calendar_day", "matching_tolerance_minutes": 30,
                    "late_grace_minutes": 30,
                    "basis": "Windows Task Scheduler triggers observed 2026-10-28; execution IDs are not stored in daily snapshots."},
                "limits": "Thirty calendar days cannot contain 63 review sessions. Hold after initial fill; no invented sell or forced end liquidation. This is operational observation, not validation of full O00 performance."})
        config = exp.load(config_path)
        if exp.sha(Path(config["ranking"])) != config["ranking_sha256"]:
            raise ValueError("TRIAL_RANKING_CHANGED")
        instant = exp.now()
        ended = instant >= dt.datetime.fromisoformat(config["ends_at_utc"])
        run_dir = home / "runs" / (instant.strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:6])
        run_dir.mkdir(parents=True)
        results = {}
        for method in config["methods"]:
            account_home = home / method
            account_home.mkdir(exist_ok=True)
            method_run = run_dir / method
            method_run.mkdir()
            try:
                if not (account_home / "account.json").exists():
                    if ended:
                        raise ValueError("TRIAL_ENDED_BEFORE_ACCOUNT_CREATION")
                    exp.initialize(account_home, Path(config["ranking"]), method_run, method)
                if ended:
                    outcome = {"status": "TRIAL_ENDED", "reason": "No further trading; positions retained at last evidenced mark."}
                else:
                    evidence, cal = exp.acquire(account_home, method_run, exp.DEFAULT_MARKET)
                    outcome = exp.update(account_home, method_run, evidence, cal, True)
                results[method] = exp.publish(account_home, outcome)
            except (Exception, SystemExit) as exc:
                results[method] = {"outcome": {"status": "ERROR", "reason": str(exc)}}
                if (account_home / "account.json").exists():
                    results[method]["account"] = exp.load(account_home / "account.json")
        payload = {"schema_version": 1, "updated_at_utc": instant.isoformat(), "config": config,
                   "state": "ENDED" if ended else "DAILY_ERRORS" if any(v["outcome"]["status"] == "ERROR" for v in results.values()) else "RUNNING",
                   "accounts": results, "real_orders_enabled": False,
                   "review_note_fa": "قرارداد ۶۳جلسه‌ای حفظ شده؛ در دورهٔ ۳۰روزه پس از خرید، نگهداری و ارزش‌گذاری روزانه انجام می‌شود. فروش ساختگی برای نمایش عملکرد ثبت نمی‌شود."}
        exp.write(run_dir / "daily.json", payload)
        analysis = paper_month_report.summarize(home, payload, ended)
        payload["analysis"] = analysis
        exp.write(home / "latest-analysis.json", analysis)
        exp.write(home / "latest.json", payload)
        if public_analysis is not None:
            exp.write(public_analysis, analysis)
        if public_trial is not None:
            exp.write(public_trial, payload)
        if ended:
            exp.write(home / "final-report.json", payload)
        return payload


def rebuild_analysis(home=None, *, public_analysis_path=None):
    """Rebuild derived analysis under the same controller lock, without acquiring or changing accounts."""
    home = Path(home or HOME)
    _, public_analysis = _public_targets(home, public_analysis_path=public_analysis_path)
    with store.account_write_lock(home / "trial-controller"):
        payload = exp.load(home / "latest.json")
        config = payload.get("config", {})
        ended = payload.get("state") == "ENDED"
        if not ended and config.get("ends_at_utc"):
            ended = exp.now() >= dt.datetime.fromisoformat(config["ends_at_utc"])
        analysis = paper_month_report.summarize(home, payload, ended)
        exp.write(home / "latest-analysis.json", analysis)
        if public_analysis is not None:
            exp.write(public_analysis, analysis)
        return analysis


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true")
    args = parser.parse_args()
    result = cycle(start=args.start)
    print(json.dumps({"state": result["state"], "accounts": {m: v["outcome"] for m, v in result["accounts"].items()}}, ensure_ascii=False))
    raise SystemExit(1 if result["state"] == "DAILY_ERRORS" else 0)
