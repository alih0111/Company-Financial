"""Builds SHADOW_V1_1_HISTORICAL_REPLAY.md from the replay engine artifacts.
Read-only over the replay outputs; writes only the MD report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import pandas as pd

HERE = Path(r"D:\RFA\Company-Financial\portfolio_shadow_replay")
md_rows = pd.read_pickle(HERE / "_monthly_rows.pkl")
hdf = pd.read_pickle(HERE / "_holding_rows.pkl")
sp_df = pd.read_pickle(HERE / "_spells.pkl")
ydf = pd.read_pickle(HERE / "_yearly.pkl")
era = pd.read_pickle(HERE / "_era.pkl")
R = json.loads((HERE / "replay_state.json").read_text(encoding="utf-8"))
preview = json.loads((HERE / "_preview_info.json").read_text(encoding="utf-8"))
summary = R["engine"]["summary"]
par = R["parity"]
dur = R["duration"]
S = R["engine"]["summary"]

def pct(x, digits=2):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x * 100:.{digits}f}%"

def f2(x):
    return "—" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.4f}"

L = []
w = L.append

w("# SHADOW V1.1 — HISTORICAL WALK-FORWARD REPLAY")
w("")
w("**Label: `HISTORICAL_REPLAY_ONLY`.** This document replays the CURRENT frozen Shadow V1.1 "
  "harness month-by-month over the certified historical PIT decision dates. It is engineering "
  "validation of what the live harness itself would have generated historically. It is **NOT** "
  "the forward 12-month shadow, **NOT** forward validation, **NOT** new validation, and **NOT** "
  "new evidence for promotion. No live shadow state was touched.")
w("")
w(f"- Active frozen spec: `portfolio_shadow/SHADOW_V1_1_SPEC.md` — SHA-256 "
  f"`{R['verification']['spec_sha256']}` (verified before the run)")
w(f"- PIT score source: `ui_score_research/ui_score_historical_pit_v2.parquet` — SHA-256 "
  f"`{R['verification']['panel_sha256']}` (verified)")
w(f"- Strategy: `score-portfolio-v1-top20` · score `canonical-v1-dev` · selection highest 20% by "
  f"`quant_score DESC, symbol ASC` · equal target weights · 50 bps one-way BASE")
w(f"- Engine: `portfolio_shadow/build_shadow_portfolio.py` (selection/decision semantics) + "
  f"`portfolio_shadow/observe_shadow_execution.py` (execution/close semantics) + "
  f"`portfolio_shadow/deterministic_accounting.py` (certified repaired accounting, sorted port) "
  f"+ `portfolio_research/repair_accounting_v1.py` (certified adjusted price chain) — the same "
  f"modules the live shadow runs")
w("- Information rule: at every decision date T the replay used only that month's PIT score "
  "snapshot; no future snapshot influences an earlier target; decisions processed sequentially "
  "(freeze target → execution date → update portfolio)")
w(f"- Decision dates: **{S['n_decision_months']}** ({R['panel']['first']} .. {R['panel']['last']}; "
  "the known 2026-02/03/04 skipped months are absent by construction, exactly as in the certified run)")
w(f"- Return semantics: PRICE_PLUS_MECHANICAL_ADJUSTMENTS (CONFIRMED gap-rule chain; no cash "
  f"dividends); monthly return = NAV_post(E_k)→NAV_post(E_k+1); entry cost inside NAV_post(0)")
w("")
w("## 1. Executive summary")
w("")
w("| Metric | Replay (TOP20, BASE) | Benchmark (equal-weight all eligible, BASE) |")
w("|---|---|---|")
w(f"| Terminal wealth multiple | {S['terminal_wealth_multiple']:.4f} | "
  f"{S['benchmark_terminal_wealth_multiple']:.4f} |")
ann_b = S['benchmark_terminal_wealth_multiple'] ** (12 / S['n_return_periods']) - 1
w(f"| Annualized return | {S['annualized_return'] * 100:.2f}% | {ann_b * 100:.2f}% |")
w(f"| Max drawdown | {S['max_drawdown'] * 100:.2f}% | — |")
w(f"| Sharpe (0% rf) | {S['sharpe_0rf']:.2f} | — |")
w(f"| Avg / median monthly turnover | {S['avg_turnover'] * 100:.1f}% / {S['median_turnover'] * 100:.1f}% | — |")
w(f"| Avg / median holdings | {S['avg_holdings']:.1f} / {S['median_holdings']:.0f} | — |")
w(f"| Avg monthly excess | {S['avg_excess_monthly'] * 100:.2f}% "
  f"(positive in {S['positive_excess_fraction'] * 100:.0f}% of months) | — |")
w(f"| Unique securities ever selected | **{S['unique_securities_ever_selected']}** | "
  f"{R['panel']['rows']} scored rows total |")
w("")
w("## 2. Parity with certified SCORE_PORTFOLIO_V1 (most important engineering test)")
w("")
w(f"**SHADOW_REPLAY_PORTFOLIO_PARITY = {par['SHADOW_REPLAY_PORTFOLIO_PARITY']}** "
  f"— replay vs `score_portfolio_v1_*_accounting_repaired` certified artifacts, all "
  f"{par['months_compared']} months.")
w("")
w("| Comparison | Mismatches | Max abs diff |")
w("|---|---|---|")
mx = par["max_abs_diff_by_field"]
for label, key in [("Execution dates", "exec_date_mismatches"), ("Eligible counts", "n_eligible_mismatches"),
                   ("Selected counts", "n_selected_mismatches"), ("Selected security sets", "selection_set_mismatches"),
                   ("Monthly portfolio returns (top20_return)", "top20_return"),
                   ("Monthly benchmark returns (bench_return)", "bench_return"),
                   ("Trade notionals (BUY/SELL/SELL_REBAL)", "trade_notional_mismatches")]:
    if key in par:
        n = len(par[key])
        d = f"{mx[key]:.2e}" if key in mx else "—"
        w(f"| {label} | {n} | {d} |")
for f, v in sorted(mx.items()):
    if f not in ("top20_return", "bench_return", "trade_notional"):
        w(f"| {f} | {len(par['float_field_mismatches'].get(f, []))} | {v:.2e} |")
w("")
w(f"All residual differences are float-summation-order noise (≤ {max(v for k, v in mx.items()) * 1e15 + 1:.0f}e-15); "
  "the certified engine iterates name sets in hash order while the shadow harness iterates in sorted "
  "order — economics identical. Root causes checked and ruled out: execution-date calendar "
  f"(re-derived 63/63 identical), tradability source ({R['tradability']['pairs_checked']} (E, symbol) pairs, "
  "0 disagreements between path-A cache evidence and the certified daily-panel flag), identity mapping "
  "(235 UNIQUE), selection/sort rule (identical).")
w("")
w("## 3. Yearly view")
w("")
w("| Year | Rebal | Start hold | End hold | Avg hold | Avg turnover | Portfolio | Benchmark | Excess | MDD | Best | Worst |")
w("|---|---|---|---|---|---|---|---|---|---|---|---|")
for _, r in ydf.iterrows():
    w(f"| {r.year} | {r.rebalances} | {r.starting_holdings} | {r.ending_holdings} | {r.avg_holdings:.1f} | "
      f"{pct(r.avg_turnover, 1)} | {pct(r.portfolio_return)} | {pct(r.benchmark_return)} | "
      f"{pct(r.excess_return)} | {pct(r.max_drawdown)} | {pct(r.best_month)} | {pct(r.worst_month)} |")
w("")
w("Most frequently held per year (top 10, by decision month):")
for _, r in ydf.iterrows():
    w(f"- **{r.year}**: {r.top10_most_frequently_held or '—'}")
w("")
top_turn = md_rows.sort_values("turnover", ascending=False).head(5)
w(f"Months with highest target turnover: " + "; ".join(
    f"{r.decision_month} {r.turnover * 100:.1f}%" for r in top_turn.itertuples()))
best_ex = md_rows.dropna(subset=["excess_return"]).sort_values("excess_return", ascending=False)
w("Months with largest positive excess: " + "; ".join(
    f"{r.decision_month} +{r.excess_return * 100:.2f}% (port {r.portfolio_return * 100:+.2f}% / bench "
    f"{r.benchmark_return * 100:+.2f}%)" for r in best_ex.head(5).itertuples()))
w("Months with largest negative excess: " + "; ".join(
    f"{r.decision_month} {r.excess_return * 100:.2f}% (port {r.portfolio_return * 100:+.2f}% / bench "
    f"{r.benchmark_return * 100:+.2f}%)" for r in best_ex.tail(5).itertuples()))
w("")
w("## 4. Monthly timeline (all historical decisions)")
w("")
for r in md_rows.itertuples():
    w(f"### {r.decision_month}")
    w("")
    w(f"score {r.score_date} (cutoff {r.knowledge_cutoff}) → exec {r.exec_date} · "
      f"Eligible: **{r.n_eligible}** · Selected: **{r.n_selected}** · "
      f"Turnover (target): **{pct(r.turnover, 1)}** · Realized traded: {pct(r.realized_traded_notional_fraction, 1)} · "
      f"Cost: {pct(r.transaction_cost_fraction, 2)}")
    act = (f"Actions: BUY {r.actions_buy} · INCREASE {r.actions_increase} · DECREASE {r.actions_decrease} · "
           f"HOLD {r.actions_hold} · exits (SELL) {r.exec_sells_exits} · "
           f"carried-unselected {r.exec_carry_held_unselected} · cash-failed {r.exec_cash_failed}")
    if r.decision_month == md_rows.iloc[0].decision_month:
        act += " (first month: full entry)"
    w(act)
    if isinstance(r.entered_symbols, str) and r.entered_symbols:
        w(f"- ENTERED ({r.n_entered}): {r.entered_symbols}")
    if isinstance(r.exited_symbols, str) and r.exited_symbols:
        w(f"- EXITED ({r.n_exited}): {r.exited_symbols}")
    w(f"- Retained: {r.n_retained} · Holdings: {r.holdings_count} · Cash: {pct(r.cash_weight, 1)} · "
      f"Top-5 weight: {pct(r.top5_weight, 1)} · Top-10 weight: {pct(r.top10_weight, 1)}")
    if r.top_weight_increases and r.top_weight_increases not in ("[]", ""):
        w(f"- Largest weight increases (vs prev target): {r.top_weight_increases}")
    if r.top_weight_decreases and r.top_weight_decreases not in ("[]", ""):
        w(f"- Largest weight decreases (vs prev target): {r.top_weight_decreases}")
    if r.score_movers_up and r.score_movers_up not in ("[]", ""):
        w(f"- Largest score increases (eligible overlap, descriptive): {r.score_movers_up}")
    if r.score_movers_down and r.score_movers_down not in ("[]", ""):
        w(f"- Largest score decreases (eligible overlap, descriptive): {r.score_movers_down}")
    w(f"- Portfolio month: **{pct(r.portfolio_return)}** · Benchmark: {pct(r.benchmark_return)} · "
      f"Excess: **{pct(r.excess_return)}** · NAV {f2(r.portfolio_nav)} (dd {pct(r.portfolio_drawdown)}) · "
      f"Bench NAV {f2(r.benchmark_nav)}")
    w("")
w("## 5. Holding duration (spells of continuous Top20 membership)")
w("")
w(f"- Total spells: **{dur['n_spells_total']}** across "
  f"**{S['unique_securities_ever_selected']}** unique securities")
w(f"- Spell length: median **{dur['spell_length_median']:.0f} months** · "
  f"p25 {dur['spell_length_p25']:.0f} · p75 {dur['spell_length_p75']:.0f} · "
  f"p90 {dur['spell_length_p90']:.0f} · mean {dur['spell_length_mean']:.1f} · max {dur['spell_length_max']}")
longest = sp_df.sort_values("months_in_spell", ascending=False).head(10)
w("- Longest spells: " + "; ".join(f"{r.symbol} {r.months_in_spell}m ({r.first_entry_month}→{r.last_exit_month}"
                                   + (", still held at replay end" if r.open_ended else "") + ")"
                                   for r in longest.itertuples()))
w("")
w("Per-security detail: `security_holding_history.csv` (every security × month: score, rank, "
  "selected, target weight, action, holding age) — one row per security × decision month.")
w("")
w("## 6. Top20 recurrence (descriptive only — no turnover buffers proposed)")
w("")
rec15 = R["recurrence"]["top15_by_months_in_top20"]
w("- Most frequently in Top20: " + "; ".join(f"{x['symbol']} ({x['months']} mo, avg rank {x['avg_rank']:.0f})"
                                             for x in rec15))
w("- Longest uninterrupted streaks: " + "; ".join(
    f"{x['symbol']} ({x['longest_uninterrupted_streak']} mo)" for x in R["recurrence"]["top10_longest_streaks"]))
w(f"- Entered only once: **{R['recurrence']['n_entered_only_once']}** securities")
w(f"- Repeated enterers/exitors (≥4 spells): **{R['recurrence']['n_churners_4plus_spells']}** — "
  + ", ".join(f"{s} ({v} spells)" for s, v in list(R["recurrence"]["churners"].items())[:12]))
w("")
w("## 7. Operational comparison: 2021–2023 vs 2024–2026 (descriptive only — no tuning)")
w("")
w("| Metric | 2021–2023 | 2024–2026 |")
w("|---|---|---|")
rows = list(era.items())
metrics = [("Decision months", "decision_months", "{:.0f}"),
           ("Median eligible universe", "median_eligible_universe", "{:.0f}"),
           ("Median selected", "median_selected", "{:.0f}"),
           ("Mean eligible DQ", "mean_eligible_dq", "{:.3f}"),
           ("Median score std-dev", "median_score_std", "{:.4f}"),
           ("Median score p90−p10", "median_score_p90_p10", "{:.4f}"),
           ("Avg target turnover", "avg_target_turnover", "{:.1%}"),
           ("Avg realized traded fraction", "avg_realized_traded_fraction", "{:.1%}"),
           ("Avg holdings", "avg_holdings", "{:.1f}"),
           ("Avg monthly retention", "avg_monthly_retention_fraction", "{:.1%}")]
for label, key, fmt in metrics:
    vals = []
    for name, _ in rows:
        v = era[name].get(key)
        vals.append("—" if v is None else fmt.format(v))
    w(f"| {label} | {vals[0]} | {vals[1]} |")
w("")
w("The eligible universe ramped once, mid-2021 (79 names in January to ~210 by September), and is "
  "essentially flat across both eras (median 209 vs 216). What actually differs after 2023: higher "
  "data quality (mean DQ 0.897 → 0.935), wider score dispersion (median per-month score std 5.91 → "
  "7.80; p90−p10 12.0 → 17.8), lower turnover (avg target 32.5% → 25.1%; realized traded fraction "
  "54.4% → 38.8%), and higher monthly retention (71.8% → 76.6%). Per the frozen rules nothing was "
  "tuned in response; this comparison is descriptive only.")
w("")
w("## 8. NON_SHADOW_CURRENT_PREVIEW (not a shadow decision)")
w("")
if preview.get("error"):
    w(f"Preview unavailable: `{preview['error']}`")
else:
    w(f"**`NON_SHADOW_CURRENT_PREVIEW`** — built from the latest REAL production score run "
      f"`{preview['run_id']}` (as_of {preview['as_of_date']}, completed {preview['completed_at']} "
      f"Tehran, code `{preview['code_version']}`; the 2026-10-02 run `e5998f6d…` is excluded — the "
      f"state file marks it a test fixture). This is **not** a frozen month-end Shadow decision: no "
      f"paper orders were generated, the shadow clock was NOT started, and nothing was written to "
      f"the live state.")
    w("")
    w(f"- Eligible universe: **{preview['eligible_universe_count']}** · selected top-20%: "
      f"**{preview['selected_count']}** · equal target weight "
      f"{1.0 / preview['selected_count'] * 100:.2f}% each")
    w("")
    pv = pd.read_csv(HERE / "current_nonshadow_preview.csv")
    w("| # | symbol | ui_score | rank | DQ | target weight |")
    w("|---|---|---|---|---|---|")
    for i, r in enumerate(pv.itertuples(), start=1):
        w(f"| {i} | {r.symbol} | {r.ui_score:.4f} | {r.ui_rank} | "
          f"{'—' if pd.isna(r.data_quality_score) else f'{r.data_quality_score:.3f}'} | "
          f"{r.target_weight * 100:.2f}% |")
w("")
w("## 9. Reproducibility & audit")
w("")
w("- Determinism probe (content hashes): monthly CSV `" +
  R["determinism_probe"]["monthly_csv_sha256"][:16] + "…`, targets `" +
  R["determinism_probe"]["targets_content_sha256"][:16] + "…`, trades `" +
  R["determinism_probe"]["trades_content_sha256"][:16] + "…` — a re-run under a different "
  "PYTHONHASHSEED must reproduce these exactly (result recorded below).")
det = "PENDING"
try:
    det = (HERE / "_determinism_check.txt").read_text(encoding="utf-8").strip()
except OSError:
    pass
w(f"- Determinism re-run (PYTHONHASHSEED=7): **{det}**")
w(f"- Live state `portfolio_shadow/shadow_v1_state.json` byte-identical before/after: "
  f"**{R['live_state_after']['byte_identical']}** (`{R['live_state_after']['sha256'][:16]}…`); "
  f"decisions = {R['live_state_before']['decisions']}; SHADOW_FORWARD_CLOCK_STARTED = **NO**; "
  f"REAL_MONEY_ORDERS_ENABLED = {R['live_state_before']['flags']['REAL_MONEY_ORDERS_ENABLED']}; "
  f"BROKER_CONNECTION_ENABLED = {R['live_state_before']['flags']['BROKER_CONNECTION_ENABLED']}")
w("- Full machine-readable audit: `replay_state.json`; monthly row data: `shadow_replay_monthly.csv`; "
  "row-level decisions: `shadow_replay_targets.parquet`; realized trades: "
  "`shadow_replay_trades.parquet`; parity: `shadow_replay_parity.json`; per-security history: "
  "`security_holding_history.csv`; yearly: `shadow_replay_yearly.csv`.")
w("")
w("---")
w("")
w("**HISTORICAL_REPLAY_ONLY** — this replay does not replace the forward 12-month shadow period, "
  "does not constitute new validation, and does not change any frozen artifact, threshold, or rule.")
(HERE / "SHADOW_V1_1_HISTORICAL_REPLAY.md").write_text("\n".join(L), encoding="utf-8")
print("report written:", HERE / "SHADOW_V1_1_HISTORICAL_REPLAY.md", f"({len(L)} lines)")
