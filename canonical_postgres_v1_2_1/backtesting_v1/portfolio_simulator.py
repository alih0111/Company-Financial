"""Minimal deterministic equal-weight portfolio simulator (no optimizer).

Phase 1 baseline only. Supports top-N / top-percentile selection, equal weighting,
turnover measurement, and illustrative transaction costs.
"""

from __future__ import annotations

import math


def select_top(signals, mode, top_n, top_pct, min_count=1):
    ranked = [s for s in signals if s.get("quant_score") is not None]
    ranked.sort(key=lambda s: (-s["quant_score"], s["company_id"]))
    if mode == "top_pct":
        k = max(1, int(round(len(ranked) * top_pct)))
    else:
        k = top_n
    return ranked[:min(k, len(ranked))]


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def simulate(rebalances, cost_bps_per_side=0.0, bench_label="benchmark"):
    """rebalances: list of dicts:
        {date, execution_date, selected:[{company_id, ret}], benchmark:[{company_id, ret}]}
    returns (portfolio_rows, summary)."""
    rows = []
    prev_sel = set()
    for r in rebalances:
        sel = r["selected"]
        bench = r["benchmark"]
        n = len(sel)
        sel_ret = _mean([x.get("ret") for x in sel])
        bench_ret = _mean([x.get("ret") for x in bench])
        cur = {x["company_id"] for x in sel}
        entered = cur - prev_sel
        exited = prev_sel - cur
        turnover = (len(entered) / n) if n else 0.0
        cost = 2.0 * turnover * (cost_bps_per_side / 10000.0) if sel_ret is not None else 0.0
        net = (sel_ret - cost) if sel_ret is not None else None
        rows.append({"date": r["date"], "execution_date": r["execution_date"],
                     "n_selected": n, "n_benchmark": len(bench),
                     "entered": len(entered), "exited": len(exited),
                     "turnover": turnover, "gross_return": sel_ret,
                     "cost": cost, "net_return": net, "benchmark_return": bench_ret})
        prev_sel = cur
    return rows, summarize(rows)


def simulate_corrected(rebalances, cost_bps_per_side=0.0):
    """Cash-aware chronological wealth path.

    Policy (Phase 2, frozen):
      * holding interval = [exec_i, exec_{i+1}] ; intervals are contiguous and
        non-overlapping (exit_i == entry_{i+1}).
      * a member with a missing exit price is excluded from that period's basket;
        the number excluded is recorded (never fabricated/forward-filled).
      * if zero members remain tradable+valuable, the interval is CASH (return 0)
        and retained in the path (interval not dropped).
      * benchmark uses the identical policy on the full tradable set.
    Returns (rows, summary, contributions).
    """
    rows = []
    contributions = []
    prev_sel = set()
    for r in rebalances:
        sel = r["selected"]
        bench = r["benchmark"]
        sel_rets = [(x["company_id"], x.get("ret"), x.get("weight", 1.0)) for x in sel]
        bench_rets = [(x["company_id"], x.get("ret")) for x in bench]
        used = [(c, ret, w) for (c, ret, w) in sel_rets if ret is not None]
        n = len(sel)
        n_missing = sum(1 for (_, ret, _) in sel_rets if ret is None)
        cash = len(used) == 0
        if cash:
            sel_ret = 0.0
        else:
            tot_w = sum(w for (_, _, w) in used)
            sel_ret = sum(ret * w for (_, ret, w) in used) / tot_w
            for (c, ret, w) in used:
                contributions.append({"date": r["date"], "company_id": c,
                                      "contribution": ret * w / tot_w})
        b_used = [ret for (_, ret) in bench_rets if ret is not None]
        bench_ret = (sum(b_used) / len(b_used)) if b_used else 0.0
        cur = {x["company_id"] for x in sel}
        entered = cur - prev_sel
        exited = prev_sel - cur
        turnover = (len(entered) / n) if n else 0.0
        cost = 2.0 * turnover * (cost_bps_per_side / 10000.0)
        rows.append({"date": r["date"], "execution_date": r["execution_date"],
                     "n_selected": n, "n_benchmark": len(bench), "n_members_used": len(used),
                     "n_missing_exit": n_missing, "cash_interval": cash,
                     "entered": len(entered), "exited": len(exited), "turnover": turnover,
                     "gross_return": sel_ret, "cost": cost, "net_return": sel_ret - cost,
                     "benchmark_return": bench_ret})
        prev_sel = cur
    return rows, summarize(rows), contributions


def summarize(rows, periods_per_year=12):
    gross = [r["gross_return"] for r in rows if r["gross_return"] is not None]
    net = [r["net_return"] for r in rows if r["net_return"] is not None]
    bench = [r["benchmark_return"] for r in rows if r["benchmark_return"] is not None]
    return {"n_periods": len(rows),
            "portfolio": _series_stats(gross, periods_per_year),
            "portfolio_net": _series_stats(net, periods_per_year),
            "benchmark": _series_stats(bench, periods_per_year),
            "mean_turnover": _mean([r["turnover"] for r in rows]) if rows else None}


def _series_stats(rets, periods_per_year):
    if not rets:
        return {}
    cum = 1.0
    for r in rets:
        cum *= (1.0 + r)
    mean = sum(rets) / len(rets)
    vol = (sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 if len(rets) > 1 else 0.0
    sharpe = (mean / vol * math.sqrt(periods_per_year)) if vol > 0 else None
    # max drawdown
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in rets:
        eq *= (1.0 + r)
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1.0)
    return {"n": len(rets), "cumulative_return": cum - 1.0,
            "mean_period_return": mean, "volatility": vol,
            "annualized_return": (cum ** (periods_per_year / len(rets)) - 1.0) if len(rets) > 0 else None,
            "max_drawdown": mdd, "sharpe_like": sharpe,
            "hit_rate": sum(1 for r in rets if r > 0) / len(rets)}
