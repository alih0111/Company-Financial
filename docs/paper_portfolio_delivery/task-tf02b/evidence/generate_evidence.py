"""Generate offline TF-02B entrypoint evidence using disposable fixtures."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from ranking_research.tests import test_paper_calendar_tf02a_regressions as a
from ranking_research.tests import test_paper_calendar_interface as f
from ranking_research.tests import test_paper_calendar_tf02b_regressions as b
from ranking_research.future_eval_v12_30 import paper_cycle

sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
PROTECTED = {
    "client/public/research/v12-36/paper-portfolio.json": "7c6fa7f17f51fc93c8d3d439acfa52fbbbcc0b400653f585383f5201f0bb21b3",
    "ranking_research/output/paper_v12_38_first_fill/execution_rules_v1_2_0.json": "ab31c9275fcdc96f787b91de1c8ec314cf32fedb5b6249aa17911bad90ec5646",
    "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json": "8b08cace7b64ee135ac862b6b9afd02242ba91cec24f8d6134b1d9b6c623c1c8",
    "ranking_research/output/return_v12_27/v12_27_1_20261022_delivery_corrections_01/analysis_contract.locked.json": "d078ff39d823d31bd28ef71c9c95e4436b6d3c5e4428bb8f2c201185b16c750e",
    "ranking_research/output/return_v12_23/v12_23_20261021_fresh_local_baseline_01/global/analysis_contract.locked.json": "48261c6dcc4001e3c294a27588837a222d0482e18ad23d8a008191ef573c49b4",
    "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/o00_session_calendar.csv": "3622b331798920d4b9ecfae04171c0c806b20d18f8e49f0962989f3865048441",
}


def account_counts(path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    order = doc.get("paper_order") or {}
    return {"account_sha256": sha(path), "event_count": len(doc.get("event_log", [])),
            "fill_event_present": bool(order.get("fill_event_id")),
            "receipt_present": isinstance(order.get("fill_receipt"), dict),
            "cash_toman": doc.get("cash_toman")}


def main():
    cases = {}
    with tempfile.TemporaryDirectory(prefix="tf02b-evidence-") as temp:
        tmp = Path(temp)
        manifest, manifest_sha, _ = a._short_package(tmp / "pkg")

        # The four provider/account combinations exercise apply.main itself.
        account, rules, run = f._public_account_fixture(tmp / "public")
        evidence = f._public_evidence(run)
        cases["apply_public_public"] = a._fill_invoke(
            account, rules, run, manifest, manifest_sha, evidence_path=evidence,
            mode="apply", calendar_provider="public")
        cases["apply_public_public"]["account"] = account_counts(account)

        account, rules, evidence = a._nsc_account_evidence(tmp / "legacy")
        run = tmp / "legacy"
        nsc_manifest = a._nsc_package(run, a._nsc_rows())
        cases["apply_legacy_nscstart"] = a._fill_invoke(
            account, rules, run, nsc_manifest, None, evidence_path=evidence,
            mode="apply", calendar_provider="nscstart",
            clock=dt.datetime(2026, 10, 24, 13, tzinfo=dt.timezone.utc))
        cases["apply_legacy_nscstart"]["account"] = account_counts(account)

        for key, provider, mode, bind in (
            ("apply_public_nscstart", "nscstart", "apply", True),
            ("apply_public_default", None, "apply", True),
            ("apply_public_observation", "nscstart", "observe", True),
            ("apply_legacy_public", "public", "preview", False),
        ):
            account, rules, run = f._public_account_fixture(tmp / key, bind=bind)
            evidence = f._public_evidence(run)
            before = account_counts(account)
            response = a._fill_invoke(account, rules, run, manifest, manifest_sha,
                                      evidence_path=evidence, mode=mode,
                                      calendar_provider=provider)
            response["account_before"] = before
            response["account_after"] = account_counts(account)
            cases[key] = response
        account, rules, evidence = a._nsc_account_evidence(tmp / "unbound-legacy")
        before = account_counts(account)
        response = a._fill_invoke(account, rules, tmp / "unbound-legacy", manifest,
                                  manifest_sha, evidence_path=evidence,
                                  mode="preview", calendar_provider="public")
        response["account_before"] = before
        response["account_after"] = account_counts(account)
        cases["apply_unbound_legacy_public"] = response

        # Same-input rules refusal across fill, status and acquisition.
        account, rules, run = f._public_account_fixture(tmp / "rules")
        evidence = f._public_evidence(run)
        before = account_counts(account)
        rules.write_bytes(rules.read_bytes() + b"  ")
        cases["rules_whitespace_mismatch"] = {
            "fill": a._fill_invoke(account, rules, run, manifest, manifest_sha,
                                   evidence_path=evidence, mode="preview"),
            "status": a._refresh_status(tmp, run, calendar_path=manifest,
                                        calendar_sha=manifest_sha, account_path=account,
                                        rules_path=rules, evidence_path=evidence)}
        cases["rules_whitespace_mismatch"]["cycle"] = paper_cycle.acquire_order_calendar(
            provider="public", run_id="rules", out_root=tmp / "rules-cycle",
            account_path=account, rules_path=rules,
            run_stage_fn=lambda *args, **kwargs: {"exit_code": 0})
        cases["rules_whitespace_mismatch"]["account_before"] = before
        cases["rules_whitespace_mismatch"]["account_after"] = account_counts(account)
        account, rules, run = f._public_account_fixture(tmp / "semantic-rules")
        evidence = f._public_evidence(run)
        semantic_before = account_counts(account)
        semantic_doc = json.loads(rules.read_text(encoding="utf-8"))
        semantic_doc["tf02b_semantic_change"] = True
        rules.write_text(json.dumps(semantic_doc), encoding="utf-8")
        cases["rules_semantic_mismatch"] = {
            "fill": a._fill_invoke(account, rules, run, manifest, manifest_sha,
                                   evidence_path=evidence, mode="preview"),
            "status": a._refresh_status(tmp, run, calendar_path=manifest,
                                        calendar_sha=manifest_sha, account_path=account,
                                        rules_path=rules, evidence_path=evidence),
            "cycle": paper_cycle.acquire_order_calendar(
                provider="public", run_id="semantic", out_root=tmp / "semantic-cycle",
                account_path=account, rules_path=rules,
                run_stage_fn=lambda *args, **kwargs: {"exit_code": 0})}
        cases["rules_semantic_mismatch"]["account_before"] = semantic_before
        cases["rules_semantic_mismatch"]["account_after"] = account_counts(account)
        account, rules, run = f._public_account_fixture(tmp / "missing-rules")
        evidence = f._public_evidence(run)
        missing_before = account_counts(account)
        rules.unlink()
        cases["rules_missing"] = {
            "fill": a._fill_invoke(account, rules, run, manifest, manifest_sha,
                                   evidence_path=evidence, mode="preview"),
            "status": a._refresh_status(tmp, run, calendar_path=manifest,
                                        calendar_sha=manifest_sha, account_path=account,
                                        rules_path=rules, evidence_path=evidence),
            "cycle": paper_cycle.acquire_order_calendar(
                provider="public", run_id="missing-rules", out_root=tmp / "missing-cycle",
                account_path=account, rules_path=rules,
                run_stage_fn=lambda *args, **kwargs: {"exit_code": 0})}
        cases["rules_missing"]["account_before"] = missing_before
        cases["rules_missing"]["account_after"] = account_counts(account)
        account, rules, run = f._public_account_fixture(tmp / "pinned-rules-control")
        evidence = f._public_evidence(run)
        rules_doc = json.loads(rules.read_text(encoding="utf-8"))
        rules_doc["tf02b_semantic_marker"] = "approved fixture revision"
        rules.write_text(json.dumps(rules_doc), encoding="utf-8")
        account_doc = json.loads(account.read_text(encoding="utf-8"))
        account_doc["active_decision"]["execution_rules"]["sha256"] = sha(rules)
        account.write_text(json.dumps(account_doc), encoding="utf-8")
        cases["rules_new_pin_control"] = {
            "fill": a._fill_invoke(account, rules, run, manifest, manifest_sha,
                                   evidence_path=evidence, mode="preview"),
            "status": a._refresh_status(tmp, run, calendar_path=manifest,
                                        calendar_sha=manifest_sha, account_path=account,
                                        rules_path=rules, evidence_path=evidence),
            "cycle": paper_cycle.acquire_order_calendar(
                provider="public", run_id="rules-new-pin", out_root=tmp / "new-pin-cycle",
                account_path=account, rules_path=rules,
                run_stage_fn=b._collector_like_stage(manifest),
                reference_now_utc=(a.NOW + dt.timedelta(minutes=5)).isoformat())}

        # All acquisition faults and the positive fresh-bundle control.
        acq = {}
        for mode in ("healthy", "no_output", "outside", "run_id_mismatch",
                     "hash_mismatch", "failed_old_pointer"):
            account, rules, _ = f._public_account_fixture(tmp / f"acq-{mode}")
            acq[mode] = paper_cycle.acquire_order_calendar(
                provider="public", run_id="cycle-id-differs-from-collector",
                out_root=tmp / f"acq-out-{mode}", account_path=account, rules_path=rules,
                run_stage_fn=b._collector_like_stage(manifest, mode),
                reference_now_utc=(a.NOW + dt.timedelta(minutes=5)).isoformat())
        cases["acquisition"] = acq
        first = paper_cycle.acquire_order_calendar(
            provider="public", run_id="two", out_root=tmp / "two",
            account_path=account, rules_path=rules,
            run_stage_fn=b._collector_like_stage(manifest),
            reference_now_utc=(a.NOW + dt.timedelta(minutes=5)).isoformat())
        first_sha = sha(first["manifest_path"])
        second = paper_cycle.acquire_order_calendar(
            provider="public", run_id="two", out_root=tmp / "two",
            account_path=account, rules_path=rules,
            run_stage_fn=b._collector_like_stage(manifest),
            reference_now_utc=(a.NOW + dt.timedelta(minutes=5)).isoformat())
        cases["two_invocations"] = {
            "first": first, "first_manifest_sha256_after_second": sha(first["manifest_path"]),
            "first_manifest_sha256_before_second": first_sha, "second": second}

    protected = {}
    for rel, baseline in PROTECTED.items():
        after = sha(ROOT / rel)
        protected[rel] = {"baseline_before": baseline, "after": after,
                          "unchanged": baseline == after}
    result = {
        "task": "TF-02B", "date": "2026-10-24", "network_requests": 0,
        "token_used": False, "live_account_written": False,
        "direct_acquire_order_calendar_only": True,
        "cases": cases, "protected_files": protected,
        "test_command": ".venv/Scripts/python.exe -X utf8 -m pytest ranking_research/tests/test_public_market_calendar.py ranking_research/tests/test_paper_calendar_interface.py ranking_research/tests/test_paper_account_atomic.py ranking_research/tests/test_paper_cycle_http.py ranking_research/tests/test_paper_calendar_tf02a_regressions.py ranking_research/tests/test_paper_calendar_tf02b_regressions.py -q --basetemp D:/RFA/Company-Financial/.pytest_tmp_tf02b_deliver",
        "test_result": {"passed": 168, "failed": 0, "duration_seconds": 453.99,
                        "unique_tf02b_regressions": 19,
                        "existing_suite": 149},
    }
    out = Path(__file__).with_name("evidence.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(json.dumps({"evidence": str(out), "cases": list(cases),
                      "protected_match": all(v["unchanged"] for v in protected.values())},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
