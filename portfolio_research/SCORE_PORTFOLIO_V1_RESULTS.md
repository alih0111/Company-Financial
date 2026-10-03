# SCORE PORTFOLIO V1 — EXECUTION RESULTS (exactly once, per frozen preregistration)

Executed 2026-10-03. Binding spec:
`SCORE_PORTFOLIO_V1_PREREGISTRATION.md` SHA-256
`10e6aa0e477b89eb73a5deacb72a4e337467fcfd2a06fd736a78e5954ecaf17c` (verified byte-for-byte
before execution). Score input `ui_score_historical_pit_v2.parquet` SHA-256
`543dfbf7…` verified. Identity map 235/235 UNIQUE verified. **No spec element was
modified.**

## VERDICT

| gate | result | value (BASE 50 bps, Top20) |
|---|---|---|
| PV1 PIT/execution integrity | **PASS** | all construction checks PASS (see below) |
| PV2 net excess return | **PASS** | annualized Top20 43.03% − benchmark 35.53% = **+7.50pp** ≥ +2.0pp |
| PV3 dependence robustness | **FAIL** | mean monthly excess +0.4617%; 6-month-block bootstrap 95% CI **[−0.343%, +1.208%]** — lower bound < 0 |
| PV4 year stability | **PASS** | positive net excess in **3 of 5** full years (2021 +4.7pp, 2024 +11.4pp, 2025 +25.7pp; 2022 −21.3pp, 2023 −0.6pp) |
| PV5 drawdown | **PASS** | Top20 MDD −25.50% vs benchmark −29.42% (better by 3.9pp) |
| PV6 turnover | **PASS** | average monthly turnover **29.84%** ≤ 30% |
| PV7 breadth | **PASS** | median holdings **44** ≥ 20 |
| PV8 executability | **PASS** | average involuntary cash **≈0%** ≤ 10% |
| **PRIMARY GATE** | **FAIL** | PV3 failed — no near-miss override applied |

**SCORE_PORTFOLIO_V1_SHADOW_ELIGIBLE = NO.** The strategy is not modified, not re-tuned,
and no variant is created. The result stands as the preregistered exploratory answer:
positive point-estimate excess (+7.5pp/yr at 50 bps) that is **not robust** at the
preregistered dependence-aware standard — 62 monthly observations with 6-month blocks
leave the mean excess statistically indistinguishable from zero.

## PRIMARY Top20 @ 50 bps (PRICE_PLUS_MECHANICAL_ADJUSTMENTS — not TSR)

- cumulative return **+535%** (terminal wealth multiple **6.35×**) over 62 monthly periods
  (2021-02-01 → 2026-07-01 execution dates)
- annualized return **43.03%** · annualized volatility **35.48%** · Sharpe-like (0% rf)
  **1.185**
- maximum drawdown **−25.50%** (monthly observation granularity)
- positive months **54.8%** · best month +36.5% · worst month −13.9%
- average/median holdings **44 / 44** · average cash **≈0%** (0 failed executions, 0
  carried valuations across all 63 rebalances)
- average monthly turnover **29.84%**, median 27.85% (see monthly CSV), p90 45.79% · total
  traded notional / average capital **43.7×**

## Benchmark (equal-weight ALL eligible, identical rules) @ 50 bps

annualized **35.53%** · cumulative **+381%** (4.81×) · MDD **−29.42%** · vol 35.11% ·
Sharpe 1.040 · median holdings 224 · turnover 16.72%.

## Cost sensitivity (annualized return / cumulative)

| scenario | Top20 | Benchmark |
|---|---|---|
| GROSS 0 bps | 43.07% / 5.36× | 35.43% / 3.79× |
| LOW 25 bps | 43.05% / 5.36× | 35.49% / 3.80× |
| **BASE 50 bps** | **43.03% / 5.35×** | **35.53% / 3.81×** |
| HIGH 100 bps | 43.00% / 5.35× | 35.63% / 3.83× |

(Cost drag is second-order here because the BASE-case annualized cost ≈ turnover 29.8% ×
2×50 bps ≈ 3.0pp/yr, applied identically to a higher-turnover portfolio and benchmark.)

## Excess performance (Top20 − benchmark, BASE)

annualized difference **+7.50pp** · terminal wealth difference **+1.54×** (6.35× vs
4.81×) · mean monthly excess **+0.4617%** · median **+0.3529%** · positive excess-month
fraction **59.7%** · yearly excess: 2021 **+4.70pp** · 2022 **−21.33pp** · 2023 **−0.61pp**
· 2024 **+11.41pp** · 2025 **+25.57pp** · 2026 (descriptive) **+15.09pp**.

## Bootstrap (seed 20261003, B=2000, 6-month moving blocks = 7 periods)

- mean monthly excess +0.4617% · 95% CI **[−0.3431%, +1.2079%]**
- annualized equivalent +5.54% · 95% CI **[−4.12%, +14.49%]**
- CAGR difference 95% CI **[−4.71%, +19.44%]**

## Top10 — DIAGNOSTIC ONLY (BASE 50 bps)

annualized **48.15%** · cumulative 6.62× · MDD −26.14% · vol 37.52% · Sharpe 1.235 ·
median holdings 21 · turnover 32.2%. Stronger point-estimate than Top20 but **DIAGNOSTIC
ONLY** — it does not change the primary gate and cannot rescue the failed PV3; any
primary switch requires a new preregistration.

## PV1 integrity record

- preregistration + score hashes verified byte-for-byte; identity map 235/235 UNIQUE.
- Execution dates: 63/63 = first canonical trading date strictly after the score date;
  no same-day execution; execution priced at canonical pClosing on the CONFIRMED adjusted
  chain.
- Tradability: daily-panel row AND `security_traded==True`; 0 failed targets, 0 carried
  valuations in the entire run (no substitution ever needed).
- Wealth continuity: `monthly_return = value_pre_trade(k+1) / value_post_trade(k) − 1`
  for all 62 periods; costs paid from portfolio cash only (no borrowing) — when cash+sells
  could not cover buys+costs, buys scaled proportionally and cash floored at 0.
- Return semantics: **PRICE_PLUS_MECHANICAL_ADJUSTMENTS**. The CONFIRMED gap-rule chain
  mechanically includes capital increases, rights issues, reverse splits, and
  dividend-like ex-date gap resets; cash-dividend disclosure completeness is NOT proven.
  **These figures are NOT total shareholder return.**

## Data-ramp context (task 17; no year excluded, no start date chosen)

| year | rebalances | median eligible | median DQ | fundamental input coverage | Top20 | Benchmark |
|---|---|---|---|---|---|---|
| 2021 | 11 | 92 | 0.80 | **0%** | −7.5% | −12.2% |
| 2022 | 12 | 210 | 1.00 | **0.04%** | +35.0% | +56.3% |
| 2023 | 12 | 214 | 1.00 | 49% | +64.8% | +65.4% |
| 2024 | 12 | 216 | 1.00 | 62% | +28.5% | +17.1% |
| 2025 | 12 | 221 | 1.00 | 65% | +53.5% | +27.9% |
| 2026* | 4 | 214 | 1.00 | 67% | +56.5% | +41.4% |

*2026 descriptive/incomplete. The 2021–23 fundamental-visibility ramp (documented in the
score audit) is inherited here; the score was effectively price-driven early on. No
period was excluded and no start date was preferred.

## Interpretation limits

Exploratory historical result on the reconstructed available product universe — full-
market survivorship/universe uncertainty remains unresolved. Not a prediction of future
returns; no BUY/SELL; production untouched; `SIGNAL_ENGINE_STARTED = NO`;
`PORTFOLIO_PRODUCTION_READY = NO`; `REAL_MONEY_AUTOMATION_READY = NO`.

## Artifacts

`score_portfolio_v1_results.json` · `score_portfolio_v1_monthly.csv` ·
`score_portfolio_v1_holdings.parquet` · `score_portfolio_v1_trades.parquet` ·
`score_portfolio_v1_yearly.csv` · `score_portfolio_v1_bootstrap.json` · this file.
SHA-256 of every artifact is recorded in `score_portfolio_v1_results.json → artifacts`.
