"""Separate output consistency checks, never certifies full financial economics."""
from pathlib import Path
import json
import hashlib
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(run):
    run = Path(run)
    summary = json.loads((run / "summary.json").read_text(encoding="utf8"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf8"))
    errors, checked = [], 0
    def require(value, message):
        if not value:
            errors.append(message)
    require(summary["mode"] == "research_only" and summary["real_orders"] == 0 and summary["promotion_ready"] is False, "scope_or_order_contract")
    policy = json.loads((run / "input_policy.json").read_text(encoding="utf8"))
    require(sha(run / "input_policy.json") == summary["policy_sha256"], "policy_hash")
    for name, item in manifest.items():
        # Verify retained inputs even if original sources later change.
        frozen = run / ("input_" + name + Path(item["path"]).suffix)
        require(frozen.is_file() and sha(frozen) == item["sha256"], "frozen_input:" + name)
    scores = pd.read_parquet(run / "input_scores.parquet")
    scores["as_of"] = scores.as_of.astype(str).str[:10]
    require(not scores.duplicated(["as_of", "symbol"]).any(), "duplicate_score_key")
    cohort = set(zip(scores.as_of, scores.symbol))
    for path in run.glob("*_selections.csv"):
        selected = pd.read_csv(path)
        require(set(zip(selected.as_of, selected.symbol)) <= cohort, "outside_cohort:" + path.name)
        if not path.name.startswith("MATCHED_EQUAL_WEIGHT"):
            require(selected.groupby("as_of").size().max() <= policy["position_limit"], "position_limit:" + path.name)
    comparisons = pd.read_csv(run / "comparisons.csv")
    require(len(comparisons) == summary["n_comparisons"], "comparison_count")
    reference_dates = None
    for ledger_path in run.glob("*_ledger.csv"):
        prefix = ledger_path.name.removesuffix("_ledger.csv")
        ledger = pd.read_csv(ledger_path)
        daily = pd.read_csv(run / (prefix + "_daily.csv"))
        trades_path = run / (prefix + "_trades.csv")
        trades = pd.read_csv(trades_path) if trades_path.stat().st_size > 2 else pd.DataFrame()
        require(not daily.date.duplicated().any() and daily.date.is_monotonic_increasing, "daily_calendar:" + prefix)
        require(np.isfinite(daily.nav).all() and daily.nav.gt(0).all(), "finite_positive_nav:" + prefix)
        require(daily.cash_weight.between(-1e-9, 1 + 1e-9).all(), "cash_bounds:" + prefix)
        require(not ledger.exec_date.duplicated().any(), "duplicate_rebalance:" + prefix)
        require(ledger.exec_date.lt(daily.date.max()).all(), "final_mark_traded:" + prefix)
        require(ledger.score_date.lt(ledger.exec_date).all(), "execution_not_after_signal:" + prefix)
        require(np.allclose(ledger.value_pre_trade - ledger.transaction_cost, ledger.value_post_trade, atol=1e-9, rtol=0), "nav_conservation:" + prefix)
        require(np.allclose(ledger.cash_pre + ledger.sell_notional - ledger.buy_notional - ledger.transaction_cost,
                            ledger.cash_post, atol=1e-9, rtol=0), "cash_conservation:" + prefix)
        require(np.allclose(daily.set_index("date").loc[ledger.exec_date].nav, ledger.value_post_trade, atol=1e-9, rtol=0), "daily_ledger_match:" + prefix)
        if not trades.empty:
            require(trades.notional.gt(0).all() and trades.cost.ge(0).all(), "invalid_trade:" + prefix)
            sums = trades.groupby("exec_date").agg(notional=("notional", "sum"), cost=("cost", "sum"))
            aligned = sums.reindex(ledger.exec_date, fill_value=0)
            require(np.allclose(aligned.notional, ledger.traded_notional, atol=1e-9, rtol=0), "trade_notional:" + prefix)
            require(np.allclose(aligned.cost, ledger.transaction_cost, atol=1e-9, rtol=0), "trade_cost:" + prefix)
        if not prefix.startswith("stress_"):
            dates = list(daily.date)
            reference_dates = reference_dates or dates
            require(dates == reference_dates, "unequal_comparison_calendar:" + prefix)
            strategy, cost = prefix.rsplit("_", 1)
            row = comparisons[comparisons.strategy.eq(strategy) & comparisons.cost_rate.eq(float(cost))].iloc[0]
            wealth = np.r_[1., daily.nav.to_numpy()]
            years = (pd.Timestamp(daily.date.iloc[-1]) - pd.Timestamp(daily.date.iloc[0])).days / 365.2425
            require(abs((wealth[-1] ** (1 / years) - 1) * 100 - row.annualized_return_pct) < 1e-7, "cagr:" + prefix)
            require(abs((wealth / np.maximum.accumulate(wealth) - 1).min() * 100 - row.max_drawdown_pct) < 1e-7, "drawdown:" + prefix)
        checked += 1
    report = {"status": "passed" if not errors else "failed", "errors": errors, "checked_scenarios": checked,
              "scope": "Independent implementation of output accounting/cohort checks; corporate actions and source completeness remain uncertified"}
    (run / "independent_audit.json").write_text(json.dumps(report, indent=2), encoding="utf8")
    if errors:
        raise ValueError("Research consistency audit failed: " + ",".join(errors[:8]))
    return report


def main():
    latest_path = HERE / "output/roadmap_latest.json"
    candidate = HERE / "output/roadmap_candidate.json"
    summary = json.loads((candidate if candidate.exists() else latest_path).read_text(encoding="utf8"))
    result = check(summary["run_path"])
    # App publication requires this separate audit and exact summary hash.
    summary["independent_audit"] = result
    run = Path(summary["run_path"])
    payload = json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False)
    (run / "summary.json").write_text(payload, encoding="utf8")
    (run / "publication.json").write_text(json.dumps({"summary_sha256": sha(run / "summary.json"), "status": "passed"}), encoding="utf8")
    tmp = latest_path.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf8")
    tmp.replace(latest_path)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
