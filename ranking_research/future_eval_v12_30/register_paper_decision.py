"""Pin an append-only, non-retroactive paper buy decision and pending order."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import argparse
import sys
from pathlib import Path
try:
    from ranking_research import paper_account_store
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from ranking_research import paper_account_store

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
RANKING = ROOT / "client/public/research/v12-36/latest-ranking.json"
RULES = ROOT / "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json"
EVIDENCE = ROOT / "ranking_research/output/paper_v12_38_first_fill/manifest.json"


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _main_locked(args: argparse.Namespace) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    account_path, ranking_path = args.account.resolve(), args.ranking.resolve()
    rules_path, evidence_path = args.rules.resolve(), args.evidence.resolve()
    policy_path = args.calendar_policy.resolve()
    account = json.loads(account_path.read_text(encoding="utf-8"))
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    rules_bytes = rules_path.read_bytes()
    rules = json.loads(rules_bytes)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    experimental = account.get("profile") == "EXPERIMENTAL_PAPER_V1"
    side = getattr(args, "side", "BUY")
    method = account.get("paper_method", "P1")
    if method not in ("P1", "P3"):
        raise SystemExit("UNSUPPORTED_PAPER_METHOD")
    if side == "SELL" and not experimental:
        raise SystemExit("SELL_REQUIRES_EXPERIMENTAL_ACCOUNT")
    if account.get("active_decision") or account.get("paper_order"):
        prior = account.get("paper_order") or {}
        if not experimental or prior.get("status") not in ("PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE", "EXPIRED_NO_FILL"):
            raise SystemExit("ACTIVE_PAPER_DECISION_OR_ORDER_ALREADY_EXISTS; append-only manual review required")
        account.setdefault("order_history", []).append({"decision": account["active_decision"], "order": prior})
    if experimental:
        if side == "SELL":
            if len(account["holdings"]) != 1:
                raise SystemExit("SELL_REQUIRES_EXACTLY_ONE_HOLDING")
            held = account["holdings"][0]
            candidate = {"company_id": held["company_id"], "symbol": held["symbol"], "rank": None, "score": None, "coverage": None}
        else:
            if account["holdings"]:
                raise SystemExit("BUY_REQUIRES_EMPTY_HOLDINGS")
            tops = [r for r in ranking.get("rows", []) if r.get("methods", {}).get(method, {}).get("rank") == 1]
            if len(tops) != 1:
                raise SystemExit("UNIQUE_P1_CANDIDATE_REQUIRED")
            row = tops[0]
            candidate = {"company_id": row["company_id"], "symbol": row["symbol"], "rank": 1,
                         "score": row["methods"][method]["score"], "coverage": row["methods"][method]["financial_factor_coverage"]}
        account["ranking"] = {"dataset_id": ranking.get("dataset_id"), "evaluation_date": ranking.get("evaluation_date"),
                              "status": ranking.get("status"), "artifact_sha256": ranking.get("artifact_sha256"), "top_candidate": candidate}
        account.setdefault("experimental_inputs", {}).update(ranking_file_sha256=file_sha(ranking_path), ranking_path=str(ranking_path))
    candidate = account["ranking"]["top_candidate"]
    if not candidate or ranking.get("artifact_sha256") != account["ranking"].get("artifact_sha256"):
        raise SystemExit("PINNED_RANKING_SNAPSHOT_MISMATCH")
    if (candidate["symbol"] != evidence.get("candidate", {}).get("symbol")
            or candidate["company_id"] != evidence.get("candidate", {}).get("company_id")):
        raise SystemExit("CANDIDATE_IDENTITY_CHANGED_SINCE_EVIDENCE_ACQUISITION")
    p1 = [x for x in ranking.get("rows", []) if x.get("company_id") == candidate["company_id"]]
    if side == "BUY" and (len(p1) != 1 or p1[0].get("methods", {}).get(method, {}).get("rank") != 1):
        raise SystemExit("CANDIDATE_NOT_RANK_ONE_IN_PINNED_P1_ARTIFACT")
    if args.fixture_clock and not args.fixture:
        raise SystemExit("FIXTURE_CLOCK_REQUIRES_EXPLICIT_FIXTURE_MODE")
    instant = dt.datetime.fromisoformat(args.fixture_clock) if args.fixture_clock else dt.datetime.now(dt.timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=dt.timezone.utc)
    instant = instant.astimezone(dt.timezone.utc)
    now = instant.isoformat()
    local_date = instant.astimezone(dt.timezone(dt.timedelta(hours=3, minutes=30))).date().isoformat()
    decision_id = "paper-decision-" + hashlib.sha256(
        f"{account['account_id']}|{now}|{ranking['artifact_sha256']}".encode()).hexdigest()[:20]
    order_id = "paper-order-" + hashlib.sha256(f"{decision_id}|{candidate['company_id']}".encode()).hexdigest()[:20]
    rules_sha = hashlib.sha256(rules_bytes).hexdigest()
    policy_binding = None
    if args.calendar_provider == "public":
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        policy_binding = {"id": policy["policy_id"], "sha256": file_sha(policy_path),
                          "provider": policy["provider"], "version": policy["version"]}
        if rules.get("calendar_policy") != policy_binding:
            raise SystemExit("PUBLIC_POLICY_RULES_BINDING_MISMATCH")
    decision = {
        "decision_id": decision_id, "decided_at_utc": now,
        "decision_local_date": local_date, "decision_kind": f"PAPER_ONLY_{side}_DECISION_NOT_O00",
        "candidate": {k: candidate.get(k) for k in ("symbol", "company_id", "rank", "score", "coverage")},
        "ranking": {"dataset_id": account["ranking"]["dataset_id"], "artifact_id": ranking["artifact_id"],
                    "evaluation_date": ranking["evaluation_date"],
                    "status": ranking["status"], "artifact_sha256": ranking["artifact_sha256"],
                    "scored": ranking.get("scored_count", {}).get(method), "universe": 254},
        "execution_rules": {"rule_id": rules["rule_id"], "sha256": rules_sha,
                            "path": str(rules_path)},
        "evidence_manifest_sha256": file_sha(evidence_path),
        "coverage_limitation": f"رتبه‌بندی {ranking.get('status')}؛ {method}: {ranking.get('scored_count', {}).get(method)} از {ranking.get('universe_count', 254)}. کیفیت کامل داده و بازده تأیید نشده‌اند.",
    }
    if policy_binding:
        decision["calendar_policy"] = policy_binding
    order = {
        "order_id": order_id, "decision_id": decision_id,
        "side": side,
        "symbol": candidate["symbol"], "company_id": candidate["company_id"],
        "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
        "created_at_utc": now,
        "designated_execution_session": None,
        "designated_execution_price_rial": None,
        "expires_after_official_sessions": 3,
        "eligible_session_count_observed": 0,
        "fill_event_id": None,
        "waiting_reason": "در انتظار شواهد قیمت و حجم نخستین جلسهٔ پذیرفته‌شده پس از تصمیم تازه؛ هیچ معامله‌ای به گذشته منتقل نمی‌شود.",
        "queue_limitation": "اجرای فرضی با محدودیت دادهٔ صف؛ پیکربندی مبتنی بر close روزانه صف/اولویت/اجرای واقعی را اثبات نمی‌کند.",
        "source_manifest": str(evidence_path),
        "source_manifest_sha256": file_sha(evidence_path),
    }
    if policy_binding:
        order["calendar_policy"] = policy_binding
    account["active_decision"] = decision
    account["paper_order"] = order
    account["assumptions_version"] = rules["rule_id"]
    account["candidate_status"] = ("نامزد فروش" if side == "SELL" else "نامزد خرید") + "؛ سفارش کاغذی ثبت شده و در انتظار نخستین جلسهٔ واجد شرایط"
    account["waiting_reason"] = order["waiting_reason"]
    account["order_created"] = True
    account["execution_recorded"] = False
    account["status"] = order["status"]
    account["assumptions"] = [
        {"id": "decision", "label": "زمان و مبنای تصمیم", "value": now + " UTC؛ رتبه‌بندی ثابت‌شده در active_decision", "status": "ثبت‌شده"},
        {"id": "price", "label": "قیمت فرضی اجرا", "value": "قیمت پایانی TSETMC در نخستین جلسهٔ رسمی پس از تصمیم", "status": "فرض آزمایشی؛ محدودیت دادهٔ صف"},
        {"id": "lot", "label": "lot", "value": "یک سهم؛ تعداد صحیح", "status": "فرض آزمایشی پذیرفته‌شده"},
        {"id": "fee", "label": "هزینه", "value": "۰٫۵٪ در هر سمت", "status": "فرض آزمایشی پذیرفته‌شده؛ هزینهٔ واقعی نیست"},
        {"id": "expiry", "label": "انقضا", "value": "پایان سومین جلسهٔ رسمی پس از تصمیم، طبق قاعدهٔ نسخه‌دار", "status": "فرض آزمایشی پذیرفته‌شده"},
    ]
    account["event_log"].extend([
        {"event_id": decision_id, "type": f"PAPER_{side}_DECISION_RECORDED", "at_utc": now,
         "reason": "ثبت تصمیم تازه پس از پذیرش قواعد اجرای آزمایشی؛ بدون انتقال به گذشته.",
         "details": f"{candidate['symbol']}؛ side={side}؛ dataset={account['ranking']['dataset_id']}; ranking_sha256={ranking['artifact_sha256']}; rules={rules['rule_id']} sha256={rules_sha}; {method}={ranking.get('scored_count', {}).get(method)}/{ranking.get('universe_count', 254)}."},
        {"event_id": order_id, "type": "PAPER_ORDER_PENDING", "at_utc": now,
         "reason": order["waiting_reason"],
         "details": f"سفارش داخلی تک‌سهمی؛ مبنا close نخستین جلسهٔ رسمی بعد از تصمیم؛ fee فرضی 0.5%؛ انقضا بعد از 3 جلسه؛ {order['queue_limitation']}"},
    ])
    if policy_binding:
        account["calendar_policy"] = policy_binding
    paper_account_store.write_account_atomic(account_path, account)
    print(json.dumps({"decision": decision, "order": order, "cash_toman": account["cash_toman"],
                      "holdings": len(account["holdings"]), "official_ledger_linked": account["official_future_evaluation_ledger_linked"]}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", type=Path, default=ACCOUNT)
    parser.add_argument("--ranking", type=Path, default=RANKING)
    parser.add_argument("--rules", type=Path, default=RULES)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE)
    parser.add_argument("--calendar-policy", type=Path, default=ROOT / "ranking_research/paper_calendar_policy.public-paper-v1.json")
    parser.add_argument("--calendar-provider", choices=("nscstart", "public"), default="nscstart")
    parser.add_argument("--fixture", action="store_true", help="explicitly label a synthetic fixture execution")
    parser.add_argument("--fixture-clock", help="fixture-only ISO clock; never for operational decisions")
    parser.add_argument("--side", choices=("BUY", "SELL"), default="BUY")
    args, _unknown = parser.parse_known_args()
    with paper_account_store.account_write_lock(args.account.resolve()):
        _main_locked(args)


if __name__ == "__main__":
    main()
