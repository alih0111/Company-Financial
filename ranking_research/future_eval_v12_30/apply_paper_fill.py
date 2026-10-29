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
    from ranking_research import paper_calendar
except ImportError:  # direct-file loader used by the Windows lock regression test
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ranking_research import paper_account_store
    from ranking_research import paper_calendar

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


def holding_price_status(public_profile: bool = False) -> str:
    base = ("اجرای فرضی با محدودیت دادهٔ صف؛ close روزانه fill یا اولویت واقعی را اثبات نمی‌کند.")
    if public_profile:
        return (base + " پایان جلسه بر پایهٔ فرض ثبت‌شدهٔ سیاست تقویم عمومی است؛ "
                "بدون گواه کامل‌بودن تقویم.")
    return base


def calendar_covers_order_window(sessions: list[dict], decision_day: str) -> bool:
    return paper_calendar.nscstart_covers_order_window(sessions, decision_day)


def resolve_now(args: argparse.Namespace) -> dt.datetime:
    """Injected evaluation clock for calendar freshness; defaults to the real clock."""
    if args.reference_now_utc:
        now = dt.datetime.fromisoformat(args.reference_now_utc)
        return now if now.tzinfo else now.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def _refuse(exc: "paper_calendar.CalendarRefusal") -> SystemExit:
    detail = f"; {exc.detail}" if exc.detail else ""
    return SystemExit(f"{exc.code}{detail}")


def write_account_atomic(account: dict) -> None:
    """Commit cash, holdings, order state and its event as one file replacement."""
    paper_account_store.write_account_atomic(ACCOUNT, account)


def _verify_replay_state(account: dict, order: dict, receipt: dict, expected: dict) -> None:
    if receipt != expected:
        raise SystemExit("FILL_REPLAY_CONFLICT; correction requires a separate append-only correction event")
    event_id = f"paper-fill-{order['order_id']}-{receipt['designated_session']}"
    events = [event for event in account.get("event_log", []) if event.get("event_id") == event_id]
    holdings = account.get("holdings", [])
    if receipt.get("side") == "SELL":
        if (order.get("fill_event_id") != event_id or order.get("status") != "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE" or len(events) != 1
                or events[0].get("type") != "PAPER_SELL_DAILY_CLOSE_LIMITED_QUEUE" or holdings
                or account["cash_toman"] != receipt["cash_before_toman"] + receipt["gross_toman"] - receipt["fee_toman"]
                or account.get("realized_pnl_toman") != receipt["realized_after_toman"]):
            raise SystemExit("FILL_REPLAY_STATE_CONFLICT")
        return
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
                        help="Saved calendar evidence: an NSCStart manifest (nscstart provider) "
                             "or a pinned public-index calendar manifest (public provider).")
    parser.add_argument("--evidence-manifest", type=Path, required=True,
                        help="Explicit versioned candidate evidence manifest from acquire_paper_candidate_evidence.py.")
    parser.add_argument("--calendar-provider", choices=("nscstart", "public"),
                        default="nscstart",
                        help="Calendar source profile. The default keeps the current pinned "
                             "NSCStart path unchanged; 'public' is the token-free experimental "
                             "profile and requires an account/order/rules binding to it.")
    parser.add_argument("--calendar-manifest-sha256", default=None,
                        help="Pinned sha256 of the calendar manifest (required for --calendar-provider public).")
    parser.add_argument("--calendar-policy", type=Path,
                        default=paper_calendar.DEFAULT_PUBLIC_POLICY_PATH,
                        help="Versioned public calendar policy document (public provider only).")
    parser.add_argument("--reference-now-utc", default=None,
                        help="Injected evaluation clock (ISO) for calendar freshness checks.")
    parser.add_argument("--account", type=Path, default=ACCOUNT)
    parser.add_argument("--rules", type=Path, default=RULES)
    parser.add_argument("--apply-fill", action="store_true", help="Apply a validated fill once to the paper account.")
    parser.add_argument("--observe-order-state", action="store_true", help="Explicitly persist non-fill order-window evidence.")
    args = parser.parse_args()
    account = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    paper_account_store.validate_account(account)
    decision, order = account["active_decision"], account["paper_order"]
    try:
        rules_bytes = RULES.read_bytes()
        rules_doc = json.loads(rules_bytes)
        paper_calendar.check_provider_contract(account=account,
                                               provider=args.calendar_provider,
                                               rules_bytes=rules_bytes,
                                               rules_doc=rules_doc)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"PINNED_EXECUTION_RULES_UNREADABLE; {type(exc).__name__}") from None
    except paper_calendar.CalendarRefusal as exc:
        raise _refuse(exc) from None
    if hashlib.sha256(rules_bytes).hexdigest() != decision["execution_rules"]["sha256"]:
        raise SystemExit("PINNED_EXECUTION_RULES_HASH_MISMATCH")
    has_prior_fill = bool(order.get("fill_event_id"))
    selling = order.get("side", "BUY") == "SELL"
    if order.get("side", "BUY") not in ("BUY", "SELL"):
        raise SystemExit("UNSUPPORTED_PAPER_ORDER_SIDE")
    if selling and account.get("profile") != "EXPERIMENTAL_PAPER_V1":
        raise SystemExit("SELL_REQUIRES_EXPERIMENTAL_ACCOUNT")
    sold_holding = (order.get("fill_receipt", {}).get("sold_holding") if has_prior_fill
                    else (account.get("holdings") or [None])[0]) if selling else None
    if selling and (not isinstance(sold_holding, dict)
                    or sold_holding.get("company_id") != order.get("company_id")
                    or sold_holding.get("symbol") != order.get("symbol")
                    or sold_holding.get("shares", 0) <= 0
                    or (not has_prior_fill and len(account["holdings"]) != 1)):
        raise SystemExit("SELL_HOLDING_IDENTITY_INVALID")
    if (not isinstance(account.get("account_id"), str) or not account["account_id"]
            or not isinstance(decision.get("decision_id"), str) or not decision["decision_id"]
            or not isinstance(order.get("order_id"), str) or not order["order_id"]
            or order.get("decision_id") != decision.get("decision_id")):
        raise SystemExit("PAPER_FILL_IDENTITY_INVALID")
    if account.get("holdings") and not has_prior_fill and not selling:
        raise SystemExit("HOLDING_WITHOUT_VERIFIED_FILL_RECEIPT")
    if has_prior_fill and not isinstance(order.get("fill_receipt"), dict):
        raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; fill has no trusted v1 receipt")
    if has_prior_fill and ((not selling and not account.get("holdings")) or not order.get("decision_id")
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
    decision_day = decision["decision_local_date"].replace("-", "")
    now_utc = resolve_now(args)
    consumption_mode = ("exact-replay" if has_prior_fill
                        else "fixture-apply" if args.apply_fill else "live-preview")

    def validate_evidence_sources() -> dict:
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
        return source_map

    calendar_receipt = None
    calendar_label_fa = None
    replayed_at_recorded_clock = None
    if args.calendar_provider == "public":
        # The public profile is a separately bound policy: an old order pinned
        # to the previous rules hash never silently converts to it. The binding
        # is mandatory at every level — a missing binding is itself a mismatch.
        policy = paper_calendar.load_policy(args.calendar_policy)
        policy_sha = sha(args.calendar_policy)
        try:
            paper_calendar.check_public_policy_binding(
                account=account, rules_doc=rules_doc,
                policy=policy, policy_sha256=policy_sha)
        except paper_calendar.CalendarRefusal as exc:
            raise _refuse(exc) from None
        if not args.calendar_manifest_sha256:
            raise SystemExit("CALENDAR_MANIFEST_SHA256_REQUIRED")
        source_map = validate_evidence_sources()
        if has_prior_fill:
            # Exact replay of this same execution: before any past clock may be
            # used, the identity of that execution and the equality of every
            # pinned input with the recorded receipt must be established. The
            # exact-replay mode alone never waives the freshness contract.
            prior_receipt = order.get("fill_receipt") or {}
            prior_calendar = prior_receipt.get("calendar") or {}
            if not prior_calendar:
                raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; "
                                 "the recorded fill has no public calendar receipt")
            if (prior_calendar.get("manifest_sha256") != args.calendar_manifest_sha256
                    or prior_calendar.get("policy_sha256") != policy_sha
                    or prior_calendar.get("evidence_manifest_sha256") != sha(evidence_path)
                    or prior_receipt.get("order_id") != order.get("order_id")
                    or prior_receipt.get("decision_id") != decision.get("decision_id")
                    or prior_receipt.get("account_id") != account.get("account_id")):
                raise SystemExit("FILL_REPLAY_INPUTS_CHANGED; the offered pinned inputs "
                                 "differ from the recorded execution; the previous "
                                 "receipt is never rewritten")
            if not prior_calendar.get("validated_at_utc"):
                raise SystemExit("FILL_REPLAY_VALIDATION_CLOCK_UNPROVABLE; this receipt "
                                 "predates clock recording; no execution time is fabricated")
            try:
                replayed_at_recorded_clock = paper_calendar.parse_utc(
                    prior_calendar["validated_at_utc"],
                    field="fill_receipt.calendar.validated_at_utc")
            except paper_calendar.CalendarRefusal as exc:
                raise _refuse(exc) from None
            # The validation clock is recovered from the receipt — not from
            # today's clock and not from a manual flag; freshness of the same
            # pinned evidence validates at its own recorded execution time.
            now_utc = replayed_at_recorded_clock
        try:
            answer = paper_calendar.resolve_public_calendar(
                manifest_path=session_path,
                expected_manifest_sha256=args.calendar_manifest_sha256,
                policy=policy, policy_sha256=policy_sha,
                candidate={"symbol": order["symbol"],
                           "ins_code": str(evidence.get("ins_code", ""))},
                decision_local_date=decision["decision_local_date"],
                decision_at_utc=dt.datetime.fromisoformat(decision["decided_at_utc"]),
                now_utc=now_utc, consumption_mode=consumption_mode)
        except paper_calendar.CalendarRefusal as exc:
            raise _refuse(exc) from None
        calendar_label_fa = answer["display_label_fa"]
        calendar_receipt = {"provider": "public-index",
                            "policy_id": policy["policy_id"], "policy_sha256": policy_sha,
                            "manifest": str(session_path),
                            "manifest_sha256": args.calendar_manifest_sha256,
                            "completion_type": answer["completion"]["type"],
                            "assumed_completion": answer["completion"].get("value"),
                            "validated_at_utc": now_utc.astimezone(dt.timezone.utc).isoformat(),
                            "evidence_manifest_sha256": sha(evidence_path),
                            "label_fa": calendar_label_fa}
    else:
        try:
            answer = paper_calendar.resolve_nscstart_calendar(
                manifest_path=session_path,
                decision_local_date=decision["decision_local_date"],
                decision_at_utc=dt.datetime.fromisoformat(decision["decided_at_utc"]),
                now_utc=now_utc, consumption_mode=consumption_mode, root=ROOT)
        except paper_calendar.CalendarRefusal as exc:
            raise _refuse(exc) from None
        source_map = validate_evidence_sources()
    # Common consumption gate for every provider: an unresolved readiness is a
    # hard stop for fill, expiry and observation alike — the real blocking
    # reason is preserved and the account is untouched.
    if not answer["readiness"]["calendar_ready"]:
        raise SystemExit("CALENDAR_NOT_READY;"
                         + ",".join(answer["readiness"]["blocking_reasons"]))
    state = answer["sessions_after_decision"]["state"]
    if answer["eligible_session_count"] is None:
        raise SystemExit(f"SESSION_COUNT_UNKNOWN;{state}")
    sessions_count = answer["eligible_session_count"]
    if sessions_count == 0:
        # Successful acquisition with no new accepted session: not an error,
        # and never a reason to fabricate a session or touch the account.
        print(json.dumps({"status": state, "first_session": None, "session_count": 0,
                          "fill_applied": False, "cash_toman": account["cash_toman"],
                          **({"calendar_label_fa": calendar_label_fa}
                             if calendar_receipt else {}),
                          "reason": ("acquisition succeeded; no new session is accepted "
                                     "for execution under this calendar policy yet")},
                         ensure_ascii=False))
        return
    first_day = answer["first_usable_session"]
    latest_session = answer["sessions_after_decision"]["sessions"][-1]
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
    if args.calendar_provider == "public":
        # session confirmation came from the public adapter's re-computed
        # completion assumption (policy-checked); the NSCStart-specific
        # reported_last_possible_session field does not exist in this profile
        if not (calendar_receipt and answer["completion"]["officially_confirmed"] is False
                and answer["completion"].get("value") and answer["completion"]["value"] >= first_day):
            raise SystemExit("SESSION_NOT_CONFIRMED_BY_PUBLIC_COMPLETION_ASSUMPTION")
    elif source_map["last_possible_session"].get("reported_last_possible_session", "")[:8] < first_day:
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
    action_start = sold_holding["purchase_at_utc"][:10].replace("-", "") if selling else decision_day
    corporate_action = any(action_start < str(x.get("dEven", ""))[:8] <= first_day
                           and float(x.get("numberOfShareNew", 0) or 0) != float(x.get("numberOfShareOld", 0) or 0)
                           for x in share_changes)
    price_toman = Decimal(str(close_rial)) / Decimal(10) if close_rial > 0 else Decimal(0)
    shares = math.floor(Decimal(cash_for_order) / (price_toman * Decimal("1.005"))) if price_toman > 0 else 0
    if selling:
        shares = sold_holding["shares"]
    gross = paper_account_store.money(shares * price_toman)
    fee = paper_account_store.money(Decimal(gross) * Decimal("0.005"))
    while not selling and shares > 0 and gross + fee > cash_for_order:
        shares -= 1
        gross = paper_account_store.money(shares * price_toman)
        fee = paper_account_store.money(Decimal(gross) * Decimal("0.005"))
    eligibility_reason = (
        "FIRST_SESSION_BAR_MISSING_OR_NO_TRADE" if close_rial <= 0 or volume <= 0 else
        "CORPORATE_ACTION_REQUIRES_MANUAL_RESOLUTION" if corporate_action else
        "CASH_BELOW_ONE_SHARE_PLUS_ASSUMED_FEE" if shares <= 0 else None
    )
    if args.apply_fill and eligibility_reason is None:
        calendar_source_sha = ({"calendar_raw": sessions_doc["raw_sha256"]}
                               if args.calendar_provider == "nscstart"
                               else {"calendar_manifest": args.calendar_manifest_sha256})
        receipt = {
            "version": 2 if calendar_receipt else 1,
            "account_id": account["account_id"], "decision_id": decision["decision_id"],
            "order_id": order["order_id"], "designated_session": first_day, "rules_sha256": sha(RULES),
            "ins_code": ins_code, "symbol": order["symbol"], "company_id": order["company_id"],
            "shares": shares, "close_rial": close_rial, "gross_toman": gross, "fee_toman": fee,
            "source_sha256": {**calendar_source_sha, **{
                key: source_map[key]["raw_sha256"] for key in
                ("candidate_daily", "candidate_share_changes", "last_possible_session")}},
            "cash_before_toman": cash_for_order,
        }
        if calendar_receipt:
            receipt["calendar"] = calendar_receipt
        if selling:
            realized_before = (order["fill_receipt"]["realized_before_toman"] if has_prior_fill
                               else account.get("realized_pnl_toman", 0))
            receipt.update(side="SELL", sold_holding=sold_holding, realized_before_toman=realized_before,
                           realized_after_toman=realized_before + gross - fee - sold_holding["cost_basis_toman"] - sold_holding["fee_toman"])
        if has_prior_fill or (account.get("holdings") and not selling):
            old_receipt = order.get("fill_receipt")
            if not has_prior_fill or not old_receipt or (not selling and not account.get("holdings")):
                raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; holding/order lacks trusted v1 receipt")
            _verify_replay_state(account, order, old_receipt, receipt)
            replay_payload = {"status": "FILL_ALREADY_APPLIED", "fill_applied": False,
                              "fill_event_id": order["fill_event_id"],
                              "cash_toman": account["cash_toman"]}
            if replayed_at_recorded_clock is not None:
                # freshness of the same pinned evidence was validated at the
                # receipt's own recorded clock, not at today's clock
                replay_payload["replayed_at_recorded_validation_clock"] = \
                    replayed_at_recorded_clock.isoformat()
            print(json.dumps(replay_payload, ensure_ascii=False))
            return
        if has_prior_fill:
            raise SystemExit("FILL_REPLAY_UNVERIFIABLE_LEGACY_STATE; fill has no trusted v1 receipt")
    elif account.get("holdings") and not has_prior_fill and not selling:
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
            record_order_observation(account, order, first_day, sessions_count, latest_session)
        pending = {"status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "first_session": first_day,
                   "candidate_bar": bool(day_rows), "volume": volume, "fill_applied": False,
                   "eligibility": eligibility_reason, "cash_toman": account["cash_toman"]}
        if calendar_receipt:
            pending["calendar_label_fa"] = calendar_label_fa
        print(json.dumps(pending, ensure_ascii=False))
        return
    if args.apply_fill:
        event_id = f"paper-fill-{order['order_id']}-{first_day}"
        if any(x.get("event_id") == event_id for x in account["event_log"]):
            raise SystemExit("DUPLICATE_FILL_EVENT_ID")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        account["cash_toman"] += gross - fee if selling else -(gross + fee)
        public_fill = calendar_receipt is not None
        price_status = holding_price_status()
        holding = {"symbol": order["symbol"], "company_id": order["company_id"], "shares": shares,
            "purchase_price_rial": close_rial, "purchase_price_toman": float(price_toman),
            "purchase_at_utc": f"{first_day} close (first official session after decision; recorded {now})",
            "cost_basis_toman": gross, "fee_toman": fee, "last_price_rial": close_rial,
            "last_price_date": f"{first_day[:4]}-{first_day[4:6]}-{first_day[6:8]}",
            "market_value_toman": gross, "unrealized_pnl_toman": -fee,
            "price_status": price_status}
        if selling:
            account["realized_pnl_toman"] = receipt["realized_after_toman"]
        account["holdings"] = [] if selling else [holding]
        value = 0 if selling else gross
        account["accounting"] = {"holdings_value_toman": value, "total_value_toman": account["cash_toman"] + value,
            "profit_loss_toman": account.get("realized_pnl_toman", 0) + (0 if selling else -fee), "last_price_status": holding["price_status"]}
        order.update({"status": "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE", "designated_execution_price_rial": close_rial,
                      "fill_event_id": event_id, "fill_source_manifest": str(evidence_path.relative_to(ROOT) if evidence_path.is_relative_to(ROOT) else evidence_path).replace("\\", "/"),
                      "fill_source_manifest_sha256": sha(evidence_path), "queue_limitation": holding["price_status"],
                      "fill_receipt": receipt})
        account["execution_recorded"] = True
        account["status"] = order["status"]
        account["candidate_status"] = "اجرای فرضی با محدودیت دادهٔ صف؛ fill بازار واقعی/تأییدشده نیست"
        account["waiting_reason"] = "موقعیت فقط در حساب آزمایشی ثبت شده است؛ صف/اولویت اجرا از close روزانه اثبات نمی‌شود."
        account["event_log"].append({"event_id": event_id, "type": "PAPER_SELL_DAILY_CLOSE_LIMITED_QUEUE" if selling else "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE", "at_utc": now,
            "reason": ("قیمت پایانی و حجم مثبت در نخستین جلسهٔ پذیرفته‌شدهٔ تقویم عمومی بعد از تصمیم، با هویت insCode منطبق و منابع بعد از تصمیم ثبت شدند؛ پایان جلسه بر پایهٔ فرض ثبت‌شده، بدون گواه کامل‌بودن تقویم."
                       if public_fill else
                       "قیمت پایانی و حجم مثبت در نخستین جلسهٔ رسمی بعد از تصمیم، با هویت insCode منطبق و منابع بعد از تصمیم ثبت شدند."),
            "details": f"{order['symbol']}; session={first_day}; shares={shares}; close_rial={close_rial}; gross_toman={gross}; assumed_fee_toman={fee}; cash_after={account['cash_toman']}; order={order['order_id']}; evidence_sha256={sha(evidence_path)}; calendar_provider={args.calendar_provider}; calendar_manifest_sha256={(calendar_receipt or {}).get('manifest_sha256')}; queue not evidenced."})
        write_account_atomic(account)
    payload = {"status": "FILL_APPLIED" if args.apply_fill else "FILL_ELIGIBLE_PREVIEW_ONLY",
               "first_session": first_day, "sessions_after_decision": sessions_count,
               "close_rial": close_rial, "volume": volume,
               "fill_applied": args.apply_fill, "cash_toman": account["cash_toman"],
               "source_manifest_sha256": sha(evidence_path)}
    if calendar_receipt:
        payload["calendar"] = {"provider": "public-index",
                               "policy_id": calendar_receipt["policy_id"],
                               "manifest_sha256": calendar_receipt["manifest_sha256"],
                               "assumed_completion": calendar_receipt["assumed_completion"],
                               "completion_type": calendar_receipt["completion_type"]}
        payload["calendar_label_fa"] = calendar_label_fa
    print(json.dumps(payload, ensure_ascii=False))


def main() -> None:
    global ACCOUNT, RULES
    paths = argparse.ArgumentParser(add_help=False)
    paths.add_argument("--account", type=Path, default=ACCOUNT)
    paths.add_argument("--rules", type=Path, default=RULES)
    selected, _ = paths.parse_known_args()
    ACCOUNT, RULES = selected.account.resolve(), selected.rules.resolve()
    with account_write_lock():
        run_locked()


if __name__ == "__main__":
    main()
