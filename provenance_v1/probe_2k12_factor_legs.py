"""READ-ONLY probe (step 2-K-12): why the 3 named Q factors are missing for the
partial-coverage symbols, and whether the blocking input exists in the store.

Reuses the existing production building blocks only:
  * compute_metrics.Engine  (SELECT-only metric engine)
  * pilot_v2_qvt.resolve_expense_ttm_channels / _expense_ttm_channel
    (the same within-report expense-TTM contract, PRE step-2-B-8 recovery)

Emits a JSON classification to provenance_v1/output/. It writes nothing to the
database, changes no formula/weight, and does not overwrite any artifact.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AN = HERE.parent / "canonical_postgres_v1_2_1" / "analytics_canonical_v1"
MT = HERE.parent / "canonical_postgres_v1_2_1" / "migration_tools"
for p in (str(AN), str(MT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import compute_metrics as CM  # noqa: E402
import expense_ttm_recovery as REC  # noqa: E402
import pilot_v2_qvt as PV  # noqa: E402
from common import load_env  # noqa: E402

AS_OF = dt.date(2026, 10, 8)
CUTOFF = dt.datetime(2026, 10, 8, 23, 59, 0, tzinfo=dt.timezone.utc)


def main() -> int:
    load_env()
    rank = json.loads(
        (HERE / "output" / "_ranking_2k11_live.json").read_text("utf-8"))
    ranked = {e["symbol"]: e for e in rank["ranked"]}
    partial = [e for e in rank["ranked"] if not e["full_coverage"]]
    cid_of = {e["symbol"]: e["company_id"] for e in rank["ranked"]}

    eng = CM.Engine(AS_OF, CUTOFF)
    eng.compute()
    rep_index = eng.report_index()
    durations, _fc = PV.fiscal_calendar_for(eng)
    # step 2-B-8 recovery, scoped read-only to the partial symbols only
    cids = sorted({e["company_id"] for e in partial})
    rec_results, rec_census = REC.recover_expense_order3(
        rep_index, durations, AS_OF, CUTOFF, company_ids=set(cids))
    channels, census = PV.resolve_expense_ttm_channels(
        eng, recovery=rec_results or None)

    out_rows = []
    for e in partial:
        cid = e["company_id"]
        m = eng.metrics.get(cid, {})
        ch = channels.get(cid, {})
        fc = (ch.get("finance_cost_ttm") or {})
        on = (ch.get("other_nonop_ttm") or {})
        rrec = (rec_results.get(cid) or {})
        out_rows.append({
            "symbol": e["symbol"],
            "rank": e["rank"],
            "q_covered_weight": e["q"]["covered_weight"],
            "t_covered_weight": e["t"]["covered_weight"],
            "cash_inputs": {
                "net_profit_ttm": m.get("net_profit_ttm"),
                "ocf_ttm": m.get("ocf_ttm"),
            },
            "finance_cost_ttm_state": fc.get("state"),
            "finance_cost_ttm_reason": fc.get("reason"),
            "other_nonop_ttm_state": on.get("state"),
            "other_nonop_ttm_reason": on.get("reason"),
            "recovery": {k: (v or {}).get("state")
                         for k, v in rrec.items()},
        })

    report = {
        "probe": "step 2-K-12 factor-leg classification (read-only)",
        "as_of": AS_OF.isoformat(),
        "cutoff": CUTOFF.isoformat(),
        "n_partial": len(partial),
        "note": ("states are POST step-2-B-8 recovery, scoped to the partial "
                 "symbols only; the recovery census is therefore scoped too. "
                 "A symbol still showing unresolved here has no recoverable "
                 "leg left in the current store/letter archive"),
        "census": census,
        "recovery_census": rec_census,
        "rows": out_rows,
    }
    dst = HERE / "output" / "_probe_2k12_factor_legs.json"
    dst.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("wrote", dst)
    for r in out_rows:
        sym = r["symbol"]
        q = r["q_covered_weight"]
        np_ = r["cash_inputs"]["net_profit_ttm"]
        ocf = r["cash_inputs"]["ocf_ttm"]
        print(f"{sym:10s} q={q:>3} t={r['t_covered_weight']:>3} | "
              f"fc={r['finance_cost_ttm_state']} | "
              f"on={r['other_nonop_ttm_state']} | "
              f"rec={r['recovery']} | "
              f"np_ok={np_ is not None} ocf_ok={ocf is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
