"""Manually check the independent paper account against fresh local evidence.

Run after materializing an explicitly selected ranking and TSETMC daily batch:
  python ranking_research/future_eval_v12_30/check_paper_account.py
This command is read-only with respect to source archives and official ledgers.
It writes only the paper-account status/check log in the V12.36 run and web app.
"""
from __future__ import annotations
import hashlib, json
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
try:
    from ranking_research import paper_account_store
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ranking_research import paper_account_store
import math
from decimal import Decimal
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "ranking_research/output/return_v12_36/v12_36_20261022_existing_archive_reextraction_01"
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
RANKING = ROOT / "client/public/research/v12-36/latest-ranking.json"
TSETMC_MANIFEST = ROOT / "ranking_research/output/return_v12_35/official_tsetmc_20261022/manifest.json"
CALENDAR = ROOT / "score_v2_research/_cache/calendar.parquet"
PUBLIC = ROOT / "client/public/research/v12-36"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_mark(holding: dict, cash_toman: int, close_rial, date: str, realized_pnl_toman: int = 0) -> dict:
    """Apply a daily close mark with the shared whole-toman HALF_UP policy."""
    value = paper_account_store.rial_to_toman(Decimal(holding["shares"]) * Decimal(str(close_rial)))
    holding["last_price_rial"] = float(close_rial)
    holding["last_price_date"] = str(date)
    holding["market_value_toman"] = value
    holding["unrealized_pnl_toman"] = value - holding["cost_basis_toman"] - holding["fee_toman"]
    holding["price_status"] = "ارزش‌گذاری با آخرین close روزانهٔ TSETMC؛ شواهد صف/اجرا ندارد."
    return {"holdings_value_toman": value, "total_value_toman": cash_toman + value,
            "profit_loss_toman": realized_pnl_toman + holding["unrealized_pnl_toman"],
            "last_price_status": holding["price_status"]}


def _main_locked():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ranking", type=Path, default=ROOT / "client/public/research/v12-36/latest-ranking.json",
        help="Explicit P1 ranking JSON snapshot used for the candidate.")
    parser.add_argument("--tsetmc-manifest", type=Path, default=TSETMC_MANIFEST,
        help="Official TSETMC batch manifest with the candidate's daily bars and retrieval metadata.")
    parser.add_argument("--calendar", type=Path, default=CALENDAR,
        help="Official session calendar parquet, including sessions after the decision time.")
    parser.add_argument("--simulate-fill-daily-close-limited-queue", action="store_true",
        help="Explicitly approve a paper-only close-price simulation that cannot verify order-queue execution.")
    parser.add_argument("--fee-rate", type=float, help="Required with simulation; a proxy assumption, not a real tariff.")
    parser.add_argument("--lot-size", type=int, help="Required with simulation; shares per lot.")
    parser.add_argument("--expiry-sessions", type=int, help="Required with simulation; order expiry in official sessions.")
    parser.add_argument("--mark-to-market", action="store_true",
        help="Append a paper-only mark-to-market event from a new positive-volume daily close for the held identity.")
    parser.add_argument("--account", type=Path, default=ACCOUNT)
    parser.add_argument("--output-dir", type=Path, default=RUN)
    parser.add_argument("--public-output-dir", type=Path, default=PUBLIC)
    args = parser.parse_args()
    if args.simulate_fill_daily_close_limited_queue:
        raise SystemExit("LEGACY_SIMULATION_RETIRED: use apply_paper_fill.py --apply-fill with pinned execution_rules_v1_2_0")
    account_path = args.account.resolve()
    account = json.loads(account_path.read_text(encoding="utf-8"))
    ranking = json.loads(args.ranking.read_text(encoding="utf-8"))
    manifest = json.loads(args.tsetmc_manifest.read_text(encoding="utf-8"))
    created = pd.Timestamp(account["created_at_utc"])
    candidate = account["ranking"]["top_candidate"]
    now = datetime.now(timezone.utc).isoformat()
    record = next((x for x in manifest.get("records", []) if str(x.get("company_id")) == str(candidate["company_id"])), None) if candidate else None
    later_rows = [x for x in (record or {}).get("daily", []) if pd.Timestamp(x["date"]) > created.tz_convert(None).normalize()]
    try:
        calendar = pd.read_parquet(args.calendar)
        sessions = sorted(str(x)[:10] for x in calendar.trade_date if str(x)[:10] > created.strftime("%Y-%m-%d"))
        calendar_latest = str(calendar.trade_date.max())[:10]
    except Exception:
        sessions, calendar_latest = [], None
    first_session = sessions[0] if sessions else None
    first_quote = next((x for x in sorted(later_rows, key=lambda z: z["date"]) if first_session and str(x["date"]) == first_session and float(x.get("volume", 0)) > 0 and float(x.get("close_rial", 0)) > 0), None)
    proposed = {
        "rule_id": "paper-execution-rules/1.1.0-proposed",
        "execution_mode": "اجرای فرضی با محدودیت دادهٔ صف",
        "decision_time_utc": account["created_at_utc"],
        "earliest_eligible_session": first_session,
        "price_basis": "قیمت پایانی رسمی TSETMC در نخستین جلسهٔ مجاز، فقط پس از تصمیم؛ اجرای صف/قیمت قابل‌دسترس را اثبات نمی‌کند.",
        "quantity_formula": "floor(cash_toman / (close_rial/10 * (1 + fee_rate))); تعداد صحیح، lot موقت ۱ سهم.",
        "fee_rate": 0.005,
        "non_execution": "جلسهٔ مجاز یا قیمت/حجم پس از تصمیم ناموجود، نماد بدون معامله، دادهٔ هویتی ناسازگار، توقف یا رویداد شرکتی حل‌نشده => عدم اجرا و حفظ وجه نقد.",
        "expiry_rule": "پس از سه جلسهٔ رسمی واجد شرایط بدون fill مستند، ثبت عدم اجرا و بستن سفارش فرضی؛ فرض آزمایشی تا تأیید کاربر.",
        "approval_status": "نیازمند انتخاب/تأیید کاربر؛ هیچ سفارش یا fill این بررسی ایجاد نمی‌کند.",
    }
    if args.simulate_fill_daily_close_limited_queue:
        proposed.update({"approval_status": "برای همین فرمان توسط کاربر صریحاً تأیید شده؛ همچنان فرض آزمایشی و محدود به صف است.",
            "fee_rate": args.fee_rate, "lot_size": args.lot_size, "expiry_sessions": args.expiry_sessions})
    blockers = []
    if (ranking.get("evaluation_date") != account["ranking"]["evaluation_date"]
            or ranking.get("artifact_sha256") != account["ranking"].get("artifact_sha256")
            or not candidate or not any(x.get("company_id") == candidate.get("company_id") and x.get("methods", {}).get("P1", {}).get("rank") == 1 for x in ranking.get("rows", []))):
        blockers.append("رتبه‌بندی فعلی با snapshot نامزد حساب تطبیق ندارد؛ نامزد تا تأیید نسخهٔ صریح به‌روز نمی‌شود.")
    if not first_session:
        blockers.append(f"تقویم رسمی جلسه‌های پس از تصمیم موجود نیست؛ cache تقویم تا {calendar_latest or 'نامعلوم'} است.")
    if not later_rows:
        blockers.append("قیمت روزانهٔ نامزد پس از زمان ایجاد حساب در manifest محلی TSETMC وجود ندارد.")
    elif first_session and not first_quote:
        blockers.append(f"برای نخستین جلسهٔ مجاز {first_session} قیمت/حجم مثبت نامزد موجود نیست.")
    if proposed["approval_status"].startswith("نیازمند") and not args.simulate_fill_daily_close_limited_queue:
        blockers.append("قواعد اجرای مبتنی بر قیمت روزانه، lot، کارمزد و عدم اجرا هنوز فرض آزمایشی‌اند و باید یک‌جا تأیید یا اصلاح شوند.")
    simulated_fill = None
    if args.simulate_fill_daily_close_limited_queue:
        if args.fee_rate is None or not 0 <= args.fee_rate < 1 or not args.lot_size or args.lot_size < 1 or not args.expiry_sessions or args.expiry_sessions < 1:
            raise SystemExit("SIMULATION_REQUIRES_EXPLICIT_VALID_FEE_LOT_AND_EXPIRY")
        if account.get("execution_recorded") or account.get("order_created") or account["holdings"]:
            raise SystemExit("PAPER_ACCOUNT_ALREADY_HAS_AN_ORDER_OR_HOLDING; manual reconciliation required")
        if blockers or not first_quote or not candidate:
            raise SystemExit("PAPER_SIMULATION_BLOCKED: " + " | ".join(blockers or ["first eligible session has no positive close and volume"]))
        price_toman = Decimal(str(first_quote["close_rial"])) / Decimal(10)
        shares = math.floor(Decimal(account["cash_toman"]) /
            (price_toman * (Decimal(1) + Decimal(str(args.fee_rate))) * args.lot_size)) * args.lot_size
        gross = paper_account_store.money(shares * price_toman)
        fee = paper_account_store.money(gross * Decimal(str(args.fee_rate)))
        while shares > 0 and gross + fee > account["cash_toman"]:
            shares -= args.lot_size
            gross = paper_account_store.money(shares * price_toman)
            fee = paper_account_store.money(gross * Decimal(str(args.fee_rate)))
        if shares <= 0:
            raise SystemExit("PAPER_SIMULATION_CASH_BELOW_ONE_LOT_AFTER_FEE")
        total_cost = gross + fee
        account["cash_toman"] -= total_cost
        limited_status = "اجرای فرضی با محدودیت دادهٔ صف؛ قیمت پایانی روزانه صف/اولویت را اثبات نمی‌کند."
        holding = {"symbol": candidate["symbol"], "company_id": candidate["company_id"], "shares": shares,
            "purchase_price_rial": float(first_quote["close_rial"]), "purchase_price_toman": float(price_toman),
            "purchase_at_utc": f"{first_quote['date']} close (جلسهٔ رسمی بعد از تصمیم)", "cost_basis_toman": gross,
            "fee_toman": fee, "last_price_rial": float(first_quote["close_rial"]), "last_price_date": str(first_quote["date"]),
            "market_value_toman": gross, "unrealized_pnl_toman": -fee, "price_status": limited_status}
        account["holdings"] = [holding]
        account["execution_recorded"] = True
        account["order_created"] = True
        account["candidate_status"] = "اجرای فرضی با محدودیت دادهٔ صف؛ اجرای تأییدشده نیست"
        account["status"] = "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE"
        account["waiting_reason"] = limited_status
        account["assumptions_version"] = "paper-execution-rules/1.1.0-user-approved-limited-queue"
        account["accounting"] = {"holdings_value_toman": gross, "total_value_toman": account["cash_toman"] + gross,
            "profit_loss_toman": -fee, "last_price_status": limited_status}
        approval = [{"id": "fee", "label": "هزینه", "value": f"نرخ فرضی هر سمت {args.fee_rate}", "status": "فرض آزمایشی"},
            {"id": "lot", "label": "lot", "value": f"مضرب {args.lot_size} سهم", "status": "فرض آزمایشی"},
            {"id": "expiry", "label": "انقضا", "value": f"{args.expiry_sessions} جلسهٔ رسمی", "status": "فرض آزمایشی"},
            {"id": "price", "label": "قیمت اجرا", "value": "close نخستین جلسهٔ رسمی پس از تصمیم؛ محدودیت دادهٔ صف", "status": "فرض آزمایشی"}]
        account["assumptions"] = approval
        event_at = datetime.now(timezone.utc).isoformat()
        account["event_log"].extend([
            {"event_id": f"paper-order-{first_quote['date']}", "type": "PAPER_ORDER_SIMULATED", "at_utc": event_at,
             "reason": "فرمان صریح کاربر برای شبیه‌سازی close روزانه با محدودیت دادهٔ صف.",
             "details": f"P1 rank 1 {candidate['symbol']}; جلسه {first_quote['date']}; lot={args.lot_size}; fee assumption={args.fee_rate}; expiry={args.expiry_sessions} sessions."},
            {"event_id": f"paper-fill-{first_quote['date']}", "type": "SIMULATED_FILL_DAILY_CLOSE_LIMITED_QUEUE", "at_utc": event_at,
             "reason": "close و volume مثبت TSETMC در جلسهٔ پس از تصمیم؛ صف سفارش از دادهٔ روزانه قابل اثبات نیست.",
             "details": f"تعداد {shares}؛ قیمت {first_quote['close_rial']} ریال؛ بهای {gross} تومان؛ هزینهٔ فرضی {fee}؛ کسر کل {total_cost} تومان."}])
        paper_account_store.write_account_atomic(account_path, account)
        simulated_fill = {"symbol": candidate["symbol"], "session": str(first_quote["date"]), "shares": shares,
            "price_rial": float(first_quote["close_rial"]), "gross_toman": gross, "fee_toman": fee,
            "cash_after_toman": account["cash_toman"], "status": limited_status}
    if args.mark_to_market:
        if len(account["holdings"]) != 1:
            raise SystemExit("MARK_TO_MARKET_REQUIRES_EXACTLY_ONE_PAPER_HOLDING")
        held = account["holdings"][0]
        held_record = next((x for x in manifest.get("records", []) if str(x.get("company_id")) == str(held["company_id"])), None)
        marks = [x for x in (held_record or {}).get("daily", []) if str(x.get("date", "")) > str(held["last_price_date"]) and float(x.get("volume", 0)) > 0 and float(x.get("close_rial", 0)) > 0]
        if not marks:
            raise SystemExit("MARK_TO_MARKET_REQUIRES_NEW_POSITIVE_VOLUME_DAILY_CLOSE")
        mark = max(marks, key=lambda x: str(x["date"]))
        account["accounting"] = apply_mark(held, account["cash_toman"], mark["close_rial"],
            str(mark["date"]), int(account.get("realized_pnl_toman", 0)))
        event_at = datetime.now(timezone.utc).isoformat()
        account["event_log"].append({"event_id": f"paper-mark-{mark['date']}", "type": "PAPER_MARK_TO_MARKET", "at_utc": event_at,
            "reason": "درخواست به‌روزرسانی داخلی با close روزانهٔ تازه و حجم مثبت.",
            "details": f"{held['symbol']}؛ {held['shares']} سهم؛ close {mark['close_rial']} ریال در {mark['date']}؛ ارزش {held['market_value_toman']} تومان؛ سود/زیان تحقق‌نیافته {held['unrealized_pnl_toman']} تومان."})
        paper_account_store.write_account_atomic(account_path, account)
    status = {
        "schema_version": 1, "checked_at_utc": now, "account_id": account["account_id"],
        "ranking_dataset_id": ranking.get("dataset_id"), "ranking_evaluation_date": ranking.get("evaluation_date"),
        "ranking_status": ranking.get("status"), "p1_scored_count": ranking.get("scored_count", {}).get("P1"),
        "candidate": candidate, "first_eligible_session": first_session,
        "calendar_local_through": calendar_latest, "tsetmc_retrieved_at_utc": manifest.get("retrieved_at_utc"),
        "candidate_post_decision_daily_rows": len(later_rows), "first_session_quote": first_quote,
        "execution_rule_proposal": proposed, "execution_ready": not blockers, "simulated_fill": simulated_fill,
        "blockers": blockers, "required_data": [
            "تقویم رسمی TSETMC/O00 از 2026-10-22 تا جلسهٔ واجد شرایط بعدی، با تاریخ‌های جلسه و تعطیلی.",
            f"دادهٔ روزانهٔ رسمی TSETMC برای {candidate['symbol'] if candidate else 'نامزد'} از نخستین جلسهٔ پس از تصمیم: تاریخ، company_id/insCode، close، volume و raw response/hash/retrieved_at.",
            "برای اجرای تأییدشده: دادهٔ صف/معاملهٔ قابل انتساب به سفارش؛ در نبود آن فقط حالت محدودشدهٔ مبتنی بر close روزانه قابل انتخاب است.",
            "انتخاب کاربر دربارهٔ نرخ هزینهٔ آزمایشی، lot یک‌سهمی، قیمت پایانی به‌عنوان مبنای شبیه‌سازی و مهلت انقضای سفارش.",
        ],
        "cash_reconciliation": {"initial_toman": account["initial_capital_toman"], "cash_toman": account["cash_toman"],
            "holdings_count": len(account["holdings"]), "holdings_value_toman": account["accounting"]["holdings_value_toman"],
            "total_value_toman": account["accounting"]["total_value_toman"], "profit_loss_toman": account["accounting"]["profit_loss_toman"],
            "balanced": account["cash_toman"] + account["accounting"]["holdings_value_toman"] == account["accounting"]["total_value_toman"]},
        "source_sha256": {"account": sha(ACCOUNT), "ranking": sha(args.ranking), "tsetmc_manifest": sha(args.tsetmc_manifest), "calendar": sha(args.calendar)},
        "source_paths": {"ranking": str(args.ranking), "tsetmc_manifest": str(args.tsetmc_manifest), "calendar": str(args.calendar)},
        "official_ledger_touched": False,
    }
    run_dir, public_dir = args.output_dir.resolve(), args.public_output_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "paper-account-check.json").write_text(json.dumps(status, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (public_dir / "paper-account-check.json").write_text(json.dumps(status, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    log = run_dir / "paper-account-check-events.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "READINESS_CHECK", "at_utc": now, "execution_ready": status["execution_ready"],
            "cash_toman": account["cash_toman"], "holdings_count": len(account["holdings"]), "blockers": blockers,
            "source_sha256": status["source_sha256"]}, ensure_ascii=False)+"\n")
    print(json.dumps({"checked_at_utc": now, "execution_ready": status["execution_ready"], "simulated_fill": simulated_fill, "blockers": blockers,
        "first_eligible_session": first_session, "cash_reconciliation": status["cash_reconciliation"]}, ensure_ascii=False))


def main():
    import argparse as _argparse
    parser = _argparse.ArgumentParser(add_help=False)
    parser.add_argument("--account", type=Path, default=ACCOUNT)
    selected, _ = parser.parse_known_args()
    with paper_account_store.account_write_lock(selected.account.resolve()):
        return _main_locked()


if __name__ == "__main__":
    main()
