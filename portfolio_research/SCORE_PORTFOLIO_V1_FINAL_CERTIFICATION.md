# SCORE PORTFOLIO V1 — FINAL CERTIFICATION (accounting / artifact certification only)

Certified 2026-10-03 against the repaired artifacts only. Binding preregistration
`10e6aa0e477b89eb73a5deacb72a4e337467fcfd2a06fd736a78e5954ecaf17c` — verified unchanged.
Score artifact `543dfbf7…` verified. Identity map 235/235 UNIQUE. **No strategy, score,
benchmark, cost, or gate was modified. This is certification, not a new execution.**

## 1. Gross path status

- `OLD_GROSS_PATH_VALID = NO` (quarantined run contained the position-financing leak;
  cost-rate independent; both its gross and net paths were invalid).
- `REPAIRED_GROSS_INTERNAL_CONSISTENCY = PASS`: the repaired 0-bps path reproduces
  **bit-identically** on re-execution (max |Δ| = 0.0 across all 63 NAV points), and the
  monthly-return/NAV identity holds to **4.44e-16** on the gross path.

## 2. Benchmark wealth reconciliation — `BENCHMARK_WEALTH_RECONCILIATION = PASS`

From `score_portfolio_v1_monthly_accounting_repaired.csv` / the repaired NAV path
(BENCH_BASE):

| quantity | value |
|---|---|
| initial capital | 1.0 |
| initial NAV after entry cost (NAV_post(0)) | 0.995025 |
| final NAV (NAV_post(62)) | **4.275451×** |
| cumulative return | **+327.55%** |
| monthly return periods | 62 |
| product(1 + monthly_return) | 4.296828 = 4.275451 / 0.995025 (path ratio, exact) |
| annualization convention | wealth^(12/62) − 1 |
| benchmark CAGR | **32.47%** ✓ consistent |

**Correction confirmed**: the previously reported "cumulative +227.5% (3.275×)" was a
prose labeling error. The artifact value 3.275451 is the **cumulative RETURN**
(+327.55%); the terminal wealth multiple is **4.2755×**. Proof: 3.275^(12/62) − 1 =
25.8% (cannot yield the reported 32.47% CAGR), while 4.2755^(12/62) − 1 = 32.47% exactly.

## 3. Top20 wealth reconciliation — `TOP20_WEALTH_RECONCILIATION = PASS`

initial capital 1.0 → NAV_post(0) 0.995025 → final NAV **5.645069×**; cumulative
**+464.51%**; product(1 + monthly) = 5.673295 = 5.645069/0.995025 (exact); CAGR
5.645069^(12/62) − 1 = **39.79%** ✓. All summary metrics in the certified JSON re-derived
from a fresh deterministic re-execution match (`metrics_match_certified_json = true` for
every series).

## 4. Excess wealth — verified from certified NAVs

terminal wealth difference = 5.645069 − 4.275451 = **+1.3696×** ✓ (matches the reported
+1.37×; recomputed from NAVs, not from a stale summary).

## 5. Return-series / NAV identity — all 9 series

`NAV_t = NAV_(t−1) × (1 + return_t)` verified for TOP20 GROSS/LOW/BASE/HIGH, BENCH
GROSS/LOW/BASE/HIGH, TOP10 BASE: **max absolute reconciliation error = 8.88e-16**
(floating-point epsilon). External cash flows: zero (self-financing). No unexplained
wealth discontinuity in any series.

## 6. Trade / cost ledger reconciliation — `TRADE_COST_LEDGER_RECONCILIATION = PASS`

For every scenario: Σ trade-level costs == Σ monthly transaction costs (**diff = 0.0**)
and every trade satisfies `cost = |executed_notional| × rate` (max per-trade formula
error = 0.0).

Top20 BASE: buys **25.3466** · sells **24.5963** · total absolute traded notional
**49.9429** (initial-capital units; = 28.29× average capital) · total fees **0.249714**
(= 14.15% of average capital).
Benchmark BASE: buys **4.4127** · sells **3.4520** · total notional **7.8647** · total
fees **0.039324**.
Cost-rate verification: 25 bps = 0.0025, 50 bps = 0.0050, 100 bps = 0.0100 (TEST A).

## 7. Self-financing invariants — `SELF_FINANCING_INVARIANTS = PASS`

Independent ledger replay (reconstructing positions from the executed-trade ledger and
the price series, without the engine's internal state): max |replay − engine| NAV error
**≤ 2.19e-9** across all 9 series (one floating-point floor event; all others ≤ 3.6e-15).
Negative cash rows **0** · NAV identity failures **0** · position reconciliation failures
**0** · external capital injections **0**.

## 8. Turnover reconciliation (frozen formula, independently recomputed)

Top20 BASE **29.31%** ✓ · Benchmark BASE **10.44%** ✓ · Top10 BASE **31.29%** ✓ —
matching the reported values. Relationship to traded notional (BASE, monthly averages):
turnover 29.31% vs buy fraction 24.54% + sell fraction 23.19% = traded-notional fraction
47.73% — the frozen formula counts all target-vs-pretrade weight deltas (including
non-executed carries); traded notional counts only executed notionals. Related, not
interchangeable, as preregistered.

## 9. Yearly returns (recomputed from monthly NAV observations, end-date attribution)

| year | Top20 | Benchmark | excess |
|---|---|---|---|
| 2021 | −10.64% | −12.45% | **+1.81pp** |
| 2022 | +15.79% | +15.24% | **+0.54pp** |
| 2023 | +70.62% | +78.31% | **−7.69pp** |
| 2024 | +19.10% | +9.95% | **+9.15pp** |
| 2025 | +45.20% | +33.06% | **+12.15pp** |
| 2026 (descr.) | +84.91% | +62.44% | **+22.47pp** |

PV4 evaluated on 2021–2025 only: **4 of 5 positive** → PASS. (Note: the repaired MD's
yearly table used start-date attribution of period returns; this certification uses the
standard end-date attribution of the same NAV path — both derive from identical
underlying data; the certification values are the certified ones.)

## 10. Bootstrap input certification — `BOOTSTRAP_INPUT_CERTIFIED = PASS`

- 62 monthly excess observations (TOP20 BASE − BENCH BASE, same periods).
- Excess-vector SHA-256 (float64 bytes): `c0a0e62b8c8c09f186242bf456095afec938fb2d3fa6b71474d97dce1422dcbb`.
- seed 20261003 · B = 2000 · 6-month moving blocks (block = 7 periods), circular,
  date-level resampling — unchanged.
- Reproduction from the certified vector reproduces the certified CI exactly:
  mean monthly excess 95% CI **[+0.0653%, +0.9612%]**. No stale series from the
  quarantined run entered the bootstrap.

## 11. PV gate certification (recomputed; thresholds unchanged)

PV1 **PASS** · PV2 **PASS** (+7.32pp ≥ +2.0) · PV3 **PASS** (lower bound +0.0653% > 0) ·
PV4 **PASS** (4 of 5) · PV5 **PASS** (−26.85% vs −29.50%) · PV6 **PASS** (29.31% ≤ 30%) ·
PV7 **PASS** (44 ≥ 20) · PV8 **PASS** (cash ≈ 0% ≤ 10%).

**SCORE_PORTFOLIO_V1_PRIMARY_GATE = PASS · SCORE_PORTFOLIO_V1_SHADOW_ELIGIBLE = YES** —
this is certification of the repaired implementation of the original frozen experiment,
not a new execution.

## 12. Interpretation boundary (unchanged, not weakened)

`PORTFOLIO_PRODUCTION_READY = NO` · `REAL_MONEY_AUTOMATION_READY = NO`. Reasons:
exploratory historical sample; unresolved full-market survivorship/universe uncertainty;
historical data-coverage ramp (fundamental visibility 0% in 2021 → 67% in 2026); only ~62
monthly out-of-time observations; dividend completeness not proven (PRICE_PLUS_
MECHANICAL_ADJUSTMENTS semantics; official gap factors empirically include 2,504
dividend-like ex-date resets 2021–2026 but disclosure completeness is unproven); no
prospective shadow/paper-execution period yet.
