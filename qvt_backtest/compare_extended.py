"""Fixed 76-vs-89 common-cohort research. Never replaces the app baseline."""
import datetime as dt
import json
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import run as R
import reconstructed_replay as B
from execute_roadmap import yearly
from audit_roadmap import check


def main():
    policy_path = R.HERE / "extended_research_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf8"))
    baseline = json.loads((R.HERE / "output/reconstructed_latest.json").read_text(encoding="utf8"))
    base = Path(baseline["run_path"])
    if json.loads((base / "audit.json").read_text(encoding="utf8"))["status"] != "passed":
        raise ValueError("baseline unaudited")
    out = R.HERE / "output" / ("extended_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    out.mkdir(parents=True, exist_ok=False)
    paths = {"policy": policy_path, "scores": base / "scores.parquet", "financial_inputs": base / "reconstructed_inputs.parquet",
             "extended": B.HISTORY / "extended_financial_panel.csv", "code": Path(__file__)}
    manifest = {k: {"path": str(p), "sha256": R.sha(p)} for k, p in paths.items()}
    R.write(out / "manifest.json", manifest)
    for key, path in paths.items():
        shutil.copyfile(path, out / ("input_" + key + path.suffix))
    R.write(out / "registration.json", {"registered_at": dt.datetime.now(dt.timezone.utc).isoformat(), "policy_sha256": manifest["policy"]["sha256"], "context": policy["registration_context"]})
    core = pd.read_parquet(out / "input_scores.parquet")
    core["as_of"] = core.as_of.astype(str).str[:10]
    financial = pd.read_parquet(out / "input_financial_inputs.parquet")
    financial["as_of"] = financial.as_of.astype(str).str[:10]
    extra = pd.read_csv(out / "input_extended.csv")
    scores = core.merge(extra, left_on=["as_of", "symbol"], right_on=["date", "symbol"], validate="one_to_one")
    scores = scores.merge(financial[["as_of", "symbol", "financial_period_end", "used_older_income_report"]], on=["as_of", "symbol"], validate="one_to_one")
    factors = list(policy["additional_weights"])
    finite = np.isfinite(scores[factors].to_numpy(dtype=float)).all(axis=1)
    age = (pd.to_datetime(scores.as_of) - pd.to_datetime(scores.financial_period_end)).dt.days
    scores = scores[finite & age.between(0, 365) & ~scores.used_older_income_report].copy()
    if any(pd.Timestamp(r.published_at).to_pydatetime() >= B.cutoff_for(r.as_of) for r in scores.itertuples()):
        raise ValueError("future or boundary publication")
    groups = []
    for date, group in scores.groupby("as_of", sort=True):
        if len(group) < policy["minimum_population"]:
            continue
        group = group.copy()
        for factor, weight in policy["additional_weights"].items():
            group["p_" + factor] = R.ranked(group[factor].to_numpy(), factor != "earnings_quality")
        group["extended_score"] = group.ui_score + sum(weight * group["p_" + f] for f, weight in policy["additional_weights"].items())
        groups.append(group)
    if not groups:
        R.write(out / "blocked.json", {"reason": "insufficient_common_complete_cohort"})
        raise ValueError("No extended cohort has twenty complete members")
    scored = pd.concat(groups, ignore_index=True)
    scored.to_parquet(out / "extended_scores.parquet", index=False)
    R.write(out / "certified_source_hashes.json", R.V.verify_frozen_shas())
    md = R.V.MarketData(R.V.load_reference_data(), symbols=sorted(scored.symbol.unique()))
    keys, RA = R.V.tradability_keys(), R.V.load_portfolio_engine()
    adj = {s: {"dates": r["dates"], "adj": {d: float(c * f) for d, c, f in zip(r["dates"], r["c"], r["cf"])}} for s, r in md.data.items()}
    market = {sym: {"path": str(R.V.RAW / f"raw_{sym}_{rec['ins']}.json.gz"), "sha256": R.sha(R.V.RAW / f"raw_{sym}_{rec['ins']}.json.gz")}
              for sym, rec in md.data.items()}
    R.write(out / "market_manifest.json", market)
    dates = [d for d in sorted(pd.read_csv(base / "availability.csv").date.unique()) if d >= scored.as_of.min()]
    extended = scored.copy()
    extended["ui_score"] = extended.extended_score
    selections = {"CORE76_COMMON": scored.sort_values(["as_of", "ui_score", "symbol"], ascending=[True, False, True]).groupby("as_of").head(10),
                  "EXTENDED89_COMMON": extended.sort_values(["as_of", "ui_score", "symbol"], ascending=[True, False, True]).groupby("as_of").head(10),
                  "MATCHED_EQUAL_WEIGHT": scored}
    results, annual = [], []
    for name, selected in selections.items():
        selected[["as_of", "symbol", "ui_score"]].to_csv(out / (name + "_selections.csv"), index=False)
        for cost in policy["cost_rates"]:
            label = f"{name}_{cost:g}"
            perf, daily, ledger, trades = B.replay(selected, dates, adj, md.cal, keys, 1, cost, RA)
            results.append({"strategy": name, "cost_rate": cost, **perf})
            annual.extend({"strategy": name, "cost_rate": cost, **y} for y in yearly(daily))
            for suffix, records in [("daily", daily), ("ledger", ledger), ("trades", trades)]:
                pd.DataFrame(records).to_csv(out / f"{label}_{suffix}.csv", index=False)
            print(f"{label}: CAGR={perf['annualized_return_pct']:.2f}, MDD={perf['max_drawdown_pct']:.2f}", flush=True)
    pd.DataFrame(results).to_csv(out / "comparisons.csv", index=False)
    pd.DataFrame(annual).to_csv(out / "yearly_returns.csv", index=False)
    for name, item in manifest.items():
        if R.sha(item["path"]) != item["sha256"]:
            raise ValueError("source changed during extended comparison: " + name)
    for item in market.values():
        if R.sha(item["path"]) != item["sha256"]:
            raise ValueError("market changed during extended comparison")
    summary = {"version": "qvt-extended-diagnostic-v1", "mode": "research_only", "real_orders": 0,
               "promotion_ready": False, "run_path": str(out), "policy_sha256": manifest["policy"]["sha256"],
               "baseline_run_path": str(base),
               "n_comparisons": len(results), "n_rows": len(scored), "n_dates": scored.as_of.nunique(),
               "n_symbols": scored.symbol.nunique(), "score_ceiling": 89, "scope": policy["scope"], "results": results}
    R.write(out / "summary.json", summary)
    summary["independent_audit"] = check(out)
    R.write(out / "summary.json", summary)
    temp = R.HERE / "output/extended_latest.json.tmp"
    R.write(temp, summary)
    temp.replace(R.HERE / "output/extended_latest.json")
    print(json.dumps({"run": str(out), "n_rows": len(scored), "audit": "passed"}))


if __name__ == "__main__":
    main()
