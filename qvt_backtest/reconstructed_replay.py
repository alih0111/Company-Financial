"""Fixed reconstructed financial/QVT-subset replay, monthly and six-monthly.

No model optimization, DB writes, fabricated publication/shares, or real orders.
"""
from __future__ import annotations
from bisect import bisect_right
import datetime as dt
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import run as R
from share_history import interval_eligible
from codal_publish_resolver import TEHRAN

HISTORY = R.HERE / "output/financial_history"


def cutoff_for(date):
    return dt.datetime.fromisoformat(date).replace(tzinfo=TEHRAN).astimezone(dt.timezone.utc)


def resolve_shares(intervals, symbol, cid, sid, date, price_date):
    matches = []
    cut = cutoff_for(date)
    for iv in intervals.get(symbol, []):
        if iv["company_id"] != cid or iv["security_id"] != sid:
            continue
        if (interval_eligible(iv, dt.date.fromisoformat(date), cut)[0]
                and interval_eligible(iv, dt.date.fromisoformat(price_date), cut)[0]
                and iv.get("evidence") and iv.get("shares_outstanding", 0) > 0):
            matches.append(iv)
    return matches[0] if len(matches) == 1 else None


def prepare(panel, financial, md, shares):
    intervals = {}
    for iv in shares:
        intervals.setdefault(iv["codal_symbol"], []).append(iv)
    joined = panel.merge(financial, left_on=["symbol", "as_of"], right_on=["symbol", "date"], how="left", validate="one_to_one", suffixes=("_old", ""))
    rows = []
    audit = []
    for row in joined.to_dict("records"):
        date, sym = str(row["as_of"])[:10], row["symbol"]
        reason = None
        period = row.get("financial_period_end")
        if not isinstance(period, str):
            reason = "missing_financial_ttm"
        elif period > date:
            reason = "future_financial_period"
        elif (dt.date.fromisoformat(date) - dt.date.fromisoformat(period)).days > 365:
            reason = "financial_period_stale"
        elif row["used_older_income_report"]:
            reason = "newer_income_report_not_reconstructible"
        elif dt.datetime.fromisoformat(row["max_source_published_at"]) >= cutoff_for(date):
            raise ValueError("future financial publication")
        rec = md.data.get(sym)
        idx = bisect_right(rec["dates"], date) - 1 if rec else -1
        while idx >= 0 and (rec["c"][idx] <= 0 or rec["vol"][idx] <= 0):
            idx -= 1
        price_date = rec["dates"][idx] if idx >= 0 else None
        if reason is None and (price_date is None or (dt.date.fromisoformat(date) - dt.date.fromisoformat(price_date)).days > 7):
            reason = "missing_or_stale_traded_price"
        iv = resolve_shares(intervals, sym, row.get("company_id"), md.sym2sid.get(sym), date, price_date) if reason is None else None
        if reason is None and iv is None:
            reason = "missing_unambiguous_published_share_interval"
        if reason is None:
            cap = float(rec["c"][idx]) * iv["shares_outstanding"]
            row.update({"roe": row["roe_end_equity"] * 100, "price_date": price_date,
                        "shares_outstanding": iv["shares_outstanding"], "share_knowledge_from": iv["knowledge_from"],
                        "share_evidence": json.dumps(iv["evidence"], ensure_ascii=False), "market_cap": cap})
            for factor, den in [("pe", "net_profit_ttm"), ("pb", "total_equity"), ("ps", "revenue_ttm")]:
                row[factor] = cap / row[den] if pd.notna(row[den]) and row[den] > 0 else np.nan
            rows.append(row)
        audit.append({"date": date, "symbol": sym, "reason": reason or "market_financial_available"})
    return pd.DataFrame(rows), pd.DataFrame(audit)


def decision_schedule(dates, months):
    if months == 1:
        return sorted(dates)
    picked = []
    for day in sorted(dates):
        if not picked or pd.Timestamp(day) >= pd.Timestamp(picked[-1]) + pd.DateOffset(months=months):
            picked.append(day)
    return picked


def replay(selected, observation_dates, adj, cal, keys, months, cost_rate, RA, execution=None):
    execution = execution or {}
    delay = execution.get("delay_sessions", 0)
    if not isinstance(delay, int) or delay < 0:
        raise ValueError("execution delay must be nonnegative integer")
    end_exec = cal[bisect_right(cal, observation_dates[-1])]
    dates = decision_schedule([d for d in selected.as_of.unique() if d < observation_dates[-1]], months)
    decisions = {cal[bisect_right(cal, d) + delay]: (d, selected[selected.as_of == d]) for d in dates
                 if bisect_right(cal, d) + delay < len(cal) and cal[bisect_right(cal, d) + delay] < end_exec}
    if not decisions:
        raise ValueError("no executable decisions")
    start = min(decisions)
    cash, positions = 1.0, {}
    daily, ledger, trades = [], [], []
    for day in cal[cal.index(start):cal.index(end_exec) + 1]:
        cur = {s: sh * RA.price_at(adj, s, day) for s, sh in positions.items()}
        pre = cash + sum(cur.values())
        if day in decisions:
            signal, group = decisions[day]
            targets = {s: pre / len(group) for s in group.symbol if (day, s) in keys}
            failed = [s for s in group.symbol if (day, s) not in keys and s not in positions]
            tradable = {s: (day, s) in keys for s in set(cur) | set(targets)}
            constrained_notional = 0.0
            if execution.get("capacities") is not None:
                # Capacities are normalized to initial capital, not current NAV.
                # Missing volume means no fill; held assets remain on the ledger.
                caps = execution["capacities"]
                bounded = {}
                for sym in set(cur) | set(targets):
                    current, desired = cur.get(sym, 0.0), targets.get(sym, 0.0)
                    cap = caps.get((day, sym), 0.0)
                    if not math.isfinite(cap) or cap < 0:
                        raise ValueError("invalid execution capacity")
                    movement = max(-cap, min(cap, desired - current)) if tradable[sym] else 0.0
                    bounded[sym] = current + movement
                    constrained_notional += abs(desired - current - movement)
                targets = bounded
            before_cash = cash
            cash, new, cost, buys, sells, scale = RA.rebalance_accounts(cash, cur, targets, tradable, cost_rate)
            post = cash + sum(new.values())
            if abs(post - (pre - cost)) > 1e-9 or cash < -1e-9:
                raise ValueError("cash/NAV conservation failed")
            for sym in set(cur) | set(new):
                delta = new.get(sym, 0) - cur.get(sym, 0)
                if abs(delta) > 1e-12:
                    trades.append({"signal_date": signal, "exec_date": day, "symbol": sym,
                                   "side": "BUY" if delta > 0 else "SELL", "notional": abs(delta), "cost": abs(delta) * cost_rate})
            positions = {s: value / RA.price_at(adj, s, day) for s, value in new.items()}
            ledger.append({"score_date": signal, "exec_date": day, "value_pre_trade": pre,
                           "value_post_trade": post, "transaction_cost": cost, "cash_weight": cash / post,
                           "n_selected": len(group), "failed_targets": len(failed), "buy_notional": buys, "sell_notional": sells,
                           "traded_notional": buys + sells, "cash_pre": before_cash, "cash_post": cash})
            ledger[-1]["constrained_notional"] = constrained_notional
        nav = cash + sum(sh * RA.price_at(adj, s, day) for s, sh in positions.items())
        daily.append({"date": day, "nav": nav, "cash_weight": cash / nav})
    wealth = np.array([1.0] + [r["nav"] for r in daily])
    elapsed = (dt.date.fromisoformat(daily[-1]["date"]) - dt.date.fromisoformat(daily[0]["date"])).days / 365.2425
    perf = {"cumulative_return_pct": float((wealth[-1] - 1) * 100),
            "annualized_return_pct": float((wealth[-1] ** (1 / elapsed) - 1) * 100),
            "max_drawdown_pct": float((wealth / np.maximum.accumulate(wealth) - 1).min() * 100),
            "execution_start": start, "execution_end": end_exec, "elapsed_years": elapsed,
            "n_rebalances": len(ledger), "failed_target_count": sum(r["failed_targets"] for r in ledger),
            "total_cost_pct_initial_capital": sum(r["transaction_cost"] for r in ledger) * 100,
            "avg_cash_pct": float(np.mean([r["cash_weight"] for r in daily]) * 100)}
    perf["total_constrained_notional_initial_capital"] = sum(r["constrained_notional"] for r in ledger)
    return perf, daily, ledger, trades


def safe_json(obj):
    if isinstance(obj, dict):
        return {str(k): safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_json(v) for v in obj]
    return obj


def main():
    protocol = json.loads((R.HERE / "reconstructed_protocol.json").read_text(encoding="utf8"))
    out = R.HERE / "output" / ("reconstructed_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out.mkdir(exist_ok=False, parents=True)
    R.write(out / "protocol.json", protocol)
    hashes = R.V.verify_frozen_shas()
    for name in ("financial_panel.csv", "reports.json", "share_intervals.json", "catalog_versions.json"):
        hashes[name] = R.sha(HISTORY / name)
        shutil.copyfile(HISTORY / name, out / ("input_" + name))
    hashes["historical_panel"] = R.sha(R.ROOT / "score_v2_research/pit_feature_panel.parquet")
    hashes["current_family_map"] = R.sha(R.ROOT / "qvt_paper/output/current_ranking.json")
    hashes["replay_code"] = R.sha(Path(__file__))
    R.write(out / "input_hashes.json", hashes)
    panel = pd.read_parquet(R.ROOT / "score_v2_research/pit_feature_panel.parquet")
    panel["as_of"] = panel.as_of.astype(str).str[:10]
    financial = pd.read_csv(out / "input_financial_panel.csv")
    md = R.V.MarketData(R.V.load_reference_data(), symbols=sorted(panel.symbol.unique()))
    source, audit = prepare(panel, financial, md, json.loads((out / "input_share_intervals.json").read_text(encoding="utf8"))["intervals"])
    audit.to_csv(out / "availability.csv", index=False)
    source.to_parquet(out / "reconstructed_inputs.parquet", index=False)
    if source.empty:
        raise ValueError("no financial/price/share inputs")
    current = json.loads((R.ROOT / "qvt_paper/output/current_ranking.json").read_text(encoding="utf8"))
    scored, timing, coverage, alignment = R.build_scores(source, md, current, protocol["weights"])
    pd.DataFrame(coverage).to_csv(out / "coverage.csv", index=False)
    R.write(out / "alignment.json", safe_json(alignment))
    if scored.empty:
        raise ValueError("no date has twenty complete subset scores")
    scored.to_parquet(out / "scores.parquet", index=False)
    scored["as_of"] = scored.as_of.astype(str).str[:10]
    observation_dates = sorted(d for d in panel.as_of.unique() if d >= scored.as_of.min())
    adj = {s: {"dates": r["dates"], "adj": {d: float(c * f) for d, c, f in zip(r["dates"], r["c"], r["cf"])}}
           for s, r in md.data.items()}
    strategies = {"QVT_TOP10": scored.sort_values(["as_of", "ui_score", "symbol"], ascending=[True, False, True]).groupby("as_of").head(10),
                  "QVT_BOTTOM10": scored.sort_values(["as_of", "ui_score", "symbol"]).groupby("as_of").head(10),
                  "MATCHED_EQUAL_WEIGHT": scored}
    RA, keys = R.V.load_portfolio_engine(), R.V.tradability_keys()
    performance, slices = {}, []
    for name, selected in strategies.items():
        selected[["as_of", "symbol", "ui_score"]].to_csv(out / f"{name}_selections.csv", index=False)
        for cadence in protocol["cadences_months"]:
            for cost in protocol["cost_rates"]:
                label = f"{name}_{cadence}m_{cost:g}"
                perf, daily, ledger, trades = replay(selected, observation_dates, adj, md.cal, keys, cadence, cost, RA)
                performance[label] = perf
                pd.DataFrame(daily).to_csv(out / f"{label}_daily.csv", index=False)
                pd.DataFrame(ledger).to_csv(out / f"{label}_ledger.csv", index=False)
                pd.DataFrame(trades).to_csv(out / f"{label}_trades.csv", index=False)
                for start, end in [("2022-01-01", "2023-12-31"), ("2024-01-01", "2024-12-31"), ("2025-01-01", "2026-12-31")]:
                    sub = [r for r in daily if start <= r["date"] <= end]
                    if not sub:
                        continue
                    previous = [r for r in daily if r["date"] < sub[0]["date"]]
                    initial = previous[-1]["nav"] if previous else 1.0
                    slices.append({"strategy": label, "start": sub[0]["date"], "end": sub[-1]["date"],
                                   "return_pct": (sub[-1]["nav"] / initial - 1) * 100})
                print(f"{label}: annual={perf['annualized_return_pct']:.2f} drawdown={perf['max_drawdown_pct']:.2f}", flush=True)
    pd.DataFrame(slices).to_csv(out / "time_slices.csv", index=False)
    summary = {"version": protocol["version"], "exact_live_model": False, "score_ceiling": 76,
               "scope": protocol["scope"], "full_qvt_status": "historical_subset_only", "real_orders": 0,
               "as_of_start": scored.as_of.min(), "as_of_end": observation_dates[-1],
               "n_dates": scored.as_of.nunique(), "n_symbols": scored.symbol.nunique(), "n_rows": len(scored),
               "min_complete": int(scored.groupby("as_of").size().min()), "max_complete": int(scored.groupby("as_of").size().max()),
               "performance": performance, "limitations": protocol["limitations"], "run_path": str(out),
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    R.write(out / "summary.json", summary)
    # Keep the app on its last audited result until independent checks pass.
    R.write(R.HERE / "output/reconstructed_candidate.json", summary)
    print(json.dumps({"run": str(out), "n_dates": summary["n_dates"], "n_symbols": summary["n_symbols"]}), flush=True)

if __name__ == "__main__":
    main()
