"""TF-02B regressions for provider binding and pinned rules snapshots."""
import json
import shutil
import uuid
import datetime as dt
import hashlib
import sys
from pathlib import Path

import pytest

from ranking_research.future_eval_v12_30 import paper_cycle
from ranking_research.tests import test_paper_calendar_tf02a_regressions as tf
from ranking_research.tests import test_paper_calendar_interface as base


@pytest.mark.parametrize("tamper", ["whitespace", "semantic"])
def test_tf02b_rules_hash_mismatch_blocks_fill_status_and_acquisition(
        tmp_path, tamper):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run")
    evidence = base._public_evidence(root)
    original = rules.read_bytes()
    if tamper == "whitespace":
        rules.write_bytes(original + b"  ")
    else:
        doc = json.loads(original)
        doc["tf02b_test_semantic_marker"] = True
        rules.write_text(json.dumps(doc), encoding="utf-8")
    before = account.read_bytes()
    fill = tf._fill_invoke(account, rules, root, manifest, manifest_sha,
                           evidence_path=evidence, mode="preview")
    assert "PINNED_EXECUTION_RULES_HASH_MISMATCH" in fill["error"]
    status = tf._refresh_status(tmp_path, root, calendar_path=manifest,
                                calendar_sha=manifest_sha, account_path=account,
                                rules_path=rules, evidence_path=evidence)
    assert status["public_calendar"]["calendar_ready"] is False
    assert status["public_calendar"]["account_compatibility"]["state"] == "mismatch"
    assert "PINNED_EXECUTION_RULES_HASH_MISMATCH" in json.dumps(status)
    called = []
    cycle = paper_cycle.acquire_order_calendar(
        provider="public", run_id="rules-mismatch", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules,
        run_stage_fn=lambda *a, **k: called.append(a) or {"exit_code": 0})
    assert cycle["profile_mismatch"] is True
    assert "PINNED_EXECUTION_RULES_HASH_MISMATCH" in cycle["profile_mismatch_detail"]
    assert called == []
    assert account.read_bytes() == before


def test_tf02b_new_rules_snapshot_with_matching_pin_is_accepted(tmp_path):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run")
    evidence = base._public_evidence(root)
    doc = json.loads(rules.read_text(encoding="utf-8"))
    doc["tf02b_semantic_marker"] = "approved fixture revision"
    rules.write_text(json.dumps(doc), encoding="utf-8")
    account_doc = json.loads(account.read_text(encoding="utf-8"))
    account_doc["active_decision"]["execution_rules"]["sha256"] = hashlib.sha256(
        rules.read_bytes()).hexdigest()
    account.write_text(json.dumps(account_doc), encoding="utf-8")
    fill = tf._fill_invoke(account, rules, root, manifest, manifest_sha,
                           evidence_path=evidence, mode="preview")
    assert fill["error"] is None
    status = tf._refresh_status(tmp_path, root, calendar_path=manifest,
                                calendar_sha=manifest_sha, account_path=account,
                                rules_path=rules, evidence_path=evidence)
    assert status["public_calendar"]["calendar_ready"] is True
    cycle = paper_cycle.acquire_order_calendar(
        provider="public", run_id="new-rules", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules,
        run_stage_fn=_collector_like_stage(manifest),
        reference_now_utc=(tf.NOW + dt.timedelta(minutes=5)).isoformat())
    assert cycle["calendar_state"] == "verified_public_calendar"


def test_tf02b_missing_rules_is_controlled_in_status_and_cycle(tmp_path):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run")
    evidence = base._public_evidence(root)
    rules.unlink()
    status = tf._refresh_status(tmp_path, root, calendar_path=manifest,
                                calendar_sha=manifest_sha, account_path=account,
                                rules_path=rules, evidence_path=evidence)
    assert status["public_calendar"]["calendar_ready"] is False
    assert "PINNED_EXECUTION_RULES_UNREADABLE" in json.dumps(status)
    cycle = paper_cycle.acquire_order_calendar(
        provider="public", run_id="missing-rules", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules,
        run_stage_fn=lambda *a, **k: pytest.fail("stage must not run"))
    assert cycle["profile_mismatch"] is True
    assert "PINNED_EXECUTION_RULES_UNREADABLE" in cycle["profile_mismatch_detail"]
    fill = tf._fill_invoke(account, rules, root, manifest, manifest_sha,
                           evidence_path=evidence, mode="preview")
    assert "PINNED_EXECUTION_RULES_UNREADABLE" in fill["error"]


def test_tf02b_public_provider_rejected_before_nscstart_cycle_stage(tmp_path):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run")
    called = []
    cycle = paper_cycle.acquire_order_calendar(
        provider="nscstart", run_id="wrong-provider", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules,
        run_stage_fn=lambda *a, **k: called.append(a) or {"exit_code": 0})
    assert cycle["profile_mismatch"] is True
    assert "CALENDAR_POLICY_MISMATCH" in cycle["profile_mismatch_detail"]
    assert called == []


@pytest.mark.parametrize(("provider", "mode"), [
    ("nscstart", "apply"), ("nscstart", "preview"),
    ("nscstart", "observe"), (None, "apply"),
])
def test_tf02b_public_bound_account_cannot_use_legacy_or_default_provider(
        tmp_path, provider, mode):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run")
    evidence = base._public_evidence(root)
    before = account.read_bytes()
    result = tf._fill_invoke(account, rules, root, manifest, manifest_sha,
                             evidence_path=evidence, mode=mode,
                             calendar_provider=provider)
    assert "CALENDAR_POLICY_MISMATCH" in result["error"]
    assert account.read_bytes() == before
    saved = json.loads(account.read_bytes())
    assert saved["event_log"] == []
    assert saved["paper_order"].get("fill_event_id") is None
    assert saved["paper_order"].get("fill_receipt") is None


def test_tf02b_legacy_account_cannot_select_public_provider(tmp_path):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run", bind=False)
    evidence = base._public_evidence(root)
    before = account.read_bytes()
    result = tf._fill_invoke(account, rules, root, manifest, manifest_sha,
                             evidence_path=evidence, mode="preview",
                             calendar_provider="public")
    assert "CALENDAR_POLICY_MISMATCH" in result["error"]
    assert account.read_bytes() == before


def test_tf02b_unbound_legacy_fixture_rejected_by_public_apply(tmp_path):
    account, rules, evidence = tf._nsc_account_evidence(tmp_path / "legacy")
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    before = account.read_bytes()
    result = tf._fill_invoke(account, rules, tmp_path / "legacy", manifest,
                             manifest_sha, evidence_path=evidence,
                             mode="preview", calendar_provider="public")
    assert "CALENDAR_POLICY_MISMATCH" in result["error"]
    assert account.read_bytes() == before


def test_tf02b_provider_mismatch_reason_matches_status_and_cycle(tmp_path, monkeypatch):
    manifest, manifest_sha, _ = tf._short_package(tmp_path / "pkg")
    account, rules, root = base._public_account_fixture(tmp_path / "run")
    evidence = base._public_evidence(root)
    out = tmp_path / "status"
    monkeypatch.setattr(sys, "argv", [
        "refresh", "--account", str(account), "--execution-rules", str(rules),
        "--evidence-manifest", str(evidence), "--calendar-provider", "nscstart",
        "--output-dir", str(out), "--public-output-dir", str(out / "public")])
    base.refresh.main()
    status = json.loads((out / "paper-account-check.json").read_text(encoding="utf-8"))
    cycle = paper_cycle.acquire_order_calendar(
        provider="nscstart", run_id="same-contract", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules,
        run_stage_fn=lambda *a, **k: pytest.fail("credential/stage must not run"))
    status_reason = status["calendar_provider_compatibility"]["mismatch_detail"]
    assert "CALENDAR_POLICY_MISMATCH" in status_reason
    assert status_reason.split(";", 1)[0] == cycle["profile_mismatch_detail"].split(";", 1)[0]


def _collector_like_stage(package_manifest, mode="healthy"):
    def stage(name, command, timeout, env=None):
        out = Path(command[command.index("--output-dir") + 1])
        if mode == "failed_old_pointer":
            (out / "latest-manifest.json").write_text(
                json.dumps({"run_id": "stale", "manifest_path": str(out / "missing.json"),
                            "manifest_sha256": "0" * 64}), encoding="utf-8")
            return {"stage": name, "exit_code": 7}
        if mode == "no_output":
            return {"stage": name, "exit_code": 0}
        doc = json.loads(package_manifest.read_text(encoding="utf-8"))
        raw_dir = out / "raw"
        raw_dir.mkdir(exist_ok=True)
        for source in doc["sources"]:
            source_path = Path(source["raw_path"])
            target = raw_dir / source_path.name
            if target.exists():
                target.unlink()
            shutil.copyfile(source_path, target)
            source["raw_path"] = str(target)
        manifest_path = out / "manifest.json"
        if mode == "outside":
            manifest_path = out.parent / f"outside-{uuid.uuid4().hex}.json"
        doc["run_id"] = f"collector-{uuid.uuid4().hex}"
        manifest_path.write_text(json.dumps(doc), encoding="utf-8")
        pointer_id = doc["run_id"] if mode != "run_id_mismatch" else "other-collector"
        pointer_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest() if mode != "hash_mismatch" else "0" * 64
        (out / "latest-manifest.json").write_text(json.dumps({
            "run_id": pointer_id, "manifest_path": str(manifest_path),
            "manifest_sha256": pointer_sha}), encoding="utf-8")
        return {"stage": name, "exit_code": 0}
    return stage


@pytest.mark.parametrize(("mode", "expected"), [
    ("no_output", "blocked_public_manifest_missing"),
    ("outside", "blocked_public_manifest_outside_invocation"),
    ("run_id_mismatch", "blocked_public_pointer_manifest_run_id_mismatch"),
    ("hash_mismatch", "blocked_public_manifest_hash_mismatch"),
    ("failed_old_pointer", "blocked_public_acquisition_failed"),
])
def test_tf02b_acquisition_faults_never_consume_manifest(tmp_path, mode, expected):
    manifest, _, _ = tf._short_package(tmp_path / "pkg")
    account, rules, _ = base._public_account_fixture(tmp_path / "run")
    result = paper_cycle.acquire_order_calendar(
        provider="public", run_id="cycle-independent-id", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules,
        run_stage_fn=_collector_like_stage(manifest, mode),
        reference_now_utc=(tf.NOW + dt.timedelta(minutes=5)).isoformat())
    assert result["calendar_state"] == expected
    assert result["manifest_path"] is None


def test_tf02b_two_acquisitions_consume_own_bundles_and_preserve_first(tmp_path):
    manifest, _, _ = tf._short_package(tmp_path / "pkg")
    account, rules, _ = base._public_account_fixture(tmp_path / "run")
    out = tmp_path / "cycle"
    one = paper_cycle.acquire_order_calendar(
        provider="public", run_id="cycle", out_root=out, account_path=account,
        rules_path=rules, run_stage_fn=_collector_like_stage(manifest),
        reference_now_utc=(tf.NOW + dt.timedelta(minutes=5)).isoformat())
    first_path = one["manifest_path"]
    first_hash = hashlib.sha256(first_path.read_bytes()).hexdigest()
    two = paper_cycle.acquire_order_calendar(
        provider="public", run_id="cycle", out_root=out, account_path=account,
        rules_path=rules, run_stage_fn=_collector_like_stage(manifest),
        reference_now_utc=(tf.NOW + dt.timedelta(minutes=5)).isoformat())
    assert one["calendar_state"] == two["calendar_state"] == "verified_public_calendar"
    assert first_path != two["manifest_path"]
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == first_hash


def test_tf02b_cycle_uses_rules_snapshot_if_stage_changes_file(tmp_path):
    manifest, _, _ = tf._short_package(tmp_path / "pkg")
    account, rules, _ = base._public_account_fixture(tmp_path / "run")
    original = rules.read_bytes()
    healthy = _collector_like_stage(manifest)
    def changing_stage(name, command, timeout, env=None):
        result = healthy(name, command, timeout, env)
        rules.write_bytes(original + b"  ")
        return result
    result = paper_cycle.acquire_order_calendar(
        provider="public", run_id="snapshot", out_root=tmp_path / "cycle",
        account_path=account, rules_path=rules, run_stage_fn=changing_stage,
        reference_now_utc=(tf.NOW + dt.timedelta(minutes=5)).isoformat())
    assert result["calendar_state"] == "verified_public_calendar"
    assert rules.read_bytes() != original
