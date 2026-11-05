from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EvaluationError(ValueError):
    """A snapshot or ledger event violates the locked prospective contract."""


METHODS = ("P1", "P3")
REQUIRED_METHOD_FIELDS = ("score", "financial_coverage", "raw_factors", "defaulted_factors", "masked_factors", "dq")
HISTORICAL_CALENDAR_SHA256 = "879e1361624c62868a722245d612396fa7f756ca4ee0911359dc7e996b52c14b"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_aware(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationError(f"{field} must be an ISO-8601 string with UTC offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvaluationError(f"{field} is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvaluationError(f"{field} must include a timezone offset")
    return parsed


def snapshot_content_hash(snapshot: dict[str, Any]) -> str:
    content = {key: value for key, value in snapshot.items() if key != "snapshot_sha256"}
    return sha256_bytes(canonical_json(content))


def validate_snapshot(snapshot: dict[str, Any], expected_contract_sha256: str, now: datetime | None = None, allow_test_fixture: bool = False) -> dict[str, Any]:
    """Validate a prospective scoring snapshot without looking beyond its cutoff."""
    if snapshot.get("schema_version") != 1:
        raise EvaluationError("SNAPSHOT_SCHEMA_UNSUPPORTED")
    if allow_test_fixture and snapshot.get("environment") == "TEST_FIXTURE" and snapshot.get("data_scope") == "TEST_FIXTURE":
        pass
    else:
        if snapshot.get("data_scope") != "PROSPECTIVE_FUTURE":
            raise EvaluationError("NON_PROSPECTIVE_DATA_REJECTED")
        if snapshot.get("environment") != "OFFICIAL_CANDIDATE":
            raise EvaluationError("TEST_OR_REPLAY_DATA_REJECTED")
    snapshot_id = snapshot.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise EvaluationError("SNAPSHOT_ID_REQUIRED")
    if snapshot.get("contract_sha256") != expected_contract_sha256:
        raise EvaluationError("CONTRACT_HASH_MISMATCH")
    if snapshot.get("snapshot_sha256") != snapshot_content_hash(snapshot):
        raise EvaluationError("SNAPSHOT_HASH_MISMATCH")
    try:
        effective = datetime.fromisoformat(snapshot["effective_date"]).date()
    except (KeyError, TypeError, ValueError) as exc:
        raise EvaluationError("EFFECTIVE_DATE_INVALID") from exc
    received = parse_aware(snapshot.get("received_at"), "received_at")
    cutoff = parse_aware(snapshot.get("decision_cutoff_at"), "decision_cutoff_at")
    if received > cutoff:
        raise EvaluationError("DATA_RECEIVED_AFTER_DECISION_CUTOFF")
    if now is not None and cutoff > now:
        raise EvaluationError("DECISION_CUTOFF_IN_FUTURE")
    if cutoff.date() < effective:
        raise EvaluationError("CUTOFF_PRECEDES_EFFECTIVE_DATE")
    if effective.isoformat() <= "2026-02-24":
        raise EvaluationError("HISTORICAL_EFFECTIVE_DATE_REJECTED")
    timezone_name = snapshot.get("timezone")
    if timezone_name != "Asia/Tehran":
        raise EvaluationError("TIMEZONE_MUST_BE_ASIA_TEHRAN")
    calendar = snapshot.get("calendar")
    if not isinstance(calendar, dict) or calendar.get("anchor_date") != "2021-04-03" or calendar.get("anchor_index") != 0:
        raise EvaluationError("O00_CALENDAR_ANCHOR_MISMATCH")
    if calendar.get("complete_through_effective_date") is not True:
        raise EvaluationError("CALENDAR_INCOMPLETE")
    try:
        session_index = int(calendar["session_index"])
        session_date = datetime.fromisoformat(calendar["session_date"]).date()
    except (KeyError, TypeError, ValueError) as exc:
        raise EvaluationError("CALENDAR_SESSION_INVALID") from exc
    if session_index < 0 or session_date != effective:
        raise EvaluationError("CALENDAR_SESSION_DATE_MISMATCH")
    extension = calendar.get("additional_session_dates")
    if not isinstance(extension, list) or not extension or any(not isinstance(day, str) for day in extension):
        raise EvaluationError("CALENDAR_EXTENSION_REQUIRED")
    if extension[-1] != effective.isoformat() or len(extension) != session_index - 1165:
        raise EvaluationError("CALENDAR_EXTENSION_INDEX_MISMATCH")
    if extension != sorted(set(extension)) or extension[0] <= "2026-02-24":
        raise EvaluationError("CALENDAR_EXTENSION_NOT_STRICTLY_INCREASING")
    if calendar.get("history_prefix_sha256") != HISTORICAL_CALENDAR_SHA256 or snapshot.get("expected_history_calendar_sha256") != HISTORICAL_CALENDAR_SHA256:
        raise EvaluationError("O00_HISTORY_PREFIX_HASH_MISMATCH")
    if session_index % 63 != 0:
        raise EvaluationError("NOT_AN_O00_REVIEW_SESSION")
    calendar_hash = sha256_bytes(canonical_json({"history_prefix_sha256": HISTORICAL_CALENDAR_SHA256, "additional_session_dates": extension}))
    if calendar.get("calendar_sha256") != calendar_hash:
        raise EvaluationError("CALENDAR_HASH_REQUIRED")
    if not isinstance(calendar.get("calendar_source_sha256"), str) or len(calendar["calendar_source_sha256"]) != 64:
        raise EvaluationError("CALENDAR_SOURCE_HASH_REQUIRED")
    first_eligible_at = parse_aware(calendar.get("next_session_open_at"), "calendar.next_session_open_at")
    if first_eligible_at <= cutoff:
        raise EvaluationError("FIRST_ELIGIBLE_EXECUTION_NOT_AFTER_DECISION_CUTOFF")
    if now is not None and now >= first_eligible_at:
        raise EvaluationError("DECISION_NOT_REGISTERABLE_BEFORE_FIRST_EXECUTION")
    provenance = snapshot.get("score_provenance")
    if not isinstance(provenance, dict) or provenance.get("uses_only_snapshot_inputs") is not True:
        raise EvaluationError("SCORE_PROVENANCE_INVALID")
    if provenance.get("scorer_contract_sha256") != expected_contract_sha256:
        raise EvaluationError("SCORER_CONTRACT_MISMATCH")
    if not isinstance(provenance.get("scorer_version"), str) or not provenance["scorer_version"].strip():
        raise EvaluationError("SCORER_VERSION_REQUIRED")
    rows = snapshot.get("universe")
    if not isinstance(rows, list) or not rows:
        raise EvaluationError("UNIVERSE_EMPTY")
    symbols: set[str] = set()
    indexes: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationError("UNIVERSE_ROW_INVALID")
        symbol = row.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip() or symbol in symbols:
            raise EvaluationError("UNIVERSE_SYMBOL_MISSING_OR_DUPLICATE")
        symbols.add(symbol)
        try:
            index = int(row["symbol_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvaluationError("SYMBOL_INDEX_INVALID") from exc
        if index < 0 or index in indexes:
            raise EvaluationError("SYMBOL_INDEX_DUPLICATE_OR_NEGATIVE")
        indexes.add(index)
        method_data = row.get("methods")
        if not isinstance(method_data, dict) or set(method_data) != set(METHODS):
            raise EvaluationError("BOTH_LOCKED_METHODS_REQUIRED")
        for method in METHODS:
            result = method_data[method]
            if not isinstance(result, dict) or not all(field in result for field in REQUIRED_METHOD_FIELDS):
                raise EvaluationError(f"{method}_SCORE_ROW_INCOMPLETE")
            score = result.get("score")
            if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)):
                raise EvaluationError(f"{method}_SCORE_NOT_FINITE")
            coverage = result.get("financial_coverage")
            if isinstance(coverage, bool) or not isinstance(coverage, (int, float)) or not math.isfinite(coverage) or not 0 <= coverage <= 1:
                raise EvaluationError(f"{method}_COVERAGE_INVALID")
            if not isinstance(result["raw_factors"], dict) or not isinstance(result["defaulted_factors"], list) or not isinstance(result["masked_factors"], list):
                raise EvaluationError(f"{method}_RAW_FACTOR_AUDIT_INVALID")
            if not isinstance(result["dq"], (int, float)) or not math.isfinite(result["dq"]):
                raise EvaluationError(f"{method}_DQ_INVALID")
    return {"effective_date": effective.isoformat(), "received_at": received.isoformat(), "decision_cutoff_at": cutoff.isoformat(), "session_index": session_index, "universe_count": len(rows)}


def rank_snapshot(snapshot: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Rank by frozen score then stable symbol index, using rows from this snapshot only."""
    ranked: dict[str, list[dict[str, Any]]] = {}
    for method in METHODS:
        candidates = []
        for row in snapshot["universe"]:
            result = row["methods"][method]
            if result["score"] is not None:
                candidates.append((float(result["score"]), int(row["symbol_index"]), row, result))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        ranked[method] = [
            {"rank": rank, "symbol": row["symbol"], "score": score, "financial_coverage": result["financial_coverage"],
             "raw_factors": result["raw_factors"], "defaulted_factors": result["defaulted_factors"], "masked_factors": result["masked_factors"], "dq": result["dq"]}
            for rank, (score, _, row, result) in enumerate(candidates, start=1)
        ]
    return ranked


class AppendOnlyLedger:
    """Small JSONL event store. Production and test ledgers must use different paths."""
    def __init__(self, path: Path, contract_sha256: str, official_path: bool = False):
        self.path = Path(path)
        self.contract_sha256 = contract_sha256
        self.official_path = official_path
        normalized_path = str(self.path).lower().replace("/", "_").replace("\\", "_")
        if official_path and ("return_v12_28" not in normalized_path or "official_event_ledger" not in normalized_path):
            raise EvaluationError("OFFICIAL_LEDGER_PATH_OUTSIDE_V12_28_NAMESPACE")

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for line_no, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvaluationError(f"LEDGER_CORRUPT_LINE_{line_no}") from exc
            if event.get("contract_sha256") != self.contract_sha256:
                raise EvaluationError(f"LEDGER_CONTRACT_HASH_MISMATCH_LINE_{line_no}")
            out.append(event)
        return out

    def append(self, event: dict[str, Any]) -> str:
        events = self.events()
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            raise EvaluationError("EVENT_ID_REQUIRED")
        normalized = {**event, "contract_sha256": self.contract_sha256}
        if normalized.get("event_type") != "UNSPECIFIED_TEST_EVENT":
            required = ("snapshot_id", "snapshot_sha256", "effective_date", "received_at", "decision_cutoff_at")
            if any(not normalized.get(field) for field in required):
                raise EvaluationError("EVENT_SNAPSHOT_PROVENANCE_REQUIRED")
        same_id = next((row for row in events if row["event_id"] == event_id), None)
        if same_id is not None:
            if canonical_json(same_id) == canonical_json(normalized):
                return "DUPLICATE_NOOP"
            raise EvaluationError("EVENT_ID_CONFLICT_DIFFERENT_PAYLOAD")
        if events and normalized.get("recorded_at"):
            new_time = parse_aware(normalized["recorded_at"], "recorded_at")
            last_times = [parse_aware(row["recorded_at"], "recorded_at") for row in events if row.get("recorded_at")]
            if last_times and new_time < max(last_times):
                raise EvaluationError("EVENT_RECORDING_TIME_REVERSED")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(normalized).decode("utf-8") + "\n")
        return "APPENDED"

    def register_snapshot(self, snapshot: dict[str, Any], now: datetime | None = None) -> str:
        validate_snapshot(snapshot, self.contract_sha256, now, allow_test_fixture=not self.official_path)
        content_hash = snapshot_content_hash(snapshot)
        existing = [row for row in self.events() if row.get("event_type") == "SNAPSHOT_REGISTERED" and row.get("snapshot_id") == snapshot["snapshot_id"]]
        if existing:
            if existing[0].get("snapshot_sha256") == content_hash:
                return "DUPLICATE_NOOP"
            raise EvaluationError("SNAPSHOT_ID_CONFLICT_DIFFERENT_CONTENT")
        return self.append({"event_id": f"snapshot:{snapshot['snapshot_id']}", "event_type": "SNAPSHOT_REGISTERED", "recorded_at": datetime.now(timezone.utc).isoformat(), "snapshot_id": snapshot["snapshot_id"], "snapshot_sha256": content_hash, "effective_date": snapshot["effective_date"], "received_at": snapshot["received_at"], "decision_cutoff_at": snapshot["decision_cutoff_at"], "session_index": snapshot["calendar"]["session_index"], "data_scope": snapshot["data_scope"], "snapshot_payload": snapshot})

    def append_correction(self, event_id: str, supersedes_event_id: str, correction: dict[str, Any], recorded_at: str) -> str:
        target = next((row for row in self.events() if row.get("event_id") == supersedes_event_id), None)
        if target is None:
            raise EvaluationError("CORRECTION_TARGET_NOT_FOUND")
        return self.append({"event_id": event_id, "event_type": "CORRECTION", "recorded_at": recorded_at,
                            "supersedes_event_id": supersedes_event_id, "correction": correction,
                            "snapshot_id": target["snapshot_id"], "snapshot_sha256": target["snapshot_sha256"],
                            "effective_date": target["effective_date"], "received_at": target["received_at"],
                            "decision_cutoff_at": target["decision_cutoff_at"], "corrects_without_mutating_target": True})

    def record_decisions(self, snapshot: dict[str, Any], status: str = "WAITING_FOR_DATA", now: datetime | None = None) -> list[str]:
        if status != "ACTIVE":
            raise EvaluationError("OFFICIAL_START_NOT_ACTIVE")
        validate_snapshot(snapshot, self.contract_sha256, now, allow_test_fixture=not self.official_path)
        if self.register_snapshot(snapshot, now) == "DUPLICATE_NOOP":
            if any(row.get("event_type") == "DECISION" and row.get("snapshot_id") == snapshot["snapshot_id"] for row in self.events()):
                return ["DUPLICATE_NOOP", "DUPLICATE_NOOP"]
        if not any(row.get("event_type") == "FORMAL_START" for row in self.events()):
            formal_start = {"event_id": f"formal-start:{snapshot['snapshot_id']}", "event_type": "FORMAL_START", "recorded_at": datetime.now(timezone.utc).isoformat(),
                            "snapshot_id": snapshot["snapshot_id"], "snapshot_sha256": snapshot_content_hash(snapshot), "effective_date": snapshot["effective_date"],
                            "received_at": snapshot["received_at"], "decision_cutoff_at": snapshot["decision_cutoff_at"], "session_index": snapshot["calendar"]["session_index"],
                            "milestone_session_indices": {str(h): int(snapshot["calendar"]["session_index"]) + h for h in (63, 126, 252)},
                            "accounts_initialized": {method: {"cash_toman": 100_000_000.0, "holdings_actual_shares": {}, "nav_toman": 100_000_000.0} for method in METHODS},
                            "start_rule": "fresh cash accounts; no historical assets or balance transferred"}
            self.append(formal_start)
        ranked = rank_snapshot(snapshot)
        results = []
        for method in METHODS:
            rows = ranked[method]
            selected = rows[0] if rows else None
            prior = [e for e in self.events() if e.get("method_id") == method and e.get("event_type") in {"DECISION", "ORDER_EXECUTION", "ORDER_CREATED"} and e.get("state_post")]
            state = dict(prior[-1]["state_post"]) if prior else {"cash_toman": 100_000_000.0, "holdings_actual_shares": {}, "market_price_marks_toman": {}, "nav_toman": 100_000_000.0, "net_profit_toman": 0.0, "valuation_status": "CASH_ONLY_INITIAL_STATE", "pending_orders": []}
            state["holdings_actual_shares"] = dict(state.get("holdings_actual_shares", {}))
            state["market_price_marks_toman"] = dict(state.get("market_price_marks_toman", {}))
            state["pending_orders"] = [dict(item) for item in state.get("pending_orders", [])]
            pending = [dict(item) for item in state["pending_orders"]]
            held = {symbol: float(qty) for symbol, qty in state["holdings_actual_shares"].items() if float(qty) > 1e-9}
            target = selected["symbol"] if selected else None
            order = None
            if not pending and target and target in held:
                pass  # no-trim: keep the already-held ranked target
            elif not pending and target and held:
                symbol_to_sell = next(iter(held))
                order = {"order_id": f"{snapshot['snapshot_id']}:{method}:exit:{symbol_to_sell}", "side": "SELL", "symbol": symbol_to_sell,
                         "quantity_shares": held[symbol_to_sell], "created_at": snapshot["decision_cutoff_at"], "first_eligible_session_index": int(snapshot["calendar"]["session_index"]) + 1,
                         "first_eligible_at": snapshot["calendar"].get("next_session_open_at"), "status": "PENDING", "reason": "rank_exit_replacement"}
            elif not pending and target and state["cash_toman"] > 0:
                order = {"order_id": f"{snapshot['snapshot_id']}:{method}:entry:{target}", "side": "BUY", "symbol": target, "quantity_shares": None,
                         "created_at": snapshot["decision_cutoff_at"], "first_eligible_session_index": int(snapshot["calendar"]["session_index"]) + 1,
                         "first_eligible_at": snapshot["calendar"].get("next_session_open_at"), "status": "PENDING", "notional_target_toman": float(state["cash_toman"]),
                         "reason": "fresh_cash_initial_entry" if not prior else "rank_exit_replacement_entry"}
            post = {**state, "pending_orders": pending + ([order] if order else [])}
            decision = {"event_id": f"decision:{snapshot['snapshot_id']}:{method}", "event_type": "DECISION", "recorded_at": datetime.now(timezone.utc).isoformat(),
                        "snapshot_id": snapshot["snapshot_id"], "snapshot_sha256": snapshot_content_hash(snapshot), "method_id": method,
                        "contract_sha256": self.contract_sha256, "decision_cutoff_at": snapshot["decision_cutoff_at"], "effective_date": snapshot["effective_date"],
                        "received_at": snapshot["received_at"],
                        "session_index": snapshot["calendar"]["session_index"], "ranked_universe": rows, "selected_symbol": selected["symbol"] if selected else None,
                        "selection_reason": "highest finite locked-method score; stable symbol_index tie-break" if selected else "NO_VALID_SCORE_CASH",
                        "state_pre": {**state, "pending_orders": pending}, "state_post": post, "pending_order_created": order, "accounting_status": "WAITING_FOR_ACTUAL_SHARE_PRICE_AND_CORPORATE_ACTION_DATA"}
            results.append(self.append(decision))
        return results

    def record_fill(self, event_id: str, order_id: str, method_id: str, symbol: str, quantity_shares: float, price_toman: float, fee_toman: float, executed_at: str, first_eligible_at: str, status: str = "FILLED", price_source: str = "", corporate_action_status: str = "UNKNOWN", execution_constraints: str = "UNKNOWN", reason: str = "", now: datetime | None = None) -> str:
        if status not in {"PARTIAL", "FILLED", "NOT_EXECUTED", "CANCELLED"}:
            raise EvaluationError("EXECUTION_STATUS_INVALID")
        executed = parse_aware(executed_at, "executed_at")
        eligible = parse_aware(first_eligible_at, "first_eligible_at")
        if method_id not in METHODS:
            raise EvaluationError("UNKNOWN_LOCKED_METHOD")
        already = next((event for event in self.events() if event.get("event_id") == event_id), None)
        if already:
            same = (already.get("event_type") == "ORDER_EXECUTION" and already.get("order_id") == order_id and already.get("method_id") == method_id
                    and already.get("symbol") == symbol and already.get("quantity_shares") == quantity_shares and already.get("price_toman") == price_toman
                    and already.get("fee_toman") == fee_toman and already.get("executed_at") == executed.isoformat() and already.get("status") == status)
            same = same and already.get("first_eligible_at") == eligible.isoformat() and already.get("price_source") == price_source
            same = same and already.get("corporate_action_status") == corporate_action_status and already.get("execution_constraints") == execution_constraints and already.get("reason") == reason
            if same:
                return "DUPLICATE_NOOP"
            raise EvaluationError("EVENT_ID_CONFLICT_DIFFERENT_PAYLOAD")
        if status in {"NOT_EXECUTED", "CANCELLED"} and not reason.strip():
            raise EvaluationError("NON_EXECUTION_REASON_REQUIRED")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in (quantity_shares, price_toman, fee_toman)):
            raise EvaluationError("FILL_NUMERIC_FIELDS_INVALID")
        prior = self.events()
        orders = [o for e in prior if e.get("method_id") == method_id for o in [e.get("pending_order_created"), e.get("order")]]
        order = next((o for o in orders if o and o.get("order_id") == order_id), None)
        if not order:
            raise EvaluationError("ORDER_NOT_FOUND_IN_EVENT_LEDGER")
        recorded_eligibility = order.get("first_eligible_at")
        if not recorded_eligibility or parse_aware(recorded_eligibility, "order.first_eligible_at") != eligible:
            raise EvaluationError("FIRST_ELIGIBLE_TIME_DOES_NOT_MATCH_ORDER")
        if executed < eligible:
            raise EvaluationError("EXECUTION_BEFORE_FIRST_ELIGIBLE_TIME")
        if executed > (now or datetime.now(timezone.utc)):
            raise EvaluationError("EXECUTION_EVENT_TIME_IN_FUTURE")
        if status in {"PARTIAL", "FILLED"} and (not price_source.strip() or corporate_action_status != "VERIFIED" or execution_constraints == "UNKNOWN"):
            raise EvaluationError("EXECUTION_PROVENANCE_OR_CORPORATE_ACTIONS_MISSING")
        if order.get("symbol") != symbol:
            raise EvaluationError("FILL_SYMBOL_MISMATCH")
        gross = quantity_shares * price_toman
        if status in {"PARTIAL", "FILLED"} and quantity_shares <= 0:
            raise EvaluationError("POSITIVE_FILL_QUANTITY_REQUIRED")
        if status in {"NOT_EXECUTED", "CANCELLED"} and (quantity_shares != 0 or price_toman != 0 or fee_toman != 0):
            raise EvaluationError("NON_EXECUTION_MUST_HAVE_ZERO_FILL_VALUES")
        decision = next((e for e in reversed(prior) if e.get("event_type") == "DECISION" and e.get("method_id") == method_id), None)
        if decision is None:
            raise EvaluationError("DECISION_NOT_FOUND_FOR_ACCOUNT")
        prior_account_events = [e for e in prior if e.get("method_id") == method_id and e.get("event_type") in {"ORDER_EXECUTION", "ORDER_CREATED"} and e.get("state_post")]
        pre = dict(prior_account_events[-1]["state_post"] if prior_account_events else decision["state_post"])
        pre["holdings_actual_shares"] = dict(pre.get("holdings_actual_shares", {}))
        pre["market_price_marks_toman"] = dict(pre.get("market_price_marks_toman", {}))
        pre["pending_orders"] = [dict(item) for item in pre.get("pending_orders", [])]
        target_order = next((item for item in pre["pending_orders"] if item.get("order_id") == order_id), None)
        if not target_order:
            raise EvaluationError("ORDER_NO_LONGER_PENDING")
        if status in {"PARTIAL", "FILLED"}:
            if target_order.get("side") == "BUY":
                if gross + fee_toman > float(pre["cash_toman"]) + 1e-9:
                    raise EvaluationError("INSUFFICIENT_CASH_FOR_FILL")
                pre["cash_toman"] = float(pre["cash_toman"]) - gross - fee_toman
                pre["holdings_actual_shares"][symbol] = float(pre["holdings_actual_shares"].get(symbol, 0.0)) + quantity_shares
            else:
                held = float(pre["holdings_actual_shares"].get(symbol, 0.0))
                if quantity_shares > held + 1e-9:
                    raise EvaluationError("SELL_FILL_EXCEEDS_HELD_SHARES")
                pre["cash_toman"] = float(pre["cash_toman"]) + gross - fee_toman
                pre["holdings_actual_shares"][symbol] = held - quantity_shares
            pre["market_price_marks_toman"][symbol] = float(price_toman)
            target_order["filled_quantity_shares"] = float(target_order.get("filled_quantity_shares", 0.0)) + quantity_shares
            target_order["last_execution_status"] = status
        elif status == "CANCELLED":
            pre["pending_orders"] = [item for item in pre["pending_orders"] if item.get("order_id") != order_id]
        if status == "FILLED":
            pre["pending_orders"] = [item for item in pre["pending_orders"] if item.get("order_id") != order_id]
        held_symbols = [key for key, value in pre["holdings_actual_shares"].items() if value > 1e-9]
        if all(symbol_key in pre["market_price_marks_toman"] for symbol_key in held_symbols):
            pre["nav_toman"] = float(pre["cash_toman"]) + sum(float(pre["holdings_actual_shares"][key]) * float(pre["market_price_marks_toman"][key]) for key in held_symbols)
            pre["valuation_status"] = "MARKED_AT_LAST_RECORDED_EXECUTION_PRICE" if held_symbols else "CASH_ONLY"
            pre["net_profit_toman"] = pre["nav_toman"] - 100_000_000.0
        else:
            pre["nav_toman"] = None
            pre["valuation_status"] = "MARK_MISSING_FOR_HELD_SECURITY"
            pre["net_profit_toman"] = None
        post = dict(pre)
        post["holdings_actual_shares"] = dict(pre["holdings_actual_shares"])
        post["market_price_marks_toman"] = dict(pre["market_price_marks_toman"])
        post["pending_orders"] = [dict(item) for item in pre["pending_orders"]]
        before = dict(prior_account_events[-1]["state_post"] if prior_account_events else decision["state_post"])
        before["holdings_actual_shares"] = dict(before.get("holdings_actual_shares", {})); before["market_price_marks_toman"] = dict(before.get("market_price_marks_toman", {})); before["pending_orders"] = [dict(item) for item in before.get("pending_orders", [])]
        event = {"event_id": event_id, "event_type": "ORDER_EXECUTION", "recorded_at": datetime.now(timezone.utc).isoformat(), "method_id": method_id,
                            "snapshot_id": decision["snapshot_id"], "snapshot_sha256": decision["snapshot_sha256"], "effective_date": decision["effective_date"],
                            "received_at": decision["received_at"], "decision_cutoff_at": decision["decision_cutoff_at"],
                            "order_id": order_id, "symbol": symbol, "status": status, "executed_at": executed.isoformat(), "first_eligible_at": eligible.isoformat(),
                            "quantity_shares": quantity_shares, "price_toman": price_toman, "price_source": price_source, "corporate_action_status": corporate_action_status,
                            "execution_constraints": execution_constraints, "reason": reason, "gross_toman": gross, "fee_toman": fee_toman,
                            "cash_delta_toman": -(gross + fee_toman) if order.get("side") == "BUY" else gross - fee_toman,
                            "state_pre": before, "state_post": post,
                            "accounting_basis": "ACTUAL_SHARES_AND_RECORDED_EXECUTION_PRICE"}
        return self.append(event)

    def record_valuation(self, event_id: str, method_id: str, snapshot_id: str, snapshot_sha256: str, effective_at: str, received_at: str,
                         decision_cutoff_at: str, prices_toman_per_share: dict[str, float | None], price_source: str,
                         corporate_action_status: str, price_unit: str = "IRR_TOMAN_PER_SHARE_UNADJUSTED", now: datetime | None = None) -> str:
        if method_id not in METHODS:
            raise EvaluationError("UNKNOWN_LOCKED_METHOD")
        effective = parse_aware(effective_at, "effective_at")
        received = parse_aware(received_at, "received_at")
        cutoff = parse_aware(decision_cutoff_at, "decision_cutoff_at")
        current = now or datetime.now(timezone.utc)
        if received > cutoff:
            raise EvaluationError("VALUATION_RECEIVED_AFTER_CUTOFF")
        if cutoff > current or received > current:
            raise EvaluationError("VALUATION_NOT_YET_RECEIVED")
        if not snapshot_id or len(snapshot_sha256) != 64:
            raise EvaluationError("VALUATION_SNAPSHOT_PROVENANCE_REQUIRED")
        if not isinstance(prices_toman_per_share, dict):
            raise EvaluationError("VALUATION_PRICE_MAP_REQUIRED")
        existing_event = next((row for row in self.events() if row.get("event_id") == event_id), None)
        if existing_event:
            same = (existing_event.get("event_type") == "VALUATION" and existing_event.get("method_id") == method_id
                    and existing_event.get("snapshot_id") == snapshot_id and existing_event.get("snapshot_sha256") == snapshot_sha256
                    and existing_event.get("effective_at") == effective.isoformat() and existing_event.get("received_at") == received.isoformat()
                    and existing_event.get("decision_cutoff_at") == cutoff.isoformat() and existing_event.get("prices_toman_per_share") == prices_toman_per_share
                    and existing_event.get("price_source") == price_source and existing_event.get("corporate_action_status") == corporate_action_status
                    and existing_event.get("price_unit") == price_unit)
            if same:
                return "DUPLICATE_NOOP"
            raise EvaluationError("EVENT_ID_CONFLICT_DIFFERENT_PAYLOAD")
        if not price_source.strip() or corporate_action_status != "VERIFIED":
            raise EvaluationError("VALUATION_SOURCE_OR_CORPORATE_ACTION_STATUS_MISSING")
        if price_unit != "IRR_TOMAN_PER_SHARE_UNADJUSTED":
            raise EvaluationError("ACTUAL_SHARE_PRICE_UNIT_REQUIRED")
        if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0) for value in prices_toman_per_share.values()):
            raise EvaluationError("VALUATION_PRICE_INVALID")
        prior = self.events()
        last_valuation = next((row for row in reversed(prior) if row.get("event_type") == "VALUATION" and row.get("method_id") == method_id), None)
        if last_valuation and effective < parse_aware(last_valuation["effective_at"], "prior.effective_at"):
            raise EvaluationError("VALUATION_TIME_REVERSED")
        decision = next((row for row in reversed(prior) if row.get("event_type") == "DECISION" and row.get("method_id") == method_id), None)
        if decision is None:
            raise EvaluationError("DECISION_NOT_FOUND_FOR_ACCOUNT")
        if cutoff < parse_aware(decision["decision_cutoff_at"], "decision.decision_cutoff_at"):
            raise EvaluationError("VALUATION_PRECEDES_LAST_DECISION")
        account_events = [row for row in prior if row.get("method_id") == method_id and row.get("state_post")]
        pre = dict(account_events[-1]["state_post"] if account_events else decision["state_post"])
        pre["holdings_actual_shares"] = dict(pre.get("holdings_actual_shares", {}))
        pre["market_price_marks_toman"] = dict(pre.get("market_price_marks_toman", {}))
        pre["pending_orders"] = [dict(item) for item in pre.get("pending_orders", [])]
        missing = []
        for symbol, quantity in pre["holdings_actual_shares"].items():
            if float(quantity) <= 1e-9:
                continue
            if prices_toman_per_share.get(symbol) is None:
                missing.append(symbol)
            else:
                pre["market_price_marks_toman"][symbol] = float(prices_toman_per_share[symbol])
        if missing:
            pre["nav_toman"] = None
            pre["net_profit_toman"] = None
            pre["valuation_status"] = "VALUATION_INCOMPLETE_MISSING_PRICE"
        else:
            pre["nav_toman"] = float(pre["cash_toman"]) + sum(float(quantity) * float(pre["market_price_marks_toman"][symbol]) for symbol, quantity in pre["holdings_actual_shares"].items() if float(quantity) > 1e-9)
            pre["net_profit_toman"] = pre["nav_toman"] - 100_000_000.0
            pre["valuation_status"] = "MARKED_WITH_RECORDED_ACTUAL_SHARE_PRICE_SNAPSHOT"
        post = {**pre,"holdings_actual_shares":dict(pre["holdings_actual_shares"]),"market_price_marks_toman":dict(pre["market_price_marks_toman"]),"pending_orders":[dict(item) for item in pre["pending_orders"]]}
        before_event = dict(account_events[-1]["state_post"] if account_events else decision["state_post"])
        before_event["holdings_actual_shares"] = dict(before_event.get("holdings_actual_shares", {})); before_event["market_price_marks_toman"] = dict(before_event.get("market_price_marks_toman", {})); before_event["pending_orders"] = [dict(item) for item in before_event.get("pending_orders", [])]
        return self.append({"event_id":event_id,"event_type":"VALUATION","recorded_at":current.astimezone(timezone.utc).isoformat(),"method_id":method_id,
                            "snapshot_id":snapshot_id,"snapshot_sha256":snapshot_sha256,"effective_date":effective.date().isoformat(),"effective_at":effective.isoformat(),
                            "received_at":received.isoformat(),"decision_cutoff_at":cutoff.isoformat(),"price_source":price_source,"price_unit":price_unit,
                            "corporate_action_status":corporate_action_status,"prices_toman_per_share":prices_toman_per_share,"missing_symbols":missing,
                            "state_pre":before_event,"state_post":post})


def main() -> int:
    parser = argparse.ArgumentParser(description="V12.28 prospective evaluation ledger; no historical replay")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--contract-sha256", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--decisions-export", type=Path, required=True)
    parser.add_argument("--public-state", type=Path, required=True)
    parser.add_argument("--public-ledger", type=Path, required=True)
    parser.add_argument("--public-decisions-export", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--execution-event", type=Path)
    parser.add_argument("--status", default="WAITING_FOR_DATA", choices=("PREPARING", "WAITING_FOR_DATA", "ACTIVE"))
    parser.add_argument("--operator-approve-start", action="store_true", help="Explicitly authorize the first formal future start after snapshot validation")
    args = parser.parse_args()
    expected = args.contract_sha256.read_text(encoding="ascii").strip()
    actual = file_sha256(args.contract)
    if expected != actual:
        raise SystemExit("CONTRACT_HASH_MISMATCH")
    ledger = AppendOnlyLedger(args.ledger, expected, official_path=True)
    if not args.snapshot and not args.execution_event:
        print(json.dumps({"event_count": len(ledger.events()), "ledger": str(args.ledger), "contract_sha256": expected}, ensure_ascii=False))
        return 0
    has_start = any(row.get("event_type") == "FORMAL_START" for row in ledger.events())
    if args.snapshot and args.status == "ACTIVE" and not has_start and not args.operator_approve_start:
        raise SystemExit("EXPLICIT_OPERATOR_START_APPROVAL_REQUIRED")
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8-sig")) if args.snapshot else None
    if snapshot is not None:
        ledger.record_decisions(snapshot, status=args.status, now=datetime.now(timezone.utc))
    if args.execution_event:
        execution = json.loads(args.execution_event.read_text(encoding="utf-8-sig"))
        ledger.record_fill(**execution)
    decisions = [row for row in ledger.events() if row.get("event_type") == "DECISION"]
    args.decisions_export.parent.mkdir(parents=True, exist_ok=True)
    args.decisions_export.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in decisions), encoding="utf-8")
    if args.status == "ACTIVE" and any(row.get("event_type") == "FORMAL_START" for row in events):
        events = ledger.events()
        start = next(row for row in events if row.get("event_type") == "FORMAL_START")
        decisions = [row for row in events if row.get("event_type") == "DECISION"]
        last_decision = decisions[-1] if decisions else None
        pending = {}
        results = {}
        for method in METHODS:
            last_state_event = next((row for row in reversed(events) if row.get("method_id") == method and row.get("state_post")), None)
            account_state = last_state_event.get("state_post", {}) if last_state_event else {}
            pending[method] = account_state.get("pending_orders", [])
            fills = [row for row in events if row.get("event_type") == "ORDER_EXECUTION" and row.get("method_id") == method and row.get("status") in {"PARTIAL", "FILLED"}]
            if fills:
                results[method] = {"nav_toman":account_state.get("nav_toman"),"net_profit_toman":account_state.get("net_profit_toman"),
                                   "fees_toman":sum(float(row.get("fee_toman", 0)) for row in events if row.get("event_type") == "ORDER_EXECUTION" and row.get("method_id") == method),
                                   "cash_toman":account_state.get("cash_toman"),"holdings_actual_shares":account_state.get("holdings_actual_shares", {}),
                                   "valuation_status":account_state.get("valuation_status")}
        state = {"status":"ACTIVE","formal_start_date":start["effective_date"],"formal_start_session_index":start["session_index"],
                 "milestones":start["milestone_session_indices"],"last_decision":last_decision.get("snapshot_id") if last_decision else None,"pending_orders":pending,
                 "account_results":results or None,"official_event_count":len(events),"contract_sha256":expected}
        args.state.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.state.with_suffix(args.state.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        tmp.replace(args.state)
        for target, source in ((args.public_state,args.state),(args.public_ledger,args.ledger),(args.public_decisions_export,args.decisions_export)):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    print(json.dumps({"event_count": len(ledger.events()), "ledger": str(args.ledger), "status": args.status}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
