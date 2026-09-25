"""Backtesting v1 Phase 2 — measurement hardening + coverage-bias control.

No model/weight/factor/missing-policy changes. Diagnostics only. File-based
deterministic artifacts. Reuses analytics_canonical_v1 for metrics/scores.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
for p in (str(HERE), str(BASE / "analytics_canonical_v1"), str(BASE / "migration_tools")):
    sys.path.insert(0, p)

from config import BacktestConfig, frozen_model_identifiers  # noqa: E402
from calendar import TradingCalendar, rebalance_dates  # noqa: E402
from market_data import load_price_store  # noqa: E402
from snapshot_builder import build_snapshot, snapshot_stable_payload  # noqa: E402
from universe import evaluate_universe  # noqa: E402
from forward_returns import compute_forward_returns, forward_return, resolve_execution_date  # noqa: E402
from portfolio_simulator import select_top, simulate_corrected  # noqa: E402
import diagnostics as DG  # noqa: E402
from assess_readiness import CATEGORY  # noqa: E402
from common import pg_pilot_conn  # noqa: E402

OUT = HERE / "output"
LOW_MAX, HIGH_MIN = 7, 15   # low <=7, medium 8..14, high >=15 (matches config coverage_buckets)
EXTREME = 0.25
SEED = 12345


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def wcsv(path, rows, fields=None):
    if not rows:
        (path).write_text("", encoding="utf-8")
        return
    fields = fields or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})


def stratum(n):
    return "low" if n <= LOW_MAX else ("high" if n >= HIGH_MIN else "medium")


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def bootstrap_ci(values, seed=SEED, n=1000, lo=2.5, hi=97.5):
    vals = [v for v in values if v is not None]
    if len(vals) < 3:
        return {"mean": mean(vals), "ci_low": None, "ci_high": None, "n": len(vals)}
    rng = random.Random(seed)
    means = []
    for _ in range(n):
        s = [vals[rng.randrange(len(vals))] for _ in range(len(vals))]
        means.append(sum(s) / len(s))
    means.sort()
    return {"mean": mean(vals), "ci_low": means[int(0.025 * n)], "ci_high": means[int(0.975 * n)], "n": len(vals)}


def ols2(rows):
    """rows: list of (y, x1, x2). Returns coefficients (b0,b1,b2) or None."""
    pts = [(y, x1, x2) for (y, x1, x2) in rows if None not in (y, x1, x2)]
    if len(pts) < 5:
        return None
    # normal equations for 3 params via Gaussian elimination
    import itertools
    X = [[1.0, x1, x2] for (_, x1, x2) in pts]
    Y = [y for (y, _, _) in pts]
    n = len(pts)
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(3)] for a in range(3)]
    XtY = [sum(X[i][a] * Y[i] for i in range(n)) for a in range(3)]
    # solve
    A = [row[:] + [XtY[i]] for i, row in enumerate(XtX)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(A[r][c]))
        if abs(A[p][c]) < 1e-12:
            return None
        A[c], A[p] = A[p], A[c]
        pv = A[c][c]
        A[c] = [v / pv for v in A[c]]
        for r in range(3):
            if r != c and A[r][c]:
                f = A[r][c]
                A[r] = [A[r][k] - f * A[c][k] for k in range(4)]
    return [A[i][3] for i in range(3)]


def market_revision_audit(pc):
    rows = []
    pc.execute("""
        SELECT security_id::text, trade_date, count(*) n,
               count(DISTINCT closing_price_rial) n_close,
               count(DISTINCT trade_value_rial) n_tval,
               count(DISTINCT adjustment_version) n_adj
        FROM market.price_observations
        GROUP BY 1,2 HAVING count(*) > 1
        ORDER BY n DESC""")
    for r in pc.fetchall():
        rows.append({"security_id": r[0], "trade_date": r[1], "n_obs": r[2],
                     "n_distinct_close": r[3], "n_distinct_trade_value": r[4],
                     "n_distinct_adjustment_version": r[5],
                     "pit_ambiguous": True})
    return rows


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = BacktestConfig()
    price_store = load_price_store()
    cal = TradingCalendar(price_store.dates)
    start = dt.date.fromisoformat(cfg.start_date)
    end = dt.date.fromisoformat(cfg.end_date)
    reb_dates = rebalance_dates(cal, cfg.rebalance_freq, start, end)
    print("rebalances:", len(reb_dates))

    # ---------- market revision audit ----------
    pg = pg_pilot_conn(autocommit=True)
    pc = pg.cursor()
    rev_rows = market_revision_audit(pc)
    total_keys = None
    default_sigma = None
    pc.execute("SELECT count(*) FROM market.price_observations")
    total_obs = pc.fetchone()[0]
    pc.execute("SELECT count(*) FROM (SELECT security_id,trade_date FROM market.price_observations GROUP BY 1,2) t")
    total_keys = pc.fetchone()[0]
    pc.execute("SELECT count(*) FROM (SELECT security_id,trade_date,count(DISTINCT closing_price_rial) c FROM market.price_observations GROUP BY 1,2 HAVING count(*)>1) t")
    conflicting = pc.fetchone()[0]
    wcsv(OUT / "market_revision_diagnostics.csv", rev_rows)

    # ---------- snapshots + universe + signals ----------
    rebalances = []
    cross = {}          # date -> list of signal dicts (tradable)
    snapshot_full = {}
    for T in reb_dates:
        snap = build_snapshot(T)
        exec_date = cal.next_trading_day(T)
        uni = evaluate_universe(snap["signals"], price_store, exec_date)
        tradable = uni["tradable"]
        selected = select_top(tradable, cfg.portfolio_mode, cfg.top_n, cfg.top_pct)
        rebalances.append({"date": T, "execution_date": exec_date, "tradable": tradable, "selected": selected})
        cross[T] = tradable
        snapshot_full[T] = snap
    print("snapshots built:", len(snapshot_full))

    # ---------- forward returns (after freeze) ----------
    all_sig = [{"company_id": s["company_id"], "security_id": s["security_id"],
                "symbol": s.get("symbol"), "signal_date": T}
               for T in reb_dates for s in cross[T]]
    fwd = compute_forward_returns(price_store, cal.dates, all_sig, list(cfg.horizons))
    fwd_by = {(r["company_id"], str(r["signal_date"])): r for r in fwd}
    wcsv(OUT / "forward_returns.csv", fwd)

    # attach returns to cross-section entries
    for T in reb_dates:
        for s in cross[T]:
            fr = fwd_by.get((s["company_id"], str(T)), {})
            s["ret_5"] = fr.get("ret_5"); s["ret_21"] = fr.get("ret_21"); s["ret_63"] = fr.get("ret_63")
            s["execution_date"] = fr.get("execution_date")

    # ---------- corrected portfolio path ----------
    port_rb = []
    for i, rb in enumerate(rebalances):
        if i + 1 >= len(rebalances):
            break
        entry = rb["execution_date"]; exit_ = rebalances[i + 1]["execution_date"]
        sel = [{"company_id": s["company_id"], "ret": forward_return(price_store, s["security_id"], entry, exit_)} for s in rb["selected"]]
        bench = [{"company_id": s["company_id"], "ret": forward_return(price_store, s["security_id"], entry, exit_)} for s in rb["tradable"]]
        port_rb.append({"date": rb["date"], "execution_date": entry, "exit_date": exit_,
                        "selected": sel, "benchmark": bench})
    port_rows, port_sum, contrib = simulate_corrected(port_rb, cfg.cost_bps_per_side)
    # contiguity: each interval's exit equals the next interval's entry (no overlap,
    # no gap, no double-counting of a market interval)
    contiguous = all(str(port_rb[i]["exit_date"]) == str(port_rb[i + 1]["execution_date"])
                     for i in range(len(port_rb) - 1)) if port_rb else True
    zero_tradable = [str(rb["date"]) for rb in rebalances if not rb["tradable"]]
    cash_intervals = [str(r["date"]) for r in port_rows if r["cash_interval"]]
    wcsv(OUT / "portfolio_returns.csv", port_rows)
    wcsv(OUT / "turnover.csv", [{"date": r["date"], "turnover": r["turnover"], "entered": r["entered"], "exited": r["exited"]} for r in port_rows])

    # cost grid
    cost_grid = []
    for bps in (0, 10, 25, 50):
        _, s, _ = simulate_corrected(port_rb, bps)
        cost_grid.append({"cost_bps_per_side": bps,
                          "gross_cumulative": s["portfolio"]["cumulative_return"],
                          "net_cumulative": s["portfolio_net"]["cumulative_return"],
                          "net_annualized": s["portfolio_net"]["annualized_return"],
                          "net_sharpe_like": s["portfolio_net"]["sharpe_like"]})
    wcsv(OUT / "cost_sensitivity.csv", cost_grid)

    # ---------- extreme discontinuities ----------
    disc = []
    for sid, ser in price_store.closes.items():
        dates = sorted(d for d, v in ser.items() if v and v > 0)
        for a, b in zip(dates, dates[1:]):
            pa, pb = ser[a], ser[b]
            r = pb / pa - 1.0
            if abs(r) >= EXTREME:
                disc.append({"security_id": sid, "trade_date": b, "prev_date": a,
                             "close": pb, "prev_close": pa, "ret": r})
    wcsv(OUT / "raw_return_discontinuities.csv", disc)
    # top-20 exposure to extreme events
    disc_by_sec = {}
    for d in disc:
        disc_by_sec.setdefault(d["security_id"], []).append(d["trade_date"])

    def in_interval(sid, entry, exit_):
        for dd in disc_by_sec.get(sid, ()):
            if entry is not None and exit_ is not None and entry < dd <= exit_:
                return True
        return False

    sel_extreme = 0; bench_extreme = 0; n_sel_obs = 0; n_bench_obs = 0
    for i, rb in enumerate(rebalances):
        if i + 1 >= len(rebalances):
            break
        entry = rb["execution_date"]; ex = rebalances[i + 1]["execution_date"]
        for s in rb["selected"]:
            n_sel_obs += 1
            if in_interval(s["security_id"], entry, ex):
                sel_extreme += 1
        for s in rb["tradable"]:
            n_bench_obs += 1
            if in_interval(s["security_id"], entry, ex):
                bench_extreme += 1

    # ---------- coverage control ----------
    horizons = list(cfg.horizons)
    # per-date IC by horizon
    horizon_rows = []
    for h in horizons:
        ics = []
        for T in reb_dates:
            xs = [s["quant_score"] for s in cross[T]]; ys = [s.get(f"ret_{h}") for s in cross[T]]
            v = DG.spearman(xs, ys)
            if v is not None:
                ics.append(v)
        horizon_rows.append({"horizon_days": h, **bootstrap_ci(ics), "target": "quant_score"})
    wcsv(OUT / "horizon_diagnostics.csv", horizon_rows)

    # raw IC (21d) and coverage-stratified
    def within_stratum_ic(T, ret="ret_21", factor=None):
        out = {}
        for st in ("low", "medium", "high"):
            seg = [s for s in cross[T] if stratum(s["n_factors_available"]) == st]
            xs = [(s["factor_rank"].get(factor) if factor else s["quant_score"]) for s in seg]
            ys = [s.get(ret) for s in seg]
            v = DG.spearman(xs, ys)
            if v is not None:
                out.setdefault(st, []).append(v)
        return out

    raw_ics = []
    strat_ics = {"low": [], "medium": [], "high": []}
    for T in reb_dates:
        v = DG.spearman([s["quant_score"] for s in cross[T]], [s.get("ret_21") for s in cross[T]])
        if v is not None:
            raw_ics.append(v)
        for st, vals in within_stratum_ic(T).items():
            strat_ics[st].extend(vals)
    cov_ic_rows = [{"coverage_stratum": "all", **bootstrap_ci(raw_ics)}]
    for st in ("low", "medium", "high"):
        cov_ic_rows.append({"coverage_stratum": st, **bootstrap_ci(strat_ics[st])})
    wcsv(OUT / "coverage_controlled_ic.csv", cov_ic_rows)

    # coverage-neutralized diagnostic score (DIAGNOSTIC_ONLY_NOT_MODEL)
    resid_ics = []
    for T in reb_dates:
        cs = [s for s in cross[T] if s.get("ret_21") is not None]
        if len(cs) < 6:
            continue
        xs = [s["n_factors_available"] for s in cs]
        ys = [s["quant_score"] for s in cs]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        var = sum((x - mx) ** 2 for x in xs)
        if var <= 0:
            continue
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
        a = my - b * mx
        resid = [y - (a + b * x) for x, y in zip(xs, ys)]
        v = DG.spearman(resid, [s["ret_21"] for s in cs])
        if v is not None:
            resid_ics.append(v)
    neutralized = bootstrap_ci(resid_ics)

    # partial association: ret ~ score + n_factors (pooled and per-date averaged)
    pooled = ols2([(s.get("ret_21"), s["quant_score"], s["n_factors_available"])
                   for T in reb_dates for s in cross[T] if s.get("ret_21") is not None])
    per_date_coefs = []
    for T in reb_dates:
        c = ols2([(s.get("ret_21"), s["quant_score"], s["n_factors_available"])
                  for s in cross[T] if s.get("ret_21") is not None])
        if c:
            per_date_coefs.append(c)
    partial = {"pooled_intercept": pooled[0] if pooled else None,
               "pooled_score_coef": pooled[1] if pooled else None,
               "pooled_n_factors_coef": pooled[2] if pooled else None,
               "per_date_score_coef_mean": mean([c[1] for c in per_date_coefs]),
               "per_date_n_factors_coef_mean": mean([c[2] for c in per_date_coefs]),
               "n_dates": len(per_date_coefs)}

    # coverage score matrix (quintile x stratum), 21d
    matrix = {}
    for T in reb_dates:
        cs = [s for s in cross[T] if s.get("ret_21") is not None and s["quant_score"] is not None]
        if len(cs) < 10:
            continue
        cs.sort(key=lambda s: s["quant_score"])
        qn = 5
        for qi in range(qn):
            lo = int(qi * len(cs) / qn); hi = int((qi + 1) * len(cs) / qn) if qi < qn - 1 else len(cs)
            seg = cs[lo:hi]
            for st in ("low", "medium", "high"):
                sub = [s["ret_21"] for s in seg if stratum(s["n_factors_available"]) == st]
                if sub:
                    matrix.setdefault((qi + 1, st), []).append(mean(sub))
    matrix_rows = [{"score_quintile": k[0], "coverage_stratum": k[1],
                    "mean_ret_21": mean(v), "n_periods": len(v)} for k, v in sorted(matrix.items())]
    wcsv(OUT / "coverage_score_matrix.csv", matrix_rows)

    # category coverage conditional IC
    cat_rows = []
    for cat in CATEGORY:
        has, hasnt = [], []
        for T in reb_dates:
            for s in cross[T]:
                if s.get("ret_21") is None:
                    continue
                (has if (s.get("category_available") or {}).get(cat, 0) > 0 else hasnt).append(
                    (s["quant_score"], s["ret_21"]))
        for label, seg in (("available", has), ("unavailable", hasnt)):
            xs = [a for a, _ in seg]; ys = [b for _, b in seg]
            v = DG.spearman(xs, ys)
            cat_rows.append({"category": cat, "coverage": label, "pooled_ic": v, "n_obs": len(seg)})
    wcsv(OUT / "category_coverage_diagnostics.csv", cat_rows)

    # factor controlled diagnostics
    from assess_readiness import FACTOR_SOURCE
    factor_rows = []
    for fc, src in FACTOR_SOURCE.items():
        raw = []
        strata = {"low": [], "medium": [], "high": []}
        avail = 0; tot = 0
        for T in reb_dates:
            tot += len(cross[T])
            for s in cross[T]:
                if s.get("factor_available", {}).get(fc):
                    avail += 1
                xs = s["factor_rank"].get(fc); ys = s.get("ret_21")
                if xs is not None and ys is not None:
                    raw.append((xs, ys))
            for st, vals in within_stratum_ic(T, factor=fc).items():
                strata[st].extend(vals)
        raw_ic = DG.spearman([a for a, _ in raw], [b for _, b in raw]) if raw else None
        ctrl = mean([v for st in strata.values() for v in st])
        if raw_ic is None:
            cls = "SIGNAL_INCONCLUSIVE"
        elif abs(raw_ic) < 0.02:
            cls = "SIGNAL_INCONCLUSIVE"
        elif ctrl is not None and abs(ctrl) >= 0.6 * abs(raw_ic) and (ctrl * raw_ic > 0):
            cls = "SIGNAL_PERSISTS_AFTER_COVERAGE_CONTROL"
        elif ctrl is not None and abs(ctrl) <= 0.4 * abs(raw_ic):
            cls = "SIGNAL_WEAKENS_AFTER_COVERAGE_CONTROL"
        else:
            cls = "COVERAGE_CONFOUNDED"
        factor_rows.append({"factor_code": fc, "raw_ic": raw_ic, "coverage_controlled_ic": ctrl,
                            "availability_rate": avail / tot if tot else None, "classification": cls})
    wcsv(OUT / "factor_controlled_diagnostics.csv", factor_rows)

    # matched benchmark (match on n_factors)
    matched_rows = []
    for idx, rb in enumerate(rebalances):
        T = rb["date"]; sel = rb["selected"]
        pool = [s for s in rb["tradable"] if s["company_id"] not in {x["company_id"] for x in sel}]
        used = set(); controls = []
        for s in sorted(sel, key=lambda x: x["company_id"]):
            cand = [p for p in pool if p["company_id"] not in used]
            if not cand:
                break
            best = min(cand, key=lambda p: (abs(p["n_factors_available"] - s["n_factors_available"]), p["company_id"]))
            used.add(best["company_id"]); controls.append(best)
        if not controls:
            continue
        entry = rb["execution_date"]; exit_ = rebalances[idx + 1]["execution_date"] if idx + 1 < len(rebalances) else None
        strat_ret = mean([forward_return(price_store, s["security_id"], entry, exit_) for s in sel])
        ctrl_ret = mean([forward_return(price_store, s["security_id"], entry, exit_) for s in controls])
        matched_rows.append({"date": str(T), "strategy_ret": strat_ret, "matched_control_ret": ctrl_ret,
                             "n_controls": len(controls)})
    wcsv(OUT / "matched_benchmark.csv", matched_rows)

    # performance concentration
    by_company = {}
    for c in contrib:
        by_company[c["company_id"]] = by_company.get(c["company_id"], 0.0) + c["contribution"]
    top_companies = sorted(by_company.items(), key=lambda kv: -kv[1])[:10]
    by_period = {}
    for c in contrib:
        by_period[str(c["date"])] = by_period.get(str(c["date"]), 0.0) + c["contribution"]
    top_periods = sorted(by_period.items(), key=lambda kv: -kv[1])[:5]
    gross = [r["gross_return"] for r in port_rows if r["gross_return"] is not None]
    pos = sorted([g for g in gross if g > 0], reverse=True)
    best10 = int(len(gross) * 0.10) or 1
    share_best10 = sum(pos[:best10]) / sum(pos) if pos else None
    concentration = {
        "top5_companies": top_companies[:5], "top10_companies": top_companies,
        "top5_periods": top_periods,
        "share_of_positive_pnl_best_10pct_periods": share_best10,
        "n_periods": len(gross), "n_companies_traded": len(by_company)}
    wcsv(OUT / "performance_concentration.csv",
         [{"rank": i + 1, "company_id": c, "contribution_sum": v} for i, (c, v) in enumerate(top_companies)])

    # liquidity / tradability correlation
    liq_pairs, mkt_pairs = [], []
    for T in reb_dates:
        for s in cross[T]:
            if s.get("quant_score") is None:
                continue
            lr = (s.get("factor_rank") or {}).get("LiquidityRank")
            if lr is not None:
                liq_pairs.append((s["quant_score"], lr))
            ms = s.get("market_score")
            if ms is not None:
                mkt_pairs.append((s["quant_score"], ms))
    liq_corr = ({"n": len(liq_pairs), "spearman": DG.spearman([a for a, _ in liq_pairs], [b for _, b in liq_pairs]),
                 "note": "LiquidityRank constant historically: canonical trade_value_rial is populated only in 2026 "
                         "(9,382/705,812 rows), so liquidity is neutral (0.0) for all historical signals; not measurable."}
                if liq_pairs else {"n": 0, "spearman": None})
    mkt_corr = ({"n": len(mkt_pairs), "spearman": DG.spearman([a for a, _ in mkt_pairs], [b for _, b in mkt_pairs])}
                if mkt_pairs else {"n": 0, "spearman": None})

    # time robustness
    def sub_ic(years):
        vals = []
        for T in reb_dates:
            if str(T)[:4] in years:
                v = DG.spearman([s["quant_score"] for s in cross[T]], [s.get("ret_21") for s in cross[T]])
                if v is not None:
                    vals.append(v)
        return {"mean_ic": mean(vals), "n": len(vals)}
    time_rob = {"2021": sub_ic({"2021"}), "2022": sub_ic({"2022"}), "2023": sub_ic({"2023"}),
                "2024": sub_ic({"2024"}), "2025": sub_ic({"2025"}),
                "2026": {**sub_ic({"2026"}), "flag": "INSUFFICIENT_PERIOD_COUNT_FOR_YEARLY_INFERENCE"},
                "2021-2023": sub_ic({"2021", "2022", "2023"}), "2024-2025": sub_ic({"2024", "2025"})}

    # ---------- summary ----------
    summary = {
        "config": cfg.__dict__, "frozen_model": frozen_model_identifiers(),
        "portfolio_path": {
            "contiguous_non_overlapping": contiguous,
            "n_intervals": len(port_rows),
            "n_cash_intervals": len(cash_intervals),
            "cash_intervals": cash_intervals,
            "zero_tradable_dates": zero_tradable,
            "n_missing_exit_total": sum(r["n_missing_exit"] for r in port_rows),
            "portfolio": port_sum["portfolio"], "portfolio_net": port_sum["portfolio_net"],
            "benchmark": port_sum["benchmark"], "mean_turnover": port_sum["mean_turnover"],
        },
        "cost_grid": cost_grid,
        "market_revision": {"total_obs": total_obs, "distinct_keys": total_keys,
                            "conflicting_keys": conflicting,
                            "conflicting_pct": round(conflicting / total_keys * 100, 4)},
        "corporate_actions": {"rows": 0, "return_convention": cfg.return_convention,
                              "extreme_events": len(disc),
                              "selected_extreme_exposure": sel_extreme,
                              "selected_extreme_exposure_pct": round(sel_extreme / n_sel_obs * 100, 3) if n_sel_obs else None,
                              "benchmark_extreme_exposure": bench_extreme,
                              "benchmark_extreme_exposure_pct": round(bench_extreme / n_bench_obs * 100, 3) if n_bench_obs else None},
        "raw_ic": bootstrap_ci(raw_ics),
        "coverage_controlled_ic": {st: bootstrap_ci(strat_ics[st]) for st in ("low", "medium", "high")},
        "coverage_neutralized_ic": {**neutralized, "label": "DIAGNOSTIC_ONLY_NOT_MODEL"},
        "partial_association": partial,
        "pearson_score_vs_n_factors": None,
        "horizon_diagnostics": horizon_rows,
        "time_robustness": time_rob,
        "liquidity_corr_score_vs_liquidity_rank": liq_corr,
        "corr_score_vs_market_score": mkt_corr,
        "matched_benchmark": {
            "strategy_mean": mean([r["strategy_ret"] for r in matched_rows]),
            "matched_control_mean": mean([r["matched_control_ret"] for r in matched_rows]),
            "strategy_minus_matched": mean([(r["strategy_ret"] or 0) - (r["matched_control_ret"] or 0)
                                            for r in matched_rows if r["strategy_ret"] is not None and r["matched_control_ret"] is not None]),
            "n_periods": len(matched_rows)},
        "category_coverage": cat_rows,
        "concentration": concentration,
        "hashes": {},
    }
    # pearson score vs n_factors (pooled)
    sc = [s["quant_score"] for T in reb_dates for s in cross[T]]
    nf = [s["n_factors_available"] for T in reb_dates for s in cross[T]]
    summary["pearson_score_vs_n_factors"] = DG.pearson(sc, nf)
    # hashes
    summary["hashes"]["snapshots"] = sha([snapshot_stable_payload(snapshot_full[T]) for T in reb_dates])
    summary["hashes"]["portfolio_path"] = sha(port_rows)
    summary["hashes"]["coverage_ic"] = sha(cov_ic_rows)
    summary["hashes"]["coverage_matrix"] = sha(matrix_rows)
    summary["hashes"]["matched_benchmark"] = sha(matched_rows)
    summary["hashes"]["market_revision"] = sha(rev_rows)
    summary["hashes"]["raw_discontinuities"] = sha(disc)
    summary["hashes"]["summary"] = sha({k: v for k, v in summary.items() if k != "hashes"})

    (OUT / "phase2_summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    pg.close()
    print("raw IC", summary["raw_ic"]["mean"],
          "| controlled low/med/high", {k: (v["mean"]) for k, v in summary["coverage_controlled_ic"].items()},
          "| neutralized", summary["coverage_neutralized_ic"]["mean"])
    print("portfolio cum", port_sum["portfolio"]["cumulative_return"],
          "bench", port_sum["benchmark"]["cumulative_return"],
          "contiguous", contiguous, "cash intervals", len(cash_intervals))
    print("summary hash", summary["hashes"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
