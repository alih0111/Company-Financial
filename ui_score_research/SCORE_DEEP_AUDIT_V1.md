# SCORE DEEP AUDIT V1 — `canonical-v1-dev` on the PIT-correct historical panel (DIAGNOSTIC ONLY)

Executed 2026-10-03. Input: `ui_score_historical_pit_v2.parquet` (+ its JSONL source,
12,604 rows / 63 frozen signal dates / 235 symbols). Production score UNCHANGED; no
weights optimized; no Score V2 built; no portfolio backtest; Fundamental Event V1 NOT
executed. Returns are used ONLY to attribute the already-frozen score and its existing
components/categories.

## 1. Input parity — PASS

Reproduced exactly on the frozen panel: **IC21 +0.0574 · IC63 +0.0853 · IC126 +0.1096 ·
IC252 +0.1031** (positive-date fractions 0.73 / 0.79 / 0.90 / 0.82; n_dates 63/62/61/55;
IC63 bootstrap 95% CI [+0.047, +0.125], seed 20261003, B=2000, block=4 dates ≈ 3 months;
63d Q1–Q5 means 0.0874 / 0.0969 / 0.0884 / 0.1005 / 0.1053; Q5−Q1 +1.78pp).

## 2. The exact production formula (verified against compute_metrics.py:719–790)

`quant_score = DQ × (G + P + V + M)`, raw maximum 89.

- **Ranks**: midrank percentile of the capped raw metric among PRESENT values,
  `(2·less + ties − 1) / (2·(n−1))`; missing → neutral placeholder (0.3 default,
  0.5 InterestCoverage/EarningsQuality, 0.0 PE/PS/PB/Liquidity); PE>60/≤0 (PS>100, PB>30)
  → rank 0.0. This IS the actual implementation — ranks are weight-multiplied directly
  (no separate percentile→points rescaling).
- **GROWTH (36)** = 10·SalesGrowth12M + 6·SalesGrowth3M + 5·RevenueGrowth
  + 5·OpProfitGrowth + 10·NetProfitGrowth(fallback EPS growth) − 6·[sales12M<−20]
  − 5·[opG<−25], floor 0.
- **PROFITABILITY (26)** = 4·OpMargin + 4·NetMargin + 6·ROE + 3·MarginTrend
  + 3·InterestCoverage + 2·CashConversion + 4·EarningsQuality − 10·[netTTM<0]
  − 4·[IntCov<1.5] − 3·[trend<−2] − nonlinear EarningsQuality penalty (0 at ≤20,
  linear to 8 at ≥100), floor 0.
- **VALUATION (16)** = 11·PE + 3·PS + 2·PB − 8·[PE missing/≤0/>60], floor 0.
- **MARKET & RISK (11)** = 3·Liquidity + 2·Leverage + 2·CurrentRatio + 1·Stability
  + 2·LowVolatility + 1·Momentum (no penalty).
- **DQ** (data_quality.py) = 0.30·has_financials + 0.20·has_monthly + 0.20·has_price
  + 0.15·fresh_financials + 0.15·fresh_market (range observed [0.55, 1.0]).
- Caps before ranking: sales ±150/±150, revenue ±200, opG ±250, NP/EPS ±300,
  margins ±80/±60, trend ±25, IntCov ≤20 (≤0 → invalid), EQ ≤150, PE (0,60], PS (0,100],
  PB (0,30], momentum [−50,40], leverage ≤50, current ratio ≤15, cash conv [−2,5].

This matches the structure in the task statement with the additions above (explicit
penalties, neutral placeholders, PE/PS/PB invalid→0-rank rules, EPS-growth fallback for
net-profit growth).

## 3. Component coverage on the PIT-correct panel (task 4)

The visibility gating has a first-order effect: statement-derived components collapse to
~4% coverage (median cross-section n≈9) because a company's statements are visible only
from their proven publication time, and TTM/fiscal-anchor chains need visible codal
evidence. Market-derived components are always present.

| family | components | coverage | median n/date |
|---|---|---|---|
| monthly-sales driven | SalesGrowth12M 40%, SalesGrowth3M 61%, Stability 54% | ramp: ~0% in 2021–22 → ~50–65% 2023+ | 123–139 |
| profit growth | NetProfitGrowth 73% (7% in 2021 → 95% 2023+), OpProfitGrowth 10% | ramp | 15–198 |
| statement-derived (margins, ROE, IntCov, CashConv, EQ, Leverage, CurrentRatio) | ~4% each | flat, tiny | 9 |
| revenue growth 5%, PE 9%, PS 2%, PB 2% | — | — | 5–18 |
| **Liquidity** | **0%** — `price_observations.trade_value_rial` is 96% NULL in the canonical DB (also 0% in the old leaky panel) | dead weight in BOTH v1 and v2 | 0 |
| price always-on | Volatility 100%, Momentum 99–100% | no ramp | 211–212 |

Major ramps: SalesGrowth3M, NetProfitGrowth (2021–22 ≈ 0 → 2023+ material). Dominated by
missingness: all statement-derived families + PS/PB + Liquidity.

## 4. Component information (task 7; IC63 / IC126 of the stored ranks)

Strongest: **SalesGrowthRank +0.109/+0.121** (pos 0.897) · SalesGrowth3M +0.080/+0.085 ·
LowVolatility +0.064/+0.082 · CashConversion +0.057/+0.061 · Stability +0.035/+0.079 ·
NetProfitGrowth +0.041/+0.038 · Momentum +0.039/+0.067.
≈ zero: RevenueGrowth +0.019/+0.012 · OpProfitGrowth +0.019/+0.032 · ROE +0.027/+0.024 ·
MarginTrend +0.009/+0.005 · InterestCoverage +0.003/+0.000 · EarningsQuality +0.012/+0.009 ·
PE +0.007/+0.023.
**Negative on BOTH horizons: NetMargin −0.004/−0.016 · PS −0.010/−0.010 ·
PB −0.011/−0.011 · Leverage −0.011/−0.007 · CurrentRatio −0.025/−0.033.** Magnitudes are
small (≤0.033) and the yearly signs flip (e.g., PS/PB −0.104 in 2021, +0.075 in 2025) —
they are non-contributing at these coverages, not strongly harmful.

## 5. Redundancy (task 5)

Pairs with |median cross-date ρ| ≥ 0.70: **PE↔PS 0.774 · PE↔PB 0.758 ·
Leverage↔CurrentRatio 0.820**. Category-level: Valuation↔Profitability 0.537, Growth↔Profitability
0.437 (details in `score_redundancy_matrix.csv`). The valuation triple is one economic
quantity counted three times; the leverage pair is one balance-sheet quantity counted twice.

## 6. Category attribution (task 6; no ranking of winners implied)

| category | IC21 | IC63 [boot CI] | IC126 | IC252 |
|---|---|---|---|---|
| Growth | +0.0556 | **+0.0781** [0.041, 0.119] | +0.0836 | +0.0588 |
| Profitability | +0.0197 | +0.0146 [−0.011, 0.039] | +0.0052 | −0.0037 |
| Valuation | +0.0005 | +0.0058 [−0.017, 0.027] | +0.0220 | +0.0315 |
| MarketRisk | +0.0366 | **+0.0687** [0.002, 0.134] | +0.1053 | +0.1248 |
| FULL | +0.0574 | +0.0853 [0.047, 0.125] | +0.1096 | +0.1031 |

Growth and MarketRisk carry provable ranking information; Profitability and Valuation CIs
cross zero on this panel (their raw-information coverage is ~4%). Note: per-category
Q5−Q1 spreads are negative (−0.7 to −7.2pp) while the FULL spread is +1.78pp — with ~96%
neutral-filled mass, category quintile spreads are dominated by ties; treat ICs as the
reliable attribution statistic here.

## 7. Leave-one-category-out (task 8; points NOT reallocated, DQ preserved)

| excluded | ΔIC63 | Δpos-frac63 | Δspread63 |
|---|---|---|---|
| Growth | −0.0109 | −0.030 | −1.07pp |
| Profitability | +0.0001 | −0.004 | +0.22pp |
| Valuation | −0.0030 | −0.016 | −0.83pp |
| MarketRisk | +0.0003 | −0.022 | −2.25pp |

Sensitivity only. Growth is the largest positive contributor; removing Profitability or
MarketRisk changes IC63 ≈ 0 but hurts/changes spreads; nothing is so harmful that its
removal lifts the score materially (no ablation would be promoted automatically).

## 8. DataQuality diagnostic (task 9; identical rows)

pre-DQ IC63 0.0823 → post-DQ **0.0853**; spread63 1.60pp → **1.78pp**; pre/post rank
correlation ~0.999 per date; 0 rows move ≥10 percentile. **DQ helps slightly on this
panel** (it is a coverage multiplier, not a signal). Ret63 by DQ bucket: 1.00 → 0.102,
0.85–1.0 → 0.077, 0.70–0.85 → 0.061, <0.70 → 0.039 (descriptive; higher-DQ rows earned
more, consistent with the multiplier's purpose).

## 9. Effective vs nominal weights (task 10)

Accounting/fundamental components hold **93.9%** of effective contribution mass vs 6.1%
for the price-derived six. Nominal-vs-effective mismatches: **Liquidity 3.4% nominal →
0% effective** (dead weight, data NULL in source); PS/PB effective shares collapse toward
0 via neutral fills at 2% coverage; SalesGrowth's effective share is roughly nominal.
Full table in `score_weight_concentration.csv`.

## 10. Temporal stability (task 11)

FULL IC63 by year: **2021 +0.025 · 2022 +0.024 · 2023 +0.042 · 2024 +0.164 · 2025 +0.151 ·
2026 +0.214** (spreads −6.3 / −5.3 / +1.3 / +8.4 / +6.4 / +27.8pp). Leave-one-year-out
pooled IC63: excluding 2021/2022/2023 → 0.096–0.100; excluding 2024/2025 → 0.066–0.070.
Interpretation (factual): 2021–22 snapshots had ~0% visibility for the fundamental drivers
(recovered publications start 1400/01/01) — the score there was mostly price components +
neutral fills; the ranking power concentrates where fundamental coverage exists. This is
a data-ramp property, not evidence of regime decay, and it is NOT used to exclude years.

## 11. Monotonicity (task 12)

63d: Q means 0.0874→0.0969→0.0884→0.1005→0.1053 (Q2>Q3 inversion; Q5−Q1 excess +1.78pp);
strictly monotonic on only 9.7% of dates. 126d: 0.1603→0.1777→0.1809→0.2019→0.2201
(2 minor inversions; 14.8% strict). 252d: 0.2816→0.3095→0.3227→0.3189→0.3401. Mean
ordering is upward at all horizons; strict per-date monotonicity is rare (expected with
~200-name cross-sections) — reported, not hidden.

## 12. Rank persistence (task 13)

Month-to-month score rank correlation **median ρ = 0.930** (62 consecutive pairs);
top-decile retention 77.5% (turnover 22.5%/month); top-quintile retention 80.2%
(**turnover 19.8%/month**). Suitable order-of-magnitude for monthly mechanical use.

## 13. Distribution (task 14)

Overall: min 2.06 · p1 12.4 · p5 16.6 · p10 17.7 · median 24.0 · p75 29.0 · p90 33.9 ·
p95 37.8 · p99 50.9 · max 71.27 (by year in `score_distribution.csv`). The score is a
0–100-scaled composite of weighted percentile ranks × a coverage multiplier — **NOT a
probability, NOT an expected return; no mapping to returns is implied.**

## 14. Price-derived dominance check (task 15)

The score is genuinely accounting/fundamental-driven: price-derived components
(PE/PS/PB/liquidity/vol/momentum) hold **6.1%** of effective contribution mass vs **93.9%**
accounting. Attribution sub-scores (descriptive only): price-side IC63 0.073 / IC126 0.104;
accounting-side IC63 0.077 / IC126 0.082 — the tiny price sleeve adds diversification
(esp. 126d) despite its small weight.

## 15. Evidence summary (task 16)

- FULL_SCORE_IC63 = +0.0853 · FULL_SCORE_IC126 = +0.1096
- FULL_SCORE_IC63_CI = [0.047, 0.125] · FULL_SCORE_IC126_CI = [0.063, 0.160]
- FULL_SCORE_YEAR_STABILITY: 0.025 / 0.024 / 0.042 / 0.164 / 0.151 / 0.214 (2021→2026)
- 63d monotonic-date share 9.7% (means upward, Q2/Q3 inversion) · 126d 14.8%
- TOP_QUINTILE_MONTHLY_TURNOVER = 0.198
- REDUNDANT_COMPONENT_COUNT = 3 · UNSTABLE_COMPONENT_COUNT = 0 (|IC63|>0.10 sign flips)
- MATERIAL_NEGATIVE_COMPONENT_COUNT = 5 (NetMargin, PS, PB, Leverage, CurrentRatio —
  both-horizon negative, small magnitudes, yearly signs not stable)
- CATEGORY_ABLATION_SENSITIVITY: Growth −0.011 IC63 when removed; Profitability/MarketRisk
  ±0.000; Valuation −0.003 (spreads −1.1 / +0.2 / −2.2 / −0.8pp)
- DQ_EFFECT: helps (IC63 +0.003, spread +0.18pp vs pre-DQ)

## 16. SCORE V2 RESEARCH JUSTIFICATION (task 17)

**SCORE_V2_RESEARCH_JUSTIFIED = YES** — concrete triggers from the diagnostics:

1. **Material redundancy** (3 pairs |ρ| ≥ 0.70): PE↔PS 0.77, PE↔PB 0.76,
   Leverage↔CurrentRatio 0.82 — the 16-point valuation block triple-counts one economic
   quantity and the leverage block double-counts another.
2. **Five components contribute negatively on both horizons** (NetMargin, PS, PB,
   Leverage, CurrentRatio) at their current coverages.
3. **Nominal/effective weight mismatches**: Liquidity 3.4% nominal → 0% effective (source
   data 96% NULL); PS/PB effectively inert at ~2% coverage.
4. **Two of four categories carry no provable ranking information** on the PIT-correct
   panel (Profitability CI [−0.011, 0.039]; Valuation CI [−0.017, 0.027]).

Explicitly NOT a trigger: the weaker overall IC vs the leaky reconstruction — most of that
gap is the 2021–23 fundamental-visibility ramp, not a scoring defect, and "weaker IC" alone
would not justify optimization. **This authorizes RESEARCH into a V2 family only; no V2 was
built, no weights changed, production score untouched.**

## 17. Portfolio-backtest justification (task 18)

**SCORE_PORTFOLIO_BACKTEST_JUSTIFIED = YES** — positive medium-horizon ranking
(IC63 +0.085 CI>0; IC126 +0.110), 235 symbols / 12,604 rows / 63 dates, rank persistence
ρ 0.930, top-quintile turnover 19.8%/month, cross-sectional dispersion present
(p90−p10 ≈ 16 points). Factual caveat for any future backtest design: fundamental
visibility ramps from ~0 (2021–22) to material (2024+); how to treat the ramp years is a
design decision for that backtest's own preregistration, made in advance, not here.
**This does NOT authorize the backtest.**

## 18. Files

`score_deep_audit_v1.json` (machine-readable, all sections) · `score_component_diagnostics.csv` ·
`score_category_diagnostics.csv` · `score_redundancy_matrix.csv` · `score_year_stability.csv` ·
`score_ablation_diagnostics.csv` · `score_distribution.csv` · supporting:
`score_component_coverage.csv`, `score_weight_concentration.csv` · this MD.
Frozen inputs: `ui_score_historical_pit_v2.parquet` (543dfbf7…) + JSONL; audit script
`run_score_deep_audit_v1.py`.
