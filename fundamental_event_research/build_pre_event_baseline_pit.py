"""PRE-EVENT UI BASELINE from the PIT-correct panel v2 (tasks 9/10/11).

For every eligible Fundamental Event V1.1 publication (V1.1 eligibility + the frozen
one-security-per-signal-date rule), select the latest PIT-correct UI snapshot satisfying:

    knowledge_cutoff  <  event published_at   (instant comparison)

No outcome columns. No staleness cutoff optimization. No performance computation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "fundamental_event_research"
PANEL = ROOT / "ui_score_research" / "ui_score_historical_pit_v2" / "ui_score_historical_pit_v2.jsonl"
ART = HERE / "monthly_sales_events_universe_v1_1.parquet"
OUT = HERE / "pre_event_ui_baseline_pit.parquet"
R = {"coverage": {}, "age": {}, "fe6": {}, "artifacts": {}}


def main() -> int:
    panel = pd.read_json(PANEL, lines=True,
                         dtype={"security_id": str, "symbol": str})
    panel = panel[["as_of", "knowledge_cutoff", "security_id", "symbol",
                   "ui_score", "data_quality_score"]].copy()
    panel["as_of_ts"] = pd.to_datetime(panel.as_of)
    panel["cutoff_ts"] = pd.to_datetime(panel.knowledge_cutoff, utc=True)
    panel = panel.dropna(subset=["ui_score"]).sort_values(["security_id", "as_of_ts"])
    by_sec = {s: (g.security_id.iloc[0], g) for s, g in panel.groupby("symbol")}

    art = pd.read_parquet(ART)
    el = art[art.event_eligible].copy()
    # frozen one-security-per-signal-date rule (identical to the gates audit):
    # keep latest published_at per (signal_entry_date, security); exact ties -> exclude
    kept_idx = []
    tie_groups = 0
    for _, g in el.groupby(["signal_entry_date", "security_id"]):
        if len(g) == 1:
            kept_idx.append(g.index[0])
            continue
        t = g.published_at.astype("int64")
        if t.nunique() == 1:
            tie_groups += 1
            continue
        kept_idx.append(g.sort_values("published_at").index[-1])
    el = el.loc[sorted(kept_idx)]
    print(f"eligible events after dedup rule: {len(el)} (tie groups excluded: {tie_groups})")

    rows = []
    for r in el.itertuples():
        pub = r.published_at.to_pydatetime() if hasattr(r.published_at, "to_pydatetime") else r.published_at
        g = by_sec.get(r.symbol)
        sel = None
        if g is not None:
            cand = g[1][g[1].cutoff_ts < pd.Timestamp(pub)]
            if len(cand):
                sel = cand.iloc[-1]
        rows.append({
            "event_id": r.event_id, "security_id": r.security_id, "symbol": r.symbol,
            "period_end": r.period_end, "published_at": r.published_at,
            "signal_entry_date": r.signal_entry_date,
            "ui_baseline_score": float(sel.ui_score) if sel is not None else None,
            "ui_baseline_as_of": str(sel.as_of)[:10] if sel is not None else None,
            "ui_baseline_cutoff": str(sel.knowledge_cutoff) if sel is not None else None,
            "ui_baseline_age_days": ((pd.Timestamp(r.tehran_date) - sel.as_of_ts).days
                                     if sel is not None else None),
            "ui_baseline_data_quality": float(sel.data_quality_score) if sel is not None else None,
        })
    b = pd.DataFrame(rows)
    b.to_parquet(OUT, compression="zstd", index=False)

    have = b.ui_baseline_score.notna()
    qual_dates = set(b.signal_entry_date.value_counts()[lambda s: s >= 10].index)
    on_qual = b.signal_entry_date.isin(qual_dates)
    ages = b.loc[have, "ui_baseline_age_days"].astype(float)
    fe6 = b[have]
    fe6_by_date = fe6.signal_entry_date.value_counts()
    R["coverage"] = {
        "eligible_events_total": int(len(b)),
        "valid_pit_baseline": int(have.sum()),
        "missing_baseline": int((~have).sum()),
        "coverage_pct": round(float(have.mean()) * 100, 2),
        "events_on_qualifying_dates": int(on_qual.sum()),
        "events_on_qualifying_dates_with_baseline": int((on_qual & have).sum()),
        "qualifying_events_coverage_pct": round(float((on_qual & have).sum() / max(int(on_qual.sum()), 1)) * 100, 2),
        "tie_groups_excluded_by_dedup_rule": tie_groups,
    }
    R["age"] = {
        "median": float(ages.median()), "p75": float(ages.quantile(0.75)),
        "p90": float(ages.quantile(0.90)), "max": float(ages.max()),
        "share_le_31d": round(float((ages <= 31).mean()), 4),
        "share_32_62d": round(float(((ages >= 32) & (ages <= 62)).mean()), 4),
        "share_gt_62d": round(float((ages > 62).mean()), 4),
        "note": "diagnostic only; no staleness cutoff optimized",
    }
    R["fe6"] = {
        "identical_row_events": int(len(fe6)),
        "distinct_entry_dates": int(fe6_by_date.size),
        "qualifying_dates_ge10_identical_rows": int((fe6_by_date >= 10).sum()),
        "events_on_fe6_qualifying_dates": int(fe6_by_date[fe6_by_date >= 10].sum()),
        "symbols": int(fe6.symbol.nunique()),
        "adequacy_rule": ">=24 qualifying identical-row dates AND >=500 identical-row events (a priori, mirrors FE1)",
        "FE6_PREOUTCOME_SAMPLE_ADEQUATE": bool((fe6_by_date >= 10).sum() >= 24 and len(fe6) >= 500),
    }
    R["artifacts"] = {"baseline_parquet": str(OUT), "panel_source": str(PANEL)}
    (HERE / "pre_event_ui_baseline_pit.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(R, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
