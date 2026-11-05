"""Model-driven review and rotation for the experimental paper accounts.

user-auto-rotation-v1, explicitly requested by the account owner: at each trial
cycle the current model ranking is re-read once the review cadence (in accepted
official sessions since the position's designated fill session) is reached.

- same rank-1 candidate -> one append-only HOLD review event per review index;
- changed candidate -> record the SELL decision now, pin the fresh ranking
  snapshot, and record the replacement BUY right after the sell fill settles;
- stale ranking -> HOLD with an explicit staleness note, never a rotation.

Every decision flows through the locked engine (register_paper_decision.py +
apply_paper_fill.py): fills stay bound to the first eligible session's close
after each decision, never retroactive, never touching real brokers.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from pathlib import Path

from ranking_research.future_eval_v12_30 import experimental_paper as exp
from ranking_research import paper_account_store as store
from ranking_research import paper_calendar as calendar

ROOT = exp.ROOT
DEFAULT_RANKING_SOURCE = "client/public/research/v12-37/latest-ranking.json"
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30))


def state_path(home: Path) -> Path:
    return Path(home) / "review-state.json"


def load_state(home: Path) -> dict:
    path = state_path(home)
    return exp.load(path) if path.exists() else {"pending_buy": None, "history": []}


def save_state(home: Path, state: dict) -> None:
    path = state_path(home)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def ensure_policy(config: dict) -> dict | None:
    """The review policy is opt-in by config key; removing the key disables rotation."""
    policy = config.get("review_policy")
    return policy if isinstance(policy, dict) else None


def _calendar_answer(home: Path, evidence_path: Path, cal_manifest: Path):
    """Recompute the run's public calendar answer (file-based, no network).

    Anchored at the account's active decision exactly like mark_verified, so the
    manifest's pinned window matches and the session list is the accepted one.
    """
    account = exp.profile_account(home)
    decision = account["active_decision"]
    evidence = exp.load(evidence_path)
    sources = {s["key"]: s for s in evidence.get("sources", [])}
    daily = sources.get("candidate_daily")
    if not daily:
        raise ValueError("REVIEW_EVIDENCE_MISSING_CANDIDATE_DAILY")
    policy_path = calendar.DEFAULT_PUBLIC_POLICY_PATH
    return calendar.resolve_public_calendar(
        manifest_path=cal_manifest, expected_manifest_sha256=exp.sha(cal_manifest),
        policy=exp.load(policy_path), policy_sha256=exp.sha(policy_path),
        candidate={"symbol": account["paper_order"]["symbol"],
                   "ins_code": str(evidence.get("ins_code", ""))},
        decision_local_date=decision["decision_local_date"],
        decision_at_utc=dt.datetime.fromisoformat(decision["decided_at_utc"]),
        now_utc=exp.now(), consumption_mode="live-preview")


def _append_event(home: Path, event: dict) -> bool:
    def mutate(account):
        if any(x.get("event_id") == event["event_id"] for x in account["event_log"]):
            return False
        account["event_log"].append(event)
        return True
    return bool(store.read_modify_write(Path(home) / "account.json", mutate))


def _review_index(sessions_after_fill: int, cadence: int) -> int:
    return sessions_after_fill // cadence


def _today() -> dt.date:
    return dt.datetime.now(TEHRAN).date()


def _stale_days(rank: dict) -> int:
    evaluation = dt.date.fromisoformat(str(rank.get("evaluation_date")))
    return (_today() - evaluation).days


def _recover_recorded_buy(home: Path, account: dict, state: dict, pending: dict, method: str) -> dict:
    """Reconcile a replacement BUY already recorded before an interruption."""
    order = account["paper_order"]
    decision = account.get("active_decision") or {}
    history = account.get("order_history") or []
    previous_buy = (history[-2].get("order") or {}) if len(history) >= 2 else {}
    sale = (history[-1].get("order") or {}) if history else {}
    if (pending.get("phase") != "SELL_INTENT"
            or previous_buy.get("order_id") != pending.get("sell_order_id")
            or sale.get("side") != "SELL" or sale.get("company_id") != pending.get("sold_company_id")
            or not pending.get("sell_basis_path") or sale.get("source_manifest") != pending.get("sell_basis_path")
            or sale.get("status") != "PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE" or not sale.get("fill_event_id")
            or order.get("company_id") != pending.get("company_id")
            or (decision.get("ranking") or {}).get("artifact_sha256") != pending.get("ranking_sha256")):
        return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PENDING_BUY_ORDER_MISMATCH"}
    _append_event(home, {"event_id": f"paper-review-rebuy-{sale['order_id']}",
        "type": "PAPER_MODEL_REVIEW_REBUY", "at_utc": exp.now().isoformat(),
        "reason": f"تصمیم خرید {pending['symbol']} پیش از توقف ثبت شده بود؛ وضعیت بازبینی بازسازی شد.",
        "details": f"method={method}; candidate={pending['symbol']}; ranking_sha256={pending['ranking_sha256']}; snapshot={pending['ranking_snapshot']}."})
    state["history"].append({"kind": "rebuy_recovered", "symbol": pending["symbol"],
                             "ranking_sha256": pending["ranking_sha256"], "buy_order_id": order["order_id"]})
    state["pending_buy"] = None
    save_state(home, state)
    return {"status": "REVIEW_REBUY_RECOVERED", "symbol": pending["symbol"]}


def run_review(home: Path, method: str, method_run: Path, evidence: Path, cal: Path, config: dict):
    """One review pass for one account; returns a reportable outcome dict."""
    home = Path(home)
    policy = ensure_policy(config)
    if not policy:
        return None
    cadence = max(1, int(policy.get("cadence_sessions", 1)))
    account = exp.profile_account(home)
    order = account["paper_order"]
    state = load_state(home)
    pending = state.get("pending_buy")
    if pending and pending.get("phase") == "SELL_INTENT" and order.get("side") == "SELL":
        history = account.get("order_history") or []
        previous = (history[-1].get("order") or {}) if history else {}
        if (previous.get("order_id") != pending.get("sell_order_id")
                or order.get("company_id") != pending.get("sold_company_id")
                or not pending.get("sell_basis_path")
                or order.get("source_manifest") != pending.get("sell_basis_path")):
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PENDING_SELL_ORDER_MISMATCH"}
        if pending.get("review_event"):
            _append_event(home, pending["review_event"])
    if (pending and order.get("side") == "BUY" and pending.get("phase") == "SELL_INTENT"
            and order.get("order_id") != pending.get("sell_order_id")):
        return _recover_recorded_buy(home, account, state, pending, method)
    if not order.get("fill_event_id"):
        return {"status": "REVIEW_SKIPPED", "reason": "ORDER_NOT_FILLED"}
    side = order.get("side")

    if side == "SELL":
        pending = state.get("pending_buy")
        if not pending:
            return None
        if account["holdings"]:
            return {"status": "REVIEW_SKIPPED", "reason": "SELL_FILL_NOT_SETTLED"}
        snapshot = Path(pending["ranking_snapshot"])
        try:
            _, pinned = exp.pin_ranking(snapshot, home, method)
            age = _stale_days(pinned)
        except (ValueError, OSError, KeyError) as exc:
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PINNED_RANKING_INVALID", "detail": str(exc)}
        tops = [r for r in pinned.get("rows", []) if r.get("methods", {}).get(method, {}).get("rank") == 1]
        if (pinned.get("artifact_sha256") != pending.get("ranking_sha256") or len(tops) != 1
                or tops[0].get("company_id") != pending.get("company_id")):
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PINNED_RANKING_MISMATCH"}
        if age < 0 or age > int(policy.get("max_ranking_age_days", 7)):
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PINNED_RANKING_NOT_FRESH"}
        exp.decide(home, "BUY", method_run, ranking_source=snapshot)
        pending["buy_requested_at_utc"] = exp.now().isoformat()
        _append_event(home, {"event_id": f"paper-review-rebuy-{order['order_id']}",
            "type": "PAPER_MODEL_REVIEW_REBUY", "at_utc": exp.now().isoformat(),
            "reason": f"فروش فرضی تسویه شد؛ تصمیم خرید {pending['symbol']} طبق رتبه‌بندی pin‌شدهٔ بازبینی مدل ثبت شد.",
            "details": f"method={method}; candidate={pending['symbol']}; ranking_sha256={pending['ranking_sha256']}; snapshot={snapshot}."})
        state["history"].append({"kind": "rebuy", "symbol": pending["symbol"],
                                 "ranking_sha256": pending["ranking_sha256"],
                                 "requested_at_utc": pending["buy_requested_at_utc"]})
        state["pending_buy"] = None
        save_state(home, state)
        return {"status": "REVIEW_REBUY_RECORDED", "symbol": pending["symbol"]}

    # side == BUY with a trusted fill receipt: an open position to review.
    receipt = order.get("fill_receipt") or {}
    recorded = (receipt.get("calendar") or {}).get("validated_at_utc")
    if not recorded:
        return {"status": "REVIEW_SKIPPED", "reason": "FILL_RECEIPT_HAS_NO_CALENDAR_CLOCK"}
    anchor_day = str(order["designated_execution_session"] or "")
    if not anchor_day:
        return {"status": "REVIEW_SKIPPED", "reason": "FILL_SESSION_UNKNOWN"}
    try:
        answer = _calendar_answer(home, evidence, cal)
    except calendar.CalendarRefusal as exc:
        return {"status": "REVIEW_SKIPPED", "reason": f"CALENDAR_REFUSAL:{exc.code}"}
    if not answer["readiness"]["calendar_ready"]:
        return {"status": "REVIEW_SKIPPED",
                "reason": "CALENDAR_NOT_READY:" + ",".join(answer["readiness"]["blocking_reasons"])}
    sessions_after_fill = [s for s in answer["sessions_after_decision"]["sessions"]
                           if str(s) > anchor_day]
    if len(sessions_after_fill) < cadence:
        return {"status": "REVIEW_WAITING", "sessions_since_fill": len(sessions_after_fill),
                "cadence_sessions": cadence}
    index = _review_index(len(sessions_after_fill), cadence)
    event_id = f"paper-model-review-{order['order_id']}-{index}"
    held = account["holdings"][0]
    pending = state.get("pending_buy")
    if pending:
        # A crash after persisting the rotation intent can leave the original
        # filled BUY in place. Resume only that exact order and only after
        # revalidating the pinned ranking at this new decision time.
        if pending.get("phase") != "SELL_INTENT" or pending.get("sell_order_id") != order["order_id"]:
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PENDING_BUY_ORDER_MISMATCH"}
        if held.get("company_id") != pending.get("sold_company_id"):
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PENDING_BUY_HOLDING_MISMATCH"}
        try:
            _, pinned = exp.pin_ranking(Path(pending["ranking_snapshot"]), home, method)
            age = _stale_days(pinned)
        except (ValueError, OSError, KeyError) as exc:
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PINNED_RANKING_INVALID", "detail": str(exc)}
        matches = [r for r in pinned.get("rows", []) if r.get("methods", {}).get(method, {}).get("rank") == 1]
        if (pinned.get("artifact_sha256") != pending.get("ranking_sha256") or len(matches) != 1
                or matches[0].get("company_id") != pending.get("company_id")):
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PINNED_RANKING_MISMATCH"}
        if age < 0 or age > int(policy.get("max_ranking_age_days", 7)):
            return {"status": "REVIEW_RECOVERY_REQUIRED", "reason": "PINNED_RANKING_NOT_FRESH"}
        pending["sell_basis_path"] = str((method_run / "decision-basis.json").resolve())
        save_state(home, state)
        exp.decide(home, "SELL", method_run)
        return {"status": "REVIEW_ROTATE_SELL_RECOVERED", "sold": held["symbol"], "new": pending["symbol"]}
    source = ROOT / policy["ranking_source"]
    try:
        snapshot, rank = exp.pin_ranking(source, home, method)
    except ValueError as exc:
        return {"status": "REVIEW_RANKING_INVALID", "reason": str(exc)}
    tops = [r for r in rank.get("rows", []) if r.get("methods", {}).get(method, {}).get("rank") == 1]
    if len(tops) != 1:
        return {"status": "REVIEW_RANKING_INVALID", "reason": "UNIQUE_TOP_CANDIDATE_REQUIRED"}
    top = tops[0]
    stale_days = _stale_days(rank)
    if stale_days < 0:
        return {"status": "REVIEW_RANKING_INVALID", "reason": "RANKING_DATE_IN_FUTURE",
                "ranking_evaluation_date": rank.get("evaluation_date")}
    stale = stale_days > int(policy.get("max_ranking_age_days", 7))
    common = {"review_index": index, "sessions_since_fill": len(sessions_after_fill),
              "cadence_sessions": cadence, "ranking_evaluation_date": rank.get("evaluation_date"),
              "ranking_sha256": rank.get("artifact_sha256"), "ranking_snapshot": str(snapshot)}
    if stale or top["company_id"] == held["company_id"]:
        appended = _append_event(home, {"event_id": event_id,
            "type": "PAPER_MODEL_REVIEW_HOLD", "at_utc": exp.now().isoformat(),
            "reason": (f"بازبینی مدل {method}: رتبه‌بندی تازه ({rank.get('evaluation_date')}) بیش از {policy.get('max_ranking_age_days', 7)} روز قدیمی است؛ نگهداری بدون چرخش."
                       if stale else
                       f"بازبینی مدل {method}: نفر اول تازهٔ رتبه‌بندی ({rank.get('evaluation_date')}) همان {top['symbol']} است؛ نگهداری."),
            "details": json.dumps({**common, "held": held["symbol"], "candidate": top["symbol"],
                                   "stale_days": stale_days}, ensure_ascii=False)})
        return {"status": "REVIEW_ALREADY_RECORDED" if not appended else
                ("REVIEW_HOLD_RANKING_STALE" if stale else "REVIEW_HOLD"),
                "candidate": top["symbol"], "held": held["symbol"], **common}
    rotation_event = {"event_id": event_id, "type": "PAPER_MODEL_REVIEW_ROTATE",
        "at_utc": exp.now().isoformat(),
        "reason": f"بازبینی مدل {method}: نفر اول تازهٔ رتبه‌بندی ({rank.get('evaluation_date')}) {top['symbol']} است؛ تصمیم فروش {held['symbol']} ثبت شد و خرید جایگزین پس از تسویهٔ فروش ثبت می‌شود.",
        "details": json.dumps({**common, "sold": held["symbol"], "new": top["symbol"]}, ensure_ascii=False)}
    state["pending_buy"] = {"symbol": top["symbol"], "company_id": top["company_id"],
                            "ranking_snapshot": str(snapshot),
                            "ranking_sha256": rank.get("artifact_sha256"),
                            "requested_at_utc": exp.now().isoformat(),
                            "sold_symbol": held["symbol"], "sold_company_id": held["company_id"],
                            "sell_order_id": order["order_id"], "phase": "SELL_INTENT",
                            "sell_basis_path": str((method_run / "decision-basis.json").resolve()),
                            "review_event": rotation_event}
    state["history"].append({"kind": "rotate_intent", "sold": held["symbol"], "new": top["symbol"],
                             "ranking_sha256": rank.get("artifact_sha256"),
                             "requested_at_utc": state["pending_buy"]["requested_at_utc"]})
    save_state(home, state)
    exp.decide(home, "SELL", method_run)
    _append_event(home, rotation_event)
    return {"status": "REVIEW_ROTATE_SELL_RECORDED", "sold": held["symbol"], "new": top["symbol"], **common}
