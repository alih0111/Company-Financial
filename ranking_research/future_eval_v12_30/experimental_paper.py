"""Explicit experimental paper profile; uses the existing locked account/fill engine.

Financial readiness is disclosed, never promoted to approved. Execution still needs
hash-bound public calendar/price evidence after a real-time decision. No broker API.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ranking_research import paper_account_store as store, paper_calendar as calendar
from ranking_research.future_eval_v12_30.check_paper_account import apply_mark

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_HOME = ROOT / "ranking_research/output/experimental_paper"
DEFAULT_SNAPSHOT = ROOT / "docs/paper_portfolio_delivery/task-tf04d-report/fresh-market-20261026T225006048"
DEFAULT_RANKING = DEFAULT_SNAPSHOT / "public-isolated/latest-ranking.json"
DEFAULT_MARKET = ROOT / "ranking_research/output/paper_cycle/market/paper-cycle-20261026T190003904708Z-9bfb1a59/manifest.json"
PUBLIC = ROOT / "client/public/research/paper-experimental/status.json"
PROFILE = "EXPERIMENTAL_PAPER_V1"
LIMITATIONS = [
    "این حساب فقط آزمایش کاغذی است؛ هیچ سفارش واقعی ارسال نمی‌شود و بازده مدل تأیید نشده است.",
    "رتبه‌بندی P1/P3 با وزن‌ها و ماسک‌های موجود مصرف می‌شود؛ receipt مالی کل universe و تازگی همهٔ گزارش‌ها اثبات نشده است.",
    "پایان جلسه بر پایهٔ تقویم عمومی و فرض ثبت‌شده است؛ کامل‌بودن تقویم و اجرای صف تأیید رسمی ندارد.",
    "هزینهٔ هر سمت ۰٫۵٪ فرضی است. سرمایهٔ این حساب مستقل است و با حساب قبلی جمع نمی‌شود.",
    "فروش با فرمان صریح انجام می‌شود؛ زمان‌بندی رسمی O00 و تعویض خودکار ۶۳جلسه‌ای فعال نیست.",
]


def now():
    return dt.datetime.now(dt.timezone.utc)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def run(script, args, run_dir):
    command = [sys.executable, "-B", "-X", "utf8", str(SCRIPTS / script), *map(str, args)]
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=240)
    write(run_dir / (script + "." + uuid.uuid4().hex[:8] + ".json"),
          {"command": command, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    if proc.returncode:
        raise ValueError(proc.stderr.strip() or proc.stdout.strip() or f"{script}: {proc.returncode}")
    return json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}


def pin_ranking(source, home, method="P1"):
    """Validate the existing locked payload, then retain exact bytes for decisions."""
    from ranking_research.future_eval_v12_28.engine import canonical_json
    # Canonical serialization is the ranker's own contract; no score recomputation here.
    rank = load(source)
    claimed = rank.get("artifact_sha256")
    payload = {k: v for k, v in rank.items() if k != "artifact_sha256"}
    if hashlib.sha256(canonical_json(payload)).hexdigest() != claimed:
        raise ValueError("RANKING_HASH_MISMATCH")
    template = load(ROOT / "client/public/research/v12-36/paper-portfolio.json")
    rows = rank.get("rows", [])
    if (rank.get("contract_sha256") != template["contract"]["sha256"] or len(rows) != 254
            or len({r["company_id"] for r in rows}) != 254):
        raise ValueError("RANKING_CONTRACT_OR_UNIVERSE_MISMATCH")
    tops = [r for r in rows if r.get("methods", {}).get(method, {}).get("rank") == 1]
    if len(tops) != 1 or not math.isfinite(float(tops[0]["methods"][method]["score"])):
        raise ValueError("RANKING_CANDIDATE_INVALID")
    target = home / "snapshots" / (sha(source) + ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != Path(source).read_bytes():
        raise ValueError("SNAPSHOT_COLLISION")
    if not target.exists():
        target.write_bytes(Path(source).read_bytes())
    return target, rank


def profile_account(home):
    account = load(home / "account.json")
    store.validate_account(account)
    if account.get("profile") != PROFILE or account.get("real_order_submitted") is not False:
        raise ValueError("EXPERIMENTAL_PROFILE_REQUIRED")
    method = account.get("paper_method", "P1")
    ranking_path = Path(account["experimental_inputs"].get("ranking_path", home / "ranking.json"))
    if sha(ranking_path) != account["experimental_inputs"]["ranking_file_sha256"]:
        raise ValueError("PINNED_RANKING_FILE_CHANGED")
    if account.get("active_decision"):
        rules_bytes = (home / "rules.json").read_bytes()
        calendar.check_provider_contract(account=account, provider="public", rules_bytes=rules_bytes, rules_doc=json.loads(rules_bytes))
    return account


def publish(home, outcome, public_path=None):
    account = profile_account(home)
    doc = {"profile": PROFILE, "updated_at_utc": now().isoformat(), "outcome": outcome,
           "strict_readiness": "BLOCKED", "strict_decision_authorized": False,
           "limitations": LIMITATIONS, "account": account, "account_sha256": sha(home / "account.json"),
           "scheduler_enabled_by_this_profile": False}
    write(home / "status.json", doc)
    if public_path:
        write(public_path, doc)
    return doc


def decide(home, side, run_dir, ranking_source=None):
    account = profile_account(home)
    method = account.get("paper_method", "P1")
    ranking_path = Path(account["experimental_inputs"].get("ranking_path", home / "ranking.json"))
    if ranking_source is not None:
        ranking_path, _ = pin_ranking(ranking_source, home, method)
    rank = load(ranking_path)
    if side == "SELL":
        if len(account["holdings"]) != 1:
            raise ValueError("NO_HOLDING_TO_SELL")
        candidate = account["holdings"][0]
    else:
        candidate = next(r for r in rank["rows"] if r.get("methods", {}).get(method, {}).get("rank") == 1)
    basis = run_dir / "decision-basis.json"
    write(basis, {"candidate": {"symbol": candidate["symbol"], "company_id": candidate["company_id"]},
                  "ranking_file_sha256": sha(ranking_path), "sources": []})
    return run("register_paper_decision.py", ["--account", home / "account.json", "--ranking", ranking_path,
               "--rules", home / "rules.json", "--evidence", basis, "--calendar-provider", "public", "--side", side], run_dir)


def initialize(home, ranking, run_dir, method="P1"):
    if (home / "account.json").exists() or (home / "rules.json").exists():
        raise ValueError("ACCOUNT_ALREADY_EXISTS; use update or status")
    snap, _ = pin_ranking(ranking, home, method)
    (home / "ranking.json").write_bytes(snap.read_bytes())
    staging = run_dir / "bootstrap"
    staging.mkdir()
    (staging / "ranking.json").write_bytes(snap.read_bytes())
    run("create_public_paper_account.py", ["--ranking", snap, "--output-account", staging / "account.json",
        "--output-rules", staging / "rules.json", "--account-id", "experimental-" + method.lower() + "-" + uuid.uuid4().hex[:12], "--method", method], run_dir)
    def activate(account):
        account.update(profile=PROFILE, strict_decision_authorized=False, data_limitations=LIMITATIONS,
                       experimental_inputs={"ranking_file_sha256": sha(home / "ranking.json"), "source": str(ranking)},
                       status="EXPERIMENTAL_PAPER_ACTIVE", realized_pnl_toman=0)
        account["event_log"].append({"event_id": "experimental-consent", "type": "EXPERIMENTAL_PROFILE_ACCEPTED",
            "at_utc": now().isoformat(), "reason": "انتخاب صریح کاربر: سبد کاغذی آزمایشی با اعلام محدودیت داده",
            "details": "پذیرش محدودیت داده؛ بدون تأیید سیاست سخت‌گیرانه یا کیفیت سرمایه‌گذاری؛ حساب جدا."})
    store.read_modify_write(staging / "account.json", activate)
    outcome = decide(staging, "BUY", run_dir)
    (home / "rules.json").write_bytes((staging / "rules.json").read_bytes())
    store.write_account_atomic(home / "account.json", load(staging / "account.json"))
    return outcome


def acquire(home, run_dir, market_map):
    account = profile_account(home)
    candidate_dir, calendar_dir = run_dir / "candidate", run_dir / "calendar"
    run("acquire_paper_candidate_evidence.py", ["--account", home / "account.json", "--output-dir", candidate_dir,
        "--security-map", market_map], run_dir)
    run("acquire_public_market_calendar.py", ["--window-start", account["active_decision"]["decision_local_date"].replace("-", ""),
        "--candidate-symbol", account["paper_order"]["symbol"], "--output-dir", calendar_dir,
        "--no-cross-check"], run_dir)
    candidate_pointer = load(candidate_dir / "latest-manifest.json")
    candidates = list(calendar_dir.glob("manifest.*.json"))
    if len(candidates) != 1:
        raise ValueError("CALENDAR_INVOCATION_NOT_UNIQUE")
    evidence = ROOT / candidate_pointer["manifest_path"]
    if sha(evidence) != candidate_pointer["manifest_sha256"]:
        raise ValueError("CANDIDATE_POINTER_HASH_MISMATCH")
    return evidence, candidates[0]


def mark_verified(home, evidence_path, calendar_path, apply):
    """Mark only a new completed positive-volume bar, refusing unresolved share changes."""
    with store.account_write_lock(home / "account.json"):
        account = profile_account(home)
        if len(account["holdings"]) != 1:
            return {"status": "CASH_ONLY", "changed": False}
        held, decision = account["holdings"][0], account["active_decision"]
        evidence = load(evidence_path)
        if evidence["candidate"]["company_id"] != held["company_id"]:
            raise ValueError("MARK_IDENTITY_MISMATCH")
        ins = str(evidence["ins_code"])
        policy_path = calendar.DEFAULT_PUBLIC_POLICY_PATH
        answer = calendar.resolve_public_calendar(manifest_path=calendar_path, expected_manifest_sha256=sha(calendar_path),
            policy=load(policy_path), policy_sha256=sha(policy_path), candidate={"symbol": held["symbol"], "ins_code": ins},
            decision_local_date=decision["decision_local_date"], decision_at_utc=dt.datetime.fromisoformat(decision["decided_at_utc"]),
            now_utc=now(), consumption_mode="live-preview")
        if not answer["readiness"]["calendar_ready"]:
            raise ValueError("CALENDAR_NOT_READY")
        sources = {s["key"]: s for s in evidence["sources"]}
        bodies = {}
        for key in ("candidate_daily", "candidate_share_changes"):
            source = sources[key]
            received = calendar.parse_utc(source["retrieved_at_utc"], field=key)
            if not dt.timedelta(0) <= now() - received <= dt.timedelta(hours=6):
                raise ValueError("MARK_SOURCE_NOT_FRESH")
            body = gzip.decompress((ROOT / source["raw_path"]).read_bytes())
            if hashlib.sha256(body).hexdigest() != source["raw_sha256"]:
                raise ValueError("MARK_RAW_HASH_MISMATCH")
            bodies[key] = json.loads(body)
        bars = bodies["candidate_daily"]["closingPriceDaily"]
        changes = bodies["candidate_share_changes"]["instrumentShareChange"]
        if any(str(r.get("insCode")) != ins for r in bars + changes):
            raise ValueError("MARK_RAW_IDENTITY_MISMATCH")
        accepted = set(answer["sessions_after_decision"]["sessions"])
        last_day = held["last_price_date"].replace("-", "")
        rows = [r for r in bars if str(r["dEven"]) in accepted and str(r["dEven"]) > last_day
                and math.isfinite(float(r.get("pClosing", 0))) and float(r.get("pClosing", 0)) > 0
                and math.isfinite(float(r.get("qTotTran5J", 0))) and float(r.get("qTotTran5J", 0)) > 0]
        if not rows:
            return {"status": "NO_NEW_MARK", "changed": False}
        bar = max(rows, key=lambda r: str(r["dEven"]))
        day = str(bar["dEven"])
        if sum(str(r["dEven"]) == day for r in bars) != 1:
            raise ValueError("DUPLICATE_MARK_BAR")
        if any(last_day < str(r.get("dEven", "")) <= day and r.get("numberOfShareNew") != r.get("numberOfShareOld") for r in changes):
            raise ValueError("CORPORATE_ACTION_REQUIRES_MANUAL_RESOLUTION")
        iso_day = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        account["accounting"] = apply_mark(held, account["cash_toman"], bar["pClosing"], iso_day, account.get("realized_pnl_toman", 0))
        account["event_log"].append({"event_id": f"experimental-mark-{held['company_id']}-{day}", "type": "PAPER_MARK_TO_MARKET",
            "at_utc": now().isoformat(), "reason": "ارزش‌گذاری با قیمت مثبت جلسهٔ عمومی پذیرفته‌شده",
            "details": f"{held['symbol']}; close={bar['pClosing']} IRR; date={iso_day}; evidence={sha(evidence_path)}; calendar={sha(calendar_path)}"})
        if apply:
            store.write_account_atomic(home / "account.json", account)
        return {"status": "MARK_APPLIED" if apply else "MARK_PREVIEW", "changed": apply, "date": iso_day, "accounting": account["accounting"]}


def update(home, run_dir, evidence, cal, apply):
    account = profile_account(home)
    order = account["paper_order"]
    if order.get("fill_event_id"):
        return mark_verified(home, evidence, cal, apply)
    args = ["--account", home / "account.json", "--rules", home / "rules.json", "--calendar-provider", "public",
            "--session-calendar-manifest", cal, "--calendar-manifest-sha256", sha(cal), "--evidence-manifest", evidence]
    if apply:
        args.append("--apply-fill")
    return run("apply_paper_fill.py", args, run_dir)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("start", "update", "preview", "sell", "buy", "status"))
    p.add_argument("--method", choices=("P1", "P3"), default="P1")
    p.add_argument("--home", type=Path, default=DEFAULT_HOME)
    p.add_argument("--ranking", type=Path, help="Pinned ranking for start or a subsequent buy")
    p.add_argument("--market-map", type=Path, default=DEFAULT_MARKET)
    p.add_argument("--evidence", type=Path)
    p.add_argument("--calendar", type=Path)
    p.add_argument("--publish", action="store_true", help="Publish only the separate experimental view")
    a = p.parse_args()
    home = a.home.resolve()
    if not home.is_relative_to(ROOT / "ranking_research/output"):
        raise SystemExit("EXPERIMENTAL_HOME_MUST_BE_UNDER_RESEARCH_OUTPUT")
    home.mkdir(parents=True, exist_ok=True)
    run_dir = home / "runs" / (now().strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:6])
    run_dir.mkdir(parents=True)
    try:
        # Serialize complete invocations as well as individual account commits.
        with store.account_write_lock(home / "controller"):
            if a.action == "start":
                outcome = {"status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE", "decision": initialize(home, a.ranking or DEFAULT_RANKING, run_dir, a.method)}
            elif a.action in ("buy", "sell"):
                outcome = {"status": "DECISION_RECORDED", "decision": decide(home, a.action.upper(), run_dir, a.ranking)}
            elif a.action in ("update", "preview"):
                profile_account(home)
                if bool(a.evidence) != bool(a.calendar):
                    raise ValueError("PROVIDE_BOTH_EVIDENCE_AND_CALENDAR")
                evidence, cal = (a.evidence.resolve(), a.calendar.resolve()) if a.evidence else acquire(home, run_dir, a.market_map)
                outcome = update(home, run_dir, evidence, cal, a.action == "update")
            else:
                outcome = {"status": "STATUS_ONLY"}
            doc = publish(home, outcome, PUBLIC if a.publish else None)
            write(run_dir / "result.json", {"status": "OK", "outcome": outcome, "account_sha256": doc["account_sha256"]})
        print(json.dumps({"status": outcome["status"], "account": str(home / "account.json"), "view": str(PUBLIC if a.publish else home / "status.json")}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired, calendar.CalendarRefusal) as exc:
        outcome = {"status": "BLOCKED_EXECUTION", "reason": str(exc)}
        write(run_dir / "result.json", outcome)
        if (home / "account.json").exists():
            try:
                publish(home, outcome, PUBLIC if a.publish else None)
            except (ValueError, OSError, KeyError):
                pass
        print(json.dumps(outcome, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
