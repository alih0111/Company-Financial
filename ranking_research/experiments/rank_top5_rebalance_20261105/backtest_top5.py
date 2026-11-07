"""Standalone top-5 quarterly rebalance backtest from 1402 (2023-03-21) onward.

READ-ONLY EXPERIMENT. It consumes frozen, certified local inputs and writes
every artifact into its own directory. It never touches production data,
pipelines, ledgers, or the client.

Recipe requested by the owner:
  - Start with 100,000,000 Toman on the first session of 1402.
  - Buy the top names of the locked P1 ranking (same engine and contract
    weights as the ranking page artifact, build_latest_ranking.py).
  - Hold ~3 months (63 trading sessions). At each rebalance, sell every held
    name that left the new top-5 and buy the entrants with the freed cash,
    equally. Survivors are not re-equalized (replace-only policy).
  - Value the portfolio at the last available adjusted close every session
    until the end of certified price data (2026-09-30).

Conventions copied from the repo's own frozen replay (return_v8.engine.simulate
and return_v5 registration):
  - execution at the NEXT session's open after a decision (no look-ahead),
  - fee 0.5% per side (cost_per_side=.005), gross variant also reported,
  - orders for halted names retry each session until filled or superseded,
  - fractional index units on the certified tsetmc_gap_rule_v1 adjusted chain
    (cash dividends act as automatic reinvestment through the chain).

`build_context()` + `run_variant(ctx, ...)` are importable so sensitivity
sweeps (sweep.py) reuse the exact same mechanics.
"""
from __future__ import annotations

import json
import sys
from bisect import bisect_right
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "score_v2_research"))

import v2lib as V  # noqa: E402  (cached reference data only; no DB access)
from ranking_research.return_v8.engine import scores as score_engine  # noqa: E402
from ranking_research.return_v8.features import FIELDS, penalties, ranks  # noqa: E402
from ranking_research.return_v11.prepare import build_monthly  # noqa: E402

CONTRACT = ROOT / "ranking_research/output/return_v12_28/v12_28_20261022_future_eval_infrastructure_01/future_evaluation_contract.locked.json"
UNIVERSE = ROOT / "ranking_research/output/return_v12_30/v12_30_20261022_data_procurement_pack_01/frozen_universe_identity_map.csv"
PANEL = ROOT / "ranking_research/output/return_v12_23/v12_23_20261021_fresh_local_baseline_01/reconstruction/fresh_feature_panel.parquet"
MONTHLY_EVENTS = ROOT / "fundamental_event_research/monthly_sales_events_universe_v1_1.parquet"

START_GREG = "2023-03-21"      # 1402-01-01
END_GREG = "2026-09-30"        # end of certified corporate-action window
CADENCE = 63                   # ~3 months in sessions
N_NAMES = 5
FEE = 0.005                    # per side, repo convention (cost_per_side)
FINANCIAL = [i for i in range(21) if i not in (15, 19, 20)]


def apply_monthly_correction(panel: pd.DataFrame) -> pd.DataFrame:
    """Replay the locked V11 monthly-sales chain for every decision date.

    Same correction the official V12.32+ chain applies at 2026-02-24
    (extract_local_locked_panel.py): replace sales_growth_12m, sales_growth_3m
    and sales_stability with knowledge-time replayed values (verified
    corrections at signal entry; unverified corrections mask the prior value).
    """
    events = pd.read_parquet(MONTHLY_EVENTS)
    dates = sorted(panel.decision_time.astype(str).unique())
    feat = panel[["decision_time", "symbol", "company_id"]].copy()
    feat["decision_time"] = feat.decision_time.astype(str)
    monthly = build_monthly(events, feat, dates, [], jalali=True, keep_corrections=True)
    out = panel.copy()
    out["decision_time"] = out.decision_time.astype(str)
    out = out.drop(columns=["sales_growth_12m", "sales_growth_3m", "sales_stability"]).merge(
        monthly[["decision_time", "symbol", "company_id", "sales_growth_12m", "sales_growth_3m", "sales_stability"]],
        on=["decision_time", "symbol", "company_id"], how="left", validate="one_to_one",
    )
    return out


def load_scores(panel: pd.DataFrame, contract: dict, syms: list[str]) -> dict[str, dict[str, np.ndarray]]:
    """Score every panel decision date exactly like build_latest_ranking.py."""
    dates = sorted(panel.decision_time.astype(str).unique())
    out: dict[str, dict[str, np.ndarray]] = {}
    for method in ("P1", "P3"):
        mc = next(m for m in contract["methods"] if m["method_id"] == method)
        weights = np.asarray(mc["weights"], dtype=float)
        per_date: dict[str, np.ndarray] = {}
        for d in dates:
            rows = panel.loc[panel.decision_time.astype(str).eq(d)]
            if len(rows) != len(syms) or rows.symbol.astype(str).nunique() != len(syms):
                raise SystemExit(f"Decision {d}: universe grid incomplete ({len(rows)})")
            rows = rows.set_index("symbol").reindex(syms).reset_index()
            x = rows[FIELDS].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
            observed = np.isfinite(x)
            for index, upper in ((12, 60), (13, 100), (14, 30)):
                observed[:, index] &= (x[:, index] > 0) & (x[:, index] <= upper)
            net = pd.to_numeric(rows.net_profit_ttm, errors="coerce").to_numpy(dtype=float)
            dq = pd.to_numeric(rows.dq, errors="coerce").to_numpy(dtype=float)
            if not np.isfinite(dq).all():
                raise SystemExit(f"Decision {d}: non-finite dq present")
            tensor = {
                "rank": ranks(x)[None, :, :],
                "observed": observed[None, :, :],
                "penalty": penalties(x, net)[None, :, :],
                "dq": dq,
            }
            config = {"weights": weights, "vol_direction": "lower", "missing": "defaults", "penalties": True, "dq": True}
            value = score_engine(tensor, config)[0]
            coverage = (observed[:, FINANCIAL] @ weights[FINANCIAL]) / weights[FINANCIAL].sum()
            value[coverage < 0.5] = np.nan
            per_date[d] = value
        out[method] = per_date
    return out


def top_k_order(scores: np.ndarray, symbol_index: np.ndarray) -> list[int]:
    """Rank order: score desc, frozen symbol_index asc (page artifact rule)."""
    valid = np.isfinite(scores)
    return sorted(
        (i for i in range(len(scores)) if valid[i]),
        key=lambda i: (-float(scores[i]), int(symbol_index[i])),
    )


def build_context() -> SimpleNamespace:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    universe = pd.read_csv(UNIVERSE, dtype={"symbol": str, "company_id": str})
    panel = pd.read_parquet(PANEL)
    panel_corrected = apply_monthly_correction(panel)

    ref = V.load_reference_data()
    syms = sorted(universe.symbol.astype(str).unique())
    md = V.MarketData(ref, symbols=syms)
    missing_md = [s for s in syms if s not in md.data]
    if missing_md:
        raise SystemExit(f"No market data for: {missing_md}")

    score_tables = load_scores(panel_corrected, contract, syms)
    score_tables_raw = load_scores(panel, contract, syms)
    sym_index = {s: int(i) for i, s in zip(universe.symbol_index, universe.symbol)}
    sym_pos = {s: i for i, s in enumerate(syms)}

    decision_dates = sorted(score_tables["P1"].keys())
    cal = [d for d in ref["cal"] if START_GREG <= d <= END_GREG]

    def last_decision(today: str) -> str:
        k = bisect_right(decision_dates, today) - 1
        if k < 0:
            raise SystemExit("No decision date before first session")
        return decision_dates[k]

    def mark(sym: str, day: str) -> tuple[float, str]:
        rec = md.data[sym]
        k = bisect_right(rec["dates"], day) - 1
        if k < 0 or rec["c"][k] <= 0:
            return np.nan, ""
        return float(rec["c"][k]) * float(rec["cf"][k]), rec["dates"][k]

    def open_price(sym: str, day: str) -> float:
        rec = md.data[sym]
        k = rec["dmap"].get(day)
        if k is None:
            return np.nan
        # tradable session only: same good-day contract as return_v8 tensors()
        if not (rec["vol"][k] > 0 and rec["tval"][k] > 0):
            return np.nan
        o = float(rec["o"][k])
        return o * float(rec["cf"][k]) if np.isfinite(o) and o > 0 else np.nan

    return SimpleNamespace(
        contract=contract, universe=universe, syms=syms, md=md,
        score_tables=score_tables, score_tables_raw=score_tables_raw,
        sym_index=sym_index, sym_pos=sym_pos, decision_dates=decision_dates,
        cal=cal, last_decision=last_decision, mark=mark, open_price=open_price,
    )


def run_variant(ctx: SimpleNamespace, method: str = "P1", fee: float = FEE,
                re_equalize: bool = False, cadence: int = CADENCE,
                n_names: int = N_NAMES, tables: dict | None = None,
                event_driven: bool = False, cooldown: int = 0,
                exit_rank: int | None = None, entry_weighting: str = "equal",
                schedule_override: set[int] | None = None) -> dict:
    """event_driven=True mimics the owner's real workflow: every time the
    ranking refreshes on new reports (new panel decision date), re-align the
    portfolio to the new top-n at the next open. cooldown optionally enforces
    a minimum number of sessions between rebalances.

    exit_rank adds a hold buffer: a held name is only sold when its rank falls
    beyond exit_rank (> n_names), while new entries still come from the
    current top n_names. entry_weighting='score' splits the entrant budget
    proportionally to P1 score instead of equally."""
    tables = tables if tables is not None else ctx.score_tables
    cal, md = ctx.cal, ctx.md
    syms = ctx.syms
    cash = 100_000_000.0
    units: dict[str, float] = {}
    pending_sells: set[str] = set()          # full exits
    pending_buys: dict[str, float] = {}      # replace-only entrant budgets (incl. fee)
    pending_reweight: set[str] = set()       # re-equalize variant: target 1/n at next open
    nav_rows, trade_rows, rebal_rows = [], [], []
    peak, max_dd = cash, 0.0
    schedule = schedule_override if schedule_override is not None else (
        set() if event_driven else set(range(0, len(cal), cadence)))
    marks: dict[str, tuple[float, str]] = {}
    last_processed_decision = ""
    last_rebalance_i = -(cooldown + 1) if cooldown else None

    for i, day in enumerate(cal):
        # ---- execute pending orders at today's open (decided at an earlier close)
        for sym in sorted(pending_sells):
            op = ctx.open_price(sym, day)
            if np.isfinite(op) and sym in units:
                gross = units[sym] * op
                cash += gross * (1 - fee)
                trade_rows.append({"session": day, "symbol": sym, "side": "SELL",
                                   "gross_toman": gross, "fee_toman": gross * fee,
                                   "units": units[sym], "exec_price_adj": op})
                del units[sym]
        pending_sells = {s for s in pending_sells if s in units}

        if pending_reweight:
            op_now = {s: ctx.open_price(s, day) for s in pending_reweight}
            nav_est = cash + sum(u * (op_now[s] if np.isfinite(op_now.get(s, np.nan)) else ctx.mark(s, day)[0])
                                 for s, u in units.items())
            sells_first = []
            for sym in sorted(pending_reweight):
                op = op_now.get(sym, np.nan)
                if not np.isfinite(op):
                    continue  # halted: retry next session until next rebalance
                desired = nav_est / n_names
                cur = units.get(sym, 0.0) * op
                delta = desired - cur
                if delta < -1.0 and sym in units and units[sym] > 0:
                    sell_u = min(units[sym], -delta / op)
                    gross = sell_u * op
                    units[sym] -= sell_u
                    cash += gross * (1 - fee)
                    trade_rows.append({"session": day, "symbol": sym, "side": "SELL_TRIM",
                                       "gross_toman": gross, "fee_toman": gross * fee,
                                       "units": sell_u, "exec_price_adj": op})
                    if units[sym] <= 1e-9:
                        del units[sym]
                elif delta > 1.0:
                    sells_first.append((sym, op, delta))
            for sym, op, delta in sells_first:
                spend = min(delta, cash)
                gross = spend / (1 + fee)
                if spend <= 1.0 or gross <= 0:
                    continue
                u = gross / op
                units[sym] = units.get(sym, 0.0) + u
                cash -= spend
                trade_rows.append({"session": day, "symbol": sym, "side": "BUY_TOPUP",
                                   "gross_toman": gross, "fee_toman": spend - gross,
                                   "units": u, "exec_price_adj": op})
            pending_reweight = {s for s in pending_reweight if not np.isfinite(op_now.get(s, np.nan))}

        if pending_buys:
            filled = {}
            for sym, budget in pending_buys.items():
                op = ctx.open_price(sym, day)
                if np.isfinite(op):
                    filled[sym] = (op, budget)
            for sym, (op, budget) in sorted(filled.items()):
                spend = min(budget, cash)
                if spend <= 1.0:
                    continue
                gross = spend / (1 + fee)
                u = gross / op
                units[sym] = units.get(sym, 0.0) + u
                cash -= spend
                trade_rows.append({"session": day, "symbol": sym, "side": "BUY",
                                   "gross_toman": gross, "fee_toman": spend - gross,
                                   "units": u, "exec_price_adj": op})
            pending_buys = {s: b for s, b in pending_buys.items() if s not in filled}

        # ---- mark to market at last known adjusted close
        marks = {s: ctx.mark(s, day) for s in units}
        stale = [s for s in units if not np.isfinite(marks[s][0])]
        if stale:
            raise SystemExit(f"No price at all for held: {stale}")
        nav = cash + sum(units[s] * marks[s][0] for s in units)
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)
        nav_rows.append({"session": day, "nav_toman": nav, "cash_toman": cash,
                         "n_positions": len(units)})

        # ---- rebalance decision at close of `day`
        d_used = ctx.last_decision(day)
        if event_driven:
            do_rebalance = d_used != last_processed_decision and (
                last_rebalance_i is None or i - last_rebalance_i >= cooldown)
        else:
            do_rebalance = i in schedule
        if do_rebalance:
            if event_driven:
                last_processed_decision = d_used
                last_rebalance_i = i
            vals = tables[method][d_used]
            order = top_k_order(vals, np.array([ctx.sym_index[s] for s in syms]))
            rank_of = {syms[j]: pos for pos, j in enumerate(order, 1)}
            if exit_rank is None:
                target = [syms[j] for j in order[:n_names]]
            else:
                target = [s for s in units if rank_of.get(s, 10**9) <= exit_rank]
                for j in order:
                    if len(target) >= n_names:
                        break
                    s = syms[j]
                    if s not in target and rank_of[s] <= n_names:
                        target.append(s)
            held = set(units)
            leavers = sorted(held - set(target))
            entrants = [s for s in target if s not in held]
            rebal_rows.append({
                "session": day, "decision_date_used": d_used,
                "target": ";".join(target),
                "scores": ";".join(f"{vals[ctx.sym_pos[s]]:.4f}" for s in target),
                "leavers": ";".join(leavers), "entrants": ";".join(entrants),
                "nav_before_toman": round(nav, 0),
            })
            for sym in leavers:
                if sym in units:
                    pending_sells.add(sym)
            pending_buys = {s: b for s, b in pending_buys.items() if s in target}
            if re_equalize:
                pending_reweight = set(target)
            elif entrants:
                expected = cash
                for sym in leavers:
                    p, _ = ctx.mark(sym, day)
                    if np.isfinite(p):
                        expected += units[sym] * p * (1 - fee)
                if entry_weighting == "score":
                    sc = {s: max(float(vals[ctx.sym_pos[s]]), 0.01) for s in entrants}
                    tot = sum(sc.values())
                    for sym in entrants:
                        pending_buys[sym] = expected * sc[sym] / tot
                else:
                    share = expected / len(entrants)
                    for sym in entrants:
                        pending_buys[sym] = share

    final_nav = nav_rows[-1]["nav_toman"]
    years = (pd.Timestamp(cal[-1]) - pd.Timestamp(cal[0])).days / 365.25
    return {
        "method": method, "fee_per_side": fee, "re_equalize": re_equalize,
        "cadence_sessions": cadence, "n_names": n_names,
        "event_driven": event_driven, "cooldown_sessions": cooldown,
        "exit_rank": exit_rank, "entry_weighting": entry_weighting,
        "n_rebalances": (len(schedule_override) if schedule_override is not None
                         else (0 if event_driven else len(schedule))),
        "start": cal[0], "end": cal[-1], "initial_toman": 100_000_000.0,
        "final_toman": round(final_nav, 0),
        "total_return": final_nav / 100_000_000.0 - 1,
        "cagr": (final_nav / 100_000_000.0) ** (1 / years) - 1 if years > 0 else np.nan,
        "max_drawdown": max_dd,
        "n_trades": len(trade_rows),
        "rebalances": rebal_rows, "nav": nav_rows, "trades": trade_rows,
        "final_holdings": {s: {"units": units[s], "mark_day": marks[s][1]} for s in units},
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    ctx = build_context()
    cal = ctx.cal
    print(f"sessions: {len(cal)} ({cal[0]} -> {cal[-1]}), decision dates: {len(ctx.decision_dates)}")

    # Faithfulness gate: corrected scoring must reproduce the official V12.32
    # artifact top-5 at 2026-02-24 (same contract weights + engine + extraction).
    gate_date = "2026-02-24"
    official = json.loads(
        (ROOT / "ranking_research/output/return_v12_32/v12_32_20261022_local_extraction_01/ranking/latest-ranking.json")
        .read_text(encoding="utf-8-sig"))
    p1_official = sorted(official["rows"], key=lambda r: (r["methods"]["P1"]["rank"] is None, r["methods"]["P1"]["rank"]))
    official_top5 = [r["symbol"] for r in p1_official[:5]]
    vals = ctx.score_tables["P1"][gate_date]
    order = top_k_order(vals, np.array([ctx.sym_index[s] for s in ctx.syms]))
    gate_top5 = [ctx.syms[j] for j in order[:5]]
    print(f"v12.32 gate: official={official_top5} mine={gate_top5} -> {'MATCH' if gate_top5 == official_top5 else 'MISMATCH'}")
    if gate_top5 != official_top5:
        raise SystemExit("FAITHFULNESS_GATE_FAILED")

    variants = [
        ("P1", FEE, False, "p1_net", None, CADENCE, N_NAMES),
        ("P1", 0.0, False, "p1_gross", None, CADENCE, N_NAMES),
        ("P3", FEE, False, "p3_net", None, CADENCE, N_NAMES),
        ("P1", FEE, True, "p1_net_reequalize", None, CADENCE, N_NAMES),
        ("P1", FEE, False, "p1_net_rawpanel", ctx.score_tables_raw, CADENCE, N_NAMES),
    ]
    results = [run_variant(ctx, m, f, r, cadence=c, n_names=n, tables=t)
               for m, f, r, _, t, c, n in variants]

    # benchmark: equal-weight daily return of the whole universe (context only)
    ew = 1.0
    for i in range(1, len(cal)):
        day_prev, day = cal[i - 1], cal[i]
        rets = []
        for rec in ctx.md.data.values():
            a = bisect_right(rec["dates"], day_prev) - 1
            b = rec["dmap"].get(day)
            if a >= 0 and b is not None and rec["c"][a] > 0 and rec["c"][b] > 0:
                rets.append(rec["c"][b] * rec["cf"][b] / (rec["c"][a] * rec["cf"][a]) - 1)
        ew *= 1 + (float(np.mean(rets)) if rets else 0.0)
    benchmark_final = ew * 100_000_000.0

    summary = {
        "experiment": "top5_quarterly_rebalance_from_1402",
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "inputs": {
            "panel": str(PANEL.relative_to(ROOT)), "contract": str(CONTRACT.relative_to(ROOT)),
            "universe": str(UNIVERSE.relative_to(ROOT)),
            "market_archive": "historical_codal_backfill/output/raw_closing_universe",
            "corporate_actions": "score_v2_research/_cache/corp_actions_confirmed.parquet (tsetmc_gap_rule_v1, CONFIRMED)",
        },
        "assumptions": {
            "start_1402_first_session": cal[0], "end_session": cal[-1],
            "cadence_sessions": CADENCE, "n_names": N_NAMES,
            "fee_per_side": FEE, "execution": "next session open after close-time decision",
            "adjusted_chain": "certified tsetmc_gap_rule_v1; cash dividends behave as auto-reinvest",
            "fractional_units": True, "liquidity_filter": "none (pure top-5 of the page ranking)",
            "panel_correction": "V11 monthly-sales replay (V12.32 policy) applied to every decision date; raw v12.31-style panel reported as sensitivity",
        },
        "benchmark_equal_weight_universe_final_toman": round(benchmark_final, 0),
        "benchmark_equal_weight_universe_return": benchmark_final / 100_000_000.0 - 1,
        "variants": [{k: v for k, v in r.items() if k not in ("rebalances", "nav", "trades", "final_holdings")}
                     for r in results],
    }
    for (m, f, r, key, _, _, _), res in zip(variants, results):
        pd.DataFrame(res["nav"]).to_csv(HERE / f"nav_{key}.csv", index=False)
        pd.DataFrame(res["trades"]).to_csv(HERE / f"trades_{key}.csv", index=False)
        pd.DataFrame(res["rebalances"]).to_csv(HERE / f"rebalances_{key}.csv", index=False)
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    print(json.dumps(summary["variants"], indent=2, ensure_ascii=False, default=str))
    print(f"benchmark equal-weight universe final: {benchmark_final:,.0f}")
    print("wrote summary.json, nav_*.csv, trades_*.csv, rebalances_*.csv")


if __name__ == "__main__":
    main()
