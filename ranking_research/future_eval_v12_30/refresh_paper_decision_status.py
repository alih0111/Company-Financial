"""Refresh the displayed status of the active paper decision from local evidence."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import argparse
import gzip
from pathlib import Path
import sys

try:
    from ranking_research import paper_calendar
except ImportError:  # direct-file execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ranking_research import paper_calendar

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
OUT = ROOT / "ranking_research/output/paper_v12_38_first_fill"
PUBLIC = ROOT / "client/public/research/v12-38"
LOCAL_CALENDAR = ROOT / "score_v2_research/_cache/calendar.parquet"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-calendar-manifest", type=Path,
                        help="Explicit official market-wide calendar manifest for this check")
    parser.add_argument("--calendar-provider", choices=("nscstart", "public"),
                        default="nscstart",
                        help="Calendar profile shown in this status check")
    parser.add_argument("--public-calendar-manifest", type=Path, default=None,
                        help="Pinned public-index calendar manifest (public provider)")
    parser.add_argument("--public-calendar-manifest-sha256", default=None)
    parser.add_argument("--calendar-policy", type=Path,
                        default=paper_calendar.DEFAULT_PUBLIC_POLICY_PATH)
    parser.add_argument("--execution-rules", type=Path,
                        default=ROOT / "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json",
                        help="Pinned execution rules file (read-only) for the shared policy binding check")
    parser.add_argument("--reference-now-utc", default=None,
                        help="Injected evaluation clock (ISO) for calendar freshness")
    parser.add_argument("--account", type=Path, default=ACCOUNT)
    parser.add_argument("--evidence-manifest", type=Path, default=None,
                        help="Explicit candidate evidence manifest (default: latest-manifest.json)")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--public-output-dir", type=Path, default=PUBLIC)
    parser.add_argument("--execution-attempt-status", default="not_attempted",
                        help="Status emitted by the locked paper-order evaluator")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    account_path = args.account
    out_dir, public_dir = args.output_dir, args.public_output_dir
    account = json.loads(account_path.read_text(encoding="utf-8"))
    try:
        rules_bytes = Path(args.execution_rules).read_bytes()
        rules_doc = json.loads(rules_bytes)
        paper_calendar.check_provider_contract(account=account,
                                               provider=args.calendar_provider,
                                               rules_bytes=rules_bytes,
                                               rules_doc=rules_doc)
        provider_contract_error = None
    except (OSError, ValueError, paper_calendar.CalendarRefusal) as exc:
        code = getattr(exc, "code", "PINNED_EXECUTION_RULES_UNREADABLE")
        provider_contract_error = f"{code}; {getattr(exc, 'detail', '')}".rstrip("; ")
    if args.evidence_manifest:
        evidence_path = args.evidence_manifest.resolve()
    else:
        latest_ref = json.loads((OUT / "latest-manifest.json").read_text(encoding="utf-8"))
        evidence_path = ROOT / latest_ref["manifest_path"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    decision = account.get("active_decision")
    order = account.get("paper_order")
    if not decision or not order:
        raise SystemExit("NO_PINNED_PAPER_DECISION_OR_ORDER")
    last_source = next(x for x in evidence["sources"] if x["key"] == "last_possible_session")
    candidate_source = next(x for x in evidence["sources"] if x["key"] == "candidate_daily")
    latest_possible = last_source.get("reported_last_possible_session", "")
    latest_possible_iso = f"{latest_possible[:4]}-{latest_possible[4:6]}-{latest_possible[6:8]}" if len(latest_possible) >= 8 else None
    candidate_dates = [
        f"{str(x['dEven'])[:4]}-{str(x['dEven'])[4:6]}-{str(x['dEven'])[6:8]}"
        for x in candidate_source.get("latest_positive_volume_rows", [])
        if len(str(x.get("dEven", ""))) == 8 and str(x["dEven"]) > decision["decision_local_date"].replace("-", "")
    ]
    if order.get("status") not in ("PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE", "EXPIRED_NO_FILL"):
        raise SystemExit("ORDER_STATE_UNRECOGNIZED; do not overwrite prior execution state")
    try:
        import pandas as pd
        calendar = pd.read_parquet(LOCAL_CALENDAR)
        local_calendar_through = str(pd.to_datetime(calendar["trade_date"]).max().date())
        local_calendar_rows = int(len(calendar))
    except Exception:
        local_calendar_through, local_calendar_rows = None, None

    session_calendar = None
    eligible_sessions = []
    calendar_error = None
    if args.session_calendar_manifest:
        calendar_path = args.session_calendar_manifest.resolve()
        try:
            session_calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
            raw_path = ROOT / session_calendar["raw_path"]
            raw = gzip.decompress(raw_path.read_bytes())
            if (session_calendar.get("source") != "TSETMC documented API MarketInfo/NSCStart"
                    or hashlib.sha256(raw).hexdigest() != session_calendar.get("raw_sha256")):
                raise ValueError("calendar source/hash mismatch")
            raw_doc = json.loads(raw)
            sessions = [{"DEven": str(x.get("DEven", "")), "NSCEnd": str(x.get("NSCEnd", ""))}
                        for x in raw_doc.get("Data", [])]
            if sessions != session_calendar.get("sessions"):
                raise ValueError("calendar manifest/raw mismatch")
            eligible_sessions = sorted(
                (x for x in sessions if x["DEven"] > decision["decision_local_date"].replace("-", "") and x["NSCEnd"] == "1"),
                key=lambda x: x["DEven"])
        except Exception as exc:
            session_calendar = None
            calendar_error = str(exc)

    no_post_decision = (
        f"آخرین جلسهٔ رسمیِ تکمیل‌شده‌ای که در بررسی {dt.datetime.now(dt.timezone.utc).isoformat()} مشاهده شد {latest_possible_iso or 'نامعلوم'} است؛ پس از تصمیم {decision['decided_at_utc']} UTC هنوز جلسهٔ کامل‌شدهٔ بعدی در شواهد رسمی ثبت نشده. از تاریخ آینده حدس نمی‌زنیم."
        if not latest_possible_iso or latest_possible_iso <= decision["decision_local_date"]
        else "یک جلسهٔ بعد از تاریخ تصمیم در LastPossibleDeven دیده می‌شود؛ تاریخ و قیمت همان جلسه هنوز باید با تقویم بازار و ردیف قیمت نامزد تطبیق داده شوند."
    )
    calendar_access = (
        f"تقویم محلی {LOCAL_CALENDAR.relative_to(ROOT).as_posix()} تا {local_calendar_through or 'نامعلوم'} ({local_calendar_rows if local_calendar_rows is not None else 'نامعلوم'} ردیف) است و پیش از تصمیم پایان می‌یابد. LastPossibleDeven فقط آخرین روز تکمیل‌شده را می‌دهد؛ GetInstrumentCalendar و GetClosingPriceDailyList فقط مشاهدات همان نماد غاذرند و به‌تنهایی تقویم کامل بازار نیستند. در کد پروژه، مسیر رسمی NSCStart برای فهرست جلسات بازار مستند شده و bearer token می‌خواهد؛ این یک مسیر است و نبود توکن آن را مانع همهٔ مسیرهای معتبر نمی‌کند. در فایل‌های محلی/مسیرهای عمومی رسمیِ بررسی‌شده، تقویم سراسری جدیدتری پیدا نشد."
    )
    if session_calendar:
        calendar_access = (f"تقویم رسمی بازار از NSCStart دریافت و hash پاسخ خام بررسی شد؛ دریافت {session_calendar['retrieved_at_utc']} UTC، "
                           f"{session_calendar['session_count']} جلسه. جلسه‌های رسمی پس از تصمیم: {len(eligible_sessions)}؛ "
                           f"اولین جلسهٔ واجد شرایط: {eligible_sessions[0]['DEven'] if eligible_sessions else 'هنوز در دادهٔ تقویم نیست'}. "
                           "تقویم نماد به‌تنهایی جایگزین این منبع بازار نیست.")
    elif calendar_error:
        calendar_access += f" بررسی manifest تقویم ارائه‌شده ناموفق بود: {calendar_error}."

    public_calendar_block = None
    provider_compatibility = {
        "state": "mismatch" if provider_contract_error else "compatible",
        "levels_checked": ("account", "decision", "order", "rules"),
        "mismatch_detail": provider_contract_error,
    }
    if args.calendar_provider == "public":
        if not args.public_calendar_manifest or not args.public_calendar_manifest_sha256:
            raise SystemExit("PUBLIC_CALENDAR_MANIFEST_AND_SHA256_REQUIRED")
        if args.reference_now_utc:
            now_utc = dt.datetime.fromisoformat(args.reference_now_utc)
            now_utc = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=dt.timezone.utc)
        else:
            now_utc = dt.datetime.now(dt.timezone.utc)
        policy = paper_calendar.load_policy(args.calendar_policy)
        policy_sha = sha(args.calendar_policy)
        # Shared four-level binding check. Data quality and account
        # compatibility are reported separately: healthy public data can be
        # high quality and still not consumable by this account, and a
        # mismatched account never gets no_new_session/ready=true as readiness.
        compatibility = dict(provider_compatibility)
        if compatibility["state"] == "compatible":
            try:
                paper_calendar.check_public_policy_binding(
                    account=account, rules_doc=rules_doc,
                    policy=policy, policy_sha256=policy_sha)
            except paper_calendar.CalendarRefusal as exc:
                compatibility = {"state": "mismatch",
                                 "levels_checked": ("account", "decision", "order", "rules"),
                                 "mismatch_detail": f"{exc.code}; {exc.detail}" if exc.detail else exc.code}
        answer = None
        resolve_note = None
        try:
            answer = paper_calendar.resolve_public_calendar(
                manifest_path=args.public_calendar_manifest.resolve(),
                expected_manifest_sha256=args.public_calendar_manifest_sha256,
                policy=policy, policy_sha256=policy_sha,
                candidate={"symbol": order["symbol"],
                           "ins_code": str(evidence.get("ins_code", ""))},
                decision_local_date=decision["decision_local_date"],
                decision_at_utc=dt.datetime.fromisoformat(decision["decided_at_utc"]),
                now_utc=now_utc, consumption_mode="live-preview")
        except paper_calendar.CalendarRefusal as exc:
            resolve_note = f"{exc.code}; {exc.detail}" if exc.detail else exc.code
        if answer is None:
            public_calendar_block = {
                "provider": "public-index",
                "policy": {"id": policy["policy_id"], "version": policy["version"],
                           "sha256": policy_sha},
                "account_compatibility": compatibility,
                "quality": None, "quality_recomputed_from_raw": False,
                "resolve_refusal": resolve_note,
                "freshness": {"state": "NOT_RESOLVED"},
                "calendar_ready": False,
                "blocking_reasons": (["CALENDAR_POLICY_MISMATCH"] if compatibility["state"] == "mismatch"
                                     else []) + [resolve_note],
                "completion": None,
                "sessions_after_decision": {"state": "NOT_RESOLVED", "count": None,
                                            "first_session": None, "count_is_unknown": True},
                "display_label_fa": policy["display_label_fa"],
                "candidate_trade_evidence": None,
            }
        else:
            sessions = answer["sessions_after_decision"]
            cand = answer["candidate"]
            archive_end = None
            by_symbol = ((answer["evaluation"].get("stock_cross_check") or {}).get("by_symbol") or {})
            if order["symbol"] in by_symbol and by_symbol[order["symbol"]]:
                archive_end = max(by_symbol[order["symbol"]])
            if cand["trade_status"] != "checked":
                trade_state = "evidence_gap_candidate_not_covered"
            elif (sessions["first_session"] is not None and archive_end is not None
                  and archive_end < sessions["first_session"]):
                trade_state = "evidence_gap_archive_ends_before_target_day"
            else:
                trade_state = "candidate_data_covers_target_day"
            answer_blocking = list(answer["readiness"]["blocking_reasons"])
            public_calendar_block = {
                "provider": "public-index",
                "policy": {"id": answer["policy"]["id"], "version": answer["policy"]["version"],
                           "sha256": answer["policy"]["sha256"]},
                "manifest": answer["manifest"],
                "account_compatibility": compatibility,
                "quality": answer["quality"],
                "quality_recomputed_from_raw": True,
                "freshness": {"state": answer["freshness"]["state"],
                              "rules": answer["freshness"]["rules"]},
                "calendar_ready": (answer["readiness"]["calendar_ready"]
                                   and compatibility["state"] == "compatible"),
                "blocking_reasons": (["CALENDAR_POLICY_MISMATCH"] if compatibility["state"] == "mismatch"
                                     else []) + answer_blocking,
                "completion": answer["completion"],
                "sessions_after_decision": {"state": sessions["state"], "count": sessions["count"],
                                            "first_session": sessions["first_session"],
                                            "count_is_unknown": sessions["count"] is None},
                "display_label_fa": answer["display_label_fa"],
                "candidate_trade_evidence": {
                    "trade_status": cand["trade_status"],
                    "no_positive_trade_sessions": cand["no_positive_trade_sessions"],
                    "archive_end": archive_end,
                    "state": trade_state,
                    "note": ("zero observed new sessions and an unknown session count are "
                             "different states; a candidate no-trade claim requires candidate "
                             "data covering that day — an archive ending before the target day "
                             "is an evidence gap, never a suspension/no-trade verdict"),
                },
            }
    no_session_data = not latest_possible_iso or latest_possible_iso <= decision["decision_local_date"]
    first_eligible_session = eligible_sessions[0]["DEven"] if eligible_sessions else None
    public_session_count = None
    if public_calendar_block:
        # one uniform answer source: the same first-session/count the fill and
        # cycle paths consume; zero observed sessions is never conflated with
        # an unknown count
        first_eligible_session = public_calendar_block["sessions_after_decision"]["first_session"]
        public_session_count = public_calendar_block["sessions_after_decision"]["count"]
    exact_first_rows = [x for x in candidate_source.get("latest_positive_volume_rows", [])
                        if first_eligible_session and str(x.get("dEven", "")) == first_eligible_session]
    no_post_decision = (
        f"آخرین جلسهٔ کامل اعلام‌شده {latest_possible_iso or 'نامعلوم'} است؛ پس از تاریخ تصمیم {decision['decision_local_date']} هنوز جلسهٔ کامل‌شده‌ای در این دریافت دیده نمی‌شود."
        if no_session_data else
        (f"LastPossibleDeven از جلسهٔ کامل {latest_possible_iso} خبر می‌دهد، اما تقویم بازار معتبر برای تعیین اولین جلسه و تطبیق دقیق سفارش در دسترس نیست."
         if not session_calendar else
        (f"اولین جلسهٔ مجاز {first_eligible_session} است، اما قیمت/حجم مثبت همان جلسه هنوز در دریافت نامزد وجود ندارد؛ جلسهٔ دیگری جایگزین نمی‌شود."
         if first_eligible_session and not exact_first_rows else
         ("قیمت و حجم مثبت جلسهٔ نخست در شواهد دریافت‌شده موجود است؛ گیت‌های هویت، رویداد شرکتی و انقضا باید با فرمان اجرای قفل‌شده بررسی شوند."
          if exact_first_rows else
          f"آخرین جلسهٔ رسمیِ تکمیل‌شده‌ای که در بررسی {dt.datetime.now(dt.timezone.utc).isoformat()} مشاهده شد {latest_possible_iso or 'نامعلوم'} است؛ جلسهٔ دقیق اجرا باید با تقویم کامل و ردیف قیمت تطبیق داده شود.")))
    )
    barriers = [
        {"id": "post_decision_market_session", "state": "no_session_observed" if no_session_data else ("calendar_unverified" if not session_calendar else ("quote_missing" if not exact_first_rows else "evidence_available_pending_gates")), "title": "هنوز دادهٔ جلسهٔ پس از تصمیم موجود نیست" if no_session_data else ("جلسهٔ پس از تصمیم گزارش شده؛ تطبیق تقویم بازار ناقص است" if not session_calendar else ("قیمت جلسهٔ نخست هنوز موجود نیست" if not exact_first_rows else "دادهٔ جلسهٔ نخست موجود است؛ گیت اجرای سفارش باقی است")), "details": no_post_decision},
        {"id": "authoritative_market_calendar", "state": "verified" if session_calendar else "incomplete", "title": "دسترسی به منبع معتبر تقویم ناقص است" if not session_calendar else "تقویم رسمی بازار دریافت و اعتبارسنجی شد", "details": calendar_access},
    ]
    if provider_contract_error:
        barriers.append({"id": "calendar_provider_contract", "state": "blocked",
                         "title": "انتخاب provider با قرارداد pinشده سازگار نیست",
                         "details": provider_contract_error})
    if public_calendar_block:
        ready = public_calendar_block["calendar_ready"]
        count = public_calendar_block["sessions_after_decision"]["count"]
        trade = public_calendar_block["candidate_trade_evidence"]
        compat = public_calendar_block["account_compatibility"]
        if compat["state"] == "mismatch":
            # account compatibility and data quality are separate states: the
            # data may be healthy, but this account/rules/order are not bound
            # to the public policy, so it is never reported as ready
            barrier_state = "account_profile_mismatch"
            barrier_title = "این حساب/سفارش/قواعد به سیاست تقویم عمومی مقید نشده‌اند"
            barrier_details = ("کیفیت دادهٔ تقویم عمومی جداگانه گزارش می‌شود، اما مصرف آن "
                               "برای این حساب مجاز نیست: " + compat["mismatch_detail"]
                               + "؛ مهاجرت/فعال‌سازی حساب، TF-03 است و در بررسی وضعیت "
                               "انجام نمی‌شود.")
        elif not ready:
            barrier_state = "blocked"
            barrier_title = "تقویم عمومی برای این مصرف آماده نیست"
            barrier_details = ("شواهد تقویم عمومی پین و بازمحاسبه شد، اما این سیاست اجازهٔ مصرف نمی‌دهد: "
                               + "، ".join(public_calendar_block["blocking_reasons"]))
        elif count is None:
            barrier_state = "unknown_session_count"
            barrier_title = "شمارش جلسهٔ پس از تصمیم نامعلوم است"
            barrier_details = (f"وضعیت {public_calendar_block['sessions_after_decision']['state']}: "
                               "شمارش نامعلوم است، نه صفر؛ اجرا متوقف می‌ماند.")
        elif count == 0:
            barrier_state = "no_new_session"
            barrier_title = "هنوز جلسهٔ پذیرفته‌شدهٔ جدیدی مشاهده نشده است"
            barrier_details = ("دریافت موفق بوده و آخرین جلسهٔ تکمیل‌شده همان مانده است؛ صفر جلسهٔ "
                               "مشاهده‌شدهٔ جدید با «شمارش نامعلوم» یکسان نیست.")
        else:
            barrier_state = "first_session_available"
            barrier_title = "نخستین جلسهٔ پذیرفته‌شدهٔ تقویم عمومی موجود است"
            barrier_details = (f"نخستین جلسهٔ قابل استفاده {public_calendar_block['sessions_after_decision']['first_session']} "
                               f"با {count} جلسهٔ پذیرفته‌شدهٔ پس از تصمیم؛ "
                               + public_calendar_block["display_label_fa"])
        if trade is not None:
            barrier_details += (f" شاهد معاملهٔ نامزد: {trade['state']}"
                                + (f" (پایان آرشیو {trade['archive_end']})" if trade["archive_end"] else "")
                                + ".")
        barriers.append({"id": "public_calendar", "state": barrier_state,
                         "title": barrier_title, "details": barrier_details,
                         "display_label_fa": public_calendar_block["display_label_fa"]})
    blockers = [no_post_decision, calendar_access]
    if provider_contract_error:
        blockers.append(provider_contract_error)
    if public_calendar_block:
        blockers.append(barriers[-1]["details"])
    if args.execution_attempt_status == "LATE_FILL_TIMING_AMBIGUOUS":
        details = "شواهد قیمت نخستین جلسه فقط پس از پایان سومین جلسهٔ مهلت سفارش در دسترس دیده شد. زمان ثبت رویداد پیش از انقضا قابل اثبات نیست؛ fill و انقضا هر دو متوقف‌اند تا ابهام طبق قواعد روشن شود."
        barriers.append({"id": "late_fill_timing", "state": "ambiguous", "title": "زمان ثبت اجرای دیرهنگام مبهم است", "details": details})
        blockers.append(details)
    if not candidate_dates:
        blockers.append("قیمت/حجم مثبت نامزد غاذر پس از تصمیم در آخرین دریافت موجود نیست؛ دریافت تازه پس از شکل‌گیری جلسه لازم است. فقط قیمت پایانی همان نخستین جلسهٔ واجد شرایط قابل استفاده است.")
    else:
        blockers.append("قیمت همان نخستین جلسهٔ مجاز باید با تقویم بازار تأیید شود؛ جلسهٔ دیرتر جایگزین آن نمی‌شود.")
    status = {
        "schema_version": 3, "checked_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "account_id": account["account_id"], "account_created_at_utc": account["created_at_utc"],
        "decision": decision, "order": order,
        "execution_attempt_status": args.execution_attempt_status,
        "execution_ready": bool(not provider_contract_error and session_calendar and exact_first_rows and args.execution_attempt_status != "LATE_FILL_TIMING_AMBIGUOUS"), "fill_recorded": bool(account.get("execution_recorded")),
        "latest_official_completed_session": latest_possible_iso,
        "candidate_latest_positive_price_date": (lambda v: f"{str(v)[:4]}-{str(v)[4:6]}-{str(v)[6:8]}" if len(str(v)) == 8 else None)(candidate_source.get("latest_positive_volume_rows", [{}])[0].get("dEven", "")),
        "candidate_post_decision_quotes": candidate_dates,
        "candidate_post_decision_daily_rows": len(exact_first_rows),
        "first_eligible_session": first_eligible_session,
        "calendar_retrieved_at_utc": session_calendar.get("retrieved_at_utc") if session_calendar else None,
        "eligible_sessions_after_decision": (public_session_count if public_calendar_block
                                             else len(eligible_sessions)),
        "public_calendar": public_calendar_block,
        "calendar_provider_compatibility": provider_compatibility,
        "barriers": barriers,
        "calendar_sources_checked": [
            {"source": "TSETMC LastPossibleDeven", "scope": "latest completed session only; not future session schedule", "retrieved_at_utc": last_source.get("retrieved_at_utc"), "url": last_source.get("url")},
            {"source": "TSETMC GetInstrumentCalendar / GetClosingPriceDailyList for غاذر", "scope": "symbol observations only; not a market-wide calendar", "retrieved_at_utc": candidate_source.get("retrieved_at_utc"), "url": candidate_source.get("url")},
            {"source": str(LOCAL_CALENDAR.relative_to(ROOT)).replace("\\", "/"), "scope": "local market session rows", "through": local_calendar_through, "row_count": local_calendar_rows, "usable_for_post_decision": bool(local_calendar_through and local_calendar_through > decision["decision_local_date"])},
            {"source": "TSETMC documented API MarketInfo/NSCStart", "scope": "market session list with DEven/NSCEnd; documented route uses bearer authorization", "available_in_current_run": bool(session_calendar), "retrieved_at_utc": session_calendar.get("retrieved_at_utc") if session_calendar else None, "note": "one official route; does not establish that all other official routes require a token"},
        ],
        "blockers": blockers,
        "required_data": [
            "یک تقویم بازار رسمی و فقط‌خواندنی که جلسه‌ها را مستقل از نماد فهرست کند و تاریخ اولین جلسه پس از تصمیم را پوشش دهد؛ NSCStart یکی از مسیرهای رسمی است و در مستندات برای آن bearer token ذکر شده است. اگر این مسیر انتخاب شد، توکن را فقط در متغیر محیطی موقت PowerShell بگذارید؛ وارد فایل عمومی، گزارش، کد یا Git نکنید.",
            "پس از ثبت جلسهٔ واجد شرایط، دریافت تازهٔ قیمت روزانهٔ غاذر برای همان تاریخ از GetClosingPriceDailyList؛ پاسخ خام، URL، زمان و hash در مسیر نسخه‌دار.",
            "فرمان واحد بررسی دستی: powershell -ExecutionPolicy Bypass -File ranking_research\\future_eval_v12_30\\check_paper_order.ps1؛ توکن فقط‌خواندنی را در SecureString prompt وارد کنید. اسکریپت تقویم و قیمت را می‌گیرد، گیت‌ها را بررسی و فقط در صورت احراز شروط همان سفارش را یک‌بار ثبت می‌کند.",
        ],
        "source_evidence": [{k: s.get(k) for k in ("key", "url", "http_status", "http_date", "retrieved_at_utc", "raw_path", "raw_sha256", "reported_last_possible_session", "latest_source_dates", "latest_positive_volume_rows") if k in s} for s in evidence["sources"]],
        "cash_reconciliation": {
            "initial_toman": account["initial_capital_toman"], "cash_toman": account["cash_toman"],
            "holdings_count": len(account["holdings"]), "holdings_value_toman": account["accounting"]["holdings_value_toman"],
            "total_value_toman": account["cash_toman"] + account["accounting"]["holdings_value_toman"],
            "profit_loss_toman": account["accounting"]["profit_loss_toman"],
            "balanced": account["cash_toman"] + account["accounting"]["holdings_value_toman"] == account["accounting"]["total_value_toman"],
            "pnl_basis": "از fill ثبت‌شده؛ تا پیش از fill صفر",
        },
        "source_sha256": {"account": sha(account_path), "ranking": sha(ROOT / "client/public/research/v12-36/latest-ranking.json"), "evidence_manifest": sha(evidence_path), "local_calendar": sha(LOCAL_CALENDAR)},
        "official_ledger_touched": False,
    }
    public_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (public_dir / "paper-account-check.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "paper-account-check.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (public_dir / "paper-decision-record.json").write_text(json.dumps({"decision": decision, "order": order}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# وضعیت سفارش آزمایشی V12.38",
        "",
        f"آخرین بررسی UTC: `{status['checked_at_utc']}`",
        f"حساب: `{account['account_id']}` · تصمیم: `{decision['decision_id']}` · سفارش: `{order['order_id']}`",
        f"تصمیم اصلی حفظ شده: `{decision['decided_at_utc']}` · وضعیت اجرا: `{order['status']}` · fill ثبت‌شده: {'بله' if status['fill_recorded'] else 'خیر'}",
        "",
        "## دو مانع مستقل",
        "",
        f"1. **{barriers[0]['title']}** — {barriers[0]['details']}",
        f"2. **{barriers[1]['title']}** — {barriers[1]['details']}",
        "",
        no_post_decision,
        "",
        "## مسیرهای تقویم بررسی‌شده",
        "",
        "- LastPossibleDeven رسمی: فقط آخرین جلسهٔ کامل‌شده.",
        "- GetInstrumentCalendar و GetClosingPriceDailyList غاذر: تاریخچهٔ یک نماد، نه تقویم کامل بازار.",
        f"- فایل تقویم محلی: تا `{local_calendar_through or 'نامعلوم'}`؛ پس از تصمیم را نمی‌پوشاند.",
        "- مستند رسمی TSETMC برای NSCStart: فهرست روزهای باز بازار را تعریف می‌کند و نمونهٔ درخواستش bearer token دارد. این یکی از مسیرهاست، نه اثبات اینکه همهٔ مسیرهای رسمی به توکن نیاز دارند.",
        "",
        "اگر NSCStart انتخاب شد، در PowerShell این روند را در همان نشست اجرا کنید: `$s=Read-Host 'TSETMC read-only token' -AsSecureString; $p=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s); try { $env:TSETMC_READONLY_BEARER_TOKEN=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($p); .venv\\Scripts\\python.exe ranking_research\\future_eval_v12_30\\acquire_tsetmc_open_sessions.py } finally { Remove-Item Env:TSETMC_READONLY_BEARER_TOKEN -ErrorAction SilentlyContinue; [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($p); $s.Dispose() }`. توکن وارد history، فایل، فرانت، گزارش یا Git نمی‌شود؛ اسکریپت آن را چاپ یا ذخیره نمی‌کند.",
        "",
        "فرمان واحد بررسی دستی از ریشهٔ پروژه: `powershell -NoProfile -ExecutionPolicy Bypass -File ranking_research\\future_eval_v12_30\\check_paper_order.ps1`. ورود توکن فقط‌خواندنی در SecureString prompt است. دریافت و بررسی دستی است؛ پایش خودکار فعال نیست.",
        "",
        f"آشتی نقد/دارایی: {status['cash_reconciliation']['cash_toman']} + {status['cash_reconciliation']['holdings_value_toman']} = {status['cash_reconciliation']['total_value_toman']} تومان؛ برابر بودن: `{status['cash_reconciliation']['balanced']}`. دفتر رسمی دست‌نخورده است.",
    ]
    if public_calendar_block:
        report += [
            "",
            "## تقویم عمومی (پروفایل آزمایشی)",
            "",
            f"- {barriers[-1]['title']} — {barriers[-1]['details']}",
            f"- سازگاری حساب با این سیاست: `{public_calendar_block['account_compatibility']['state']}`"
            + (f" ({public_calendar_block['account_compatibility']['mismatch_detail']})"
               if public_calendar_block['account_compatibility']['mismatch_detail'] else "")
            + ".",
            f"- کیفیت بازمحاسبه‌شده از raw: `{public_calendar_block['quality']}`؛ تازگی: `{public_calendar_block['freshness']['state']}`.",
            f"- برچسب نمایش: {public_calendar_block['display_label_fa']}",
            "",
            "- مسیر عمومی بدون توکن: دو شاخص بورس تهران + LastPossibleDeven از endpointهای عمومی؛ پایان جلسه فرض ثبت‌شدهٔ سیاست است، نه گواه رسمی.",
        ]
    (out_dir / "execution_status.fa.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    try:
        evidence_rel = str(evidence_path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        evidence_rel = str(evidence_path)
    print(json.dumps({"checked_at_utc": status["checked_at_utc"], "decision_at_utc": decision["decided_at_utc"],
                      "order_id": order["order_id"], "fill_recorded": False, "evidence_manifest": evidence_rel, "barriers": barriers,
                      "cash_reconciliation": status["cash_reconciliation"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
