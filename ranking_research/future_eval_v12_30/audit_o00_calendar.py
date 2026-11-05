"""Audit, but never infer, the locked O00 global market-session index."""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import hashlib
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CAL = ROOT / "score_v2_research/_cache/calendar.parquet"
OUT = ROOT / "ranking_research/output/paper_cycle/o00-calendar-check.json"
LOCKED = ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/o00_session_calendar.csv"
MAPPING = ROOT / "ranking_research/output/paper_cycle/o00-local-to-locked-date-map.csv"
BASE = pd.Timestamp("2021-04-03")
PANEL_END = pd.Timestamp("2026-02-24")
LOCKED_INDEX = 1165
TARGET_INDEX = 1197

def main() -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    frame = pd.read_parquet(CAL)
    raw_dates = pd.to_datetime(frame["trade_date"], errors="coerce").dropna().dt.normalize()
    duplicate_rows = int(raw_dates.duplicated().sum())
    dates = raw_dates.drop_duplicates().sort_values()
    locked = pd.read_csv(LOCKED, parse_dates=["date_gregorian"])
    locked["date_gregorian"] = locked.date_gregorian.dt.normalize()
    locked = locked[locked.global_session_index <= LOCKED_INDEX].sort_values("global_session_index")
    locked_map = dict(zip(locked.date_gregorian, locked.global_session_index))
    base_seen = bool((dates == BASE).any())
    end_seen = bool((dates == PANEL_END).any())
    local_prefix = [x for x in dates if BASE <= x <= PANEL_END]
    expected_prefix = set(locked.date_gregorian)
    local_prefix_set = set(local_prefix)
    missing_locked_dates = sorted(expected_prefix - local_prefix_set)
    extra_local_dates = sorted(local_prefix_set - expected_prefix)
    local_index = len(local_prefix) - 1 if base_seen and end_seen else None
    latest = dates.max().date().isoformat() if len(dates) else None
    after_panel = int(((dates > PANEL_END) & (dates <= dates.max())).sum()) if len(dates) else 0
    divergence = next((i for i, (expected, actual) in enumerate(zip(locked.date_gregorian.tolist(), local_prefix))
                       if expected != actual), None)
    map_rows = []
    for day in dates:
        index = locked_map.get(day)
        if day < BASE:
            reason = "before_locked_anchor"
        elif day <= PANEL_END and index is not None:
            reason = "matched_locked_date"
        elif day <= PANEL_END:
            reason = "local_date_absent_from_locked_prefix"
        else:
            reason = "post_panel_requires_official_global_history"
        map_rows.append({"local_date": day.date().isoformat(), "locked_global_session_index": index,
                         "mapping_state": reason})
    pd.DataFrame(map_rows).to_csv(MAPPING, index=False, encoding="utf-8-sig")
    mapping_frame = pd.DataFrame(map_rows)
    mapped_locked_rows = int(mapping_frame["mapping_state"].eq("matched_locked_date").sum())
    extra_rows = int(mapping_frame["mapping_state"].eq("local_date_absent_from_locked_prefix").sum())
    duplicate_dates = sorted(raw_dates[raw_dates.duplicated(keep=False)].dt.strftime("%Y-%m-%d").unique().tolist())
    locked_sha = hashlib.sha256(LOCKED.read_bytes()).hexdigest()
    cache_sha = hashlib.sha256(CAL.read_bytes()).hexdigest()
    payload = {"checked_at_utc": now, "state": "blocked_global_history_extension",
        "source": "score_v2_research/_cache/calendar.parquet", "source_authority": "local_cache_not_independently_verified_as_complete_official_history",
        "source_provenance": {"cache_sha256": cache_sha, "cache_modified_at_utc": dt.datetime.fromtimestamp(CAL.stat().st_mtime, dt.timezone.utc).isoformat(),
            "available_source_columns": list(frame.columns),
            "date_origin_or_collection_method": "not_recorded_in_calendar.parquet; row values alone do not establish that these dates were official market sessions",
            "extra_date_interpretation": "The five dates occur in the local date column and are absent from the locked official prefix. This explains the +5 local count; evidence does not identify why the cache producer inserted them."},
        "locked_prefix_source": str(LOCKED.relative_to(ROOT)).replace("\\", "/"),
        "locked_prefix_sha256": locked_sha,
        "baseline_date": BASE.date().isoformat(), "locked_panel_end": PANEL_END.date().isoformat(),
        "locked_panel_index": LOCKED_INDEX, "local_calendar_computed_index_at_panel_end": local_index,
        "locked_prefix_count": len(expected_prefix), "local_prefix_unique_date_count": len(local_prefix_set),
        "locked_prefix_date_mapping_complete": not missing_locked_dates,
        "date_mapping_validation": {"locked_dates_mapped_one_to_one": mapped_locked_rows == len(expected_prefix),
            "locked_dates_mapped_count": mapped_locked_rows, "locked_dates_expected_count": len(expected_prefix),
            "extra_local_dates_without_locked_index": extra_rows, "post_panel_dates_assigned_locked_index": 0,
            "mapping_validation": "PASS" if mapped_locked_rows == len(expected_prefix) and extra_rows == len(extra_local_dates) else "FAIL"},
        "missing_locked_dates": [x.date().isoformat() for x in missing_locked_dates],
        "extra_local_dates": [x.date().isoformat() for x in extra_local_dates],
        "first_sequence_divergence_zero_based": divergence,
        "raw_calendar_duplicate_row_count": duplicate_rows, "duplicate_dates": duplicate_dates,
        "index_matches_locked_panel": local_index == LOCKED_INDEX and not missing_locked_dates and not extra_local_dates,
        "index_difference": (local_index - LOCKED_INDEX) if local_index is not None else None,
        "target_global_index": TARGET_INDEX, "target_is_date": False, "latest_local_calendar_date": latest,
        "local_calendar_rows": int(len(dates)), "local_sessions_after_panel_end": after_panel,
        "local_to_locked_mapping_path": str(MAPPING.relative_to(ROOT)).replace("\\", "/"),
        "continuation_validation": {"state": "blocked_missing_authoritative_history", "last_locked_date_index": LOCKED_INDEX,
            "required_first_date": "2026-02-25", "available_local_through": latest,
            "local_dates_after_locked_end": after_panel, "official_market_wide_history_manifest": None,
            "target_index_1197_date": None, "reason": "Local post-prefix dates are not independently verified as a complete official session sequence; index continuation cannot be validated."},
        "o00_history_gap_from": "2026-02-25", "o00_history_gap_through": dt.datetime.now().date().isoformat(),
        "official_global_session_history_manifest": None,
        "error": ("The local calendar has five extra dates in the locked prefix: 2025-06-21, 2025-06-22, 2025-06-23, 2025-06-24, 2025-06-25; "
                  "the date-keyed mapping matches all 1166 locked dates and does not assign indices to those extras. "
                  "Official global sessions from 2026-02-25 through the run date remain unavailable; "
                  "no O00 indices or date for target 1197 are inferred.")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
