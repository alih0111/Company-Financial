"""Build a versioned comparison from saved paper-account snapshots only."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from ranking_research.future_eval_v12_30 import experimental_paper as exp

TEHRAN = ZoneInfo("Asia/Tehran")


def _value(account):
    accounting = account.get("accounting") or {}
    value = accounting.get("total_value_toman")
    return int(value) if isinstance(value, (int, float)) else None


def _fee_events(account):
    found = {}
    for event in account.get("event_log", []):
        if event.get("type") not in ("PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE", "PAPER_SELL_DAILY_CLOSE_LIMITED_QUEUE"):
            continue
        match = re.search(r"assumed_fee_toman=(\d+)", event.get("details", ""))
        fee = int(match.group(1)) if match else None
        found[event.get("event_id", f"{event.get('at_utc')}:{event.get('type')}")] = fee
    return found


def _point(account, at, outcome_status):
    holdings = account.get("holdings") or []
    prices = [h.get("last_price_date") for h in holdings]
    has_price = (all(p for p in prices) and outcome_status in ("MARK_APPLIED", "FILL_APPLIED")) if holdings else None
    local_day = dt.datetime.fromisoformat(at).astimezone(TEHRAN).date().isoformat()
    price_day = min((p for p in prices if p), default=None)
    age_days = (dt.date.fromisoformat(local_day) - dt.date.fromisoformat(price_day)).days if price_day else None
    return {"observed_at_utc": at, "observation_day_local": local_day,
            "cash_toman": account.get("cash_toman"),
            "holdings_value_toman": (account.get("accounting") or {}).get("holdings_value_toman"),
            "total_value_toman": _value(account), "last_price_dates": prices,
            "last_price_market_date": price_day,
            "last_mark_recorded_at_utc": None,
            "price_age_calendar_days": age_days,
            "price_mark_stale": bool(age_days is not None and age_days > 0),
            "valid_price_observation": has_price,
            "symbols": sorted({h.get("symbol") for h in holdings if h.get("symbol")})}


def _schedule_coverage(observations, config, generated_at):
    policy = config.get("observation_schedule_policy")
    if not isinstance(policy, dict):
        return {"status": "UNKNOWN", "scheduled_slots": None,
                "observed_slots": None, "pending_slots": None, "missed_slots": None, "fraction": None,
                "reason": "NO_RECORDED_OBSERVATION_SCHEDULE_POLICY"}
    if not policy.get("daily_local_times") or not policy.get("timezone") or "late_grace_minutes" not in policy:
        return {"status": "UNKNOWN", "scheduled_slots": None,
                "observed_slots": None, "pending_slots": None, "missed_slots": None, "fraction": None,
                "reason": "RECORDED_OBSERVATION_SCHEDULE_POLICY_INCOMPLETE"}
    try:
        def aware(value):
            stamp = dt.datetime.fromisoformat(value)
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("SCHEDULE_TIMESTAMP_TIMEZONE_MISSING")
            return stamp.astimezone(dt.timezone.utc)

        zone = ZoneInfo(policy["timezone"])
        start_utc = aware(config["started_at_utc"])
        end_utc = aware(config["ends_at_utc"])
        generated_utc = aware(generated_at)
        if end_utc < start_utc:
            raise ValueError("SCHEDULE_PERIOD_END_BEFORE_START")
        tolerance = int(policy.get("matching_tolerance_minutes", 30))
        grace = int(policy["late_grace_minutes"])
        if tolerance < 0 or tolerance > 1440 or grace < 0 or grace > 1440:
            raise ValueError("SCHEDULE_MATCHING_TOLERANCE_INVALID")
        days_policy = policy.get("days", "every_calendar_day")
        if days_policy not in ("every_calendar_day", "weekdays"):
            raise ValueError("SCHEDULE_DAYS_POLICY_INVALID")
        local_start = start_utc.astimezone(zone).date()
        local_end = end_utc.astimezone(zone).date()
        slots = []
        time_values = policy["daily_local_times"]
        if len(set(time_values)) != len(time_values):
            raise ValueError("SCHEDULE_LOCAL_TIMES_DUPLICATED")
        for value in time_values:
            hour, minute = map(int, value.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("SCHEDULE_LOCAL_TIME_INVALID")
        day = local_start
        while day <= local_end:
            if days_policy == "every_calendar_day" or day.weekday() < 5:
                for value in policy["daily_local_times"]:
                    hour, minute = map(int, value.split(":"))
                    slot = dt.datetime.combine(day, dt.time(hour, minute), zone).astimezone(dt.timezone.utc)
                    if start_utc <= slot <= end_utc and slot <= generated_utc:
                        slots.append(slot)
            day += dt.timedelta(days=1)

        run_times = []
        for doc in observations:
            try:
                run = aware(doc["updated_at_utc"])
            except (KeyError, TypeError, ValueError):
                continue
            if start_utc <= run <= end_utc and run <= generated_utc:
                run_times.append(run)

        # Maximum-cardinality one-to-one matching: a snapshot can cover at most
        # one slot, and a slot can consume at most one snapshot.
        candidates = {}
        for run_index, run in enumerate(run_times):
            candidates[run_index] = sorted(
                (i for i, slot in enumerate(slots)
                 if abs((run - slot).total_seconds()) <= tolerance * 60),
                key=lambda i: (abs((run_times[run_index] - slots[i]).total_seconds()), slots[i]))
        slot_to_run = {}

        def assign(run_index, seen):
            for slot_index in candidates[run_index]:
                if slot_index in seen:
                    continue
                seen.add(slot_index)
                previous_run = slot_to_run.get(slot_index)
                if previous_run is None or assign(previous_run, seen):
                    slot_to_run[slot_index] = run_index
                    return True
            return False

        for run_index in sorted(candidates, key=lambda i: (len(candidates[i]), run_times[i])):
            assign(run_index, set())

        observed_indices = set(slot_to_run)
        grace_end = [slot + dt.timedelta(minutes=grace) for slot in slots]
        pending_indices = {i for i in range(len(slots))
                           if i not in observed_indices and generated_utc <= grace_end[i]}
        missed_indices = set(range(len(slots))) - observed_indices - pending_indices
        count = len(slots)
        observed = len(observed_indices)
        return {"status": "KNOWN", "policy_id": policy.get("id"), "timezone": policy["timezone"],
                "daily_local_times": policy["daily_local_times"], "matching_tolerance_minutes": tolerance,
                "period_started_at_utc": start_utc.isoformat(), "period_ends_at_utc": end_utc.isoformat(),
                "evaluated_at_utc": generated_utc.isoformat(),
                "late_grace_minutes": grace,
                "scheduled_slots": count, "observed_slots": observed,
                "pending_slots": len(pending_indices), "missed_slots": len(missed_indices),
                "observed_slot_times_utc": [slots[i].isoformat() for i in sorted(observed_indices)],
                "pending_slot_times_utc": [slots[i].isoformat() for i in sorted(pending_indices)],
                "missed_slot_times_utc": [slots[i].isoformat() for i in sorted(missed_indices)],
                "fraction": observed / count if count else None,
                "method": "One-to-one timestamp matching; snapshots outside the inclusive configured period are excluded. Unmatched slots stay pending through the configured tolerance, then count as missed. Task execution IDs unavailable."}
    except (KeyError, TypeError, ValueError) as error:
        return {"status": "UNKNOWN", "scheduled_slots": None, "observed_slots": None,
                "pending_slots": None, "missed_slots": None, "fraction": None,
                "reason": f"INVALID_RECORDED_SCHEDULE_POLICY: {error}"}


def summarize(home: Path, current_payload: dict, ended: bool) -> dict:
    run_files = sorted((home / "runs").glob("*/daily.json"))
    observations, malformed = [], []
    for file in run_files:
        try:
            doc = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("updated_at_utc") and isinstance(doc.get("accounts", {}), dict):
                stamp = dt.datetime.fromisoformat(doc["updated_at_utc"])
                if stamp.tzinfo is None:
                    raise ValueError("OBSERVATION_TIMESTAMP_TIMEZONE_MISSING")
                observations.append(doc)
            else:
                malformed.append({"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                                  "error": "MISSING_UPDATED_AT_OR_INVALID_SCHEMA"})
        except (OSError, ValueError, TypeError) as error:
            try:
                digest = hashlib.sha256(file.read_bytes()).hexdigest()
            except OSError:
                digest = None
            malformed.append({"path": str(file), "sha256": digest, "error": str(error)})
    if not observations or observations[-1].get("updated_at_utc") != current_payload.get("updated_at_utc"):
        observations.append(current_payload)
    observations.sort(key=lambda doc: doc.get("updated_at_utc", ""))
    methods = current_payload.get("config", {}).get("methods", ["P1", "P3"])
    summaries = {}
    for method in methods:
        points, event_ids, fees, transactions = [], {}, {}, []
        outcome_count = 0
        for doc in observations:
            row = (doc.get("accounts") or {}).get(method) or {}
            outcome_count += isinstance(row.get("outcome"), dict)
            account = row.get("account")
            if not isinstance(account, dict):
                continue
            at = doc.get("updated_at_utc")
            point = _point(account, at, (row.get("outcome") or {}).get("status"))
            price_events = [e.get("at_utc") for e in account.get("event_log", [])
                            if e.get("type") in ("PAPER_MARK_TO_MARKET", "PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE") and e.get("at_utc")]
            point["last_mark_recorded_at_utc"] = max(price_events) if price_events else None
            points.append(point)
            for event in account.get("event_log", []):
                if event.get("type") in ("PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE", "PAPER_SELL_DAILY_CLOSE_LIMITED_QUEUE"):
                    key = event.get("event_id")
                    if key and key not in event_ids:
                        event_ids[key] = event
                        transactions.append({"event_id": key, "type": event.get("type"),
                            "at_utc": event.get("at_utc"), "reason": event.get("reason"),
                            "details": event.get("details")})
            fees.update(_fee_events(account))
        initial = (current_payload.get("config") or {}).get("initial_capital_per_method_toman")
        priced = [point for point in points if point["total_value_toman"] is not None]
        peak = None
        drawdowns = []
        for point in priced:
            value = point["total_value_toman"]
            peak = max(peak, value) if peak is not None else value
            drawdowns.append((peak - value) / peak if peak else 0)
        last = points[-1] if points else None
        applicable = [p for p in points if p["valid_price_observation"] is not None]
        day_groups = {}
        for point in applicable:
            day_groups.setdefault(point["observation_day_local"], []).append(point)
        days_without_price = sum(not any(p["valid_price_observation"] is True for p in day_points)
                                 for day_points in day_groups.values())
        summaries[method] = {"initial_capital_toman": initial,
            "latest_total_value_toman": last["total_value_toman"] if last else None,
            "net_return_toman": (last["total_value_toman"] - initial) if last and last["total_value_toman"] is not None and initial is not None else None,
            "net_return_fraction": ((last["total_value_toman"] / initial) - 1) if last and last["total_value_toman"] is not None and initial else None,
            "cash_toman": last["cash_toman"] if last else None,
            "holdings_value_toman": last["holdings_value_toman"] if last else None,
            "observed_max_drawdown_fraction": max(drawdowns) if drawdowns else None,
            "observed_max_drawdown_label": "drawdown only across saved observation points; not intraday drawdown",
            "observed_points": len(points), "observed_run_count": len(observations),
            "unique_observation_days": len({p["observation_day_local"] for p in points}),
            "outcome_coverage_fraction": outcome_count / len(observations) if observations else None,
            "valid_price_coverage_fraction": sum(p["valid_price_observation"] is True for p in applicable) / len(applicable) if applicable else None,
            "unique_days_without_valid_price": days_without_price,
            "price_observation_applicable_points": len(applicable),
            "price_observation_applicable_days": len(day_groups),
            "assumed_cost_toman": sum(x for x in fees.values() if x is not None),
            "costs_missing_for_transactions": sum(x is None for x in fees.values()),
            "transaction_count": len(transactions), "transactions": transactions,
            "decision_symbol": ((observations[-1].get("accounts") or {}).get(method) or {}).get("account", {}).get("paper_order", {}).get("symbol"),
            "last_price_dates": last["last_price_dates"] if last else [],
            "last_price_market_date": last["last_price_market_date"] if last else None,
            "last_price_observed_at_utc": last["last_mark_recorded_at_utc"] if last else None,
            "last_price_age_calendar_days": last["price_age_calendar_days"] if last else None,
            "last_price_is_stale": last["price_mark_stale"] if last else None,
            "last_observed_at_utc": last["observed_at_utc"] if last else None,
            "points": points}
    symbols = {m: (s["points"][-1]["symbols"] if s["points"] else []) for m, s in summaries.items()}
    common = set.intersection(*(set(v) for v in symbols.values())) if symbols else set()
    decision_symbols = {m: s["decision_symbol"] for m, s in summaries.items() if s["decision_symbol"]}
    common_decisions = set.intersection(*(set([v]) for v in decision_symbols.values())) if decision_symbols else set()
    point_maps = {m: {p["observed_at_utc"]: p for p in s["points"]} for m, s in summaries.items()}
    common_times = set.intersection(*(set(v) for v in point_maps.values())) if point_maps else set()
    aligned = []
    if len(point_maps) == 2:
        left, right = methods
        for at in sorted(common_times):
            p1, p3 = point_maps[left][at], point_maps[right][at]
            if p1["total_value_toman"] is not None and p3["total_value_toman"] is not None:
                aligned.append({"observed_at_utc": at,
                    "P1_total_value_toman": p1["total_value_toman"],
                    "P3_total_value_toman": p3["total_value_toman"],
                    "P1_minus_P3_toman": p1["total_value_toman"] - p3["total_value_toman"]})
    generated = current_payload.get("updated_at_utc") or exp.now().isoformat()
    return {"schema_version": 2, "report_type": "PAPER_MONTH_TRIAL_COMPARISON",
        "state": "FINAL" if ended else "PROVISIONAL", "generated_at_utc": generated,
        "period": {"started_at_utc": current_payload.get("config", {}).get("started_at_utc"),
                   "ends_at_utc": current_payload.get("config", {}).get("ends_at_utc"),
                   "ended": bool(ended), "stop_execution": bool(ended),
                   "execution_stopped_at_utc": generated if ended else None,
                   "forced_liquidation": False},
        "observation_schedule_coverage": _schedule_coverage(observations, current_payload.get("config", {}), generated),
        "history_integrity": {"status": "ISSUES" if malformed else "OK", "malformed_run_count": len(malformed), "malformed_runs": malformed},
        "accounts": summaries,
        "comparison": {"common_last_observed_symbols": sorted(common),
            "common_decision_symbols": sorted(common_decisions),
            "same_symbol_models_are_independent_performance_evidence": False if common or common_decisions else None,
            "aligned_observation_count": len(aligned), "aligned_points": aligned,
            "benchmark": None, "benchmark_result": "UNKNOWN_NO_ALIGNED_VALID_BENCHMARK",
            "aligned_observation_method": "Only snapshots with identical UTC observation times may be compared; missing points are not imputed."},
        "limitations": ["Observed drawdown uses saved snapshots and is not intraday drawdown.",
            "Missing prices are not carried forward or filled with synthetic values.",
            "A shared symbol is not independent evidence that one model is superior.",
            "No forced sale is recorded at period end; holdings retain their last evidenced mark.",
            "Costs are included only when evidenced by saved fill-event details.",
            "Price market date and mark recording time are separate; an older market date is labeled stale."],
        "source_run_count": len(observations)}
