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
from ranking_research.future_eval_v12_30 import paper_model_review as review
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


def cycle(home=None, start=False, *, action=None, public_trial_path=None, public_analysis_path=None):
    home = Path(home or HOME)
    if action not in (None, "sell", "buy"):
        raise ValueError("UNSUPPORTED_TRIAL_ACTION")
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
                "limits": "Thirty calendar days cannot contain 63 review sessions. Hold after initial fill; no invented sell or forced end liquidation. This is operational observation, not validation of full O00 performance.",
                "review_policy": {"id": "user-auto-rotation-v1", "cadence_sessions": 1,
                    "ranking_source": review.DEFAULT_RANKING_SOURCE, "max_ranking_age_days": 7,
                    "directive_fa": "به درخواست صریح کاربر: بازبینی مدل در هر اجرا و چرخش خودکار سبد کاغذی؛ فروش/خرید فقط از موتور قفل‌شده و با رتبه‌بندی تازهٔ pin‌شده."}})
        config = exp.load(config_path)
        if "review_policy" not in config:
            # Owner directive 2026-10-31: enable per-run model review and rotation
            # on the already-running trial; removing the key disables it again.
            config["review_policy"] = {"id": "user-auto-rotation-v1", "cadence_sessions": 1,
                "ranking_source": review.DEFAULT_RANKING_SOURCE, "max_ranking_age_days": 7,
                "directive_fa": "به درخواست صریح کاربر در ۳۱ اکتبر ۲۰۲۶: بازبینی مدل در هر اجرا و چرخش خودکار سبد کاغذی؛ فروش/خرید فقط از موتور قفل‌شده و با رتبه‌بندی تازهٔ pin‌شده."}
            exp.write(config_path, config)
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
                    if action:
                        raise ValueError(f"ACCOUNT_NOT_INITIALIZED_BEFORE_{action.upper()}")
                    exp.initialize(account_home, Path(config["ranking"]), method_run, method)
                if ended:
                    outcome = {"status": "TRIAL_ENDED", "reason": "No further trading; positions retained at last evidenced mark."}
                    review_outcome = None
                else:
                    review_outcome = None
                    decision = None
                    if action:
                        # Explicit user command (close the basket / re-enter):
                        # records the decision now; the fill itself stays bound to
                        # the first eligible session's close evidence, never retroactive.
                        decision = exp.decide(account_home, action.upper(), method_run)
                    evidence, cal = exp.acquire(account_home, method_run, exp.DEFAULT_MARKET)
                    outcome = exp.update(account_home, method_run, evidence, cal, True)
                    if decision:
                        outcome = {**outcome, "recorded_decision": decision.get("decision"),
                                   "decision_note_fa": ("بستن سبد: تصمیم فروش با فرمان صریح ثبت شد؛ " if action == "sell" else
                                                        "خرید مجدد: تصمیم خرید با فرمان صریح ثبت شد؛ ") +
                                                       "اجرای فرضی در نخستین جلسهٔ واجد شرایط بعدی انجام می‌شود."}
                    # Owner-directed model review (user-auto-rotation-v1): after the
                    # mark/fill settled, re-read the fresh ranking and hold or rotate.
                    review_outcome = review.run_review(account_home, method, method_run, evidence, cal, config)
                results[method] = exp.publish(account_home, outcome)
                if review_outcome is not None:
                    results[method]["review"] = review_outcome
            except (Exception, SystemExit) as exc:
                results[method] = {"outcome": {"status": "ERROR", "reason": str(exc)}}
                if (account_home / "account.json").exists():
                    results[method]["account"] = exp.load(account_home / "account.json")
        policy = config.get("review_policy")
        review_note = "قرارداد ۶۳جلسه‌ای حفظ شده؛ در دورهٔ ۳۰روزه، ارزش‌گذاری روزانه انجام می‌شود."
        if isinstance(policy, dict):
            review_note += (f" چرخش خودکار مدل فعال است (بازبینی هر {policy.get('cadence_sessions', 1)} جلسهٔ کاری): "
                            "نفر اول تازهٔ رتبه‌بندی بررسی می‌شود و در صورت تغییر، تصمیم فروش و سپس خرید جایگزین ثبت می‌شود.")
        else:
            review_note += " پس از خرید، نگهداری ادامه دارد و فروش ساختگی برای نمایش عملکرد ثبت نمی‌شود."
        if action == "sell":
            review_note += " بستن سبد با فرمان صریح این اجرا درخواست شده است؛ فروش فرضی روی قیمت پایانی نخستین جلسهٔ واجد شرایط بعد از همان فرمان ثبت می‌شود."
        elif action == "buy":
            review_note += " خرید مجدد با فرمان صریح این اجرا درخواست شده است؛ خرید فرضی روی قیمت پایانی نخستین جلسهٔ واجد شرایط بعد از همان فرمان ثبت می‌شود."
        payload = {"schema_version": 1, "updated_at_utc": instant.isoformat(), "config": config,
                   "state": "ENDED" if ended else "DAILY_ERRORS" if any(v["outcome"]["status"] == "ERROR" for v in results.values()) else "RUNNING",
                   "accounts": results, "real_orders_enabled": False,
                   "requested_action": action,
                   "review_note_fa": review_note}
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
    parser.add_argument("--sell", action="store_true",
                        help="Explicitly close each account's basket: record a SELL decision now; "
                             "the paper fill applies at the first eligible session's close on a later update.")
    parser.add_argument("--buy", action="store_true",
                        help="Explicitly re-open a closed (cash-only) account: record a BUY decision "
                             "from the pinned ranking; the fill stays bound to future session evidence.")
    args = parser.parse_args()
    if args.sell and args.buy:
        parser.error("--sell and --buy are mutually exclusive")
    result = cycle(start=args.start, action="sell" if args.sell else "buy" if args.buy else None)
    print(json.dumps({"state": result["state"], "accounts": {m: v["outcome"] for m, v in result["accounts"].items()}}, ensure_ascii=False))
    raise SystemExit(1 if result["state"] == "DAILY_ERRORS" else 0)
