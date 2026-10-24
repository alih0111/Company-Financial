"""Shared paper-calendar interface: pin evidence, recompute, answer uniformly.

One consumption boundary for every calendar consumer (fill, status refresh,
cycle, factor preparation). The adapter never fetches and never writes: it
reads a pinned manifest, re-derives the evaluation from the saved raws with
the collector's pure functions (stored quality/session fields are never
trusted), applies the versioned freshness rules at the caller-supplied clock,
and answers with market scope, observed-date quality, completion type,
post-decision sessions and a readiness verdict *for the named consumption*.

Calendar readiness is not trade permission: price, corporate action, account
and receipt gates remain the consumer's own responsibility. The current
authenticated NSCStart source passes through the same interface with its
20-session contract preserved; the public token-free source is never
converted into a fake Data/NSCEnd document, and one adapter accepting a
source never makes that source acceptable for every contract.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf
except ImportError:  # direct-file execution
    import sys
    sys.path.insert(0, str(ROOT))
    from ranking_research.future_eval_v12_30 import acquire_public_market_calendar as tf

INTERFACE_VERSION = "paper-calendar-adapter@1"
DEFAULT_PUBLIC_POLICY_PATH = ROOT / "ranking_research/paper_calendar_policy.public-paper-v1.json"
CONSUMPTION_MODES = ("live-preview", "fixture-apply", "exact-replay")

# The currently pinned policy: the authenticated NSCStart contract exactly as
# the locked 1.2.0 rules use it. Absence of a token never silently upgrades
# this profile to the public policy.
NSCSTART_POLICY = {
    "policy_id": "nscstart-pinned-v1",
    "version": "1.2.0-pinned",
    "status": "current pinned policy; identical validation to the locked execution rules 1.2.0 path",
    "provider": "nscstart",
    "conditions": {
        "required_source": "TSETMC documented API MarketInfo/NSCStart",
        "window_contract": {"sessions": 20, "completed_flag": "NSCEnd==1",
                            "window_must_cover_decision": True},
        # Exactly the checks the locked 1.2.0 path performs today: a valid UTC
        # retrieval timestamp that does not predate the decision. The numeric
        # freshness proposal belongs to the public profile only.
        "freshness": {"version": "nscstart-freshness@1",
                      "max_source_age_hours": None,
                      "future_tolerance_minutes": None,
                      "require_retrieval_after_decision": True},
    },
    "capabilities": {"order_fill_preview": True, "order_fill_apply_on_experimental_account": True,
                     "sales_pit_timing": True, "official_future_calendar": False,
                     "o00_history_extension": False},
    "display_label_fa": "تقویم رسمی بازار از NSCStart با قرارداد پنجرهٔ ۲۰ جلسه‌ای",
}

READINESS_NOTE = ("calendar readiness is not full trade permission; price, corporate "
                  "action, account and receipt gates still apply in the consumer")


class CalendarRefusal(RuntimeError):
    """The pinned calendar evidence cannot serve this consumption. Nothing is faked."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code, self.detail = code, detail[:400]


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse_utc(value, *, field: str = "timestamp") -> dt.datetime:
    text = str(value or "").strip()
    if not text:
        raise CalendarRefusal("CALENDAR_TIMESTAMP_INVALID", f"{field} is empty")
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise CalendarRefusal("CALENDAR_TIMESTAMP_INVALID",
                              f"{field}={text!r} is not an ISO timestamp") from None
    if parsed.tzinfo is None:
        raise CalendarRefusal("CALENDAR_TIMESTAMP_INVALID",
                              f"{field}={text!r} carries no UTC offset")
    return parsed.astimezone(dt.timezone.utc)


def load_policy(path: Path) -> dict:
    """Load and structurally validate a versioned calendar policy document."""
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CalendarRefusal("CALENDAR_POLICY_UNREADABLE",
                              f"{type(exc).__name__} for {path}") from None
    if not isinstance(policy, dict) or not str(policy.get("policy_id", "")).strip():
        raise CalendarRefusal("CALENDAR_POLICY_INVALID", "policy_id missing")
    for field in ("version", "status", "provider", "conditions", "capabilities",
                  "display_label_fa"):
        if field not in policy:
            raise CalendarRefusal("CALENDAR_POLICY_INVALID", f"field {field} missing")
    if policy["provider"] not in ("public-index", "nscstart"):
        raise CalendarRefusal("CALENDAR_POLICY_INVALID", f"unknown provider {policy['provider']}")
    conditions = policy["conditions"]
    if not isinstance(conditions, dict) or not isinstance(conditions.get("freshness"), dict):
        raise CalendarRefusal("CALENDAR_POLICY_INVALID", "conditions.freshness missing")
    freshness = conditions["freshness"]
    for field in ("future_tolerance_minutes", "require_retrieval_after_decision"):
        if field not in freshness:
            raise CalendarRefusal("CALENDAR_POLICY_INVALID", f"freshness.{field} missing")
    if policy["provider"] == "public-index":
        if not isinstance(conditions.get("required_quality"), str):
            raise CalendarRefusal("CALENDAR_POLICY_INVALID", "required_quality missing")
        if not isinstance(freshness.get("max_source_age_hours"), (int, float)):
            raise CalendarRefusal("CALENDAR_POLICY_INVALID",
                                  "freshness.max_source_age_hours missing for a public policy")
    if not isinstance(policy["capabilities"], dict):
        raise CalendarRefusal("CALENDAR_POLICY_INVALID", "capabilities must be an object")
    return policy


def check_freshness(records: list, *, decision_at_utc: dt.datetime,
                    now_utc: dt.datetime, rules: dict) -> dict:
    """Versioned freshness gate measured at the evaluation clock.

    These boundaries are operational assumptions, not exchange law. Because
    they are evaluated at ``now_utc``, an exact replay of an old receipt with
    its recorded execution clock validates at that time, while the same raws
    offered for today's consumption are stale.
    """
    problems: list[dict] = []
    per_source: dict[str, dict] = {}
    tolerance_minutes = rules.get("future_tolerance_minutes")
    tolerance = (dt.timedelta(minutes=float(tolerance_minutes))
                 if tolerance_minutes is not None else None)
    max_age_hours = rules.get("max_source_age_hours")
    max_age = (dt.timedelta(hours=float(max_age_hours))
               if isinstance(max_age_hours, (int, float)) else None)
    for record in records:
        key = str(record.get("key", "unknown"))
        try:
            retrieved = parse_utc(record.get("retrieved_at_utc"),
                                  field=f"{key}.retrieved_at_utc")
        except CalendarRefusal as exc:
            per_source[key] = {"state": "INVALID_TIMESTAMP", "detail": exc.detail}
            problems.append({"source": key, "code": exc.code, "detail": exc.detail})
            continue
        age = now_utc - retrieved
        entry = {"retrieved_at_utc": retrieved.isoformat(),
                 "age_seconds": age.total_seconds()}
        if tolerance is not None and retrieved - now_utc > tolerance:
            entry["state"] = "RETRIEVED_IN_FUTURE"
            problems.append({"source": key, "code": "SOURCE_RETRIEVED_IN_FUTURE",
                             "detail": f"{retrieved.isoformat()} is ahead of the evaluation clock"})
        elif rules.get("require_retrieval_after_decision") and retrieved < decision_at_utc:
            entry["state"] = "RETRIEVED_BEFORE_DECISION"
            problems.append({"source": key, "code": "SOURCE_RETRIEVED_BEFORE_DECISION",
                             "detail": f"{retrieved.isoformat()} predates the decision"})
        elif max_age is not None and age > max_age:
            entry["state"] = "STALE"
            problems.append({"source": key, "code": "SOURCE_STALE",
                             "detail": (f"age {age.total_seconds() / 3600:.3f}h exceeds "
                                        f"max_source_age_hours={max_age_hours}")})
        else:
            entry["state"] = "OK"
        per_source[key] = entry
    return {"state": "FRESH" if not problems else "BLOCKED",
            "rules": dict(rules), "sources": per_source, "problems": problems}


def _read_pinned_manifest(manifest_path: Path, expected_sha256: str | None) -> tuple[dict, str]:
    try:
        data = Path(manifest_path).read_bytes()
    except OSError as exc:
        raise CalendarRefusal("CALENDAR_MANIFEST_UNREADABLE",
                              f"{type(exc).__name__} for {manifest_path}") from None
    actual = sha_bytes(data)
    if expected_sha256 is not None and actual != expected_sha256:
        raise CalendarRefusal("CALENDAR_MANIFEST_HASH_MISMATCH",
                              f"expected {expected_sha256[:16]}…, got {actual[:16]}…; "
                              "the manifest must be pinned before consumption")
    try:
        manifest = json.loads(data)
    except ValueError:
        raise CalendarRefusal("CALENDAR_MANIFEST_INVALID_JSON", str(manifest_path)) from None
    if not isinstance(manifest, dict):
        raise CalendarRefusal("CALENDAR_MANIFEST_INVALID_JSON", "top level is not an object")
    return manifest, actual


def _validate_consumption_mode(mode: str) -> None:
    if mode not in CONSUMPTION_MODES:
        raise CalendarRefusal("CALENDAR_CONSUMPTION_MODE_INVALID", str(mode))


def nscstart_covers_order_window(sessions: list, decision_day: str) -> bool:
    """The NSCStart 20-session window contract, unchanged."""
    dates = [str(row.get("DEven", "")) for row in sessions]
    return (len(dates) == 20 and all(len(day) == 8 and day.isdigit() for day in dates)
            and len(set(dates)) == 20 and min(dates) <= decision_day)


def resolve_nscstart_calendar(*, manifest_path: Path, decision_local_date: str,
                              decision_at_utc: dt.datetime, now_utc: dt.datetime,
                              consumption_mode: str, root: Path | None = None,
                              expected_manifest_sha256: str | None = None,
                              policy: dict | None = None) -> dict:
    """Validate the authenticated NSCStart calendar and answer uniformly.

    Refusal codes intentionally match the historical guard codes of the locked
    fill path, so delegation never weakens an existing guard.
    """
    _validate_consumption_mode(consumption_mode)
    policy = policy or NSCSTART_POLICY
    manifest, manifest_sha = _read_pinned_manifest(manifest_path, expected_manifest_sha256)
    if (manifest.get("source") != policy["conditions"]["required_source"]
            or not manifest.get("raw_sha256")):
        raise CalendarRefusal("OFFICIAL_SESSION_CALENDAR_SOURCE_OR_HASH_MISSING")
    try:
        retrieved = parse_utc(manifest.get("retrieved_at_utc"), field="retrieved_at_utc")
    except CalendarRefusal:
        raise CalendarRefusal("SESSION_CALENDAR_TIMESTAMP_INVALID") from None
    base = Path(root) if root is not None else ROOT
    raw_path = Path(manifest.get("raw_path", ""))
    if not raw_path.is_absolute():
        raw_path = base / raw_path
    try:
        raw = gzip.decompress(raw_path.read_bytes())
    except (OSError, EOFError):
        raise CalendarRefusal("OFFICIAL_SESSION_CALENDAR_RAW_HASH_MISMATCH") from None
    if sha_bytes(raw) != manifest["raw_sha256"]:
        raise CalendarRefusal("OFFICIAL_SESSION_CALENDAR_RAW_HASH_MISMATCH")
    try:
        raw_doc = json.loads(raw)
    except ValueError:
        raise CalendarRefusal("OFFICIAL_SESSION_CALENDAR_MANIFEST_RAW_MISMATCH") from None
    recomputed = [{"DEven": str(x.get("DEven", "")), "HEven": x.get("HEven"),
                   "NSCEnd": str(x.get("NSCEnd", ""))}
                  for x in raw_doc.get("Data", []) if isinstance(x, dict)]
    if recomputed != manifest.get("sessions"):
        raise CalendarRefusal("OFFICIAL_SESSION_CALENDAR_MANIFEST_RAW_MISMATCH")
    decision_day = str(decision_local_date).replace("-", "")
    if not nscstart_covers_order_window(recomputed, decision_day):
        raise CalendarRefusal(
            "CALENDAR_WINDOW_DOES_NOT_COVER_DECISION_OR_FULL_20_SESSION_WINDOW")
    freshness = check_freshness(
        [{"key": "nscstart_calendar", "retrieved_at_utc": manifest.get("retrieved_at_utc")}],
        decision_at_utc=decision_at_utc, now_utc=now_utc,
        rules=policy["conditions"]["freshness"])
    completed = [row["DEven"] for row in recomputed
                 if row["DEven"] > decision_day and row["NSCEnd"] == "1"]
    if not completed:
        raise CalendarRefusal("NO_COMPLETED_OFFICIAL_SESSION_AFTER_DECISION")
    dates = [row["DEven"] for row in recomputed]
    return {
        "interface_version": INTERFACE_VERSION,
        "provider": "nscstart",
        "policy": {"id": policy["policy_id"], "version": policy["version"],
                   "sha256": None, "status": policy["status"],
                   "note": "embedded pinned policy; the 1.2.0 rules file stays the authority"},
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha,
                     "retrieved_at_utc": manifest.get("retrieved_at_utc"),
                     "raw_sha256": manifest["raw_sha256"]},
        "identities": {"provider": policy["conditions"]["required_source"],
                       "official": True},
        "market_scope": "official market session list (NSCStart)",
        "quality": "OFFICIAL_NSCSTART_WINDOW_VERIFIED",
        "quality_recomputed_from_raw": True,
        "freshness": freshness,
        "coverage": {"session_count": len(dates), "first": min(dates), "last": max(dates)},
        "completion": {"type": "official_per_source_contract",
                       "value": max(row["DEven"] for row in recomputed
                                    if row["NSCEnd"] == "1"),
                       "officially_confirmed": True,
                       "basis": "NSCEnd==1 completed-session flags in the official response"},
        "sessions_after_decision": {"state": "HAS_COMPLETED_SESSIONS",
                                    "count": len(completed),
                                    "first_session": completed[0],
                                    "sessions": completed},
        "first_usable_session": completed[0],
        "eligible_session_count": len(completed),
        "readiness": {"calendar_ready": freshness["state"] == "FRESH",
                      "for_consumption": consumption_mode,
                      "blocking_reasons": [p["code"] for p in freshness["problems"]],
                      "note": READINESS_NOTE},
        "capabilities": dict(policy["capabilities"]),
        "display_label_fa": policy["display_label_fa"],
    }


def _check_public_source_urls(manifest: dict, candidate_ins_code: str) -> None:
    """URL/key consistency: each source URL must match its registered template."""
    by_key = {entry.get("key"): entry for entry in manifest["sources"]}
    ins_by_role = {profile["role"]: str(profile["ins_code"])
                   for profile in manifest.get("policy", {}).get("indices", [])}
    expectations = {
        "identity": lambda url: url == tf.IDENTITY_URL,
        "primary_history": lambda url: url == tf.HISTORY_URL_TEMPLATE.format(
            ins_code=ins_by_role.get("primary")),
        "secondary_history": lambda url: url == tf.HISTORY_URL_TEMPLATE.format(
            ins_code=ins_by_role.get("secondary")),
        "last_possible": lambda url: url == tf.LAST_POSSIBLE_URL,
        "candidate_instrument": lambda url: url == tf.INSTRUMENT_URL_TEMPLATE.format(
            ins_code=str(candidate_ins_code)),
    }
    for key, check in expectations.items():
        url = str(by_key.get(key, {}).get("url", ""))
        if not check(url):
            raise CalendarRefusal("CALENDAR_SOURCE_URL_INCONSISTENT",
                                  f"{key} url {url!r} does not match its registered "
                                  "template/identity")


def resolve_public_calendar(*, manifest_path: Path, expected_manifest_sha256: str,
                            policy: dict, policy_sha256: str | None,
                            candidate: dict, decision_local_date: str,
                            decision_at_utc: dt.datetime, now_utc: dt.datetime,
                            consumption_mode: str) -> dict:
    """Pin, recompute and policy-check the token-free public calendar evidence."""
    _validate_consumption_mode(consumption_mode)
    if policy.get("provider") != "public-index" or policy.get("dataset_id") != tf.DATASET_ID:
        raise CalendarRefusal("CALENDAR_POLICY_PROVIDER_MISMATCH",
                              f"policy {policy.get('policy_id')} is not a public-index policy "
                              f"for dataset {tf.DATASET_ID}")
    manifest, manifest_sha = _read_pinned_manifest(manifest_path, expected_manifest_sha256)
    if manifest.get("dataset_id") != tf.DATASET_ID:
        raise CalendarRefusal("CALENDAR_PROVIDER_DATASET_MISMATCH",
                              f"dataset_id={manifest.get('dataset_id')!r}")
    if manifest.get("parser_version") != tf.PARSER_VERSION:
        raise CalendarRefusal("CALENDAR_PARSER_VERSION_MISMATCH",
                              f"manifest={manifest.get('parser_version')!r} "
                              f"adapter={tf.PARSER_VERSION!r}; rebuild or replay-pin both")
    records = manifest.get("sources")
    if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
        raise CalendarRefusal("CALENDAR_MANIFEST_SOURCES_INVALID")
    keys = [str(r.get("key")) for r in records]
    if len(set(keys)) != len(keys):
        raise CalendarRefusal("CALENDAR_MANIFEST_DUPLICATE_SOURCE_KEY", str(keys))
    if set(keys) != set(tf.SOURCE_KEYS):
        raise CalendarRefusal("CALENDAR_MANIFEST_SOURCE_KEYS_INVALID",
                              f"expected {sorted(tf.SOURCE_KEYS)}, got {sorted(set(keys))}")
    decision_day = str(decision_local_date).replace("-", "")
    if str(manifest.get("window_start", "")) != decision_day:
        raise CalendarRefusal("CALENDAR_WINDOW_MISMATCH",
                              f"manifest window_start={manifest.get('window_start')!r} "
                              f"is not the decision day {decision_day!r}")
    pinned_candidate = manifest.get("candidate") or {}
    if (str(pinned_candidate.get("ins_code", "")) != str(candidate.get("ins_code", ""))
            or str(pinned_candidate.get("symbol", "")) != str(candidate.get("symbol", ""))):
        raise CalendarRefusal(
            "CALENDAR_CANDIDATE_MISMATCH",
            f"manifest pins ins_code={pinned_candidate.get('ins_code')!r} "
            f"symbol={pinned_candidate.get('symbol')!r}; requested "
            f"ins_code={candidate.get('ins_code')!r} symbol={candidate.get('symbol')!r}")
    _check_public_source_urls(manifest, candidate.get("ins_code"))

    # Recompute from the saved raws: stored manifest quality/session fields are
    # never taken as truth by a consumer.
    sources = tf.sources_from_records(records)
    evaluation = tf.evaluate_public_calendar(policy=manifest["policy"], sources=sources,
                                             now_utc=now_utc)
    if manifest.get("quality") not in (None, evaluation["quality"]):
        raise CalendarRefusal("CALENDAR_MANIFEST_QUALITY_INCONSISTENT",
                              f"manifest stores quality={manifest.get('quality')!r} but the "
                              f"recomputed evaluation is {evaluation['quality']!r}")

    freshness = check_freshness(records, decision_at_utc=decision_at_utc, now_utc=now_utc,
                                rules=policy["conditions"]["freshness"])

    blocking: list[str] = []
    required_quality = policy["conditions"]["required_quality"]
    if evaluation["quality"] != required_quality:
        blocking.append(f"CALENDAR_QUALITY_{evaluation['quality']}")
    blocking.extend(f"FRESHNESS_{problem['code']}:{problem['source']}"
                    for problem in freshness["problems"])

    assumed = evaluation["completion"]["assumed_completion"]
    completion: dict = {"type": "unknown", "value": None, "officially_confirmed": False,
                        "policy_id": policy["policy_id"]}
    if assumed is not None:
        value = assumed["value"]
        primary_end = (evaluation["coverage"]["primary"] or {}).get("end")
        secondary_end = (evaluation["coverage"]["secondary"] or {}).get("end")
        completion = {
            "type": "named_operational_assumption",
            "name": "assumed_completion_via_last_possible_agreement",
            "value": value,
            "basis": ("LastPossibleDeven component agreement plus alignment of both index "
                      "history tails with that value; an explicitly named operational "
                      "assumption accepted by this policy version, never an official "
                      "confirmation"),
            "officially_confirmed": False,
            "policy_id": policy["policy_id"],
            "policy_version_of_assumption": assumed.get("policy_version"),
            "tail_primary": primary_end, "tail_secondary": secondary_end,
            "tails_aligned_with_assumption": primary_end == value == secondary_end,
        }
        if not completion["tails_aligned_with_assumption"]:
            blocking.append("COMPLETION_TAIL_MISALIGNED")
    else:
        blocking.append("COMPLETION_ASSUMPTION_UNAVAILABLE")

    sessions = evaluation["sessions_after_decision"]
    first_usable = sessions.get("first_assumed_session")
    count = sessions.get("session_count")  # None means unknown, never zero
    calendar_ready = not blocking
    answer = {
        "interface_version": INTERFACE_VERSION,
        "provider": "public-index",
        "policy": {"id": policy["policy_id"], "version": policy["version"],
                   "sha256": policy_sha256, "status": policy["status"]},
        "manifest": {"path": str(manifest_path), "sha256": manifest_sha,
                     "run_id": manifest.get("run_id"), "mode": manifest.get("mode"),
                     "reference_now_utc": manifest.get("reference_now_utc")},
        "identities": {"dataset_id": manifest.get("dataset_id"),
                       "schema_version": manifest.get("schema_version"),
                       "parser_version": manifest.get("parser_version"),
                       "collector_policy_version": manifest.get("policy_version"),
                       "official": False},
        "candidate": {"symbol": candidate.get("symbol"),
                      "ins_code": str(candidate.get("ins_code")),
                      "market_scope": (evaluation.get("candidate") or {}).get("scope"),
                      "identity_state": (evaluation.get("candidate") or {}).get("state"),
                      "category_state": (evaluation.get("candidate") or {}).get("category_state"),
                      "trade_status": (evaluation.get("candidate") or {}).get("trade_status"),
                      "no_positive_trade_sessions": (evaluation.get("candidate") or {}).get(
                          "no_positive_trade_sessions")},
        "market_scope": manifest.get("market_scope"),
        "quality": evaluation["quality"],
        "quality_recomputed_from_raw": True,
        "conflicts": evaluation["conflicts"],
        "freshness": freshness,
        "coverage": evaluation["coverage"],
        "completion": completion,
        "sessions_after_decision": {"state": sessions.get("state"),
                                    "count": count,
                                    "first_session": first_usable,
                                    "sessions": [entry["date"] for entry in (sessions.get("sessions") or [])],
                                    "count_is_unknown": count is None},
        "first_usable_session": first_usable if calendar_ready else None,
        "eligible_session_count": count if calendar_ready else None,
        "readiness": {"calendar_ready": calendar_ready,
                      "for_consumption": consumption_mode,
                      "blocking_reasons": blocking,
                      "note": READINESS_NOTE},
        "capabilities": dict(policy["capabilities"]),
        "display_label_fa": policy["display_label_fa"],
        "evaluation": evaluation,
    }
    return answer


def resolve_calendar(*, provider: str, manifest_path: Path,
                     decision_local_date: str, decision_at_utc: dt.datetime,
                     now_utc: dt.datetime, consumption_mode: str,
                     candidate: dict | None = None,
                     expected_manifest_sha256: str | None = None,
                     policy: dict | None = None,
                     policy_sha256: str | None = None,
                     root: Path | None = None) -> dict:
    """Single entry point; provider selection is always an explicit input."""
    if provider == "nscstart":
        return resolve_nscstart_calendar(
            manifest_path=manifest_path, decision_local_date=decision_local_date,
            decision_at_utc=decision_at_utc, now_utc=now_utc,
            consumption_mode=consumption_mode, root=root,
            expected_manifest_sha256=expected_manifest_sha256, policy=policy)
    if provider == "public":
        if candidate is None or expected_manifest_sha256 is None or policy is None:
            raise CalendarRefusal("CALENDAR_PUBLIC_INPUTS_INCOMPLETE",
                                  "public resolution requires candidate, pinned manifest "
                                  "sha256 and policy")
        return resolve_public_calendar(
            manifest_path=manifest_path, expected_manifest_sha256=expected_manifest_sha256,
            policy=policy, policy_sha256=policy_sha256, candidate=candidate,
            decision_local_date=decision_local_date, decision_at_utc=decision_at_utc,
            now_utc=now_utc, consumption_mode=consumption_mode)
    raise CalendarRefusal("CALENDAR_PROVIDER_UNKNOWN", str(provider))
