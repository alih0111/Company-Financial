"""Frozen, preregistered research; does not change live weights or submit orders.

Run from repository root: .venv/Scripts/python.exe qvt_backtest/execute_roadmap.py
All comparisons reuse the audited complete cohort. No parameter winner is promoted.
"""
from __future__ import annotations
import datetime as dt
import json
from pathlib import Path
import shutil
from bisect import bisect_right

import numpy as np
import pandas as pd
import reconstructed_replay as B
import run as R

POLICY = R.HERE / "investment_policy.v1.json"
FAMILIES = {"Q": ["roe_level", "margins", "cash_conversion", "leverage"],
            "V": ["pe", "pb", "ps"],
            "T": ["momentum_6m_rel", "momentum_3m_rel", "liquidity", "low_volatility"]}


def select_buffer(scores, limit=10, retention_rank=15):
    """Pure chronological selection; absent/ineligible incumbents cannot remain."""
    previous, groups = [], []
    for date, group in scores.groupby("as_of", sort=True):
        ordered = group.sort_values(["ui_score", "symbol"], ascending=[False, True])
        ranks = {s: i + 1 for i, s in enumerate(ordered.symbol)}
        retained = [s for s in previous if ranks.get(s, retention_rank + 1) <= retention_rank]
        retained = sorted(retained, key=lambda s: ranks[s])[:limit]
        selected = retained + [s for s in ordered.symbol if s not in retained][:limit - len(retained)]
        groups.append(ordered[ordered.symbol.isin(selected)])
        previous = selected
    return pd.concat(groups, ignore_index=True)


def yearly(daily):
    result, previous = [], 1.0
    for year, group in pd.DataFrame(daily).groupby(pd.to_datetime([r["date"] for r in daily]).year):
        first, last = group.iloc[0], group.iloc[-1]
        result.append({"year": int(year), "start": first["date"], "end": last["date"],
                       "complete_year": first["date"][5:] <= "01-10" and last["date"][5:] >= "12-20",
                       "return_pct": (last.nav / previous - 1) * 100})
        previous = last.nav
    return result


def paired_uncertainty(top, reference, config):
    if [r["date"] for r in top] != [r["date"] for r in reference]:
        raise ValueError("bootstrap calendars differ")
    a = np.diff(np.log([1.] + [r["nav"] for r in top]))
    b = np.diff(np.log([1.] + [r["nav"] for r in reference]))
    n, block = len(a), config["block_sessions"]
    rng = np.random.default_rng(config["seed"])
    starts = rng.integers(0, n, (config["replications"], (n + block - 1) // block))
    indices = ((starts[..., None] + np.arange(block)) % n).reshape(config["replications"], -1)[:, :n]
    years = (dt.date.fromisoformat(top[-1]["date"]) - dt.date.fromisoformat(top[0]["date"])).days / 365.2425
    delta = (np.expm1(a[indices].sum(axis=1) / years) - np.expm1(b[indices].sum(axis=1) / years)) * 100
    return {"metric": "excess_cagr_percentage_points", "interval_95": np.quantile(delta, [.025, .975]).tolist(),
            "positive_fraction": float((delta > 0).mean()), **config,
            "limitations": "Stationary block approximation on already observed history; not a calibrated probability of future success and no selection-bias correction"}


def gap_inventory(base, scores, out):
    availability = pd.read_csv(base / "availability.csv", keep_default_na=False)
    scored_pairs = set(zip(scores.as_of, scores.symbol))
    source = pd.read_parquet(base / "reconstructed_inputs.parquet")
    lookup = {(str(r["as_of"])[:10], r["symbol"]): r for r in source.to_dict("records")}
    raw_columns = {"roe_level": "roe", "margins": "operating_margin", "cash_conversion": "cash_conversion",
                   "leverage": "debt_ratio", "pe": "pe", "pb": "pb", "ps": "ps"}
    for index, row in availability.iterrows():
        key = row["date"], row["symbol"]
        if key in scored_pairs:
            reason, category = "complete_76_point_subset", "eligible_subset"
        elif row["reason"] == "market_financial_available":
            raw = lookup.get(key, {})
            absent = [f for f, c in raw_columns.items() if not pd.notna(raw.get(c))]
            economic = [f for f, c in {"pe": "net_profit_ttm", "pb": "total_equity", "ps": "revenue_ttm"}.items()
                        if pd.notna(raw.get(c)) and raw[c] <= 0]
            if economic:
                reason, category = "invalid_economic_denominator:" + ",".join(economic), "economic_ineligible"
            elif absent:
                reason, category = "missing_factors:" + ",".join(absent), "financial_or_economic_check"
            else:
                reason, category = "timing_or_population_or_family_gate", "timing_or_model_check"
        else:
            reason = row["reason"]
            category = ("share_evidence" if "share" in reason else "market_history" if "price" in reason else "financial_history")
        availability.loc[index, "stage_reason"] = reason
        availability.loc[index, "category"] = category
    availability.to_csv(out / "gap_matrix.csv", index=False)
    by_date = availability.groupby(["date", "category"]).size().rename("rows").reset_index()
    by_date.to_csv(out / "gap_by_date.csv", index=False)
    priority = availability[availability.category.ne("eligible_subset")].groupby(["symbol", "category"]).size().rename("affected_dates").reset_index()
    priority.sort_values(["affected_dates", "symbol"], ascending=[False, True]).to_csv(out / "gap_priorities.csv", index=False)
    gaps, partial_gaps = [], []
    history = B.HISTORY
    for filename, kind in [("missing_reports.csv", "not_archived"), ("unusable_reports.csv", "unsupported_or_unproven_extraction"),
                           ("partial_reports.csv", "partial_own_statement_coverage")]:
        table = pd.read_csv(history / filename, dtype=str)
        shutil.copyfile(history / filename, out / ("input_" + filename))
        for rec in table.to_dict("records"):
            published = pd.Timestamp(rec["published_at"])
            candidates = availability[availability.symbol.eq(rec["symbol"]) & availability.category.eq("financial_history")]
            potential = sum(B.cutoff_for(day) > published.to_pydatetime() and
                            0 <= (dt.date.fromisoformat(day) - dt.date.fromisoformat(rec["period_end"])).days <= 365
                            for day in candidates.date)
            target = partial_gaps if kind == "partial_own_statement_coverage" else gaps
            target.append({**rec, "gap_type": kind, "potential_affected_dates": potential,
                           "impact_basis": "Candidate current-period coverage only; not a guarantee of reconstructed TTM or eligibility"})
    columns = ["company_id", "symbol", "tracing_no", "period_end", "published_at", "reason", "missing_metrics",
               "gap_type", "potential_affected_dates", "impact_basis"]
    pd.DataFrame(gaps, columns=columns).sort_values(["potential_affected_dates", "symbol"], ascending=[False, True]).to_csv(out / "report_recovery_queue.csv", index=False)
    pd.DataFrame(partial_gaps, columns=columns).sort_values(["potential_affected_dates", "symbol"], ascending=[False, True]).to_csv(out / "partial_statement_gaps.csv", index=False)
    current = json.loads((R.ROOT / "qvt_paper/output/current_ranking.json").read_text(encoding="utf8"))
    # Preserve the actual live reasons; never infer eligibility from historical scores.
    R.write(out / "current_gaps.json", {"ranked_count": len(current["ranked"]), "unscored_count": len(current["unscored"]),
        "unscored": [{k: row.get(k) for k in ("symbol", "company_id", "model_family", "unscored_reason", "status", "main_risk", "q", "v", "t")}
                     for row in current["unscored"]]})
    return {"rows": len(availability), "categories": availability.category.value_counts().to_dict(),
            "report_recovery_candidates": len(gaps), "partial_statement_candidates": len(partial_gaps), "live_unscored": len(current["unscored"])}


def factor_diagnostics(scores, md, keys, out):
    dates = sorted(scores.as_of.unique())
    records = []
    for signal, next_signal in zip(dates, dates[1:]):
        entry_i, exit_i = bisect_right(md.cal, signal), bisect_right(md.cal, next_signal)
        if entry_i >= len(md.cal) or exit_i >= len(md.cal):
            continue
        entry, exit_day = md.cal[entry_i], md.cal[exit_i]
        # Missing months are not silently treated as one-month outcome labels.
        if (dt.date.fromisoformat(exit_day) - dt.date.fromisoformat(entry)).days > 45:
            continue
        for row in scores[scores.as_of.eq(signal)].to_dict("records"):
            sym, rec = row["symbol"], md.data.get(row["symbol"])
            if not rec or (entry, sym) not in keys or (exit_day, sym) not in keys:
                continue
            i, j = rec["dmap"].get(entry), rec["dmap"].get(exit_day)
            if i is None or j is None:
                continue
            ret = rec["c"][j] * rec["cf"][j] / (rec["c"][i] * rec["cf"][i]) - 1
            records.append({"signal": signal, "entry": entry, "exit": exit_day, "symbol": sym,
                            "return_pct": ret * 100, "score": row["ui_score"],
                            **{c: row[c] for c in scores.columns if c.startswith("p_")}})
    frame = pd.DataFrame(records)
    frame.to_csv(out / "factor_forward_observations.csv", index=False)
    correlations, buckets = [], []
    for day, group in frame.groupby("signal"):
        if len(group) < 20:
            continue
        for factor in ["score"] + [c for c in frame.columns if c.startswith("p_")]:
            value = group[factor].rank().corr(group.return_pct.rank())
            correlations.append({"signal": day, "factor": factor, "spearman": value, "n": len(group)})
        group = group.copy()
        # Stable tie-breaking; group sizes differ by at most one.
        order = group.sort_values(["score", "symbol"]).index
        group.loc[order, "quintile"] = np.minimum(4, np.arange(len(group)) * 5 // len(group)) + 1
        for q, members in group.groupby("quintile"):
            buckets.append({"signal": day, "quintile": int(q), "mean_return_pct": members.return_pct.mean(), "n": len(members)})
    pd.DataFrame(correlations).to_csv(out / "factor_ic_by_date.csv", index=False)
    pd.DataFrame(buckets).to_csv(out / "score_quintiles_by_date.csv", index=False)
    ic = pd.DataFrame(correlations).groupby("factor").spearman.agg(["mean", "median", "count"]).reset_index()
    ic.to_csv(out / "factor_ic_summary.csv", index=False)
    return {"forward_rows": len(frame), "evaluated_dates": frame.signal.nunique(),
            "scope": "Complete-case descriptive price outcomes, variable next-observation horizon <=45 days, not net portfolio returns"}


def main():
    policy = json.loads(POLICY.read_text(encoding="utf8"))
    latest = json.loads((R.HERE / "output/reconstructed_latest.json").read_text(encoding="utf8"))
    base = Path(latest["run_path"])
    audit = json.loads((base / "audit.json").read_text(encoding="utf8"))
    if audit["status"] != "passed" or latest["exact_live_model"] is not False or latest["real_orders"] != 0:
        raise ValueError("baseline not approved for subset research")
    out = R.HERE / "output" / ("roadmap_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(parents=True, exist_ok=False)
    files = {"policy": POLICY, "baseline_summary": base / "summary.json", "baseline_audit": base / "audit.json",
             "scores": base / "scores.parquet", "availability": base / "availability.csv",
             "financial_inputs": base / "reconstructed_inputs.parquet", "code": Path(__file__),
             "replay_code": Path(B.__file__), "ranking": R.ROOT / "qvt_paper/output/current_ranking.json",
             "missing_reports": B.HISTORY / "missing_reports.csv", "unusable_reports": B.HISTORY / "unusable_reports.csv",
             "partial_reports": B.HISTORY / "partial_reports.csv"}
    manifest = {k: {"path": str(p), "sha256": R.sha(p)} for k, p in files.items()}
    # Freeze protocol and baseline before evaluating any candidate.
    for key, path in files.items():
        shutil.copyfile(path, out / ("input_" + key + path.suffix))
    R.write(out / "manifest.json", manifest)
    R.write(out / "registration.json", {"registered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                        "policy_sha256": manifest["policy"]["sha256"], "selection_uses_outcomes": False})
    weights = json.loads((base / "protocol.json").read_text(encoding="utf8"))["weights"]
    scores = pd.read_parquet(out / "input_scores.parquet")
    scores["as_of"] = scores.as_of.astype(str).str[:10]
    if scores.duplicated(["as_of", "symbol"]).any() or not np.isfinite(scores.ui_score).all():
        raise ValueError("invalid baseline score keys")
    gap_summary = gap_inventory(base, scores, out)
    print("Gap matrix and preregistration saved", flush=True)
    source_hashes = R.V.verify_frozen_shas()
    md = R.V.MarketData(R.V.load_reference_data(), symbols=sorted(scores.symbol.unique()))
    market_manifest = {sym: {"path": str(R.V.RAW / f"raw_{sym}_{rec['ins']}.json.gz"),
                             "sha256": R.sha(R.V.RAW / f"raw_{sym}_{rec['ins']}.json.gz")}
                       for sym, rec in md.data.items()}
    R.write(out / "market_manifest.json", market_manifest)
    R.write(out / "certified_source_hashes.json", source_hashes)
    keys, RA = R.V.tradability_keys(), R.V.load_portfolio_engine()
    adj = {s: {"dates": rec["dates"], "adj": {day: float(c * f) for day, c, f in zip(rec["dates"], rec["c"], rec["cf"])}}
           for s, rec in md.data.items()}
    observation_dates = sorted(pd.read_csv(base / "availability.csv").date.unique())
    observation_dates = [d for d in observation_dates if d >= scores.as_of.min()]
    variants = {name: [f for family in name for f in FAMILIES[family]] for name in policy["score_variants"]}
    if policy["single_factor_ablation"]:
        variants.update({"WITHOUT_" + f: [k for k in weights if k != f] for f in weights})
    selections = {}
    for name, factors in variants.items():
        group = scores.copy()
        group["ui_score"] = sum(weights[f] * group["p_" + f] for f in factors)
        selections[name] = group.sort_values(["as_of", "ui_score", "symbol"], ascending=[True, False, True]).groupby("as_of").head(policy["position_limit"])
    selections["QVT_BUFFER"] = select_buffer(scores, policy["position_limit"], policy["retention_rank"])
    selections["MATCHED_EQUAL_WEIGHT"] = scores
    results, annual, daily_cache = [], [], {}
    for name, selected in selections.items():
        selected[["as_of", "symbol", "ui_score"]].to_csv(out / (name + "_selections.csv"), index=False)
        for cost in policy["cost_rates"]:
            label = f"{name}_{cost:g}"
            perf, daily, ledger, trades = B.replay(selected, observation_dates, adj, md.cal, keys, policy["cadence_months"], cost, RA)
            perf.update({"strategy": name, "cost_rate": cost,
                         "annualized_traded_nav": sum(r["traded_notional"] / r["value_pre_trade"] for r in ledger) / perf["elapsed_years"]})
            results.append(perf)
            daily_cache[label] = daily
            annual.extend({"strategy": name, "cost_rate": cost, **year} for year in yearly(daily))
            for suffix, records in [("daily", daily), ("ledger", ledger), ("trades", trades)]:
                pd.DataFrame(records).to_csv(out / f"{label}_{suffix}.csv", index=False)
            print(f"{label}: CAGR={perf['annualized_return_pct']:.2f}; drawdown={perf['max_drawdown_pct']:.2f}", flush=True)
    table, years = pd.DataFrame(results), pd.DataFrame(annual)
    table.to_csv(out / "comparisons.csv", index=False)
    years.to_csv(out / "yearly_returns.csv", index=False)
    uncertainty = paired_uncertainty(daily_cache["QVT_0.005"], daily_cache["MATCHED_EQUAL_WEIGHT_0.005"], policy["uncertainty"])
    R.write(out / "paired_uncertainty.json", uncertainty)
    stress, stress_config = [], policy["execution_stress"]
    for capital in stress_config["initial_capital_rial"]:
        caps = {}
        for sym, rec in md.data.items():
            for i, day in enumerate(rec["dates"]):
                tv = rec["tval"][i]
                blocked = stress_config["blocked_single_price_bars"] and (not np.isfinite(rec["h"][i]) or
                    not np.isfinite(rec["l"][i]) or rec["h"][i] <= rec["l"][i])
                caps[day, sym] = max(0, float(tv)) * stress_config["participation_rate"] / capital if np.isfinite(tv) and not blocked else 0.0
        for name in ("QVT", "QVT_BUFFER", "MATCHED_EQUAL_WEIGHT"):
            for scenario, execution in [("delay", {"delay_sessions": stress_config["delay_sessions"]}),
                                        ("capacity", {"capacities": caps}),
                                        ("capacity_delay", {"capacities": caps, "delay_sessions": stress_config["delay_sessions"]})]:
                # Pure delay does not depend on account size.
                if scenario == "delay" and capital != stress_config["initial_capital_rial"][0]:
                    continue
                label = f"{name}_{scenario}_{capital}"
                perf, daily, ledger, trades = B.replay(selections[name], observation_dates, adj, md.cal, keys, 1, .005, RA, execution)
                stress.append({"strategy": name, "scenario": scenario, "initial_capital_rial": capital, **perf})
                for suffix, records in [("daily", daily), ("ledger", ledger), ("trades", trades)]:
                    pd.DataFrame(records).to_csv(out / f"stress_{label}_{suffix}.csv", index=False)
                print(f"Stress {label}: CAGR={perf['annualized_return_pct']:.2f}; cash={perf['avg_cash_pct']:.1f}%", flush=True)
    pd.DataFrame(stress).to_csv(out / "execution_stress.csv", index=False)
    diagnostics = factor_diagnostics(scores, md, keys, out)
    screening = []
    for name in selections:
        if name == "MATCHED_EQUAL_WEIGHT":
            continue
        candidate = table[table.strategy.eq(name)].set_index("cost_rate")
        ref = table[table.strategy.eq("MATCHED_EQUAL_WEIGHT")].set_index("cost_rate")
        y = years[years.strategy.eq(name) & years.cost_rate.eq(.005) & years.complete_year].set_index("year")
        ry = years[years.strategy.eq("MATCHED_EQUAL_WEIGHT") & years.cost_rate.eq(.005) & years.complete_year].set_index("year")
        fraction = float((y.return_pct > ry.return_pct).mean())
        excess = float(candidate.loc[.005, "annualized_return_pct"] - ref.loc[.005, "annualized_return_pct"])
        high = float(candidate.loc[.01, "annualized_return_pct"] - ref.loc[.01, "annualized_return_pct"])
        limits = policy["research_acceptance"]
        passed = (excess >= limits["min_excess_cagr_percentage_points"] and
                  abs(candidate.loc[.005, "max_drawdown_pct"]) <= limits["max_observed_drawdown_pct"] and
                  fraction >= limits["min_positive_year_fraction"] and high > 0)
        screening.append({"strategy": name, "screen_passed": bool(passed), "excess_cagr_pp": excess,
                          "high_cost_excess_cagr_pp": high, "positive_complete_year_fraction": fraction,
                          "complete_years": len(y), "promoted": False})
    R.write(out / "screening.json", screening)
    errors = []
    for key, item in manifest.items():
        if R.sha(item["path"]) != item["sha256"]:
            errors.append("source_changed:" + key)
    for sym, item in market_manifest.items():
        if R.sha(item["path"]) != item["sha256"]:
            errors.append("market_source_changed:" + sym)
    for cost in policy["cost_rates"]:
        old = latest["performance"][f"QVT_TOP10_1m_{cost:g}"]
        new = table[table.strategy.eq("QVT") & table.cost_rate.eq(cost)].iloc[0]
        if abs(new.annualized_return_pct - old["annualized_return_pct"]) > 1e-8:
            errors.append("baseline_reproduction_failed")
    if errors:
        R.write(out / "audit.json", {"status": "failed", "errors": errors})
        raise ValueError("Research audit failed; latest result unchanged")
    R.write(out / "audit.json", {"status": "passed", "errors": [], "checks": ["frozen_manifest", "market_manifest", "baseline_reproduction", "cash_nav_conservation", "shared_cohort", "shared_calendar"],
                                 "note": "Engineering consistency audit; not independent certification of source economics"})
    summary = {"version": "qvt-roadmap-research-v1", "mode": "research_only", "real_orders": 0,
               "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "run_path": str(out),
               "baseline_run_path": str(base), "policy_sha256": manifest["policy"]["sha256"],
               "n_comparisons": len(results), "n_variants": len(selections), "gaps": gap_summary,
               "factor_diagnostics": diagnostics, "uncertainty": uncertainty,
               "execution_stress": stress, "execution_stress_scope": stress_config["scope"],
               "screening": screening, "promotion_ready": False,
               "promotion_gates": {g: False for g in policy["mandatory_promotion_gates"]},
               "limits": ["Previously observed history", "76-point subset only", "Current universe survivorship bias", "No industry map or full dividends", "Volume gate does not prove fills", "No investable benchmark", "No brokerage access"]}
    R.write(out / "summary.json", summary)
    tmp = R.HERE / "output/roadmap_candidate.json.tmp"
    R.write(tmp, summary)
    tmp.replace(R.HERE / "output/roadmap_candidate.json")
    print(json.dumps({"run": str(out), "comparisons": len(results), "audit": "passed", "promotion_ready": False}), flush=True)


if __name__ == "__main__":
    main()
