"""TF-02A regressions: the five independent-review defect groups, pinned.

Each test converts one finding of the TF-02 independent review into a permanent
regression against the real entrypoints: (1) one Tehran-day basis for decision
date and every window field; (2) NSCStart row-order independence plus a shared
readiness gate that also closes the official path; (3) the pinned cross-check
set rebuilt from raw at consumption time; (4) next-day replay validated at the
execution clock recorded inside the receipt; (5) mandatory four-level policy
binding shared by fill/status/cycle. All fixtures are artificial, everything
runs offline, and every ACCOUNT/RULES/OUT path is redirected to tmp_path; the
real account and ledger files are only ever read or hashed.
"""
from __future__ import annotations

import contextlib
import copy
import datetime as dt
import gzip
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ranking_research.future_eval_v12_30 import apply_paper_fill
from ranking_research.future_eval_v12_30 import paper_cycle
from ranking_research.future_eval_v12_30 import refresh_paper_decision_status as refresh
from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf
from ranking_research import paper_calendar as pc
from ranking_research.tests import test_public_market_calendar as fx
from ranking_research.tests import test_paper_calendar_interface as f

NOW = fx.NOW
POLICY_PATH = f.POLICY_PATH
POLICY_SHA = f.POLICY_SHA
POLICY = f.POLICY
NEXT_DAY = NOW + dt.timedelta(days=1)
SHORT_DAYS = ["20260901", "20260902", "20260905"]


# ---- shared local runners (real entrypoints, redirected paths) ------------- #
def _fill_invoke(account_path, rules_path, root, calendar_path, calendar_sha, *,
                 evidence_path, mode="apply", clock=None, policy_path=POLICY_PATH,
                 calendar_provider="public"):
    """Run the real fill entrypoint once; refusals are data, not test errors."""
    argv = ["--session-calendar-manifest", str(calendar_path),
            "--evidence-manifest", str(evidence_path)]
    if calendar_provider is not None:
        argv += ["--calendar-provider", calendar_provider]
    argv += ["--calendar-policy", str(policy_path),
            "--reference-now-utc", (clock or NOW + dt.timedelta(minutes=5)).isoformat()]
    if calendar_provider == "public":
        argv += ["--calendar-manifest-sha256", calendar_sha]
    if mode == "apply":
        argv.append("--apply-fill")
    elif mode == "observe":
        argv.append("--observe-order-state")
    stream = io.StringIO()
    error = None
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(apply_paper_fill, "ACCOUNT", account_path)
        mp.setattr(apply_paper_fill, "RULES", rules_path)
        mp.setattr(apply_paper_fill, "ROOT", root)
        mp.setattr(sys, "argv", ["apply_paper_fill.py", *argv])
        with contextlib.redirect_stdout(stream):
            try:
                apply_paper_fill.main()
            except SystemExit as exc:
                error = str(exc)
    stdout = stream.getvalue().strip()
    return {"error": error,
            "stdout": json.loads(stdout) if stdout and not error else None}


def _short_package(pkg_dir):
    return f.public_package(pkg_dir, primary=SHORT_DAYS, secondary=SHORT_DAYS,
                            watermark="20260905;20260905")


def _write_json(path, doc):
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tf.sha_file(path)


def _assert_untouched(account_path, before_bytes):
    assert account_path.read_bytes() == before_bytes
    saved = json.loads(before_bytes)
    assert saved["cash_toman"] == 100000 and saved["holdings"] == []
    assert saved["event_log"] == []
    assert "fill_receipt" not in saved["paper_order"]
    assert saved["paper_order"]["status"] == "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE"


# =========================================================================== #
# Group 1 — one Tehran-day basis for the decision date and the window        #
# =========================================================================== #
def test_g1_control_two_session_package_first_and_count(tmp_path):
    path, sha, _ = _short_package(tmp_path / "pkg")
    answer = f.consume(path, sha)
    assert answer["readiness"]["calendar_ready"] is True
    assert answer["quality"] == "CORROBORATED_PUBLIC"
    assert answer["first_usable_session"] == "20260902"
    assert answer["eligible_session_count"] == 2
    assert answer["sessions_after_decision"]["sessions"] == ["20260902", "20260905"]


@pytest.mark.parametrize("tamper", ["inner_window", "outer_window"])
def test_g1_window_disagreement_refused_before_any_account_change(tmp_path, tamper):
    path, sha, manifest = _short_package(tmp_path / "pkg")
    changed = copy.deepcopy(manifest)
    if tamper == "inner_window":
        changed["policy"]["window_start"] = "20260902"
    else:
        changed["window_start"] = "20260902"
    new_sha = _write_json(path, changed)
    # a fresh correct hash proves the file is unchanged, never that it agrees
    # with itself: the mismatched basis is refused structurally
    with pytest.raises(pc.CalendarRefusal, match="CALENDAR_WINDOW_MISMATCH"):
        f.consume(path, new_sha)
    root = tmp_path / "run"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root, bar_day="20260905")  # the wrong-day price
    before = account_path.read_bytes()
    result = _fill_invoke(account_path, rules_path, root, path, new_sha,
                          evidence_path=evidence_path, mode="apply")
    assert result["error"] is not None and "CALENDAR_WINDOW_MISMATCH" in result["error"]
    _assert_untouched(account_path, before)


def test_g1_duplicated_field_disagreement_refused(tmp_path):
    path, sha, manifest = _short_package(tmp_path / "pkg")
    for field, inner in (("market_scope", True), ("policy_version", True)):
        changed = copy.deepcopy(manifest)
        if inner:
            changed["policy"][field] = "TAMPERED"
        else:
            changed[field] = "TAMPERED"
        new_sha = _write_json(path, changed)
        with pytest.raises(pc.CalendarRefusal, match="CALENDAR_MANIFEST_INTERNAL_INCONSISTENT"):
            f.consume(path, new_sha)
    changed = copy.deepcopy(manifest)
    changed["policy"]["indices"][0]["ins_code"] = "1" * 17
    new_sha = _write_json(path, changed)
    with pytest.raises(pc.CalendarRefusal, match="CALENDAR_MANIFEST_INTERNAL_INCONSISTENT"):
        f.consume(path, new_sha)


def test_g1_decision_datetime_must_describe_the_same_teheran_day(tmp_path):
    path, sha, _ = _short_package(tmp_path / "pkg")  # window/decision day 20260901
    # 2026-08-31T20:30Z is exactly Tehran midnight 2026-09-01 00:00: accepted
    ok = f.consume(path, sha, decision_at=dt.datetime(2026, 8, 31, 20, 30,
                                                      tzinfo=dt.timezone.utc))
    assert ok["readiness"]["calendar_ready"] is True
    # one second earlier is still Tehran 2026-08-31: refused, no second basis
    with pytest.raises(pc.CalendarRefusal, match="DECISION_DATE_TIME_INCONSISTENT"):
        f.consume(path, sha, decision_at=dt.datetime(2026, 8, 31, 20, 29, 59,
                                                     tzinfo=dt.timezone.utc))
    # past Tehran midnight of the decision day: the UTC instant names 09-02
    with pytest.raises(pc.CalendarRefusal, match="DECISION_DATE_TIME_INCONSISTENT"):
        f.consume(path, sha, decision_at=dt.datetime(2026, 9, 1, 20, 30,
                                                     tzinfo=dt.timezone.utc))


# =========================================================================== #
# Group 2 — NSCStart row order + shared readiness gate                       #
# =========================================================================== #
NSC_KWARGS = dict(decision_local_date="2026-10-22",
                  decision_at_utc=dt.datetime(2026, 10, 22, 10, tzinfo=dt.timezone.utc),
                  now_utc=dt.datetime(2026, 10, 24, 13, tzinfo=dt.timezone.utc),
                  consumption_mode="live-preview")


def _nsc_package(root: Path, rows, retrieved="2026-10-24T13:00:00+00:00"):
    root.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"Data": rows}, separators=(",", ":")).encode()
    raw = root / "nsc.json.gz"
    raw.write_bytes(gzip.compress(body))
    manifest = {"source": "TSETMC documented API MarketInfo/NSCStart",
                "raw_path": raw.name, "raw_sha256": hashlib.sha256(body).hexdigest(),
                "retrieved_at_utc": retrieved, "sessions": rows}
    path = root / "nsc-manifest.json"
    _write_json(path, manifest)
    return path


def _nsc_rows():
    return [{"DEven": f"202610{d:02d}", "HEven": 120000, "NSCEnd": "1"}
            for d in range(5, 25)]


def _brief(answer):
    return (answer["first_usable_session"], answer["eligible_session_count"],
            answer["coverage"]["first"], answer["coverage"]["last"])


def test_g2_nscstart_first_latest_count_ignore_row_order(tmp_path):
    rows = _nsc_rows()
    ascending = _nsc_package(tmp_path / "asc", rows)
    expected = ("20261023", 2, "20261005", "20261024")
    assert _brief(pc.resolve_nscstart_calendar(manifest_path=ascending,
                                               root=tmp_path / "asc", **NSC_KWARGS)) == expected
    descending = _nsc_package(tmp_path / "desc", list(reversed(rows)))
    assert _brief(pc.resolve_nscstart_calendar(manifest_path=descending,
                                               root=tmp_path / "desc", **NSC_KWARGS)) == expected
    shuffled_rows = [rows[7], rows[19], rows[0], rows[12], rows[3],
                     *[r for i, r in enumerate(rows) if i not in (0, 3, 7, 12, 19)]]
    assert shuffled_rows != rows and sorted(shuffled_rows, key=lambda r: r["DEven"]) == rows
    shuffled = _nsc_package(tmp_path / "mixed", shuffled_rows)
    assert _brief(pc.resolve_nscstart_calendar(manifest_path=shuffled,
                                               root=tmp_path / "mixed", **NSC_KWARGS)) == expected


def _nsc_account_evidence(root: Path, *, bar_day="20261023"):
    """A pending 1.2.0-style account plus NSCStart evidence (no public binding)."""
    root.mkdir(parents=True, exist_ok=True)
    rules_path = root / "rules.json"
    _write_json(rules_path, {"rule_id": "paper-execution-rules/1.2.0-TEST_FIXTURE"})
    account = {"account_id": "TEST_FIXTURE_NSC", "initial_capital_toman": 100000,
               "cash_toman": 100000, "holdings": [], "event_log": [],
               "created_at_utc": "2026-10-22T09:00:00+00:00",
               "accounting": {"holdings_value_toman": 0, "total_value_toman": 100000,
                              "profit_loss_toman": 0},
               "active_decision": {"decision_id": "nsc-decision",
                                   "decided_at_utc": "2026-10-22T10:00:00+00:00",
                                   "decision_local_date": "2026-10-22",
                                   "execution_rules": {"sha256": apply_paper_fill.sha(rules_path)}},
               "paper_order": {"order_id": "nsc-order", "decision_id": "nsc-decision",
                               "company_id": "fixture-company", "symbol": "TEST",
                               "status": "PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE",
                               "expires_after_official_sessions": 3,
                               "eligible_session_count_observed": 0, "fill_event_id": None}}
    account_path = root / "account.json"
    _write_json(account_path, account)
    daily_rows = [{"dEven": bar_day, "insCode": "123", "pClosing": 1234,
                   "qTotTran5J": 10000}]
    sources = []
    for key, doc in (("candidate_daily", {"closingPriceDaily": daily_rows}),
                     ("candidate_share_changes", {"instrumentShareChange": []}),
                     ("last_possible_session", {})):
        body = json.dumps(doc, separators=(",", ":")).encode()
        raw = root / f"{key}.gz"
        raw.write_bytes(gzip.compress(body))
        entry = {"key": key, "raw_path": raw.name,
                 "raw_sha256": hashlib.sha256(body).hexdigest(),
                 "retrieved_at_utc": "2026-10-24T13:00:00+00:00"}
        if key == "candidate_daily":
            entry["url"] = "https://example.invalid/123/0"
        if key == "last_possible_session":
            entry["reported_last_possible_session"] = "20261024"
        sources.append(entry)
    evidence_path = root / "evidence.json"
    _write_json(evidence_path, {"ins_code": "123",
                                "candidate": {"company_id": "fixture-company"},
                                "sources": sources})
    return account_path, rules_path, evidence_path


def test_g2_predating_nscstart_manifest_blocks_the_fill_entrypoint(tmp_path):
    root = tmp_path / "run"
    root.mkdir(parents=True)
    account_path, rules_path, evidence_path = _nsc_account_evidence(root)
    manifest_path = _nsc_package(root, _nsc_rows(),
                                 retrieved="2026-10-21T13:00:00+00:00")
    # the adapter itself answers blocked with the real reason
    answer = pc.resolve_nscstart_calendar(manifest_path=manifest_path,
                                          root=root, **NSC_KWARGS)
    assert answer["readiness"]["calendar_ready"] is False
    assert answer["readiness"]["blocking_reasons"] == ["SOURCE_RETRIEVED_BEFORE_DECISION"]
    # and the shared gate closes the official path at the entrypoint too
    before = account_path.read_bytes()
    result = _fill_invoke(account_path, rules_path, root, manifest_path, None,
                          evidence_path=evidence_path, mode="apply",
                          calendar_provider="nscstart",
                          clock=dt.datetime(2026, 10, 24, 13, tzinfo=dt.timezone.utc))
    assert result["error"] == "CALENDAR_NOT_READY;SOURCE_RETRIEVED_BEFORE_DECISION"
    _assert_untouched(account_path, before)


def test_g2_healthy_nscstart_fixture_still_buys_from_the_entrypoint(tmp_path):
    # guards against fixing the review finding by unconditionally closing the
    # official path: a fresh, after-decision manifest still fills
    root = tmp_path / "run"
    root.mkdir(parents=True)
    account_path, rules_path, evidence_path = _nsc_account_evidence(root)
    manifest_path = _nsc_package(root, _nsc_rows())
    result = _fill_invoke(account_path, rules_path, root, manifest_path, None,
                          evidence_path=evidence_path, mode="apply",
                          calendar_provider="nscstart",
                          clock=dt.datetime(2026, 10, 24, 13, tzinfo=dt.timezone.utc))
    assert result["error"] is None
    assert result["stdout"]["status"] == "FILL_APPLIED"
    assert result["stdout"]["first_session"] == "20261023"
    saved = json.loads(account_path.read_text(encoding="utf-8"))
    assert saved["cash_toman"] == 43 and len(saved["event_log"]) == 1


# =========================================================================== #
# Group 3 — the pinned cross-check set is rebuilt from raw at consumption    #
# =========================================================================== #
def _multi_symbol_package(pkg_dir, *, other_days=None, max_symbols=None,
                          test_days=None):
    records = [("TEST", fx.CANDIDATE_INS,
                [fx.daily_row(fx.CANDIDATE_INS, d)
                 for d in (test_days or SHORT_DAYS)])]
    if other_days is not None:
        records.append(("OTHER1", "11111111111111112",
                        [fx.daily_row("11111111111111112", d) for d in other_days]))
    return f.public_package(pkg_dir, primary=SHORT_DAYS, secondary=SHORT_DAYS,
                            watermark="20260905;20260905", snapshot_records=records,
                            max_symbols=max_symbols)


@pytest.mark.parametrize("corrupt", ["raw_tampered", "raw_missing",
                                     "snapshot_manifest_changed",
                                     "selection_changed"])
def test_g3_broken_pinned_cross_inputs_refused_at_consumption(tmp_path, corrupt):
    path, sha, manifest = _multi_symbol_package(tmp_path / "pkg",
                                                other_days=SHORT_DAYS)
    if corrupt == "raw_tampered":
        raw_path = tf.resolve_repo_path(manifest["stock_cross_check"]
                                        ["daily_inputs"]["TEST"]["path"])
        original = raw_path.read_bytes()
        raw_path.write_bytes(gzip.compress(b"corrupted TEST_FIXTURE archive"))
    elif corrupt == "raw_missing":
        raw_path = tf.resolve_repo_path(manifest["stock_cross_check"]
                                        ["daily_inputs"]["TEST"]["path"])
        raw_path.unlink()
    elif corrupt == "snapshot_manifest_changed":
        snap = tf.resolve_repo_path(manifest["stock_cross_check"]["snapshot_dir"])
        doc = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
        doc["retrieved_at_utc"] = "2026-10-01T00:00:00+00:00"
        (snap / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    else:  # selection_changed: an announced set the pinned raw cannot rebuild
        changed = copy.deepcopy(manifest)
        changed["stock_cross_check"]["by_symbol"]["GHOST"] = ["20260902"]
        sha = _write_json(path, changed)
    with pytest.raises(pc.CalendarRefusal, match="STOCK_CROSS_REPLAY_FAILED"):
        f.consume(path, sha)
    # at least one broken case also stops the real entrypoint byte-identically
    if corrupt == "raw_tampered":
        root = tmp_path / "run"
        account_path, rules_path, root = f._public_account_fixture(root)
        evidence_path = f._public_evidence(root)
        before = account_path.read_bytes()
        result = _fill_invoke(account_path, rules_path, root, path, sha,
                              evidence_path=evidence_path, mode="apply")
        assert result["error"] is not None
        assert "STOCK_CROSS_REPLAY_FAILED" in result["error"]
        _assert_untouched(account_path, before)


def test_g3_rebuilt_conflict_closes_readiness(tmp_path):
    # OTHER1 traded on 20260904 (a Friday) which the corroborated calendar does
    # not list: a real rebuilt witness, so readiness closes with CONFLICT
    path, sha, manifest = _multi_symbol_package(tmp_path / "pkg",
                                                other_days=["20260904", "20260905"])
    answer = f.consume(path, sha)
    assert answer["readiness"]["calendar_ready"] is False
    assert "CALENDAR_QUALITY_CONFLICT" in answer["readiness"]["blocking_reasons"]
    assert any(c.get("type") == "stock_trade_date_outside_calendar"
               for c in answer["conflicts"])
    assert answer["stock_cross_check"]["rebuilt_from_pinned_raw"] is True


@pytest.mark.parametrize("max_symbols,checked", [(0, 0), (1, 1), (None, 2)])
def test_g3_empty_one_and_limited_selections_still_consume(tmp_path, max_symbols, checked):
    path, sha, _ = _multi_symbol_package(tmp_path / f"pkg-{max_symbols}",
                                         other_days=SHORT_DAYS,
                                         max_symbols=max_symbols)
    answer = f.consume(path, sha)
    assert answer["readiness"]["calendar_ready"] is True
    assert answer["first_usable_session"] == "20260902"
    assert answer["eligible_session_count"] == 2
    assert answer["stock_cross_check"]["eligible_symbols_checked"] == checked


def _refresh_status(tmp_path, root, *, calendar_path, calendar_sha,
                    account_path, rules_path, evidence_path):
    out_dir = root / "out"
    stream = io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(refresh, "ACCOUNT", account_path)
        mp.setattr(sys, "argv", ["refresh", "--account", str(account_path),
                                 "--evidence-manifest", str(evidence_path),
                                 "--execution-rules", str(rules_path),
                                 "--output-dir", str(out_dir),
                                 "--public-output-dir", str(out_dir / "public"),
                                 "--calendar-provider", "public",
                                 "--public-calendar-manifest", str(calendar_path),
                                 "--public-calendar-manifest-sha256", calendar_sha,
                                 "--reference-now-utc",
                                 (NOW + dt.timedelta(minutes=5)).isoformat()])
        with contextlib.redirect_stdout(stream):
            refresh.main()
    return json.loads((out_dir / "paper-account-check.json").read_text(encoding="utf-8"))


def test_g3_refresh_consumes_candidate_witness_and_short_archive_is_gap(tmp_path):
    # covering archive: TEST traded through 20260905, so the first usable
    # session 20260902 is witnessed by the rebuilt pinned archive
    path, sha, _ = _multi_symbol_package(tmp_path / "cover", test_days=SHORT_DAYS)
    root = tmp_path / "run-cover"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root)
    status = _refresh_status(tmp_path, root, calendar_path=path, calendar_sha=sha,
                             account_path=account_path, rules_path=rules_path,
                             evidence_path=evidence_path)
    trade = status["public_calendar"]["candidate_trade_evidence"]
    assert trade["trade_status"] == "checked"
    assert trade["state"] == "candidate_data_covers_target_day"
    assert trade["archive_end"] == "20260905"
    # shorter archive: TEST's rows stop on the decision day itself, before the
    # target session — an evidence gap, never a suspension/no-trade verdict
    short_path, short_sha, _ = _multi_symbol_package(tmp_path / "short",
                                                     test_days=["20260901"])
    root2 = tmp_path / "run-short"
    account2, rules2, root2 = f._public_account_fixture(root2)
    evidence2 = f._public_evidence(root2)
    status2 = _refresh_status(tmp_path, root2, calendar_path=short_path,
                              calendar_sha=short_sha, account_path=account2,
                              rules_path=rules2, evidence_path=evidence2)
    trade2 = status2["public_calendar"]["candidate_trade_evidence"]
    assert trade2["trade_status"] == "checked"
    assert trade2["state"] == "evidence_gap_archive_ends_before_target_day"
    assert trade2["archive_end"] == "20260901"


# =========================================================================== #
# Group 4 — next-day replay at the receipt's recorded validation clock       #
# =========================================================================== #
def test_g4_next_day_replay_succeeds_via_recorded_clock(tmp_path):
    path, sha, _ = _short_package(tmp_path / "pkg")
    root = tmp_path / "run"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root)
    first = _fill_invoke(account_path, rules_path, root, path, sha,
                         evidence_path=evidence_path, mode="apply",
                         clock=NOW + dt.timedelta(minutes=5))
    assert first["error"] is None and first["stdout"]["status"] == "FILL_APPLIED"
    filled_bytes = account_path.read_bytes()
    filled = json.loads(filled_bytes)
    receipt = filled["paper_order"]["fill_receipt"]
    recorded = receipt["calendar"]["validated_at_utc"]
    assert recorded == (NOW + dt.timedelta(minutes=5)).isoformat()
    assert (filled["cash_toman"], len(filled["event_log"]),
            len(filled["holdings"])) == (43, 1, 1)
    # retry the very next day WITHOUT re-injecting the original clock: the
    # validation time is recovered from the receipt, never taken from today
    replay = _fill_invoke(account_path, rules_path, root, path, sha,
                          evidence_path=evidence_path, mode="apply",
                          clock=NEXT_DAY)
    assert replay["error"] is None
    assert replay["stdout"]["status"] == "FILL_ALREADY_APPLIED"
    assert replay["stdout"]["replayed_at_recorded_validation_clock"] == recorded
    assert account_path.read_bytes() == filled_bytes  # one debit only
    # the same behaviour holds after a mark changes only the valuation
    from ranking_research.future_eval_v12_30.check_paper_account import apply_mark
    marked = json.loads(account_path.read_text(encoding="utf-8"))
    marked["accounting"] = apply_mark(marked["holdings"][0], marked["cash_toman"],
                                      1300, "2026-10-24")
    from ranking_research import paper_account_store
    paper_account_store.write_account_atomic(account_path, marked)
    marked_bytes = account_path.read_bytes()
    replay_marked = _fill_invoke(account_path, rules_path, root, path, sha,
                                 evidence_path=evidence_path, mode="apply",
                                 clock=NEXT_DAY)
    assert replay_marked["stdout"]["status"] == "FILL_ALREADY_APPLIED"
    assert account_path.read_bytes() == marked_bytes


@pytest.mark.parametrize("case", ["other_manifest_sha", "other_policy",
                                  "other_evidence", "clockless_receipt"])
def test_g4_replay_refuses_changed_inputs_or_unprovable_clock(tmp_path, case):
    path, sha, _ = _short_package(tmp_path / "pkg")
    root = tmp_path / f"run-{case}"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root)
    assert _fill_invoke(account_path, rules_path, root, path, sha,
                        evidence_path=evidence_path, mode="apply",
                        clock=NOW + dt.timedelta(minutes=5))["stdout"]["status"] == "FILL_APPLIED"
    before = account_path.read_bytes()
    invoke_sha, invoke_policy, invoke_evidence = sha, POLICY_PATH, evidence_path
    if case == "other_manifest_sha":
        invoke_sha = "0" * 64
    elif case == "other_policy":
        doc = copy.deepcopy(POLICY)
        doc["display_label_fa"] += " (تغییر یافته)"
        invoke_policy = root / "policy-other.json"
        _write_json(invoke_policy, doc)
    elif case == "other_evidence":
        # a separate root with its own consistent evidence (same account copy):
        # valid evidence in itself, but not the evidence the receipt pinned
        other_root = tmp_path / "other-root"
        other_root.mkdir()
        (other_root / "account.json").write_bytes(account_path.read_bytes())
        (other_root / "rules.json").write_bytes(rules_path.read_bytes())
        invoke_evidence = f._public_evidence(other_root, bar_day="20260905")
        account_path, rules_path, root = (other_root / "account.json",
                                          other_root / "rules.json", other_root)
    else:  # clockless_receipt: strip the recorded clock, never fabricate one
        doc = json.loads(account_path.read_text(encoding="utf-8"))
        doc["paper_order"]["fill_receipt"]["calendar"].pop("validated_at_utc")
        _write_json(account_path, doc)
        before = account_path.read_bytes()
    result = _fill_invoke(account_path, rules_path, root, path, invoke_sha,
                          evidence_path=invoke_evidence, mode="apply",
                          clock=NEXT_DAY, policy_path=invoke_policy)
    expected = {"other_manifest_sha": "FILL_REPLAY_INPUTS_CHANGED",
                "other_policy": "CALENDAR_POLICY_MISMATCH",
                "other_evidence": "FILL_REPLAY_INPUTS_CHANGED",
                "clockless_receipt": "FILL_REPLAY_VALIDATION_CLOCK_UNPROVABLE"}[case]
    assert result["error"] is not None and expected in result["error"]
    assert account_path.read_bytes() == before  # the old receipt is never rewritten


def test_g4_fresh_account_does_not_buy_with_the_old_raw_next_day(tmp_path):
    path, sha, _ = _short_package(tmp_path / "pkg")
    spent_root = tmp_path / "spent"
    spent_account, spent_rules, spent_root = f._public_account_fixture(spent_root)
    spent_evidence = f._public_evidence(spent_root)
    assert _fill_invoke(spent_account, spent_rules, spent_root, path, sha,
                        evidence_path=spent_evidence, mode="apply",
                        clock=NOW + dt.timedelta(minutes=5))["stdout"]["status"] == "FILL_APPLIED"
    # a brand-new bound account offers the SAME (now stale) raws one day later:
    # there is no receipt to recover a clock from, so nothing may be bought
    fresh_root = tmp_path / "fresh"
    fresh_account, fresh_rules, fresh_root = f._public_account_fixture(fresh_root)
    fresh_evidence = f._public_evidence(fresh_root)
    before = fresh_account.read_bytes()
    result = _fill_invoke(fresh_account, fresh_rules, fresh_root, path, sha,
                          evidence_path=fresh_evidence, mode="apply", clock=NEXT_DAY)
    assert result["error"] is not None
    assert "CALENDAR_NOT_READY" in result["error"]
    assert "FRESHNESS_SOURCE_STALE" in result["error"]
    _assert_untouched(fresh_account, before)


PUBLIC_FILL_CHILD = r'''import os,sys
from pathlib import Path
from ranking_research.future_eval_v12_30 import apply_paper_fill as m
m.ROOT=Path(sys.argv[1]); m.ACCOUNT=Path(sys.argv[2]); m.RULES=Path(sys.argv[3])
sys.argv=['apply_paper_fill.py',*sys.argv[4:]]
real=os.replace
mode=sys.argv[-1]
if mode=='DIE_BEFORE_REPLACE':
 def die_before(*a,**k): os._exit(75)
 os.replace=die_before
else:
 def die_after(*a,**k): real(*a,**k); os._exit(74)
 os.replace=die_after
sys.argv=sys.argv[:-1]
m.main()
'''


def _run_fill_child(root, account_path, rules_path, argv, mode_flag):
    return subprocess.run([sys.executable, "-c", PUBLIC_FILL_CHILD, str(root),
                           str(account_path), str(rules_path), *argv, mode_flag],
                          cwd=Path.cwd(), capture_output=True, text=True, timeout=60)


def test_g4_crash_harness_atomicity_and_clock_rules(tmp_path):
    path, sha, _ = _short_package(tmp_path / "pkg")
    root = tmp_path / "run"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root)
    argv = ["--session-calendar-manifest", str(path),
            "--calendar-manifest-sha256", sha,
            "--evidence-manifest", str(evidence_path),
            "--calendar-provider", "public",
            "--calendar-policy", str(POLICY_PATH),
            "--reference-now-utc", (NOW + dt.timedelta(minutes=5)).isoformat(),
            "--apply-fill"]
    pre_state = account_path.read_bytes()
    # cut BEFORE the atomic replace: the file keeps its valid pre-fill state
    crashed = _run_fill_child(root, account_path, rules_path, argv, "DIE_BEFORE_REPLACE")
    assert crashed.returncode == 75
    assert account_path.read_bytes() == pre_state
    # the honest next-day retry of an uncommitted fill has no recorded clock to
    # recover: stale evidence refuses and no fabricated past clock may buy
    retry = _fill_invoke(account_path, rules_path, root, path, sha,
                         evidence_path=evidence_path, mode="apply", clock=NEXT_DAY)
    assert retry["error"] is not None and "CALENDAR_NOT_READY" in retry["error"]
    assert account_path.read_bytes() == pre_state
    # cut AFTER the replace: exactly one committed fill…
    committed = _run_fill_child(root, account_path, rules_path, argv, "DIE_AFTER_REPLACE")
    assert committed.returncode == 74
    saved = json.loads(account_path.read_text(encoding="utf-8"))
    assert (saved["cash_toman"], len(saved["event_log"])) == (43, 1)
    committed_bytes = account_path.read_bytes()
    # …and the next-day retry replays at the receipt clock without a second debit
    replay = _fill_invoke(account_path, rules_path, root, path, sha,
                          evidence_path=evidence_path, mode="apply", clock=NEXT_DAY)
    assert replay["stdout"]["status"] == "FILL_ALREADY_APPLIED"
    assert account_path.read_bytes() == committed_bytes


# =========================================================================== #
# Group 5 — mandatory four-level binding shared by every consumer            #
# =========================================================================== #
@pytest.mark.parametrize("level,mode", [
    ("account", "missing"), ("account", "wrong_id"), ("account", "wrong_sha"),
    ("decision", "missing"), ("decision", "wrong_id"),
    ("order", "missing"), ("order", "wrong_sha"),
    ("rules", "missing"), ("rules", "wrong_id"), ("rules", "wrong_sha"),
    ("account+order", "wrong_id+missing"),  # the exact combination the review bought with
])
def test_g5_binding_is_mandatory_and_consistent_at_every_level(tmp_path, level, mode):
    path, sha, _ = _short_package(tmp_path / "pkg")
    root = tmp_path / f"run-{level}-{mode}"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root)

    def mutate(doc, name, how):
        if how == "missing":
            doc.pop(name, None)
        else:
            doc[name] = {"id": "WRONG_POLICY" if "id" in how else POLICY["policy_id"],
                         "sha256": "0" * 64 if "sha" in how else POLICY_SHA}
    account_doc = json.loads(account_path.read_text(encoding="utf-8"))
    rules_doc = json.loads(rules_path.read_text(encoding="utf-8"))
    if level in ("account", "account+order"):
        mutate(account_doc, "calendar_policy", mode if level == "account" else "wrong_id")
    if level == "decision":
        mutate(account_doc["active_decision"], "calendar_policy", mode)
    if level in ("order", "account+order"):
        if level == "order":
            mutate(account_doc["paper_order"], "calendar_policy", mode)
        else:
            account_doc["paper_order"].pop("calendar_policy", None)
    if level == "rules":
        mutate(rules_doc, "calendar_policy", mode)
    _write_json(rules_path, rules_doc)
    # keep the account pinned to exactly the (mutated) rules file so the early
    # rules-hash guard stays satisfied and the binding check itself must fire
    account_doc["active_decision"]["execution_rules"]["sha256"] = \
        apply_paper_fill.sha(rules_path)
    _write_json(account_path, account_doc)
    before = account_path.read_bytes()
    result = _fill_invoke(account_path, rules_path, root, path, sha,
                          evidence_path=evidence_path, mode="apply")
    assert result["error"] is not None and "CALENDAR_POLICY_MISMATCH" in result["error"]
    _assert_untouched(account_path, before)
    # the healthy control with every level bound still buys (same package)
    control_root = tmp_path / "control"
    control_account, control_rules, control_root = f._public_account_fixture(control_root)
    control_evidence = f._public_evidence(control_root)
    control = _fill_invoke(control_account, control_rules, control_root, path, sha,
                           evidence_path=control_evidence, mode="apply")
    assert control["error"] is None and control["stdout"]["status"] == "FILL_APPLIED"


def _cycle_stage(stage_root, *, calendar_path, calendar_sha, account_path,
                 rules_path, manifest_sha=None, drop_latest=False):
    def fake_stage(name, command, timeout, env=None):
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        if not drop_latest:
            manifest = json.loads(calendar_path.read_text(encoding="utf-8"))
            target = out_dir / "manifest.json"
            target.write_text(json.dumps(manifest), encoding="utf-8")
            reference = {"run_id": manifest.get("run_id"),
                         "manifest_path": str(target),
                         "manifest_sha256": manifest_sha or tf.sha_file(target)}
            (out_dir / "latest-manifest.json").write_text(json.dumps(reference),
                                                          encoding="utf-8")
        return {"stage": name, "exit_code": 0}
    return paper_cycle.acquire_order_calendar(
        provider="public", run_id="run-x", out_root=stage_root / "out",
        account_path=account_path, rules_path=rules_path, run_stage_fn=fake_stage,
        reference_now_utc=(NOW + dt.timedelta(minutes=5)).isoformat())


def test_g5_one_input_consistent_across_fill_status_and_cycle(tmp_path):
    # healthy package: three real entrypoints, one first/count answer
    path, sha, _ = _short_package(tmp_path / "pkg")
    root = tmp_path / "run"
    account_path, rules_path, root = f._public_account_fixture(root)
    evidence_path = f._public_evidence(root)
    fill = _fill_invoke(account_path, rules_path, root, path, sha,
                        evidence_path=evidence_path, mode="preview")
    assert fill["stdout"]["status"] == "FILL_ELIGIBLE_PREVIEW_ONLY"
    assert fill["stdout"]["first_session"] == "20260902"
    assert fill["stdout"]["sessions_after_decision"] == 2
    status = _refresh_status(tmp_path, root, calendar_path=path, calendar_sha=sha,
                             account_path=account_path, rules_path=rules_path,
                             evidence_path=evidence_path)
    public_block = status["public_calendar"]
    assert public_block["sessions_after_decision"]["first_session"] == "20260902"
    assert public_block["sessions_after_decision"]["count"] == 2
    assert public_block["calendar_ready"] is True
    assert next(b for b in status["barriers"] if b["id"] == "public_calendar")["state"] \
        == "first_session_available"
    info = _cycle_stage(tmp_path / "cycle", calendar_path=path,
                        calendar_sha=sha, account_path=account_path,
                        rules_path=rules_path)
    assert info["calendar_state"] == "verified_public_calendar"
    assert info["profile_mismatch"] is False
    assert info["answer_summary"]["first_session"] == "20260902"
    assert info["answer_summary"]["session_count"] == 2
    # the same inputs with an unverifiable completion are blocked everywhere
    # with the SAME reason, never with three different stories
    blocked_pkg = tmp_path / "blocked"
    blocked_path, blocked_sha, _ = f.public_package(
        blocked_pkg, primary=SHORT_DAYS, secondary=SHORT_DAYS, watermark="not-a-date")
    blocked_fill = _fill_invoke(account_path, rules_path, root, blocked_path,
                                blocked_sha, evidence_path=evidence_path,
                                mode="preview")
    assert "CALENDAR_NOT_READY" in blocked_fill["error"]
    assert "COMPLETION_ASSUMPTION_UNAVAILABLE" in blocked_fill["error"]
    blocked_status = _refresh_status(tmp_path, tmp_path / "run-blocked",
                                     calendar_path=blocked_path,
                                     calendar_sha=blocked_sha,
                                     account_path=account_path,
                                     rules_path=rules_path, evidence_path=evidence_path)
    blocked_barrier = next(b for b in blocked_status["barriers"]
                           if b["id"] == "public_calendar")
    assert blocked_barrier["state"] == "blocked"
    assert "COMPLETION_ASSUMPTION_UNAVAILABLE" in blocked_barrier["details"]
    blocked_info = _cycle_stage(tmp_path / "cycle-blocked",
                                calendar_path=blocked_path, calendar_sha=blocked_sha,
                                account_path=account_path, rules_path=rules_path)
    assert blocked_info["calendar_state"] == "blocked_public_calendar_not_ready"
    assert "COMPLETION_ASSUMPTION_UNAVAILABLE" in ",".join(
        blocked_info["answer_summary"]["blocking_reasons"])


def test_g5_cycle_with_fake_acquisition_outcomes(tmp_path):
    path, sha, _ = _short_package(tmp_path / "pkg")
    stage_root = tmp_path / "cycle"
    account_path, rules_path, _ = f._public_account_fixture(stage_root)
    # success but a hash-mismatched pointer: the manifest is not consumed
    info = _cycle_stage(stage_root, calendar_path=path, calendar_sha=sha,
                        account_path=account_path, rules_path=rules_path,
                        manifest_sha="0" * 64)
    assert info["calendar_state"] == "blocked_public_manifest_hash_mismatch"
    assert info["stage"]["status"] == "public_manifest_hash_mismatch"
    # success but no latest pointer at all: no glob/mtime fallback
    info = _cycle_stage(tmp_path / "cycle-nopointer", calendar_path=path,
                        calendar_sha=sha, account_path=account_path,
                        rules_path=rules_path, drop_latest=True)
    assert info["calendar_state"] == "blocked_public_manifest_missing"
    assert info["manifest_path"] is None


def test_g5_real_account_copy_reports_mismatch_in_refresh_and_keeps_ledger(tmp_path):
    real_account = apply_paper_fill.ACCOUNT
    real_rules = apply_paper_fill.RULES
    hashes = {p: tf.sha_file(p) for p in (real_account, real_rules)}
    path, sha, _ = _short_package(tmp_path / "pkg")
    root = tmp_path / "dryrun"
    root.mkdir()
    account_copy = root / "account.json"
    account_copy.write_bytes(real_account.read_bytes())
    rules_copy = root / "rules.json"
    rules_copy.write_bytes(real_rules.read_bytes())
    evidence_path = f._public_evidence(root)
    status = _refresh_status(tmp_path, root, calendar_path=path, calendar_sha=sha,
                             account_path=account_copy, rules_path=rules_copy,
                             evidence_path=evidence_path)
    block = status["public_calendar"]
    # quality and account compatibility stay two separate reports; a mismatched
    # account is never presented as ready
    assert block["account_compatibility"]["state"] == "mismatch"
    assert "CALENDAR_POLICY_MISMATCH" in block["account_compatibility"]["mismatch_detail"]
    assert block["calendar_ready"] is False
    assert "CALENDAR_POLICY_MISMATCH" in block["blocking_reasons"]
    barrier = next(b for b in status["barriers"] if b["id"] == "public_calendar")
    assert barrier["state"] == "account_profile_mismatch"
    # the real account/rules/ledger were only read and hashed
    assert {p: tf.sha_file(p) for p in (real_account, real_rules)} == hashes
