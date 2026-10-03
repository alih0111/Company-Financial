# SCORE PORTFOLIO V1 — PREREGISTRATION (pre-outcome freeze; execution NOT authorized)

Frozen: 2026-10-03, BEFORE any portfolio return, CAGR, drawdown, or excess-return
computation. `PORTFOLIO_V1_EXECUTED = NO`. After execution this document may not be
edited; corrections require a new version.

## 1. Score source (frozen)

`ui_score_research/ui_score_historical_pit_v2.parquet`
SHA-256 `543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a`
(JSONL source `ui_score_historical_pit_v2/ui_score_historical_pit_v2.jsonl`, same rows).
Score formula: the existing frozen production score **`canonical-v1-dev`**, evaluated on
the PIT-correct reconstruction (visibility-gated inputs; cutoff = 23:59:59 UTC on the
signal date). NO changes to component weights, category weights, DQ, penalties, caps,
missing-data behavior, or ranking logic. **Dead weights and weak/negative components
(Liquidity, PS, PB, NetMargin, Leverage, CurrentRatio) are deliberately KEPT** — this
experiment establishes the clean baseline of the EXISTING score. No Score V2 exists or is
used. The Fundamental Event signal, momentum, pullback, and volatility timing are NOT
used.

## 2. Research question

If capital had been mechanically allocated each month to the highest-ranked companies
under the PIT-correct production UI score, would the resulting portfolio have produced
useful risk-adjusted performance relative to the same investable covered universe?
Mechanical portfolio-allocation experiment — NOT individual BUY/SELL prediction.

## 3. Portfolios (frozen)

- **PRIMARY `score-portfolio-v1-top20`**: at each monthly score date, rank all eligible
  scored securities; select TOP 20% by score rank; equal weight among selected names
  BEFORE failed executions. No optimization, no volatility/market-cap weighting, no
  sector rules, no momentum overlay, no event timing, no stops, no discretionary rules.
- **SECONDARY `score-portfolio-v1-top10` (diagnostic only)**: TOP 10% by score rank, equal
  weight. Top10 cannot replace a failed Top20 primary; if it looks better it is recorded
  and any primary change requires a NEW preregistration.

Selection arithmetic: `n = max(1, floor(pct × N_eligible))`; ties broken deterministically
by `(ui_score DESC, symbol ASC)`. Rank used directly (higher UI rank = better score);
legacy Q labels are not relied on ("top 20%" = highest-score quintile, descriptive only).

## 4. Schedule, execution, tradability, cash (frozen)

- Rebalance MONTHLY on each frozen score date (63 dates, 2021-01-31 … 2026-06-30). No
  intra-month rebalance, no event-driven rebalance.
- `EXECUTION_DATE` = first canonical trading date strictly AFTER the score date / its
  proven `knowledge_cutoff` (EOD score date UTC). Never same-day close; execution dates
  are never moved.
- Execution price: canonical `pClosing` on EXECUTION_DATE (stored consistently; no
  intraday VWAP is assumed). Same convention for entries, exits, rebalances, benchmark.
- **Identity key = SYMBOL** (the score panel's is-primary `security_id` does not match
  the daily panel's research-symbol security mapping for the same symbol; every return
  pipeline in this project is symbol-keyed via `raw_{symbol}_{ins_code}` caches).
- **Tradability**: a selected security is executable on EXECUTION_DATE iff the canonical
  daily panel has an observation AND `security_traded == True` (zero-trade / unknown =
  NOT executable). If selected but not executable: NO substitute, NO assumed execution —
  that target weight remains **CASH** until the next rebalance (prevents look-ahead
  replacement selection). If the portfolio already holds a temporarily non-tradable
  security: carry at the canonical carried-valuation convention but do not pretend it
  could be sold.
- **Cash**: allowed; returns 0% (no synthetic risk-free rate). Causes: unavailable
  selected name, failed execution, insufficient valid names. Average cash % is reported.

## 5. Corporate actions & return semantics (frozen)

The canonical adjusted chain (pClosing × CONFIRMED `tsetmc_gap_rule_v1` factors) is used
as-is; NO second adjustment system. **PORTFOLIO_RETURN_SEMANTICS =
PRICE_PLUS_MECHANICAL_ADJUSTMENTS**: the chain captures capital increases (384),
rights issues (480), reverse splits (30), and heuristic gap corrections (6,119), and does
NOT capture cash dividends. All cumulative/annualized figures are therefore **price-plus-
mechanical-adjustment returns; the term "total shareholder return" is NOT permitted** in
any report of this experiment.

## 6. Transaction costs & turnover (frozen)

Fixed scenarios on absolute one-way traded notional (buys and sells): GROSS 0 bps,
LOW 25 bps, **BASE 50 bps (PRIMARY reporting convention)**, HIGH 100 bps. No historical
fee schedule is assumed; no optimization of costs. Turnover per rebalance =
`0.5 × Σ|target_weight_i − pretrade_weight_i|` with cash included consistently; also
reported: buys, sells, names entered/exited, median holding period. No
turnover-minimizing buffers.

## 7. Benchmark (frozen)

Equal-weight portfolio of ALL securities eligible in the score cross-section on the same
monthly score date, with identical knowledge date, execution date, execution price,
tradability treatment, cash treatment, return semantics, and cost scenarios. No external
index as primary benchmark (canonical historical index series unavailable over the full
sample); an external index may appear as descriptive-only for subsets.

## 8. Sample period & reporting (frozen)

ALL 63 available score dates — no preferred start year, no dropping weak years. Calendar-
year breakdowns for 2021–2025 and 2026 (descriptive/incomplete) plus a DATA-COVERAGE
diagnostic by year. Metrics (Top20 and benchmark; Top10 diagnostic): cumulative
price-plus-adjustment return, annualized return, annualized volatility, maximum drawdown,
Sharpe-like ratio with 0% cash rate, monthly positive-return fraction, monthly excess-
fraction vs benchmark, best/worst month, average holdings, average cash %, average and
median monthly turnover, total traded notional / average capital. Excess performance:
annualized return difference, cumulative wealth difference, monthly excess mean/median,
positive excess-month fraction, year-by-year excess, maximum relative drawdown. No
cherry-picked subperiods.

## 9. Dependence-aware uncertainty (frozen)

Monthly portfolio observations; **seed 20261003, B = 2000, 6-month moving blocks**
(date-level resampling); bootstrap CIs for mean monthly excess return and its annualized
equivalent; if technically valid, CAGR difference via time-block paths. 95% intervals;
block size never altered after results.

## 10. Research gates PV1–PV8 (frozen; exploratory shadow eligibility only; no near-miss override)

- **PV1 PIT/execution integrity**: all construction, execution-date, tradability, and
  return-semantic tests PASS.
- **PV2 net excess return** (50 bps one-way): Top20 annualized − benchmark annualized
  ≥ **+2.0pp**.
- **PV3 dependence robustness**: 95% block-bootstrap lower bound for mean monthly excess
  return > 0.
- **PV4 year stability**: positive net excess return in ≥ **3 of 5** full years 2021–2025
  (2026 descriptive).
- **PV5 drawdown**: Top20 max drawdown ≤ benchmark max drawdown + 5pp.
- **PV6 turnover**: average monthly turnover ≤ **30%**.
- **PV7 breadth**: median holdings ≥ **20**.
- **PV8 executability**: average involuntary cash ≤ **10%**.
Gates are never softened after execution.

## 11. Survivorship caveat (required language)

"Results apply to the reconstructed available historical product universe and retain
unresolved full-market survivorship/universe uncertainty." No missing issuers are
reconstructed in this experiment.

## 12. Pre-outcome feasibility (measured 2026-10-03; no returns computed)

From `feasibility_score_portfolio_v1.py` → `score_portfolio_v1_feasibility.json` +
`score_portfolio_v1_feasibility_by_date.csv`:

- 63 monthly rebalance dates (2021-01-31 … 2026-06-30); all execution dates resolvable.
- Eligible names per date: median **212** (min 79, max 227).
- Top20 holdings: median **42** (min 15, max 45) → PV7 pre-check PASS. Top10 median 21
  (min 7).
- Executability on execution days: **0 expected failed executions across all 63 dates**
  for both Top20 and Top10 (every selected name has a `security_traded == True`
  observation on its execution date) → expected involuntary cash **0%** (PV8 pre-check
  PASS).
- Score coverage by year (median eligible): 2021 124 · 2022 211 · 2023 216 · 2024 215 ·
  2025 221 · 2026 209 — the fundamental-visibility ramp documented in the score audit is
  inherited by this experiment and will be reported as the DATA-COVERAGE diagnostic.
- **PORTFOLIO_V1_FEASIBLE = YES.**

## 13. Boundary

Fundamental Event V1 remains paused and is NOT combined with this experiment. Score V2
does not exist. The production UI score, its weights, DQ, and dead weights are untouched.
No BUY/SELL orders; research labels never reach users; `SIGNAL_ENGINE_STARTED = NO`.
