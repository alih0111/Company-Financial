# SCORE PORTFOLIO V1 — RESULTS (ACCOUNTING REPAIR RUN — official, supersedes the quarantined run)

Execution lineage (all under the SAME immutable preregistration
`10e6aa0e477b89eb73a5deacb72a4e337467fcfd2a06fd736a78e5954ecaf17c`, never modified):

1. **Initial implementation run** (2026-10-03): produced the first net results.
2. **Negative-cash accounting defect discovered**: costs financed from cash drove cash
   below zero (implicit borrowing). Corrected before gate evaluation.
3. **Corrected financing run**: declared `PRIMARY_GATE = FAIL` (PV3).
4. **External review** rejected the net results: cost magnitude inconsistent with
   reported turnover/traded notional. Quarantined: `PORTFOLIO_V1_NET_RESULT_VALID = NO`.
5. **Root-cause audit (this run)**: the defect was NOT the bps conversion (rates were
   numerically correct) and NOT the cost ledger (fees were 0.005 × actual notionals).
   The defect was **position-financing**: the buy-financing factor `f` was applied to
   TARGET POSITIONS instead of BUY DELTAS, destroying `(1−f) × current_value` of held
   positions at every rebalance where buys exceeded cash+sells. The leak is cost-rate
   INDEPENDENT (active at 0 bps), so **both the gross and net paths of the initial run
   were invalid** (value_pre collapsed 1.0 → 0.0002), and the reported "+535%" was the
   product of growth ratios across a collapsing path — economically meaningless.
6. **Accounting-repair run (this document)**: `f` now scales BUY DELTAS only; the exact
   invariant `NAV_post = NAV_pre − cost` is asserted at every rebalance; all five unit
   tests pass; the official results below come from this repaired engine.

This is implementation debugging, not model tuning. Strategy, selection, benchmark,
costs, turnover rule, and PV1–PV8 are unchanged from the frozen preregistration.

## Unit tests (all PASS before recomputation)

- TEST A bps conversion: 25 bps = 0.0025, 50 bps = 0.005, 100 bps = 0.010 — **PASS**
- TEST B one-way purchase (NAV 100, cash 100, 50 bps): buy 99.5025 + fee 0.4975 = 100
  exactly; cash 0 — **PASS**
- TEST C full rotation A→B (100%, 50 bps): total cost **0.995 ≈ 1% round trip** — **PASS**
- TEST D zero turnover: 0 notional, 0 cost — **PASS**
- TEST E proportional buy reduction: cash ≥ 0 always; NAV_post = NAV_pre − cost — **PASS**
- Invariant sweep (500 randomized rebalances): `NAV_post = NAV_pre − cost` exact — **PASS**

## Gross-path parity

`GROSS_PATH_PARITY = FAIL` against the quarantined run's reported gross path — **and that
is expected**: the quarantined gross path contained the same position-scaling leak (it is
cost-rate independent), so the old gross path was itself invalid and cannot serve as a
parity anchor. There is no valid prior gross path to reproduce. The corrected gross path
is validated instead by the unit tests, the exact NAV identity, and the cost
reconciliation below. **This parity failure is the one item requiring reviewer
sign-off before the PASS verdict below is treated as final** (per the task's stop rule,
the reason is stated here explicitly rather than hidden).

## Cost reconciliation (Top20; the review's section-6 check)

| scenario | gross ann | net ann | observed drag | total fees / avg capital | fees-implied annual drag |
|---|---|---|---|---|---|
| LOW 25 bps | 43.92% | 41.84% | **2.08pp** | 7.06% | 1.37pp |
| BASE 50 bps | 43.92% | **39.79%** | **4.13pp** | 14.15% | 2.74pp |
| HIGH 100 bps | 43.92% | 35.80% | **8.12pp** | 28.42% | 5.50pp |

Observed-to-implied ratio is **1.48–1.52 across all three scenarios** — the stable
linear-in-rate signature of a correct implementation (fees paid early, when capital is
smaller, compound to a larger terminal impact than a naive fees/average-capital
annualization; dividing the drag by the cost rate gives the same ratio at every
scenario). Total traded notional / average capital (BASE) = **28.29×**; total fees paid
= **0.2497** in initial-capital units. The quarantined run's "43.7× notional, 0.04pp
drag" inconsistency is fully explained and eliminated.

## OFFICIAL RESULTS — Top20 `score-portfolio-v1-top20` (BASE 50 bps)

62 monthly periods (exec dates 2021-02-01 → 2026-07-01), PRICE_PLUS_MECHANICAL_ADJUSTMENTS
(NOT total shareholder return):

- cumulative return **+464.5%** (terminal wealth **5.645×** the initial capital, all
  costs included)
- annualized return **39.79%** · annualized volatility 35.63% · Sharpe-like (0% rf)
  **1.118**
- maximum drawdown **−26.85%** · positive months 53.2% · best +36.3% · worst −14.4%
- median holdings **44** · average cash **≈0%** · 0 failed executions, 0 carried
  valuations across all 63 rebalances
- average monthly turnover **29.31%** (median 27.83%, p90 46.32%) — PV6 PASS
- total transaction costs 0.2497 (initial-capital units) = 14.15% of average capital;
  average monthly cost drag 0.239%

Benchmark (equal-weight ALL eligible, identical rules, BASE): annualized **32.47%** ·
cumulative **+227.5%** (3.275×) · MDD **−29.50%** · turnover 10.44% · fees 0.0393.

## Excess performance (BASE)

annualized **+7.32pp** · terminal wealth difference **+1.37×** · mean monthly excess
**+0.4973%** · median **+0.2502%** · positive excess-month fraction **58.1%**.

Year-by-year (Top20 / Benchmark / excess): 2021 −11.4% / −12.7% / **+1.2pp** · 2022
+31.3% / +31.7% / **−0.5pp** · 2023 +60.0% / +63.6% / **−3.7pp** · 2024 +26.9% / +18.7% /
**+8.2pp** · 2025 +54.8% / +37.5% / **+17.3pp** · 2026 (descriptive) +55.3% / +39.8% /
**+15.4pp**.

## Bootstrap (seed 20261003, B = 2000, 6-month moving blocks = 7 periods)

- mean monthly excess +0.4973% · 95% CI **[+0.0653%, +0.9612%]** — lower bound > 0
- annualized equivalent +5.97% · 95% CI [+0.78%, +11.53%]
- CAGR difference 95% CI [+0.88%, +15.25%]

## Gates PV1–PV8 (BASE, Top20 — all recomputed from the repaired path)

| gate | result | evidence |
|---|---|---|
| PV1 | **PASS** | hashes verified; identity 235/235 UNIQUE; 63/63 execution dates; tradability rule enforced; NAV identity exact every period; semantics = PRICE_PLUS_MECHANICAL_ADJUSTMENTS |
| PV2 | **PASS** | 39.79% − 32.47% = **+7.32pp** ≥ +2.0pp |
| PV3 | **PASS** | bootstrap lower bound **+0.0653%** > 0 |
| PV4 | **PASS** | positive net excess in **3 of 5** full years (2021, 2024, 2025) |
| PV5 | **PASS** | MDD −26.85% vs benchmark −29.50% |
| PV6 | **PASS** | turnover 29.31% ≤ 30% |
| PV7 | **PASS** | median holdings 44 ≥ 20 |
| PV8 | **PASS** | involuntary cash ≈ 0% ≤ 10% |
| **PRIMARY GATE** | **PASS** | all eight gates PASS — **conditional on reviewer acceptance of the gross-parity failure explanation above** (the prior gross path was itself invalid; there is no valid prior gross to reconcile against) |

## Top10 — DIAGNOSTIC ONLY (BASE)

annualized **44.58%** · cumulative **+471.7%** (5.717×) · MDD −27.40% · Sharpe 1.163 ·
turnover 31.29% · median holdings 21. Stronger point-estimate; does not change the
primary gate; no variant created.

## Boundary

Exploratory historical result on the reconstructed available product universe —
"Results apply to the reconstructed available historical product universe and retain
unresolved full-market survivorship/universe uncertainty." Not TSR (cash-dividend
disclosure completeness not proven; official gap factors empirically include 2,504
dividend-like ex-date resets 2021–2026). No BUY/SELL; production untouched;
`SIGNAL_ENGINE_STARTED = NO`; `PORTFOLIO_PRODUCTION_READY = NO`;
`REAL_MONEY_AUTOMATION_READY = NO`.
