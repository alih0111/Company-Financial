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
    if account.get("active_decision") or account.get("paper_order"):
        raise SystemExit("ACTIVE_PAPER_DECISION_OR_ORDER_ALREADY_EXISTS; append-only manual review required")
    candidate = account["ranking"]["top_candidate"]
    if not candidate or ranking.get("artifact_sha256") != account["ranking"].get("artifact_sha256"):
        raise SystemExit("PINNED_RANKING_SNAPSHOT_MISMATCH")
    if (candidate["symbol"] != evidence.get("candidate", {}).get("symbol")
            or candidate["company_id"] != evidence.get("candidate", {}).get("company_id")):
        raise SystemExit("CANDIDATE_IDENTITY_CHANGED_SINCE_EVIDENCE_ACQUISITION")
    p1 = [x for x in ranking.get("rows", []) if x.get("company_id") == candidate["company_id"]]
    if len(p1) != 1 or p1[0].get("methods", {}).get("P1", {}).get("rank") != 1:
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
        "decision_local_date": local_date, "decision_kind": "PAPER_ONLY_BUY_DECISION_NOT_O00",
        "candidate": {k: candidate.get(k) for k in ("symbol", "company_id", "rank", "score", "coverage")},
        "ranking": {"dataset_id": account["ranking"]["dataset_id"], "artifact_id": ranking["artifact_id"],
                    "evaluation_date": ranking["evaluation_date"],
                    "status": ranking["status"], "artifact_sha256": ranking["artifact_sha256"],
                    "scored": ranking.get("scored_count", {}).get("P1"), "universe": 254},
        "execution_rules": {"rule_id": rules["rule_id"], "sha256": rules_sha,
                            "path": str(rules_path)},
        "evidence_manifest_sha256": file_sha(evidence_path),
        "coverage_limitation": "رتبه‌بندی P1 آماده‌سازی تأییدنشده است؛ فقط 166 از 254 نماد امتیاز دارند و 88 بدون امتیازند. این تصمیم تک‌سهمی از رتبهٔ اول قابل امتیازدهی می‌آید؛ پوشش محدودیت تصمیم است.",
    }
    if policy_binding:
        decision["calendar_policy"] = policy_binding
    order = {
        "order_id": order_id, "decision_id": decision_id,
        "symbol": candidate["symbol"], "company_id": candidate["company_id"],
        "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
        "created_at_utc": now,
        "designated_execution_session": None,
        "designated_execution_price_rial": None,
        "expires_after_official_sessions": 3,
        "eligible_session_count_observed": 0,
        "fill_event_id": None,
        "waiting_reason": "منبع رسمی اکنون آخرین جلسهٔ کامل را 2026-10-21 اعلام می‌کند؛ هنوز جلسه‌ای بعد از تصمیم ثبت نشده است. تاریخ جلسهٔ بعد را حدس نمی‌زنیم. قیمت نامزد نیز فعلاً تا 2026-10-21 است.",
        "queue_limitation": "اجرای فرضی با محدودیت دادهٔ صف؛ پیکربندی مبتنی بر close روزانه صف/اولویت/اجرای واقعی را اثبات نمی‌کند.",
        "source_manifest": str(evidence_path),
        "source_manifest_sha256": file_sha(evidence_path),
    }
    if policy_binding:
        order["calendar_policy"] = policy_binding
    account["active_decision"] = decision
    account["paper_order"] = order
    account["assumptions_version"] = rules["rule_id"]
    account["candidate_status"] = "نامزد خرید؛ سفارش کاغذی ثبت شده و در انتظار نخستین جلسهٔ واجد شرایط"
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
        {"event_id": decision_id, "type": "PAPER_BUY_DECISION_RECORDED", "at_utc": now,
         "reason": "ثبت تصمیم تازه پس از پذیرش قواعد اجرای آزمایشی؛ بدون انتقال به گذشته.",
         "details": f"{candidate['symbol']}؛ P1 rank 1؛ dataset={account['ranking']['dataset_id']}; ranking_sha256={ranking['artifact_sha256']}; rules={rules['rule_id']} sha256={rules_sha}; امتیازدار 166/254."},
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
    args, _unknown = parser.parse_known_args()
    with paper_account_store.account_write_lock(args.account.resolve()):
        _main_locked(args)


if __name__ == "__main__":
    main()
