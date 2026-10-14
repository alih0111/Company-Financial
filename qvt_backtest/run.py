"""Bounded, fixed-weight historical QVT subset diagnostic, read-only sources.

No historical validation claim for the live full model, no policy changes or
weight search. The old certified accounting engine is imported unchanged.
"""
from __future__ import annotations
import datetime as dt
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
ANA = ROOT / "canonical_postgres_v1_2_1/analytics_canonical_v1"
sys.path[:0] = [str(ROOT / "score_v2_research"), str(ANA), str(ROOT / "provenance_v1")]
import numpy as np
import pandas as pd
import v2lib as V
import score_v2_t_raw as TR
import score_v2_normalize as SN
import score_v4 as S4
from aligned_timing import align_returns


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False,
                               default=lambda value: value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else str(value)), encoding="utf8")


def ranked(values, higher=True):
    values = np.array(values, dtype=float)
    output = np.full(len(values), np.nan)
    present = np.isfinite(values)
    if present.sum() < 10:
        return output
    bounds = SN._winsor_bounds(values[present].tolist(), SN.RankPolicy())
    safe = values[present] if bounds is None else np.clip(values[present], *bounds)
    percentiles = S4.midrank(dict(enumerate(safe)), higher_is_better=higher)
    output[present] = [percentiles[i] for i in range(len(safe))]
    return output


def historical_timing(md, symbols, date):
    day = dt.date.fromisoformat(date)
    histories, securities, meta = {}, {}, {}
    for sym in symbols:
        securities[sym] = sym
        meta[sym] = {"model_family": "general", "industry": None}
        if sym not in md.data:
            continue
        record = md.data[sym]
        end = md.idx_at(sym, date)
        # Only past/current corporate events affect features. Never stamp a
        # fabricated historical collection time on recently acquired archives.
        causal = md.asof_factors(sym, date)
        histories[sym] = [{"date": dt.date.fromisoformat(record["dates"][k]),
                           "close": float(record["c"][k] * causal[k]),
                           "tv": float(record["tval"][k]), "collected_at": None}
                          for k in range(end + 1)]
    raw = TR.build_t_raw(histories, securities, meta, as_of=day)
    alignment = align_returns(raw, meta)
    return raw, alignment


def build_scores(panel, md, current, weights):
    family = {r["symbol"]: r["model_family"] for r in current["ranked"] + current["unscored"]}
    panel = panel[panel.symbol.map(family).eq("general")].copy()
    if (pd.to_datetime(panel.knowledge_cutoff, utc=True) > pd.to_datetime(panel.as_of, utc=True) + pd.Timedelta(days=1)).any():
        raise ValueError("historical panel contains future knowledge cutoff")
    output, timing_output, coverage, alignments = [], [], [], {}
    for date, group in panel.groupby("as_of", sort=True):
        date = str(date)[:10]
        group = group.sort_values("symbol").copy()
        raw_t, alignment = historical_timing(md, list(group.symbol), date)
        alignments[date] = alignment
        raw = {
            "roe_level": group.roe.to_numpy(dtype=float),
            "cash_conversion": group.cash_conversion.to_numpy(dtype=float),
            "leverage": group.debt_ratio.to_numpy(dtype=float),
            "pe": group.pe.to_numpy(dtype=float), "pb": group.pb.to_numpy(dtype=float), "ps": group.ps.to_numpy(dtype=float),
            "operating_margin": group.operating_margin.to_numpy(dtype=float), "net_margin": group.net_margin.to_numpy(dtype=float),
        }
        for factor in ("momentum_6m_rel", "momentum_3m_rel", "liquidity", "low_volatility"):
            raw[factor] = np.array([raw_t[sym][factor]["raw_value"] if raw_t[sym][factor]["status"] == "valid" else np.nan
                                    for sym in group.symbol], dtype=float)
        valid = np.ones(len(group), dtype=bool)
        for values in raw.values():
            valid &= np.isfinite(values)
        for field in ("roe_level", "pe", "pb", "ps"):
            valid &= raw[field] > 0
        valid &= raw["leverage"] >= 0
        valid &= group.net_profit_ttm.to_numpy(dtype=float) > 0
        valid &= group.revenue_ttm.to_numpy(dtype=float) > 0
        tv = np.ones(len(group), dtype=bool)
        t_factors = ("momentum_6m_rel", "momentum_3m_rel", "liquidity", "low_volatility")
        for f in t_factors:
            tv &= np.isfinite(raw[f])
        if tv.sum() >= 20:
            ts = group.loc[tv, ["as_of", "symbol", "ui_score", "ret_21", "ret_63"]].copy()
            ts.rename(columns={"ui_score": "baseline_score"}, inplace=True)
            ts["ui_score"] = sum(weights[f] * ranked(raw[f][tv], f != "low_volatility") for f in t_factors)
            timing_output.append(ts)
        coverage.append({"as_of": date, "source_rows": len(group), "complete_rows": int(valid.sum()),
                         "complete_timing_rows": int(tv.sum()), "excluded_rows": int((~valid).sum()),
                         **{f"finite_{f}": int(np.isfinite(v).sum()) for f, v in raw.items()}})
        if valid.sum() < 20:
            print(f"{date}: complete QVT subset {valid.sum()}; complete timing {tv.sum()}", flush=True)
            continue
        # All strategies and all factors use the same complete date population.
        ranks = {f: ranked(values[valid], f not in ("pe", "pb", "ps", "leverage", "low_volatility"))
                 for f, values in raw.items()}
        ranks["margins"] = .6 * ranks["operating_margin"] + .4 * ranks["net_margin"]
        result = group.loc[valid, ["as_of", "symbol", "ui_score", "ret_21", "ret_63"]].copy()
        result.rename(columns={"ui_score": "baseline_score"}, inplace=True)
        result["ui_score"] = sum(weights[f] * ranks[f] for f in weights)
        for f in weights:
            result[f"p_{f}"] = ranks[f]
        output.append(result)
        print(f"{date}: {valid.sum()} complete / {len(group)} general", flush=True)
    return (pd.concat(output, ignore_index=True) if output else pd.DataFrame(),
            pd.concat(timing_output, ignore_index=True), coverage, alignments)


def performance(rows):
    nav = np.array([1.0] + [r["value_post_trade"] for r in rows])
    start, end = (dt.date.fromisoformat(rows[i]["exec_date"]) for i in (0, -1))
    years = (end - start).days / 365.2425
    return {"cumulative_return_pct": float((nav[-1] - 1) * 100),
            "annualized_return_pct": float((nav[-1] ** (1 / years) - 1) * 100),
            "max_drawdown_pct": float((nav / np.maximum.accumulate(nav) - 1).min() * 100),
            "execution_start": start.isoformat(), "execution_end": end.isoformat(), "elapsed_years": years,
            "n_rebalances": len(rows), "avg_cash_pct": float(np.mean([r["cash_weight"] for r in rows]) * 100),
            "avg_turnover_pct": float(np.mean([r["turnover"] for r in rows]) * 100),
            "failed_target_count": sum(r["failed_targets"] for r in rows)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=Path, help="resume accounting from this unchanged run's saved scores")
    args = parser.parse_args()
    protocol = json.loads((HERE / "protocol.json").read_text(encoding="utf8"))
    timing_protocol = json.loads((HERE / "timing_protocol.json").read_text(encoding="utf8"))
    run = args.resume or HERE / "output" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.resume:
        if sha(run / "protocol.json") != sha(HERE / "protocol.json") or sha(run / "timing_protocol.json") != sha(HERE / "timing_protocol.json"):
            # Compare semantic JSON, as the run copy was pretty-printed.
            if json.loads((run / "protocol.json").read_text(encoding="utf8")) != protocol or json.loads((run / "timing_protocol.json").read_text(encoding="utf8")) != timing_protocol:
                raise ValueError("cannot resume with changed protocol")
        if (run / "summary.json").exists():
            raise ValueError("completed research run cannot be overwritten")
    else:
        run.mkdir(parents=True, exist_ok=False)
        write(run / "protocol.json", protocol)
        write(run / "timing_protocol.json", timing_protocol)
    hashes = V.verify_frozen_shas()
    # Full feature file is immutable input only; features and returns are kept
    # apart: build_scores never receives an outcome in a factor calculation.
    source = V.PANEL_PQ
    panel = pd.read_parquet(ROOT / "score_v2_research/pit_feature_panel.parquet")
    panel_sha = sha(ROOT / "score_v2_research/pit_feature_panel.parquet")
    current_path = ROOT / "qvt_paper/output/current_ranking.json"
    current = json.loads(current_path.read_text(encoding="utf8"))
    reference = V.load_reference_data()
    md = V.MarketData(reference, symbols=sorted(panel.symbol.unique()))
    if args.resume:
        scored = pd.read_parquet(run / "historical_scores.parquet")
        coverage = pd.read_csv(run / "coverage.csv").to_dict("records")
        full_scored = pd.read_parquet(run / "full_subset_scores.parquet") if (run / "full_subset_scores.parquet").exists() else pd.DataFrame()
    else:
        full_scored, scored, coverage, alignments = build_scores(panel, md, current, protocol["weights"])
        if not full_scored.empty:
            full_scored.to_parquet(run / "full_subset_scores.parquet", index=False)
        scored.to_parquet(run / "historical_scores.parquet", index=False)
        pd.DataFrame(coverage).to_csv(run / "coverage.csv", index=False)
        write(run / "alignment.json", alignments)
    RA = V.load_portfolio_engine()
    adj = {sym: {"dates": row["dates"], "adj": {d: float(c * f) for d, c, f in zip(row["dates"], row["c"], row["cf"])}}
           for sym, row in md.data.items()}
    keys = V.tradability_keys()
    strategies = {
        "TIMING_TOP10": scored.sort_values(["as_of", "ui_score", "symbol"], ascending=[True, False, True]).groupby("as_of", sort=True).head(10),
        "TIMING_BOTTOM10": scored.sort_values(["as_of", "ui_score", "symbol"]).groupby("as_of", sort=True).head(10),
        "V1_MATCHED_TOP10": scored.sort_values(["as_of", "baseline_score", "symbol"], ascending=[True, False, True]).groupby("as_of", sort=True).head(10),
        "MATCHED_EQUAL_WEIGHT": scored,
    }
    measures, yearly, curves = {}, [], []
    for name, selected in strategies.items():
        selected[["as_of", "symbol", "ui_score"]].to_csv(run / f"{name}_selections.csv", index=False)
        for rate in protocol["cost_rates"]:
            label = f"{name}_{rate:g}"
            rows, holds, trades = RA.simulate(selected, adj, md.cal, keys, 1.0, rate)
            measures[label] = performance(rows)
            pd.DataFrame(rows).to_csv(run / f"{label}_nav.csv", index=False)
            pd.DataFrame(trades).to_parquet(run / f"{label}_trades.parquet", index=False)
            for r in rows:
                curves.append({"strategy": name, "cost_rate": rate, "date": r["exec_date"], "nav": r["value_post_trade"]})
            # Allocate each actual rebalance-to-rebalance interval to its end
            # year; do not invent a calendar-year closing observation.
            by_year = {}
            for previous, following in zip(rows, rows[1:]):
                y = following["exec_date"][:4]
                by_year[y] = by_year.get(y, 1.0) * following["value_post_trade"] / previous["value_post_trade"]
            for y, wealth in by_year.items():
                yearly.append({"strategy": name, "cost_rate": rate, "end_year": y, "return_pct": 100 * (wealth - 1)})
    pd.DataFrame(yearly).to_csv(run / "yearly_intervals.csv", index=False)
    pd.DataFrame(curves).to_csv(run / "curves.csv", index=False)
    diagnostics = {}
    for horizon in (21, 63):
        monthly = []
        for date, g in scored.groupby("as_of", sort=True):
            paired = g[["ui_score", f"ret_{horizon}"]].dropna()
            ic = paired.ui_score.rank(method="average").corr(paired[f"ret_{horizon}"].rank(method="average"))
            if math.isfinite(ic): monthly.append(float(ic))
        diagnostics[str(horizon)] = {"mean_spearman": float(np.mean(monthly)), "n_dates": len(monthly),
                                    "positive_fraction": float(np.mean(np.array(monthly) > 0))}
    summary = {"version": timing_protocol["version"], "exact_live_model": False, "score_ceiling": timing_protocol["score_ceiling"],
               "full_qvt_status": "insufficient_historical_financials" if full_scored.empty else "subset_available",
               "status": "diagnostic_only", "as_of_start": str(scored.as_of.min()), "as_of_end": str(scored.as_of.max()),
               "n_dates": len(coverage), "n_rows": len(scored), "n_symbols": scored.symbol.nunique(),
               "min_complete": min(r["complete_timing_rows"] for r in coverage), "max_complete": max(r["complete_timing_rows"] for r in coverage),
               "max_complete_financial_subset": max(r["complete_rows"] for r in coverage),
               "alignment_details_saved": (run / "alignment.json").exists(),
               "input_hashes": {**hashes, "feature_panel": panel_sha, "current_family_map": sha(current_path), "protocol": sha(HERE / "protocol.json"), "timing_protocol": sha(HERE / "timing_protocol.json")},
               "performance": measures, "ic": diagnostics, "limitations": protocol["limitations"],
               "run_path": str(run), "generated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    write(run / "summary.json", summary)
    write(HERE / "output/latest.json", summary)
    print(json.dumps({"run": str(run), "base_top10": measures["TIMING_TOP10_0.005"], "benchmark": measures["MATCHED_EQUAL_WEIGHT_0.005"]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
