"""Phase-1 point-in-time backtest runner (infrastructure + untuned baseline).

Reuses analytics_canonical_v1 for all metrics/scores. File-based deterministic
artifacts (no production/analytics writes). Forward returns are computed only after
the full signal snapshot set is frozen.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(BASE / "analytics_canonical_v1"))
sys.path.insert(0, str(BASE / "migration_tools"))

from config import BacktestConfig, frozen_model_identifiers, SCORE_VERSION  # noqa: E402
from calendar import TradingCalendar, rebalance_dates  # noqa: E402
from market_data import load_price_store  # noqa: E402
import risk_model  # noqa: E402
from snapshot_builder import build_snapshot, snapshot_stable_payload  # noqa: E402
from universe import evaluate_universe, track_changes  # noqa: E402
from forward_returns import compute_forward_returns, forward_return  # noqa: E402
from portfolio_simulator import select_top, simulate, simulate_corrected  # noqa: E402
import diagnostics as DG  # noqa: E402
from assess_readiness import FACTOR_SOURCE  # noqa: E402


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _write_csv(path: Path, rows, fieldnames=None):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})


def run(cfg: BacktestConfig | None = None, outdir: Path | None = None,
        simulator: str = "auto") -> dict:
    """simulator: "auto" (default, unchanged) | "simple" | "corrected".

    "corrected" is the Phase-2 cash-aware wealth-path policy and is the only one
    that honours per-member weights; the weighting validation uses it for every
    scheme so the comparison is apples-to-apples.
    """
    cfg = cfg or BacktestConfig()
    outdir = outdir or (HERE / "output")
    outdir.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    price_store = load_price_store()
    cal = TradingCalendar(price_store.dates)
    start = dt.date.fromisoformat(cfg.start_date)
    end = dt.date.fromisoformat(cfg.end_date)
    reb_dates = rebalance_dates(cal, cfg.rebalance_freq, start, end)
    print("rebalance dates:", len(reb_dates), reb_dates[0] if reb_dates else None, reb_dates[-1] if reb_dates else None)

    # ---- Phase A: freeze signals (no forward returns) ----
    rebalances = []
    snapshot_rows = []
    universe_rows = []
    prev_ids = []
    for T in reb_dates:
        snap = build_snapshot(T)
        exec_date = cal.next_trading_day(T)
        uni = evaluate_universe(snap["signals"], price_store, exec_date)
        tradable = uni["tradable"]
        selected = select_top(tradable, cfg.portfolio_mode, cfg.top_n, cfg.top_pct)
        rebalances.append({"date": T, "execution_date": exec_date, "tradable": tradable, "selected": selected})
        ch = track_changes(prev_ids, [s["company_id"] for s in tradable])
        prev_ids = [s["company_id"] for s in tradable]
        universe_rows.append({"date": T, "execution_date": exec_date,
                              "eligible_universe": uni["eligible"], "with_security": uni["with_security"],
                              "tradable": len(tradable), "excluded": len(uni["excluded"]),
                              "additions": len(ch["additions"]), "removals": len(ch["removals"]),
                              "scored_selected": len(selected)})
        for s in tradable:
            r = dict(s)
            r["signal_date"] = T
            snapshot_rows.append(r)

    # ---- Phase B: forward returns (after freeze) ----
    all_tradable_signals = [{"company_id": s["company_id"], "security_id": s["security_id"],
                             "symbol": s.get("symbol"), "signal_date": s["signal_date"]}
                            for s in snapshot_rows]
    fwd_rows = compute_forward_returns(price_store, cal.dates, all_tradable_signals, list(cfg.horizons))
    fwd_by_key = {(r["company_id"], str(r["signal_date"])): r for r in fwd_rows}

    # ---- Phase C: portfolio (rebalance-to-rebalance holding) ----
    port_rebalances = []
    weighted_info = []
    for i, rb in enumerate(rebalances):
        if i + 1 >= len(rebalances):
            break
        entry = rb["execution_date"]
        exit_ = rebalances[i + 1]["execution_date"]
        def hret(s):
            return forward_return(price_store, s["security_id"], entry, exit_)
        sel = [{"company_id": s["company_id"], "ret": hret(s)} for s in rb["selected"]]
        if cfg.weighting != "equal":
            # PIT risk weighting: only closes on/before the signal date T are used.
            wmap, winfo = risk_model.weights_for(price_store, rb["selected"], rb["date"], cfg.weighting)
            for m in sel:
                m["weight"] = wmap.get(m["company_id"], 0.0)
            weighted_info.append({"date": str(rb["date"]), **winfo})
        bench = [{"company_id": s["company_id"], "ret": hret(s)} for s in rb["tradable"]]
        port_rebalances.append({"date": rb["date"], "execution_date": entry,
                                "selected": sel, "benchmark": bench})
    use_corrected = simulator == "corrected" or (simulator == "auto" and cfg.weighting != "equal")
    if use_corrected:
        port_rows, port_summary, _contrib = simulate_corrected(port_rebalances, cfg.cost_bps_per_side)
    else:
        port_rows, port_summary = simulate(port_rebalances, cfg.cost_bps_per_side)

    # ---- Phase D: cross-sectional diagnostics on primary horizon ----
    primary = 21
    cs_rebalances = []
    for rb in rebalances:
        cs = []
        for s in rb["tradable"]:
            fr = fwd_by_key.get((s["company_id"], str(rb["date"])))
            cs.append({"company_id": s["company_id"], "symbol": s.get("symbol"),
                       "quant_score": s["quant_score"], "n_factors_available": s["n_factors_available"],
                       "factor_rank": s["factor_rank"], "ret": fr.get(f"ret_{primary}") if fr else None,
                       "dq_flags": s.get("dq_flags"), "uses_report_chain": s.get("uses_report_chain"),
                       "category_available": s.get("category_available")})
        cs_rebalances.append({"date": rb["date"], "cross_section": cs})

    ic_rows = DG.ic_by_date(cs_rebalances)
    ic_sum = DG.ic_summary(ic_rows)
    q_rows, q_sum = DG.quantile_diagnostics(cs_rebalances, cfg.quantile_buckets)
    factor_rows = DG.factor_ic(cs_rebalances, list(FACTOR_SOURCE.keys()))
    miss_rows, miss_sum = DG.missingness_diagnostics(cs_rebalances, cfg.coverage_buckets[0], cfg.coverage_buckets[1])
    time_rows = DG.time_segments(ic_rows)
    # factor coverage distribution
    cov_dist = {}
    for s in snapshot_rows:
        cov_dist[s["n_factors_available"]] = cov_dist.get(s["n_factors_available"], 0) + 1
    dq_counts = {}
    chain = 0
    source_absent = 0
    for s in snapshot_rows:
        for f in s.get("dq_flags", []):
            dq_counts[f] = dq_counts.get(f, 0) + 1
        if s.get("uses_report_chain"):
            chain += 1
        if s.get("n_factors_available", 0) <= cfg.coverage_buckets[0]:
            source_absent += 1

    # ---- hashes / manifest ----
    signal_hash = _sha([snapshot_stable_payload({"signals": [s for s in snapshot_rows if str(s["signal_date"]) == str(rb["date"])],
                                                 "universe_stats": {}}) for rb in rebalances])
    fwd_hash = _sha(fwd_rows)
    port_hash = _sha(port_rows)
    summary = {"config": cfg.__dict__, "frozen_model": frozen_model_identifiers(),
               "date_range": {"start": cfg.start_date, "end": cfg.end_date,
                              "actual_first_rebalance": str(reb_dates[0]) if reb_dates else None,
                              "actual_last_rebalance": str(reb_dates[-1]) if reb_dates else None},
               "n_rebalance_dates": len(reb_dates),
               "n_signal_observations": len(snapshot_rows),
               "ic": ic_sum, "quantile": q_sum, "missingness": miss_sum,
               "factor_coverage_distribution": dict(sorted(cov_dist.items())),
               "dq_flag_counts": dq_counts,
               "report_chain_signals": chain,
               "low_coverage_signals": source_absent,
               "portfolio": port_summary,
               "time_segments": time_rows,
               "return_convention": cfg.return_convention,
               "corporate_actions_available": False,
               "hashes": {"signal_snapshot": signal_hash, "forward_returns": fwd_hash,
                          "portfolio_path": port_hash, "config": cfg.hash()}}
    summary_hash = _sha({k: v for k, v in summary.items() if k != "hashes"})
    summary["hashes"]["summary"] = summary_hash

    # ---- artifacts ----
    _write_csv(outdir / "rebalance_snapshots.csv", universe_rows)
    _write_csv(outdir / "signal_snapshot.csv", snapshot_rows,
               fieldnames=["signal_date", "company_id", "security_id", "symbol", "quant_score",
                           "growth_score", "profitability_score", "valuation_score", "market_score",
                           "data_quality_score", "n_factors_available", "uses_report_chain", "dq_flags"])
    _write_csv(outdir / "forward_returns.csv", fwd_rows)
    _write_csv(outdir / "factor_diagnostics.csv", factor_rows)
    _write_csv(outdir / "quantile_diagnostics.csv", q_rows)
    _write_csv(outdir / "missingness_diagnostics.csv", miss_rows)
    _write_csv(outdir / "portfolio_returns.csv", port_rows)
    _write_csv(outdir / "turnover.csv", [{"date": r["date"], "turnover": r["turnover"],
                                          "entered": r["entered"], "exited": r["exited"]} for r in port_rows])
    (outdir / "summary_metrics.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (outdir / "run_manifest.json").write_text(json.dumps({
        "score_version": SCORE_VERSION,
        "implementation_revision": frozen_model_identifiers()["implementation_revision"],
        "config_hash": cfg.hash(), "summary_hash": summary_hash,
        "frozen_model": frozen_model_identifiers()}, indent=2, default=str), encoding="utf-8")

    print("signals:", len(snapshot_rows), "IC mean:", ic_sum.get("mean_ic"),
          "port cum:", port_summary["portfolio"].get("cumulative_return"),
          "bench cum:", port_summary["benchmark"].get("cumulative_return"),
          "summary_hash:", summary_hash)
    return summary


if __name__ == "__main__":
    run()
