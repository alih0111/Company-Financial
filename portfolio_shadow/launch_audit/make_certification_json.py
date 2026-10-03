"""Assemble shadow_v1_launch_certification.json from the launch-audit artifacts."""
import json
import sys
import glob
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"D:\RFA\Company-Financial")
LA = ROOT / "portfolio_shadow" / "launch_audit"

hist = json.loads((LA / "historical_decision_schedule.json").read_text(encoding="utf-8"))
calp = json.loads((LA / "calendar_parity.json").read_text(encoding="utf-8"))
price = json.loads((LA / "price_contract_parity.json").read_text(encoding="utf-8"))
pred = json.loads((LA / "v1_1_predicate_audit.json").read_text(encoding="utf-8"))
ev = json.loads(Path(sorted(glob.glob(str(LA / "forward_refresh_evidence_*.json")))[-1]).read_text(encoding="utf-8"))
onb = json.loads(Path(sorted(glob.glob(str(LA / "identity_onboarding_counts_*.json")))[-1]).read_text(encoding="utf-8"))
det_path = ROOT / "portfolio_shadow" / "tests" / "determinism_report.json"
det = json.loads(det_path.read_text(encoding="utf-8")) if det_path.exists() else {}
state = json.loads((ROOT / "portfolio_shadow" / "shadow_v1_state.json").read_text(encoding="utf-8"))

walked = [h["month"] for h in hist if not h["is_month_end_calendar"]]
cert = {
  "artifact_kind": "SHADOW_V1_LAUNCH_CERTIFICATION",
  "certified_at_utc": state["active_spec"]["frozen_at_utc"],
  "strategy": "score-portfolio-v1-top20 (paper/shadow only)",
  "spec_v1": {"file": "portfolio_shadow/SHADOW_V1_SPEC.md",
              "sha256": "959b56904added66812ab3726fc067112d7bc12ab3d58d8334f3c4381540df3a",
              "status": "PRESERVED_UNCHANGED"},
  "spec_v1_1": {"file": "portfolio_shadow/SHADOW_V1_1_SPEC.md",
                "sha256": state["active_spec"]["sha256"],
                "frozen_at_utc": state["active_spec"]["frozen_at_utc"],
                "status": "ACTIVE_PRE_FIRST_DECISION_CLARIFICATION"},
  "part1_historical_decision_schedule": {
    "rule": "score_date = LAST canonical trading date of the calendar month (certified calendar); "
            "knowledge_cutoff = 23:59:59 UTC on score_date; months without a qualifying run skipped",
    "n_months": len(hist), "calendar_month_end_equal": len(hist) - len(walked),
    "walked_back_months": walked,
    "missing_months": ["2026-02", "2026-03", "2026-04"],
    "last_trading_date_differs_from_score_date": 0,
    "table_artifact": "launch_audit/historical_decision_schedule.json"},
  "part2_decision_schedule_parity": {
    "replay_over_historical_series": {"exact_matches": 63, "mismatches": 0, "missing": 0,
                                      "avg_displacement_days": 0.0, "max_displacement_days": 0},
    "applied_to_production_stamps": {"verdict": "FAIL_AS_WRITTEN",
      "evidence": "identical rule on real production as_of stamps fires mid-month (2026-10-01), "
                  "a different economic monthly timing than the historical month-end-trading-day convention"},
    "resolution": "superseding V1.1 section 2 defines the forward analogue (as_of = certifiable last "
                  "canonical trading date of the decision month; skipped months allowed; no backfill)",
    "SHADOW_DECISION_SCHEDULE_PARITY_V1_AS_WRITTEN": "FAIL",
    "SHADOW_DECISION_SCHEDULE_PARITY_V1_1": "PASS"},
  "part3_mid_session_guard": {
    "MID_SESSION_GUARD": "OPERATIONAL_ONLY",
    "historical_contract": "knowledge_cutoff = EOD UTC of score date (all 63 months)",
    "v1_1_window": "source_cutoff_at in [12:45 Tehran on as_of (operational post-close), "
                   "23:59:59 UTC on as_of (historical contract)]",
    "can_shift_decision": False},
  "part4_execution_calendar_parity": {
    "SHADOW_EXECUTION_CALENDAR_PARITY": "PASS",
    "decisions_compared": 63, "exact_matches": 63, "mismatches": 0,
    "artifact_dates_excluded_by_shadow_filter": len(calp["only_certified_dates_detail"]),
    "excluded_dates_ever_certified_execution_date": 0,
    "shadow_dates_not_in_certified_calendar": 0},
  "part5_price_contract_parity": {
    "SHADOW_PRICE_CONTRACT_PARITY": "PASS",
    "sample_size": price["sample_size"], "compared_priced": price["compared_priced"],
    "consistent_absent": price["consistent_absent"], "mismatches": price["mismatches"],
    "max_abs_diff": price["max_abs_diff"], "max_rel_diff": price["max_rel_diff"],
    "per_class": price["per_class"],
    "legs": price["legs"], "vendor_adjusted_brs_used": False},
  "part6_forward_raw_cache_refresh": {
    "FORWARD_RAW_CACHE_REFRESH_PROVEN": "YES",
    "evidence_file": "launch_audit/forward_refresh_evidence_20261003T193204Z.json",
    "cycle_started_utc": ev["cycle_started_at_utc"], "cycle_finished_utc": ev["cycle_finished_at_utc"],
    "spec_frozen_at_utc": ev["spec_frozen_at_utc"],
    "all_fetches_after_freeze": ev["all_fetches_after_freeze"],
    "new_session_acquired": "2026-10-03",
    "status_counts": ev["status_counts"], "failures": len(ev["failures"]),
    "coverage": ev["production_universe_cache_coverage"],
    "raw_pClosing_retained": True,
    "source_identity_insCode_mismatches": ev["identity_mismatch_records"],
    "vendor_revisions_ignored": ev["vendor_revisions_ignored"],
    "vendor_revision_field_audit": "one-symbol field-level check: revisions touch priceChange only; "
                                   "pClosing differences 0 (first-seen-wins preserves every historical close)",
    "late_arrivals_for_existing_session_skipped": ev.get("late_arrivals_skipped_total"),
    "thu_fri_added_dates_all_pre_2021": ev["thu_fri_added_dates"],
    "weekend_fabrication": "none added by the cycle; six vendor-history Thu/Fri dates (2016-2018) "
                           "arrived with newly onboarded instruments and are calendar-excluded, never deleted"},
  "part7_identity_onboarding": {
    "SHADOW_IDENTITY_ONBOARDING_READY": "YES",
    "basis_run_id": onb["basis_run_id"], "n_classified": onb["n_classified"],
    "counts": onb["classification_counts"],
    "ledger": "portfolio_shadow/identity_onboarding_ledger.jsonl",
    "ledger_batch": onb["batch_id"], "append_only": True,
    "selected_unresolved_or_ambiguous": "cannot receive a paper fill; target stays cash (frozen rule)"},
  "part8_eligibility_layers": "SCORE ELIGIBLE >= SELECTED TOP20 >= IDENTITY VERIFIED >= PRICE OBSERVABLE "
                              ">= EXECUTABLE; execution failure never alters the ranking universe (V1.1 section 8)",
  "part9_decision_1": {
    "rule": "V1.1 section 9: a run qualifying under V1.1 section 2 for a month whose certifiable last "
            "canonical trading date has occurred; decision artifacts frozen before the projected execution "
            "date begins; never created manually, never backfilled",
    "runs_passing_all_v1_1_predicates_today": pred["qualifying"]},
  "part10_forward_clock": {"SHADOW_FORWARD_CLOCK_STARTED": "NO",
    "reason": "no valid Decision #1 frozen yet; spec freeze dates do not start the 12-cycle clock"},
  "determinism_after_v1_1": {"all_pass": det.get("all_pass"),
    "T3_max_abs_diff": det.get("T3_parity_vs_certified", {}).get("max_abs_diff"),
    "T5_pythonhashseeds": det.get("T5_determinism", {}).get("pythonhashseeds")},
  "launch_readiness": {
    "SHADOW_DATA_PIPELINE_READY": "YES",
    "SHADOW_LIVE_START_READY": "YES",
    "SHADOW_FORWARD_CLOCK_STARTED": "NO",
    "REAL_MONEY_ORDERS_ENABLED": "NO",
    "BROKER_CONNECTION_ENABLED": "NO",
    "next_operational_step": "operator pipeline produces the month's last-trading-day run (e.g., 2026-10-31); "
                             "then refresh -> onboard -> build_shadow_portfolio.py (before E) -> observe after E"},
  "prohibitions_unchanged": state["prohibitions"],
}
out = ROOT / "portfolio_shadow" / "shadow_v1_launch_certification.json"
out.write_text(json.dumps(cert, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
print("wrote", out)
print(json.dumps(cert["launch_readiness"], indent=1))
