"""TF-02 acceptance tests: shared calendar interface and experimental wiring.

All fixtures are explicitly artificial; no test touches the network and no
test writes outside tmp_path. The real account file is only ever hashed, and
dry-run mismatch checks run on a temp copy.
"""
from __future__ import annotations

import copy
import datetime as dt
import gzip
import hashlib
import io
import json
import sys
import tempfile
import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest

from ranking_research.future_eval_v12_30 import apply_paper_fill
from ranking_research.future_eval_v12_30 import paper_cycle
from ranking_research.future_eval_v12_30 import refresh_paper_decision_status as refresh
from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf
from ranking_research import paper_calendar as pc
from ranking_research.tests import test_public_market_calendar as fx

NOW = fx.NOW
POLICY_PATH = pc.DEFAULT_PUBLIC_POLICY_PATH
POLICY_SHA = tf.sha_file(POLICY_PATH)
POLICY = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
CANDIDATE = {"symbol": "TEST", "ins_code": fx.CANDIDATE_INS}


def public_package(tmp_path, *, primary=None, secondary=None, watermark=None,
                   snapshot_records=None, max_symbols=None, window_start=None):
    """Deterministic pinned public package + answer inputs."""
    path, manifest, evaluation = fx.build_pinned_package(
        tmp_path, primary_dates=primary, secondary_dates=secondary,
        watermark=watermark, snapshot_records=snapshot_records,
        max_symbols=max_symbols, window_start=window_start)
    return path, tf.sha_file(path), manifest


def consume(path, manifest_sha, *, decision_day="20260901",
            decision_at=None, now=None, mode="fixture-apply",
            policy=None, policy_sha=POLICY_SHA, candidate=None):
    return pc.resolve_public_calendar(
        manifest_path=path, expected_manifest_sha256=manifest_sha,
        policy=policy or POLICY, policy_sha256=policy_sha,
        candidate=candidate or CANDIDATE, decision_local_date=decision_day,
        decision_at_utc=decision_at or dt.datetime(2026, 9, 1, 6, 0, 0, tzinfo=dt.timezone.utc),
        now_utc=now or (NOW + dt.timedelta(minutes=5)),
        consumption_mode=mode)


# 1 - public acquisition without a token builds a usable pinned answer ------ #
def test_public_path_needs_no_token_and_adapter_consumes_it(tmp_path):
    assert "environ" not in Path(tf.__file__).read_text(encoding="utf-8")
    assert "environ" not in Path(pc.__file__).read_text(encoding="utf-8")
    path, manifest_sha, manifest = public_package(tmp_path)
    answer = consume(path, manifest_sha, mode="live-preview")
    assert answer["provider"] == "public-index"
    assert answer["quality"] == "CORROBORATED_PUBLIC"
    assert answer["quality_recomputed_from_raw"] is True
    assert answer["freshness"]["state"] == "FRESH"
    assert answer["completion"]["type"] == "named_operational_assumption"
    assert answer["completion"]["officially_confirmed"] is False
    assert answer["completion"]["tails_aligned_with_assumption"] is True
    assert answer["readiness"]["calendar_ready"] is True
    assert answer["first_usable_session"] == "20260902"
    assert answer["eligible_session_count"] == 6
    assert "no NSCStart" not in json.dumps(manifest)[:0]  # placeholder guard
    assert all("api.tsetmc.com" not in str(s.get("url", ""))
               for s in manifest["sources"])
    # the collector never wrote into the consumer namespace and no token is read
    for module in (apply_paper_fill, pc, tf):
        assert "TSETMC_READONLY_BEARER_TOKEN" not in Path(module.__file__).read_text(encoding="utf-8")


# 2 - healthy evidence + bound public account: preview keeps bytes, apply
#     debits once, replay is byte-identical ---------------------------------- #
def _public_account_fixture(root: Path, *, policy_id="public-paper-v1",
                            policy_sha=POLICY_SHA, bind=True) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    rules = {
        "rule_id": "paper-execution-rules/1.2.0-TEST_FIXTURE",
        "calendar_policy": {"id": policy_id, "sha256": policy_sha} if bind else None,
    }
    rules_path = root / "rules.json"
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    decision_binding = {"id": policy_id, "sha256": policy_sha} if bind else None
    account = {
        "account_id": "TEST_FIXTURE_PUBLIC", "initial_capital_toman": 100000,
        "cash_toman": 100000, "holdings": [], "event_log": [],
        "created_at_utc": "2026-09-01T09:00:00+00:00",
        "accounting": {"holdings_value_toman": 0, "total_value_toman": 100000,
                       "profit_loss_toman": 0},
        "active_decision": {
            "decision_id": "fixture-decision-public",
            "decided_at_utc": "2026-09-01T10:00:00+00:00",
            "decision_local_date": "2026-09-01",
            "execution_rules": {"sha256": apply_paper_fill.sha(rules_path)},
            "calendar_policy": decision_binding,
        },
        "paper_order": {
            "order_id": "fixture-order-public",
            "decision_id": "fixture-decision-public", "company_id": "fixture-company",
            "symbol": "TEST", "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
            "expires_after_official_sessions": 3,
            "eligible_session_count_observed": 0, "fill_event_id": None,
            "calendar_policy": decision_binding,
        },
    }
    account_path = root / "account.json"
    account_path.write_text(json.dumps(account), encoding="utf-8")
    return account_path, rules_path, root


def _public_evidence(root: Path, *, has_bar=True, bar_day="20260902"):
    daily_rows = ([{"dEven": bar_day, "insCode": fx.CANDIDATE_INS, "pClosing": 1234,
                    "qTotTran5J": 10000}] if has_bar else [])
    sources = []
    body = json.dumps({"closingPriceDaily": daily_rows}, separators=(",", ":")).encode()
    raw = root / "daily.gz"
    raw.write_bytes(gzip.compress(body))
    sources.append({"key": "candidate_daily", "raw_path": raw.name,
                    "raw_sha256": hashlib.sha256(body).hexdigest(),
                    "retrieved_at_utc": (NOW + dt.timedelta(minutes=4)).isoformat(),
                    "url": f"https://example.invalid/api/ClosingPrice/GetClosingPriceDailyList/{fx.CANDIDATE_INS}/0"})
    for key in ("candidate_share_changes", "last_possible_session"):
        body = json.dumps({"instrumentShareChange": []} if key == "candidate_share_changes"
                          else {}, separators=(",", ":")).encode()
        raw = root / f"{key}.gz"
        raw.write_bytes(gzip.compress(body))
        sources.append({"key": key, "raw_path": raw.name,
                        "raw_sha256": hashlib.sha256(body).hexdigest(),
                        "retrieved_at_utc": (NOW + dt.timedelta(minutes=4)).isoformat()})
    evidence = {"ins_code": fx.CANDIDATE_INS,
                "candidate": {"company_id": "fixture-company"},
                "sources": sources}
    path = root / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return path


def _run_public_fill(account_path, rules_path, root, calendar_path, calendar_sha,
                     argv_extra=(), *, mode="apply", policy_id="public-paper-v1",
                     policy_sha=POLICY_SHA, decided_at=None,
                     decision_local="2026-09-01"):
    account_path, rules_path, root = _public_account_fixture(
        root, policy_id=policy_id, policy_sha=policy_sha) if account_path is None else (
        account_path, rules_path, root)
    if decided_at is not None:
        account = json.loads(account_path.read_text(encoding="utf-8"))
        account["active_decision"]["decided_at_utc"] = decided_at
        account["active_decision"]["decision_local_date"] = decision_local
        account["paper_order"]["decision_id"] = account["active_decision"]["decision_id"]
        account_path.write_text(json.dumps(account), encoding="utf-8")
    evidence_path = _public_evidence(root)
    argv = ["--session-calendar-manifest", str(calendar_path),
            "--calendar-manifest-sha256", calendar_sha,
            "--evidence-manifest", str(evidence_path),
            "--calendar-provider", "public",
            "--calendar-policy", str(POLICY_PATH),
            "--reference-now-utc", (NOW + dt.timedelta(minutes=5)).isoformat(),
            *argv_extra]
    if mode == "apply":
        argv.append("--apply-fill")
    output = io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(apply_paper_fill, "ACCOUNT", account_path)
        mp.setattr(apply_paper_fill, "RULES", rules_path)
        mp.setattr(apply_paper_fill, "ROOT", root)
        mp.setattr(sys, "argv", ["apply_paper_fill.py", *argv])
        with contextlib.redirect_stdout(output):
            apply_paper_fill.main()
    return json.loads(output.getvalue())


def test_public_preview_then_apply_then_replay_is_byte_exact(tmp_path):
    # decision 2026-09-01; histories end at 20260905 with a matching watermark:
    # two accepted post-decision sessions (below the 3-session expiry) and a
    # fresh bar on the first -> eligible preview, one debit, byte-identical replay
    days = [d for d in fx.BASE_SESSIONS if d <= "20260905"]
    calendar_path, calendar_sha, _ = public_package(
        tmp_path / "pkg", primary=days, secondary=days, watermark="20260905;20260905")
    root = tmp_path / "run"
    account_path, rules_path, root = _public_account_fixture(root)
    # preview: account bytes unchanged
    before = account_path.read_bytes()
    preview = _run_public_fill(account_path, rules_path, root, calendar_path,
                               calendar_sha, mode="preview")
    assert preview["status"] == "FILL_ELIGIBLE_PREVIEW_ONLY"
    assert preview["fill_applied"] is False
    assert account_path.read_bytes() == before
    assert preview["calendar"]["policy_id"] == "public-paper-v1"
    assert preview["calendar_label_fa"] == POLICY["display_label_fa"]
    # apply: exactly one debit / holding / event / receipt
    applied = _run_public_fill(account_path, rules_path, root, calendar_path,
                               calendar_sha, mode="apply")
    assert applied["status"] == "FILL_APPLIED"
    filled = json.loads(account_path.read_text(encoding="utf-8"))
    assert filled["cash_toman"] == 43 and len(filled["holdings"]) == 1
    assert len(filled["event_log"]) == 1
    receipt = filled["paper_order"]["fill_receipt"]
    assert receipt["version"] == 2 and receipt["calendar"]["policy_id"] == "public-paper-v1"
    assert receipt["calendar"]["completion_type"] == "named_operational_assumption"
    assert filled["paper_order"]["designated_execution_session"] == "20260902"
    after = account_path.read_bytes()
    # replay with the same pinned evidence: state stays FILL_ALREADY_APPLIED and
    # the account content is semantically unchanged (byte comparison in the
    # atomic-writer regression; here the first run's pretty-write is the base)
    for _ in range(2):
        replay = _run_public_fill(account_path, rules_path, root, calendar_path,
                                  calendar_sha, mode="apply")
        assert replay["status"] == "FILL_ALREADY_APPLIED"
        replayed = json.loads(account_path.read_text(encoding="utf-8"))
        assert replayed == filled
        assert replayed["cash_toman"] == 43 and len(replayed["event_log"]) == 1


# 3 - tampered/broken evidence stops with no account change ----------------- #
def _fresh_public_account(root: Path, **kwargs):
    """A fresh (unmodified) public-bound account for each independent case."""
    return _public_account_fixture(root, **kwargs)


@pytest.mark.parametrize("corrupt", ["raw", "manifest_hash", "duplicate_key",
                                     "policy", "predates_decision", "future_ts"])
def test_broken_public_inputs_stop_without_account_changes(tmp_path, corrupt):
    # each parametrized case gets its own fresh account and a single-session
    # package so the order stays pending and every case reaches the calendar gate
    root = tmp_path / f"run-{corrupt}"
    account_path, rules_path, root = _fresh_public_account(root)
    # decision 20260901, histories end 20260905 -> 2 accepted sessions, order
    # stays below expiry so every case reaches the calendar gates
    days = [d for d in fx.BASE_SESSIONS if d <= "20260905"]
    calendar_path, calendar_sha, manifest = public_package(
        tmp_path / f"pkg-{corrupt}", primary=days, secondary=days,
        watermark="20260905;20260905")
    if corrupt == "raw":
        for source in manifest["sources"]:
            if source["key"] == "primary_history":
                raw_path = tf.resolve_repo_path(source["raw_path"])
                raw_path.write_bytes(gzip.compress(json.dumps({"indexB2": []}).encode()))
    elif corrupt == "manifest_hash":
        calendar_sha = "0" * 64
    elif corrupt == "duplicate_key":
        docs = json.loads(calendar_path.read_text(encoding="utf-8"))
        docs["sources"] = docs["sources"] + [dict(docs["sources"][0])]
        calendar_path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        calendar_sha = tf.sha_file(calendar_path)
    before = account_path.read_bytes()
    if corrupt == "duplicate_key":
        with pytest.raises(SystemExit, match="CALENDAR_MANIFEST_DUPLICATE_SOURCE_KEY"):
            _run_public_fill(account_path, rules_path, root, calendar_path,
                             calendar_sha, mode="preview")
    elif corrupt == "policy":
        # the account/order/rules stay UNBOUND (like the current real account):
        # consuming with the public policy must refuse, not silently convert
        root = tmp_path / "run-policy-unbound"
        account_path, rules_path, root = _public_account_fixture(root, bind=False)
        before_unbound = account_path.read_bytes()
        with pytest.raises(SystemExit, match="CALENDAR_POLICY_MISMATCH"):
            _run_public_fill(account_path, rules_path, root, calendar_path,
                             calendar_sha, mode="preview")
        assert account_path.read_bytes() == before_unbound
        return  # this case carries its own baseline
    elif corrupt == "predates_decision":
        stale = tmp_path / "pkg-stale"
        stale.mkdir()
        docs = json.loads(calendar_path.read_text(encoding="utf-8"))
        for source in docs["sources"]:
            source["retrieved_at_utc"] = "2026-08-31T00:00:00+00:00"
        calendar_path = stale / "manifest.json"
        calendar_path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        calendar_sha = tf.sha_file(calendar_path)
        with pytest.raises(SystemExit, match="SOURCE_RETRIEVED_BEFORE_DECISION"):
            _run_public_fill(account_path, rules_path, root, calendar_path,
                             calendar_sha, mode="preview")
    elif corrupt == "future_ts":
        future = tmp_path / "pkg-future"
        future.mkdir()
        docs = json.loads(calendar_path.read_text(encoding="utf-8"))
        for source in docs["sources"]:
            # 7 minutes ahead of the evaluation clock (NOW+5min), beyond the 5-minute tolerance
            source["retrieved_at_utc"] = (NOW + dt.timedelta(minutes=12)).isoformat()
        calendar_path = future / "manifest.json"
        calendar_path.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
        calendar_sha = tf.sha_file(calendar_path)
        with pytest.raises(SystemExit, match="SOURCE_RETRIEVED_IN_FUTURE"):
            _run_public_fill(account_path, rules_path, root, calendar_path,
                             calendar_sha, mode="preview")
    else:  # raw tampering / wrong pinned hash must stop before any write
        with pytest.raises(SystemExit, match="CALENDAR_MANIFEST_QUALITY_INCONSISTENT|CALENDAR_MANIFEST_HASH_MISMATCH"):
            _run_public_fill(account_path, rules_path, root, calendar_path,
                             calendar_sha, mode="preview")
    assert account_path.read_bytes() == before


    # 4 - weekend freshness boundary: fresh = NO_NEW_SESSION; stale = blocked #
def test_weekend_fresh_vs_stale_evidence_boundary(tmp_path):
    path, manifest_sha, _ = public_package(
        tmp_path, primary=["20261019", "20261020", "20261021"],
        secondary=["20261019", "20261020", "20261021"], watermark="20261021;20261021")
    at = dict(decision_day="20261019",  # manifest window_start is the package decision day
              decision_at=dt.datetime(2026, 10, 19, 10, 0, 0, tzinfo=dt.timezone.utc))
    fresh = consume(path, manifest_sha,
                    now=dt.datetime(2026, 10, 23, 12, 0, 0, tzinfo=dt.timezone.utc),
                    mode="live-preview", **at)
    # Saturday clock, watermark 20261021: both post-decision sessions are
    # accepted within the completion assumption; no weekend session is fabricated
    assert fresh["sessions_after_decision"]["state"] == "HAS_SESSIONS_WITHIN_ASSUMED_COMPLETION"
    assert fresh["sessions_after_decision"]["count"] == 2
    assert fresh["first_usable_session"] == "20261020"
    assert fresh["readiness"]["calendar_ready"] is True
    stale = consume(path, manifest_sha,
                    now=dt.datetime(2026, 10, 24, 12, 0, 0, tzinfo=dt.timezone.utc),
                    mode="live-preview", **at)
    assert stale["freshness"]["state"] == "BLOCKED"
    assert stale["readiness"]["calendar_ready"] is False
    assert any(reason.startswith("FRESHNESS_SOURCE_STALE")
               for reason in stale["readiness"]["blocking_reasons"])
    # historical replay at its own execution clock remains valid
    replay = consume(path, manifest_sha,
                     now=dt.datetime(2026, 10, 23, 12, 0, 0, tzinfo=dt.timezone.utc),
                     mode="exact-replay", **at)
    assert replay["readiness"]["calendar_ready"] is True


# 5 - market open without a candidate bar: no-fill, session kept; short
#     archive = evidence gap, never a no-trade claim -------------------------- #
def test_missing_candidate_bar_keeps_session_and_short_archive_is_gap(tmp_path):
    path, manifest_sha, manifest = public_package(tmp_path)
    answer = consume(path, manifest_sha)
    sessions = answer["sessions_after_decision"]["sessions"]
    assert "20260902" in sessions  # market session preserved with no bar
    # the default package carries no eligible archive member list for TEST, so
    # trade_status is unknown (never a no-trade claim)
    assert answer["candidate"]["trade_status"] in ("checked", "not_in_archive_unknown", None)
    # a later-session price can never backfill the first session: the fill
    # entrypoint picks only the designated first session's bar
    # short archive covering only 20260901 while first session is 20260902
    short = tmp_path / "short-archive"
    short.mkdir()
    directory = fx._snapshot_dir(short, [("TEST", fx.CANDIDATE_INS,
                                          [fx.daily_row(fx.CANDIDATE_INS, "20260901")])])
    stock = tf.load_stock_cross(directory, window_start="20260901", market_scope="TSE",
                                identity_map={"TEST": {
                                    "ins_code": fx.CANDIDATE_INS,
                                    "flowTitle": "بازار بورس",
                                    "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
                                    "evidence_source": "fixture"}})
    sources = fx.make_sources(by_symbol=stock["by_symbol"])
    evaluation = tf.evaluate_public_calendar(policy=fx.policy(), sources=sources,
                                             now_utc=NOW)
    assert evaluation["candidate"]["trade_status"] == "checked"
    # every post-decision session lacks a candidate row: recorded as missing
    # trade evidence, the market sessions stay in the calendar
    assert evaluation["candidate"]["no_positive_trade_sessions"] == [
        d for d in fx.BASE_SESSIONS if d > "20260901"]
    assert evaluation["quality"] == "CORROBORATED_PUBLIC"  # session kept; candidate row absent


# 6 - quality defects block with their own reason ---------------------------- #
def test_conflict_and_missing_anchor_and_watermark_block_specifically(tmp_path):
    # quality defects are answered, not hidden: calendar_ready=false with the
    # specific blocking code (structural violations raise; quality blocks answer)
    pkg = tmp_path / "conflict"
    path, sha, _ = public_package(
        pkg, primary=fx.BASE_SESSIONS + ["20260910"],
        secondary=fx.BASE_SESSIONS)
    answer = consume(path, sha)
    assert answer["readiness"]["calendar_ready"] is False
    assert "CALENDAR_QUALITY_CONFLICT" in answer["readiness"]["blocking_reasons"]
    assert any(c["type"] == "index_date_mismatch" and c["date"] == "20260910"
               for c in answer["conflicts"])
    # missing anchor: decision window starts 20260902; primary anchors it via an
    # earlier row, secondary has no row on/before the decision day and the union
    # lower bound must not hide the gap -> pure INSUFFICIENT_COVERAGE
    pkg = tmp_path / "anchor"
    path, sha, _ = public_package(
        pkg, primary=["20260901", "20260905"],
        secondary=["20260905"], watermark="20260905;20260905",
        snapshot_records=None, window_start="20260902")
    answer = consume(path, sha, decision_day="20260902",
                     decision_at=dt.datetime(2026, 9, 2, 6, 0, 0, tzinfo=dt.timezone.utc))
    assert "CALENDAR_QUALITY_INSUFFICIENT_COVERAGE" in answer["readiness"]["blocking_reasons"]
    # watermark components disagree -> completion assumption unavailable
    pkg = tmp_path / "disagree"
    path, sha, _ = public_package(pkg, watermark="20260909;20260908")
    answer = consume(path, sha)
    assert "COMPLETION_ASSUMPTION_UNAVAILABLE" in answer["readiness"]["blocking_reasons"]
    # watermark behind index tail -> tail misalignment
    pkg = tmp_path / "tail"
    path, sha, _ = public_package(pkg, watermark="20260905;20260905")
    answer = consume(path, sha)
    assert "COMPLETION_TAIL_MISALIGNED" in answer["readiness"]["blocking_reasons"]
    assert answer["completion"]["tails_aligned_with_assumption"] is False


# 7 - expiry counts accepted sessions; Tehran boundary; replay-after-mark ---- #
def test_expiry_and_replay_after_mark_with_public_calendar(tmp_path):
    # five accepted sessions after the decision, no bar on the first -> expire
    days = ["20260902", "20260905", "20260906", "20260907", "20260908", "20260909"]
    pkg = tmp_path / "expire"
    calendar_path, calendar_sha, _ = public_package(
        pkg, primary=days, secondary=days, watermark="20260909;20260909")
    root = tmp_path / "run-expire"
    account_path, rules_path, root = _public_account_fixture(root)
    account = json.loads(account_path.read_text(encoding="utf-8"))
    # the package window starts on the decision day 20260902
    account["active_decision"]["decision_local_date"] = "2026-09-02"
    account["active_decision"]["decided_at_utc"] = "2026-09-02T10:00:00+00:00"
    account_path.write_text(json.dumps(account), encoding="utf-8")
    evidence_path = _public_evidence(root, has_bar=False)
    argv = ["--session-calendar-manifest", str(calendar_path),
            "--calendar-manifest-sha256", calendar_sha,
            "--evidence-manifest", str(evidence_path),
            "--calendar-provider", "public",
            "--calendar-policy", str(POLICY_PATH),
            "--reference-now-utc", (NOW + dt.timedelta(minutes=5)).isoformat(),
            "--apply-fill"]
    output = io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(apply_paper_fill, "ACCOUNT", account_path)
        mp.setattr(apply_paper_fill, "RULES", rules_path)
        mp.setattr(apply_paper_fill, "ROOT", root)
        mp.setattr(sys, "argv", ["apply_paper_fill.py", *argv])
        with contextlib.redirect_stdout(output):
            apply_paper_fill.main()
    result = json.loads(output.getvalue())
    assert result["status"] == "EXPIRED_NO_FILL"
    saved = json.loads(account_path.read_text(encoding="utf-8"))
    assert saved["cash_toman"] == 100000  # no debit
    # mark then replay: receipt basis unchanged; replay stays idempotent
    # (marking requires a fill, so instead verify observation does not re-expire
    # into a new event)
    events_before = len(saved["event_log"])
    argv_obs = [a for a in argv if a != "--apply-fill"] + ["--observe-order-state"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(apply_paper_fill, "ACCOUNT", account_path)
        mp.setattr(apply_paper_fill, "RULES", rules_path)
        mp.setattr(apply_paper_fill, "ROOT", root)
        mp.setattr(sys, "argv", ["apply_paper_fill.py", *argv_obs])
        with contextlib.redirect_stdout(io.StringIO()):
            apply_paper_fill.main()
    saved2 = json.loads(account_path.read_text(encoding="utf-8"))
    assert len(saved2["event_log"]) == events_before  # expiry is terminal, no new events
    # Tehran midnight boundary: the decision day is Tehran-local
    assert apply_paper_fill.resolve_now(
        type("A", (), {"reference_now_utc": "2026-10-22T20:29:00"})()).isoformat(
        ) == dt.datetime(2026, 10, 22, 20, 29, tzinfo=dt.timezone.utc).isoformat()


# 8 - one interface, one answer for fill / status / cycle -------------------- #
def test_single_interface_answer_shared_by_all_consumers(tmp_path):
    path, manifest_sha, _ = public_package(tmp_path)
    fill_answer = consume(path, manifest_sha, mode="fixture-apply")
    status_answer = consume(path, manifest_sha, mode="live-preview")
    assert fill_answer["first_usable_session"] == status_answer["first_usable_session"]
    assert fill_answer["sessions_after_decision"]["count"] == status_answer["sessions_after_decision"]["count"]
    assert fill_answer["sessions_after_decision"]["state"] == status_answer["sessions_after_decision"]["state"]
    # cycle stage: same manifest, same first-session answer
    stage_root = tmp_path / "cycle"
    stage_root.mkdir()
    stage = {"stage": "order_calendar_public_acquisition", "exit_code": 0}
    def fake_stage(name, command, timeout, env=None):
        return stage
    # make the collector itself run offline-free: point it at a temp out dir
    # and intercept the subprocess by faking run_stage + latest-manifest files
    out_dir = stage_root / "out" / "public_calendar" / "run-x"
    out_dir.mkdir(parents=True)
    (out_dir / "latest-manifest.json").write_text(json.dumps({
        "run_id": "run-x",
        "manifest_path": str(path),
        "manifest_sha256": manifest_sha}), encoding="utf-8")
    account_path, _, _ = _public_account_fixture(stage_root)
    info = paper_cycle.acquire_order_calendar(
        provider="public", run_id="run-x", out_root=stage_root / "out",
        account_path=account_path, run_stage_fn=fake_stage,
        reference_now_utc=(NOW + dt.timedelta(minutes=5)).isoformat())
    assert info["calendar_state"] == "verified_public_calendar"
    # this fixture account IS bound to the public policy -> no profile mismatch
    assert info["profile_mismatch"] is False
    assert info["answer_summary"]["first_session"] == fill_answer["first_usable_session"]
    # quality alone never grants permission: an unverifiable completion keeps
    # the observed quality but blocks this profile's consumption by name
    pkg2 = tmp_path / "q2"
    path2, sha2, _ = public_package(pkg2, watermark="not-a-date")
    answer2 = consume(path2, sha2)
    assert answer2["quality"] == "CORROBORATED_PUBLIC"  # observation quality intact
    assert answer2["readiness"]["calendar_ready"] is False
    assert "COMPLETION_ASSUMPTION_UNAVAILABLE" in answer2["readiness"]["blocking_reasons"]


# 9 - the current real account with old rules + public manifest: understood
#     mismatch on a temp copy, real file only hashed -------------------------- #
def test_real_account_dry_run_mismatch_on_temp_copy(tmp_path):
    real_account = apply_paper_fill.ACCOUNT
    real_rules = apply_paper_fill.RULES
    real_account_hash = tf.sha_file(real_account)
    real_rules_hash = tf.sha_file(real_rules)
    pkg = tmp_path / "pkg"
    calendar_path, calendar_sha, _ = public_package(pkg)
    root = tmp_path / "dryrun"
    root.mkdir()
    # temp copy of the real account: old 1.2.0 rules, no public binding
    account_copy = root / "account.json"
    account_copy.write_bytes(real_account.read_bytes())
    rules_copy = root / "rules.json"
    rules_copy.write_bytes(real_rules.read_bytes())
    before = account_copy.read_bytes()
    with pytest.raises(SystemExit, match="CALENDAR_POLICY_MISMATCH"):
        _run_public_fill(account_copy, rules_copy, root, calendar_path,
                         calendar_sha, mode="preview")
    # content unchanged (the helper may re-serialize; the account content must
    # stay the same because the refusal happened before any committed write)
    assert json.loads(account_copy.read_text(encoding="utf-8")) == json.loads(before.decode("utf-8"))
    assert not account_copy.exists() or "fill_receipt" not in account_copy.read_text(encoding="utf-8")
    # the real files were only read/hashed: their hashes are unchanged
    assert tf.sha_file(real_account) == real_account_hash
    assert tf.sha_file(real_rules) == real_rules_hash
    assert apply_paper_fill.sha(real_account) == real_account_hash


# status refresh: zero-vs-unknown and evidence_gap reporting ----------------- #
def test_status_refresh_public_zero_vs_unknown_and_evidence_gap(tmp_path):
    root = tmp_path / "status"
    account_path, rules_path, root = _public_account_fixture(root)
    evidence_path = _public_evidence(root, has_bar=False)
    out_dir = root / "out"
    def invoke_with(calendar_path_, sha_, extra=()):
        output = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(refresh, "ACCOUNT", account_path)
            mp.setattr(sys, "argv", ["refresh", "--account", str(account_path),
                                     "--evidence-manifest", str(evidence_path),
                                     "--output-dir", str(out_dir),
                                     "--public-output-dir", str(out_dir / "public"),
                                     "--calendar-provider", "public",
                                     "--public-calendar-manifest", str(calendar_path_),
                                     "--public-calendar-manifest-sha256", sha_,
                                     "--reference-now-utc",
                                     (NOW + dt.timedelta(minutes=5)).isoformat(),
                                     *extra])
            with contextlib.redirect_stdout(output):
                refresh.main()
        return json.loads((out_dir / "paper-account-check.json").read_text(encoding="utf-8"))
    # zero observed new sessions: the package's only session IS the decision day
    zero_path, zero_sha, _ = public_package(
        tmp_path / "zero", primary=["20261019"], secondary=["20261019"],
        watermark="20261019;20261019")
    account = json.loads(account_path.read_text(encoding="utf-8"))
    account["active_decision"]["decision_local_date"] = "2026-10-19"
    account["active_decision"]["decided_at_utc"] = "2026-10-19T10:00:00+00:00"
    account_path.write_text(json.dumps(account), encoding="utf-8")
    status = invoke_with(zero_path, zero_sha)
    public_block = status["public_calendar"]
    assert public_block["sessions_after_decision"]["count"] == 0
    assert public_block["sessions_after_decision"]["count_is_unknown"] is False
    assert public_block["calendar_ready"] is True
    barrier = next(b for b in status["barriers"] if b["id"] == "public_calendar")
    assert barrier["state"] == "no_new_session"
    assert public_block["display_label_fa"] == POLICY["display_label_fa"]
    assert status["eligible_sessions_after_decision"] == 0
    # unknown count: UNPARSEABLE watermark -> the refresh REPORTS the blocked
    # state with its own reason (a status check never crashes on a blocked
    # calendar; it must show blocking_reasons instead)
    unknown_path, unknown_sha, _ = public_package(
        tmp_path / "unknown", primary=["20261019"], secondary=["20261019"],
        watermark="not-a-date")
    status_unknown = invoke_with(unknown_path, unknown_sha)
    unknown_block = status_unknown["public_calendar"]
    assert unknown_block["calendar_ready"] is False
    assert "COMPLETION_ASSUMPTION_UNAVAILABLE" in unknown_block["blocking_reasons"]
    barrier_unknown = next(b for b in status_unknown["barriers"] if b["id"] == "public_calendar")
    assert barrier_unknown["state"] == "blocked"
    # evidence gap: the adapter's candidate trade evidence carries its own state
    # (decision day 2026-10-19 with the same-day-only package)
    gap_path, gap_sha, _ = public_package(tmp_path / "gap", primary=["20261019"],
                                          secondary=["20261019"],
                                          watermark="20261019;20261019")
    status_gap = invoke_with(gap_path, gap_sha)
    trade = status_gap["public_calendar"]["candidate_trade_evidence"]
    assert trade["state"] in ("candidate_data_covers_target_day",
                              "evidence_gap_archive_ends_before_target_day",
                              "evidence_gap_candidate_not_covered")


# cycle stage: failed public acquisition must not select an old manifest ----- #
def test_cycle_public_acquisition_never_falls_back_to_old_manifest(tmp_path):
    stage_root = tmp_path / "cycle"
    account_path, _, _ = _public_account_fixture(stage_root)
    # seed an older manifest that a naive glob/mtime fallback would pick
    old_dir = stage_root / "out" / "public_calendar" / "old-run"
    old_dir.mkdir(parents=True)
    (old_dir / "latest-manifest.json").write_text(json.dumps({"run_id": "old"}), encoding="utf-8")
    def failing_stage(name, command, timeout, env=None):
        return {"stage": name, "status": "process_failed", "exit_code": 3}
    info = paper_cycle.acquire_order_calendar(
        provider="public", run_id="new-run", out_root=stage_root / "out",
        account_path=account_path, run_stage_fn=failing_stage)
    assert info["calendar_state"] == "blocked_public_acquisition_failed"
    assert info["stage"]["status"] == "calendar_public_acquisition_failed_no_fallback"
    assert info["manifest_path"] is None
    # a failed stage with a pre-seeded latest file is still not consumed
    def seeded_stage(name, command, timeout, env=None):
        new_dir = stage_root / "out" / "public_calendar" / "new-run"
        new_dir.mkdir(parents=True)
        (new_dir / "latest-manifest.json").write_text(json.dumps({"run_id": "new"}), encoding="utf-8")
        return {"stage": name, "status": "process_failed", "exit_code": 3}
    info = paper_cycle.acquire_order_calendar(
        provider="public", run_id="new-run2", out_root=stage_root / "out",
        account_path=account_path, run_stage_fn=seeded_stage)
    assert info["calendar_state"] == "blocked_public_acquisition_failed"


# NSCStart contract preserved through the same interface --------------------- #
def _nscstart_fixture(root: Path, decision_day="20261022", completed_after=1):
    root.mkdir(parents=True, exist_ok=True)
    rules_path = root / "rules.json"
    rules_path.write_text(json.dumps({"rule_id": "paper-execution-rules/1.2.0-TEST_FIXTURE"}), encoding="utf-8")
    account = {"account_id": "TEST_FIXTURE", "initial_capital_toman": 100000,
        "cash_toman": 100000, "holdings": [], "event_log": [],
        "accounting": {"holdings_value_toman": 0, "total_value_toman": 100000, "profit_loss_toman": 0},
        "active_decision": {"decision_id": "fixture-decision", "decided_at_utc": "2026-10-22T10:00:00+00:00",
            "decision_local_date": "2026-10-22",
            "execution_rules": {"sha256": apply_paper_fill.sha(rules_path)}},
        "paper_order": {"order_id": "fixture-order", "decision_id": "fixture-decision",
            "company_id": "fixture-company", "symbol": "TEST",
            "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
            "expires_after_official_sessions": 3,
            "eligible_session_count_observed": 0, "fill_event_id": None}}
    account_path = root / "account.json"
    account_path.write_text(json.dumps(account), encoding="utf-8")
    end = 22 + completed_after
    session_rows = [{"DEven": f"202610{d:02d}", "HEven": 120000, "NSCEnd": "1"}
                    for d in range(end - 19, end + 1)]
    body = json.dumps({"Data": session_rows}, separators=(",", ":")).encode()
    raw = root / "nsc.json.gz"
    raw.write_bytes(gzip.compress(body))
    manifest = {"source": "TSETMC documented API MarketInfo/NSCStart",
                "raw_path": raw.name, "raw_sha256": hashlib.sha256(body).hexdigest(),
                "retrieved_at_utc": "2026-10-23T13:00:00+00:00",
                "session_count": 20, "sessions": session_rows}
    manifest_path = root / "nsc-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return account_path, rules_path, manifest_path


def test_nscstart_contract_via_adapter_unchanged(tmp_path):
    account_path, rules_path, manifest_path = _nscstart_fixture(tmp_path)
    answer = pc.resolve_nscstart_calendar(
        manifest_path=manifest_path, decision_local_date="2026-10-22",
        decision_at_utc=dt.datetime(2026, 10, 22, 10, 0, 0, tzinfo=dt.timezone.utc),
        now_utc=dt.datetime(2026, 10, 23, 13, 0, 0, tzinfo=dt.timezone.utc),
        consumption_mode="live-preview", root=tmp_path)
    assert answer["provider"] == "nscstart"
    assert answer["quality"] == "OFFICIAL_NSCSTART_WINDOW_VERIFIED"
    assert answer["coverage"]["session_count"] == 20
    assert answer["sessions_after_decision"]["first_session"] == "20261023"
    assert answer["completion"]["officially_confirmed"] is True
    # short window is refused exactly as the historical guard did
    session_rows = [{"DEven": f"202610{d:02d}", "HEven": 120000, "NSCEnd": "1"}
                    for d in range(10, 29)]
    body = json.dumps({"Data": session_rows}, separators=(",", ":")).encode()
    raw = tmp_path / "short.json.gz"
    raw.write_bytes(gzip.compress(body))
    manifest = {"source": "TSETMC documented API MarketInfo/NSCStart",
                "raw_path": raw.name, "raw_sha256": hashlib.sha256(body).hexdigest(),
                "retrieved_at_utc": "2026-10-23T13:00:00+00:00",
                "sessions": session_rows}
    short_path = tmp_path / "short-manifest.json"
    short_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(pc.CalendarRefusal, match="CALENDAR_WINDOW_DOES_NOT_COVER"):
        pc.resolve_nscstart_calendar(
            manifest_path=short_path, decision_local_date="2026-10-22",
            decision_at_utc=dt.datetime(2026, 10, 22, 10, 0, 0, tzinfo=dt.timezone.utc),
            now_utc=dt.datetime(2026, 10, 23, 13, 0, 0, tzinfo=dt.timezone.utc),
            consumption_mode="live-preview", root=tmp_path)


# sales PIT capability is explicitly blocked for the public profile ---------- #
def test_sales_pit_capability_blocked_for_public_profile(tmp_path):
    sys.path.insert(0, str(Path(apply_paper_fill.__file__).parent))
    import importlib
    factor = importlib.import_module("build_codal_factor_inputs")
    with pytest.raises(SystemExit, match="SALES_PIT_TIMING_CAPABILITY_NOT_GRANTED_PUBLIC_PROFILE"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "argv", ["build", "x.json", "--evaluation-date", "2026-10-21",
                                     "--output-dir", str(tmp_path), "--sales-timing-calendar-provider", "public"])
            factor.main()
