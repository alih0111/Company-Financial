"""TF-01A tests: token-free public market calendar collector/evaluator.

All fixtures are explicitly artificial; no test touches the live network and
no test reads or sets any token variable. Schema v2: observation quality,
completion confirmation and fill permission are separate concepts.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import urllib.error
from pathlib import Path

import pytest

from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf

NOW = dt.datetime(2026, 10, 23, 12, 0, 0, tzinfo=dt.timezone.utc)  # Tehran 15:30
PRIMARY, SECONDARY = "32097828799138957", "67130298613737946"
CANDIDATE_INS = "35158826900216508"
# Iranian trading weekdays (Sat..Wed) across 2026-09-01..2026-09-10,
# excluding Thursday 2026-09-03 and Friday 2026-09-04.
BASE_SESSIONS = ["20260901", "20260902", "20260905", "20260906",
                 "20260907", "20260908", "20260909"]


def hist_row(day, ins=PRIMARY, close=100.0):
    return {"insCode": int(ins), "dEven": int(day),
            "xNivInuClMresIbs": close, "xNivInuPbMresIbs": close - 1,
            "xNivInuPhMresIbs": close + 1}


def identity_rows():
    return [
        {"insCode": int(PRIMARY), "dEven": 0, "hEven": 195817, "lVal30": "شاخص كل"},
        {"insCode": int(SECONDARY), "dEven": 0, "hEven": 195817, "lVal30": "شاخص كل (هم وزن)"},
        {"insCode": 11111111111111111, "dEven": 0, "lVal30": "شاخص ديگر"},
    ]


def instrument_doc(flow_title="بازار بورس", cgr_title="بازار دوم (تابلوی فرعی) بورس",
                   ins_code=CANDIDATE_INS):
    return {"instrumentInfo": {"insCode": ins_code, "lVal30": "fixture-symbol",
                               "lVal18AFC": "FIX", "flow": 1, "flowTitle": flow_title,
                               "cgrValCot": "N2", "cgrValCotTitle": cgr_title}}


def make_sources(primary_dates=None, secondary_dates=None, watermark=None,
                 symbol="TEST", instrument=None, by_symbol=None):
    primary_dates = BASE_SESSIONS if primary_dates is None else primary_dates
    secondary_dates = (list(primary_dates) if secondary_dates is None
                       else secondary_dates)
    default_watermark = (primary_dates[-1] + ";" + primary_dates[-1]
                         if primary_dates else None)
    return {
        "identity": {"state": "OK", "rows": identity_rows()},
        "primary_history": {"state": "OK", "rows": [hist_row(d) for d in primary_dates],
                            "ins_code": PRIMARY},
        "secondary_history": {"state": "OK",
                              "rows": [hist_row(d, SECONDARY) for d in secondary_dates],
                              "ins_code": SECONDARY},
        "last_possible": {"state": "OK",
                          "text": (default_watermark if watermark is None else watermark)},
        "candidate_instrument": {"state": "OK", "ins_code": CANDIDATE_INS,
                                 "expected_ins_code": CANDIDATE_INS, "symbol": symbol,
                                 "doc": instrument_doc() if instrument is None else instrument},
        **({"stock_cross": {"by_symbol": by_symbol}} if by_symbol is not None else {}),
    }


def policy(window_start="20260901", cross=None):
    return tf.make_policy(market="TSE", window_start=window_start,
                          indices=tf.TSE_INDEX_PROFILES,
                          cross_check_window_start=cross or window_start)


def evaluate(sources, now_utc=NOW, window_start="20260901", cross=None, pol=None):
    return tf.evaluate_public_calendar(policy=pol or policy(window_start, cross),
                                       sources=sources, now_utc=now_utc)


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.status = status
        self._headers = {"Date": "Fri, 23 Oct 2026 12:00:00 GMT"}

    def read(self, limit=-1):
        return self._body if limit is None or limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    headers = property(lambda self: self._headers)


def recording_opener(responses, urls):
    def opener(request, timeout=35):
        urls.append(request.full_url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item), 1, 0.0
    return opener


def live_docs(primary=BASE_SESSIONS, secondary=None, watermark=None):
    return [
        json.dumps({"indexB1": identity_rows()}),
        json.dumps({"indexB2": [hist_row(d) for d in primary]}),
        json.dumps({"indexB2": [hist_row(d, SECONDARY)
                                for d in (primary if secondary is None else secondary)]}),
        (BASE_SESSIONS[-1] + ";" + BASE_SESSIONS[-1] if watermark is None else watermark),
        json.dumps(instrument_doc()),
    ]


# 1 ---------------------------------------------------------------------- #
def test_agreeing_indices_yield_corroborated_public_sorted_set():
    result = evaluate(make_sources())
    assert result["quality"] == "CORROBORATED_PUBLIC"
    dates = [entry["date"] for entry in result["observed_sessions"]]
    assert dates == sorted(set(dates)) == BASE_SESSIONS
    assert all(entry["corroborated"] and entry["within_assumed_completion"]
               for entry in result["observed_sessions"])
    # completion is never officially confirmed; agreement is only an assumption
    assert result["completion"]["state"] == "COMPLETION_UNVERIFIED"
    assert result["completion"]["watermark_observation"] == "AGREES"
    assert result["completion"]["assumed_completion"]["value"] == BASE_SESSIONS[-1]
    assert result["readiness"]["calendar_usable"] is True
    assert result["readiness"]["completion_officially_confirmed"] is False
    assert result["readiness"]["fill_capable"] is False
    assert result["completeness_certified"] is False
    advisory = {entry["date"] for entry in result["weekend_pattern_days"]}
    assert advisory == {"20260903", "20260904"}
    assert not result["no_positive_evidence_days"]
    assert result["coverage"]["corroborated_intersection"] == {"start": "20260901",
                                                               "end": "20260909"}


# 2 ---------------------------------------------------------------------- #
def test_candidate_missing_row_preserves_market_session():
    sources = make_sources(by_symbol={"TEST": ["20260901"]})  # no trade on 20260902+
    result = evaluate(sources)
    assert result["quality"] == "CORROBORATED_PUBLIC"
    dates = [entry["date"] for entry in result["observed_sessions"]]
    assert "20260902" in dates  # market session kept despite missing candidate row
    assert result["candidate"]["trade_status"] == "checked"
    assert "20260902" in result["candidate"]["no_positive_trade_sessions"]
    assert "suspension is not concluded" in result["candidate"]["no_trade_note"]


# 3 ---------------------------------------------------------------------- #
def test_missing_from_all_sources_is_no_positive_evidence_not_closure():
    gap = [d for d in BASE_SESSIONS if d != "20260908"]  # Tuesday removed everywhere
    result = evaluate(make_sources(primary_dates=gap, secondary_dates=gap))
    dates = [entry["date"] for entry in result["observed_sessions"]]
    assert "20260908" not in dates
    entry = next(x for x in result["no_positive_evidence_days"]
                 if x["date"] == "20260908")
    assert entry["classification"] == "NO_POSITIVE_EVIDENCE"
    assert "closed" not in json.dumps(entry).lower()
    assert result["quality"] == "CORROBORATED_PUBLIC"  # gap recorded, not a failure


# 4 ---------------------------------------------------------------------- #
def test_single_index_or_stock_witness_disagreement_is_conflict():
    only_primary = list(BASE_SESSIONS) + ["20260910"]
    result = evaluate(make_sources(primary_dates=only_primary,
                                   secondary_dates=BASE_SESSIONS))
    assert result["quality"] == "CONFLICT"
    assert any(c["type"] == "index_date_mismatch" and c["date"] == "20260910"
               for c in result["conflicts"])
    assert result["sessions_after_decision"]["session_count"] is None

    witness = make_sources(by_symbol={"TEST": ["20260910"]})  # Tuesday trade, no index
    result = evaluate(witness)
    assert result["quality"] == "CONFLICT"
    assert any(c["type"] == "stock_trade_date_outside_calendar" and c["date"] == "20260910"
               for c in result["conflicts"])
    assert any(p["type"] == "stock_trade_dates_outside_calendar"
               for p in result["problems"]["CONFLICT"])

    # a different index history start BEFORE the decision window is a recorded
    # non-blocking history-start warning, never a conflict
    older = evaluate(make_sources(primary_dates=["20080101"] + BASE_SESSIONS,
                                  secondary_dates=BASE_SESSIONS))
    assert older["quality"] == "CORROBORATED_PUBLIC"
    assert older["pre_window_history_start_difference"]["label"] == "history_start_difference"
    assert older["pre_window_history_start_difference"]["non_blocking"] is True
    assert older["pre_window_history_start_difference"]["later_source"] == "secondary"
    assert not older["conflicts"]


# 5 ---------------------------------------------------------------------- #
def test_wrong_market_or_non_stock_candidate_rejected():
    farabourse = evaluate(make_sources(instrument=instrument_doc(flow_title="بازار فرابورس")))
    assert farabourse["quality"] == "MARKET_SCOPE_MISMATCH"
    assert farabourse["problems"]["MARKET_SCOPE_MISMATCH"][0]["candidate_scope"] == "IFB"

    etf = evaluate(make_sources(instrument=instrument_doc(cgr_title="صندوق قابل معامله")))
    assert etf["quality"] == "MARKET_SCOPE_MISMATCH"
    assert etf["problems"]["MARKET_SCOPE_MISMATCH"][0]["category_state"] == "other_or_unknown"

    unknown = evaluate(make_sources(instrument=instrument_doc(flow_title="بازار پایه فرابورس")))
    assert unknown["quality"] == "MARKET_SCOPE_UNCLASSIFIED"
    assert unknown["sessions_after_decision"]["session_count"] is None


# 6 ---------------------------------------------------------------------- #
def test_weekend_fresh_fetch_is_no_new_session():
    sources = make_sources(primary_dates=["20261019", "20261020", "20261021"],
                           secondary_dates=["20261019", "20261020", "20261021"],
                           watermark="20261021;20261021")
    result = evaluate(sources, window_start="20261022")  # decision Thursday
    assert result["quality"] == "CORROBORATED_PUBLIC"
    after = result["sessions_after_decision"]
    assert after["state"] == "NO_NEW_SESSION"
    assert after["session_count"] == 0
    assert after["first_assumed_session"] is None
    assert all(entry["date"] <= "20261021" for entry in result["observed_sessions"])


# 7 ---------------------------------------------------------------------- #
def test_watermark_gates_completion_permission():
    behind = evaluate(make_sources(watermark="20260908;20260908"),
                      window_start="20260908")  # decision day at the watermark
    assert behind["completion"]["state"] == "COMPLETION_UNVERIFIED"
    beyond = behind["sessions_after_decision"]
    assert beyond["state"] == "SESSIONS_ALL_BEYOND_ASSUMED_COMPLETION"
    assert beyond["session_count"] == 0  # observed 20260909 is beyond the assumption
    assert beyond["first_assumed_session"] is None

    garbage = evaluate(make_sources(watermark="not-a-date"))
    assert garbage["completion"]["state"] == "COMPLETION_UNVERIFIED"
    assert garbage["completion"]["watermark_observation"] == "UNPARSEABLE"
    assert garbage["completion"]["assumed_completion"] is None
    assert garbage["sessions_after_decision"]["state"] == "SESSIONS_OBSERVED_COMPLETION_UNVERIFIED"
    assert garbage["sessions_after_decision"]["session_count"] is None  # unknown, not 0
    assert garbage["problems"]["COMPLETION_UNVERIFIED"]


# 8 ---------------------------------------------------------------------- #
def test_fetch_failures_are_precise_and_never_faked(tmp_path, monkeypatch):
    monkeypatch.delenv("TSETMC_READONLY_BEARER_TOKEN", raising=False)
    cases = [
        (urllib.error.URLError("boom"), "NETWORK_ERROR"),
        (b"", "EMPTY_BODY"),
        (b"<!doctype html><html>blocked</html>", "HTML_BODY"),
        (b"{not json", "INVALID_JSON"),
        (json.dumps({"unexpected": []}), "MISSING_FIELD"),
    ]
    for body, code in cases:
        urls, sources = [], None
        opener = recording_opener(
            [body if isinstance(body, Exception) else body] * 5, urls)
        collected = tf.collect_live(policy=policy(), candidate={
            "symbol": "TEST", "ins_code": CANDIDATE_INS},
            out_dir=tmp_path / ("case-" + code), now_utc=NOW, opener=opener)
        sources = collected["sources"]
        failed = {key: entry.get("error_code") for key, entry in sources.items()
                  if entry["state"] == "FETCH_FAILED"}
        assert set(failed.values()) == {code}, failed
        result = evaluate({k: v for k, v in sources.items() if k != "stock_cross"})
        assert result["quality"] == "FETCH_FAILED"
        assert result["sessions_after_decision"]["session_count"] is None
        assert result["observed_sessions"] == []

    # saved raw that no longer matches its hash is refused (no cache false-pass)
    raw = tmp_path / "tampered.bin.gz"
    raw.write_bytes(gzip.compress(b"original-body"))
    with pytest.raises(tf.SourceFetchError) as exc:
        tf.load_raw_verified(raw, "0" * 64)
    assert exc.value.code == "RAW_HASH_MISMATCH"


# 9 ---------------------------------------------------------------------- #
def test_invalid_rows_rejected_and_identical_duplicates_deduped():
    rows = [hist_row("20260901"), hist_row("20260902"),
            hist_row("20261024"),                       # future vs NOW (Tehran 20261023)
            hist_row("20260905", ins=99999999999999999),  # foreign insCode
            hist_row("20260906", close=111.0), hist_row("20260906", close=222.0)]
    sources = make_sources()
    sources["primary_history"]["rows"] = rows
    result = evaluate(sources)
    assert result["quality"] == "INPUT_ROWS_REJECTED"
    reasons = {r["reason"] for r in result["problems"]["INPUT_ROWS_REJECTED"][0]["rejects"]}
    assert reasons == {"future_date", "foreign_ins_code", "conflicting_duplicate"}
    assert result["sessions_after_decision"]["session_count"] is None

    # source metadata must never override the policy identity
    identical = make_sources(primary_dates=["20260901", "20260902"],
                             secondary_dates=["20260901", "20260902"])
    identical["primary_history"]["rows"] = [hist_row("20260901"), hist_row("20260901"),
                                            hist_row("20260902")]
    identical["primary_history"]["ins_code"] = "99999999999999999"  # bogus metadata
    ok = evaluate(identical, window_start="20260901")
    assert ok["quality"] == "CORROBORATED_PUBLIC"  # rows still checked against policy id
    assert ok["parse"]["primary"]["identical_duplicate_rows"] == 1
    assert [e["date"] for e in ok["observed_sessions"]] == ["20260901", "20260902"]

    wrong_name = make_sources()
    wrong_name["identity"]["rows"].append({"insCode": int(PRIMARY), "lVal30": "شاخص ديگر"})
    assert evaluate(wrong_name)["quality"] == "IDENTITY_CHECK_FAILED"
    reasons = {f["reason"] for f in evaluate(wrong_name)["problems"]["IDENTITY_CHECK_FAILED"]}
    assert "duplicate_identity_conflicting" in reasons


# 10 --------------------------------------------------------------------- #
def test_row_order_rerun_and_midnight_boundary_are_stable():
    shuffled = make_sources()
    shuffled["primary_history"]["rows"] = list(reversed(shuffled["primary_history"]["rows"]))
    first, second = evaluate(make_sources()), evaluate(shuffled)
    assert ([e["date"] for e in first["observed_sessions"]]
            == [e["date"] for e in second["observed_sessions"]])
    assert first["quality"] == second["quality"] == "CORROBORATED_PUBLIC"
    assert first == second  # pure function: identical inputs, identical output

    before_midnight = dt.datetime(2026, 10, 22, 20, 29, 0, tzinfo=dt.timezone.utc)
    sources = make_sources(primary_dates=["20261021", "20261022"],
                           secondary_dates=["20261021", "20261022"],
                           watermark="20261022;20261022")
    # Tehran 2026-10-22 23:59 -> 20261022 is today (valid) on the first clock;
    # the decision window starts 20261021 so coverage is sufficient.
    assert evaluate(sources, now_utc=before_midnight,
                    window_start="20261021")["quality"] == "CORROBORATED_PUBLIC"
    # Tehran 2026-10-21 23:59 (clock 20:29 UTC) makes the 20261022 row future:
    # the same row is rejected, proving the boundary is Tehran-local, not UTC.
    earlier = dt.datetime(2026, 10, 21, 20, 29, 0, tzinfo=dt.timezone.utc)
    rejected = evaluate(sources, now_utc=earlier, window_start="20261021")
    assert rejected["quality"] == "INPUT_ROWS_REJECTED"
    assert any(r["reason"] == "future_date" and r["dEven"] == "20261022"
               for r in rejected["problems"]["INPUT_ROWS_REJECTED"][0]["rejects"])


# 11 --------------------------------------------------------------------- #
def test_window_outside_coverage_is_insufficient_not_zero():
    short = make_sources(primary_dates=["20260905", "20260906"],
                         secondary_dates=["20260905", "20260906"],
                         watermark="20260906;20260906")
    result = evaluate(short, window_start="20260901")
    assert result["quality"] == "INSUFFICIENT_COVERAGE"
    anchor_reasons = {p["source"] for p in result["problems"]["INSUFFICIENT_COVERAGE"]
                      if p["reason"] == "source_missing_decision_anchor"}
    assert anchor_reasons == {"primary_history", "secondary_history"}
    assert result["sessions_after_decision"]["session_count"] is None  # unknown, not 0

    lagging = make_sources(watermark="20260909;20260909",
                           primary_dates=[d for d in BASE_SESSIONS if d != "20260909"],
                           secondary_dates=[d for d in BASE_SESSIONS if d != "20260909"])
    result = evaluate(lagging)
    assert result["quality"] == "INSUFFICIENT_COVERAGE"
    assert any(p["reason"] == "index_history_behind_completion_watermark"
               for p in result["problems"]["INSUFFICIENT_COVERAGE"])


# 12 --------------------------------------------------------------------- #
def test_collector_never_touches_authenticated_endpoints_or_token_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TSETMC_READONLY_BEARER_TOKEN", raising=False)
    urls: list[str] = []
    opener = recording_opener(live_docs(), urls)
    collected = tf.collect_live(policy=policy(), candidate={
        "symbol": "TEST", "ins_code": CANDIDATE_INS},
        out_dir=tmp_path / "live", now_utc=NOW, opener=opener)
    assert len(urls) == 5
    assert all("api.tsetmc.com" not in url and "NSCStart" not in url for url in urls)
    assert all(entry["state"] == "OK" for entry in collected["sources"].values())
    result = evaluate(collected["sources"])
    assert result["quality"] == "CORROBORATED_PUBLIC"
    source_text = Path(tf.__file__).read_text(encoding="utf-8")
    assert "TSETMC_READONLY_BEARER_TOKEN" not in source_text
    assert "environ" not in source_text  # no environment secrets are read at all
    for url in (tf.IDENTITY_URL, tf.LAST_POSSIBLE_URL):
        assert "api.tsetmc.com" not in url


# 13 --------------------------------------------------------------------- #
def test_offline_replay_from_saved_manifest_matches_and_detects_tampering(tmp_path):
    urls: list[str] = []
    opener = recording_opener(live_docs(), urls)
    candidate = {"symbol": "TEST", "ins_code": CANDIDATE_INS}
    collected = tf.collect_live(policy=policy(), candidate=candidate,
                                out_dir=tmp_path / "live", now_utc=NOW, opener=opener)
    live_sources = collected["sources"]
    live_result = evaluate(live_sources)
    manifest = tf.build_manifest(policy=policy(), sources=live_sources,
                                 evaluation=live_result, run_id=collected["run_id"],
                                 mode="live", now_utc=NOW, candidate=candidate,
                                 stock_cross_meta=None)
    replay_sources = tf.sources_from_records(manifest["sources"])
    # provenance (URL, timestamps, HTTP status) survives the replay untouched
    for record, key in zip(manifest["sources"], tf.SOURCE_KEYS):
        if record.get("state") == "OK":
            for field in ("url", "retrieved_at_utc", "request_started_at_utc", "http_status"):
                assert replay_sources[key].get(field) == record.get(field), field
    replay = evaluate(replay_sources)
    equality = tf.compare_evaluations(live_result, replay)
    assert all(equality.values()), {k: v for k, v in equality.items() if not v}

    first_raw = tf.resolve_repo_path(manifest["sources"][0]["raw_path"])
    first_raw.write_bytes(gzip.compress(b"tampered"))  # mutate saved evidence
    replay_tampered = tf.sources_from_records(manifest["sources"])
    assert replay_tampered["identity"]["state"] == "FETCH_FAILED"
    assert replay_tampered["identity"]["error_code"] == "RAW_HASH_MISMATCH"
    assert evaluate(replay_tampered)["quality"] == "FETCH_FAILED"


# ---- TF-01A block 1: identity and error states ------------------------- #
def test_candidate_payload_missing_rejected():
    result = evaluate(make_sources(instrument={"instrumentInfo": None}))
    assert result["quality"] == "CANDIDATE_IDENTITY_INVALID"
    assert result["candidate"]["state"] == "INVALID_PAYLOAD"
    assert result["sessions_after_decision"]["session_count"] is None
    assert result["readiness"]["state"] == "BLOCKED_CANDIDATE_IDENTITY_INVALID"


def test_candidate_wrong_inscode_rejected():
    result = evaluate(make_sources(instrument=instrument_doc(ins_code="999")))
    assert result["quality"] == "CANDIDATE_IDENTITY_INVALID"
    assert result["candidate"]["state"] == "WRONG_INS_CODE"
    assert result["candidate"]["ins_code"] == "999"  # reported from the response
    assert result["problems"]["CANDIDATE_IDENTITY_INVALID"][0]["expected_ins_code"] == CANDIDATE_INS
    assert result["sessions_after_decision"]["session_count"] is None


def test_single_source_failure_only_last_possible():
    sources = make_sources()
    sources["last_possible"] = {"state": "FETCH_FAILED", "error_code": "NETWORK_ERROR"}
    result = evaluate(sources)
    assert result["quality"] == "FETCH_FAILED"
    assert result["source_health"]["last_possible"] == {"state": "FAILED",
                                                        "error_code": "NETWORK_ERROR"}
    assert all(result["source_health"][key]["state"] == "OK"
               for key in ("identity", "primary_history", "secondary_history",
                           "candidate_instrument"))
    assert any(p["source"] == "last_possible" for p in result["problems"]["FETCH_FAILED"])
    assert result["sessions_after_decision"]["session_count"] is None


def test_invalid_last_possible_only_is_not_a_hidden_success():
    result = evaluate(make_sources(watermark=";;"))
    assert result["quality"] == "CORROBORATED_PUBLIC"
    assert result["completion"]["watermark_observation"] == "UNPARSEABLE"
    assert result["completion"]["assumed_completion"] is None
    assert result["problems"]["COMPLETION_UNVERIFIED"][0]["reason"] == "last_possible_unparseable"
    assert result["readiness"]["completion_officially_confirmed"] is False


def test_policy_validation_rejects_broken_contracts():
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        tf.make_policy(market="TSE", window_start="20260901",
                       indices=[tf.TSE_INDEX_PROFILES[0], tf.TSE_INDEX_PROFILES[0]])
    with pytest.raises(ValueError, match="POLICY_INVALID"):
        tf.make_policy(market="TSE", window_start="2026/09/01",
                       indices=tf.TSE_INDEX_PROFILES)
    broken = policy()
    broken["indices"] = [dict(tf.TSE_INDEX_PROFILES[0], role="primary"),
                         dict(tf.TSE_INDEX_PROFILES[1], role="primary")]
    with pytest.raises(ValueError, match="POLICY_INVALID_ROLES"):
        tf.evaluate_public_calendar(policy=broken, sources=make_sources(), now_utc=NOW)


# ---- TF-01A block 2: per-source coverage and completion ---------------- #
def test_empty_secondary_is_insufficient_and_single_source_days_not_confirmed():
    result = evaluate(make_sources(primary_dates=["20261019", "20261020", "20261021"],
                                   secondary_dates=[], watermark="20261021;20261021"),
                      window_start="20261022")
    assert result["quality"] == "INSUFFICIENT_COVERAGE"
    assert any(p["reason"] == "source_history_empty" and p["source"] == "secondary_history"
               for p in result["problems"]["INSUFFICIENT_COVERAGE"])
    single = [e for e in result["observed_sessions"] if e["in_primary"] and not e["in_secondary"]]
    assert single and all(not e["corroborated"] and not e["within_assumed_completion"]
                          for e in single)
    assert result["coverage"]["corroborated_intersection"] is None
    assert result["sessions_after_decision"]["session_count"] is None


def test_secondary_missing_decision_anchor_is_insufficient():
    # variant A: an exact-day mismatch exists (20260902 primary-only) — already CONFLICT
    result_a = evaluate(make_sources(primary_dates=["20260901", "20260902", "20260905"],
                                     secondary_dates=["20260905"],
                                     watermark="20260905;20260905"),
                        window_start="20260902")
    assert result_a["quality"] == "CONFLICT"
    # variant B: no exact-day row on the decision day — the union lower bound must
    # NOT hide the missing secondary anchor
    result_b = evaluate(make_sources(primary_dates=["20260901", "20260905"],
                                     secondary_dates=["20260905"],
                                     watermark="20260905;20260905"),
                        window_start="20260902")
    assert result_b["quality"] == "INSUFFICIENT_COVERAGE"
    assert any(p["reason"] == "source_missing_decision_anchor"
               and p["source"] == "secondary_history"
               for p in result_b["problems"]["INSUFFICIENT_COVERAGE"])
    assert result_b["sessions_after_decision"]["session_count"] is None


def test_future_watermark_rejected():
    result = evaluate(make_sources(watermark="20261231;20261231"))  # after NOW
    assert result["completion"]["watermark_observation"] == "FUTURE"
    assert result["completion"]["assumed_completion"] is None
    assert result["problems"]["COMPLETION_UNVERIFIED"][0]["reason"] == "future_watermark"
    assert result["sessions_after_decision"]["session_count"] is None


def test_cross_check_not_evaluated_when_index_quality_unusable():
    # a failed index pair must not turn every stock trade day into a false
    # "outside the calendar" witness
    sources = make_sources(by_symbol={"TEST": BASE_SESSIONS})
    sources["secondary_history"] = {"state": "FETCH_FAILED", "error_code": "NETWORK_ERROR"}
    result = evaluate(sources)
    assert result["quality"] == "FETCH_FAILED"
    assert result["stock_cross_check"]["state"] == "NOT_EVALUATED_QUALITY_UNUSABLE"
    assert not [c for c in result["conflicts"]
                if c["type"] == "stock_trade_date_outside_calendar"]
    assert result["sessions_after_decision"]["session_count"] is None


def test_replay_preserves_failed_source_error_code():
    records = [{"key": "last_possible", "state": "FETCH_FAILED",
                "error_code": "NETWORK_ERROR", "detail": "socket timeout"}]
    replayed = tf.sources_from_records(records)
    assert replayed["last_possible"]["state"] == "FETCH_FAILED"
    assert replayed["last_possible"]["error_code"] == "NETWORK_ERROR"
    assert replayed["last_possible"]["detail"] == "socket timeout"


# ---- TF-01A block 3: identity-gated cross-check and candidate report ---- #
def _snapshot_dir(tmp_path, records):
    directory = tmp_path / "snapshot"
    directory.mkdir()
    manifest = {"retrieved_at_utc": "2026-10-22T13:00:00+00:00", "records": []}
    for symbol, ins_code, rows in records:
        body = json.dumps({"closingPriceDaily": rows}).encode("utf-8")
        raw = directory / f"{symbol}.daily.json.gz"
        raw.write_bytes(gzip.compress(body))
        manifest["records"].append({
            "symbol": symbol, "ins_code": ins_code,
            "sources": {"daily": {"raw_path": str(raw),
                                  "raw_sha256": tf.sha_bytes(body)}}})
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def daily_row(ins_code, day, volume=100):
    return {"insCode": ins_code, "dEven": int(day), "qTotTran5J": volume,
            "pClosing": 1000}


def test_candidate_traded_all_sessions_reports_no_missing_trade():
    sources = make_sources(by_symbol={"TEST": BASE_SESSIONS})
    result = evaluate(sources)
    assert result["candidate"]["trade_status"] == "checked"
    assert result["candidate"]["no_positive_trade_sessions"] == []


def test_candidate_one_no_trade_day():
    traded = [d for d in BASE_SESSIONS if d != "20260905"]
    result = evaluate(make_sources(by_symbol={"TEST": traded}))
    assert result["candidate"]["no_positive_trade_sessions"] == ["20260905"]


def test_candidate_not_in_archive_is_unknown_not_no_trade():
    result = evaluate(make_sources(by_symbol={"OTHER": BASE_SESSIONS}))
    assert result["candidate"]["trade_status"] == "not_in_archive_unknown"
    assert result["candidate"]["no_positive_trade_sessions"] is None
    assert "unknown" in result["candidate"]["no_trade_note"]


def test_foreign_market_etf_and_unclassified_symbols_are_not_witnesses(tmp_path):
    directory = _snapshot_dir(tmp_path, [
        ("GOOD", "1", [daily_row("1", "20260910")]),        # TSE stock witness candidate
        ("IFB1", "2", [daily_row("2", "20260910")]),        # farabourse stock
        ("ETF1", "3", [daily_row("3", "20260910")]),        # TSE ETF
        ("NOEV", "4", [daily_row("4", "20260910")]),        # no identity evidence
    ])
    identity_map = {
        "GOOD": {"flowTitle": "بازار بورس", "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
                 "evidence_source": "fixture"},
        "IFB1": {"flowTitle": "بازار فرابورس", "cgrValCotTitle": "بازار دوم فرابورس",
                 "evidence_source": "fixture"},
        "ETF1": {"flowTitle": "بازار بورس", "cgrValCotTitle": "صندوق قابل معامله",
                 "evidence_source": "fixture"},
    }
    stock = tf.load_stock_cross(directory, window_start="20260901",
                                market_scope="TSE", identity_map=identity_map)
    assert stock["by_symbol"] == {"GOOD": ["20260910"]}  # only eligible symbol
    assert stock["counts"] == {"records": 4, "eligible": 1, "skipped_listed": 3}
    reasons = {entry["symbol"]: entry["reason"] for entry in stock["skipped"]}
    assert reasons == {"IFB1": "other_market",
                       "ETF1": "non_equity_instrument",
                       "NOEV": "unclassified_no_identity_evidence"}
    result = evaluate(make_sources(by_symbol=stock["by_symbol"]))
    # only the eligible TSE stock witnesses 20260910; IFB/ETF cannot
    assert result["quality"] == "CONFLICT"
    assert [c["symbols_sample"] for c in result["conflicts"]
            if c["type"] == "stock_trade_date_outside_calendar"] == [["GOOD"]]


def test_corrupt_daily_rows_are_counted_or_skipped(tmp_path):
    directory = _snapshot_dir(tmp_path, [
        # identity evidence present, but every row carries a foreign insCode
        ("MISMATCH", "7", [daily_row("999", "20260910")]),
        # valid symbol with one bad-volume and one foreign row alongside good rows
        ("PARTIAL", "8", [daily_row("8", "20260910"),
                          {"insCode": "8", "dEven": 20260909, "qTotTran5J": "many"},
                          daily_row("777", "20260908")]),
    ])
    identity_map = {
        name: {"flowTitle": "بازار بورس", "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
               "evidence_source": "fixture"}
        for name in ("MISMATCH", "PARTIAL")}
    stock = tf.load_stock_cross(directory, window_start="20260901",
                                market_scope="TSE", identity_map=identity_map)
    assert set(stock["by_symbol"]) == {"PARTIAL"}
    assert stock["by_symbol"]["PARTIAL"] == ["20260910"]
    assert stock["daily_inputs"]["PARTIAL"]["invalid_volume_rows"] == 1
    assert stock["daily_inputs"]["PARTIAL"]["foreign_rows"] == 1
    assert any(s["reason"] == "daily_identity_mismatch" and s["symbol"] == "MISMATCH"
               for s in stock["skipped"])


# ---- TF-01A block 4: pinned CLI replay ---------------------------------- #
def build_pinned_package(tmp_path, *, with_cross=True, parser_version=None,
                         snapshot_records=None, max_symbols=None,
                         identity_ins_code=CANDIDATE_INS,
                         primary_dates=None, secondary_dates=None,
                         watermark=None, window_start=None):
    """Artificial pinned package: manifest + raws (+ snapshot), ready to replay."""
    package = tmp_path / "package"
    raw_dir = package / "raw"
    raw_dir.mkdir(parents=True)
    urls = []
    primary_dates = primary_dates if primary_dates is not None else BASE_SESSIONS
    opener = recording_opener(live_docs(primary=primary_dates,
                                        secondary=secondary_dates,
                                        watermark=watermark), urls)
    candidate = {"symbol": "TEST", "ins_code": CANDIDATE_INS}
    effective_window = window_start or primary_dates[0]
    pol = policy(effective_window)
    from unittest.mock import patch
    with patch.object(tf, "utc_now", lambda: NOW):  # deterministic retrieval stamps
        collected = tf.collect_live(policy=pol, candidate=candidate,
                                    out_dir=package, now_utc=NOW, opener=opener)
    sources = collected["sources"]
    stock_meta = None
    if with_cross:
        records = snapshot_records if snapshot_records is not None else [
            ("TEST", CANDIDATE_INS,
             [daily_row(CANDIDATE_INS, d) for d in primary_dates])]
        directory = _snapshot_dir(tmp_path, records)
        stock_meta = tf.load_stock_cross(
            directory, window_start=effective_window, market_scope="TSE",
            identity_map={symbol: {
                "ins_code": identity_ins_code if symbol == "TEST" else ins,
                "flowTitle": "بازار بورس",
                "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
                "evidence_source": "fixture"}
                for symbol, ins, _ in records},
            max_symbols=max_symbols)
        stock_meta["identity_input"]["map"] = {
            symbol: {"ins_code": identity_ins_code if symbol == "TEST" else ins,
                     "flowTitle": "بازار بورس",
                     "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
                     "evidence_source": "fixture"}
            for symbol, ins, _ in records}
        sources["stock_cross"] = {"by_symbol": stock_meta["by_symbol"]}
    evaluation = tf.evaluate_public_calendar(policy=pol, sources=sources, now_utc=NOW)
    manifest = tf.build_manifest(policy=pol, sources=sources, evaluation=evaluation,
                                 run_id=collected["run_id"], mode="live", now_utc=NOW,
                                 candidate=candidate, stock_cross_meta=stock_meta)
    if parser_version:
        manifest["parser_version"] = parser_version
    path = package / f"manifest.{collected['run_id']}.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path, manifest, evaluation


def run_cli(argv):
    import sys
    from unittest.mock import patch
    with patch.object(sys, "argv", ["collector", *argv]):
        return tf.main()


def test_cli_replay_is_pinned_and_needs_no_current_state(tmp_path, monkeypatch, capsys):
    manifest_path, manifest, evaluation = build_pinned_package(tmp_path)
    # the current account and the default snapshot must not exist for this test
    monkeypatch.setattr(tf, "ACCOUNT", tmp_path / "nonexistent-account.json")
    monkeypatch.setattr(tf, "DEFAULT_SNAPSHOT", tmp_path / "nonexistent-snapshot")

    def sentinel(args):
        raise RuntimeError("CURRENT_STATE_UNEXPECTEDLY_REQUIRED")
    monkeypatch.setattr(tf, "resolve_candidate", sentinel)

    out_dir = tmp_path / "replayed"
    run_cli(["--from-manifest", str(manifest_path), "--output-dir", str(out_dir)])
    replay_manifest = json.loads((out_dir / "latest-manifest.json").read_text(encoding="utf-8"))
    replay = json.loads((out_dir / replay_manifest["manifest_path"].split("/")[-1])
                        .read_text(encoding="utf-8"))
    assert replay["mode"] == "replay"
    assert replay["reference_now_utc"] == manifest["reference_now_utc"]  # pinned clock
    equality = tf.compare_evaluations(evaluation, replay["evaluation"])
    assert all(equality.values()), {k: v for k, v in equality.items() if not v}
    # provenance survives: source retrieval timestamps are the pinned ones
    pinned = {s["key"]: s.get("retrieved_at_utc") for s in manifest["sources"]}
    for entry in replay["sources"]:
        assert entry.get("retrieved_at_utc") == pinned[entry["key"]]

    # tampering with a pinned daily raw is detected
    daily_path = tf.resolve_repo_path(manifest["stock_cross_check"]["daily_inputs"]["TEST"]["path"])
    daily_path.write_bytes(gzip.compress(b"tampered"))
    with pytest.raises(SystemExit, match="REPLAY_RAW_CHANGED"):
        run_cli(["--from-manifest", str(manifest_path),
                 "--output-dir", str(tmp_path / "replayed2")])

    # an incompatible parser version is rejected unless explicitly re-evaluated
    old_path, _, _ = build_pinned_package(tmp_path / "older", parser_version="old@0.9")
    with pytest.raises(SystemExit, match="REPLAY_PARSER_VERSION_MISMATCH"):
        run_cli(["--from-manifest", str(old_path),
                 "--output-dir", str(tmp_path / "reeval-blocked")])
    run_cli(["--from-manifest", str(old_path), "--allow-reevaluate",
             "--output-dir", str(tmp_path / "reeval-allowed")])
    allowed = json.loads((tmp_path / "reeval-allowed" / "latest-manifest.json")
                         .read_text(encoding="utf-8"))
    replayed = json.loads((tmp_path / "reeval-allowed" / allowed["manifest_path"].split("/")[-1])
                          .read_text(encoding="utf-8"))
    assert replayed["mode"] == "re-evaluated"  # labelled honestly, not called a replay


def test_manifest_write_is_exclusive_and_hash_matches_file(tmp_path):
    manifest = {"schema_version": 2, "run_id": "x", "payload": "fixture"}
    path, digest = tf.write_manifest_files(manifest, tmp_path, "UNIQUE01")
    assert digest == tf.sha_file(path)  # stdout hash == on-disk bytes (LF stable)
    with pytest.raises(SystemExit, match="MANIFEST_RUN_ID_EXISTS"):
        tf.write_manifest_files({"payload": "overwrite-attempt"}, tmp_path, "UNIQUE01")
    assert json.loads(path.read_text(encoding="utf-8"))["payload"] == "fixture"


# ---- TF-02 step 1: review conditions ------------------------------------- #
def _multi_records():
    return [
        ("TEST", CANDIDATE_INS, [daily_row(CANDIDATE_INS, d) for d in BASE_SESSIONS]),
        ("OTHER1", "111", [daily_row("111", d) for d in BASE_SESSIONS]),
        ("OTHER2", "222", [daily_row("222", d) for d in BASE_SESSIONS]),
    ]


def test_replay_preserves_cross_check_selection_exactly(tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "ACCOUNT", tmp_path / "nonexistent-account.json")
    monkeypatch.setattr(tf, "DEFAULT_SNAPSHOT", tmp_path / "nonexistent-snapshot")
    monkeypatch.setattr(tf, "resolve_candidate",
                        lambda args: (_ for _ in ()).throw(RuntimeError("UNEXPECTED")))

    # a) positive limit over a multi-member archive keeps exactly one member
    manifest_path, manifest, evaluation = build_pinned_package(
        tmp_path / "limited", snapshot_records=_multi_records(), max_symbols=1)
    assert manifest["stock_cross_check"]["max_symbols"] == 1
    assert set(manifest["stock_cross_check"]["by_symbol"]) == {"TEST"}
    out = tmp_path / "replay-limited"
    run_cli(["--from-manifest", str(manifest_path), "--output-dir", str(out)])
    replayed = json.loads((out / "latest-manifest.json").read_text(encoding="utf-8"))
    replay_doc = json.loads((out / replayed["manifest_path"].split("/")[-1]).read_text(encoding="utf-8"))
    assert replay_doc["mode"] == "replay"
    assert set(replay_doc["stock_cross_check"]["by_symbol"]) == {"TEST"}
    assert replay_doc["stock_cross_check"]["max_symbols"] == 1

    # b) zero limit: an empty pinned set stays empty; zero is not "unlimited"
    manifest_path, manifest, evaluation = build_pinned_package(
        tmp_path / "zero", snapshot_records=_multi_records(), max_symbols=0)
    assert manifest["stock_cross_check"]["by_symbol"] == {}
    out = tmp_path / "replay-zero"
    run_cli(["--from-manifest", str(manifest_path), "--output-dir", str(out)])
    replayed = json.loads((out / "latest-manifest.json").read_text(encoding="utf-8"))
    replay_doc = json.loads((out / replayed["manifest_path"].split("/")[-1]).read_text(encoding="utf-8"))
    assert replay_doc["stock_cross_check"]["by_symbol"] == {}
    assert replay_doc["stock_cross_check"]["counts"]["eligible"] == 0

    # c) a pinned empty set WITHOUT a recorded limit is an explicit error, not
    #    a silent expansion to the whole archive (legacy-manifest protection)
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy["stock_cross_check"].pop("max_symbols", None)
    legacy_path = tmp_path / "zero" / "manifest.legacy.json"
    legacy_path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    with pytest.raises(SystemExit, match="REPLAY_ELIGIBLE_SET_CHANGED"):
        run_cli(["--from-manifest", str(legacy_path),
                 "--output-dir", str(tmp_path / "replay-legacy")])

    # d) a pinned single-member set that silently grows on replay is refused
    manifest_path, manifest, _ = build_pinned_package(
        tmp_path / "grown", snapshot_records=_multi_records(), max_symbols=1)
    grown = json.loads(manifest_path.read_text(encoding="utf-8"))
    grown["stock_cross_check"].pop("max_symbols", None)  # replay would see all 3
    grown_path = tmp_path / "grown" / "manifest.nolimit.json"
    grown_path.write_text(json.dumps(grown, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    with pytest.raises(SystemExit, match="REPLAY_ELIGIBLE_SET_CHANGED.*added=.*OTHER1"):
        run_cli(["--from-manifest", str(grown_path),
                 "--output-dir", str(tmp_path / "replay-grown")])


def test_identity_evidence_must_bind_to_the_record_ins_code(tmp_path):
    directory = _snapshot_dir(tmp_path, [("TEST", CANDIDATE_INS,
                                          [daily_row(CANDIDATE_INS, "20260910")])])
    stock = tf.load_stock_cross(
        directory, window_start="20260901", market_scope="TSE",
        identity_map={"TEST": {"ins_code": "99999999999999999",
                               "flowTitle": "بازار بورس",
                               "cgrValCotTitle": "بازار دوم (تابلوی فرعی) بورس",
                               "evidence_source": "fixture"}})
    assert stock["by_symbol"] == {}  # the title alone proves nothing here
    assert stock["skipped"][0]["reason"] == "identity_ins_code_mismatch"


def test_replay_clock_override_is_reevaluated_not_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "ACCOUNT", tmp_path / "nonexistent-account.json")
    monkeypatch.setattr(tf, "DEFAULT_SNAPSHOT", tmp_path / "nonexistent-snapshot")
    manifest_path, manifest, evaluation = build_pinned_package(tmp_path / "clock")

    same = tmp_path / "replay-same-clock"
    run_cli(["--from-manifest", str(manifest_path),
             "--reference-now-utc", manifest["reference_now_utc"],
             "--output-dir", str(same)])
    pinned = json.loads((same / "latest-manifest.json").read_text(encoding="utf-8"))
    same_doc = json.loads((same / pinned["manifest_path"].split("/")[-1]).read_text(encoding="utf-8"))
    assert same_doc["mode"] == "replay"  # identical pinned clock stays a replay

    changed = tmp_path / "replay-new-clock"
    run_cli(["--from-manifest", str(manifest_path),
             "--reference-now-utc", "2026-10-24T12:00:00+00:00",
             "--output-dir", str(changed)])
    ref = json.loads((changed / "latest-manifest.json").read_text(encoding="utf-8"))
    changed_doc = json.loads((changed / ref["manifest_path"].split("/")[-1]).read_text(encoding="utf-8"))
    assert changed_doc["mode"] == "re-evaluated"
    assert changed_doc["reference_now_utc"] == "2026-10-24T12:00:00+00:00"
    assert changed_doc["offline_replay"]["reference_clock_changed"] is True
    assert changed_doc["offline_replay"]["reevaluation_reasons"] == ["reference_clock_changed"]
    # retrieval timestamps stay the pinned ones in both modes
    pinned_times = {s["key"]: s.get("retrieved_at_utc") for s in manifest["sources"]}
    for entry in changed_doc["sources"]:
        assert entry.get("retrieved_at_utc") == pinned_times[entry["key"]]


def test_pre_window_differences_split_start_vs_overlapping_range():
    # both indices start together; secondary misses 20260908 while the window
    # starts 20260910 -> an internal overlapping-range difference, not a
    # "later index start", and never an in-window conflict
    primary = BASE_SESSIONS
    secondary = [d for d in BASE_SESSIONS if d != "20260908"]
    result = evaluate(make_sources(primary_dates=primary,
                                   secondary_dates=secondary,
                                   watermark="20260909;20260909"),
                      window_start="20260910")
    assert result["quality"] == "CORROBORATED_PUBLIC"
    assert result["pre_window_history_start_difference"] is None
    overlap = result["pre_window_overlapping_range_difference"]
    assert overlap["label"] == "overlapping_range_date_difference"
    assert overlap["count"] == 1 and overlap["first"] == "20260908"
    assert overlap["non_blocking"] is True
    assert not result["conflicts"]
    # a genuinely earlier start is still labelled as the history-start difference
    older = evaluate(make_sources(primary_dates=["20080101"] + BASE_SESSIONS,
                                  secondary_dates=BASE_SESSIONS))
    assert older["pre_window_history_start_difference"]["label"] == "history_start_difference"
    assert older["pre_window_overlapping_range_difference"] is None
