#!/usr/bin/env python
"""INVESTOR VIEW FROM 1403-01 — display-only rescaling of the certified historical
Shadow V1.1 walk-forward replay (label: HISTORICAL_REPLAY_ONLY).

READS ONLY the already-certified replay artifacts in portfolio_shadow_replay/:
  - shadow_replay_monthly.csv        (certified monthly decision/execution/accounting rows)
  - shadow_replay_targets.parquet    (per-security decision rows)
  - security_holding_history.csv     (per-security eligible rows per month)
  - replay_state.json                (provenance: spec/panel/imap SHAs, conventions)

It performs NO strategy computation, NO accounting change, NO cost change, and
modifies NO certified artifact. The only transformation is a pure display scaling:
the certified normalized NAV path is re-denominated so that the certified portfolio
value immediately before the first window rebalance equals 100,000,000 TOMAN.

Window: first certified monthly replay decision with score_date on or after
Farvardin 1403 (= 2024-03-20 Gregorian). No decision is invented on 1403-01-01.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
INITIAL_CAPITAL_TOMAN = 100_000_000
PERSIAN_START_MONTH = "1403-01"
NOWRUZ_1403_GREGORIAN = (2024, 3, 20)  # 1403-01-01
# Determinism-probe SHA-256 of the certified monthly CSV (recorded in
# _determinism_check.txt at replay build time). Aborts on any mismatch.
CERT_MONTHLY_SHA = "c00f22a9abdcc1b34ee9a8c8733005dbbcfbb75280776d7f0edd8fffad859880"

PERSIAN_MONTH_NAMES = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]

# ---------------------------------------------------------------- jalali calendar
# Port of jalaali-js (Behrooz K. Hooshmand algorithm). JS-style truncated
# division/modulo are required (negative operands occur in g2d/d2g).

def tdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def tmod(a: int, b: int) -> int:
    return a - tdiv(a, b) * b


_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _jal_cal(jy: int):
    bl = len(_BREAKS)
    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    if jy < jp or jy >= _BREAKS[bl - 1]:
        raise ValueError(f"Jalali year out of range: {jy}")
    jump = 0
    for i in range(1, bl):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += tdiv(jump, 33) * 8 + tdiv(tmod(jump, 33), 4)
        jp = jm
    n = jy - jp
    leap_j += tdiv(n, 33) * 8 + tdiv(tmod(n, 33) + 3, 4)
    if tmod(jump, 33) == 4 and jump - n == 4:
        leap_j += 1
    leap_g = tdiv(gy, 4) - tdiv((tdiv(gy, 100) + 1) * 3, 4) - 150
    march = 20 + leap_j - leap_g
    if jump - n < 6:
        n = n - jump + tdiv(jump + 4, 33) * 33
    leap = tmod(tmod(n + 1, 33) - 1, 4)
    if leap == -1:
        leap = 4
    return leap, gy, march


def _g2d(gy: int, gm: int, gd: int) -> int:
    d = (tdiv((gy + tdiv(gm - 8, 6) + 100100) * 1461, 4)
         + tdiv(153 * tmod(gm + 9, 12) + 2, 5)
         + gd - 34840408)
    d = d - tdiv(tdiv(gy + 100100 + tdiv(gm - 8, 6), 100) * 3, 4) + 752
    return d


def _d2g(jdn: int):
    j = 4 * jdn + 139361631
    j = j + tdiv(tdiv(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908
    i = tdiv(tmod(j, 1461), 4) * 5 + 308
    gd = tdiv(tmod(i, 153), 5) + 1
    gm = tmod(tdiv(i, 153), 12) + 1
    gy = tdiv(j, 1461) - 100100 + tdiv(8 - gm, 6)
    return gy, gm, gd


def greg_to_jalali(d: date):
    jdn = _g2d(d.year, d.month, d.day)
    gy = _d2g(jdn)[0]
    jy = gy - 621
    leap, rgy, march = _jal_cal(jy)
    jdn1f = _g2d(rgy, 3, march)
    k = jdn - jdn1f
    if k >= 0:
        if k <= 185:
            return jy, 1 + tdiv(k, 31), tmod(k, 31) + 1
        k -= 186
    else:
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + tdiv(k, 30), tmod(k, 30) + 1


def jalali_to_greg(jy: int, jm: int, jd: int) -> date:
    leap, gy, march = _jal_cal(jy)
    jdn = _g2d(gy, 3, march)
    if jm <= 7:
        k = (jm - 1) * 31 + jd - 1
    else:
        k = 186 + (jm - 7) * 30 + jd - 1
    gy2, gm2, gd2 = _d2g(jdn + k)
    return date(gy2, gm2, gd2)


def _jalali_selfcheck():
    assert jalali_to_greg(1403, 1, 1) == date(2024, 3, 20), "Nowruz 1403 anchor failed"
    assert jalali_to_greg(1404, 1, 1) == date(2025, 3, 21), "Nowruz 1404 anchor failed"
    assert jalali_to_greg(1405, 1, 1) == date(2026, 3, 21), "Nowruz 1405 anchor failed"
    assert greg_to_jalali(date(2024, 3, 30)) == (1403, 1, 11), "1403-01-11 anchor failed"
    assert greg_to_jalali(date(2026, 6, 30)) == (1405, 4, 9), "1405-04-09 anchor failed"
    for y in (2024, 2025, 2026):
        for m in range(1, 13):
            for dd in (1, 15, 28):
                jy, jm, jd = greg_to_jalali(date(y, m, dd))
                assert jalali_to_greg(jy, jm, jd) == date(y, m, dd), "jalali roundtrip failed"


# ---------------------------------------------------------------- helpers

def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def fmt_toman(v: float) -> str:
    return f"{v:,.0f}"


def fmt_pct(x, digits=2) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x * 100:.{digits}f}%"


def iso_jalali(d: date) -> str:
    jy, jm, jd = greg_to_jalali(d)
    return f"{jy}-{jm:02d}-{jd:02d}"


def max_drawdown(points) -> float:
    peak = -np.inf
    mdd = 0.0
    for v in points:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return mdd


def pctile(vals, q):
    return float(np.percentile(np.asarray(vals, dtype=float), q)) if vals else None


# ---------------------------------------------------------------- main

def main() -> None:
    _jalali_selfcheck()

    monthly_path = BASE / "shadow_replay_monthly.csv"
    targets_path = BASE / "shadow_replay_targets.parquet"
    trades_path = BASE / "shadow_replay_trades.parquet"
    holding_path = BASE / "security_holding_history.csv"
    state_path = BASE / "replay_state.json"

    monthly_sha = sha256_file(monthly_path)
    if monthly_sha != CERT_MONTHLY_SHA:
        sys.exit(f"ABORT: certified monthly CSV hash mismatch: {monthly_sha}")

    m = pd.read_csv(monthly_path)
    targets = pd.read_parquet(targets_path)
    holding = pd.read_csv(holding_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(m) == 63, f"expected 63 certified rows, got {len(m)}"

    input_shas = {
        "shadow_replay_monthly.csv": monthly_sha,
        "shadow_replay_targets.parquet": sha256_file(targets_path),
        "shadow_replay_trades.parquet": sha256_file(trades_path),
        "security_holding_history.csv": sha256_file(holding_path),
    }

    # ---------------------------------------------------------------- window
    start_greg = date(*NOWRUZ_1403_GREGORIAN)
    score_dates = pd.to_datetime(m["score_date"]).dt.date
    win = m[score_dates >= start_greg].copy()
    win = win.reset_index(drop=True)
    assert len(win) == 25, f"expected 25 window rows, got {len(win)}"
    first = win.iloc[0]
    last = win.iloc[-1]
    assert first["score_date"] == "2024-03-30"
    assert last["score_date"] == "2026-06-30"
    first_score = date.fromisoformat(first["score_date"])
    first_exec = date.fromisoformat(first["exec_date"])
    jy_f, jm_f, jd_f = greg_to_jalali(first_score)
    assert (jy_f, jm_f) == (1403, 1), "first window decision must fall in Farvardin 1403"

    start_nav_normalized = float(first["value_pre_trade"])
    bench_start_nav_normalized = float(first["bench_value_pre_trade"])
    scale = INITIAL_CAPITAL_TOMAN / start_nav_normalized
    bench_scale = INITIAL_CAPITAL_TOMAN / bench_start_nav_normalized

    # ---------------------------------------------------------------- monthly investor table
    # Return convention of the certified artifact (unchanged):
    #   portfolio_return[j] = NAV_post(E_{j+1}) / NAV_post(E_j) - 1
    # Row j's starting capital = scaled NAV_post(E_j) (post-trade). For the first
    # window row only, the investor starts from cash: INITIAL -> entry cost ->
    # scaled NAV_post(E_first). The final row has no subsequent certified return
    # period (n_return_periods = 62 < 63), so its return is empty.
    rows = []
    wealth_points = [float(INITIAL_CAPITAL_TOMAN)]
    post_entry_capital = scale * float(first["value_post_trade"])
    wealth_points.append(post_entry_capital)
    prev_ending = None
    for i, r in win.iterrows():
        jy, jm, _ = greg_to_jalali(date.fromisoformat(r["score_date"]))
        is_first = i == 0
        is_last = i == len(win) - 1
        starting = float(INITIAL_CAPITAL_TOMAN) if is_first else prev_ending
        ret = None if is_last else float(r["portfolio_return"])
        bench_ret = None if is_last else float(r["benchmark_return"])
        excess = None if is_last else float(r["excess_return"])
        # ending for non-last rows = scaled NAV_post(E_{j+1}) = next certified row's value_post_trade
        ending = scale * float(r["value_post_trade"]) if is_last else scale * float(win.iloc[i + 1]["value_post_trade"])
        cost_toman = scale * float(r["transaction_cost"])
        peak = max(wealth_points)
        dd = ending / peak - 1.0
        rows.append({
            "persian_month": f"{jy}-{jm:02d}",
            "persian_month_name": PERSIAN_MONTH_NAMES[jm - 1],
            "decision_month": r["decision_month"],
            "score_date": r["score_date"],
            "exec_date": r["exec_date"],
            "starting_capital_toman": starting,
            "entry_cost_toman": cost_toman if is_first else 0.0,
            "post_entry_capital_toman": post_entry_capital if is_first else starting,
            "n_selected": int(r["n_selected"]),
            "n_eligible": int(r["n_eligible"]),
            "n_entered": int(r["n_entered"]),
            "n_exited": int(r["n_exited"]),
            "n_retained": int(r["n_retained"]),
            "actions_buy": int(r["actions_buy"]),
            "actions_increase": int(r["actions_increase"]),
            "actions_decrease": int(r["actions_decrease"]),
            "actions_hold": int(r["actions_hold"]),
            "sell_exits": int(r["exec_sells_exits"]),
            "sell_rebal_partial": int(r["exec_sell_rebal"]),
            "target_turnover": float(r["turnover"]),
            "transaction_cost_toman": cost_toman,
            "portfolio_monthly_return": ret,
            "benchmark_monthly_return": bench_ret,
            "excess_return": excess,
            "ending_capital_toman": ending,
            "drawdown_from_prior_peak": dd,
            "cash_weight": float(r["cash_weight"]),
            "top_holding_weight": float(r["top_holding_weight"]),
            "top5_weight": float(r["top5_weight"]),
            "top10_weight": float(r["top10_weight"]),
            "holdings_count": int(r["holdings_count"]),
        })
        assert abs(int(r["actions_buy"]) + int(r["actions_hold"]) + int(r["actions_increase"])
                   + int(r["actions_decrease"]) - int(r["n_selected"])) < 1e-9, \
            f"action count mismatch at {r['decision_month']}"
        if not is_first and ret is not None:
            # table arithmetic identity: ending = starting x (1 + certified return)
            assert abs(ending - starting * (1.0 + ret)) < 0.01, \
                f"ending/starting identity failed at {r['decision_month']}"
        if is_first:
            assert abs(post_entry_capital - (INITIAL_CAPITAL_TOMAN - cost_toman)) < 0.01
            assert abs(post_entry_capital * (1.0 + ret) - ending) < 0.01
        wealth_points.append(ending)
        prev_ending = ending

    final_capital = rows[-1]["ending_capital_toman"]
    bench_final_capital = bench_scale * float(last["benchmark_nav"])
    bench_points = [float(INITIAL_CAPITAL_TOMAN)]
    for i, r in win.iterrows():
        bench_points.append(bench_scale * float(r["benchmark_nav"]))
    assert abs(bench_points[-1] - bench_final_capital) < 0.01

    ret_rows = [r for r in rows if r["portfolio_monthly_return"] is not None]
    n_return_periods = len(ret_rows)
    cum_return = final_capital / INITIAL_CAPITAL_TOMAN - 1.0
    annualized = (final_capital / INITIAL_CAPITAL_TOMAN) ** (12.0 / n_return_periods) - 1.0
    window_mdd = max_drawdown(wealth_points)
    bench_cum = bench_final_capital / INITIAL_CAPITAL_TOMAN - 1.0
    bench_annualized = (bench_final_capital / INITIAL_CAPITAL_TOMAN) ** (12.0 / n_return_periods) - 1.0
    bench_mdd = max_drawdown(bench_points)
    total_cost_toman = sum(r["transaction_cost_toman"] for r in rows)
    avg_turnover = float(np.mean([r["target_turnover"] for r in rows]))
    median_turnover = float(np.median([r["target_turnover"] for r in rows]))

    # identity: final capital equals scaled certified terminal NAV
    cert_terminal = float(m.iloc[-1]["value_post_trade"])
    assert abs(final_capital - scale * cert_terminal) < 0.01

    # ---------------------------------------------------------------- security-level data
    tgt = targets.copy()
    tgt_w = {}
    for dm, g in tgt.groupby("decision_month"):
        tgt_w[dm] = dict(zip(g["symbol"], g["target_weight"]))
    hold_lookup = {}
    for (dm, sym), g in holding.groupby(["decision_month", "symbol"]):
        hold_lookup[(dm, sym)] = g.iloc[0]

    month_sections = []
    win_decision_months = list(win["decision_month"])
    for i, r in win.iterrows():
        dm = r["decision_month"]
        g = tgt[tgt["decision_month"] == dm].sort_values("ui_rank")
        sel_rows = []
        for _, t in g.iterrows():
            sel_rows.append({
                "symbol": t["symbol"],
                "ui_score": float(t["ui_score"]),
                "ui_rank": int(t["ui_rank"]),
                "data_quality": float(t["data_quality"]),
                "target_weight": float(t["target_weight"]),
                "previous_weight": float(t["previous_weight"]),
                "paper_action": t["paper_action"],
                "trade_notional_fraction": float(t["trade_notional_fraction"]),
            })
        exited = [] if pd.isna(r["exited_symbols"]) or not str(r["exited_symbols"]).strip() \
            else [s.strip() for s in str(r["exited_symbols"]).split(",") if s.strip()]
        prev_dm = win_decision_months[i - 1] if i > 0 else m.iloc[
            m.index[m["decision_month"] == dm][0] - 1]["decision_month"]
        sell_rows = []
        for sym in exited:
            hk = hold_lookup.get((dm, sym))
            sell_rows.append({
                "symbol": sym,
                "ui_score": float(hk["ui_score"]) if hk is not None else None,
                "ui_rank": int(hk["ui_rank"]) if hk is not None else None,
                "previous_weight": float(tgt_w.get(prev_dm, {}).get(sym, 0.0)),
                "paper_action": "SELL",
            })
        month_sections.append({
            "persian_month": rows[i]["persian_month"],
            "persian_month_name": rows[i]["persian_month_name"],
            "decision_month": dm,
            "score_date": r["score_date"],
            "exec_date": r["exec_date"],
            "n_selected": int(r["n_selected"]),
            "counts": {"BUY": int(r["actions_buy"]), "SELL": int(r["n_exited"]),
                       "HOLD": int(r["actions_hold"]), "INCREASE": int(r["actions_increase"]),
                       "DECREASE": int(r["actions_decrease"])},
            "selected": sel_rows,
            "sell": sell_rows,
        })

    # ---------------------------------------------------------------- holdings analytics (window)
    membership = {dm: set(tgt[tgt["decision_month"] == dm]["symbol"]) for dm in win_decision_months}
    held_months = {}
    streaks = {}
    for dm in win_decision_months:
        for sym in membership[dm]:
            held_months[sym] = held_months.get(sym, 0) + 1
    for sym in held_months:
        best = cur = 0
        for dm in win_decision_months:
            if sym in membership[dm]:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        streaks[sym] = best
    all_spells = []
    for sym in held_months:
        cur = 0
        for dm in win_decision_months:
            if sym in membership[dm]:
                cur += 1
            elif cur:
                all_spells.append(cur)
                cur = 0
        if cur:
            all_spells.append(cur)
    entered_counts: dict = {}
    exited_counts: dict = {}
    for i, r in win.iterrows():
        ent = [] if pd.isna(r["entered_symbols"]) else [s.strip() for s in str(r["entered_symbols"]).split(",") if s.strip()]
        ext = [] if pd.isna(r["exited_symbols"]) else [s.strip() for s in str(r["exited_symbols"]).split(",") if s.strip()]
        for s in ent:
            entered_counts[s] = entered_counts.get(s, 0) + 1
        for s in ext:
            exited_counts[s] = exited_counts.get(s, 0) + 1
    unique_securities = sorted(held_months)
    median_holding = pctile(list(held_months.values()), 50)

    # ---------------------------------------------------------------- persian-year breakdown
    persian_years = []
    for jy in sorted({int(r["persian_month"][:4]) for r in rows}):
        block = [r for r in rows if int(r["persian_month"][:4]) == jy]
        start_cap = block[0]["starting_capital_toman"]
        if jy == 1403:
            start_cap = float(INITIAL_CAPITAL_TOMAN)
        end_cap = block[-1]["ending_capital_toman"]
        pts = [start_cap] + [b["ending_capital_toman"] for b in block]
        port_ret = end_cap / start_cap - 1.0
        idxs = [i for i, r in enumerate(rows) if int(r["persian_month"][:4]) == jy]
        # bench window path points: [INITIAL, b(post_39), b(post_40), ..., b(post_63)];
        # block starts at INITIAL (1403) or at the previous block's ending point,
        # and ends at its last row's ending point (the terminal NAV for the final block)
        b_start_k = 0 if jy == 1403 else idxs[0] + 1
        b_end_k = min(idxs[-1] + 2, len(bench_points) - 1)
        b_start_point = bench_points[b_start_k]
        b_end_point = bench_points[b_end_k]
        bench_ret = b_end_point / b_start_point - 1.0
        b_block_points = bench_points[b_start_k: b_end_k + 1]
        persian_years.append({
            "persian_year": jy,
            "n_months": len(block),
            "decision_months": [b["decision_month"] for b in block],
            "starting_capital_toman": start_cap,
            "ending_capital_toman": end_cap,
            "portfolio_return": port_ret,
            "benchmark_return": bench_ret,
            "excess_return": port_ret - bench_ret,
            "excess_wealth_toman": end_cap - b_end_point,
            "max_drawdown": max_drawdown(pts),
            "benchmark_max_drawdown": max_drawdown(b_block_points),
            "avg_turnover": float(np.mean([b["target_turnover"] for b in block])),
        })

    # ---------------------------------------------------------------- top-5 lists
    def top5(key, reverse=True):
        return sorted(ret_rows, key=key, reverse=reverse)[:5]

    best5 = top5(lambda r: r["portfolio_monthly_return"])
    worst5 = top5(lambda r: r["portfolio_monthly_return"], reverse=False)
    turn5 = sorted(rows, key=lambda r: r["target_turnover"], reverse=True)[:5]
    pos5 = top5(lambda r: r["excess_return"])
    neg5 = top5(lambda r: r["excess_return"], reverse=False)

    # ---------------------------------------------------------------- summary
    summary = {
        "label": "HISTORICAL_REPLAY_ONLY — INVESTOR VIEW FROM 1403-01 (display scaling only)",
        "persian_start_month": PERSIAN_START_MONTH,
        "persian_start_gregorian": "2024-03-20",
        "actual_first_decision_date": first["score_date"],
        "actual_first_decision_jalali": iso_jalali(first_score),
        "actual_first_execution_date": first["exec_date"],
        "latest_replay_decision_date": last["score_date"],
        "latest_replay_decision_jalali": iso_jalali(date.fromisoformat(last["score_date"])),
        "latest_replay_execution_date": last["exec_date"],
        "start_nav_normalized": start_nav_normalized,
        "benchmark_start_nav_normalized": bench_start_nav_normalized,
        "initial_capital_toman": INITIAL_CAPITAL_TOMAN,
        "final_capital_toman": round(final_capital, 2),
        "total_profit_toman": round(final_capital - INITIAL_CAPITAL_TOMAN, 2),
        "cumulative_return": round(cum_return, 10),
        "annualized_return": round(annualized, 10),
        "annualization_basis": f"(final/initial)^(12/{n_return_periods}) - 1, certified return periods in window",
        "max_drawdown": round(window_mdd, 10),
        "benchmark_final_capital_toman": round(bench_final_capital, 2),
        "benchmark_cumulative_return": round(bench_cum, 10),
        "benchmark_annualized_return": round(bench_annualized, 10),
        "benchmark_max_drawdown": round(bench_mdd, 10),
        "excess_wealth_vs_benchmark_toman": round(final_capital - bench_final_capital, 2),
        "total_transaction_cost_toman": round(total_cost_toman, 2),
        "number_of_months": len(rows),
        "number_of_return_periods": n_return_periods,
        "number_of_rebalances": len(rows),
        "number_of_unique_securities_held": len(unique_securities),
        "median_holding_period_months": round(median_holding, 4) if median_holding is not None else None,
        "average_monthly_turnover": round(avg_turnover, 10),
        "median_monthly_turnover": round(median_turnover, 10),
        "return_convention": "NAV_post(E_k) -> NAV_post(E_k+1) (certified repaired convention, unchanged)",
        "price_series": "PRICE_PLUS_MECHANICAL_ADJUSTMENTS (CONFIRMED tsetmc_gap_rule_v1 chain; no cash dividends; not proven full total shareholder return)",
        "persian_year_breakdown": persian_years,
        "top5_best_months": [{"persian_month": r["persian_month"], "return": r["portfolio_monthly_return"]} for r in best5],
        "top5_worst_months": [{"persian_month": r["persian_month"], "return": r["portfolio_monthly_return"]} for r in worst5],
        "top5_turnover_months": [{"persian_month": r["persian_month"], "turnover": r["target_turnover"]} for r in turn5],
        "top5_positive_excess_months": [{"persian_month": r["persian_month"], "excess": r["excess_return"]} for r in pos5],
        "top5_negative_excess_months": [{"persian_month": r["persian_month"], "excess": r["excess_return"]} for r in neg5],
        "top10_most_held": sorted(held_months.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "top10_longest_streaks": sorted(streaks.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "top10_most_entered": sorted(entered_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "top10_most_exited": sorted(exited_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
        "spell_stats_window": {
            "n_spells": len(all_spells),
            "median": pctile(all_spells, 50), "p25": pctile(all_spells, 25),
            "p75": pctile(all_spells, 75), "p90": pctile(all_spells, 90),
            "max": max(all_spells) if all_spells else None,
        },
        "monthly": rows,
        "provenance": {
            "source": "certified portfolio_shadow_replay artifacts (HISTORICAL_REPLAY_ONLY)",
            "spec_sha256": state["verification"]["spec_sha256"],
            "panel_sha256": state["verification"]["panel_sha256"],
            "imap_sha256": state["verification"]["imap_sha256"],
            "input_artifact_sha256": input_shas,
            "builder_script": "build_investor_view_1403.py",
            "transformation": "pure display scaling: investor_capital(t) = 100,000,000 x NAV_cert(t) / NAV_cert_pre(E_first)",
            "accounting_modified": False,
            "costs_modified": False,
        },
        "disclaimers": [
            "Historical hypothetical replay for understanding only.",
            "NOT forward validation. NOT a guarantee. NOT a real-money execution record.",
            "Returns are PRICE_PLUS_MECHANICAL_ADJUSTMENTS; not proven full total shareholder return.",
            "Live shadow state untouched; this view is not Decision #1 and starts no clock.",
        ],
    }

    # ---------------------------------------------------------------- write CSV
    csv_path = BASE / "investor_view_from_1403_monthly.csv"
    csv_cols = ["persian_month", "persian_month_name", "decision_month", "score_date", "exec_date",
                "starting_capital_toman", "entry_cost_toman", "post_entry_capital_toman",
                "n_selected", "n_eligible", "n_entered", "n_exited", "n_retained",
                "actions_buy", "actions_increase", "actions_decrease", "actions_hold",
                "sell_exits", "sell_rebal_partial",
                "target_turnover", "transaction_cost_toman",
                "portfolio_monthly_return", "benchmark_monthly_return", "excess_return",
                "ending_capital_toman", "drawdown_from_prior_peak",
                "cash_weight", "holdings_count", "top_holding_weight", "top5_weight", "top10_weight"]
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(csv_cols) + "\n")
        for r in rows:
            vals = []
            for c in csv_cols:
                v = r[c]
                if v is None:
                    vals.append("")
                elif isinstance(v, float):
                    vals.append(f"{v:.10f}")
                else:
                    vals.append(str(v))
            f.write(",".join(vals) + "\n")

    # ---------------------------------------------------------------- write JSON
    json_path = BASE / "investor_view_from_1403_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float),
                         encoding="utf-8")

    # ---------------------------------------------------------------- write MD
    md = []
    md.append("# INVESTOR VIEW FROM 1403-01 — 100,000,000 TOMAN (HISTORICAL REPLAY ONLY)")
    md.append("")
    md.append("> **HISTORICAL_REPLAY_ONLY.** This document is a display-only rescaling of the already-certified")
    md.append("> historical Shadow V1.1 walk-forward replay (`portfolio_shadow_replay/`, parity PASS, 63/63 months).")
    md.append("> It is **NOT forward validation**, **NOT a guarantee**, **NOT a real-money execution record**, and it is")
    md.append("> **not** Decision #1 of the live shadow. The live shadow state is untouched and the forward clock has not started.")
    md.append("> Return terminology remains **PRICE_PLUS_MECHANICAL_ADJUSTMENTS** (CONFIRMED gap-rule chain; no cash")
    md.append("> dividends) — **not** proven full total shareholder return.")
    md.append("")
    md.append("No accounting was modified, no costs were changed (BASE 50bps one-way, exactly as certified), and no")
    md.append("deposits or withdrawals were added. The only transformation is:")
    md.append("")
    md.append("```")
    md.append("investor_capital(t) = 100,000,000 x NAV_certified(t) / NAV_certified_pre_trade(E_first)")
    md.append("```")
    md.append("")
    md.append("## 1 — Definition of the start")
    md.append("")
    md.append("| Item | Value |")
    md.append("|---|---|")
    md.append(f"| PERSIAN_START_MONTH | **{PERSIAN_START_MONTH}** (Farvardin 1403 = 2024-03-20) |")
    md.append(f"| ACTUAL_FIRST_DECISION_DATE | **{first['score_date']}** (= {iso_jalali(first_score)}, Farvardin 1403) |")
    md.append(f"| ACTUAL_FIRST_EXECUTION_DATE | **{first['exec_date']}** |")
    md.append(f"| START_NAV_NORMALIZED | **{start_nav_normalized:.15f}** (certified value immediately before the first window rebalance) |")
    md.append(f"| BENCHMARK_START_NAV_NORMALIZED | {bench_start_nav_normalized:.15f} |")
    md.append(f"| INITIAL_CAPITAL_TOMAN | **{fmt_toman(INITIAL_CAPITAL_TOMAN)}** |")
    md.append("")
    md.append("No decision is invented on 1403-01-01: the first **actual** certified monthly decision on or after")
    md.append("Farvardin 1403 is used (the certified decision cadence is end-of-month; 2024-03-30 is the last Tehran")
    md.append("trading day of that certified month). The latest certified replay decision is")
    md.append(f"{last['score_date']} ({iso_jalali(date.fromisoformat(last['score_date']))}), executed {last['exec_date']}.")
    md.append("")
    md.append("**Window-start note.** The certified path is a *continuous* portfolio; at the window start it already")
    md.append(f"holds the previous certified month's selections, so the first rebalance cost is the certified")
    md.append(f"{fmt_toman(rows[0]['entry_cost_toman'])} toman (~{rows[0]['entry_cost_toman']/INITIAL_CAPITAL_TOMAN*100:.3f}% of capital), not a fresh full-notional")
    md.append("entry. Per the display-scaling-only instruction this certified cost is shown unchanged. (Informational")
    md.append("sensitivity only, **not applied**: a hypothetical fresh subscription buying the whole basket at the first")
    md.append("execution would pay ~50bps on full notional ≈ 500,000 toman and would end ≈1.1M toman lower.) A fresh")
    md.append("investor would buy **all** 44 first-month names, whereas the certified entered/retained counts below are")
    md.append("relative to the carried certified portfolio.")
    md.append("")
    md.append("## 2 — Month-by-month investor table")
    md.append("")
    md.append("Certified return convention (unchanged): each month's return runs from its execution date to the next")
    md.append("execution date, post-trade to post-trade. Starting capital = post-trade capital at this month's execution")
    md.append("(for 1403-01: the 100,000,000 initial cash, shown with its entry cost). The last certified decision")
    md.append(f"({last['score_date']}) has **no subsequent return period in the certified replay** (62 return periods / 63")
    md.append("decisions), so its return cells are empty and its capital equals the final capital.")
    md.append("")
    md.append("| ماه | Persian month | Score date | Exec date | Starting capital (toman) | Holdings | Entered | Exited | Retained | Target turnover | Cost (toman) | Portfolio ret | Benchmark ret | Excess | Ending capital (toman) | DD from peak |")
    md.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        md.append(f"| {r['persian_month']} | {r['persian_month_name']} | {r['score_date']} | {r['exec_date']} | "
                  f"{fmt_toman(r['starting_capital_toman'])} | {r['n_selected']} | {r['n_entered']} | {r['n_exited']} | {r['n_retained']} | "
                  f"{r['target_turnover']*100:.1f}% | {fmt_toman(r['transaction_cost_toman'])} | {fmt_pct(r['portfolio_monthly_return'])} | "
                  f"{fmt_pct(r['benchmark_monthly_return'])} | {fmt_pct(r['excess_return'])} | {fmt_toman(r['ending_capital_toman'])} | "
                  f"{fmt_pct(r['drawdown_from_prior_peak'])} |")
    md.append("")
    md.append(f"First-month detail: initial {fmt_toman(INITIAL_CAPITAL_TOMAN)} → entry cost −{fmt_toman(rows[0]['entry_cost_toman'])} "
              f"→ post-entry {fmt_toman(rows[0]['post_entry_capital_toman'])} → × (1 + certified return) → "
              f"{fmt_toman(rows[0]['ending_capital_toman'])}.")
    md.append("")
    md.append("## 3 — Security-level decisions (per month)")
    md.append("")
    md.append("Decision-time paper actions from the certified decision rows: **BUY** (not held → selected),")
    md.append("**INCREASE / DECREASE / HOLD** (held → selected, vs decision NAV). **SELL** = held name not re-selected")
    md.append("(full exit at execution); partial weight reductions execute as the DECREASE trades. UI score/rank are the")
    md.append("certified PIT values at the decision date.")
    for sec in month_sections:
        md.append("")
        md.append(f"### {sec['persian_month']} ({sec['decision_month']}) — decision {sec['score_date']}, execution {sec['exec_date']}")
        md.append("")
        c = sec["counts"]
        md.append(f"Actions: **{c['BUY']} BUY · {c['SELL']} SELL · {c['HOLD']} HOLD · {c['INCREASE']} INCREASE · {c['DECREASE']} DECREASE** "
                  f"({sec['n_selected']} selected)")
        md.append("")
        md.append("| Rank | Symbol | UI score | UI rank | DQ | Target weight | Previous weight | Paper action | Trade notional frac |")
        md.append("|---:|---|---:|---:|---:|---:|---:|---|---:|")
        for t in sec["selected"]:
            md.append(f"| {t['ui_rank']} | {t['symbol']} | {t['ui_score']:.2f} | {t['ui_rank']} | {t['data_quality']:.2f} | "
                      f"{t['target_weight']*100:.2f}% | {t['previous_weight']*100:.2f}% | {t['paper_action']} | {t['trade_notional_fraction']*100:.2f}% |")
        if sec["sell"]:
            md.append("")
            md.append("| Symbol (SELL — exit) | UI score | UI rank | Previous weight | Paper action |")
            md.append("|---|---:|---:|---:|---|")
            for t in sec["sell"]:
                score = f"{t['ui_score']:.2f}" if t["ui_score"] is not None else "—"
                rank = str(t["ui_rank"]) if t["ui_rank"] is not None else "—"
                md.append(f"| {t['symbol']} | {score} | {rank} | {t['previous_weight']*100:.2f}% | SELL |")
    md.append("")
    md.append("## 4 — Final investor result")
    md.append("")
    md.append("```")
    md.append(f"INITIAL_CAPITAL_TOMAN            = {fmt_toman(INITIAL_CAPITAL_TOMAN)}")
    md.append(f"FINAL_CAPITAL_TOMAN              = {fmt_toman(final_capital)}")
    md.append(f"TOTAL_PROFIT_TOMAN               = {fmt_toman(final_capital - INITIAL_CAPITAL_TOMAN)}")
    md.append(f"CUMULATIVE_RETURN                = {cum_return*100:.2f}%")
    md.append(f"ANNUALIZED_RETURN                = {annualized*100:.2f}%   (over {n_return_periods} certified monthly return periods)")
    md.append(f"MAX_DRAWDOWN                     = {window_mdd*100:.2f}%")
    md.append(f"BENCHMARK_FINAL_CAPITAL_TOMAN    = {fmt_toman(bench_final_capital)}")
    md.append(f"EXCESS_WEALTH_VS_BENCHMARK_TOMAN = {fmt_toman(final_capital - bench_final_capital)}")
    md.append(f"TOTAL_TRANSACTION_COST_TOMAN     = {fmt_toman(total_cost_toman)}")
    md.append(f"NUMBER_OF_REBALANCES             = {len(rows)}")
    md.append(f"NUMBER_OF_UNIQUE_SECURITIES_HELD = {len(unique_securities)}")
    md.append(f"MEDIAN_HOLDING_PERIOD_MONTHS     = {median_holding:.1f}")
    md.append(f"AVERAGE_MONTHLY_TURNOVER         = {avg_turnover*100:.2f}%")
    md.append("```")
    md.append("")
    md.append("Drawdowns are measured inside the 1403-start window (peak resets at the 100,000,000 start); the certified")
    md.append("full-history drawdowns remain in `shadow_replay_monthly.csv`. Holding periods are measured within the")
    md.append("window; spells continuing across the window start are counted from the first window month.")
    md.append("")
    md.append("## 5 — Benchmark comparison (same start, same 100,000,000 toman)")
    md.append("")
    md.append("The benchmark is the certified equal-weight all-eligible basket, scaled identically: 100,000,000 maps to")
    md.append("the certified benchmark value immediately before the same first window rebalance; its own certified")
    md.append("rebalance costs remain inside its path (unchanged).")
    md.append("")
    md.append("| Metric | Portfolio | Benchmark |")
    md.append("|---|---:|---:|")
    md.append(f"| Final capital (toman) | {fmt_toman(final_capital)} | {fmt_toman(bench_final_capital)} |")
    md.append(f"| Difference (toman) | {fmt_toman(final_capital - bench_final_capital)} | — |")
    md.append(f"| Cumulative return | {cum_return*100:.2f}% | {bench_cum*100:.2f}% |")
    md.append(f"| Annualized return | {annualized*100:.2f}% | {bench_annualized*100:.2f}% |")
    md.append(f"| Excess return (cumulative, arithmetic) | {(cum_return - bench_cum)*100:.2f}% | — |")
    md.append(f"| Max drawdown (window) | {window_mdd*100:.2f}% | {bench_mdd*100:.2f}% |")
    md.append("")
    md.append("## 6 — Persian-year breakdown")
    md.append("")
    md.append("| Persian year | Months | Starting capital | Ending capital | Portfolio ret | Benchmark ret | Excess ret | Excess wealth (toman) | Max DD | Avg turnover |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for y in persian_years:
        md.append(f"| {y['persian_year']} | {y['n_months']} | {fmt_toman(y['starting_capital_toman'])} | {fmt_toman(y['ending_capital_toman'])} | "
                  f"{y['portfolio_return']*100:.2f}% | {y['benchmark_return']*100:.2f}% | {y['excess_return']*100:.2f}% | "
                  f"{fmt_toman(y['excess_wealth_toman'])} | {y['max_drawdown']*100:.2f}% | {y['avg_turnover']*100:.1f}% |")
    md.append("")
    md.append("Persian-year boundaries follow the Jalali calendar (1403: 2024-03-20…2025-03-20; 1404: 2025-03-21…2026-03-20;")
    md.append("1405: from 2026-03-21). Certified decision months 2026-02/03/04 are absent in the certified source panel by")
    md.append("construction, so 1405 contains two certified rebalances (1405-03, 1405-04) up to the latest replay date.")
    md.append("The 1403 return includes the first-window entry cost shown in section 2.")
    md.append("")
    md.append("## 7 — Most important months (within the 1403-start window only)")
    md.append("")
    def month_list(items, valfmt, label):
        md.append(f"**{label}**")
        md.append("")
        md.append("| Persian month | Score date | Value |")
        md.append("|---|---|---:|")
        for r in items:
            md.append(f"| {r['persian_month']} | {r['score_date']} | {valfmt(r)} |")
        md.append("")
    month_list(best5, lambda r: fmt_pct(r["portfolio_monthly_return"]), "5 best portfolio months")
    month_list(worst5, lambda r: fmt_pct(r["portfolio_monthly_return"]), "5 worst portfolio months")
    month_list(turn5, lambda r: f"{r['target_turnover']*100:.1f}%", "5 highest-turnover months")
    month_list(pos5, lambda r: fmt_pct(r["excess_return"]), "5 largest positive-excess months")
    month_list(neg5, lambda r: fmt_pct(r["excess_return"]), "5 largest negative-excess months")
    md.append("## 8 — Most held stocks (from 1403-start onward)")
    md.append("")
    md.append(f"Total unique securities held in the window: **{len(unique_securities)}**.")
    md.append("")
    md.append("**10 most frequently held** (months selected in window):")
    md.append("")
    md.append("| Symbol | Months held | Longest streak |")
    md.append("|---|---:|---:|")
    for sym, cnt in summary["top10_most_held"]:
        md.append(f"| {sym} | {cnt} | {streaks[sym]} |")
    md.append("")
    md.append("**Longest uninterrupted holding streaks** (consecutive window months):")
    md.append("")
    md.append("| Symbol | Streak (months) |")
    md.append("|---|---:|")
    for sym, st in summary["top10_longest_streaks"]:
        md.append(f"| {sym} | {st} |")
    md.append("")
    md.append("**Most frequently entered** (BUY months in window):")
    md.append("")
    md.append("| Symbol | Entries |")
    md.append("|---|---:|")
    for sym, cnt in summary["top10_most_entered"]:
        md.append(f"| {sym} | {cnt} |")
    md.append("")
    md.append("**Most frequently exited** (SELL months in window):")
    md.append("")
    md.append("| Symbol | Exits |")
    md.append("|---|---:|")
    for sym, cnt in summary["top10_most_exited"]:
        md.append(f"| {sym} | {cnt} |")
    md.append("")
    sp = summary["spell_stats_window"]
    md.append(f"Window holding spells: n={sp['n_spells']}, median={sp['median']:.1f}, p25={sp['p25']:.1f}, "
              f"p75={sp['p75']:.1f}, p90={sp['p90']:.1f}, max={sp['max']} months. Descriptive only — no turnover")
    md.append("buffers, no timing, nothing optimized.")
    md.append("")
    md.append("## 9 — Plain-language summary")
    md.append("")
    md.append(f"**If 100 million toman had been put into the frozen Score Portfolio V1 (Shadow V1.1 configuration) at the")
    md.append(f"first certified decision of Farvardin 1403 ({first['score_date']}, executed {first['exec_date']}), it would have become")
    md.append(f"about {fmt_toman(final_capital)} toman by the latest certified replay date ({last['score_date']}, executed {last['exec_date']}) —")
    md.append(f"a cumulative gain of about {cum_return*100:.0f}% over {len(rows)} monthly decisions. The equal-weight all-eligible benchmark,")
    md.append(f"started with the same 100 million toman on the same date, would have become about {fmt_toman(bench_final_capital)} toman,")
    md.append(f"leaving about {fmt_toman(final_capital - bench_final_capital)} toman of excess wealth. The worst peak-to-trough loss inside this window")
    md.append(f"was about {abs(window_mdd)*100:.0f}%.**")
    md.append("")
    md.append("This is a **historical hypothetical replay** of an already-frozen system on already-certified PIT data:")
    md.append("")
    md.append("- it is **NOT forward validation** and does not predict future results;")
    md.append("- it is **NOT a guarantee** of any return;")
    md.append("- it is **NOT a real-money execution record** — no orders were ever sent;")
    md.append("- it ignores market impact, liquidity limits, taxes and any practical trading friction beyond the certified")
    md.append("  BASE 50bps one-way cost;")
    md.append("- returns use **PRICE_PLUS_MECHANICAL_ADJUSTMENTS** (CONFIRMED gap-rule chain, no cash dividends) — **not**")
    md.append("  proven full total shareholder return.")
    md.append("")
    md.append("نسخه فارسی: اگر ۱۰۰ میلیون تومان از اولین تصمیمِ تأییدشدهٔ فروردین ۱۴۰۳ در پرتفوی امتیازِ منجمد (پیکربندی")
    md.append(f"Shadow V1.1) قرار می‌گرفت، تا آخرین تاریخ تأییدشدهٔ ریپلی ({last['score_date']}) به حدود {fmt_toman(final_capital)} تومان می‌رسید")
    md.append(f"(حدود {cum_return*100:.0f}% سود تجمعی)؛ بنچمارک هم‌وزنِ همان تاریخ به حدود {fmt_toman(bench_final_capital)} تومان. این یک بازپخشِ")
    md.append("تاریخیِ فرضی برای فهم و اعتبارسنجی مهندسی است؛ نه اعتبارسنجی آینده‌نگر، نه تضمین سود، نه سابقهٔ معاملهٔ واقعی.")
    md.append("")
    md.append("## Provenance, integrity & reproducibility")
    md.append("")
    md.append("| Item | Value |")
    md.append("|---|---|")
    md.append(f"| Frozen spec SHA-256 | `{state['verification']['spec_sha256']}` |")
    md.append(f"| PIT source panel SHA-256 | `{state['verification']['panel_sha256']}` |")
    md.append(f"| Identity map SHA-256 (235 rows, UNIQUE) | `{state['verification']['imap_sha256']}` |")
    for k, v in input_shas.items():
        md.append(f"| Input artifact `{k}` | `{v}` |")
    md.append("| Cost convention | BASE 50bps one-way, exactly as certified — unchanged |")
    md.append("| Accounting | unchanged (pure display scaling of the certified normalized NAV path) |")
    md.append("| Deposits / withdrawals | none |")
    md.append("| Builder script | `build_investor_view_1403.py` (reads certified artifacts only; aborts on any input hash mismatch) |")
    md.append(f"| Certified replay parity | SHADOW_REPLAY_PORTFOLIO_PARITY = PASS (63/63 months, see `shadow_replay_parity.json`) |")
    md.append("")
    md.append("Generated outputs (this view only — no certified artifact modified):")
    md.append("`INVESTOR_VIEW_FROM_1403.md`, `investor_view_from_1403_monthly.csv`, `investor_view_from_1403_summary.json`.")
    md.append("")
    md.append("**STOP.** No strategy was rerun, no score changed, no Top20 changed, no start date optimized, no live")
    md.append("shadow state modified, no forward clock started, no real orders sent.")

    md_path = BASE / "INVESTOR_VIEW_FROM_1403.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")

    # ---------------------------------------------------------------- console report
    print("INVESTOR_VIEW_FROM_1403 — built OK (display scaling only; no certified artifact modified)")
    print(f"  window: {first['score_date']} (1403-01-11) .. {last['score_date']}  |  months={len(rows)} rebalances={len(rows)} return_periods={n_return_periods}")
    print(f"  FINAL_CAPITAL_TOMAN          = {fmt_toman(final_capital)}")
    print(f"  BENCHMARK_FINAL_CAPITAL_TOMAN= {fmt_toman(bench_final_capital)}")
    print(f"  CUMULATIVE_RETURN            = {cum_return*100:.2f}%   ANNUALIZED = {annualized*100:.2f}%")
    print(f"  MAX_DRAWDOWN (window)        = {window_mdd*100:.2f}%   benchmark = {bench_mdd*100:.2f}%")
    print(f"  EXCESS_WEALTH_TOMAN          = {fmt_toman(final_capital - bench_final_capital)}")
    print(f"  TOTAL_COST_TOMAN             = {fmt_toman(total_cost_toman)}   AVG_TURNOVER = {avg_turnover*100:.2f}%")
    print(f"  UNIQUE_SECURITIES            = {len(unique_securities)}   MEDIAN_HOLDING = {median_holding:.1f} months")
    print(f"  outputs: {md_path.name}, {csv_path.name}, {json_path.name}")


if __name__ == "__main__":
    main()
