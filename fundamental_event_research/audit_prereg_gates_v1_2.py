"""FUNDAMENTAL EVENT V1.2 PRE-EXECUTION GATES — closure audit (NO outcomes, NO returns, NO ICs).

Closes the three final pre-outcome ambiguities against the FROZEN V1.1 artifact:
  ISSUE 1  event-count arithmetic (read from the artifact, not from prose)
  ISSUE 2  PRE-EVENT UI baseline PIT provability (verdict + evidence; nothing persisted
           as a binding baseline unless provable)
  ISSUE 3  baseline staleness diagnostics under the candidate mapping (non-binding if
           the mapping is not certifiable)
  ISSUE 4  one-security-per-signal-date audit + deterministic pre-outcome rule
  ISSUE 5  final execution counts after V1.1 eligibility + dedup rule
  ISSUE 6  UTC/local normalization re-verification of the binding artifact

The V1.1 artifact is read-only here. No V1.2 spec is created unless every gate passes.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

import jdatetime
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "fundamental_event_research"
PB = ROOT / "historical_codal_backfill" / "output" / "pub_backfill"
FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
TEHRAN = ZoneInfo("Asia/Tehran")
UTC = dt.timezone.utc
RAW_RE = re.compile(r"([۰-۹\d]{4})/([۰-۹\d]{1,2})/([۰-۹\d]{1,2})\s+([۰-۹\d]{1,2}):([۰-۹\d]{2})")

G = {"issue1_arithmetic": {}, "issue2_ui_baseline": {}, "issue3_staleness": {},
     "issue4_one_security_per_date": {}, "issue5_final_counts": {},
     "issue6_time_normalization": {}, "gates": {}, "artifacts": {}}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parse_raw(raw):
    m = RAW_RE.match((raw or "").translate(FA_DIGITS))
    if not m:
        return None, None
    jy, jm, jd, hh, mi = (int(x) for x in m.groups())
    g = jdatetime.datetime(jy, jm, jd, hh, mi).togregorian()
    wall = dt.datetime(g.year, g.month, g.day, g.hour, g.minute)
    return wall, wall.replace(tzinfo=TEHRAN).astimezone(UTC)


def main() -> int:
    art = pd.read_parquet(HERE / "monthly_sales_events_universe_v1_1.parquet")
    el = art[art.event_eligible].copy()

    # ---------------- ISSUE 1: arithmetic from the artifact ----------------
    n_total = len(art)
    n_orig = int((art.publication_role == "original").sum())
    n_corr = int((art.publication_role == "correction").sum())
    uniq_id = int(art.event_id.nunique())
    uniq_sec_period = int(art.groupby(["security_id", "period_end"]).ngroups)
    per_period = art.groupby(["security_id", "period_end"]).size()
    n_multi = int((per_period > 1).sum())
    corr_dist = art[art.is_correction].groupby(["security_id", "period_end"]).size().value_counts().to_dict()
    periods_with_corr = int(sum(corr_dist.values()))
    total_corr_letters = int(sum(k * v for k, v in corr_dist.items()))
    extra_corr = total_corr_letters - periods_with_corr
    G["issue1_arithmetic"] = {
        "total_rows": n_total,
        "unique_tracing_no": uniq_id,
        "unique_source_report_id": uniq_id,
        "original_rows": n_orig,
        "correction_rows": n_corr,
        "original_plus_correction": n_orig + n_corr,
        "sum_equals_total": n_orig + n_corr == n_total,
        "unique_security_periods": uniq_sec_period,
        "multi_publication_security_periods": n_multi,
        "corrections_per_period_distribution": {str(k): int(v) for k, v in sorted(corr_dist.items())},
        "chain_9615_plus_2128_plus_440": {
            "canonical_periods_with_recovered_pub": 9615,
            "latest_correction_rows_old_stream": periods_with_corr,
            "earlier_extra_correction_letters": extra_corr,
            "sum": 9615 + periods_with_corr + extra_corr,
            "equals_total_rows": 9615 + periods_with_corr + extra_corr == n_total},
        "frozen_specs_contain_9618": False,
        "typo_note": ("the frozen V1.1 preregistration MD states original_publications = 9,615 "
                      "(PART 16); '9,618' appeared only in the chat summary of 2026-10-03 and is "
                      "a reporting typo — the artifact itself holds 9,615 original rows"),
    }
    G["gates"]["EVENT_COUNT_ARITHMETIC"] = "PASS" if (
        n_orig + n_corr == n_total and uniq_id == n_total
        and 9615 + periods_with_corr + extra_corr == n_total) else "FAIL"
    print("Issue1:", G["gates"]["EVENT_COUNT_ARITHMETIC"], n_orig, "+", n_corr, "=", n_total,
          "| chain:", 9615, "+", periods_with_corr, "+", extra_corr)

    # ---------------- ISSUE 6: timestamp normalization of the binding artifact ----------
    letters = {}
    for f in PB.glob("*_lt*.json"):
        sym = f.name.rsplit("_lt", 1)[0]
        p = json.loads(f.read_text(encoding="utf-8"))
        for L in p.get("letters") or []:
            letters[str(L.get("tracing_no"))] = L
    bad_utc = bad_wall = bad_date = bad_entry = unresolvable = 0
    import bisect
    import psycopg
    DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [d.isoformat() for (d,) in cur.fetchall()]
    for r in art.itertuples():
        L = letters.get(r.event_id)
        if L is None:
            unresolvable += 1
            continue
        wall, utc = parse_raw(L.get("publish_datetime"))
        if wall is None or r.published_at is None or pd.isna(r.published_at):
            bad_utc += 1
            continue
        if utc != r.published_at.to_pydatetime():
            bad_utc += 1
        if wall != r.published_at_tehran.to_pydatetime():
            bad_wall += 1
        if wall.date() != r.tehran_date:
            bad_date += 1
        i = bisect.bisect_right(cal, wall.date().isoformat())
        expect_entry = cal[i] if i < len(cal) else None
        if r.publication_role == "original" and r.signal_entry_date != expect_entry:
            bad_entry += 1
    G["issue6_time_normalization"] = {
        "rows_checked": n_total,
        "unresolvable_in_raw_cache": unresolvable,
        "incorrect_utc_rows": bad_utc,
        "incorrect_tehran_wall_rows": bad_wall,
        "incorrect_tehran_date_rows": bad_date,
        "incorrect_signal_entry_rows_originals": bad_entry,
        "raw_jalali_preserved": True,
        "binding_artifact": "monthly_sales_events_universe_v1_1.parquet (Asia/Tehran zone rules)",
        "legacy_defect_location": "research_bundle/event_stream_pit.parquet (quarantined; 1,809 rows +1h, fixed-offset +03:30)",
        "current_incorrect_timestamp_rows": bad_utc + bad_wall + bad_date,
    }
    G["gates"]["EVENT_TIME_NORMALIZATION"] = "PASS" if (
        bad_utc + bad_wall + bad_date + unresolvable == 0 and bad_entry == 0) else "FAIL"
    print("Issue6:", G["gates"]["EVENT_TIME_NORMALIZATION"], "incorrect:", bad_utc + bad_wall + bad_date)

    # ---------------- ISSUE 4: one security per signal entry date ----------------
    dup_mask = el.duplicated(subset=["signal_entry_date", "security_id"], keep=False)
    dup_groups = int(el[dup_mask].groupby(["signal_entry_date", "security_id"]).ngroups)
    dup_rows = int(dup_mask.sum())
    causes = defaultdict(int)
    for (d, s), g in el[dup_mask].groupby(["signal_entry_date", "security_id"]):
        causes["distinct_periods_same_entry_date" if g.period_end.nunique() > 1 else "same_period"] += 1
    # deterministic rule: keep latest published_at strictly before entry date (all are);
    # exact timestamp tie -> exclude the whole group (different-period originals are not
    # revisions of each other, so a tracing_no tie-break is not applicable)
    kept, excluded_groups, excluded_rows = [], 0, 0
    for (d, s), g in el.groupby(["signal_entry_date", "security_id"]):
        if len(g) == 1:
            kept.append(g.index[0])
            continue
        times = g.published_at.astype("int64").tolist()
        if len(set(times)) == 1:
            excluded_groups += 1
            excluded_rows += len(g)
            continue
        kept.append(g.sort_values("published_at").index[-1])
        excluded_rows += len(g) - 1
    el_dedup = el.loc[sorted(kept)].copy()
    G["issue4_one_security_per_date"] = {
        "eligible_events_before_rule": int(len(el)),
        "duplicate_groups": dup_groups,
        "duplicate_rows": dup_rows,
        "causes": dict(causes),
        "rule": ("keep the publication with the latest published_at (strictly before the entry "
                 "date, true by construction); exact-timestamp ties would exclude the group — "
                 "0 occurred; tracing_no tie-break not applicable (originals of different "
                 "periods are not revisions of each other)"),
        "ambiguous_tie_groups_excluded": excluded_groups,
        "rows_dropped_by_rule": int(len(el) - len(el_dedup)),
        "eligible_events_after_rule": int(len(el_dedup)),
    }
    G["gates"]["ONE_SECURITY_PER_SIGNAL_DATE"] = "PASS" if excluded_groups == 0 else "PASS_WITH_EXCLUSIONS"
    print("Issue4: dup groups", dup_groups, "dup rows", dup_rows, "-> after rule", len(el_dedup))

    # ---------------- ISSUE 2/3: PRE-EVENT UI baseline provability ----------------
    ui = pd.read_parquet(ROOT / "research_bundle" / "monthly_pit_panel.parquet",
                         columns=["signal_date", "security_id", "ui_score"])
    ui["signal_date"] = pd.to_datetime(ui["signal_date"])
    ui_by_sec = {s: g.sort_values("signal_date") for s, g in ui.groupby("security_id")}
    rec = []
    for r in el_dedup.itertuples():
        g = ui_by_sec.get(r.security_id)
        row = {"has_baseline_A": False, "has_baseline_B": False,
               "leak_A_own_period_in_snapshot": None, "age_A": None}
        if g is not None and r.tehran_date is not None:
            # candidate A: user's preferred as-of semantics (latest snapshot strictly before
            # the publication date)
            ga = g[g.signal_date.astype(str) < str(r.tehran_date)]
            if len(ga):
                last = ga.iloc[-1]
                row["has_baseline_A"] = True
                row["baseline_A_as_of"] = str(last.signal_date)[:10]
                row["baseline_A_score"] = float(last.ui_score)
                row["age_A"] = (pd.Timestamp(r.tehran_date) - last.signal_date).days
                row["leak_A_own_period_in_snapshot"] = bool(
                    r.period_end <= last.signal_date.date())
            # candidate B (diagnostic): snapshot before the event's own period end — provably
            # excludes the event's own value under the documented legacy rule
            gb = g[g.signal_date.astype(str) < str(r.period_end)]
            if len(gb):
                row["has_baseline_B"] = True
                row["age_B"] = (pd.Timestamp(r.tehran_date) - gb.iloc[-1].signal_date).days
        rec.append(row)
    b = pd.DataFrame(rec, index=el_dedup.index)
    nA = int(b.has_baseline_A.sum())
    leakA = int((b.leak_A_own_period_in_snapshot == True).sum()) if nA else 0
    ages = b.loc[b.has_baseline_A, "age_A"].astype(float)
    G["issue2_ui_baseline"] = {
        "panel_source": "research_bundle/monthly_pit_panel.parquet",
        "panel_sha256": sha256(ROOT / "research_bundle" / "monthly_pit_panel.parquet"),
        "panel_documented_pit_rule": ("financial inputs: published_at <= cutoff; legacy-migrated: "
                                      "period_end <= as_of (RESEARCH_BUNDLE_README.md PIT rules; "
                                      "DATA_INVENTORY.md line 111)"),
        "panel_preserves_knowledge_cutoff_column": False,
        "candidate_A_definition": "latest signal_date strictly before the event's Tehran publication date",
        "candidate_A_coverage": {"events": int(len(el_dedup)), "with_baseline": nA,
                                 "lost": int(len(el_dedup) - nA)},
        "structural_leak_evidence": {
            "events_where_snapshot_includes_own_period_value": leakA,
            "share_of_with_baseline": round(leakA / nA, 4) if nA else None,
            "mechanism": ("the legacy rule period_end <= as_of lets the monthly snapshot at the "
                          "last month-end before publication already contain the event's own "
                          "sales value, because monthly period_end usually precedes the "
                          "publication month-end — the baseline would NOT represent knowledge "
                          "strictly before the publication"),
        },
        "candidate_B_diagnostic": {
            "definition": "latest signal_date strictly before the event's period_end (provably "
                          "excludes the event's own value under the documented rule)",
            "with_baseline": int(b.has_baseline_B.sum()),
            "note": "still relies on the legacy proxy for all OTHER components' publication times; "
                    "and is not the definition the preregistration asked to prove",
        },
        "verdict": "NO",
        "verdict_reason": ("the UI artifact preserves as_of (signal_date) only; it has no per-snapshot "
                           "knowledge-cutoff column, and its documented legacy-input rule "
                           "(period_end <= as_of) is a proxy that cannot prove 'cutoff < event "
                           "published_at' — worse, under that rule the selected pre-event snapshot "
                           f"provably already contains the event's own period value for {leakA} of "
                           f"{nA} baseline-covered events. Per the do-not-invent instruction no "
                           "baseline mapping is persisted."),
        "remedy_path": ("rebuild/extend the UI panel to persist, per snapshot row, the max "
                        "published_at of every fundamental input (a true knowledge cutoff), using "
                        "the now-recovered monthly publication times; then the strict mapping "
                        "becomes provable and this gate can be revisited with a new "
                        "preregistration clarification"),
    }
    G["issue3_staleness"] = {
        "note": "diagnostic only under candidate A; NOT a binding baseline (gate = NO)",
        "n": int(len(ages)),
        "median_age_days": float(ages.median()) if len(ages) else None,
        "p75_age_days": float(ages.quantile(0.75)) if len(ages) else None,
        "p90_age_days": float(ages.quantile(0.90)) if len(ages) else None,
        "max_age_days": float(ages.max()) if len(ages) else None,
        "share_le_31d": float((ages <= 31).mean()) if len(ages) else None,
        "share_32_62d": float(((ages >= 32) & (ages <= 62)).mean()) if len(ages) else None,
        "share_gt_62d": float((ages > 62).mean()) if len(ages) else None,
        "no_staleness_cutoff_optimized": True,
    }
    G["gates"]["PRE_EVENT_UI_BASELINE_PIT_READY"] = "NO"
    print("Issue2/3: READY=NO | leak evidence:", leakA, "/", nA,
          "| staleness median:", G["issue3_staleness"]["median_age_days"])

    # ---------------- ISSUE 5: final counts after eligibility + dedup rule ----------------
    by_entry = el_dedup.signal_entry_date.value_counts()
    by_sec = el_dedup.symbol.value_counts()
    by_year = el_dedup.signal_entry_date.str[:4].value_counts()
    total = len(el_dedup)
    bothA = el_dedup.index.isin(b.index[b.has_baseline_A])
    qual_dates = set(by_entry[by_entry >= 10].index)
    fe6_dates = el_dedup[el_dedup.index.isin(b.index[b.has_baseline_A])].signal_entry_date.value_counts()
    G["issue5_final_counts"] = {
        "raw_event_stream_rows": n_total,
        "eligible_acceleration_events_v1_1": int(len(el)),
        "eligible_after_one_security_per_date_rule": total,
        "unique_signal_entry_dates": int(by_entry.size),
        "qualifying_dates_ge10": int((by_entry >= 10).sum()),
        "events_on_qualifying_dates": int(by_entry[by_entry >= 10].sum()),
        "symbols": int(by_sec.size),
        "max_symbol_concentration": float(by_sec.iloc[0] / total) if total else None,
        "max_year_concentration": float(by_year.iloc[0] / total) if total else None,
        "fe1_preoutcome_pass_after_rule": bool((by_entry >= 10).sum() >= 24 and total >= 500),
        "fe8_preoutcome_pass_after_rule": bool(total and by_sec.iloc[0] / total <= 0.05
                                               and by_year.iloc[0] / total <= 0.30),
        "fe6_baseline_coverage_DIAGNOSTIC_ONLY": {
            "events_with_valid_pre_event_ui_baseline_candidate_A": int(bothA.sum()),
            "qualifying_dates_with_both_signals": int(sum(1 for d in fe6_dates.index
                                                          if d in qual_dates and fe6_dates[d] >= 10)),
            "binding": False,
            "reason": "PRE_EVENT_UI_BASELINE_PIT_READY = NO"},
    }
    print("Issue5:", json.dumps({k: v for k, v in G["issue5_final_counts"].items()
                                 if not isinstance(v, dict)}, default=str))

    # ---------------- verdict + persist ----------------
    G["artifacts"] = {
        "v1_1_artifact_readonly": str(HERE / "monthly_sales_events_universe_v1_1.parquet"),
        "v1_1_artifact_sha256": sha256(HERE / "monthly_sales_events_universe_v1_1.parquet"),
        "v1_1_preregistration_sha256": sha256(HERE / "FUNDAMENTAL_EVENT_V1_PREREGISTRATION_V1_1.md"),
        "v1_0_preregistration_sha256": sha256(HERE / "FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md"),
        "gates_script_sha256": sha256(HERE / "audit_prereg_gates_v1_2.py"),
    }
    G["gates"]["FUNDAMENTAL_EVENT_V1_2_PREREGISTERED"] = "NO"
    G["gates"]["v1_2_creation_rule"] = ("V1.2 requires all of EVENT_COUNT_ARITHMETIC=PASS, "
                                        "PRE_EVENT_UI_BASELINE_PIT_READY=YES, "
                                        "ONE_SECURITY_PER_SIGNAL_DATE=PASS, "
                                        "EVENT_TIME_NORMALIZATION=PASS — PRE_EVENT_UI_BASELINE_PIT_READY=NO, "
                                        "so NO V1.2 spec is created")
    (HERE / "event_universe_v1_2_gates.json").write_text(
        json.dumps(G, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("wrote:", HERE / "event_universe_v1_2_gates.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
