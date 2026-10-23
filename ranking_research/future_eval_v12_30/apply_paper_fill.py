"""Preview or apply the single approved close-only paper fill, with explicit source inputs."""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
RULES = ROOT / "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expiry_outcome(session_count: int, expiry_sessions: int, first_session_fill_eligible: bool) -> str:
    if session_count < expiry_sessions:
        return "continue"
    return "late_fill_timing_ambiguous" if first_session_fill_eligible else "expire"


def calendar_covers_order_window(sessions: list[dict], decision_day: str) -> bool:
    dates = [str(row.get("DEven", "")) for row in sessions]
    return (len(dates) == 20 and all(len(day) == 8 and day.isdigit() for day in dates)
            and len(set(dates)) == 20 and min(dates) <= decision_day)


def write_account_atomic(account: dict) -> None:
    """Commit cash, holdings, order state and its event as one file replacement."""
    temporary = ACCOUNT.with_suffix(ACCOUNT.suffix + ".tmp")
    payload = json.dumps(account, ensure_ascii=False, indent=2) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, ACCOUNT)


def record_order_observation(account: dict, order: dict, first_day: str,
                             sessions_count: int, latest_session: str) -> None:
    """Append one idempotent evidence event and persist order-window progress."""
    order["designated_execution_session"] = order.get("designated_execution_session") or first_day
    order["eligible_session_count_observed"] = max(
        int(order.get("eligible_session_count_observed", 0)), sessions_count)
    event_id = f"paper-order-observation-{order['order_id']}-{latest_session}"
    if not any(x.get("event_id") == event_id for x in account["event_log"]):
        account["event_log"].append({"event_id": event_id, "type": "PAPER_ORDER_SESSION_EVIDENCE_OBSERVED",
            "at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "reason": "تقویم رسمی، پیشرفت پنجرهٔ همان سفارش را بدون تغییر نقد یا دارایی تأیید کرد.",
            "details": f"order={order['order_id']}; designated_session={first_day}; observed_sessions={sessions_count}; latest_session={latest_session}."})
        account["paper_order"] = order
        write_account_atomic(account)


@contextmanager
def account_write_lock():
    """A named OS mutex excludes concurrent writers and is crash-released."""
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, "Local\\CompanyFinancialPaperAccount")
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        result = kernel.WaitForSingleObject(handle, 0)
        if result not in (0x00000000, 0x00000080):  # acquired, or abandoned by a crashed writer
            kernel.CloseHandle(handle)
            raise SystemExit("PAPER_ACCOUNT_LOCKED; no account event was written")
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
    else:
        import fcntl
        lock_path = ROOT / ".runtime/paper-account.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SystemExit("PAPER_ACCOUNT_LOCKED; no account event was written") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_locked() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-calendar-manifest", type=Path, required=True,
                        help="A saved manifest/raw response from the documented official NSCStart endpoint.")
    parser.add_argument("--evidence-manifest", type=Path, required=True,
                        help="Explicit versioned candidate evidence manifest from acquire_paper_candidate_evidence.py.")
    parser.add_argument("--apply-fill", action="store_true", help="Apply a validated fill once to the paper account.")
    args = parser.parse_args()
    account = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    decision, order = account["active_decision"], account["paper_order"]
    rules_bytes = RULES.read_bytes()
    if hashlib.sha256(rules_bytes).hexdigest() != decision["execution_rules"]["sha256"]:
        raise SystemExit("PINNED_EXECUTION_RULES_HASH_MISMATCH")
    if order.get("fill_event_id") or account.get("holdings"):
        raise SystemExit("ORDER_ALREADY_FILLED_OR_HOLDING_EXISTS; duplicate debit prevented")
    if order.get("status") not in ("PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "EXPIRED_NO_FILL"):
        raise SystemExit(f"ORDER_NOT_FILLABLE:{order.get('status')}")
    if order.get("status") == "EXPIRED_NO_FILL":
        print(json.dumps({"status": "EXPIRED_NO_FILL", "fill_applied": False,
                          "reason": "Order already has a terminal expiry event; no later-session fill is allowed."}, ensure_ascii=False))
        return
    session_path = args.session_calendar_manifest.resolve()
    evidence_path = args.evidence_manifest.resolve()
    sessions_doc = json.loads(session_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if sessions_doc.get("source") != "TSETMC documented API MarketInfo/NSCStart" or not sessions_doc.get("raw_sha256"):
        raise SystemExit("OFFICIAL_SESSION_CALENDAR_SOURCE_OR_HASH_MISSING")
    if sessions_doc.get("retrieved_at_utc", "") < decision["decided_at_utc"]:
        raise SystemExit("SESSION_CALENDAR_WAS_RETRIEVED_BEFORE_DECISION")
    session_raw_path = ROOT / sessions_doc.get("raw_path", "")
    if not session_raw_path.is_file() or hashlib.sha256(gzip.decompress(session_raw_path.read_bytes())).hexdigest() != sessions_doc["raw_sha256"]:
        raise SystemExit("OFFICIAL_SESSION_CALENDAR_RAW_HASH_MISMATCH")
    session_raw = json.loads(gzip.decompress(session_raw_path.read_bytes()))
    normalized_session_rows = [{"DEven": str(x["DEven"]), "HEven": x.get("HEven"), "NSCEnd": str(x.get("NSCEnd", ""))} for x in session_raw.get("Data", [])]
    if normalized_session_rows != sessions_doc.get("sessions"):
        raise SystemExit("OFFICIAL_SESSION_CALENDAR_MANIFEST_RAW_MISMATCH")
    decision_day = decision["decision_local_date"].replace("-", "")
    if not calendar_covers_order_window(normalized_session_rows, decision_day):
        raise SystemExit("CALENDAR_WINDOW_DOES_NOT_COVER_DECISION_OR_FULL_20_SESSION_WINDOW")
    source_map = {x["key"]: x for x in evidence.get("sources", [])}
    for key in ("candidate_daily", "candidate_share_changes", "last_possible_session"):
        if key not in source_map or not source_map[key].get("raw_sha256"):
            raise SystemExit(f"REQUIRED_OFFICIAL_SOURCE_MISSING:{key}")
        if source_map[key].get("retrieved_at_utc", "") < decision["decided_at_utc"]:
            raise SystemExit(f"OFFICIAL_SOURCE_PREDATES_DECISION:{key}")
        raw_path = ROOT / source_map[key].get("raw_path", "")
        if not raw_path.is_file() or hashlib.sha256(gzip.decompress(raw_path.read_bytes())).hexdigest() != source_map[key]["raw_sha256"]:
            raise SystemExit(f"OFFICIAL_RAW_HASH_MISMATCH:{key}")
    if (evidence.get("candidate", {}).get("company_id") != order["company_id"]
            or str(evidence.get("ins_code", "")) != str(source_map["candidate_daily"].get("url", "").rsplit("/", 2)[-2])):
        raise SystemExit("CANDIDATE_IDENTITY_OR_INSCODE_MISMATCH")
    rows = [x for x in sessions_doc.get("sessions", [])
            if str(x.get("DEven", "")) > decision["decision_local_date"].replace("-", "") and str(x.get("NSCEnd")) == "1"]
    rows.sort(key=lambda x: str(x["DEven"]))
    if not rows:
        raise SystemExit("NO_COMPLETED_OFFICIAL_SESSION_AFTER_DECISION")
    first = rows[0]
    first_day = str(first["DEven"])
    sessions_count = len(rows)
    order["eligible_session_count_observed"] = max(order.get("eligible_session_count_observed", 0), sessions_count)
    if order.get("designated_execution_session") and order["designated_execution_session"] != first_day:
        raise SystemExit("FIRST_ELIGIBLE_SESSION_CONFLICT_WITH_PINNED_ORDER")
    order["designated_execution_session"] = first_day
    daily_entry = source_map["candidate_daily"]
    daily_raw_path = ROOT / daily_entry["raw_path"]
    daily_doc = json.loads(gzip.decompress(daily_raw_path.read_bytes()))
    ins_code = str(evidence.get("ins_code", ""))
    day_rows = [x for x in daily_doc.get("closingPriceDaily", [])
                if str(x.get("dEven", "")) == first_day and str(x.get("insCode", "")) == ins_code]
    if len(day_rows) > 1:
        raise SystemExit("DUPLICATE_CANDIDATE_BAR_FOR_FIRST_SESSION")
    if source_map["last_possible_session"].get("reported_last_possible_session", "")[:8] < first_day:
        raise SystemExit("SESSION_NOT_CONFIRMED_BY_LAST_POSSIBLE_SESSION_ENDPOINT")
    if day_rows:
        bar = day_rows[0]
        close_rial, volume = float(bar.get("pClosing") or 0), float(bar.get("qTotTran5J") or 0)
    else:
        close_rial, volume = 0.0, 0.0
    share_doc = json.loads(gzip.decompress((ROOT / source_map["candidate_share_changes"]["raw_path"]).read_bytes()))
    share_changes = share_doc.get("instrumentShareChange")
    if not isinstance(share_changes, list) or any(str(x.get("insCode", "")) != ins_code for x in share_changes):
        raise SystemExit("SHARE_CHANGE_LINEAGE_INVALID")
    decision_day = decision["decision_local_date"].replace("-", "")
    corporate_action = any(decision_day < str(x.get("dEven", ""))[:8] <= first_day
                           and float(x.get("numberOfShareNew", 0) or 0) != float(x.get("numberOfShareOld", 0) or 0)
                           for x in share_changes)
    price_toman = close_rial / 10 if close_rial > 0 else 0
    shares = math.floor(account["cash_toman"] / (price_toman * 1.005)) if price_toman > 0 else 0
    gross = int(round(shares * price_toman))
    fee = int(round(gross * 0.005))
    while shares > 0 and gross + fee > account["cash_toman"]:
        shares -= 1
        gross = int(round(shares * price_toman))
        fee = int(round(gross * 0.005))
    eligibility_reason = (
        "FIRST_SESSION_BAR_MISSING_OR_NO_TRADE" if close_rial <= 0 or volume <= 0 else
        "CORPORATE_ACTION_REQUIRES_MANUAL_RESOLUTION" if corporate_action else
        "CASH_BELOW_ONE_SHARE_PLUS_ASSUMED_FEE" if shares <= 0 else None
    )
    expiry = expiry_outcome(sessions_count, int(order["expires_after_official_sessions"]), eligibility_reason is None)
    if expiry == "late_fill_timing_ambiguous":
        ambiguity_id = f"paper-late-fill-ambiguity-{order['order_id']}-{sha(evidence_path)}"
        if not any(x.get("event_id") == ambiguity_id for x in account["event_log"]):
            account["event_log"].append({"event_id": ambiguity_id, "type": "PAPER_LATE_FILL_TIMING_AMBIGUOUS",
                "at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "reason": "قیمت نخستین جلسه دیده شد، اما ثبت پیش از لحظهٔ انقضا اثبات‌پذیر نیست؛ fill و انقضا متوقف‌اند.",
                "details": f"order={order['order_id']}; designated_session={first_day}; sessions_observed={sessions_count}; evidence_sha256={sha(evidence_path)}."})
            order["waiting_reason"] = "شواهد قیمت جلسهٔ نخست دیررس است؛ زمان ثبت نسبت به انقضا اثبات نشده و fill/انقضا انجام نشد."
            account["paper_order"] = order
            write_account_atomic(account)
        print(json.dumps({"status": "LATE_FILL_TIMING_AMBIGUOUS", "sessions_after_decision": sessions_count,
                          "first_session": first_day, "candidate_bar": bool(day_rows), "fill_applied": False,
                          "expired": False, "reason": "Evidence for the designated first-session fill is present only after the third-session expiry point; no event was recorded before expiry, so neither fill nor expiry is safe."}, ensure_ascii=False))
        return
    if expiry == "expire":
        event_id = f"paper-expire-{order['order_id']}"
        if not any(x.get("event_id") == event_id for x in account["event_log"]):
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            account["event_log"].append({"event_id": event_id, "type": "PAPER_ORDER_EXPIRED_NO_FILL", "at_utc": now,
                "reason": "سومین جلسهٔ رسمی پس از تصمیم کامل شده و شواهد جلسهٔ اجرای نخست، اجرای واجد شرایطی را اثبات نکرده است.",
                "details": f"order={order['order_id']}; designated_first_session={first_day}; eligibility={eligibility_reason}."})
        order["status"] = "EXPIRED_NO_FILL"
        order["waiting_reason"] = "در پایان سومین جلسهٔ رسمی، قیمت/حجم/رویداد لازم برای اجرای واجد شرایط موجود نبود؛ وجه نقد و دارایی تغییر نکرد."
        account["paper_order"] = order
        account["status"] = "EXPIRED_NO_FILL"
        if args.apply_fill:
            write_account_atomic(account)
        print(json.dumps({"status": "EXPIRED_NO_FILL", "sessions_after_decision": sessions_count,
                          "first_session": first_day, "eligibility": eligibility_reason,
                          "fill_applied": False, "cash_toman": account["cash_toman"]}, ensure_ascii=False))
        return
    if eligibility_reason:
        if expiry == "continue":
            record_order_observation(account, order, first_day, sessions_count, str(rows[-1]["DEven"]))
        print(json.dumps({"status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "first_session": first_day,
                          "candidate_bar": bool(day_rows), "volume": volume, "fill_applied": False,
                          "eligibility": eligibility_reason, "cash_toman": account["cash_toman"]}, ensure_ascii=False))
        return
    if args.apply_fill:
        event_id = f"paper-fill-{order['order_id']}-{first_day}"
        if any(x.get("event_id") == event_id for x in account["event_log"]):
            raise SystemExit("DUPLICATE_FILL_EVENT_ID")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        account["cash_toman"] -= gross + fee
        holding = {"symbol": order["symbol"], "company_id": order["company_id"], "shares": shares,
            "purchase_price_rial": close_rial, "purchase_price_toman": price_toman,
            "purchase_at_utc": f"{first_day} close (first official session after decision; recorded {now})",
            "cost_basis_toman": gross, "fee_toman": fee, "last_price_rial": close_rial,
            "last_price_date": f"{first_day[:4]}-{first_day[4:6]}-{first_day[6:8]}",
            "market_value_toman": gross, "unrealized_pnl_toman": -fee,
            "price_status": "اجرای فرضی با محدودیت دادهٔ صف؛ close روزانه fill یا اولویت واقعی را اثبات نمی‌کند."}
        account["holdings"] = [holding]
        account["accounting"] = {"holdings_value_toman": gross, "total_value_toman": account["cash_toman"] + gross,
            "profit_loss_toman": -fee, "last_price_status": holding["price_status"]}
        order.update({"status": "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE", "designated_execution_price_rial": close_rial,
                      "fill_event_id": event_id, "fill_source_manifest": str(evidence_path.relative_to(ROOT)).replace("\\", "/"),
                      "fill_source_manifest_sha256": sha(evidence_path), "queue_limitation": holding["price_status"]})
        account["execution_recorded"] = True
        account["status"] = order["status"]
        account["candidate_status"] = "اجرای فرضی با محدودیت دادهٔ صف؛ fill بازار واقعی/تأییدشده نیست"
        account["waiting_reason"] = "موقعیت فقط در حساب آزمایشی ثبت شده است؛ صف/اولویت اجرا از close روزانه اثبات نمی‌شود."
        account["event_log"].append({"event_id": event_id, "type": "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE", "at_utc": now,
            "reason": "قیمت پایانی و حجم مثبت در نخستین جلسهٔ رسمی بعد از تصمیم، با هویت insCode منطبق و منابع بعد از تصمیم ثبت شدند.",
            "details": f"{order['symbol']}; session={first_day}; shares={shares}; close_rial={close_rial}; gross_toman={gross}; assumed_fee_toman={fee}; cash_after={account['cash_toman']}; order={order['order_id']}; evidence_sha256={sha(evidence_path)}; queue not evidenced."})
        write_account_atomic(account)
    print(json.dumps({"status": "FILL_APPLIED" if args.apply_fill else "FILL_ELIGIBLE_PREVIEW_ONLY",
                      "first_session": first_day, "close_rial": close_rial, "volume": volume,
                      "fill_applied": args.apply_fill, "cash_toman": account["cash_toman"],
                      "source_manifest_sha256": sha(evidence_path)}, ensure_ascii=False))


def main() -> None:
    with account_write_lock():
        run_locked()


if __name__ == "__main__":
    main()
