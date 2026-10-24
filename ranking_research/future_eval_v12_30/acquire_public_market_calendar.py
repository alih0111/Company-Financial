"""TF-01/TF-01A: token-free public market calendar collector and evaluator.

Collects the two proven Tehran-exchange (TSE) index histories, their identity
list, LastPossibleDeven and the candidate instrument info from public
read-only TSETMC endpoints, then derives an observed, corroborated session
set as a pure function of the parsed inputs. No authenticated endpoint
(MarketInfo/NSCStart) is called, referenced or emulated; no token is read;
importing this module performs no network access and no writes.

TF-01A contract (schema v2): observation quality, completion confirmation and
fill permission are three separate concepts. String equality of the two
undocumented LastPossibleDeven components is only an observation and feeds an
explicitly named ``assumed_completion`` assumption — never an official
confirmation. Archive cross-check witnesses require per-symbol traceable
identity evidence; unproven symbols are skipped, not guessed. Offline replay
runs exclusively from the pinned manifest: no current account, no default
snapshot, and manifest files are created exclusively (never overwritten).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

try:
    from ranking_research.future_eval_v12_30.http_retry import open_readonly
except ImportError:  # direct-file execution from this directory
    from http_retry import open_readonly

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ranking_research/output/public_market_calendar_tf01"
ACCOUNT = ROOT / "client/public/research/v12-36/paper-portfolio.json"
DEFAULT_SNAPSHOT = ROOT / "ranking_research/output/return_v12_35/official_tsetmc_20261022"

DATASET_ID = "tsetmc_public_index_calendar_v1"
# 1.2.0 (TF-02 step 1): replay preserves the pinned cross-check selection set
# and max_symbols exactly (zero is not "unlimited"); a changed reference clock
# in replay is labelled re-evaluated, never "replay"; pre-window differences
# are split into history-start vs overlapping-range disagreements.
PARSER_VERSION = "tsetmc_public_index_calendar_v1@1.2.0"
POLICY_VERSION = "public-calendar-policy@1.1"
TEHRAN = dt.timezone(dt.timedelta(hours=3, minutes=30), "Asia/Tehran")

IDENTITY_URL = "https://cdn.tsetmc.com/api/Index/GetIndexB1LastAll/All/1"
HISTORY_URL_TEMPLATE = "https://cdn.tsetmc.com/api/Index/GetIndexB2History/{ins_code}"
LAST_POSSIBLE_URL = "https://service.tsetmc.com/tsev2/data/TseClient2.aspx?t=LastPossibleDeven"
INSTRUMENT_URL_TEMPLATE = "https://cdn.tsetmc.com/api/Instrument/GetInstrumentInfo/{ins_code}"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
}
SOURCE_KEYS = ("identity", "primary_history", "secondary_history",
               "last_possible", "candidate_instrument")
LIST_FIELD = {"identity": "indexB1", "primary_history": "indexB2",
              "secondary_history": "indexB2"}

# Registered acceptance policy inputs (documented, never outcome-driven):
# flowTitle values are recorded verbatim from public GetInstrumentInfo responses.
FLOW_TITLE_SCOPE = {"بازار بورس": "TSE", "بازار فرابورس": "IFB"}
# Common-stock board titles from the same responses; ETFs, bonds and other
# paper are not covered by an equity market calendar.
COMMON_STOCK_BOARD_PREFIXES = ("بازار اول", "بازار دوم")

TSE_INDEX_PROFILES = [
    {"role": "primary", "ins_code": "32097828799138957",
     "expected_name": "شاخص كل",
     "proven_in": "token-free-plan evidence live-probe.json (شاخص كل identity match)"},
    {"role": "secondary", "ins_code": "67130298613737946",
     "expected_name": "شاخص كل (هم وزن)",
     "proven_in": "token-free-plan evidence live-probe.json (شاخص كل (هم وزن))"},
]

# Quality describes the index-date evidence only. Source failures, candidate
# identity, scope and coverage defects block it; completion uncertainty does
# NOT (it is a separate concept reported under readiness/completion).
QUALITY_PRIORITY = [
    "INPUT_ROWS_REJECTED", "FETCH_FAILED", "IDENTITY_CHECK_FAILED",
    "CANDIDATE_IDENTITY_INVALID", "MARKET_SCOPE_UNCLASSIFIED",
    "MARKET_SCOPE_MISMATCH", "CONFLICT", "INSUFFICIENT_COVERAGE",
    "NO_POSITIVE_EVIDENCE", "CORROBORATED_PUBLIC",
]

MAX_GAP_DAYS_LISTED = 60
MAX_CONFLICT_SYMBOLS_LISTED = 5
MAX_SKIPPED_LISTED = 400


class SourceFetchError(RuntimeError):
    """A public source failed; its key/code are recorded, nothing is faked."""

    def __init__(self, key: str, code: str, detail: str = ""):
        super().__init__(f"{key}:{code}")
        self.key, self.code, self.detail = key, code, detail[:300]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repo_relative(path: Path) -> str:
    """Prefer a repo-relative POSIX path; absolute when outside the repo."""
    try:
        return str(Path(path).relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(Path(path)).replace("\\", "/")


def resolve_repo_path(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else ROOT / path


# --------------------------------------------------------------------------- #
# Pure helpers: no I/O, no clocks; every function here is fixture-testable.
# --------------------------------------------------------------------------- #

def normalize_name(text: object) -> str:
    """Normalize Arabic/Persian characters and spacing for identity matching."""
    value = str(text or "")
    for src, dst in (("ي", "ی"), ("ك", "ک"), ("\u200c", " "), ("ة", "ه")):
        value = value.replace(src, dst)
    return " ".join(value.split()).strip()


def tehran_local_date(now_utc: dt.datetime) -> str:
    return now_utc.astimezone(TEHRAN).strftime("%Y%m%d")


def parse_deven(value: object) -> str | None:
    """Return YYYYMMDD if value is a real calendar date; else None."""
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        dt.datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text


def to_iso(compact: str) -> str:
    return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"


def validate_policy(policy: dict) -> None:
    """Policy is the pre-registered contract; invalid policy refuses evaluation."""
    indices = policy.get("indices")
    if not isinstance(indices, list) or len(indices) != 2:
        raise ValueError("POLICY_INVALID_INDICES: exactly two indices required")
    roles = sorted(str(index.get("role")) for index in indices)
    if roles != ["primary", "secondary"]:
        raise ValueError("POLICY_INVALID_ROLES: roles must be primary+secondary")
    codes = [str(index.get("ins_code", "")) for index in indices]
    if len(set(codes)) != 2 or any(not code.isdigit() for code in codes):
        raise ValueError("POLICY_INVALID_INS_CODES: distinct numeric ins codes required")
    if any(not str(index.get("expected_name", "")).strip() for index in indices):
        raise ValueError("POLICY_INVALID_EXPECTED_NAMES")
    for field in ("window_start", "cross_check_window_start"):
        if parse_deven(policy.get(field)) is None:
            raise ValueError(f"POLICY_INVALID_{field.upper()}")


def extract_index_dates(rows: list, *, expected_ins_code: str,
                        now_utc: dt.datetime) -> dict:
    """Validate index-history rows and derive their unique dates.

    The expected identity always comes from the registered policy, never from
    source metadata. Fully identical duplicate rows are deduplicated and
    counted; a conflicting duplicate (same date, different values), a foreign
    insCode row, an invalid calendar date or a date after the Tehran-local
    reference day is a hard reject.
    """
    local_today = tehran_local_date(now_utc)
    dates: dict[str, list] = {}
    identical_duplicates = 0
    rejects: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            rejects.append({"reason": "row_not_object", "row": str(row)[:80]})
            continue
        if str(row.get("insCode", "")).strip() != str(expected_ins_code):
            rejects.append({"reason": "foreign_ins_code",
                            "insCode": str(row.get("insCode"))[:32]})
            continue
        day = parse_deven(row.get("dEven"))
        if day is None:
            rejects.append({"reason": "invalid_date",
                            "dEven": str(row.get("dEven"))[:32]})
            continue
        if day > local_today:
            rejects.append({"reason": "future_date", "dEven": day})
            continue
        prior = dates.get(day)
        if prior is None:
            dates[day] = [row]
        elif prior[0] == row:
            identical_duplicates += 1
        else:
            rejects.append({"reason": "conflicting_duplicate", "dEven": day})
    return {"dates": sorted(dates), "identical_duplicate_rows": identical_duplicates,
            "rejects": rejects}


def parse_last_possible(text: object) -> dict:
    """Parse the LastPossibleDeven text into a watermark observation.

    The individual meaning of the semicolon components is not officially
    documented; only their agreement is observed here, and the derived value
    is exposed as an explicitly named assumption, never a confirmation.
    """
    raw = str(text or "").strip()
    sample = raw[:64]
    base = {"sample": sample, "semantics_officially_documented": False}
    if not raw:
        return {"state": "EMPTY", "watermark": None, "components": [], **base}
    parts = [p.strip() for p in raw.split(";")]
    days = [parse_deven(p) for p in parts]
    if len(parts) < 2 or days[0] is None or days[1] is None:
        return {"state": "UNPARSEABLE", "watermark": None, "components": parts[:4], **base}
    if days[0] != days[1]:
        return {"state": "DISAGREE", "watermark": None, "components": parts[:4], **base}
    return {"state": "AGREES", "watermark": days[0], "components": parts[:4], **base}


def classify_candidate(instrument_doc: dict, *, expected_ins_code: str) -> dict:
    """Classify the candidate from GetInstrumentInfo evidence, strictly.

    The response payload must be a valid instrumentInfo object whose insCode
    equals the pinned expected identity; the reported ins_code always comes
    from the response itself, never from the argument.
    """
    info = (instrument_doc or {}).get("instrumentInfo") if isinstance(instrument_doc, dict) else None
    if not isinstance(info, dict):
        return {"state": "INVALID_PAYLOAD", "ins_code": None, "scope": None,
                "category_state": "unknown",
                "detail": "instrumentInfo object missing or not an object"}
    response_code = str(info.get("insCode", "")).strip()
    expected = str(expected_ins_code or "").strip()
    if response_code != expected:
        return {"state": "WRONG_INS_CODE", "ins_code": response_code or None,
                "expected_ins_code": expected, "scope": None,
                "category_state": "unknown",
                "detail": "response insCode does not match the pinned candidate identity"}
    flow_title = normalize_name(info.get("flowTitle"))
    category_title = normalize_name(info.get("cgrValCotTitle"))
    category_state = ("common_stock_board"
                      if category_title.startswith(COMMON_STOCK_BOARD_PREFIXES)
                      else "other_or_unknown")
    return {"state": "OK", "ins_code": response_code,
            "lVal30": info.get("lVal30"), "lVal18AFC": info.get("lVal18AFC"),
            "flow": info.get("flow"), "flowTitle": info.get("flowTitle"),
            "cgrValCot": info.get("cgrValCot"), "cgrValCotTitle": info.get("cgrValCotTitle"),
            "scope": FLOW_TITLE_SCOPE.get(flow_title), "category_state": category_state,
            "flow_title_map": dict(FLOW_TITLE_SCOPE),
            "common_stock_board_prefixes": list(COMMON_STOCK_BOARD_PREFIXES)}


def check_identities(identity_rows: list, profiles: list) -> dict:
    """Match both configured index identities by insCode and normalized name.

    Duplicate insCode rows are grouped: fully identical duplicates dedupe;
    conflicting duplicates (same code, different names) are an explicit
    identity failure instead of a silent last-row win.
    """
    grouped: dict[str, list] = {}
    for row in identity_rows:
        if isinstance(row, dict):
            grouped.setdefault(str(row.get("insCode", "")).strip(), []).append(row)
    matches, failures = [], []
    for profile in profiles:
        rows = grouped.get(str(profile["ins_code"]), [])
        if not rows:
            failures.append({"ins_code": profile["ins_code"], "reason": "not_listed"})
            continue
        names = {normalize_name(r.get("lVal30")) for r in rows}
        if len(names) > 1:
            failures.append({"ins_code": profile["ins_code"],
                             "reason": "duplicate_identity_conflicting",
                             "observed_names": sorted(names)})
            continue
        actual = names.pop()
        expected = normalize_name(profile["expected_name"])
        if actual != expected:
            failures.append({"ins_code": profile["ins_code"], "reason": "name_mismatch",
                             "expected": expected, "actual": actual})
            continue
        matches.append({"role": profile["role"], "ins_code": profile["ins_code"],
                        "lVal30": rows[0].get("lVal30"),
                        "note": ("identity endpoint dEven/hEven are ignored for "
                                 "session dating")})
    return {"matches": matches, "failures": failures}


def classify_archive_symbol(record: dict, identity_map: dict | None,
                            *, market_scope: str) -> dict:
    """Classify one archive record using traceable identity evidence only.

    Without identity evidence the symbol is ``unclassified`` — it is never
    counted as an eligible same-market witness on the file name's say-so.
    """
    symbol = str(record.get("symbol", ""))
    evidence = (identity_map or {}).get(symbol)
    if not isinstance(evidence, dict) or not evidence.get("flowTitle"):
        return {"symbol": symbol, "market": None, "type_state": "unknown",
                "classification": "unclassified_no_identity_evidence"}
    evidence_ins_code = str(evidence.get("ins_code", "") or "")
    record_ins_code = str(record.get("ins_code", "") or "")
    if evidence_ins_code and record_ins_code and evidence_ins_code != record_ins_code:
        return {"symbol": symbol, "market": None, "type_state": "unknown",
                "classification": "identity_ins_code_mismatch",
                "detail": ("the identity evidence is bound to a different insCode "
                           "than this archive record; a market title alone is not "
                           "traceable identity for this symbol")}
    flow_title = normalize_name(evidence.get("flowTitle"))
    category_title = normalize_name(evidence.get("cgrValCotTitle"))
    market = FLOW_TITLE_SCOPE.get(flow_title)
    type_state = ("common_stock_board"
                  if category_title.startswith(COMMON_STOCK_BOARD_PREFIXES)
                  else "other_or_unknown")
    if market is None:
        classification = "unclassified_unknown_market_title"
    elif market != market_scope:
        classification = "other_market"
    elif type_state != "common_stock_board":
        classification = "non_equity_instrument"
    else:
        classification = "eligible_common_stock"
    return {"symbol": symbol, "market": market, "type_state": type_state,
            "classification": classification,
            "evidence_source": evidence.get("evidence_source")}


def cross_check_stocks(session_dates: set, by_symbol: dict, *,
                      window_start: str) -> dict:
    """Compare eligible positive-volume trade dates against the session set.

    Any positive-trade date from window_start onward that the corroborated
    session set does not list is a conflict witness — including dates beyond
    the observed coverage, which are the strongest witnesses.
    """
    witnesses: dict[str, list] = {}
    positive_dates: set = set()
    for symbol, dates in by_symbol.items():
        for day in dates:
            if day >= window_start:
                positive_dates.add(day)
                if day not in session_dates:
                    witnesses.setdefault(day, []).append(symbol)
    outside = [{"date": day, "iso": to_iso(day),
                "symbols_count": len(symbols),
                "symbols_sample": sorted(symbols)[:MAX_CONFLICT_SYMBOLS_LISTED]}
               for day, symbols in sorted(witnesses.items())]
    return {"eligible_symbols_checked": len(by_symbol),
            "by_symbol": dict(by_symbol),
            "positive_trade_dates": sorted(positive_dates),
            "trade_dates_outside_calendar": outside}


def _weekday(compact: str) -> int:
    return dt.datetime.strptime(compact, "%Y%m%d").weekday()  # Mon=0..Sun=6


def _history_problems(role: str, dates: list, window_start: str) -> list[dict]:
    """Per-source coverage: empty histories and missing decision anchors."""
    found = []
    if not dates:
        found.append({"source": f"{role}_history", "reason": "source_history_empty"})
        return found
    if dates[0] > window_start:
        found.append({"source": f"{role}_history",
                      "reason": "source_missing_decision_anchor",
                      "source_first_date": dates[0],
                      "anchor_required_on_or_before": window_start,
                      "detail": ("this index has no row on/before the decision day, "
                                 "so it cannot corroborate continuity across the "
                                 "decision point")})
    return found


def evaluate_public_calendar(*, policy: dict, sources: dict,
                             now_utc: dt.datetime) -> dict:
    """Pure evaluation of the public calendar evidence. Performs no I/O."""
    validate_policy(policy)
    window_start = str(policy["window_start"])
    cross_window = str(policy.get("cross_check_window_start") or window_start)
    problems: dict[str, list] = {code: [] for code in QUALITY_PRIORITY}
    problems["COMPLETION_UNVERIFIED"] = []  # informational; never flips quality
    source_health: dict[str, dict] = {}
    index_dates: dict[str, list] = {}
    parse_summary: dict[str, dict] = {}
    profile_by_role = {profile["role"]: profile for profile in policy["indices"]}

    for role in ("primary", "secondary"):
        source = sources.get(f"{role}_history") or {}
        if source.get("state") != "OK":
            problems["FETCH_FAILED"].append(
                {"source": f"{role}_history", "error": source.get("error_code", "missing")})
            source_health[f"{role}_history"] = {"state": "FAILED",
                                                "error_code": source.get("error_code", "missing")}
            continue
        extracted = extract_index_dates(
            source.get("rows", []),
            expected_ins_code=profile_by_role[role]["ins_code"],  # policy wins
            now_utc=now_utc)
        parse_summary[role] = extracted
        if extracted["rejects"]:
            problems["INPUT_ROWS_REJECTED"].append(
                {"source": f"{role}_history", "rejects": extracted["rejects"]})
        index_dates[role] = extracted["dates"]
        source_health[f"{role}_history"] = {"state": "OK"}

    identity = sources.get("identity") or {}
    identity_result = None
    if identity.get("state") != "OK":
        problems["FETCH_FAILED"].append({"source": "identity",
                                         "error": identity.get("error_code", "missing")})
        source_health["identity"] = {"state": "FAILED",
                                     "error_code": identity.get("error_code", "missing")}
    else:
        identity_result = check_identities(identity.get("rows", []), policy["indices"])
        if identity_result["failures"]:
            problems["IDENTITY_CHECK_FAILED"] = identity_result["failures"]
        source_health["identity"] = {"state": "OK"}

    lp = sources.get("last_possible") or {}
    watermark = {"state": "SOURCE_FAILED", "watermark": None, "components": [],
                 "sample": None, "semantics_officially_documented": False}
    if lp.get("state") != "OK":
        problems["FETCH_FAILED"].append({"source": "last_possible",
                                         "error": lp.get("error_code", "missing")})
        source_health["last_possible"] = {"state": "FAILED",
                                          "error_code": lp.get("error_code", "missing")}
    else:
        watermark = parse_last_possible(lp.get("text"))
        source_health["last_possible"] = {"state": "OK"}
        if watermark["state"] != "AGREES":
            problems["COMPLETION_UNVERIFIED"].append(
                {"reason": f"last_possible_{watermark['state'].lower()}",
                 "sample": watermark["sample"]})

    candidate_source = sources.get("candidate_instrument") or {}
    candidate = None
    if candidate_source.get("state") != "OK":
        problems["FETCH_FAILED"].append(
            {"source": "candidate_instrument",
             "error": candidate_source.get("error_code", "missing")})
        source_health["candidate_instrument"] = {
            "state": "FAILED", "error_code": candidate_source.get("error_code", "missing")}
    else:
        candidate = classify_candidate(
            candidate_source.get("doc"),
            expected_ins_code=candidate_source.get("expected_ins_code",
                                                   candidate_source.get("ins_code", "")))
        source_health["candidate_instrument"] = {
            "state": "OK" if candidate["state"] == "OK" else "FAILED",
            "candidate_state": candidate["state"]}
        if candidate["state"] != "OK":
            problems["CANDIDATE_IDENTITY_INVALID"].append(
                {"state": candidate["state"], "detail": candidate.get("detail"),
                 "response_ins_code": candidate.get("ins_code"),
                 "expected_ins_code": candidate_source.get(
                     "expected_ins_code", candidate_source.get("ins_code"))})
        elif candidate["scope"] is None:
            problems["MARKET_SCOPE_UNCLASSIFIED"].append(
                {"flowTitle": candidate["flowTitle"],
                 "detail": "flowTitle is not in the registered market map; no coverage claim"})
        elif (candidate["scope"] != policy["market_scope"]
                or candidate["category_state"] != "common_stock_board"):
            problems["MARKET_SCOPE_MISMATCH"].append(
                {"candidate_scope": candidate["scope"],
                 "calendar_scope": policy["market_scope"],
                 "category_state": candidate["category_state"],
                 "detail": ("calendar market scope does not cover this instrument; "
                            "no coverage claim is made for it")})

    primary_dates = set(index_dates.get("primary", []))
    secondary_dates = set(index_dates.get("secondary", []))
    observed = sorted(primary_dates | secondary_dates)
    corroborated = sorted(primary_dates & secondary_dates)
    coverage_block = {
        "primary": ({"start": index_dates["primary"][0], "end": index_dates["primary"][-1]}
                    if index_dates.get("primary") else None),
        "secondary": ({"start": index_dates["secondary"][0], "end": index_dates["secondary"][-1]}
                      if index_dates.get("secondary") else None),
        "observed_union": ({"start": observed[0], "end": observed[-1]} if observed else None),
        "corroborated_intersection": ({"start": corroborated[0], "end": corroborated[-1]}
                                      if corroborated else None),
        "window_start": window_start,
        "cross_check_window_start": cross_window,
        "basis": ("per-source observation ranges; the union is observation only, "
                  "the intersection is corroboration"),
    }

    for role in ("primary", "secondary"):
        if (sources.get(f"{role}_history") or {}).get("state") == "OK":
            problems["INSUFFICIENT_COVERAGE"].extend(
                _history_problems(role, index_dates.get(role, []), window_start))

    disagreements = sorted(primary_dates ^ secondary_dates)
    in_window_diffs = [day for day in disagreements if day >= window_start]
    pre_window_diffs = [day for day in disagreements if day < window_start]
    conflicts = [{"type": "index_date_mismatch", "date": day, "iso": to_iso(day),
                  "present_in": "primary" if day in primary_dates else "secondary",
                  "absent_from": "secondary" if day in primary_dates else "primary"}
                 for day in in_window_diffs]
    if conflicts:
        problems["CONFLICT"].extend(conflicts)
    pre_window_start_difference = None
    pre_window_overlapping_difference = None
    if pre_window_diffs:
        starts = [index_dates[role][0] for role in ("primary", "secondary")
                  if index_dates.get(role)]
        overlap_start = max(starts) if len(starts) == 2 else None
        start_diffs = [d for d in pre_window_diffs
                       if overlap_start is None or d < overlap_start]
        overlap_diffs = [d for d in pre_window_diffs
                         if overlap_start is not None and d >= overlap_start]
        later = ("secondary" if (index_dates.get("secondary") and index_dates.get("primary")
                                 and index_dates["secondary"][0] > index_dates["primary"][0])
                 else "primary" if index_dates.get("primary") else "unknown")
        if start_diffs:
            pre_window_start_difference = {
                "label": "history_start_difference",
                "later_source": later,
                "count": len(start_diffs),
                "first": start_diffs[0], "last": start_diffs[-1],
                "non_blocking": True,
                "note": ("the two indices start at different dates; differences before the "
                         "overlapping range and before the operational decision window are "
                         "recorded as a non-blocking warning and are not treated as "
                         "corroboration or conflict"),
            }
        if overlap_diffs:
            pre_window_overlapping_difference = {
                "label": "overlapping_range_date_difference",
                "count": len(overlap_diffs),
                "first": overlap_diffs[0], "last": overlap_diffs[-1],
                "overlapping_range_start": overlap_start,
                "non_blocking": True,
                "note": ("both indices were already active on these pre-window dates, yet "
                         "they disagree day by day; this is an internal overlapping-range "
                         "difference, distinct from the history-start difference, recorded "
                         "as a non-blocking warning before the decision window"),
            }

    stock_cross = None
    # Witnesses are only meaningful against a usable corroborated session set;
    # with a failed/conflicting index pair every stock day would falsely read
    # as "outside the calendar".
    pre_cross_quality = next((code for code in QUALITY_PRIORITY if problems[code]),
                             "CORROBORATED_PUBLIC")
    if sources.get("stock_cross"):
        if pre_cross_quality != "CORROBORATED_PUBLIC":
            stock_cross = {"state": "NOT_EVALUATED_QUALITY_UNUSABLE",
                           "pre_cross_quality": pre_cross_quality,
                           "eligible_symbols_available": len(
                               sources["stock_cross"].get("by_symbol", {})),
                           "note": ("index evidence is not usable, so no witness "
                                    "comparison is claimed")}
        else:
            stock_cross = cross_check_stocks(set(corroborated),
                                             sources["stock_cross"]["by_symbol"],
                                             window_start=cross_window)
            for entry in stock_cross["trade_dates_outside_calendar"]:
                conflicts.append({"type": "stock_trade_date_outside_calendar",
                                  "date": entry["date"], "iso": entry["iso"],
                                  "symbols_count": entry["symbols_count"],
                                  "symbols_sample": entry["symbols_sample"]})
            if stock_cross["trade_dates_outside_calendar"]:
                problems["CONFLICT"].append(
                    {"type": "stock_trade_dates_outside_calendar",
                     "count": len(stock_cross["trade_dates_outside_calendar"])})

    if not observed:
        problems["NO_POSITIVE_EVIDENCE"].append(
            {"detail": "no index dates observed in either source"})
    else:
        assumed_value = watermark.get("watermark")
        if (watermark["state"] == "AGREES" and assumed_value
                and assumed_value > tehran_local_date(now_utc)):
            problems["COMPLETION_UNVERIFIED"].append(
                {"reason": "future_watermark", "value": assumed_value})
            watermark = {**watermark, "state": "FUTURE", "watermark": None}
        elif watermark["state"] == "AGREES" and observed[-1] < assumed_value:
            problems["INSUFFICIENT_COVERAGE"].append(
                {"reason": "index_history_behind_completion_watermark",
                 "coverage_end": observed[-1], "watermark": assumed_value})

    quality = next((code for code in QUALITY_PRIORITY if problems[code]),
                   "CORROBORATED_PUBLIC")
    usable = quality == "CORROBORATED_PUBLIC"

    assumed_completion = None
    if usable and watermark["state"] == "AGREES" and watermark.get("watermark"):
        assumed_completion = {
            "value": watermark["watermark"],
            "policy_version": POLICY_VERSION,
            "basis_observation": "components_agree",
            "assumption": ("agreement of the two undocumented LastPossibleDeven "
                           "components marks the latest completed session; this is "
                           "an operational assumption, not an official confirmation"),
            "sample": watermark["sample"],
        }
    completion = {
        "state": "COMPLETION_UNVERIFIED",
        "watermark_observation": watermark["state"],
        "components": watermark.get("components"),
        "sample": watermark.get("sample"),
        "assumed_completion": assumed_completion,
        "note": ("no public referable evidence defines the LastPossibleDeven "
                 "components' meaning; agreement is only an observation, so "
                 "official completion stays unverified in this version"),
    }

    session_entries = [{"date": day, "iso": to_iso(day),
                        "in_primary": day in primary_dates,
                        "in_secondary": day in secondary_dates,
                        "corroborated": day in primary_dates and day in secondary_dates,
                        "within_assumed_completion": bool(
                            day in primary_dates and day in secondary_dates
                            and assumed_completion
                            and day <= assumed_completion["value"])}
                       for day in observed]

    if usable:
        after = [entry for entry in session_entries
                 if entry["corroborated"] and entry["date"] > window_start]
        if not after:
            decision_sessions = {"state": "NO_NEW_SESSION", "session_count": 0,
                                 "assumed_eligible_session_count": 0,
                                 "sessions": [], "first_assumed_session": None}
        elif assumed_completion is None:
            decision_sessions = {"state": "SESSIONS_OBSERVED_COMPLETION_UNVERIFIED",
                                 "session_count": None,
                                 "assumed_eligible_session_count": None,
                                 "sessions": after, "first_assumed_session": None,
                                 "note": ("sessions are corroborated by two indices, but "
                                          "no completion assumption is available, so the "
                                          "eligible count is unknown, not zero")}
        else:
            within = [entry for entry in after if entry["within_assumed_completion"]]
            beyond = [entry for entry in after if not entry["within_assumed_completion"]]
            decision_sessions = {
                "state": ("HAS_SESSIONS_WITHIN_ASSUMED_COMPLETION" if within
                          else "SESSIONS_ALL_BEYOND_ASSUMED_COMPLETION"),
                "session_count": len(within),
                "assumed_eligible_session_count": len(within),
                "sessions": after, "first_assumed_session": within[0]["date"] if within else None,
                "sessions_beyond_assumed_completion": [e["date"] for e in beyond],
            }
    else:
        decision_sessions = {"state": "UNKNOWN_QUALITY_" + quality,
                             "session_count": None,
                             "assumed_eligible_session_count": None,
                             "sessions": None, "first_assumed_session": None}

    no_evidence_days, weekend_days = [], []
    if usable and corroborated:
        cursor = dt.datetime.strptime(max(corroborated[0], window_start), "%Y%m%d").date()
        end = dt.datetime.strptime(corroborated[-1], "%Y%m%d").date()
        sessions = set(corroborated)
        listed = 0
        while cursor <= end and listed < MAX_GAP_DAYS_LISTED:
            day = cursor.strftime("%Y%m%d")
            if day not in sessions:
                if _weekday(day) in (3, 4):  # Thursday/Friday
                    weekend_days.append({"date": day, "iso": to_iso(day),
                                         "classification": "WEEKEND_PATTERN_ADVISORY"})
                else:
                    no_evidence_days.append({"date": day, "iso": to_iso(day),
                                             "classification": "NO_POSITIVE_EVIDENCE"})
                listed += 1
            cursor += dt.timedelta(days=1)

    candidate_report = dict(candidate or {})
    trade_status = None
    no_trade_sessions = None
    if usable and stock_cross and candidate_source.get("symbol"):
        symbol = candidate_source["symbol"]
        by_symbol = stock_cross.get("by_symbol") or {}
        if symbol in by_symbol:
            trade_status = "checked"
            traded = set(by_symbol[symbol])
            no_trade_sessions = [
                entry["date"] for entry in session_entries
                if entry["corroborated"] and entry["date"] > window_start
                and (not assumed_completion or entry["within_assumed_completion"])
                and entry["date"] not in traded]
        else:
            trade_status = "not_in_archive_unknown"
            no_trade_sessions = None  # not-checked is not no-trade
    candidate_report["trade_status"] = trade_status
    candidate_report["no_positive_trade_sessions"] = no_trade_sessions
    if trade_status == "checked":
        candidate_report["no_trade_note"] = (
            "absent candidate rows never remove a market session; suspension is "
            "not concluded without symbol-specific evidence")
    elif trade_status == "not_in_archive_unknown":
        candidate_report["no_trade_note"] = (
            "candidate was not part of the eligible cross-check archive set; "
            "trade absence is unknown, not asserted")

    blocking = [code for code in QUALITY_PRIORITY if problems[code]]
    readiness = {
        "calendar_usable": usable,
        "completion_officially_confirmed": False,  # never claimed in this version
        "fill_capable": False,  # TF-01A wires no consumer and grants no fill
        "state": ("USABLE_COMPLETION_UNVERIFIED" if usable else "BLOCKED_" + quality),
        "blocking_reasons": blocking,
        "note": ("three separate concepts: observation quality (quality), completion "
                 "confirmation (completion/readiness.completion_officially_confirmed) "
                 "and fill permission (readiness.fill_capable); consumers must never "
                 "derive permission from quality alone"),
    }

    return {
        "schema_version": 2,
        "parser_version": PARSER_VERSION,
        "policy_version": POLICY_VERSION,
        "quality": quality,
        "readiness": readiness,
        "completeness_certified": False,
        "coverage": coverage_block,
        "completion": completion,
        "observed_sessions": session_entries,
        "conflicts": conflicts,
        "pre_window_history_start_difference": pre_window_start_difference,
        "pre_window_overlapping_range_difference": pre_window_overlapping_difference,
        "sessions_after_decision": decision_sessions,
        "no_positive_evidence_days": no_evidence_days,
        "weekend_pattern_days": weekend_days,
        "index_identities": identity_result,
        "candidate": candidate_report,
        "stock_cross_check": stock_cross,
        "parse": {role: {"dates": len(result["dates"]),
                         "identical_duplicate_rows": result["identical_duplicate_rows"],
                         "rejects": result["rejects"]}
                  for role, result in parse_summary.items()},
        "source_health": source_health,
        "problems": {code: problems[code]
                     for code in list(QUALITY_PRIORITY) + ["COMPLETION_UNVERIFIED"]
                     if problems[code]},
        "limitations": [
            "completeness_certified=false: both indices come from one provider and are not independent; agreement does not certify that every market session is present.",
            "LastPossibleDeven component semantics are not officially documented; component agreement feeds an explicitly named assumed_completion, never an official confirmation.",
            "Identity endpoint rows carry dEven=0; they are used for identity only, never for session dates.",
            "This dataset is not an NSCStart equivalent; no NSCEnd field is fabricated.",
            "No future sessions are predicted; Thursday/Friday patterns are advisory only and never generate sessions.",
            "Days absent from all sources are NO_POSITIVE_EVIDENCE, never definite market closure.",
            "Whether the identity endpoint enumerates non-TSE indices was not established.",
            "Archive cross-check eligibility requires per-symbol traceable identity evidence; unproven symbols are skipped, never assumed same-market.",
            "End of the usual market day clock time is not used as completion evidence.",
        ],
    }


COMPARISON_FIELDS = ("quality", "readiness", "coverage", "completion",
                     "observed_sessions", "sessions_after_decision", "candidate",
                     "stock_cross_check", "conflicts", "problems")


def compare_evaluations(expected: dict, actual: dict) -> dict[str, bool]:
    """Field-by-field semantic equality for replay verification."""
    return {field: expected.get(field) == actual.get(field)
            for field in COMPARISON_FIELDS}


# --------------------------------------------------------------------------- #
# I/O layer: bounded public fetching, immutable raws, pinned offline replay.
# --------------------------------------------------------------------------- #

def fetch_public(key: str, url: str, *, run_id: str, out_dir: Path,
                 opener=open_readonly, timeout: int = 35,
                 max_bytes: int = 32 * 1024 * 1024, sleep_before: float = 1.2) -> tuple[dict, bytes]:
    """Fetch one public source, save its raw immutably, return (record, body)."""
    if sleep_before:
        time.sleep(sleep_before)
    request = urllib.request.Request(url, headers=HEADERS)
    started = utc_now().isoformat()
    try:
        response, attempts, retry_wait = opener(request, timeout=timeout)
        with response:
            raw = response.read(max_bytes + 1)
            status, http_date = response.status, response.headers.get("Date")
    except Exception as exc:  # urllib.error.*, timeouts, socket errors
        raise SourceFetchError(key, "NETWORK_ERROR",
                               f"{type(exc).__name__}: {exc}") from None
    if len(raw) > max_bytes:
        raise SourceFetchError(key, "RESPONSE_TOO_LARGE", f"{len(raw)} bytes")
    if status != 200:
        raise SourceFetchError(key, f"HTTP_{status}")
    if not raw.strip():
        raise SourceFetchError(key, "EMPTY_BODY")
    head = raw.lstrip()[:512].lower()
    if head.startswith(b"<") or b"<!doctype html" in head or b"<html" in head:
        raise SourceFetchError(key, "HTML_BODY", "HTML body returned with HTTP 200")
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{key}.{run_id}.bin.gz"
    with raw_path.open("xb") as handle:  # unique name; never overwrite evidence
        handle.write(gzip.compress(raw, compresslevel=6))
    record = {"key": key, "url": url, "http_status": status, "http_date": http_date,
              "request_started_at_utc": started,
              "retrieved_at_utc": utc_now().isoformat(),
              "raw_path": repo_relative(raw_path),
              "raw_sha256": sha_bytes(raw), "raw_bytes": len(raw),
              "raw_content_sha256_basis": "uncompressed response bytes",
              "request_attempts": attempts, "retry_wait_seconds": retry_wait}
    return record, raw


def load_raw_verified(raw_path: Path, expected_sha256: str) -> bytes:
    """Decompress a saved raw and verify its uncompressed sha256; refuse mismatches."""
    try:
        raw = gzip.decompress(Path(raw_path).read_bytes())
    except (OSError, EOFError) as exc:
        raise SourceFetchError(Path(raw_path).name, "RAW_UNREADABLE",
                               f"{type(exc).__name__}") from None
    if sha_bytes(raw) != expected_sha256:
        raise SourceFetchError(Path(raw_path).name, "RAW_HASH_MISMATCH",
                               "saved raw no longer matches its recorded sha256")
    return raw


def parse_json_dict(raw: bytes, key: str) -> dict:
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise SourceFetchError(key, "INVALID_JSON") from None
    if not isinstance(doc, dict):
        raise SourceFetchError(key, "INVALID_JSON", "top-level JSON is not an object")
    return doc


def collect_live(*, policy: dict, candidate: dict, out_dir: Path,
                 now_utc: dt.datetime, opener=open_readonly) -> dict:
    """Fetch all public sources once, bounded; never reads any token variable."""
    run_id = now_utc.strftime("%Y%m%dT%H%M%S%fZ")
    sources: dict[str, dict] = {}
    specs = [("identity", IDENTITY_URL)]
    for profile in policy["indices"]:
        specs.append((f"{profile['role']}_history",
                      HISTORY_URL_TEMPLATE.format(ins_code=profile["ins_code"])))
    specs.append(("last_possible", LAST_POSSIBLE_URL))
    specs.append(("candidate_instrument",
                  INSTRUMENT_URL_TEMPLATE.format(ins_code=candidate["ins_code"])))
    for index, (key, url) in enumerate(specs):
        source: dict = {"key": key, "url": url}
        try:
            record, body = fetch_public(key, url, run_id=run_id, out_dir=out_dir,
                                        opener=opener,
                                        sleep_before=1.2 if index else 0.0)
            source.update(record)
            if key == "last_possible":
                source.update(state="OK", text=body.decode("utf-8", "replace"))
            else:
                doc = parse_json_dict(body, key)
                if key == "candidate_instrument":
                    source.update(state="OK", doc=doc, rows=[])
                else:
                    rows = doc.get(LIST_FIELD[key])
                    if not isinstance(rows, list):
                        raise SourceFetchError(key, "MISSING_FIELD", LIST_FIELD[key])
                    source.update(state="OK", doc=doc, rows=rows)
        except SourceFetchError as exc:
            source.update(state="FETCH_FAILED", error_code=exc.code, detail=exc.detail)
        sources[key] = source
    for profile in policy["indices"]:
        sources[f"{profile['role']}_history"]["ins_code"] = profile["ins_code"]
    sources["candidate_instrument"]["ins_code"] = candidate["ins_code"]
    sources["candidate_instrument"]["expected_ins_code"] = candidate["ins_code"]
    sources["candidate_instrument"]["symbol"] = candidate["symbol"]
    return {"run_id": run_id, "sources": sources}


PROVENANCE_FIELDS = ("url", "http_status", "http_date", "request_started_at_utc",
                     "retrieved_at_utc", "raw_path", "raw_sha256", "raw_bytes",
                     "raw_content_sha256_basis", "request_attempts",
                     "retry_wait_seconds")


def sources_from_records(records: list) -> dict:
    """Rebuild evaluation sources from saved raw records (hash-verified offline).

    Source provenance (URL, request/retrieval timestamps, HTTP status) is
    preserved verbatim: a valid raw never earns a claim of a fresh retrieval.
    """
    by_key = {entry.get("key"): entry for entry in records if isinstance(entry, dict)}
    sources: dict[str, dict] = {}
    for key in SOURCE_KEYS:
        record = by_key.get(key)
        if not record or record.get("state") != "OK" or not record.get("raw_path"):
            sources[key] = {"state": "FETCH_FAILED",
                            "error_code": (record or {}).get("error_code")
                            or "missing_or_failed_in_source_records",
                            "detail": (record or {}).get("detail")}
            continue
        source = {"key": key}
        source.update({field: record[field] for field in PROVENANCE_FIELDS
                       if field in record})
        try:
            raw = load_raw_verified(resolve_repo_path(record["raw_path"]),
                                    record["raw_sha256"])
            if key == "last_possible":
                source.update(state="OK", text=raw.decode("utf-8", "replace"))
            elif key == "candidate_instrument":
                source.update(state="OK", doc=parse_json_dict(raw, key), rows=[],
                              expected_ins_code=record.get("expected_ins_code"),
                              symbol=record.get("symbol"))
            else:
                doc = parse_json_dict(raw, key)
                rows = doc.get(LIST_FIELD[key])
                if not isinstance(rows, list):
                    raise SourceFetchError(key, "MISSING_FIELD", LIST_FIELD[key])
                source.update(state="OK", doc=doc, rows=rows)
        except SourceFetchError as exc:
            source.update(state="FETCH_FAILED", error_code=exc.code, detail=exc.detail)
        sources[key] = source
    return sources


def collect_offline(*, manifest_path: Path) -> tuple[dict, dict]:
    """Offline replay inputs exclusively from a pinned manifest and its raws."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    sources = sources_from_records(manifest.get("sources", []))
    for key in ("primary_history", "secondary_history"):
        if sources[key].get("state") == "OK":
            sources[key].setdefault("ins_code", "")
    return manifest, sources


def load_stock_cross(snapshot_dir: Path, *, window_start: str,
                     market_scope: str = "TSE", identity_map: dict | None = None,
                     max_symbols: int | None = None) -> dict:
    """Cross-check input from the local snapshot, identity-gated.

    Eligibility requires traceable identity evidence (market + common-stock
    board) per symbol; unproven symbols are skipped with a reason and never
    counted toward the checked total. Offline only: verifies each raw's hash
    and never connects to any database.
    """
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    by_symbol: dict[str, list] = {}
    per_symbol_hashes: dict[str, str] = {}
    skipped: list[dict] = []
    by_classification: dict[str, int] = {}
    daily_inputs: dict[str, str] = {}
    records = manifest.get("records", [])
    for record in records:
        symbol = str(record.get("symbol", ""))
        classification = classify_archive_symbol(record, identity_map,
                                                 market_scope=market_scope)
        by_classification[classification["classification"]] = (
            by_classification.get(classification["classification"], 0) + 1)
        if classification["classification"] != "eligible_common_stock":
            if len(skipped) < MAX_SKIPPED_LISTED:
                skipped.append({"symbol": symbol,
                                "reason": classification["classification"],
                                "market": classification["market"],
                                "type_state": classification["type_state"]})
            continue
        if max_symbols is not None and len(by_symbol) >= max_symbols:
            continue
        daily = (record.get("sources") or {}).get("daily") or {}
        raw_path, expected = daily.get("raw_path"), daily.get("raw_sha256")
        if not raw_path or not expected:
            if len(skipped) < MAX_SKIPPED_LISTED:
                skipped.append({"symbol": symbol, "reason": "no_daily_raw"})
            continue
        try:
            raw = load_raw_verified(resolve_repo_path(raw_path), expected)
            rows = parse_json_dict(raw, "daily").get("closingPriceDaily")
            if not isinstance(rows, list):
                raise SourceFetchError("daily", "MISSING_FIELD", "closingPriceDaily")
        except SourceFetchError as exc:
            if len(skipped) < MAX_SKIPPED_LISTED:
                skipped.append({"symbol": symbol, "reason": exc.code})
            continue
        ins_code = str(record.get("ins_code", ""))
        dates: set[str] = set()
        foreign_rows = invalid_rows = 0
        for row in rows:
            if not isinstance(row, dict):
                invalid_rows += 1
                continue
            if str(row.get("insCode", "")) != ins_code:
                foreign_rows += 1
                continue
            day = parse_deven(row.get("dEven"))
            try:
                volume = float(row.get("qTotTran5J"))
            except (TypeError, ValueError):
                invalid_rows += 1
                continue
            if volume < 0:
                invalid_rows += 1
                continue
            if day and volume > 0 and day >= window_start:
                dates.add(day)
        if foreign_rows and not dates and rows:
            if len(skipped) < MAX_SKIPPED_LISTED:
                skipped.append({"symbol": symbol, "reason": "daily_identity_mismatch",
                                "foreign_rows": foreign_rows})
            continue
        by_symbol[symbol] = sorted(dates)
        per_symbol_hashes[ins_code] = expected
        daily_inputs[symbol] = {"path": raw_path, "sha256": expected,
                                "foreign_rows": foreign_rows,
                                "invalid_volume_rows": invalid_rows}
    skipped_count = {"records": len(records), "eligible": len(by_symbol),
                     "skipped_listed": len(skipped)}
    return {"by_symbol": by_symbol,
            "symbols_checked": len(by_symbol),
            "max_symbols": max_symbols,
            "counts": skipped_count,
            "by_classification": by_classification,
            "skipped": skipped,
            "identity_input": {
                "map_entries": len(identity_map or {}),
                "evidence_sources": sorted({str(entry.get("evidence_source"))
                                            for entry in (identity_map or {}).values()
                                            if isinstance(entry, dict)}),
                "note": ("eligibility requires per-symbol traceable market/type "
                         "evidence; symbols without evidence are skipped, never "
                         "assumed same-market"),
            },
            "daily_inputs": daily_inputs,
            "snapshot_manifest_path": repo_relative(snapshot_dir / "manifest.json"),
            "snapshot_manifest_sha256": sha_file(snapshot_dir / "manifest.json"),
            "snapshot_dir": repo_relative(snapshot_dir),
            "snapshot_retrieved_at_utc": manifest.get("retrieved_at_utc")}


def make_policy(*, market: str, window_start: str, indices: list,
                cross_check_window_start: str | None = None) -> dict:
    policy = {
        "policy_version": POLICY_VERSION,
        "market_scope": market,
        "indices": indices,
        "window_start": window_start,
        "cross_check_window_start": cross_check_window_start or window_start,
        "identical_duplicate_policy": "identical duplicate rows are deduplicated and counted",
        "conflict_policy": ("any primary/secondary date disagreement in the decision window, "
                            "or a positive-volume eligible stock date outside both indices, "
                            "is a CONFLICT; operations depending on that window halt"),
        "watermark_policy": ("LastPossibleDeven component agreement is an observation feeding "
                             "an explicitly named assumed_completion; official completion "
                             "stays unverified"),
        "market_title_map": dict(FLOW_TITLE_SCOPE),
        "common_stock_board_prefixes": list(COMMON_STOCK_BOARD_PREFIXES),
        "weekend_policy": "Thursday/Friday absence is advisory only; sessions are never generated",
        "future_date_policy": "dates after the Tehran-local reference day are rejected",
        "coverage_policy": ("each index must have a decision-day anchor (a row on/before "
                            "window_start) and non-empty history; the union of two "
                            "histories never substitutes per-source coverage"),
    }
    validate_policy(policy)
    return policy


MANIFEST_SOURCE_FIELDS = ("key", "url", "http_status", "http_date",
                          "request_started_at_utc", "retrieved_at_utc", "raw_path",
                          "raw_sha256", "raw_bytes", "raw_content_sha256_basis",
                          "request_attempts", "retry_wait_seconds", "state",
                          "error_code", "detail", "reported_text",
                          "expected_ins_code", "symbol")


def build_manifest(*, policy: dict, sources: dict, evaluation: dict, run_id: str,
                   mode: str, now_utc: dt.datetime, candidate: dict,
                   stock_cross_meta: dict | None, extra: dict | None = None) -> dict:
    public_sources = [{k: sources[key][k] for k in MANIFEST_SOURCE_FIELDS
                       if k in sources[key]} for key in SOURCE_KEYS]
    last = sources["last_possible"]
    if last.get("state") == "OK":
        next(entry for entry in public_sources
             if entry["key"] == "last_possible")["reported_text"] = last["text"]
    manifest = {
        "schema_version": 2,
        "dataset_id": DATASET_ID,
        "provider": "public unauthenticated TSETMC cdn/service endpoints",
        "parser_version": PARSER_VERSION,
        "policy_version": POLICY_VERSION,
        "mode": mode,
        "run_id": run_id,
        "reference_now_utc": now_utc.isoformat(),
        "market_scope": policy["market_scope"],
        "window_start": policy["window_start"],
        "policy": policy,
        "nscstart_compatible": False,
        "completeness_certified": False,
        "index_identities": evaluation.get("index_identities"),
        "candidate": candidate,
        "sources": public_sources,
        "coverage_start": evaluation["coverage"]["observed_union"]["start"] if evaluation["coverage"]["observed_union"] else None,
        "coverage_end": evaluation["coverage"]["observed_union"]["end"] if evaluation["coverage"]["observed_union"] else None,
        "corroborated_coverage": evaluation["coverage"]["corroborated_intersection"],
        "completion_watermark": evaluation["completion"],
        "observed_sessions": evaluation["observed_sessions"],
        "conflicts": evaluation["conflicts"],
        "quality": evaluation["quality"],
        "readiness": evaluation["readiness"],
        "sessions_after_decision": evaluation["sessions_after_decision"],
        "stock_cross_check": stock_cross_meta,
        "evaluation": evaluation,
    }
    if extra:
        manifest.update(extra)
    return manifest


def write_manifest_files(manifest: dict, out_dir: Path, run_id: str) -> tuple[Path, str]:
    """Write the run manifest exclusively (never overwrite) with stable LF bytes.

    The recorded sha256 is computed over the final file bytes, so stdout, the
    latest pointer and the file on disk always agree.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"manifest.{run_id}.json"
    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError:
        raise SystemExit(f"MANIFEST_RUN_ID_EXISTS:{run_id}; runs never overwrite evidence") from None
    digest = sha_file(path)
    (out_dir / "latest-manifest.json").write_text(
        json.dumps({"run_id": run_id,
                    "manifest_path": repo_relative(path),
                    "manifest_sha256": digest},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, digest


def resolve_candidate(args: argparse.Namespace) -> dict:
    """Read-only candidate resolution (live mode only): account + snapshot map."""
    account = json.loads(ACCOUNT.read_text(encoding="utf-8"))
    candidate = ((account.get("ranking") or {}).get("top_candidate")
                 or (account.get("active_decision") or {}).get("top_candidate")
                 or {})
    symbol = args.candidate_symbol or candidate.get("symbol")
    if not symbol:
        raise SystemExit("NO_PINNED_CANDIDATE; pass --candidate-symbol explicitly")
    manifest = json.loads((args.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    record = next((r for r in manifest["records"] if r.get("symbol") == symbol), None)
    if record is None:
        raise SystemExit(f"CANDIDATE_NOT_IN_LOCAL_SNAPSHOT:{symbol}")
    return {"symbol": symbol, "ins_code": str(record["ins_code"]),
            "company_id": record.get("company_id") or candidate.get("company_id"),
            "account_read_only": True}


def _replay_stock_cross(pinned_meta: dict, policy: dict) -> dict:
    """Rebuild and re-verify the pinned cross-check inputs from the pinned snapshot.

    The pinned selection is preserved exactly: the recorded ``max_symbols``
    limit is replayed as recorded (zero stays zero; an absent field means the
    limit was not recorded), and the rebuilt eligible symbol set must equal the
    pinned set — no symbol may be silently dropped or added.
    """
    snapshot_dir = resolve_repo_path(pinned_meta["snapshot_dir"])
    current_manifest_sha = sha_file(snapshot_dir / "manifest.json")
    if current_manifest_sha != pinned_meta["snapshot_manifest_sha256"]:
        raise SystemExit("REPLAY_SNAPSHOT_MANIFEST_CHANGED; pinned snapshot no longer matches")
    replay_max_symbols = (pinned_meta["max_symbols"] if "max_symbols" in pinned_meta
                          else None)
    rebuilt = load_stock_cross(snapshot_dir,
                               window_start=policy["cross_check_window_start"],
                               market_scope=policy["market_scope"],
                               identity_map=(pinned_meta.get("identity_input") or {}).get("map"),
                               max_symbols=replay_max_symbols)
    pinned_hashes = {entry.get("sha256") for entry in pinned_meta.get("daily_inputs", {}).values()}
    current_hashes = {entry["sha256"] for entry in rebuilt["daily_inputs"].values()}
    changed = pinned_hashes - current_hashes
    if changed:
        raise SystemExit(f"REPLAY_RAW_CHANGED; {len(changed)} pinned daily raw(s) no longer match")
    pinned_eligible = set(pinned_meta.get("by_symbol", {}))
    rebuilt_eligible = set(rebuilt["by_symbol"])
    if rebuilt_eligible != pinned_eligible:
        missing = sorted(pinned_eligible - rebuilt_eligible)
        extra = sorted(rebuilt_eligible - pinned_eligible)
        raise SystemExit("REPLAY_ELIGIBLE_SET_CHANGED; "
                         f"pinned_count={len(pinned_eligible)}; replayed_count={len(rebuilt_eligible)}; "
                         f"missing={missing[:5]}; added={extra[:5]}")
    rebuilt["max_symbols"] = replay_max_symbols
    pinned_map = (pinned_meta.get("identity_input") or {}).get("map")
    if pinned_map:
        rebuilt["identity_input"]["map"] = pinned_map  # keep the chain replayable
    return rebuilt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-start", default=None, help="decision day YYYYMMDD (live mode)")
    parser.add_argument("--market", default="TSE",
                        help="calendar market scope; only the TSE profile is configured")
    parser.add_argument("--from-manifest", type=Path, default=None,
                        help="offline replay: evaluate a pinned manifest's saved raws "
                             "without touching the current account or default snapshot")
    parser.add_argument("--allow-reevaluate", action="store_true",
                        help="with --from-manifest: accept a parser-version mismatch and "
                             "re-evaluate with the current parser (labelled, not a replay)")
    parser.add_argument("--reference-now-utc", default=None,
                        help="injected reference clock (ISO); offline default: pinned manifest clock")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT,
                        help="local stock archive for the live cross-check")
    parser.add_argument("--no-cross-check", action="store_true",
                        help="skip the stock archive cross-check (recorded as not available)")
    parser.add_argument("--max-cross-symbols", type=int, default=None)
    parser.add_argument("--cross-check-lookback-days", type=int, default=60,
                        help="stock cross-check window starts this many days before window_start")
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--candidate-symbol", default=None)
    args = parser.parse_args()
    if args.market != "TSE":
        raise SystemExit("MARKET_PROFILE_NOT_CONFIGURED; only the TSE public profile is proven; no guessing")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    stock_cross_meta = None
    replay_pinned = None
    if args.from_manifest:
        # Pinned replay path: no resolve_candidate, no current account, no
        # default snapshot — every input comes from the pinned manifest.
        source_manifest, sources = collect_offline(manifest_path=args.from_manifest)
        if source_manifest.get("parser_version") != PARSER_VERSION and not args.allow_reevaluate:
            raise SystemExit("REPLAY_PARSER_VERSION_MISMATCH; pass --allow-reevaluate to "
                             "re-evaluate with the current parser (labelled, not a replay)")
        pinned_clock = dt.datetime.fromisoformat(source_manifest["reference_now_utc"])
        clock_changed = False
        if args.reference_now_utc:
            now_utc = dt.datetime.fromisoformat(args.reference_now_utc)
            if now_utc.tzinfo is None:
                now_utc = now_utc.replace(tzinfo=dt.timezone.utc)
            clock_changed = now_utc != pinned_clock
        else:
            now_utc = pinned_clock
        # An exact replay requires the pinned inputs AND the pinned clock; a
        # different clock (or parser) is a labelled re-evaluation, never a replay.
        mode = ("replay" if (source_manifest.get("parser_version") == PARSER_VERSION
                             and not clock_changed)
                else "re-evaluated")
        policy = dict(source_manifest["policy"])
        validate_policy(policy)
        candidate = dict(source_manifest["candidate"])
        pinned_stock = source_manifest.get("stock_cross_check")
        if pinned_stock:
            replay_pinned = _replay_stock_cross(pinned_stock, policy)
            sources["stock_cross"] = {"by_symbol": replay_pinned["by_symbol"]}
            stock_cross_meta = replay_pinned
        run_id = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    else:
        if not args.window_start:
            raise SystemExit("WINDOW_START_REQUIRED for live mode")
        now_utc = dt.datetime.now(dt.timezone.utc)
        policy = make_policy(
            market=args.market, window_start=args.window_start, indices=TSE_INDEX_PROFILES,
            cross_check_window_start=(
                dt.datetime.strptime(args.window_start, "%Y%m%d")
                - dt.timedelta(days=args.cross_check_lookback_days)).strftime("%Y%m%d"))
        candidate = resolve_candidate(args)
        collected = collect_live(policy=policy, candidate=candidate,
                                 out_dir=args.output_dir, now_utc=now_utc)
        run_id, mode, sources = collected["run_id"], "live", collected["sources"]

    evaluation = evaluate_public_calendar(policy=policy, sources=sources, now_utc=now_utc)

    if mode == "live":
        candidate_entry = sources["candidate_instrument"]
        if not args.no_cross_check:
            classification = classify_candidate(
                candidate_entry.get("doc"),
                expected_ins_code=candidate_entry.get("expected_ins_code", ""))
            identity_map = None
            if classification["state"] == "OK":
                identity_map = {candidate["symbol"]: {
                    "ins_code": classification["ins_code"],
                    "flowTitle": classification["flowTitle"],
                    "cgrValCotTitle": classification["cgrValCotTitle"],
                    "evidence_raw_sha256": candidate_entry.get("raw_sha256"),
                    "evidence_source": f"live GetInstrumentInfo raw {candidate_entry.get('raw_sha256', '')[:16]}",
                }}
            stock_cross_meta = load_stock_cross(
                args.snapshot_dir, window_start=policy["cross_check_window_start"],
                market_scope=policy["market_scope"], identity_map=identity_map,
                max_symbols=args.max_cross_symbols)
            if identity_map:
                stock_cross_meta["identity_input"]["map"] = identity_map
            sources["stock_cross"] = {"by_symbol": stock_cross_meta["by_symbol"]}
            evaluation = evaluate_public_calendar(policy=policy, sources=sources,
                                                  now_utc=now_utc)

    extra: dict = {}
    if mode == "live":
        replay_sources = sources_from_records(
            [{k: v for k, v in sources[key].items()} for key in SOURCE_KEYS])
        replay_sources["stock_cross"] = sources.get("stock_cross")
        replay = evaluate_public_calendar(policy=policy, sources=replay_sources,
                                          now_utc=now_utc)
        extra["offline_replay"] = {
            "basis": "re-loaded and hash-verified the raw files just written",
            "provenance_preserved": all(
                replay_sources[key].get("retrieved_at_utc") == sources[key].get("retrieved_at_utc")
                for key in SOURCE_KEYS if sources[key].get("state") == "OK"),
            "field_equality": compare_evaluations(evaluation, replay),
        }
    else:
        extra["offline_replay"] = {
            "source_manifest": str(args.from_manifest),
            "source_parser_version": source_manifest.get("parser_version"),
            "mode": mode,
            "reference_clock_changed": clock_changed,
            "reevaluation_reasons": ([r for r in (
                None if source_manifest.get("parser_version") == PARSER_VERSION
                else "parser_version_changed",
                "reference_clock_changed" if clock_changed else None) if r]),
            "source_reference_now_utc": source_manifest.get("reference_now_utc"),
            "pinned_stock_inputs_verified": bool(replay_pinned),
            "field_equality": compare_evaluations(
                source_manifest.get("evaluation", {}), evaluation),
        }

    manifest = build_manifest(policy=policy, sources=sources, evaluation=evaluation,
                              run_id=run_id, mode=mode, now_utc=now_utc,
                              candidate=candidate, stock_cross_meta=stock_cross_meta,
                              extra=extra)
    path, manifest_sha = write_manifest_files(manifest, args.output_dir, run_id)
    print(json.dumps({
        "manifest": repo_relative(path),
        "manifest_sha256": manifest_sha, "mode": mode, "run_id": run_id,
        "quality": evaluation["quality"],
        "readiness_state": evaluation["readiness"]["state"],
        "completion_state": evaluation["completion"]["state"],
        "completion_observation": evaluation["completion"]["watermark_observation"],
        "assumed_completion": (evaluation["completion"]["assumed_completion"] or {}).get("value"),
        "coverage": evaluation["coverage"],
        "sessions_after_decision": evaluation["sessions_after_decision"]["state"],
        "session_count": evaluation["sessions_after_decision"]["session_count"],
        "conflicts": len(evaluation["conflicts"]),
        "stock_cross_symbols": (stock_cross_meta or {}).get("symbols_checked"),
        "stock_cross_counts": (stock_cross_meta or {}).get("counts"),
        "offline_replay": extra.get("offline_replay", {}).get("field_equality"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
