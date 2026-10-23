"""Preview or apply the single approved close-only paper fill, with explicit source inputs."""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import zlib
from decimal import Decimal
from pathlib import Path
try:
    from ranking_research import paper_account_store
except ImportError:  # direct-file loader used by the Windows lock regression test
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ranking_research import paper_account_store

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
RULES = ROOT / "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_gzip_raw(path: Path, expected_sha256: str, error_code: str) -> bytes:
    try:
        raw = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile, zlib.error):
        raise SystemExit(error_code) from None
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise SystemExit(error_code)
    return raw


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
    paper_account_store.write_account_atomic(ACCOUNT, account)


def _verify_replay_state(account: dict, order: dict, receipt: dict, expected: dict) -> None:
    if receipt != expected:
        raise SystemExit("FILL_REPLAY_CONFLICT; correction requires a separate append-only correction event")
    event_id = f"paper-fill-{order['order_id']}-{receipt['designated_session']}"
    events = [event for event in account.get("event_log", []) if event.get("event_id") == event_id]
    holdings = account.get("holdings", [])
    if (order.get("fill_event_id") != event_id
            or order.get("status") != "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE"
            or len(events) != 1 or events[0].get("type") != "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE"
            or len(holdings) != 1):
        raise SystemExit("FILL_REPLAY_STATE_CONFLICT; correction requires a separate append-only correction event")
    holding = holdings[0]
    if (holding.get("symbol") != receipt["symbol"] or holding.get("company_id") != receipt["company_id"]
            or holding.get("shares") != receipt["shares"]
            or holding.get("cost_basis_toman") != receipt["gross_toman"]
            or holding.get("fee_toman") != receipt["fee_toman"]
            or account.get("cash_toman") != receipt["cash_before_toman"] - receipt["gross_toman"] - receipt["fee_toman"]):
        raise SystemExit("FILL_REPLAY_STATE_CONFLICT; correction requires a separate append-only correction event")


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


def account_write_lock():
    """Compatibility alias for the shared cross-process account lock."""
    return paper_account_store.account_write_lock(ACCOUNT)


def run_locked() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-calendar-manifest", type=Path, required=True,
                        help="A saved manifest/raw response from the documented official NSCStart endpoint.")
    parser.add_argument("--evidence-manifest", type=Path, required=True,
                        help="Explicit versioned candidate evidence manifest from acquire_paper_candidate_evidence.py.")
    parser.add_argument("--apply-fill", action="store_true", help="Apply a validated fill once to the paper account.")
    parser.add_argument("--observe-order-state", action="store_true", help="Explicitly persist non-fill order-window evidence.")
    args = parser.parse_args()
    account = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    paper_account_store.validate_account(account)
    decision, order = account["active_decision"], account["paper_order"]
    rules_bytes = RULES.read_bytes()
    if hashlib.sha256(rules_bytes).hexdigest() != decision["execution_rules"]["sha256"]:
        raise SystemExit("PINNED_EXECUTION_RULES_HASH_MISMATCH")
    has_prior_fill = bool(order.get("fill_event_id"))
    if (not isinstance(account.get("account_id"), str) or not account["account_id"]
            or not isinstance(decision.get("decision_id"), str) or not decision["decision_id"]
            or not isinstance(order.get("order_id"), str) or not order["order_id"]
            or order.get("decision_id") != decision.get("decision_id")):
        raise SystemExit("PAPER_FILL_IDENTITY_INVALID")
    if account.get("holdings") and not has_prior_fill:
        raise SystemExit("HOLDING_WITHOUT_VERIFIED_FILL_RECEIPT")
    if has_prior_fill and not isinstance(order.get("fill_receipt"), dict):
        raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; fill has no trusted v1 receipt")
    if has_prior_fill and (not account.get("holdings") or not order.get("decision_id")
                           or not decision.get("decision_id")):
        raise SystemExit("FILL_REPLAY_RECEIPT_IDENTITY_INVALID")
    cash_for_order = account["cash_toman"]
    if has_prior_fill:
        receipt_cash = order["fill_receipt"].get("cash_before_toman")
        if isinstance(receipt_cash, bool) or not isinstance(receipt_cash, int) or receipt_cash < 0:
            raise SystemExit("FILL_REPLAY_RECEIPT_INVALID")
        cash_for_order = receipt_cash
    if order.get("status") not in ("PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "EXPIRED_NO_FILL",
                                    "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE"):
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
    session_raw = json.loads(verified_gzip_raw(session_raw_path, sessions_doc["raw_sha256"],
                                               "OFFICIAL_SESSION_CALENDAR_RAW_HASH_MISMATCH"))
    normalized_session_rows = [{"DEven": str(x["DEven"]), "HEven": x.get("HEven"), "NSCEnd": str(x.get("NSCEnd", ""))} for x in session_raw.get("Data", [])]
    if normalized_session_rows != sessions_doc.get("sessions"):
        raise SystemExit("OFFICIAL_SESSION_CALENDAR_MANIFEST_RAW_MISMATCH")
    decision_day = decision["decision_local_date"].replace("-", "")
    if not calendar_covers_order_window(normalized_session_rows, decision_day):
        raise SystemExit("CALENDAR_WINDOW_DOES_NOT_COVER_DECISION_OR_FULL_20_SESSION_WINDOW")
    source_entries = evidence.get("sources", [])
    if not isinstance(source_entries, list) or any(not isinstance(x, dict) or not isinstance(x.get("key"), str) for x in source_entries):
        raise SystemExit("OFFICIAL_SOURCE_MANIFEST_INVALID")
    source_map = {x["key"]: x for x in source_entries}
    if len(source_map) != len(source_entries):
        raise SystemExit("OFFICIAL_SOURCE_MANIFEST_DUPLICATE_KEY")
    for key in ("candidate_daily", "candidate_share_changes", "last_possible_session"):
        if key not in source_map or not source_map[key].get("raw_sha256"):
            raise SystemExit(f"REQUIRED_OFFICIAL_SOURCE_MISSING:{key}")
        if source_map[key].get("retrieved_at_utc", "") < decision["decided_at_utc"]:
            raise SystemExit(f"OFFICIAL_SOURCE_PREDATES_DECISION:{key}")
        raw_path = ROOT / source_map[key].get("raw_path", "")
        verified_gzip_raw(raw_path, source_map[key]["raw_sha256"], f"OFFICIAL_RAW_HASH_MISMATCH:{key}")
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
    price_toman = Decimal(str(close_rial)) / Decimal(10) if close_rial > 0 else Decimal(0)
    shares = math.floor(Decimal(cash_for_order) / (price_toman * Decimal("1.005"))) if price_toman > 0 else 0
    gross = paper_account_store.money(shares * price_toman)
    fee = paper_account_store.money(gross * 0.005)
    while shares > 0 and gross + fee > cash_for_order:
        shares -= 1
        gross = paper_account_store.money(shares * price_toman)
        fee = paper_account_store.money(gross * 0.005)
    eligibility_reason = (
        "FIRST_SESSION_BAR_MISSING_OR_NO_TRADE" if close_rial <= 0 or volume <= 0 else
        "CORPORATE_ACTION_REQUIRES_MANUAL_RESOLUTION" if corporate_action else
        "CASH_BELOW_ONE_SHARE_PLUS_ASSUMED_FEE" if shares <= 0 else None
    )
    if args.apply_fill and eligibility_reason is None:
        receipt = {
            "version": 1, "account_id": account["account_id"], "decision_id": decision["decision_id"],
            "order_id": order["order_id"], "designated_session": first_day, "rules_sha256": sha(RULES),
            "ins_code": ins_code, "symbol": order["symbol"], "company_id": order["company_id"],
            "shares": shares, "close_rial": close_rial, "gross_toman": gross, "fee_toman": fee,
            "source_sha256": {"calendar_raw": sessions_doc["raw_sha256"], **{
                key: source_map[key]["raw_sha256"] for key in
                ("candidate_daily", "candidate_share_changes", "last_possible_session")}},
            "cash_before_toman": cash_for_order,
        }
        if has_prior_fill or account.get("holdings"):
            old_receipt = order.get("fill_receipt")
            if not has_prior_fill or not old_receipt or not account.get("holdings"):
                raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; holding/order lacks trusted v1 receipt")
            _verify_replay_state(account, order, old_receipt, receipt)
            print(json.dumps({"status": "FILL_ALREADY_APPLIED", "fill_applied": False,
                              "fill_event_id": order["fill_event_id"], "cash_toman": account["cash_toman"]}, ensure_ascii=False))
            return
        if has_prior_fill:
            raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; fill has no trusted v1 receipt")
    elif account.get("holdings") and not has_prior_fill:
        raise SystemExit("HOLDING_WITHOUT_VERIFIED_FILL_RECEIPT")
    expiry = expiry_outcome(sessions_count, int(order["expires_after_official_sessions"]), eligibility_reason is None)
    if expiry == "late_fill_timing_ambiguous":
        ambiguity_id = f"paper-late-fill-ambiguity-{order['order_id']}-{sha(evidence_path)}"
        if not any(x.get("event_id") == ambiguity_id for x in account["event_log"]):
            if args.apply_fill or args.observe_order_state:
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
        if args.apply_fill or args.observe_order_state:
            write_account_atomic(account)
        print(json.dumps({"status": "EXPIRED_NO_FILL", "sessions_after_decision": sessions_count,
                          "first_session": first_day, "eligibility": eligibility_reason,
                          "fill_applied": False, "cash_toman": account["cash_toman"]}, ensure_ascii=False))
        return
    if eligibility_reason:
        if expiry == "continue" and args.observe_order_state:
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
            "purchase_price_rial": close_rial, "purchase_price_toman": float(price_toman),
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
                      "fill_source_manifest_sha256": sha(evidence_path), "queue_limitation": holding["price_status"],
                      "fill_receipt": receipt})
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
