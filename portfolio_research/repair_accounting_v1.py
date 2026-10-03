"""SCORE PORTFOLIO V1 — ACCOUNTING REPAIR RUN (implementation debugging, NOT model tuning).

Root cause of the quarantined run: the buy-scaling correction multiplied TARGET POSITIONS
by the financing factor f (calibrated on buy deltas), destroying (1-f) x current_value of
every held position at each rebalance where buys exceeded cash+sells. The leak is
cost-rate INDEPENDENT (present at 0 bps) and collapsed both gross and net paths.

Repair: f scales the BUY DELTAS only — bought positions = current + f x delta; reduced
names execute at exact target; carried names unchanged. Invariant (asserted every
rebalance): NAV_post == NAV_pre - cost, exactly.

Unit tests A-E run BEFORE any historical recomputation.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import sys
from bisect import bisect_right
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import psycopg

ROOT = Path(r"D:\RFA\Company-Financial")
HERE = ROOT / "portfolio_research"
PANEL = ROOT / "ui_score_research" / "ui_score_historical_pit_v2.parquet"
IMAP = HERE / "portfolio_identity_map.parquet"
DAILY = ROOT / "research_bundle" / "daily_market_panel.parquet"
RAW = ROOT / "historical_codal_backfill" / "output" / "raw_closing_universe"
DSN = "postgresql://postgres:pG%402027@localhost:5432/company_financial_analytics_shadow_v121"
PREREG_SHA = "10e6aa0e477b89eb73a5deacb72a4e337467fcfd2a06fd736a78e5954ecaf17c"
SCORE_SHA = "543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a"
SEED, B = 20261003, 2000
COSTS = {"GROSS": 0.0, "LOW": 0.0025, "BASE": 0.005, "HIGH": 0.01}
R = {"verification": {}, "unit_tests": {}, "root_cause": {}, "gross_parity": {},
     "results": {}, "gates": {}, "bootstrap": {}, "data_ramp": {}, "artifacts": {}}


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rebalance_accounts(cash_pre, current_values, target_values, tradable, cost_rate):
    """Pure rebalance accounting with delta-scaled buy financing.

    current_values: {sym: market value at the execution date} for HELD names
    target_values:  {sym: equal-weight target value} for SELECTED+EXECUTABLE names
    tradable:       {sym: bool} executability on the execution date
    Returns (cash_post, new_position_values, cost, buys_executed, sells_executed, buy_scale).
    Invariant: cash_post + sum(new_position_values) == cash_pre + sum(current_values) - cost.
    """
    sells = buys = 0.0
    new_pos = {}
    for sym in set(current_values) | set(target_values):
        cur = current_values.get(sym, 0.0)
        if sym in target_values and tradable.get(sym, False):
            d = target_values[sym] - cur
            if d > 0:
                buys += d
            elif d < 0:
                sells += -d
            new_pos[sym] = target_values[sym]          # executed at exact target (f=1 path)
        elif cur > 0 and not tradable.get(sym, False):
            new_pos[sym] = cur                          # carried: held but not executable
        elif cur > 0:
            sells += cur                                # held, not re-selected, tradable -> full exit
        # not held, not targeted -> stays cash (failed target handled by caller)
    cost = cost_rate * (buys + sells)
    avail = cash_pre + sells - cost_rate * sells
    buy_scale = 1.0
    if buys > 0 and avail < buys * (1 + cost_rate):
        buy_scale = max(0.0, avail / (buys * (1 + cost_rate)))
        buys = buys * buy_scale                          # executed buys shrink
        cost = cost_rate * (buys + sells)
        for sym in list(new_pos):
            if sym in target_values and tradable.get(sym, False) and target_values[sym] > current_values.get(sym, 0.0):
                cur = current_values.get(sym, 0.0)
                new_pos[sym] = cur + buy_scale * (target_values[sym] - cur)  # scale the DELTA
    cash_post = cash_pre + sells - buys - cost
    return cash_post, new_pos, cost, buys, sells, buy_scale


def run_unit_tests():
    T = {}
    # TEST A — bps conversion
    T["A_bps_conversion"] = (COSTS["LOW"] == 0.0025 and COSTS["BASE"] == 0.005
                             and COSTS["HIGH"] == 0.01 and COSTS["GROSS"] == 0.0)
    # TEST B — one-way purchase: buy + fee = 100, cash >= 0
    cash_post, pos, cost, buys, sells, f = rebalance_accounts(
        100.0, {}, {"X": 100.0}, {"X": True}, 0.005)
    T["B_one_way_purchase"] = (abs(buys + cost - 100.0) < 1e-9 and cash_post >= -1e-9
                               and abs(pos["X"] + cost - 100.0) < 1e-9 and abs(cost - 0.5) < 0.01)
    # TEST C — full rotation A -> B: ~1% round-trip drag
    cash_post, pos, cost, buys, sells, f = rebalance_accounts(
        0.0, {"A": 100.0}, {"B": 100.0}, {"A": True, "B": True}, 0.005)
    T["C_full_rotation"] = (abs(cost - 1.0) < 0.05 and abs(cash_post + pos["B"] - (100.0 - cost)) < 1e-9
                            and cash_post >= -1e-9 and "A" not in pos)
    # TEST D — zero turnover
    cash_post, pos, cost, buys, sells, f = rebalance_accounts(
        0.0, {"A": 60.0, "B": 40.0}, {"A": 60.0, "B": 40.0}, {"A": True, "B": True}, 0.005)
    T["D_zero_turnover"] = (abs(cost) < 1e-12 and abs(cash_post) < 1e-12
                            and abs(pos["A"] - 60.0) < 1e-12)
    # TEST E — proportional buy reduction, cash >= 0, NAV identity
    cash_post, pos, cost, buys, sells, f = rebalance_accounts(
        0.0, {"A": 100.0}, {"A": 50.0, "B": 50.0}, {"A": True, "B": True}, 0.005)
    nav_pre, nav_post = 100.0, cash_post + sum(pos.values())
    T["E_proportional_reduction"] = (cash_post >= -1e-9 and abs(nav_post - (nav_pre - cost)) < 1e-9)
    # invariant sweep on random cases
    rng = np.random.default_rng(7)
    ok_inv = True
    for _ in range(500):
        n = int(rng.integers(1, 6))
        names = [f"s{i}" for i in range(n)]
        cash = float(rng.uniform(0, 20))
        cur = {s: float(rng.uniform(0, 50)) for s in names}
        tgt = {s: float(rng.uniform(0, 50)) for s in names if rng.uniform() > 0.2}
        trad = {s: bool(rng.uniform() > 0.15) for s in names}
        c = float(rng.choice([0.0, 0.0025, 0.005, 0.01]))
        cp, np_, cost, b_, s_, f_ = rebalance_accounts(cash, cur, tgt, trad, c)
        nav_pre = cash + sum(cur.values())
        nav_post = cp + sum(np_.values())
        if abs(nav_post - (nav_pre - cost)) > 1e-9 or cp < -1e-9:
            ok_inv = False
            break
    T["invariant_NAV_post_eq_pre_minus_cost"] = ok_inv
    for k, v in T.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    return T, all(T.values())


def build_adj():
    with psycopg.connect(DSN) as pg, pg.cursor() as cur:
        cur.execute("""SELECT security_id::text, action_date, adjustment_factor
                       FROM market.corporate_actions
                       WHERE source='tsetmc_gap_rule_v1' AND adjustment_evidence_status='CONFIRMED'""")
        events = {}
        for sid, d, f in cur.fetchall():
            events.setdefault(sid, []).append(
                (d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)), float(f)))
        cur.execute("SELECT codal_symbol, id::text, tsetmc_ins_code::text FROM core.securities WHERE is_primary")
        sec = {s: (i, ins) for s, i, ins in cur.fetchall()}
        cur.execute("SELECT DISTINCT trade_date FROM market.price_observations ORDER BY trade_date")
        cal = [str(d) for (d,) in cur.fetchall()]
    adj = {}
    for sym, (sid, ins) in sec.items():
        gz = RAW / f"raw_{sym}_{ins}.json.gz"
        if not gz.exists():
            continue
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            doc = json.loads(fh.read())
        recs = sorted(doc["closingPriceDaily"], key=lambda r: r["dEven"])
        dates_s, raw = [], {}
        for r in recs:
            s = str(r["dEven"])
            d = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
            dates_s.append(d)
            raw[d] = float(r["pClosing"])
        evs = sorted(events.get(sid, []), key=lambda e: e[0])
        c, run, ei = {}, 1.0, len(evs) - 1
        for d in reversed(dates_s):
            dd = dt.date.fromisoformat(d)
            while ei >= 0 and evs[ei][0] > dd:
                run *= evs[ei][1]
                ei -= 1
            c[d] = run
        adj[sym] = {"dates": dates_s, "adj": {d: raw[d] * c[d] for d in dates_s}}
    return adj, cal


def price_at(adj, sym, d):
    s = adj.get(sym)
    if not s:
        return None
    i = bisect_right(s["dates"], d)
    return s["adj"][s["dates"][i - 1]] if i > 0 else None


def simulate(panel, adj, cal, traded_keys, sel_pct, cost_rate):
    dates = sorted(panel.as_of.unique())
    exec_dates = []
    for T in dates:
        i = bisect_right(cal, str(T)[:10])
        exec_dates.append(cal[i] if i < len(cal) else None)
    per_rows, trade_rows, hold_rows = [], [], []
    cash, positions = 1.0, {}
    n_periods = len(dates) - 1
    for k, T in enumerate(dates):
        E = exec_dates[k]
        g = panel[panel.as_of == T]
        n_elig = len(g)
        n_sel = max(1, int(np.floor(sel_pct * n_elig)))
        gs = g.sort_values(["ui_score", "symbol"], ascending=[False, True])
        sel = gs.head(n_sel)
        price = {r.symbol: price_at(adj, r.symbol, E) for r in sel.itertuples()}
        cur_vals = {sym: sh * price_at(adj, sym, E) for sym, sh in positions.items()}
        value_pre = cash + sum(cur_vals.values())
        pre_w = {s: v / value_pre for s, v in cur_vals.items()} if value_pre > 0 else {}
        pre_cash_w = cash / value_pre if value_pre > 0 else 0.0
        target_each = value_pre / n_sel
        target_values, failed = {}, []
        for r in sel.itertuples():
            if (E, r.symbol) in traded_keys:
                target_values[r.symbol] = target_each
            elif r.symbol in cur_vals:
                pass  # held selected non-executable -> carried
            else:
                failed.append(r.symbol)
        tradable = {s: (E, s) in traded_keys for s in set(cur_vals) | set(target_values)}
        cash_post, new_pos_vals, cost, buys, sells, buy_scale = rebalance_accounts(
            cash, cur_vals, target_values, tradable, cost_rate)
        assert cash_post >= -1e-9, f"negative cash at {k+1}"
        nav_pre, nav_post = value_pre, cash_post + sum(new_pos_vals.values())
        assert abs(nav_post - (nav_pre - cost)) < 1e-6, f"NAV identity violated at {k+1}"
        positions = {s: v / price_at(adj, s, E) for s, v in new_pos_vals.items()}
        # trades ledger (actual executed notionals)
        for sym, tv in target_values.items():
            cur = cur_vals.get(sym, 0.0)
            d = tv - cur
            if d > 0 and buy_scale < 1.0:
                d = buy_scale * d
            if abs(d) > 1e-9:
                trade_rows.append({"rebalance": k + 1, "exec_date": E, "symbol": sym,
                                   "side": "BUY" if d > 0 else "SELL_REBAL",
                                   "notional": abs(d), "cost": cost_rate * abs(d)})
        for sym, cv in cur_vals.items():
            if sym not in target_values and (E, sym) in traded_keys:
                trade_rows.append({"rebalance": k + 1, "exec_date": E, "symbol": sym,
                                   "side": "SELL", "notional": cv, "cost": cost_rate * cv})
            elif sym not in target_values:
                trade_rows.append({"rebalance": k + 1, "exec_date": E, "symbol": sym,
                                   "side": "CARRY_HELD_UNSELECTED", "notional": 0.0, "cost": 0.0})
        for r in sel.itertuples():
            if r.symbol in failed:
                trade_rows.append({"rebalance": k + 1, "exec_date": E, "symbol": r.symbol,
                                   "side": "CASH_FAILED_TARGET", "notional": 0.0, "cost": 0.0})
        # turnover (frozen formula)
        tw = {r.symbol: 1.0 / n_sel for r in sel.itertuples()}
        target_cash_w = sum(1.0 / n_sel for _ in failed)
        union = set(tw) | set(pre_w)
        turn = 0.5 * (sum(abs(tw.get(s, 0.0) - pre_w.get(s, 0.0)) for s in union)
                      + abs(target_cash_w - pre_cash_w))
        per_rows.append({
            "rebalance": k + 1, "score_date": str(T)[:10], "exec_date": E,
            "n_eligible": n_elig, "n_selected": n_sel,
            "value_pre_trade": value_pre, "transaction_cost": cost,
            "value_post_trade": nav_post,
            "cash_weight": cash_post / nav_post if nav_post > 0 else 0.0,
            "holdings_count": sum(1 for v in new_pos_vals.values() if v > nav_post * 1e-9),
            "turnover": turn, "buy_notional": buys, "sell_notional": sells,
            "traded_notional": buys + sells,
            "buy_notional_fraction": buys / value_pre if value_pre > 0 else 0.0,
            "sell_notional_fraction": sells / value_pre if value_pre > 0 else 0.0,
            "absolute_traded_notional_fraction": (buys + sells) / value_pre if value_pre > 0 else 0.0,
            "transaction_cost_fraction": cost / value_pre if value_pre > 0 else 0.0,
            "failed_targets": len(failed), "buy_scale": buy_scale,
        })
        for r in sel.itertuples():
            hold_rows.append({"rebalance": k + 1, "score_date": str(T)[:10], "exec_date": E,
                              "symbol": r.symbol, "ui_score": r.ui_score,
                              "target_weight": 1.0 / n_sel,
                              "tradable_on_exec": (E, r.symbol) in traded_keys,
                              "rank_in_date": int((g.ui_score > r.ui_score).sum()) + 1})
        cash = cash_post
    # period returns from the NAV_post wealth path: these compound EXACTLY to
    # NAV_post(final)/NAV_post(0) — growth AND the cost charged at each rebalance
    rets = [per_rows[k + 1]["value_post_trade"] / per_rows[k]["value_post_trade"] - 1
            for k in range(n_periods)]
    for k, r_ in enumerate(rets):
        per_rows[k]["monthly_return"] = r_
    return per_rows, hold_rows, trade_rows


def metrics(per, label):
    rets = np.array([p["monthly_return"] for p in per if "monthly_return" in p])
    # wealth path: start at 1.0, first rebalance's entry cost applies, then compounded
    # NAV_post growth (the monthly series above starts AFTER the entry rebalance)
    entry = per[0]["value_post_trade"]                      # NAV_post(0) = 1 - entry cost
    path = np.concatenate([[entry], entry * np.cumprod(1 + rets)])
    wealth_multiple = float(path[-1])                       # includes entry cost (denominator 1.0)
    peak = np.maximum.accumulate(np.concatenate([[1.0], path]))
    mdd = float((np.concatenate([[1.0], path]) / peak - 1).min())
    turn = np.array([p["turnover"] for p in per])
    ann = wealth_multiple ** (12 / len(rets)) - 1 if len(rets) else None
    return {
        "label": label, "n_periods": int(len(rets)),
        "cumulative_return": wealth_multiple - 1, "terminal_wealth_multiple": wealth_multiple,
        "annualized_return": ann,
        "annualized_volatility": float(np.std(rets, ddof=1) * np.sqrt(12)),
        "max_drawdown": mdd,
        "sharpe_0rf": float(np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(12)),
        "positive_month_fraction": float(np.mean(rets > 0)),
        "best_month": float(rets.max()), "worst_month": float(rets.min()),
        "avg_holdings": float(np.mean([p["holdings_count"] for p in per])),
        "median_holdings": float(np.median([p["holdings_count"] for p in per])),
        "avg_cash_pct": float(np.mean([p["cash_weight"] for p in per]) * 100),
        "avg_turnover": float(np.mean(turn)), "median_turnover": float(np.median(turn)),
        "p90_turnover": float(np.percentile(turn, 90)),
        "total_traded_notional_over_avg_capital": float(
            np.sum([p["traded_notional"] for p in per]) / np.mean([p["value_post_trade"] for p in per])),
        "total_fees_paid": float(np.sum([p["transaction_cost"] for p in per])),
        "avg_monthly_cost_drag_pct": float(np.mean([p["transaction_cost_fraction"] for p in per]) * 100),
    }


def yearly(per):
    out = {}
    for p in per:
        if "monthly_return" in p:
            out.setdefault(p["exec_date"][:4], []).append(p["monthly_return"])
    return {y: float(np.prod(1 + np.array(v))) - 1 for y, v in sorted(out.items())}


def main() -> int:
    assert sha256(HERE / "SCORE_PORTFOLIO_V1_PREREGISTRATION.md") == PREREG_SHA
    assert sha256(PANEL) == SCORE_SHA
    imap = pd.read_parquet(IMAP)
    assert (imap.mapping_status == "UNIQUE").all() and len(imap) == 235
    R["verification"] = {"preregistration_sha256": PREREG_SHA, "score_sha256": SCORE_SHA,
                         "identity_map": "235 UNIQUE / 0 ambiguous", "all_match": True}
    panel = pd.read_parquet(PANEL, columns=["as_of", "security_id", "symbol", "ui_score",
                                            "data_quality_score", "sales_growth_12m"]).dropna(subset=["ui_score"])
    adj, cal = build_adj()
    daily = pd.read_parquet(DAILY, columns=["date", "symbol", "security_traded"])
    daily["date"] = daily.date.astype(str).str[:10]
    traded = set(map(tuple, daily.loc[daily.security_traded == True, ["date", "symbol"]].values))
    assert set(panel.symbol.unique()).issubset(set(imap.symbol))

    T, all_pass = run_unit_tests()
    R["unit_tests"] = {"tests": {k: "PASS" if v else "FAIL" for k, v in T.items()},
                       "all_pass": all_pass,
                       "cost_rates_used_in_flawed_run": {"GROSS": 0.0, "LOW": 0.0025,
                                                         "BASE": 0.005, "HIGH": 0.01},
                       "cost_rates_corrected": "identical numerically — the flaw was in the "
                                               "financing/position-scaling, not the rate"}
    assert all_pass, "unit tests failed"

    R["root_cause"] = {
        "defect": ("previous run scaled TARGET POSITIONS by the financing factor f (calibrated "
                   "on buy deltas), destroying (1-f) x current_value of held positions at every "
                   "rebalance where buys exceeded cash+sells; the leak is cost-rate independent "
                   "and collapsed both the gross and net paths (value_pre -> 0.0002 by 2025)"),
        "fix": "f now scales BUY DELTAS only; NAV_post = NAV_pre - cost holds exactly (asserted)",
        "quarantined_run_verdict": "PORTFOLIO_V1_NET_RESULT_VALID = NO (both gross and net paths invalid)",
    }

    # gross parity vs the quarantined run's reported gross summary
    runs = {}
    for label, pct in [("TOP20", 0.20), ("TOP10", 0.10), ("BENCH", 1.00)]:
        for cname, c in COSTS.items():
            per, holds, trades = simulate(panel, adj, cal, traded, pct, c)
            runs[(label, cname)] = (per, holds, trades)
    R["results"] = {f"{k[0]}_{k[1]}": metrics(v[0], f"{k[0]}_{k[1]}") for k, v in runs.items()}
    # section-6 reconciliation: gross-to-net annualized drag vs total fees / capital
    recon = {}
    for cname in ["LOW", "BASE", "HIGH"]:
        g = R["results"][f"TOP20_GROSS"]["annualized_return"]
        n_ = R["results"][f"TOP20_{cname}"]["annualized_return"]
        fees = R["results"][f"TOP20_{cname}"]["total_fees_paid"]
        avg_cap = float(np.mean([p["value_post_trade"] for p in runs[("TOP20", cname)][0]]))
        implied_annual_drag_pp = fees / avg_cap / (62 / 12) * 100
        recon[cname] = {"gross_ann": round(g, 4), "net_ann": round(n_, 4),
                        "observed_drag_pp": round((g - n_) * 100, 3),
                        "total_fees_over_avg_capital": round(fees / avg_cap, 4),
                        "fees_implied_annual_drag_pp": round(implied_annual_drag_pp, 3)}
    R["results"]["cost_reconciliation"] = recon
    old_gross = {"annualized": 0.4307, "cumulative": 5.36}
    new_gross = R["results"]["TOP20_GROSS"]
    parity = abs(new_gross["annualized_return"] - old_gross["annualized"]) < 0.005
    R["gross_parity"] = {
        "GROSS_PATH_PARITY": "PASS" if parity else "FAIL",
        "old_gross_annualized": old_gross["annualized"], "new_gross_annualized": round(new_gross["annualized_return"], 4),
        "reason": ("the quarantined gross path contained the SAME position-scaling value leak "
                   "(the leak is cost-rate independent, active at 0 bps whenever buys exceeded "
                   "cash+sells), so the old gross path was itself invalid and cannot anchor "
                   "parity; the corrected gross path is validated by the unit tests and the "
                   "exact NAV_post = NAV_pre - cost identity instead"),
    }
    print("gross parity:", R["gross_parity"]["GROSS_PATH_PARITY"],
          "| corrected gross ann:", round(new_gross["annualized_return"], 4))

    base20, baseb = runs[("TOP20", "BASE")][0], runs[("BENCH", "BASE")][0]
    et = [p["monthly_return"] for p in base20 if "monthly_return" in p]
    eb = [p["monthly_return"] for p in baseb if "monthly_return" in p]
    ex = np.array(et) - np.array(eb)
    yex = {y: round(yearly(base20)[y] - yearly(baseb)[y], 5) for y in yearly(base20)}
    R["results"]["TOP20_BASE"]["excess"] = {
        "mean_monthly": float(np.mean(ex)), "median_monthly": float(np.median(ex)),
        "positive_fraction": float(np.mean(ex > 0)),
        "annualized_return_difference_pp": (R["results"]["TOP20_BASE"]["annualized_return"]
                                            - R["results"]["BENCH_BASE"]["annualized_return"]) * 100,
        "terminal_wealth_difference": (R["results"]["TOP20_BASE"]["terminal_wealth_multiple"]
                                       - R["results"]["BENCH_BASE"]["terminal_wealth_multiple"]),
        "yearly_top": yearly(base20), "yearly_bench": yearly(baseb), "yearly_excess": yex,
    }
    per_dates = [p["exec_date"] for p in base20 if "monthly_return" in p]
    ds = [dt.date.fromisoformat(d) for d in per_dates]
    block = 1
    for i in range(len(ds)):
        j = i
        while j + 1 < len(ds) and (ds[j + 1] - ds[i]).days <= 6 * 30.44:
            j += 1
        block = max(block, j - i + 1)
    rng = np.random.default_rng(SEED)
    n = len(ex)
    nb = int(np.ceil(n / block))
    means, cagr = np.empty(B), np.empty(B)
    for b_ in range(B):
        idx = []
        for _ in range(nb):
            s = int(rng.integers(0, n))
            idx.extend((s + k) % n for k in range(block))
        idx = np.array(idx[:n])
        means[b_] = ex[idx].mean()
        cagr[b_] = (np.prod(1 + np.array(et)[idx]) ** (12 / n)
                    - np.prod(1 + np.array(eb)[idx]) ** (12 / n))
    R["bootstrap"] = {
        "seed": SEED, "B": B, "block_len_periods": block,
        "mean_monthly_excess": {"mean": float(np.mean(ex)),
                                "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]},
        "annualized_excess_equivalent": {"mean": float(np.mean(ex) * 12),
                                         "ci95": [float(np.percentile(means, 2.5)) * 12,
                                                  float(np.percentile(means, 97.5)) * 12]},
        "cagr_difference": {"ci95": [float(np.percentile(cagr, 2.5)), float(np.percentile(cagr, 97.5))]},
    }
    m20, mb = R["results"]["TOP20_BASE"], R["results"]["BENCH_BASE"]
    pv = {"PV1": "PASS",
          "PV2": "PASS" if (m20["annualized_return"] - mb["annualized_return"]) * 100 >= 2.0 else "FAIL",
          "PV3": "PASS" if R["bootstrap"]["mean_monthly_excess"]["ci95"][0] > 0 else "FAIL",
          "PV4": "PASS" if sum(1 for y in ["2021", "2022", "2023", "2024", "2025"] if yex.get(y, 0) > 0) >= 3 else "FAIL",
          "PV5": "PASS" if m20["max_drawdown"] >= mb["max_drawdown"] - 0.05 else "FAIL",
          "PV6": "PASS" if m20["avg_turnover"] <= 0.30 else "FAIL",
          "PV7": "PASS" if m20["median_holdings"] >= 20 else "FAIL",
          "PV8": "PASS" if m20["avg_cash_pct"] <= 10 else "FAIL"}
    pv["SCORE_PORTFOLIO_V1_PRIMARY_GATE"] = "PASS" if all(v == "PASS" for v in pv.values()) else "FAIL"
    R["gates"] = pv
    ramp = []
    for y in sorted({p["exec_date"][:4] for p in base20}):
        dd = [p for p in base20 if p["exec_date"][:4] == y]
        sy = panel[panel.as_of.str[:4] == y]
        ramp.append({"year": y, "rebalances": len(dd),
                     "median_eligible": float(np.median([p["n_eligible"] for p in dd])),
                     "median_dq": float(sy.data_quality_score.median()),
                     "fundamental_input_coverage": float(sy.sales_growth_12m.notna().mean()),
                     "top20_return": yearly(base20).get(y), "bench_return": yearly(baseb).get(y)})
    R["data_ramp"] = ramp

    # ---------- artifacts (accounting repaired; old files preserved) ----------
    monthly = pd.DataFrame([{**{k: v for k, v in p.items() if k != "monthly_return"},
                             "top20_return": p.get("monthly_return"),
                             "bench_return": b.get("monthly_return"),
                             "excess_return": (p.get("monthly_return") - b.get("monthly_return"))
                             if "monthly_return" in p else None}
                            for p, b in zip(base20, baseb)])
    monthly.to_csv(HERE / "score_portfolio_v1_monthly_accounting_repaired.csv", index=False)
    pd.DataFrame(runs[("TOP20", "BASE")][2]).to_parquet(
        HERE / "score_portfolio_v1_trades_accounting_repaired.parquet", compression="zstd", index=False)
    pd.DataFrame(runs[("TOP20", "BASE")][1]).to_parquet(
        HERE / "score_portfolio_v1_holdings_accounting_repaired.parquet", compression="zstd", index=False)
    pd.DataFrame(ramp).to_csv(HERE / "score_portfolio_v1_yearly_accounting_repaired.csv", index=False)
    (HERE / "score_portfolio_v1_bootstrap_accounting_repaired.json").write_text(
        json.dumps(R["bootstrap"], indent=1), encoding="utf-8")
    R["artifacts"] = {
        "preregistration_sha256": PREREG_SHA, "score_panel_sha256": SCORE_SHA,
        "identity_map_sha256": sha256(IMAP),
        "execution_script_sha256": sha256(Path(__file__).resolve()),
        "quarantined_artifacts_preserved": ["score_portfolio_v1_results.json",
                                            "score_portfolio_v1_monthly.csv",
                                            "score_portfolio_v1_trades.parquet",
                                            "score_portfolio_v1_holdings.parquet",
                                            "score_portfolio_v1_yearly.csv",
                                            "score_portfolio_v1_bootstrap.json",
                                            "SCORE_PORTFOLIO_V1_RESULTS.md"],
    }
    (HERE / "score_portfolio_v1_results_accounting_repaired.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    R["artifacts"]["results_json_sha256"] = sha256(HERE / "score_portfolio_v1_results_accounting_repaired.json")
    (HERE / "score_portfolio_v1_results_accounting_repaired.json").write_text(
        json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"gates": pv,
                      "top20_base": {k: v for k, v in m20.items() if not isinstance(v, dict)},
                      "bench_base": {k: v for k, v in mb.items() if not isinstance(v, dict)},
                      "excess": R["results"]["TOP20_BASE"]["excess"],
                      "bootstrap": R["bootstrap"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
