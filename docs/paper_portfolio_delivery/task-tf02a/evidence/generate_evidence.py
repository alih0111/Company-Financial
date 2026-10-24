"""TF-02A delivery evidence: real entrypoint runs on temporary accounts.

Runs the actual entrypoints (subprocess, the same redirected-constant pattern
the atomic-writer tests use) against artificial fixtures in a temp directory
and records their stdout/refusals, replay clocks, debit/fill/event/receipt
counts, account hashes before/after every refusal, and the six protected
ledger hashes. No network request is made; the real account and rules files
are only ever read or hashed. Re-running this script never edits any earlier
evidence file of a previous delivery.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from ranking_research.tests import test_public_market_calendar as fx          # noqa: E402
from ranking_research.tests import test_paper_calendar_interface as f         # noqa: E402
from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf  # noqa: E402

HERE = Path(__file__).parent
NOW = fx.NOW
NEXT_DAY = NOW + dt.timedelta(days=1)
SHORT_DAYS = ["20260901", "20260902", "20260905"]
PYTHON = sys.executable

FILL_CHILD = r'''import os,sys
from pathlib import Path
from ranking_research.future_eval_v12_30 import apply_paper_fill as m
m.ROOT=Path(sys.argv[1]); m.ACCOUNT=Path(sys.argv[2]); m.RULES=Path(sys.argv[3])
argv=sys.argv[4:]
mode=None
if argv and argv[-1] in ("DIE_BEFORE_REPLACE","DIE_AFTER_REPLACE"):
    mode=argv[-1]; argv=argv[:-1]
real=os.replace
if mode=="DIE_BEFORE_REPLACE":
 os.replace=lambda *a,**k: os._exit(75)
elif mode=="DIE_AFTER_REPLACE":
 def die_after(*a,**k): real(*a,**k); os._exit(74)
 os.replace=die_after
sys.argv=['apply_paper_fill.py',*argv]
m.main()
'''


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_fill(root: Path, account: Path, rules: Path, argv, mode=None):
    result = subprocess.run(
        [PYTHON, "-c", FILL_CHILD, str(root), str(account), str(rules), *argv,
         *( [mode] if mode else [] )],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120)
    return {"exit_code": result.returncode, "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()}


def fill_argv(calendar_path, calendar_sha, evidence_path, *, clock, apply=True,
              provider="public", calendar_sha_override=None):
    argv = ["--session-calendar-manifest", str(calendar_path),
            "--evidence-manifest", str(evidence_path),
            "--calendar-provider", provider,
            "--calendar-policy", str(f.POLICY_PATH),
            "--reference-now-utc", clock.isoformat()]
    if provider == "public":
        argv += ["--calendar-manifest-sha256",
                 calendar_sha_override or calendar_sha]
    if apply:
        argv.append("--apply-fill")
    return argv


def account_state(account: Path):
    doc = json.loads(account.read_text(encoding="utf-8"))
    return {"cash_toman": doc["cash_toman"], "holding_count": len(doc["holdings"]),
            "event_count": len(doc["event_log"]),
            "has_receipt": bool(doc["paper_order"].get("fill_receipt")),
            "order_status": doc["paper_order"]["status"]}


def main() -> None:
    evidence = {}
    with tempfile.TemporaryDirectory(prefix="tf02a-evidence-") as directory:
        base = Path(directory)
        path, sha, manifest = f.public_package(
            base / "pkg", primary=SHORT_DAYS, secondary=SHORT_DAYS,
            watermark="20260905;20260905")
        # --- 1) healthy apply, next-day replay at the recorded clock -------- #
        root = base / "replay"
        account, rules, root = f._public_account_fixture(root)
        evidence_path = f._public_evidence(root)
        argv = fill_argv(path, sha, evidence_path,
                         clock=NOW + dt.timedelta(minutes=5))
        first = run_fill(root, account, rules, argv)
        filled_doc = json.loads(account.read_text(encoding="utf-8"))
        state_after_first = account_state(account)
        filled_sha = sha_file(account)
        receipt_calendar = filled_doc["paper_order"]["fill_receipt"]["calendar"]
        next_day = run_fill(root, account, rules, fill_argv(
            path, sha, evidence_path, clock=NEXT_DAY))
        after_replay_sha = sha_file(account)
        evidence["public_fill_then_next_day_replay"] = {
            "first_run": first, "first_run_state": state_after_first,
            "receipt_calendar": {k: receipt_calendar[k] for k in
                                 ("policy_id", "manifest_sha256",
                                  "validated_at_utc", "evidence_manifest_sha256",
                                  "completion_type", "assumed_completion")},
            "recorded_validation_clock": receipt_calendar["validated_at_utc"],
            "next_day_retry_clock": NEXT_DAY.isoformat(),
            "next_day_retry": next_day,
            "state_after_replay": account_state(account),
            "account_sha256_before_replay": filled_sha,
            "account_sha256_after_replay": after_replay_sha,
            "bytes_unchanged_by_replay": filled_sha == after_replay_sha,
        }
        # --- 2) refusals leave the temp account byte-identical ------------- #
        refusals = {}
        manifest_original_bytes = path.read_bytes()
        # (a) inner window disagrees with the decision day, wrong-day price
        changed = copy.deepcopy(manifest)
        changed["policy"]["window_start"] = "20260902"
        path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")
        wrong_sha = sha_file(path)
        root_w = base / "window"
        account_w, rules_w, root_w = f._public_account_fixture(root_w)
        ev_w = f._public_evidence(root_w, bar_day="20260905")
        before_w = sha_file(account_w)
        run_w = run_fill(root_w, account_w, rules_w, fill_argv(
            path, wrong_sha, ev_w, clock=NOW + dt.timedelta(minutes=5)))
        refusals["inner_window_mismatch_wrong_day_price"] = {
            "run": run_w, "account_sha_before": before_w,
            "account_sha_after": sha_file(account_w),
            "bytes_unchanged": before_w == sha_file(account_w),
            "state": account_state(account_w)}
        # byte-exact restore: every later case pins the original manifest sha
        path.write_bytes(manifest_original_bytes)
        # (b) fresh bound account + same raw one day later: stale, no purchase
        root_f = base / "fresh"
        account_f, rules_f, root_f = f._public_account_fixture(root_f)
        ev_f = f._public_evidence(root_f)
        before_f = sha_file(account_f)
        run_f = run_fill(root_f, account_f, rules_f, fill_argv(
            path, sha, ev_f, clock=NEXT_DAY))
        refusals["fresh_account_next_day_stale"] = {
            "run": run_f, "account_sha_before": before_f,
            "account_sha_after": sha_file(account_f),
            "bytes_unchanged": before_f == sha_file(account_f),
            "state": account_state(account_f)}
        # (c) corrupted pinned cross-check raw
        root_c = base / "cross"
        account_c, rules_c, root_c = f._public_account_fixture(root_c)
        ev_c = f._public_evidence(root_c)
        raw_path = tf.resolve_repo_path(
            manifest["stock_cross_check"]["daily_inputs"]["TEST"]["path"])
        original_raw = raw_path.read_bytes()
        raw_path.write_bytes(__import__("gzip").compress(b"corrupted fixture"))
        before_c = sha_file(account_c)
        run_c = run_fill(root_c, account_c, rules_c, fill_argv(
            path, sha, ev_c, clock=NOW + dt.timedelta(minutes=5)))
        raw_path.write_bytes(original_raw)
        refusals["corrupted_pinned_cross_raw"] = {
            "run": run_c, "account_sha_before": before_c,
            "account_sha_after": sha_file(account_c),
            "bytes_unchanged": before_c == sha_file(account_c),
            "state": account_state(account_c)}
        # (d) missing order binding + wrong account binding (the review's buy)
        root_b = base / "binding"
        account_b, rules_b, root_b = f._public_account_fixture(root_b)
        doc_b = json.loads(account_b.read_text(encoding="utf-8"))
        doc_b["calendar_policy"] = {"id": "WRONG_ACCOUNT_POLICY", "sha256": "0" * 64}
        doc_b["paper_order"].pop("calendar_policy", None)
        account_b.write_text(json.dumps(doc_b), encoding="utf-8")
        ev_b = f._public_evidence(root_b)
        before_b = sha_file(account_b)
        run_b = run_fill(root_b, account_b, rules_b, fill_argv(
            path, sha, ev_b, clock=NOW + dt.timedelta(minutes=5)))
        refusals["wrong_account_and_missing_order_binding"] = {
            "run": run_b, "account_sha_before": before_b,
            "account_sha_after": sha_file(account_b),
            "bytes_unchanged": before_b == sha_file(account_b),
            "state": account_state(account_b)}
        evidence["refusals"] = refusals
        # --- 3) NSCStart predating manifest blocks the official path -------- #
        from ranking_research.tests import test_paper_calendar_tf02a_regressions as reg
        root_n = base / "nsc"
        root_n.mkdir()
        account_n, rules_n, ev_n = reg._nsc_account_evidence(root_n)
        nsc_manifest = reg._nsc_package(root_n, reg._nsc_rows(),
                                        retrieved="2026-10-21T13:00:00+00:00")
        before_n = sha_file(account_n)
        run_n = run_fill(root_n, account_n, rules_n, fill_argv(
            nsc_manifest, None, ev_n, provider="nscstart",
            clock=dt.datetime(2026, 10, 24, 13, tzinfo=dt.timezone.utc)))
        evidence["nscstart_predating_manifest"] = {
            "run": run_n, "account_sha_before": before_n,
            "account_sha_after": sha_file(account_n),
            "bytes_unchanged": before_n == sha_file(account_n),
            "state": account_state(account_n)}
        # --- 4) crash harness: valid state before or after, clock rules ----- #
        root_x = base / "crash"
        account_x, rules_x, root_x = f._public_account_fixture(root_x)
        ev_x = f._public_evidence(root_x)
        argv_x = fill_argv(path, sha, ev_x, clock=NOW + dt.timedelta(minutes=5))
        pre_state = account_x.read_bytes()
        pre_sha = sha_file(account_x)
        cut_before = run_fill(root_x, account_x, rules_x, argv_x,
                              mode="DIE_BEFORE_REPLACE")
        sha_after_cut_before = sha_file(account_x)
        retry_after_crash = run_fill(root_x, account_x, rules_x, fill_argv(
            path, sha, ev_x, clock=NEXT_DAY))
        sha_after_retry = sha_file(account_x)
        cut_after = run_fill(root_x, account_x, rules_x, argv_x,
                             mode="DIE_AFTER_REPLACE")
        committed_sha = sha_file(account_x)
        replay_after_commit = run_fill(root_x, account_x, rules_x, fill_argv(
            path, sha, ev_x, clock=NEXT_DAY))
        evidence["crash_harness"] = {
            "pre_state_sha256": pre_sha,
            "cut_before_replace": {"run": cut_before, "exit_code_expected": 75,
                                   "account_sha_after": sha_after_cut_before,
                                   "bytes_unchanged": pre_sha == sha_after_cut_before},
            "next_day_retry_of_uncommitted_fill": {
                "run": retry_after_crash,
                "refused": retry_after_crash["exit_code"] != 0,
                "account_sha_after": sha_after_retry,
                "bytes_unchanged": pre_sha == sha_after_retry},
            "cut_after_replace": {"run": cut_after, "exit_code_expected": 74,
                                  "state": account_state(account_x)},
            "next_day_replay_after_commit": {
                "run": replay_after_commit,
                "state": account_state(account_x),
                "account_sha256_before_replay": committed_sha,
                "account_sha256_after_replay": sha_file(account_x),
                "bytes_unchanged": committed_sha == sha_file(account_x)},
        }
        # --- 5) refresh on a temp copy of the REAL account: mismatch -------- #
        real_account = ROOT / "client/public/research/v12-36/paper-portfolio.json"
        real_rules = ROOT / ("ranking_research/output/paper_v12_38_first_fill/"
                             "execution_rules_v1_2_0.json")
        hashes_real = {str(p.relative_to(ROOT)).replace("\\", "/"): sha_file(p)
                       for p in (real_account, real_rules)}
        root_r = base / "real-copy"
        root_r.mkdir()
        (root_r / "account.json").write_bytes(real_account.read_bytes())
        (root_r / "rules.json").write_bytes(real_rules.read_bytes())
        ev_r = f._public_evidence(root_r)
        refresh = subprocess.run(
            [PYTHON, "-X", "utf8",
             str(ROOT / "ranking_research/future_eval_v12_30/refresh_paper_decision_status.py"),
             "--account", str(root_r / "account.json"),
             "--evidence-manifest", str(ev_r),
             "--execution-rules", str(root_r / "rules.json"),
             "--output-dir", str(root_r / "out"),
             "--public-output-dir", str(root_r / "out" / "public"),
             "--calendar-provider", "public",
             "--public-calendar-manifest", str(path),
             "--public-calendar-manifest-sha256", sha,
             "--reference-now-utc", (NOW + dt.timedelta(minutes=5)).isoformat()],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        check_doc = json.loads((root_r / "out" / "paper-account-check.json")
                               .read_text(encoding="utf-8"))
        barrier = next(b for b in check_doc["barriers"]
                       if b["id"] == "public_calendar")
        evidence["real_copy_refresh_mismatch"] = {
            "exit_code": refresh.returncode,
            "public_calendar": check_doc["public_calendar"],
            "barrier": barrier,
            "real_files_hashes": hashes_real,
            "real_files_unchanged": (
                sha_file(real_account) == hashes_real["client/public/research/v12-36/paper-portfolio.json"]
                and sha_file(real_rules) == hashes_real["ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json"]),
        }
    # --- 6) the six protected ledger files --------------------------------- #
    tf02 = json.loads((ROOT / "docs/paper_portfolio_delivery/task-tf02/result.json")
                      .read_text(encoding="utf-8"))
    recorded = tf02["flags"]["ledger_files_before_equal_after"]
    evidence["protected_files"] = {
        name: {"recorded_sha256": digest, "current_sha256": sha_file(ROOT / name),
               "match": sha_file(ROOT / name) == digest}
        for name, digest in recorded.items()}
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence["generated_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    evidence["fixtures"] = "TEST_FIXTURE"
    evidence["network_requests"] = 0
    (HERE / f"evidence.{stamp}.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"written": f"evidence.{stamp}.json",
                      "replay_bytes_unchanged":
                          evidence["public_fill_then_next_day_replay"]["bytes_unchanged_by_replay"],
                      "protected_all_match": all(
                          v["match"] for v in evidence["protected_files"].values())},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
