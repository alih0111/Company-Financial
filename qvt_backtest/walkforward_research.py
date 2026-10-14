"""Causal, fixed-rule model selection with one continuous research account."""
import datetime as dt
import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import run as R
import reconstructed_replay as B
from audit_roadmap import check
from execute_roadmap import yearly


def training_metrics(frame, signal, policy):
    train = frame[frame.date.lt(signal)].sort_values("date")
    if train.empty:
        return None
    days = (pd.Timestamp(train.date.iloc[-1]) - pd.Timestamp(train.date.iloc[0])).days
    if days < policy["minimum_history_days"] or len(train) < policy["minimum_history_sessions"]:
        return None
    nav = train.nav.to_numpy(dtype=float)
    if not np.isfinite(nav).all() or (nav <= 0).any():
        raise ValueError("invalid training account")
    wealth = np.r_[1., nav]
    cagr = (nav[-1] ** (365.2425 / days) - 1) * 100
    drawdown = abs(float((wealth / np.maximum.accumulate(wealth) - 1).min() * 100))
    return {"training_start": train.date.iloc[0], "training_end": train.date.iloc[-1],
            "days": days, "sessions": len(train), "cagr_pct": cagr, "drawdown_pct": drawdown,
            "criterion": cagr - policy["drawdown_penalty"] * drawdown}


def choose_schedule(dates, candidate_daily, policy):
    """No outcome on or after a decision may affect that decision."""
    choices, metrics, schedule = [], [], {}
    previous_year, chosen = None, policy["default_strategy"]
    for day in sorted(dates):
        if day[:4] != previous_year:
            results = {name: training_metrics(candidate_daily[name], day, policy) for name in policy["candidates"]}
            enough = all(result is not None for result in results.values())
            chosen = (sorted(results, key=lambda name: (-results[name]["criterion"], name))[0]
                      if enough else policy["default_strategy"])
            choices.append({"signal_date": day, "chosen": chosen, "warmup_default": not enough})
            metrics.extend({"signal_date": day, "strategy": name, **result} for name, result in results.items() if result)
            previous_year = day[:4]
        schedule[day] = chosen
    return schedule, choices, metrics


def audit_schedule(schedule, choices, metrics, frames, policy):
    """Independent scalar reconstruction of every annual training decision."""
    errors = []
    for choice in choices:
        day, values, enough = choice["signal_date"], {}, True
        for name in policy["candidates"]:
            rows = sorted((r for r in frames[name].to_dict("records") if r["date"] < day), key=lambda r: r["date"])
            days = ((dt.date.fromisoformat(rows[-1]["date"]) - dt.date.fromisoformat(rows[0]["date"])).days if rows else 0)
            if not rows or days < policy["minimum_history_days"] or len(rows) < policy["minimum_history_sessions"]:
                enough = False
                continue
            peak, worst = 1., 0.
            for row in rows:
                peak = max(peak, row["nav"])
                worst = max(worst, (1 - row["nav"] / peak) * 100)
            cagr = (rows[-1]["nav"] ** (365.2425 / days) - 1) * 100
            values[name] = cagr - policy["drawdown_penalty"] * worst
            saved = [r for r in metrics if r["signal_date"] == day and r["strategy"] == name]
            if (len(saved) != 1 or saved[0]["training_end"] != rows[-1]["date"] or
                    saved[0]["training_end"] >= day or abs(saved[0]["criterion"] - values[name]) > 1e-8):
                errors.append("training_trace:" + day + ":" + name)
        expected = sorted(values, key=lambda name: (-values[name], name))[0] if enough else policy["default_strategy"]
        if choice["chosen"] != expected or choice["warmup_default"] != (not enough):
            errors.append("noncausal_or_incorrect_choice:" + day)
    for day, chosen in schedule.items():
        prior = [c for c in choices if c["signal_date"] <= day]
        if not prior or chosen != prior[-1]["chosen"]:
            errors.append("intra_year_switch:" + day)
    if errors:
        raise ValueError(",".join(errors))
    return {"status": "passed", "annual_decisions": len(choices), "same_day_outcomes_used": False,
            "scope": "Chronology and fixed selection arithmetic; not independent certification of source economics"}


def main():
    policy_path = R.HERE / "walkforward_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf8"))
    research = json.loads((R.HERE / "output/roadmap_latest.json").read_text(encoding="utf8"))
    prior = Path(research["run_path"])
    baseline = json.loads((R.HERE / "output/reconstructed_latest.json").read_text(encoding="utf8"))
    base = Path(baseline["run_path"])
    if research.get("independent_audit", {}).get("status") != "passed" or research["baseline_run_path"] != str(base):
        raise ValueError("Need matching audited baseline and fixed research")
    out = R.HERE / "output" / ("walkforward_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(parents=True, exist_ok=False)
    paths = {"policy": policy_path, "scores": base / "scores.parquet", "availability": base / "availability.csv", "code": Path(__file__)}
    for name in policy["candidates"]:
        paths["daily_" + name] = prior / f"{name}_{policy['training_cost_rate']:g}_daily.csv"
        paths["selection_" + name] = prior / f"{name}_selections.csv"
    manifest = {key: {"path": str(path), "sha256": R.sha(path)} for key, path in paths.items()}
    R.write(out / "manifest.json", manifest)
    for key, path in paths.items():
        shutil.copyfile(path, out / ("input_" + key + path.suffix))
    R.write(out / "registration.json", {"registered_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "policy_sha256": manifest["policy"]["sha256"], "context": policy["registration_context"]})
    scores = pd.read_parquet(out / "input_scores.parquet")
    scores["as_of"] = scores.as_of.astype(str).str[:10]
    frames = {name: pd.read_csv(out / ("input_daily_" + name + ".csv")) for name in policy["candidates"]}
    if len({tuple(frame.date) for frame in frames.values()}) != 1:
        raise ValueError("Candidate training calendars differ")
    schedule, choices, metrics = choose_schedule(scores.as_of.unique(), frames, policy)
    chronology = audit_schedule(schedule, choices, metrics, frames, policy)
    pd.DataFrame(choices).to_csv(out / "annual_choices.csv", index=False)
    pd.DataFrame(metrics).to_csv(out / "training_metrics.csv", index=False)
    R.write(out / "decision_schedule.json", schedule)
    R.write(out / "chronology_audit.json", chronology)
    candidate_selections = {name: pd.read_csv(out / ("input_selection_" + name + ".csv")) for name in policy["candidates"]}
    selected = pd.concat([candidate_selections[name][candidate_selections[name].as_of.eq(day)] for day, name in schedule.items()], ignore_index=True)
    selections = {"WALKFORWARD": selected, "QVT_FIXED": candidate_selections["QVT"], "MATCHED_EQUAL_WEIGHT": scores}
    md = R.V.MarketData(R.V.load_reference_data(), symbols=sorted(scores.symbol.unique()))
    keys, RA = R.V.tradability_keys(), R.V.load_portfolio_engine()
    adj = {s: {"dates": r["dates"], "adj": {d: float(c*f) for d,c,f in zip(r["dates"],r["c"],r["cf"])}} for s,r in md.data.items()}
    R.write(out / "certified_source_hashes.json", R.V.verify_frozen_shas())
    market = {s: {"path": str(R.V.RAW / f"raw_{s}_{r['ins']}.json.gz"), "sha256": R.sha(R.V.RAW / f"raw_{s}_{r['ins']}.json.gz")} for s,r in md.data.items()}
    R.write(out / "market_manifest.json", market)
    dates = [d for d in sorted(pd.read_csv(out / "input_availability.csv").date.unique()) if d >= scores.as_of.min()]
    results, annual = [], []
    for name, targets in selections.items():
        targets[["as_of","symbol","ui_score"]].to_csv(out / (name + "_selections.csv"), index=False)
        for cost in policy["cost_rates"]:
            label = f"{name}_{cost:g}"
            perf, daily, ledger, trades = B.replay(targets, dates, adj, md.cal, keys, 1, cost, RA)
            results.append({"strategy": name, "cost_rate": cost, **perf})
            annual.extend({"strategy": name, "cost_rate": cost, **row} for row in yearly(daily))
            for suffix, records in [("daily", daily), ("ledger", ledger), ("trades", trades)]:
                pd.DataFrame(records).to_csv(out / f"{label}_{suffix}.csv", index=False)
            print(f"{label}: CAGR={perf['annualized_return_pct']:.2f}, MDD={perf['max_drawdown_pct']:.2f}", flush=True)
    pd.DataFrame(results).to_csv(out / "comparisons.csv", index=False)
    pd.DataFrame(annual).to_csv(out / "yearly_returns.csv", index=False)
    for name, item in {**manifest, **market}.items():
        if R.sha(item["path"]) != item["sha256"]:
            raise ValueError("Source changed during chronological research: " + name)
    summary = {"version": policy["version"], "mode": "research_only", "real_orders": 0, "promotion_ready": False,
               "run_path": str(out), "baseline_run_path": str(base), "fixed_research_run_path": str(prior),
               "policy_sha256": manifest["policy"]["sha256"], "n_comparisons": len(results),
               "choices": choices, "chronology_audit": chronology, "results": results,
               "scope": policy["scope"], "limitations": [policy["registration_context"], "No untouched holdout or live promotion", "Training uses counterfactual candidate accounts; actual replay maintains one continuous account"]}
    R.write(out / "summary.json", summary)
    summary["independent_audit"] = check(out)
    R.write(out / "summary.json", summary)
    R.write(out / "publication.json", {"status": "passed", "summary_sha256": R.sha(out / "summary.json")})
    temp = R.HERE / "output/walkforward_latest.json.tmp"
    R.write(temp, summary)
    temp.replace(R.HERE / "output/walkforward_latest.json")
    print(json.dumps({"run": str(out), "audit": "passed", "promotion_ready": False}))


if __name__ == "__main__":
    main()
