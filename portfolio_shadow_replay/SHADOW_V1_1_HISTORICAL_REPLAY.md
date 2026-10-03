# SHADOW V1.1 — HISTORICAL WALK-FORWARD REPLAY

**Label: `HISTORICAL_REPLAY_ONLY`.** This document replays the CURRENT frozen Shadow V1.1 harness month-by-month over the certified historical PIT decision dates. It is engineering validation of what the live harness itself would have generated historically. It is **NOT** the forward 12-month shadow, **NOT** forward validation, **NOT** new validation, and **NOT** new evidence for promotion. No live shadow state was touched.

- Active frozen spec: `portfolio_shadow/SHADOW_V1_1_SPEC.md` — SHA-256 `f396b5f65474a017f7f97ff9f2d0c8679708f6e20ee104dc19dc53d06709ff0e` (verified before the run)
- PIT score source: `ui_score_research/ui_score_historical_pit_v2.parquet` — SHA-256 `543dfbf732ae9b60eff8014b2226faa806ffb85baec8794a109870c97df0639a` (verified)
- Strategy: `score-portfolio-v1-top20` · score `canonical-v1-dev` · selection highest 20% by `quant_score DESC, symbol ASC` · equal target weights · 50 bps one-way BASE
- Engine: `portfolio_shadow/build_shadow_portfolio.py` (selection/decision semantics) + `portfolio_shadow/observe_shadow_execution.py` (execution/close semantics) + `portfolio_shadow/deterministic_accounting.py` (certified repaired accounting, sorted port) + `portfolio_research/repair_accounting_v1.py` (certified adjusted price chain) — the same modules the live shadow runs
- Information rule: at every decision date T the replay used only that month's PIT score snapshot; no future snapshot influences an earlier target; decisions processed sequentially (freeze target → execution date → update portfolio)
- Decision dates: **63** (2021-01-31 .. 2026-06-30; the known 2026-02/03/04 skipped months are absent by construction, exactly as in the certified run)
- Return semantics: PRICE_PLUS_MECHANICAL_ADJUSTMENTS (CONFIRMED gap-rule chain; no cash dividends); monthly return = NAV_post(E_k)→NAV_post(E_k+1); entry cost inside NAV_post(0)

## 1. Executive summary

| Metric | Replay (TOP20, BASE) | Benchmark (equal-weight all eligible, BASE) |
|---|---|---|
| Terminal wealth multiple | 5.6451 | 4.2755 |
| Annualized return | 39.79% | 32.47% |
| Max drawdown | -26.85% | — |
| Sharpe (0% rf) | 1.12 | — |
| Avg / median monthly turnover | 29.3% / 27.8% | — |
| Avg / median holdings | 41.5 / 44 | — |
| Avg monthly excess | 0.50% (positive in 58% of months) | — |
| Unique securities ever selected | **171** | 12604 scored rows total |

## 2. Parity with certified SCORE_PORTFOLIO_V1 (most important engineering test)

**SHADOW_REPLAY_PORTFOLIO_PARITY = PASS** — replay vs `score_portfolio_v1_*_accounting_repaired` certified artifacts, all 63 months.

| Comparison | Mismatches | Max abs diff |
|---|---|---|
| Execution dates | 0 | — |
| Eligible counts | 0 | — |
| Selected counts | 0 | — |
| Selected security sets | 0 | — |
| Trade notionals (BUY/SELL/SELL_REBAL) | 0 | — |
| absolute_traded_notional_fraction | 0 | 4.44e-16 |
| buy_notional | 0 | 7.77e-16 |
| buy_scale | 0 | 1.11e-15 |
| cash_weight | 0 | 6.22e-17 |
| failed_targets | 0 | 0.00e+00 |
| holdings_count | 0 | 0.00e+00 |
| sell_notional | 0 | 7.77e-16 |
| transaction_cost | 0 | 9.80e-17 |
| transaction_cost_fraction | 0 | 1.00e-16 |
| turnover | 0 | 1.67e-16 |
| value_post_trade | 0 | 1.78e-15 |
| value_pre_trade | 0 | 2.22e-15 |

All residual differences are float-summation-order noise (≤ 3e-15); the certified engine iterates name sets in hash order while the shadow harness iterates in sorted order — economics identical. Root causes checked and ruled out: execution-date calendar (re-derived 63/63 identical), tradability source (14805 (E, symbol) pairs, 0 disagreements between path-A cache evidence and the certified daily-panel flag), identity mapping (235 UNIQUE), selection/sort rule (identical).

## 3. Yearly view

| Year | Rebal | Start hold | End hold | Avg hold | Avg turnover | Portfolio | Benchmark | Excess | MDD | Best | Worst |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2021 | 11 | 0 | 41 | 26.9 | 42.5% | -11.44% | -12.65% | 1.22% | -20.87% | 12.00% | -14.39% |
| 2022 | 12 | 41 | 43 | 43.3 | 31.8% | 31.27% | 31.73% | -0.46% | -11.70% | 14.72% | -8.67% |
| 2023 | 12 | 43 | 44 | 44.2 | 25.4% | 59.96% | 63.63% | -3.67% | -23.16% | 30.12% | -10.84% |
| 2024 | 12 | 44 | 44 | 44.4 | 21.4% | 26.92% | 18.67% | 8.24% | -11.45% | 15.88% | -10.35% |
| 2025 | 12 | 44 | 49 | 46.4 | 24.4% | 54.83% | 37.54% | 17.29% | -20.29% | 19.56% | -10.77% |
| 2026 | 4 | 49 | 43 | 45.2 | 35.6% | 55.25% | 39.83% | 15.43% | -5.71% | 36.29% | -5.71% |

Most frequently held per year (top 10, by decision month):
- **2021**: شرانل; شپدیس; رمپنا; سمازن; سکرما; تاصیکو; دتماد; خبهمن; کاسپین; تپمپی
- **2022**: غمینو; دجابر; شمواد; دتماد; غاذر; دلقما; رمپنا; غکورش; کاما; غپینو
- **2023**: غمینو; دجابر; سفانو; غپینو; دلقما; کحافظ; رمپنا; کپشیر; غکورش; زفکا
- **2024**: غمینو; شمواد; سیستم; پکویر; غکورش; غپینو; افق; سشرق; خبهمن; پتایر
- **2025**: غاذر; غمینو; ساربیل; سصوفی; غکورش; بپیوند; دلقما; غپینو; سباقر; کاسپین
- **2026**: غاذر; غمینو; سباقر; دابور; دلقما; دزهراوی; رمپنا; غکورش; غپینو; دارو

Months with highest target turnover: 2021-01 100.0%; 2021-07 58.1%; 2026-05 54.4%; 2021-08 53.8%; 2022-07 51.4%
Months with largest positive excess: 2026-05 +9.32% (port +36.29% / bench +26.97%); 2021-06 +5.56% (port +12.00% / bench +6.44%); 2024-05 +3.86% (port +2.18% / bench -1.68%); 2025-03 +3.44% (port +19.56% / bench +16.12%); 2021-04 +3.37% (port -7.29% / bench -10.65%)
Months with largest negative excess: 2022-02 -2.50% (port +10.57% / bench +13.07%); 2021-07 -2.84% (port +10.40% / bench +13.24%); 2023-09 -3.18% (port -10.84% / bench -7.66%); 2023-01 -3.62% (port +8.41% / bench +12.03%); 2021-01 -6.55% (port -5.72% / bench +0.83%)

## 4. Monthly timeline (all historical decisions)

### 2021-01

score 2021-01-31 (cutoff 2021-01-31T23:59:59+00:00) → exec 2021-02-01 · Eligible: **79** · Selected: **15** · Turnover (target): **100.0%** · Realized traded: 99.5% · Cost: 0.50%
Actions: BUY 15 · INCREASE 0 · DECREASE 0 · HOLD 0 · exits (SELL) 0 · carried-unselected 0 · cash-failed 0 (first month: full entry)
- ENTERED (15): تاصیکو,سدور,تپمپی,وپست,شرانل,سنیر,گشان,پخش,کپشیر,وخارزم,وخاور,شپدیس,کالا,خبهمن,شستا
- Retained: 0 · Holdings: 15 · Cash: -0.0% · Top-5 weight: 33.3% · Top-10 weight: 66.7%
- Largest weight increases (vs prev target): [["تاصیکو", 0.0667], ["سدور", 0.0667], ["تپمپی", 0.0667], ["وپست", 0.0667], ["شرانل", 0.0667]]
- Portfolio month: **-5.72%** · Benchmark: 0.83% · Excess: **-6.55%** · NAV 0.9950 (dd -0.50%) · Bench NAV 0.9950

### 2021-02

score 2021-02-28 (cutoff 2021-02-28T23:59:59+00:00) → exec 2021-03-01 · Eligible: **82** · Selected: **16** · Turnover (target): **26.7%** · Realized traded: 53.2% · Cost: 0.27%
Actions: BUY 4 · INCREASE 5 · DECREASE 7 · HOLD 0 · exits (SELL) 3 · carried-unselected 0 · cash-failed 0
- ENTERED (4): درهآور,فولای,سپیدار,قلرست
- EXITED (3): سدور,سنیر,کپشیر
- Retained: 12 · Holdings: 16 · Cash: -0.0% · Top-5 weight: 31.3% · Top-10 weight: 62.7%
- Largest weight increases (vs prev target): [["درهآور", 0.0625], ["فولای", 0.0625], ["سپیدار", 0.0625], ["قلرست", 0.0625]]
- Largest weight decreases (vs prev target): [["کپشیر", -0.0667], ["سنیر", -0.0667], ["سدور", -0.0667], ["شستا", -0.0042], ["خبهمن", -0.0042]]
- Largest score increases (eligible overlap, descriptive): [["حسینا", 1.33], ["درهآور", 1.26], ["فولای", 1.09], ["بپیوند", 1.02], ["بهپاک", 0.97]]
- Largest score decreases (eligible overlap, descriptive): [["شرانل", -0.89], ["کلر", -0.83], ["وسپه", -0.82], ["شگل", -0.76], ["کاوه", -0.75]]
- Portfolio month: **3.24%** · Benchmark: 4.59% · Excess: **-1.34%** · NAV 0.9381 (dd -6.19%) · Bench NAV 1.0032

### 2021-03

score 2021-03-31 (cutoff 2021-03-31T23:59:59+00:00) → exec 2021-04-03 · Eligible: **81** · Selected: **16** · Turnover (target): **27.8%** · Realized traded: 44.3% · Cost: 0.22%
Actions: BUY 4 · INCREASE 5 · DECREASE 7 · HOLD 0 · exits (SELL) 3 · carried-unselected 1 · cash-failed 0
- ENTERED (4): هجرت,پرداخت,رمپنا,قاسم
- EXITED (4): درهآور,خبهمن,فولای,سپیدار
- Retained: 12 · Holdings: 17 · Cash: -0.0% · Top-5 weight: 31.3% · Top-10 weight: 62.4%
- Largest weight increases (vs prev target): [["هجرت", 0.0625], ["پرداخت", 0.0625], ["رمپنا", 0.0625], ["قاسم", 0.0625]]
- Largest weight decreases (vs prev target): [["سپیدار", -0.0625], ["فولای", -0.0625], ["خبهمن", -0.0625], ["درهآور", -0.0625]]
- Largest score increases (eligible overlap, descriptive): [["تاصیکو", 8.41], ["رمپنا", 7.95], ["تپمپی", 1.2], ["کالا", 1.12], ["شاوان", 1.11]]
- Largest score decreases (eligible overlap, descriptive): [["سپیدار", -1.24], ["کپشیر", -1.09], ["شستا", -0.75], ["سنیر", -0.65], ["ساروم", -0.53]]
- Portfolio month: **-6.37%** · Benchmark: -5.49% · Excess: **-0.88%** · NAV 0.9685 (dd -3.15%) · Bench NAV 1.0493

### 2021-04

score 2021-04-28 (cutoff 2021-04-28T23:59:59+00:00) → exec 2021-05-01 · Eligible: **85** · Selected: **17** · Turnover (target): **49.4%** · Realized traded: 98.3% · Cost: 0.49%
Actions: BUY 8 · INCREASE 2 · DECREASE 7 · HOLD 0 · exits (SELL) 8 · carried-unselected 0 · cash-failed 0
- ENTERED (8): دبالک,سمازن,کاسپین,شیران,سکرما,سشمال,ساربیل,غبشهر
- EXITED (7): تپمپی,هجرت,پرداخت,وخارزم,قاسم,قلرست,شستا
- Retained: 9 · Holdings: 17 · Cash: 0.0% · Top-5 weight: 29.6% · Top-10 weight: 59.0%
- Largest weight increases (vs prev target): [["دبالک", 0.0588], ["سمازن", 0.0588], ["کاسپین", 0.0588], ["شیران", 0.0588], ["سکرما", 0.0588]]
- Largest weight decreases (vs prev target): [["شستا", -0.0625], ["قلرست", -0.0625], ["قاسم", -0.0625], ["وخارزم", -0.0625], ["پرداخت", -0.0625]]
- Largest score increases (eligible overlap, descriptive): [["کاسپین", 10.8], ["حکشتی", 9.16], ["شوینده", 6.91], ["ثبهساز", 2.83], ["تاصیکو", 1.29]]
- Largest score decreases (eligible overlap, descriptive): [["شستا", -10.11], ["تپمپی", -5.95], ["وخارزم", -5.87], ["وسپه", -5.12], ["شگل", -4.26]]
- Portfolio month: **-7.29%** · Benchmark: -10.65% · Excess: **3.37%** · NAV 0.9068 (dd -9.32%) · Bench NAV 0.9917

### 2021-05

score 2021-05-31 (cutoff 2021-05-31T23:59:59+00:00) → exec 2021-06-01 · Eligible: **92** · Selected: **18** · Turnover (target): **13.4%** · Realized traded: 26.7% · Cost: 0.13%
Actions: BUY 2 · INCREASE 5 · DECREASE 11 · HOLD 0 · exits (SELL) 1 · carried-unselected 0 · cash-failed 0
- ENTERED (2): بهپاک,دتماد
- EXITED (1): پخش
- Retained: 16 · Holdings: 18 · Cash: -0.0% · Top-5 weight: 27.8% · Top-10 weight: 55.6%
- Largest weight increases (vs prev target): [["بهپاک", 0.0556], ["دتماد", 0.0556]]
- Largest weight decreases (vs prev target): [["پخش", -0.0588], ["کالا", -0.0033], ["غبشهر", -0.0033], ["شپدیس", -0.0033], ["وخاور", -0.0033]]
- Largest score increases (eligible overlap, descriptive): [["دتماد", 8.74], ["سپیدار", 4.86], ["دزهراوی", 3.73], ["کیمیا", 1.13], ["فبیرا", 0.93]]
- Largest score decreases (eligible overlap, descriptive): [["پخش", -7.85], ["سبجنو", -1.78], ["ساروم", -1.61], ["پرداخت", -1.31], ["قاسم", -1.1]]
- Portfolio month: **5.82%** · Benchmark: 5.40% · Excess: **0.42%** · NAV 0.8408 (dd -15.92%) · Bench NAV 0.8861

### 2021-06

score 2021-06-30 (cutoff 2021-06-30T23:59:59+00:00) → exec 2021-07-03 · Eligible: **88** · Selected: **17** · Turnover (target): **17.6%** · Realized traded: 24.1% · Cost: 0.12%
Actions: BUY 2 · INCREASE 11 · DECREASE 4 · HOLD 0 · exits (SELL) 2 · carried-unselected 1 · cash-failed 0
- ENTERED (2): شوینده,کهمدا
- EXITED (3): دبالک,رمپنا,کالا
- Retained: 15 · Holdings: 18 · Cash: -0.0% · Top-5 weight: 29.4% · Top-10 weight: 58.6%
- Largest weight increases (vs prev target): [["شوینده", 0.0588], ["کهمدا", 0.0588], ["تاصیکو", 0.0033], ["وپست", 0.0033], ["شرانل", 0.0033]]
- Largest weight decreases (vs prev target): [["کالا", -0.0556], ["رمپنا", -0.0556], ["دبالک", -0.0556]]
- Largest score increases (eligible overlap, descriptive): [["کهمدا", 8.48], ["دتماد", 5.44], ["شستا", 1.2], ["دزهراوی", 1.06], ["شغدیر", 1.06]]
- Largest score decreases (eligible overlap, descriptive): [["دتوزیع", -1.66], ["دارو", -1.54], ["کلر", -1.31], ["خمهر", -1.17], ["دبالک", -1.17]]
- Portfolio month: **12.00%** · Benchmark: 6.44% · Excess: **5.56%** · NAV 0.8897 (dd -11.03%) · Bench NAV 0.9339

### 2021-07

score 2021-07-31 (cutoff 2021-07-31T23:59:59+00:00) → exec 2021-08-01 · Eligible: **156** · Selected: **31** · Turnover (target): **58.1%** · Realized traded: 115.6% · Cost: 0.58%
Actions: BUY 18 · INCREASE 0 · DECREASE 13 · HOLD 0 · exits (SELL) 5 · carried-unselected 0 · cash-failed 0
- ENTERED (18): غکورش,تپمپی,دبالک,دجابر,وخارزم,رمپنا,غویتا,غمینو,پتایر,دلقما,ثبهساز,کچاد,غپینو,حکشتی,خبهمن,کاما,پارس,شستا
- EXITED (4): وپست,کاسپین,گشان,وخاور
- Retained: 13 · Holdings: 31 · Cash: -0.0% · Top-5 weight: 16.2% · Top-10 weight: 32.4%
- Largest weight increases (vs prev target): [["غکورش", 0.0323], ["تپمپی", 0.0323], ["دبالک", 0.0323], ["دجابر", 0.0323], ["وخارزم", 0.0323]]
- Largest weight decreases (vs prev target): [["وخاور", -0.0588], ["گشان", -0.0588], ["کاسپین", -0.0588], ["وپست", -0.0588], ["دتماد", -0.0266]]
- Largest score increases (eligible overlap, descriptive): [["غویتا", 8.54], ["شستا", 8.32], ["ثبهساز", 4.82], ["تاصیکو", 1.4], ["سبجنو", 1.4]]
- Largest score decreases (eligible overlap, descriptive): [["کاسپین", -10.77], ["شپدیس", -8.78], ["وخاور", -8.77], ["وپست", -8.31], ["گشان", -7.92]]
- Portfolio month: **10.40%** · Benchmark: 13.24% · Excess: **-2.84%** · NAV 0.9964 (dd -0.36%) · Bench NAV 0.9941

### 2021-08

score 2021-08-31 (cutoff 2021-08-31T23:59:59+00:00) → exec 2021-09-01 · Eligible: **198** · Selected: **39** · Turnover (target): **53.8%** · Realized traded: 101.0% · Cost: 0.50%
Actions: BUY 21 · INCREASE 0 · DECREASE 18 · HOLD 0 · exits (SELL) 12 · carried-unselected 1 · cash-failed 0
- ENTERED (21): فباهنر,بگیلان,کحافظ,شبهرن,دابور,هجرت,کاسپین,دارو,دزهراوی,ارفع,فملی,شیراز,کرماشا,ساروم,دسینا,قرن,دعبید,شسپا,کطبس,دکپسول,کلوند
- EXITED (13): غکورش,تپمپی,شرانل,وخارزم,غویتا,پتایر,ثبهساز,کچاد,شپدیس,غپینو,حکشتی,پارس,شستا
- Retained: 18 · Holdings: 40 · Cash: -0.0% · Top-5 weight: 13.4% · Top-10 weight: 26.3%
- Largest weight increases (vs prev target): [["فباهنر", 0.0256], ["بگیلان", 0.0256], ["کحافظ", 0.0256], ["شبهرن", 0.0256], ["دابور", 0.0256]]
- Largest weight decreases (vs prev target): [["شستا", -0.0323], ["پارس", -0.0323], ["حکشتی", -0.0323], ["غپینو", -0.0323], ["شپدیس", -0.0323]]
- Largest score increases (eligible overlap, descriptive): [["دجابر", 13.41], ["غمینو", 10.59], ["دارو", 9.87], ["کاسپین", 9.07], ["کطبس", 8.63]]
- Largest score decreases (eligible overlap, descriptive): [["شرانل", -5.36], ["غپینو", -1.17], ["غبشهر", -1.03], ["غنوش", -0.91], ["تکمبا", -0.8]]
- Portfolio month: **-7.57%** · Benchmark: -8.17% · Excess: **0.60%** · NAV 1.1000 (dd 0.00%) · Bench NAV 1.1257

### 2021-09

score 2021-09-29 (cutoff 2021-09-29T23:59:59+00:00) → exec 2021-10-02 · Eligible: **202** · Selected: **40** · Turnover (target): **37.1%** · Realized traded: 62.0% · Cost: 0.31%
Actions: BUY 14 · INCREASE 13 · DECREASE 13 · HOLD 0 · exits (SELL) 12 · carried-unselected 2 · cash-failed 0
- ENTERED (15): نوری,سکرد,بمپنا,پخش,خراسان,غویتا,خزامیا,آریا,غاذر,فاراک,سپیدار,قصفها,قلرست,شستا,بپیوند
- EXITED (14): تاصیکو,کحافظ,دبالک,شوینده,دابور,دزهراوی,شیراز,غمینو,دسینا,قرن,دعبید,شسپا,دکپسول,کلوند
- Retained: 25 · Holdings: 42 · Cash: -0.0% · Top-5 weight: 13.5% · Top-10 weight: 26.0%
- Largest weight increases (vs prev target): [["نوری", 0.025], ["سکرد", 0.025], ["بمپنا", 0.025], ["پخش", 0.025], ["خراسان", 0.025]]
- Largest weight decreases (vs prev target): [["کلوند", -0.0256], ["دکپسول", -0.0256], ["شسپا", -0.0256], ["دعبید", -0.0256], ["قرن", -0.0256]]
- Largest score increases (eligible overlap, descriptive): [["دلقما", 13.36], ["سکرد", 11.64], ["کپارس", 11.22], ["غاذر", 9.12], ["چکاپا", 8.83]]
- Largest score decreases (eligible overlap, descriptive): [["تاصیکو", -14.55], ["دبالک", -5.16], ["شوینده", -3.57], ["دکپسول", -3.49], ["دابور", -2.44]]
- Portfolio month: **-14.39%** · Benchmark: -15.59% · Excess: **1.21%** · NAV 1.0167 (dd -7.57%) · Bench NAV 1.0337

### 2021-10

score 2021-10-31 (cutoff 2021-10-31T23:59:59+00:00) → exec 2021-11-01 · Eligible: **204** · Selected: **40** · Turnover (target): **46.7%** · Realized traded: 88.1% · Cost: 0.44%
Actions: BUY 17 · INCREASE 14 · DECREASE 9 · HOLD 0 · exits (SELL) 18 · carried-unselected 1 · cash-failed 0
- ENTERED (19): تپمپی,غدام,کمنگنز,شرانل,شغدیر,پاکشو,سهگمت,کپشیر,شیراز,فگستر,غمینو,سبجنو,قنیشا,سیستم,سفانو,سصوفی,دعبید,فنوال,شسپا
- EXITED (19): فباهنر,بگیلان,کهمدا,سمازن,هجرت,بمپنا,ارفع,شیران,فملی,کرماشا,سشمال,غویتا,ساربیل,ساروم,بهپاک,آریا,غبشهر,فاراک,شستا
- Retained: 21 · Holdings: 41 · Cash: -0.0% · Top-5 weight: 12.6% · Top-10 weight: 25.1%
- Largest weight increases (vs prev target): [["تپمپی", 0.025], ["غدام", 0.025], ["کمنگنز", 0.025], ["شرانل", 0.025], ["شغدیر", 0.025]]
- Largest weight decreases (vs prev target): [["شستا", -0.025], ["فاراک", -0.025], ["غبشهر", -0.025], ["آریا", -0.025], ["بهپاک", -0.025]]
- Largest score increases (eligible overlap, descriptive): [["غدام", 18.42], ["تپمپی", 10.75], ["خمحرکه", 6.75], ["چدن", 6.39], ["وسپه", 6.01]]
- Largest score decreases (eligible overlap, descriptive): [["کهمدا", -12.53], ["شیران", -11.81], ["غویتا", -10.03], ["سمازن", -9.64], ["ساربیل", -8.89]]
- Portfolio month: **2.66%** · Benchmark: 0.34% · Excess: **2.32%** · NAV 0.8705 (dd -20.87%) · Bench NAV 0.8725

### 2021-11

score 2021-11-30 (cutoff 2021-11-30T23:59:59+00:00) → exec 2021-12-01 · Eligible: **208** · Selected: **41** · Turnover (target): **36.9%** · Realized traded: 73.4% · Cost: 0.37%
Actions: BUY 14 · INCREASE 17 · DECREASE 10 · HOLD 0 · exits (SELL) 14 · carried-unselected 0 · cash-failed 0
- ENTERED (14): فباهنر,سمازن,شبصیر,شمواد,شگویا,شگل,بشهاب,غویتا,خمحرکه,دسینا,شپدیس,غپینو,بوعلی,کگل
- EXITED (13): نوری,کمنگنز,دارو,سکرد,شغدیر,پاکشو,پخش,شیراز,دعبید,فنوال,شسپا,کطبس,بپیوند
- Retained: 27 · Holdings: 41 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.5%
- Largest weight increases (vs prev target): [["فباهنر", 0.0244], ["سمازن", 0.0244], ["شبصیر", 0.0244], ["شمواد", 0.0244], ["شگویا", 0.0244]]
- Largest weight decreases (vs prev target): [["بپیوند", -0.025], ["کطبس", -0.025], ["شسپا", -0.025], ["فنوال", -0.025], ["دعبید", -0.025]]
- Largest score increases (eligible overlap, descriptive): [["شگل", 9.54], ["شکام", 7.77], ["غپینو", 4.76], ["کگل", 4.26], ["شپدیس", 3.8]]
- Largest score decreases (eligible overlap, descriptive): [["بپیوند", -4.75], ["شیراز", -3.4], ["سکرد", -3.31], ["پخش", -3.27], ["هجرت", -3.18]]
- Portfolio month: **-1.38%** · Benchmark: -0.73% · Excess: **-0.65%** · NAV 0.8936 (dd -18.77%) · Bench NAV 0.8755

### 2021-12

score 2021-12-29 (cutoff 2021-12-29T23:59:59+00:00) → exec 2022-01-01 · Eligible: **209** · Selected: **41** · Turnover (target): **34.6%** · Realized traded: 65.3% · Cost: 0.33%
Actions: BUY 13 · INCREASE 15 · DECREASE 13 · HOLD 0 · exits (SELL) 12 · carried-unselected 1 · cash-failed 0
- ENTERED (13): غکورش,فجر,دزهراوی,شیران,زگلدشت,سهرمز,پتایر,فولاد,شکام,تلیسه,فسپا,فنوال,دکپسول
- EXITED (13): فباهنر,شبهرن,شبصیر,کاسپین,کپشیر,سکرما,غویتا,سبجنو,خمحرکه,دلقما,سیستم,سصوفی,خبهمن
- Retained: 28 · Holdings: 42 · Cash: 0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.5%
- Largest weight increases (vs prev target): [["غکورش", 0.0244], ["فجر", 0.0244], ["دزهراوی", 0.0244], ["شیران", 0.0244], ["زگلدشت", 0.0244]]
- Largest weight decreases (vs prev target): [["خبهمن", -0.0244], ["سصوفی", -0.0244], ["سیستم", -0.0244], ["دلقما", -0.0244], ["خمحرکه", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["سهرمز", 8.95], ["غکورش", 4.21], ["شیران", 3.73], ["فسپا", 3.27], ["رمپنا", 3.15]]
- Largest score decreases (eligible overlap, descriptive): [["خبهمن", -12.99], ["سکرما", -8.33], ["کاسپین", -4.23], ["سصوفی", -3.44], ["سرود", -2.99]]
- Portfolio month: **-8.67%** · Benchmark: -8.68% · Excess: **0.02%** · NAV 0.8812 (dd -19.89%) · Bench NAV 0.8691

### 2022-01

score 2022-01-31 (cutoff 2022-01-31T23:59:59+00:00) → exec 2022-02-01 · Eligible: **203** · Selected: **40** · Turnover (target): **33.1%** · Realized traded: 65.9% · Cost: 0.33%
Actions: BUY 11 · INCREASE 20 · DECREASE 9 · HOLD 0 · exits (SELL) 13 · carried-unselected 0 · cash-failed 0
- ENTERED (12): فباهنر,شبهرن,کمنگنز,ارفع,فملی,کرماشا,خمحرکه,دلقما,سغرب,خودرو,دفرا,کیمیاتک
- EXITED (13): سمازن,شیران,زگلدشت,شگویا,خراسان,فگستر,سفانو,شپدیس,تلیسه,فسپا,کگل,فنوال,دکپسول
- Retained: 28 · Holdings: 40 · Cash: -0.0% · Top-5 weight: 12.5% · Top-10 weight: 25.1%
- Largest weight increases (vs prev target): [["فباهنر", 0.025], ["شبهرن", 0.025], ["کمنگنز", 0.025], ["ارفع", 0.025], ["فملی", 0.025]]
- Largest weight decreases (vs prev target): [["دکپسول", -0.0244], ["فنوال", -0.0244], ["کگل", -0.0244], ["فسپا", -0.0244], ["تلیسه", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["دجابر", 5.03], ["کیمیاتک", 4.2], ["ارفع", 3.93], ["سغرب", 3.89], ["خودرو", 3.41]]
- Largest score decreases (eligible overlap, descriptive): [["فگستر", -4.88], ["غاذر", -3.51], ["رمپنا", -3.51], ["زکشت", -2.98], ["شپدیس", -2.58]]
- Portfolio month: **-0.03%** · Benchmark: 0.12% · Excess: **-0.15%** · NAV 0.8048 (dd -26.83%) · Bench NAV 0.7936

### 2022-02

score 2022-02-28 (cutoff 2022-02-28T23:59:59+00:00) → exec 2022-03-02 · Eligible: **209** · Selected: **41** · Turnover (target): **28.3%** · Realized traded: 56.3% · Cost: 0.28%
Actions: BUY 11 · INCREASE 13 · DECREASE 17 · HOLD 0 · exits (SELL) 10 · carried-unselected 0 · cash-failed 0
- ENTERED (11): کحافظ,دبالک,کپارس,شغدیر,شدوص,کفرا,فسپا,فنوال,کخاک,کلر,فاراک
- EXITED (10): فباهنر,شبهرن,شرانل,فجر,سهگمت,کرماشا,خزامیا,خمحرکه,دسینا,قصفها
- Retained: 30 · Holdings: 41 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.5%
- Largest weight increases (vs prev target): [["کحافظ", 0.0244], ["دبالک", 0.0244], ["کپارس", 0.0244], ["شغدیر", 0.0244], ["شدوص", 0.0244]]
- Largest weight decreases (vs prev target): [["قصفها", -0.025], ["دسینا", -0.025], ["خمحرکه", -0.025], ["خزامیا", -0.025], ["کرماشا", -0.025]]
- Largest score increases (eligible overlap, descriptive): [["بهپاک", 7.27], ["غمهرا", 7.11], ["زبینا", 5.97], ["غدیس", 4.39], ["دزهراوی", 3.58]]
- Largest score decreases (eligible overlap, descriptive): [["غدام", -10.86], ["رمپنا", -4.71], ["دتماد", -4.36], ["دجابر", -3.53], ["کپشیر", -3.2]]
- Portfolio month: **10.57%** · Benchmark: 13.07% · Excess: **-2.50%** · NAV 0.8046 (dd -26.85%) · Bench NAV 0.7946

### 2022-03

score 2022-03-30 (cutoff 2022-03-30T23:59:59+00:00) → exec 2022-04-03 · Eligible: **212** · Selected: **42** · Turnover (target): **30.6%** · Realized traded: 60.9% · Cost: 0.30%
Actions: BUY 12 · INCREASE 11 · DECREASE 19 · HOLD 0 · exits (SELL) 11 · carried-unselected 0 · cash-failed 0
- ENTERED (12): غدیس,کهمدا,زفکا,غگل,سهگمت,کرماشا,سیستم,چدن,خنصیر,کماسه,زبینا,شاراک
- EXITED (11): کحافظ,غدام,کمنگنز,کپارس,سهرمز,فملی,بشهاب,پتایر,فنوال,قلرست,دفرا
- Retained: 30 · Holdings: 42 · Cash: -0.0% · Top-5 weight: 11.9% · Top-10 weight: 23.9%
- Largest weight increases (vs prev target): [["غدیس", 0.0238], ["کهمدا", 0.0238], ["زفکا", 0.0238], ["غگل", 0.0238], ["سهگمت", 0.0238]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0244], ["قلرست", -0.0244], ["فنوال", -0.0244], ["پتایر", -0.0244], ["بشهاب", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["سهگمت", 3.52], ["سیستم", 3.45], ["رمپنا", 3.31], ["کهمدا", 3.06], ["غاذر", 2.88]]
- Largest score decreases (eligible overlap, descriptive): [["غدام", -7.55], ["قلرست", -4.99], ["شوینده", -3.41], ["فجر", -2.59], ["تلیسه", -2.36]]
- Portfolio month: **11.79%** · Benchmark: 13.70% · Excess: **-1.91%** · NAV 0.8897 (dd -19.12%) · Bench NAV 0.8984

### 2022-04

score 2022-04-30 (cutoff 2022-04-30T23:59:59+00:00) → exec 2022-05-01 · Eligible: **206** · Selected: **41** · Turnover (target): **43.7%** · Realized traded: 78.4% · Cost: 0.39%
Actions: BUY 17 · INCREASE 15 · DECREASE 9 · HOLD 0 · exits (SELL) 16 · carried-unselected 2 · cash-failed 0
- ENTERED (17): نوری,حتاید,کحافظ,غدام,سمازن,شیران,زگلدشت,شگویا,شیراز,سشمال,ساربیل,بهپاک,آریا,سفانو,قاسم,غبشهر,دعبید
- EXITED (18): تپمپی,دبالک,غگل,شغدیر,شگل,شدوص,قنیشا,سغرب,شکام,بوعلی,خنصیر,کلر,فاراک,خودرو,کماسه,زبینا,کیمیاتک,شاراک
- Retained: 24 · Holdings: 43 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.5%
- Largest weight increases (vs prev target): [["نوری", 0.0244], ["حتاید", 0.0244], ["کحافظ", 0.0244], ["غدام", 0.0244], ["سمازن", 0.0244]]
- Largest weight decreases (vs prev target): [["شاراک", -0.0238], ["کیمیاتک", -0.0238], ["زبینا", -0.0238], ["کماسه", -0.0238], ["خودرو", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["ساربیل", 19.84], ["غبشهر", 18.18], ["کهمدا", 15.36], ["شیران", 14.99], ["غدام", 14.98]]
- Largest score decreases (eligible overlap, descriptive): [["شگل", -22.2], ["تپمپی", -12.25], ["حکشتی", -9.12], ["غویتا", -7.07], ["شوینده", -6.82]]
- Portfolio month: **2.71%** · Benchmark: 3.96% · Excess: **-1.25%** · NAV 0.9946 (dd -9.58%) · Bench NAV 1.0216

### 2022-05

score 2022-05-31 (cutoff 2022-05-31T23:59:59+00:00) → exec 2022-06-01 · Eligible: **201** · Selected: **40** · Turnover (target): **34.1%** · Realized traded: 50.4% · Cost: 0.25%
Actions: BUY 11 · INCREASE 23 · DECREASE 6 · HOLD 0 · exits (SELL) 10 · carried-unselected 4 · cash-failed 0
- ENTERED (12): دبالک,زاگرس,سکرد,غفارس,سکرما,شپدیس,سقاین,سصوفی,تایرا,دکپسول,رانفور,بپیوند
- EXITED (13): غدیس,نوری,حتاید,زفکا,زگلدشت,سشمال,کفرا,آریا,فولاد,قاسم,فسپا,کخاک,چدن
- Retained: 28 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.5% · Top-10 weight: 25.0%
- Largest weight increases (vs prev target): [["دبالک", 0.025], ["زاگرس", 0.025], ["سکرد", 0.025], ["غفارس", 0.025], ["سکرما", 0.025]]
- Largest weight decreases (vs prev target): [["چدن", -0.0244], ["کخاک", -0.0244], ["فسپا", -0.0244], ["قاسم", -0.0244], ["فولاد", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["غفارس", 11.66], ["سمازن", 10.55], ["سکرما", 8.34], ["سصوفی", 5.83], ["کیمیا", 5.67]]
- Largest score decreases (eligible overlap, descriptive): [["خنصیر", -6.08], ["فسپا", -5.39], ["دزهراوی", -2.92], ["غبشهر", -2.83], ["فاراک", -2.72]]
- Portfolio month: **-4.42%** · Benchmark: -4.79% · Excess: **0.37%** · NAV 1.0215 (dd -7.14%) · Bench NAV 1.0620

### 2022-06

score 2022-06-29 (cutoff 2022-06-29T23:59:59+00:00) → exec 2022-07-02 · Eligible: **209** · Selected: **41** · Turnover (target): **28.1%** · Realized traded: 41.9% · Cost: 0.21%
Actions: BUY 9 · INCREASE 20 · DECREASE 12 · HOLD 0 · exits (SELL) 9 · carried-unselected 3 · cash-failed 0
- ENTERED (9): بگیلان,حتاید,پاسا,خراسان,کپشیر,شدوص,ساروم,شسپا,خودرو
- EXITED (8): زاگرس,سکرد,شیران,شگویا,دلقما,سفانو,سقاین,بپیوند
- Retained: 32 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.4% · Top-10 weight: 24.6%
- Largest weight increases (vs prev target): [["بگیلان", 0.0244], ["حتاید", 0.0244], ["پاسا", 0.0244], ["خراسان", 0.0244], ["کپشیر", 0.0244]]
- Largest weight decreases (vs prev target): [["بپیوند", -0.025], ["سقاین", -0.025], ["سفانو", -0.025], ["دلقما", -0.025], ["شگویا", -0.025]]
- Largest score increases (eligible overlap, descriptive): [["ساروم", 6.17], ["فگستر", 4.49], ["کاسپین", 4.46], ["خودرو", 3.05], ["کپشیر", 2.95]]
- Largest score decreases (eligible overlap, descriptive): [["سغرب", -5.07], ["سفانو", -3.59], ["کهمدا", -2.96], ["انرژی", -2.68], ["کیمیا", -2.37]]
- Portfolio month: **-5.69%** · Benchmark: -8.32% · Excess: **2.63%** · NAV 0.9764 (dd -11.24%) · Bench NAV 1.0111

### 2022-07

score 2022-07-31 (cutoff 2022-07-31T23:59:59+00:00) → exec 2022-08-01 · Eligible: **211** · Selected: **42** · Turnover (target): **51.4%** · Realized traded: 91.6% · Cost: 0.46%
Actions: BUY 20 · INCREASE 13 · DECREASE 9 · HOLD 0 · exits (SELL) 20 · carried-unselected 2 · cash-failed 0
- ENTERED (21): غشاذر,شبهرن,پکویر,شبصیر,هجرت,کاسپین,دارو,زمگسا,افق,سشمال,خزامیا,دلقما,داسوه,قاسم,بوعلی,زکشت,کلوند,قصفها,زبینا,بپیوند,کیمیاتک
- EXITED (20): حتاید,کحافظ,دبالک,پاسا,دزهراوی,ارفع,سهگمت,کپشیر,شیراز,کرماشا,ساروم,سیستم,غاذر,شپدیس,تایرا,شسپا,خودرو,دکپسول,سپیدار,رانفور
- Retained: 21 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.6% · Top-10 weight: 24.5%
- Largest weight increases (vs prev target): [["غشاذر", 0.0238], ["شبهرن", 0.0238], ["پکویر", 0.0238], ["شبصیر", 0.0238], ["هجرت", 0.0238]]
- Largest weight decreases (vs prev target): [["رانفور", -0.0244], ["سپیدار", -0.0244], ["دکپسول", -0.0244], ["خودرو", -0.0244], ["شسپا", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["قصفها", 11.37], ["غمینو", 10.5], ["پکویر", 9.97], ["قاسم", 9.82], ["داسوه", 9.09]]
- Largest score decreases (eligible overlap, descriptive): [["رمپنا", -6.24], ["سیستم", -5.66], ["دزهراوی", -4.99], ["سپیدار", -4.9], ["حتاید", -4.13]]
- Portfolio month: **9.19%** · Benchmark: 7.02% · Excess: **2.17%** · NAV 0.9208 (dd -16.29%) · Bench NAV 0.9269

### 2022-08

score 2022-08-31 (cutoff 2022-08-31T23:59:59+00:00) → exec 2022-09-03 · Eligible: **216** · Selected: **43** · Turnover (target): **16.7%** · Realized traded: 27.2% · Cost: 0.14%
Actions: BUY 5 · INCREASE 25 · DECREASE 13 · HOLD 0 · exits (SELL) 5 · carried-unselected 1 · cash-failed 0
- ENTERED (6): زفکا,سشرق,شیران,زشگزا,سفانو,غاذر
- EXITED (5): غدام,زمگسا,شدوص,بپیوند,کیمیاتک
- Retained: 37 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.4% · Top-10 weight: 24.0%
- Largest weight increases (vs prev target): [["زفکا", 0.0233], ["سشرق", 0.0233], ["شیران", 0.0233], ["زشگزا", 0.0233], ["سفانو", 0.0233]]
- Largest weight decreases (vs prev target): [["کیمیاتک", -0.0238], ["بپیوند", -0.0238], ["شدوص", -0.0238], ["زمگسا", -0.0238], ["غدام", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["شیران", 10.43], ["سآبیک", 9.77], ["غشان", 6.65], ["زشگزا", 5.04], ["شپدیس", 4.82]]
- Largest score decreases (eligible overlap, descriptive): [["غدام", -10.5], ["رمپنا", -4.14], ["ساروم", -2.77], ["زاگرس", -2.66], ["فجر", -2.51]]
- Portfolio month: **-5.71%** · Benchmark: -6.44% · Excess: **0.73%** · NAV 1.0054 (dd -8.60%) · Bench NAV 0.9920

### 2022-09

score 2022-09-28 (cutoff 2022-09-28T23:59:59+00:00) → exec 2022-10-01 · Eligible: **211** · Selected: **42** · Turnover (target): **17.9%** · Realized traded: 16.1% · Cost: 0.08%
Actions: BUY 5 · INCREASE 31 · DECREASE 6 · HOLD 0 · exits (SELL) 3 · carried-unselected 4 · cash-failed 0
- ENTERED (6): سهرمز,زمگسا,شکام,کلر,بپیوند,کیمیاتک
- EXITED (7): غکورش,زفکا,افق,رمپنا,زشگزا,زکشت,دعبید
- Retained: 36 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.2%
- Largest weight increases (vs prev target): [["سهرمز", 0.0238], ["زمگسا", 0.0238], ["شکام", 0.0238], ["کلر", 0.0238], ["بپیوند", 0.0238]]
- Largest weight decreases (vs prev target): [["دعبید", -0.0233], ["زکشت", -0.0233], ["زشگزا", -0.0233], ["رمپنا", -0.0233], ["افق", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["سهرمز", 6.59], ["تاصیکو", 5.28], ["شگل", 4.42], ["چکاپا", 1.94], ["دفرا", 1.82]]
- Largest score decreases (eligible overlap, descriptive): [["غویتا", -3.24], ["فگستر", -2.84], ["کپشیر", -2.56], ["زشگزا", -2.21], ["پکویر", -2.09]]
- Portfolio month: **-4.86%** · Benchmark: -4.72% · Excess: **-0.14%** · NAV 0.9480 (dd -13.82%) · Bench NAV 0.9281

### 2022-10

score 2022-10-31 (cutoff 2022-10-31T23:59:59+00:00) → exec 2022-11-01 · Eligible: **212** · Selected: **42** · Turnover (target): **34.2%** · Realized traded: 45.4% · Cost: 0.23%
Actions: BUY 11 · INCREASE 22 · DECREASE 9 · HOLD 0 · exits (SELL) 10 · carried-unselected 5 · cash-failed 0
- ENTERED (14): غکورش,تپمپی,زفکا,دابور,سرود,پرداخت,غگل,سهگمت,افق,رمپنا,شیراز,کرماشا,غویتا,غشان
- EXITED (14): کهمدا,پکویر,شیران,زمگسا,سکرما,سشمال,ساربیل,بهپاک,قاسم,غبشهر,غپینو,بوعلی,کلوند,بپیوند
- Retained: 28 · Holdings: 47 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.1%
- Largest weight increases (vs prev target): [["غکورش", 0.0238], ["تپمپی", 0.0238], ["زفکا", 0.0238], ["دابور", 0.0238], ["سرود", 0.0238]]
- Largest weight decreases (vs prev target): [["بپیوند", -0.0238], ["کلوند", -0.0238], ["بوعلی", -0.0238], ["غپینو", -0.0238], ["غبشهر", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["غویتا", 15.95], ["تپمپی", 10.91], ["ثبهساز", 8.98], ["شگل", 8.41], ["شستا", 6.04]]
- Largest score decreases (eligible overlap, descriptive): [["سمازن", -14.85], ["ساربیل", -12.61], ["بهپاک", -12.57], ["شیران", -12.05], ["سکرما", -11.18]]
- Portfolio month: **14.72%** · Benchmark: 14.10% · Excess: **0.62%** · NAV 0.9019 (dd -18.01%) · Bench NAV 0.8843

### 2022-11

score 2022-11-30 (cutoff 2022-11-30T23:59:59+00:00) → exec 2022-12-03 · Eligible: **214** · Selected: **42** · Turnover (target): **28.7%** · Realized traded: 51.9% · Cost: 0.26%
Actions: BUY 8 · INCREASE 25 · DECREASE 9 · HOLD 0 · exits (SELL) 12 · carried-unselected 1 · cash-failed 0
- ENTERED (8): دبالک,غشصفا,سآبیک,ساربیل,سبجنو,قاسم,فاراک,دفرا
- EXITED (8): بگیلان,زفکا,دابور,سمازن,سهگمت,خراسان,غویتا,کاما
- Retained: 34 · Holdings: 43 · Cash: 0.0% · Top-5 weight: 12.1% · Top-10 weight: 24.1%
- Largest weight increases (vs prev target): [["دبالک", 0.0238], ["غشصفا", 0.0238], ["سآبیک", 0.0238], ["ساربیل", 0.0238], ["سبجنو", 0.0238]]
- Largest weight decreases (vs prev target): [["کاما", -0.0238], ["غویتا", -0.0238], ["خراسان", -0.0238], ["سهگمت", -0.0238], ["سمازن", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["شاوان", 7.26], ["کاذر", 4.61], ["کطبس", 3.88], ["شبندر", 3.72], ["سیستم", 3.31]]
- Largest score decreases (eligible overlap, descriptive): [["غکورش", -6.61], ["خچرخش", -5.46], ["بمپنا", -4.87], ["دزهراوی", -4.13], ["کخاک", -3.56]]
- Portfolio month: **11.80%** · Benchmark: 13.47% · Excess: **-1.66%** · NAV 1.0347 (dd -5.94%) · Bench NAV 1.0090

### 2022-12

score 2022-12-31 (cutoff 2022-12-31T23:59:59+00:00) → exec 2023-01-01 · Eligible: **213** · Selected: **42** · Turnover (target): **18.3%** · Realized traded: 31.5% · Cost: 0.16%
Actions: BUY 6 · INCREASE 20 · DECREASE 16 · HOLD 0 · exits (SELL) 6 · carried-unselected 1 · cash-failed 0
- ENTERED (6): شبندر,سکرد,زمگسا,غپینو,کالا,بپیوند
- EXITED (6): دبالک,شبصیر,پرداخت,ساربیل,زبینا,دفرا
- Retained: 36 · Holdings: 43 · Cash: -0.0% · Top-5 weight: 12.0% · Top-10 weight: 23.9%
- Largest weight increases (vs prev target): [["شبندر", 0.0238], ["سکرد", 0.0238], ["زمگسا", 0.0238], ["غپینو", 0.0238], ["کالا", 0.0238]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0238], ["زبینا", -0.0238], ["ساربیل", -0.0238], ["پرداخت", -0.0238], ["شبصیر", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["خبهمن", 6.18], ["فایرا", 4.04], ["خنصیر", 3.71], ["غپینو", 3.38], ["فباهنر", 2.75]]
- Largest score decreases (eligible overlap, descriptive): [["رمپنا", -9.83], ["پرداخت", -6.07], ["شبصیر", -5.3], ["کیمیا", -4.75], ["شیراز", -4.65]]
- Portfolio month: **4.50%** · Benchmark: 6.46% · Excess: **-1.95%** · NAV 1.1568 (dd 0.00%) · Bench NAV 1.1449

### 2023-01

score 2023-01-31 (cutoff 2023-01-31T23:59:59+00:00) → exec 2023-02-01 · Eligible: **201** · Selected: **40** · Turnover (target): **35.1%** · Realized traded: 55.2% · Cost: 0.28%
Actions: BUY 12 · INCREASE 19 · DECREASE 9 · HOLD 0 · exits (SELL) 12 · carried-unselected 3 · cash-failed 0
- ENTERED (13): کحافظ,دبالک,غنوش,خموتور,کپشیر,تپسی,زکشت,خبهمن,خودرو,کماسه,سپیدار,کاما,دفرا
- EXITED (15): غشاذر,سشرق,کاسپین,سکرد,سآبیک,زمگسا,افق,شیراز,خزامیا,شکام,سصوفی,دتماد,کالا,فاراک,بپیوند
- Retained: 27 · Holdings: 43 · Cash: -0.0% · Top-5 weight: 12.6% · Top-10 weight: 25.2%
- Largest weight increases (vs prev target): [["کحافظ", 0.025], ["دبالک", 0.025], ["غنوش", 0.025], ["خموتور", 0.025], ["کپشیر", 0.025]]
- Largest weight decreases (vs prev target): [["بپیوند", -0.0238], ["فاراک", -0.0238], ["کالا", -0.0238], ["دتماد", -0.0238], ["سصوفی", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["کاما", 16.41], ["غنوش", 12.2], ["کپرور", 7.82], ["تپسی", 7.55], ["سپیدار", 7.12]]
- Largest score decreases (eligible overlap, descriptive): [["سشرق", -9.65], ["افق", -7.17], ["شکام", -6.89], ["غپاک", -6.61], ["زبینا", -6.59]]
- Portfolio month: **8.41%** · Benchmark: 12.03% · Excess: **-3.62%** · NAV 1.2089 (dd 0.00%) · Bench NAV 1.2188

### 2023-02

score 2023-02-28 (cutoff 2023-02-28T23:59:59+00:00) → exec 2023-03-01 · Eligible: **209** · Selected: **41** · Turnover (target): **44.8%** · Realized traded: 71.2% · Cost: 0.36%
Actions: BUY 17 · INCREASE 14 · DECREASE 10 · HOLD 0 · exits (SELL) 15 · carried-unselected 4 · cash-failed 0
- ENTERED (18): شپارس,غشاذر,کهمدا,زفکا,زمگسا,غویتا,ساربیل,خزامیا,زشگزا,سغرب,دسینا,شپدیس,تلیسه,بوعلی,قرن,دعبید,دکپسول,کلوند
- EXITED (17): دبالک,سرود,شمواد,دارو,غگل,خموتور,تپسی,سبجنو,داسوه,غشان,خبهمن,کلر,خودرو,قصفها,کاما,دفرا,کیمیاتک
- Retained: 23 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 12.4% · Top-10 weight: 24.6%
- Largest weight increases (vs prev target): [["شپارس", 0.0244], ["غشاذر", 0.0244], ["کهمدا", 0.0244], ["زفکا", 0.0244], ["زمگسا", 0.0244]]
- Largest weight decreases (vs prev target): [["کیمیاتک", -0.025], ["دفرا", -0.025], ["کاما", -0.025], ["قصفها", -0.025], ["خودرو", -0.025]]
- Largest score increases (eligible overlap, descriptive): [["رمپنا", 12.74], ["سغرب", 10.08], ["غویتا", 9.11], ["کحافظ", 7.39], ["زمگسا", 7.07]]
- Largest score decreases (eligible overlap, descriptive): [["تپسی", -5.87], ["کمنگنز", -5.86], ["سبجنو", -4.56], ["شمواد", -3.46], ["فنورد", -3.36]]
- Portfolio month: **20.25%** · Benchmark: 16.96% · Excess: **3.29%** · NAV 1.3106 (dd 0.00%) · Bench NAV 1.3654

### 2023-03

score 2023-03-29 (cutoff 2023-03-29T23:59:59+00:00) → exec 2023-04-03 · Eligible: **218** · Selected: **43** · Turnover (target): **18.2%** · Realized traded: 36.3% · Cost: 0.18%
Actions: BUY 5 · INCREASE 22 · DECREASE 16 · HOLD 0 · exits (SELL) 7 · carried-unselected 0 · cash-failed 0
- ENTERED (8): دبالک,غدام,شمواد,شیراز,داسوه,کلر,کاما,دفرا
- EXITED (6): شپارس,سهرمز,شپدیس,بوعلی,قرن,کلوند
- Retained: 35 · Holdings: 43 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["دبالک", 0.0233], ["غدام", 0.0233], ["شمواد", 0.0233], ["شیراز", 0.0233], ["داسوه", 0.0233]]
- Largest weight decreases (vs prev target): [["کلوند", -0.0244], ["قرن", -0.0244], ["بوعلی", -0.0244], ["شپدیس", -0.0244], ["سهرمز", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["غدام", 11.37], ["غپینو", 7.92], ["شیران", 7.28], ["پاسا", 5.17], ["کرازی", 4.72]]
- Largest score decreases (eligible overlap, descriptive): [["قلرست", -4.09], ["بهپاک", -3.92], ["فولاد", -3.89], ["سهرمز", -2.58], ["شغدیر", -2.48]]
- Portfolio month: **30.12%** · Benchmark: 30.41% · Excess: **-0.30%** · NAV 1.5760 (dd 0.00%) · Bench NAV 1.5971

### 2023-04

score 2023-04-30 (cutoff 2023-04-30T23:59:59+00:00) → exec 2023-05-01 · Eligible: **208** · Selected: **41** · Turnover (target): **23.7%** · Realized traded: 42.8% · Cost: 0.21%
Actions: BUY 8 · INCREASE 22 · DECREASE 11 · HOLD 0 · exits (SELL) 9 · carried-unselected 1 · cash-failed 0
- ENTERED (8): پکویر,سمازن,خموتور,سهگمت,سکرما,شگل,ثبهساز,غبشهر
- EXITED (10): تپمپی,شبهرن,غدام,شمواد,کرماشا,زشگزا,داسوه,دکپسول,سپیدار,دفرا
- Retained: 33 · Holdings: 42 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.4%
- Largest weight increases (vs prev target): [["پکویر", 0.0244], ["سمازن", 0.0244], ["خموتور", 0.0244], ["سهگمت", 0.0244], ["سکرما", 0.0244]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0233], ["سپیدار", -0.0233], ["دکپسول", -0.0233], ["داسوه", -0.0233], ["زشگزا", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["غبشهر", 20.54], ["شگل", 20.25], ["ساربیل", 15.79], ["کهمدا", 13.27], ["سمازن", 13.11]]
- Largest score decreases (eligible overlap, descriptive): [["شستا", -13.96], ["تپمپی", -9.88], ["غدام", -9.37], ["حکشتی", -8.95], ["کرماشا", -7.1]]
- Portfolio month: **-6.05%** · Benchmark: -7.21% · Excess: **1.17%** · NAV 2.0506 (dd 0.00%) · Bench NAV 2.0828

### 2023-05

score 2023-05-31 (cutoff 2023-05-31T23:59:59+00:00) → exec 2023-06-03 · Eligible: **210** · Selected: **42** · Turnover (target): **20.8%** · Realized traded: 21.4% · Cost: 0.11%
Actions: BUY 7 · INCREASE 21 · DECREASE 14 · HOLD 0 · exits (SELL) 3 · carried-unselected 4 · cash-failed 0
- ENTERED (8): سرود,شمواد,وسپه,ارفع,شیران,سآبیک,زشگزا,سصوفی
- EXITED (7): غنوش,شبندر,کپشیر,ساربیل,قاسم,غاذر,دسینا
- Retained: 34 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 12.4% · Top-10 weight: 24.3%
- Largest weight increases (vs prev target): [["سرود", 0.0238], ["شمواد", 0.0238], ["وسپه", 0.0238], ["ارفع", 0.0238], ["شیران", 0.0238]]
- Largest weight decreases (vs prev target): [["دسینا", -0.0244], ["غاذر", -0.0244], ["قاسم", -0.0244], ["ساربیل", -0.0244], ["کپشیر", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["وسپه", 16.3], ["بهپاک", 9.7], ["خمحرکه", 8.41], ["ارفع", 7.07], ["کنور", 4.85]]
- Largest score decreases (eligible overlap, descriptive): [["غنوش", -6.33], ["قنیشا", -4.62], ["کخاک", -4.39], ["قلرست", -4.34], ["نوری", -4.13]]
- Portfolio month: **-3.12%** · Benchmark: -2.89% · Excess: **-0.23%** · NAV 1.9266 (dd -6.05%) · Bench NAV 1.9325

### 2023-06

score 2023-06-28 (cutoff 2023-06-28T23:59:59+00:00) → exec 2023-07-01 · Eligible: **208** · Selected: **41** · Turnover (target): **13.2%** · Realized traded: 13.6% · Cost: 0.07%
Actions: BUY 1 · INCREASE 28 · DECREASE 12 · HOLD 0 · exits (SELL) 3 · carried-unselected 3 · cash-failed 0
- ENTERED (5): کپشیر,ساربیل,غاذر,دسینا,دکپسول
- EXITED (6): غشصفا,ارفع,سآبیک,شیراز,کماسه,کاما
- Retained: 36 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.4%
- Largest weight increases (vs prev target): [["کپشیر", 0.0244], ["ساربیل", 0.0244], ["غاذر", 0.0244], ["دسینا", 0.0244], ["دکپسول", 0.0244]]
- Largest weight decreases (vs prev target): [["کاما", -0.0238], ["کماسه", -0.0238], ["شیراز", -0.0238], ["سآبیک", -0.0238], ["ارفع", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["شلیا", 7.17], ["غکورش", 7.12], ["قلرست", 5.25], ["بگیلان", 4.69], ["کاسپین", 3.77]]
- Largest score decreases (eligible overlap, descriptive): [["تپمپی", -8.97], ["کیمیا", -6.01], ["فملی", -4.54], ["شپارس", -3.35], ["سیستم", -3.14]]
- Portfolio month: **-4.95%** · Benchmark: -6.34% · Excess: **1.39%** · NAV 1.8665 (dd -8.98%) · Bench NAV 1.8767

### 2023-07

score 2023-07-31 (cutoff 2023-07-31T23:59:59+00:00) → exec 2023-08-01 · Eligible: **216** · Selected: **43** · Turnover (target): **33.1%** · Realized traded: 54.1% · Cost: 0.27%
Actions: BUY 13 · INCREASE 14 · DECREASE 16 · HOLD 0 · exits (SELL) 11 · carried-unselected 3 · cash-failed 0
- ENTERED (14): پاکشو,ارفع,زگلدشت,پتایر,پیزد,سیستم,زقیام,شکربن,پکرمان,خبهمن,خنصیر,کلوند,کاما,دفرا
- EXITED (12): غکورش,پکویر,هجرت,وسپه,شیران,غفارس,سکرما,سغرب,دسینا,سصوفی,کلر,دکپسول
- Retained: 29 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["پاکشو", 0.0233], ["ارفع", 0.0233], ["زگلدشت", 0.0233], ["پتایر", 0.0233], ["پیزد", 0.0233]]
- Largest weight decreases (vs prev target): [["دکپسول", -0.0244], ["کلر", -0.0244], ["سصوفی", -0.0244], ["دسینا", -0.0244], ["سغرب", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["دلقما", 18.48], ["پیزد", 13.09], ["پتایر", 10.63], ["خنصیر", 9.03], ["حفاری", 9.01]]
- Largest score decreases (eligible overlap, descriptive): [["غفارس", -16.27], ["شیراز", -11.07], ["غنوش", -7.31], ["خودکفا", -7.08], ["شبندر", -6.53]]
- Portfolio month: **0.88%** · Benchmark: 1.51% · Excess: **-0.63%** · NAV 1.7741 (dd -13.49%) · Bench NAV 1.7577

### 2023-08

score 2023-08-30 (cutoff 2023-08-30T23:59:59+00:00) → exec 2023-09-02 · Eligible: **216** · Selected: **43** · Turnover (target): **20.5%** · Realized traded: 30.8% · Cost: 0.15%
Actions: BUY 6 · INCREASE 27 · DECREASE 10 · HOLD 0 · exits (SELL) 7 · carried-unselected 2 · cash-failed 0
- ENTERED (7): غکورش,غدام,غفارس,دسینا,کلر,کماسه,زبینا
- EXITED (7): شمواد,پاکشو,ارفع,سهگمت,غویتا,خزامیا,غبشهر
- Retained: 36 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 12.1% · Top-10 weight: 23.8%
- Largest weight increases (vs prev target): [["غکورش", 0.0233], ["غدام", 0.0233], ["غفارس", 0.0233], ["دسینا", 0.0233], ["کلر", 0.0233]]
- Largest weight decreases (vs prev target): [["غبشهر", -0.0233], ["خزامیا", -0.0233], ["غویتا", -0.0233], ["سهگمت", -0.0233], ["ارفع", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["غاذر", 17.48], ["غدام", 10.16], ["دقاضی", 9.06], ["غمهرا", 5.75], ["شرانل", 4.34]]
- Largest score decreases (eligible overlap, descriptive): [["غویتا", -6.14], ["خزامیا", -5.75], ["ارفع", -4.37], ["فگستر", -4.22], ["کرماشا", -4.15]]
- Portfolio month: **-1.26%** · Benchmark: -1.31% · Excess: **0.05%** · NAV 1.7897 (dd -12.73%) · Bench NAV 1.7842

### 2023-09

score 2023-09-30 (cutoff 2023-09-30T23:59:59+00:00) → exec 2023-10-01 · Eligible: **222** · Selected: **44** · Turnover (target): **17.1%** · Realized traded: 34.0% · Cost: 0.17%
Actions: BUY 6 · INCREASE 22 · DECREASE 16 · HOLD 0 · exits (SELL) 7 · carried-unselected 0 · cash-failed 0
- ENTERED (8): شمواد,شیران,سشمال,بهپاک,سبجنو,سغرب,غبشهر,چدن
- EXITED (7): زمگسا,پتایر,شکربن,دسینا,تلیسه,زکشت,زبینا
- Retained: 36 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 11.4% · Top-10 weight: 22.8%
- Largest weight increases (vs prev target): [["شمواد", 0.0227], ["شیران", 0.0227], ["سشمال", 0.0227], ["بهپاک", 0.0227], ["سبجنو", 0.0227]]
- Largest weight decreases (vs prev target): [["زبینا", -0.0233], ["زکشت", -0.0233], ["تلیسه", -0.0233], ["دسینا", -0.0233], ["شکربن", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["غکورش", 15.75], ["شیران", 9.21], ["کاما", 8.53], ["قاسم", 3.37], ["فاراک", 2.9]]
- Largest score decreases (eligible overlap, descriptive): [["شوینده", -8.86], ["قلرست", -3.35], ["زمگسا", -3.1], ["دکپسول", -3.07], ["سهرمز", -3.06]]
- Portfolio month: **-10.84%** · Benchmark: -7.66% · Excess: **-3.18%** · NAV 1.7672 (dd -13.82%) · Bench NAV 1.7608

### 2023-10

score 2023-10-31 (cutoff 2023-10-31T23:59:59+00:00) → exec 2023-11-01 · Eligible: **216** · Selected: **43** · Turnover (target): **34.0%** · Realized traded: 58.2% · Cost: 0.29%
Actions: BUY 13 · INCREASE 21 · DECREASE 9 · HOLD 0 · exits (SELL) 12 · carried-unselected 2 · cash-failed 0
- ENTERED (13): شپارس,هجرت,دارو,پاکشو,غمهرا,زمگسا,پخش,حسینا,پتایر,دسینا,تلیسه,قصفها,زبینا
- EXITED (14): دبالک,کهمدا,سمازن,شیران,سشمال,ساربیل,پیزد,ثبهساز,سغرب,غبشهر,دعبید,کماسه,کلوند,دفرا
- Retained: 30 · Holdings: 45 · Cash: 0.0% · Top-5 weight: 11.8% · Top-10 weight: 23.5%
- Largest weight increases (vs prev target): [["شپارس", 0.0233], ["هجرت", 0.0233], ["دارو", 0.0233], ["پاکشو", 0.0233], ["غمهرا", 0.0233]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0227], ["کلوند", -0.0227], ["کماسه", -0.0227], ["دعبید", -0.0227], ["غبشهر", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["غدام", 12.92], ["کسرا", 9.45], ["گشان", 7.86], ["شستا", 7.63], ["فبیرا", 7.43]]
- Largest score decreases (eligible overlap, descriptive): [["شیران", -17.87], ["ساربیل", -16.27], ["غبشهر", -15.35], ["کهمدا", -13.43], ["سشمال", -10.62]]
- Portfolio month: **12.04%** · Benchmark: 10.65% · Excess: **1.39%** · NAV 1.5756 (dd -23.16%) · Bench NAV 1.6260

### 2023-11

score 2023-11-29 (cutoff 2023-11-29T23:59:59+00:00) → exec 2023-12-02 · Eligible: **219** · Selected: **43** · Turnover (target): **26.0%** · Realized traded: 47.0% · Cost: 0.23%
Actions: BUY 9 · INCREASE 21 · DECREASE 13 · HOLD 0 · exits (SELL) 10 · carried-unselected 1 · cash-failed 0
- ENTERED (10): دبالک,پکویر,پاسا,ساروم,خمحرکه,شکربن,سصوفی,کالا,کماسه,کلوند
- EXITED (10): غشاذر,هجرت,دارو,زمگسا,غفارس,بهپاک,سبجنو,چدن,کلر,زبینا
- Retained: 33 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["دبالک", 0.0233], ["پکویر", 0.0233], ["پاسا", 0.0233], ["ساروم", 0.0233], ["خمحرکه", 0.0233]]
- Largest weight decreases (vs prev target): [["زبینا", -0.0233], ["کلر", -0.0233], ["چدن", -0.0233], ["سبجنو", -0.0233], ["بهپاک", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["پاسا", 6.59], ["قنیشا", 6.29], ["پتایر", 4.74], ["پکویر", 4.5], ["کاذر", 4.35]]
- Largest score decreases (eligible overlap, descriptive): [["بهپاک", -16.48], ["غاذر", -5.26], ["غنوش", -5.08], ["بپیوند", -4.23], ["کحافظ", -4.04]]
- Portfolio month: **4.82%** · Benchmark: 4.12% · Excess: **0.70%** · NAV 1.7653 (dd -13.91%) · Bench NAV 1.7991

### 2023-12

score 2023-12-31 (cutoff 2023-12-31T23:59:59+00:00) → exec 2024-01-01 · Eligible: **218** · Selected: **43** · Turnover (target): **15.4%** · Realized traded: 26.1% · Cost: 0.13%
Actions: BUY 5 · INCREASE 25 · DECREASE 13 · HOLD 0 · exits (SELL) 5 · carried-unselected 1 · cash-failed 0
- ENTERED (6): ارفع,سهرمز,زمگسا,خزامیا,سقاین,چدن
- EXITED (6): پخش,حسینا,زشگزا,شکربن,سصوفی,خبهمن
- Retained: 37 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["ارفع", 0.0233], ["سهرمز", 0.0233], ["زمگسا", 0.0233], ["خزامیا", 0.0233], ["سقاین", 0.0233]]
- Largest weight decreases (vs prev target): [["خبهمن", -0.0233], ["سصوفی", -0.0233], ["شکربن", -0.0233], ["زشگزا", -0.0233], ["حسینا", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["کچاد", 7.4], ["قنیشا", 5.25], ["ارفع", 5.09], ["دابور", 4.87], ["کگل", 4.68]]
- Largest score decreases (eligible overlap, descriptive): [["دزهراوی", -4.24], ["زاگرس", -4.07], ["وپست", -4.01], ["زشگزا", -3.43], ["زبینا", -2.99]]
- Portfolio month: **-3.41%** · Benchmark: -2.99% · Excess: **-0.42%** · NAV 1.8504 (dd -9.76%) · Bench NAV 1.8733

### 2024-01

score 2024-01-31 (cutoff 2024-01-31T23:59:59+00:00) → exec 2024-02-03 · Eligible: **215** · Selected: **43** · Turnover (target): **30.8%** · Realized traded: 52.3% · Cost: 0.26%
Actions: BUY 12 · INCREASE 19 · DECREASE 12 · HOLD 0 · exits (SELL) 11 · carried-unselected 2 · cash-failed 0
- ENTERED (13): غدیس,کمنگنز,سشرق,سکرد,پخش,افق,حسینا,سبجنو,قنیشا,پیزد,تایرا,خبهمن,سپیدار
- EXITED (13): کحافظ,زفکا,خموتور,غمهرا,سهرمز,زمگسا,شگل,ساروم,خزامیا,سفانو,دسینا,سقاین,کالا
- Retained: 30 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["غدیس", 0.0233], ["کمنگنز", 0.0233], ["سشرق", 0.0233], ["سکرد", 0.0233], ["پخش", 0.0233]]
- Largest weight decreases (vs prev target): [["کالا", -0.0233], ["سقاین", -0.0233], ["دسینا", -0.0233], ["سفانو", -0.0233], ["خزامیا", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["سپیدار", 11.01], ["فگستر", 9.11], ["شمواد", 8.82], ["قنیشا", 8.0], ["پخش", 7.63]]
- Largest score decreases (eligible overlap, descriptive): [["دلقما", -11.61], ["غمینو", -8.74], ["دانا", -8.31], ["غپینو", -7.22], ["قاسم", -7.1]]
- Portfolio month: **-1.67%** · Benchmark: -1.51% · Excess: **-0.16%** · NAV 1.7874 (dd -12.84%) · Bench NAV 1.8173

### 2024-02

score 2024-02-28 (cutoff 2024-02-28T23:59:59+00:00) → exec 2024-03-02 · Eligible: **209** · Selected: **41** · Turnover (target): **24.9%** · Realized traded: 27.9% · Cost: 0.14%
Actions: BUY 7 · INCREASE 31 · DECREASE 3 · HOLD 0 · exits (SELL) 6 · carried-unselected 5 · cash-failed 0
- ENTERED (8): کهمدا,کاسپین,خموتور,غمهرا,سآبیک,فگستر,شکربن,کخاک
- EXITED (10): شپارس,کمنگنز,پاسا,پتایر,سبجنو,خمحرکه,پکرمان,تلیسه,قصفها,کاما
- Retained: 33 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.2%
- Largest weight increases (vs prev target): [["کهمدا", 0.0244], ["کاسپین", 0.0244], ["خموتور", 0.0244], ["غمهرا", 0.0244], ["سآبیک", 0.0244]]
- Largest weight decreases (vs prev target): [["کاما", -0.0233], ["قصفها", -0.0233], ["تلیسه", -0.0233], ["پکرمان", -0.0233], ["خمحرکه", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["کپرور", 4.87], ["سآبیک", 4.83], ["ذوب", 4.4], ["شکربن", 3.78], ["بمپنا", 3.61]]
- Largest score decreases (eligible overlap, descriptive): [["دارو", -8.46], ["قصفها", -6.75], ["رمپنا", -6.74], ["خودرو", -6.47], ["پاسا", -5.91]]
- Portfolio month: **6.13%** · Benchmark: 5.90% · Excess: **0.24%** · NAV 1.7575 (dd -14.29%) · Bench NAV 1.7898

### 2024-03

score 2024-03-30 (cutoff 2024-03-30T23:59:59+00:00) → exec 2024-04-02 · Eligible: **223** · Selected: **44** · Turnover (target): **15.3%** · Realized traded: 25.5% · Cost: 0.13%
Actions: BUY 4 · INCREASE 19 · DECREASE 21 · HOLD 0 · exits (SELL) 5 · carried-unselected 1 · cash-failed 0
- ENTERED (8): کپارس,سهرمز,ساروم,پتایر,سبجنو,پکرمان,کالا,کاما
- EXITED (5): کاسپین,ارفع,فگستر,زقیام,غپینو
- Retained: 36 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 22.9%
- Largest weight increases (vs prev target): [["کپارس", 0.0227], ["سهرمز", 0.0227], ["ساروم", 0.0227], ["پتایر", 0.0227], ["سبجنو", 0.0227]]
- Largest weight decreases (vs prev target): [["غپینو", -0.0244], ["زقیام", -0.0244], ["فگستر", -0.0244], ["ارفع", -0.0244], ["کاسپین", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["رمپنا", 8.53], ["شوینده", 4.51], ["ساروم", 3.97], ["بهپاک", 3.02], ["شغدیر", 2.87]]
- Largest score decreases (eligible overlap, descriptive): [["ارفع", -6.51], ["خراسان", -6.22], ["سرود", -5.79], ["دسینا", -4.0], ["شیران", -3.52]]
- Portfolio month: **-1.23%** · Benchmark: -1.20% · Excess: **-0.02%** · NAV 1.8653 (dd -9.04%) · Bench NAV 1.8954

### 2024-04

score 2024-04-30 (cutoff 2024-04-30T23:59:59+00:00) → exec 2024-05-01 · Eligible: **216** · Selected: **43** · Turnover (target): **33.6%** · Realized traded: 54.0% · Cost: 0.27%
Actions: BUY 13 · INCREASE 21 · DECREASE 9 · HOLD 0 · exits (SELL) 12 · carried-unselected 3 · cash-failed 0
- ENTERED (14): حتاید,سمازن,پرداخت,بمپنا,شیران,سهگمت,شگویا,شگل,ساربیل,بهپاک,سغرب,غبشهر,غپینو,سصوفی
- EXITED (15): دبالک,غدام,کپارس,خموتور,پاکشو,غمهرا,سهرمز,کپشیر,ساروم,پیزد,تایرا,چدن,کالا,کماسه,کلوند
- Retained: 29 · Holdings: 46 · Cash: 0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["حتاید", 0.0233], ["سمازن", 0.0233], ["پرداخت", 0.0233], ["بمپنا", 0.0233], ["شیران", 0.0233]]
- Largest weight decreases (vs prev target): [["کلوند", -0.0227], ["کماسه", -0.0227], ["کالا", -0.0227], ["چدن", -0.0227], ["تایرا", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["بهپاک", 20.95], ["ساربیل", 14.73], ["کهمدا", 12.82], ["بمپنا", 12.29], ["غبشهر", 12.22]]
- Largest score decreases (eligible overlap, descriptive): [["غدام", -28.84], ["دجابر", -12.18], ["کیمیا", -11.61], ["خمحرکه", -9.23], ["کسرا", -8.54]]
- Portfolio month: **-10.35%** · Benchmark: -10.31% · Excess: **-0.04%** · NAV 1.8424 (dd -10.16%) · Bench NAV 1.8725

### 2024-05

score 2024-05-29 (cutoff 2024-05-29T23:59:59+00:00) → exec 2024-06-01 · Eligible: **213** · Selected: **42** · Turnover (target): **11.1%** · Realized traded: 10.3% · Cost: 0.05%
Actions: BUY 1 · INCREASE 31 · DECREASE 10 · HOLD 0 · exits (SELL) 2 · carried-unselected 3 · cash-failed 0
- ENTERED (4): دبالک,ساروم,خزامیا,کماسه
- EXITED (5): دجابر,سآبیک,شگویا,پخش,شگل
- Retained: 38 · Holdings: 45 · Cash: 0.0% · Top-5 weight: 11.9% · Top-10 weight: 23.8%
- Largest weight increases (vs prev target): [["دبالک", 0.0238], ["ساروم", 0.0238], ["خزامیا", 0.0238], ["کماسه", 0.0238], ["غدیس", 0.0006]]
- Largest weight decreases (vs prev target): [["شگل", -0.0233], ["پخش", -0.0233], ["شگویا", -0.0233], ["سآبیک", -0.0233], ["دجابر", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["شپدیس", 10.96], ["خراسان", 8.87], ["غنوش", 7.37], ["ساربیل", 4.35], ["زاگرس", 3.9]]
- Largest score decreases (eligible overlap, descriptive): [["فگستر", -7.37], ["قاسم", -5.04], ["شگویا", -3.84], ["غشاذر", -3.67], ["سفانو", -3.02]]
- Portfolio month: **2.18%** · Benchmark: -1.68% · Excess: **3.86%** · NAV 1.6517 (dd -19.45%) · Bench NAV 1.6795

### 2024-06

score 2024-06-30 (cutoff 2024-06-30T23:59:59+00:00) → exec 2024-07-01 · Eligible: **206** · Selected: **41** · Turnover (target): **17.6%** · Realized traded: 30.8% · Cost: 0.15%
Actions: BUY 4 · INCREASE 27 · DECREASE 10 · HOLD 0 · exits (SELL) 7 · carried-unselected 1 · cash-failed 0
- ENTERED (7): کاسپین,سآبیک,پخش,شگل,شاملا,کلوند,قلرست
- EXITED (8): حتاید,زگلدشت,خزامیا,قنیشا,شکربن,سغرب,غبشهر,خنصیر
- Retained: 34 · Holdings: 42 · Cash: 0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.4%
- Largest weight increases (vs prev target): [["کاسپین", 0.0244], ["سآبیک", 0.0244], ["پخش", 0.0244], ["شگل", 0.0244], ["شاملا", 0.0244]]
- Largest weight decreases (vs prev target): [["خنصیر", -0.0238], ["غبشهر", -0.0238], ["سغرب", -0.0238], ["شکربن", -0.0238], ["قنیشا", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["غویتا", 9.73], ["دزهراوی", 6.35], ["دکپسول", 4.91], ["کسرا", 4.43], ["قلرست", 4.37]]
- Largest score decreases (eligible overlap, descriptive): [["خزامیا", -5.46], ["سیستم", -4.66], ["تپسی", -4.26], ["کاما", -4.16], ["سفانو", -4.09]]
- Portfolio month: **-0.78%** · Benchmark: -3.86% · Excess: **3.08%** · NAV 1.6878 (dd -17.69%) · Bench NAV 1.6514

### 2024-07

score 2024-07-31 (cutoff 2024-07-31T23:59:59+00:00) → exec 2024-08-03 · Eligible: **213** · Selected: **42** · Turnover (target): **31.0%** · Realized traded: 52.4% · Cost: 0.26%
Actions: BUY 12 · INCREASE 13 · DECREASE 17 · HOLD 0 · exits (SELL) 10 · carried-unselected 2 · cash-failed 0
- ENTERED (13): فباهنر,حتاید,غنوش,فایرا,خموتور,زگلدشت,سهرمز,انرژی,تپسی,سغرب,تایرا,دکپسول,رانفور
- EXITED (12): سرود,سکرد,سهگمت,پخش,شگل,حسینا,رمپنا,بهپاک,کماسه,کلوند,کاما,قلرست
- Retained: 29 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.0% · Top-10 weight: 23.9%
- Largest weight increases (vs prev target): [["فباهنر", 0.0238], ["حتاید", 0.0238], ["غنوش", 0.0238], ["فایرا", 0.0238], ["خموتور", 0.0238]]
- Largest weight decreases (vs prev target): [["قلرست", -0.0244], ["کاما", -0.0244], ["کلوند", -0.0244], ["کماسه", -0.0244], ["بهپاک", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["غپینو", 12.21], ["فایرا", 11.91], ["شبصیر", 11.01], ["شبریز", 10.12], ["تپسی", 9.52]]
- Largest score decreases (eligible overlap, descriptive): [["رمپنا", -22.31], ["کاما", -13.72], ["پخش", -13.19], ["حسینا", -8.81], ["شگویا", -8.79]]
- Portfolio month: **6.63%** · Benchmark: 4.80% · Excess: **1.83%** · NAV 1.6745 (dd -18.34%) · Bench NAV 1.5875

### 2024-08

score 2024-08-31 (cutoff 2024-08-31T23:59:59+00:00) → exec 2024-09-01 · Eligible: **219** · Selected: **43** · Turnover (target): **14.5%** · Realized traded: 28.8% · Cost: 0.14%
Actions: BUY 5 · INCREASE 18 · DECREASE 20 · HOLD 0 · exits (SELL) 6 · carried-unselected 0 · cash-failed 0
- ENTERED (7): شگل,فبیرا,شکربن,بوعلی,کماسه,قصفها,کاما
- EXITED (6): فایرا,خموتور,زگلدشت,انرژی,دلقما,سغرب
- Retained: 36 · Holdings: 43 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["شگل", 0.0233], ["فبیرا", 0.0233], ["شکربن", 0.0233], ["بوعلی", 0.0233], ["کماسه", 0.0233]]
- Largest weight decreases (vs prev target): [["سغرب", -0.0238], ["دلقما", -0.0238], ["انرژی", -0.0238], ["زگلدشت", -0.0238], ["خموتور", -0.0238]]
- Largest score increases (eligible overlap, descriptive): [["کرماشا", 5.65], ["فنوال", 4.83], ["قاسم", 4.69], ["فگستر", 4.27], ["کیمیا", 3.54]]
- Largest score decreases (eligible overlap, descriptive): [["دارو", -6.26], ["دلقما", -6.1], ["کزغال", -5.45], ["شدوص", -4.44], ["سقاین", -4.24]]
- Portfolio month: **5.82%** · Benchmark: 7.15% · Excess: **-1.33%** · NAV 1.7856 (dd -12.93%) · Bench NAV 1.6637

### 2024-09

score 2024-09-30 (cutoff 2024-09-30T23:59:59+00:00) → exec 2024-10-01 · Eligible: **205** · Selected: **41** · Turnover (target): **15.0%** · Realized traded: 15.8% · Cost: 0.08%
Actions: BUY 4 · INCREASE 29 · DECREASE 8 · HOLD 0 · exits (SELL) 3 · carried-unselected 3 · cash-failed 0
- ENTERED (4): فایرا,زگلدشت,غبشهر,خودرو
- EXITED (6): سشرق,فبیرا,تپسی,غاذر,سپیدار,قصفها
- Retained: 37 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 12.3% · Top-10 weight: 24.5%
- Largest weight increases (vs prev target): [["فایرا", 0.0244], ["زگلدشت", 0.0244], ["غبشهر", 0.0244], ["خودرو", 0.0244], ["فباهنر", 0.0011]]
- Largest weight decreases (vs prev target): [["قصفها", -0.0233], ["سپیدار", -0.0233], ["غاذر", -0.0233], ["تپسی", -0.0233], ["فبیرا", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["شوینده", 6.41], ["فاراک", 4.78], ["پرداخت", 3.73], ["غویتا", 3.71], ["غشان", 2.88]]
- Largest score decreases (eligible overlap, descriptive): [["شاملا", -5.44], ["سشرق", -4.34], ["سغرب", -3.33], ["کطبس", -2.88], ["سمازن", -2.45]]
- Portfolio month: **-3.98%** · Benchmark: -4.68% · Excess: **0.70%** · NAV 1.8896 (dd -7.85%) · Bench NAV 1.7826

### 2024-10

score 2024-10-30 (cutoff 2024-10-30T23:59:59+00:00) → exec 2024-11-02 · Eligible: **218** · Selected: **43** · Turnover (target): **28.8%** · Realized traded: 48.0% · Cost: 0.24%
Actions: BUY 11 · INCREASE 11 · DECREASE 21 · HOLD 0 · exits (SELL) 10 · carried-unselected 2 · cash-failed 0
- ENTERED (14): سشرق,سهگمت,تپسی,قنیشا,غاذر,دسینا,زکشت,قرن,غمایه,دقاضی,سپیدار,قصفها,زبینا,کیمیاتک
- EXITED (12): دبالک,کهمدا,بمپنا,شیران,افق,شگل,شاملا,غبشهر,پکرمان,خودرو,کماسه,کاما
- Retained: 29 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 11.8% · Top-10 weight: 23.5%
- Largest weight increases (vs prev target): [["سشرق", 0.0233], ["سهگمت", 0.0233], ["تپسی", 0.0233], ["قنیشا", 0.0233], ["غاذر", 0.0233]]
- Largest weight decreases (vs prev target): [["کاما", -0.0244], ["کماسه", -0.0244], ["خودرو", -0.0244], ["پکرمان", -0.0244], ["غبشهر", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["شستا", 14.27], ["قنیشا", 8.63], ["غفارس", 6.73], ["بموتو", 6.53], ["فزر", 6.09]]
- Largest score decreases (eligible overlap, descriptive): [["دبالک", -19.21], ["کهمدا", -17.7], ["تپمپی", -13.15], ["وسپه", -12.09], ["پکویر", -11.08]]
- Portfolio month: **15.88%** · Benchmark: 16.41% · Excess: **-0.53%** · NAV 1.8144 (dd -11.52%) · Bench NAV 1.6993

### 2024-11

score 2024-11-30 (cutoff 2024-11-30T23:59:59+00:00) → exec 2024-12-01 · Eligible: **221** · Selected: **44** · Turnover (target): **19.3%** · Realized traded: 38.4% · Cost: 0.19%
Actions: BUY 7 · INCREASE 16 · DECREASE 21 · HOLD 0 · exits (SELL) 8 · carried-unselected 0 · cash-failed 0
- ENTERED (9): زفکا,کاذر,افق,فگستر,خزامیا,شاملا,زدشت,کالا,فاراک
- EXITED (8): غدیس,دسینا,بوعلی,زکشت,دکپسول,دقاضی,سپیدار,کیمیاتک
- Retained: 35 · Holdings: 44 · Cash: -0.0% · Top-5 weight: 11.4% · Top-10 weight: 22.8%
- Largest weight increases (vs prev target): [["زفکا", 0.0227], ["کاذر", 0.0227], ["افق", 0.0227], ["فگستر", 0.0227], ["خزامیا", 0.0227]]
- Largest weight decreases (vs prev target): [["کیمیاتک", -0.0233], ["سپیدار", -0.0233], ["دقاضی", -0.0233], ["دکپسول", -0.0233], ["زکشت", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["ارفع", 7.33], ["خزامیا", 7.13], ["کاذر", 5.24], ["غگل", 4.64], ["بهپاک", 4.52]]
- Largest score decreases (eligible overlap, descriptive): [["داسوه", -7.6], ["کیمیا", -6.92], ["دسینا", -6.56], ["فپنتا", -5.77], ["غدیس", -5.67]]
- Portfolio month: **11.70%** · Benchmark: 12.39% · Excess: **-0.69%** · NAV 2.1025 (dd 0.00%) · Bench NAV 1.9781

### 2024-12

score 2024-12-31 (cutoff 2024-12-31T23:59:59+00:00) → exec 2025-01-01 · Eligible: **215** · Selected: **43** · Turnover (target): **25.1%** · Realized traded: 41.3% · Cost: 0.21%
Actions: BUY 9 · INCREASE 17 · DECREASE 17 · HOLD 0 · exits (SELL) 8 · carried-unselected 2 · cash-failed 0
- ENTERED (9): غدیس,خموتور,دلقما,پکرمان,تلیسه,زکشت,شسپا,کماسه,سپیدار
- EXITED (10): غکورش,سمازن,کاسپین,سآبیک,ساربیل,سبجنو,غاذر,خبهمن,فاراک,زبینا
- Retained: 34 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.3%
- Largest weight increases (vs prev target): [["غدیس", 0.0233], ["خموتور", 0.0233], ["دلقما", 0.0233], ["پکرمان", 0.0233], ["تلیسه", 0.0233]]
- Largest weight decreases (vs prev target): [["زبینا", -0.0227], ["فاراک", -0.0227], ["خبهمن", -0.0227], ["غاذر", -0.0227], ["سبجنو", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["دلقما", 10.42], ["قلرست", 6.51], ["کسرا", 6.2], ["کچاد", 4.58], ["سپیدار", 4.33]]
- Largest score decreases (eligible overlap, descriptive): [["کیمیا", -8.46], ["چکاپا", -7.76], ["قنیشا", -4.81], ["خبهمن", -4.44], ["ساربیل", -4.43]]
- Portfolio month: **5.14%** · Benchmark: 2.35% · Excess: **2.78%** · NAV 2.3484 (dd 0.00%) · Bench NAV 2.2231

### 2025-01

score 2025-01-29 (cutoff 2025-01-29T23:59:59+00:00) → exec 2025-02-01 · Eligible: **216** · Selected: **43** · Turnover (target): **30.9%** · Realized traded: 48.5% · Cost: 0.24%
Actions: BUY 11 · INCREASE 18 · DECREASE 14 · HOLD 0 · exits (SELL) 10 · carried-unselected 3 · cash-failed 0
- ENTERED (13): نوری,غکورش,کاسپین,حسینا,انرژی,شدوص,ساربیل,سباقر,غاذر,فنوال,خبهمن,فاراک,بپیوند
- EXITED (13): غدیس,غنوش,زفکا,سشرق,شمواد,کاذر,سهرمز,شکربن,پکرمان,زدشت,غمایه,کماسه,قصفها
- Retained: 30 · Holdings: 46 · Cash: 0.0% · Top-5 weight: 11.9% · Top-10 weight: 23.6%
- Largest weight increases (vs prev target): [["نوری", 0.0233], ["غکورش", 0.0233], ["کاسپین", 0.0233], ["حسینا", 0.0233], ["انرژی", 0.0233]]
- Largest weight decreases (vs prev target): [["قصفها", -0.0233], ["کماسه", -0.0233], ["غمایه", -0.0233], ["زدشت", -0.0233], ["پکرمان", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["چکارن", 10.52], ["حسینا", 9.85], ["خبهمن", 9.7], ["وتوشه", 7.84], ["بپیوند", 7.72]]
- Largest score decreases (eligible overlap, descriptive): [["سشرق", -7.93], ["برکت", -7.13], ["سرود", -7.01], ["کگل", -6.91], ["زبینا", -6.37]]
- Portfolio month: **-0.44%** · Benchmark: -2.30% · Excess: **1.86%** · NAV 2.4690 (dd 0.00%) · Bench NAV 2.2754

### 2025-02

score 2025-02-26 (cutoff 2025-02-26T23:59:59+00:00) → exec 2025-03-01 · Eligible: **212** · Selected: **42** · Turnover (target): **20.5%** · Realized traded: 19.9% · Cost: 0.10%
Actions: BUY 5 · INCREASE 26 · DECREASE 11 · HOLD 0 · exits (SELL) 4 · carried-unselected 5 · cash-failed 0
- ENTERED (7): غنوش,دجابر,شیران,سهرمز,آریا,کماسه,دفرا
- EXITED (8): سهگمت,شدوص,دلقما,تلیسه,تایرا,فنوال,شسپا,سپیدار
- Retained: 35 · Holdings: 47 · Cash: -0.0% · Top-5 weight: 11.9% · Top-10 weight: 23.8%
- Largest weight increases (vs prev target): [["غنوش", 0.0238], ["دجابر", 0.0238], ["شیران", 0.0238], ["سهرمز", 0.0238], ["آریا", 0.0238]]
- Largest weight decreases (vs prev target): [["سپیدار", -0.0233], ["شسپا", -0.0233], ["فنوال", -0.0233], ["تایرا", -0.0233], ["تلیسه", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["کیمیا", 10.0], ["دارو", 6.76], ["دسینا", 6.25], ["قلرست", 6.17], ["شکام", 5.23]]
- Largest score decreases (eligible overlap, descriptive): [["شمس", -8.29], ["سقاین", -7.75], ["کرماشا", -6.62], ["سغرب", -5.48], ["زشگزا", -4.4]]
- Portfolio month: **-4.27%** · Benchmark: -4.31% · Excess: **0.04%** · NAV 2.4581 (dd -0.44%) · Bench NAV 2.2229

### 2025-03

score 2025-03-30 (cutoff 2025-03-30T23:59:59+00:00) → exec 2025-04-05 · Eligible: **220** · Selected: **44** · Turnover (target): **15.3%** · Realized traded: 12.8% · Cost: 0.06%
Actions: BUY 3 · INCREASE 25 · DECREASE 16 · HOLD 0 · exits (SELL) 2 · carried-unselected 4 · cash-failed 0
- ENTERED (6): سمازن,دلقما,دسینا,تایرا,فنوال,کاما
- EXITED (4): نوری,حسینا,غپینو,دفرا
- Retained: 38 · Holdings: 48 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 23.0%
- Largest weight increases (vs prev target): [["سمازن", 0.0227], ["دلقما", 0.0227], ["دسینا", 0.0227], ["تایرا", 0.0227], ["فنوال", 0.0227]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0238], ["غپینو", -0.0238], ["حسینا", -0.0238], ["نوری", -0.0238], ["بپیوند", -0.0011]]
- Largest score increases (eligible overlap, descriptive): [["غکورش", 15.12], ["فجر", 6.53], ["رمپنا", 5.07], ["داسوه", 3.86], ["غمینو", 3.69]]
- Largest score decreases (eligible overlap, descriptive): [["کحافظ", -2.78], ["دفرا", -2.42], ["غشصفا", -2.36], ["غمهرا", -1.95], ["شاراک", -1.75]]
- Portfolio month: **19.56%** · Benchmark: 16.12% · Excess: **3.44%** · NAV 2.3533 (dd -4.69%) · Bench NAV 2.1271

### 2025-04

score 2025-04-30 (cutoff 2025-04-30T23:59:59+00:00) → exec 2025-05-03 · Eligible: **222** · Selected: **44** · Turnover (target): **38.0%** · Realized traded: 67.3% · Cost: 0.34%
Actions: BUY 14 · INCREASE 14 · DECREASE 16 · HOLD 0 · exits (SELL) 16 · carried-unselected 2 · cash-failed 0
- ENTERED (17): غدیس,نوری,غشاذر,غشصفا,کهمدا,بمپنا,سآبیک,غفارس,شگل,سشمال,غویتا,بهپاک,غشان,غبشهر,غپینو,دعبید,سپیدار
- EXITED (17): فباهنر,فایرا,خموتور,زگلدشت,ساروم,فگستر,خزامیا,شاملا,دسینا,زکشت,قرن,تایرا,فنوال,کخاک,کماسه,کاما,رانفور
- Retained: 27 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.1%
- Largest weight increases (vs prev target): [["غدیس", 0.0227], ["نوری", 0.0227], ["غشاذر", 0.0227], ["غشصفا", 0.0227], ["کهمدا", 0.0227]]
- Largest weight decreases (vs prev target): [["رانفور", -0.0227], ["کاما", -0.0227], ["کماسه", -0.0227], ["کخاک", -0.0227], ["فنوال", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["بهپاک", 18.57], ["شیران", 17.26], ["کهمدا", 15.67], ["سمازن", 15.47], ["غبشهر", 15.4]]
- Largest score decreases (eligible overlap, descriptive): [["شوینده", -15.5], ["خزامیا", -11.29], ["رمپنا", -7.52], ["حکشتی", -7.07], ["کسرا", -7.02]]
- Portfolio month: **4.69%** · Benchmark: 2.70% · Excess: **2.00%** · NAV 2.8136 (dd 0.00%) · Bench NAV 2.4699

### 2025-05

score 2025-05-31 (cutoff 2025-05-31T23:59:59+00:00) → exec 2025-06-01 · Eligible: **215** · Selected: **43** · Turnover (target): **20.6%** · Realized traded: 27.6% · Cost: 0.14%
Actions: BUY 6 · INCREASE 28 · DECREASE 9 · HOLD 0 · exits (SELL) 6 · carried-unselected 3 · cash-failed 0
- ENTERED (8): فباهنر,حسینا,ددانا,ساروم,فگستر,شپدیس,قرن,دکپسول
- EXITED (9): نوری,غشاذر,دجابر,شیران,سهرمز,شگل,سشمال,فاراک,سپیدار
- Retained: 35 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 11.8% · Top-10 weight: 23.4%
- Largest weight increases (vs prev target): [["فباهنر", 0.0233], ["حسینا", 0.0233], ["ددانا", 0.0233], ["ساروم", 0.0233], ["فگستر", 0.0233]]
- Largest weight decreases (vs prev target): [["سپیدار", -0.0227], ["فاراک", -0.0227], ["سشمال", -0.0227], ["شگل", -0.0227], ["سهرمز", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["غدام", 13.44], ["بمپنا", 12.5], ["ساربیل", 11.0], ["دبالک", 9.89], ["شمس", 8.86]]
- Largest score decreases (eligible overlap, descriptive): [["شستا", -11.64], ["شگل", -11.22], ["بموتو", -5.81], ["قلرست", -5.33], ["بهپاک", -4.59]]
- Portfolio month: **-10.77%** · Benchmark: -10.77% · Excess: **0.01%** · NAV 2.9456 (dd 0.00%) · Bench NAV 2.5365

### 2025-06

score 2025-06-30 (cutoff 2025-06-30T23:59:59+00:00) → exec 2025-07-01 · Eligible: **221** · Selected: **44** · Turnover (target): **14.0%** · Realized traded: 22.7% · Cost: 0.11%
Actions: BUY 4 · INCREASE 23 · DECREASE 17 · HOLD 0 · exits (SELL) 5 · carried-unselected 1 · cash-failed 0
- ENTERED (6): غشاذر,دزهراوی,سهگمت,شاملا,سپیدار,دفرا
- EXITED (5): ددانا,آریا,شپدیس,کالا,دکپسول
- Retained: 38 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 11.7% · Top-10 weight: 23.0%
- Largest weight increases (vs prev target): [["غشاذر", 0.0227], ["دزهراوی", 0.0227], ["سهگمت", 0.0227], ["شاملا", 0.0227], ["سپیدار", 0.0227]]
- Largest weight decreases (vs prev target): [["دکپسول", -0.0233], ["کالا", -0.0233], ["شپدیس", -0.0233], ["آریا", -0.0233], ["ددانا", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["رمپنا", 6.37], ["سهگمت", 6.24], ["چخزر", 5.84], ["خراسان", 5.59], ["پاسا", 4.13]]
- Largest score decreases (eligible overlap, descriptive): [["قنیشا", -6.52], ["سیستم", -4.52], ["شاراک", -4.5], ["تایرا", -4.04], ["غاذر", -3.97]]
- Portfolio month: **-6.41%** · Benchmark: -6.68% · Excess: **0.26%** · NAV 2.6285 (dd -10.77%) · Bench NAV 2.2633

### 2025-07

score 2025-07-30 (cutoff 2025-07-30T23:59:59+00:00) → exec 2025-08-02 · Eligible: **206** · Selected: **41** · Turnover (target): **31.2%** · Realized traded: 42.3% · Cost: 0.21%
Actions: BUY 10 · INCREASE 25 · DECREASE 6 · HOLD 0 · exits (SELL) 10 · carried-unselected 4 · cash-failed 0
- ENTERED (10): شرانل,سکرد,نان,پخش,ددانا,پیزد,دسینا,فنوال,کالا,فاراک
- EXITED (13): فباهنر,غنوش,کاسپین,افق,حسینا,انرژی,تپسی,پتایر,قنیشا,سیستم,شاملا,خبهمن,سپیدار
- Retained: 31 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 12.6% · Top-10 weight: 24.8%
- Largest weight increases (vs prev target): [["شرانل", 0.0244], ["سکرد", 0.0244], ["نان", 0.0244], ["پخش", 0.0244], ["ددانا", 0.0244]]
- Largest weight decreases (vs prev target): [["سپیدار", -0.0227], ["خبهمن", -0.0227], ["شاملا", -0.0227], ["سیستم", -0.0227], ["قنیشا", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["دلقما", 21.12], ["پخش", 9.87], ["قاسم", 9.55], ["کپرور", 8.63], ["غمینو", 8.36]]
- Largest score decreases (eligible overlap, descriptive): [["خبهمن", -16.35], ["غنوش", -11.39], ["سپیدار", -10.42], ["قنیشا", -8.53], ["ذوب", -7.81]]
- Portfolio month: **-4.55%** · Benchmark: -3.84% · Excess: **-0.71%** · NAV 2.4599 (dd -16.49%) · Bench NAV 2.1121

### 2025-08

score 2025-08-31 (cutoff 2025-08-31T23:59:59+00:00) → exec 2025-09-02 · Eligible: **223** · Selected: **44** · Turnover (target): **17.6%** · Realized traded: 30.2% · Cost: 0.15%
Actions: BUY 6 · INCREASE 15 · DECREASE 23 · HOLD 0 · exits (SELL) 6 · carried-unselected 1 · cash-failed 0
- ENTERED (8): کاسپین,دارو,پاکشو,شیران,شگل,چکارن,دکپسول,کاما
- EXITED (5): شرانل,سکرد,پیزد,قرن,کالا
- Retained: 36 · Holdings: 45 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 22.9%
- Largest weight increases (vs prev target): [["کاسپین", 0.0227], ["دارو", 0.0227], ["پاکشو", 0.0227], ["شیران", 0.0227], ["شگل", 0.0227]]
- Largest weight decreases (vs prev target): [["کالا", -0.0244], ["قرن", -0.0244], ["پیزد", -0.0244], ["سکرد", -0.0244], ["شرانل", -0.0244]]
- Largest score increases (eligible overlap, descriptive): [["خمحرکه", 9.15], ["شگل", 8.36], ["سقاین", 6.4], ["پاکشو", 6.11], ["داسوه", 5.83]]
- Largest score decreases (eligible overlap, descriptive): [["زگلدشت", -4.97], ["شاملا", -4.73], ["سپیدار", -3.78], ["انرژی", -3.44], ["فولاد", -3.32]]
- Portfolio month: **5.58%** · Benchmark: 6.88% · Excess: **-1.29%** · NAV 2.3481 (dd -20.29%) · Bench NAV 2.0311

### 2025-09

score 2025-09-30 (cutoff 2025-09-30T23:59:59+00:00) → exec 2025-10-01 · Eligible: **225** · Selected: **45** · Turnover (target): **24.9%** · Realized traded: 36.4% · Cost: 0.18%
Actions: BUY 10 · INCREASE 15 · DECREASE 20 · HOLD 0 · exits (SELL) 7 · carried-unselected 3 · cash-failed 0
- ENTERED (10): دبالک,دزاگرس,رمپنا,سشمال,پیزد,قاسم,کپرور,قرن,کالا,قلرست
- EXITED (9): غدیس,پرداخت,سآبیک,غویتا,فگستر,دعبید,فاراک,دکپسول,دفرا
- Retained: 35 · Holdings: 48 · Cash: -0.0% · Top-5 weight: 11.2% · Top-10 weight: 22.4%
- Largest weight increases (vs prev target): [["دبالک", 0.0222], ["دزاگرس", 0.0222], ["رمپنا", 0.0222], ["سشمال", 0.0222], ["پیزد", 0.0222]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0227], ["دکپسول", -0.0227], ["فاراک", -0.0227], ["دعبید", -0.0227], ["فگستر", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["کاما", 24.49], ["رمپنا", 15.45], ["قلرست", 7.52], ["دزاگرس", 6.56], ["کفرا", 4.55]]
- Largest score decreases (eligible overlap, descriptive): [["پرداخت", -9.68], ["شکربن", -5.3], ["غدیس", -4.01], ["سآبیک", -3.57], ["شمس", -3.4]]
- Portfolio month: **17.82%** · Benchmark: 16.85% · Excess: **0.97%** · NAV 2.4792 (dd -15.83%) · Bench NAV 2.1708

### 2025-10

score 2025-10-29 (cutoff 2025-10-29T23:59:59+00:00) → exec 2025-11-01 · Eligible: **227** · Selected: **45** · Turnover (target): **34.6%** · Realized traded: 60.8% · Cost: 0.30%
Actions: BUY 13 · INCREASE 19 · DECREASE 13 · HOLD 0 · exits (SELL) 14 · carried-unselected 2 · cash-failed 0
- ENTERED (15): غدیس,غدام,شرانل,دابور,شبصیر,پاسا,کپشیر,افق,غویتا,فگستر,سغرب,شکام,سقاین,دعبید,کطبس
- EXITED (15): غشاذر,حتاید,دبالک,غشصفا,کهمدا,پکویر,بمپنا,شیران,غفارس,ددانا,سشمال,بهپاک,پیزد,قاسم,غشان
- Retained: 30 · Holdings: 47 · Cash: 0.0% · Top-5 weight: 11.1% · Top-10 weight: 22.3%
- Largest weight increases (vs prev target): [["غدیس", 0.0222], ["غدام", 0.0222], ["شرانل", 0.0222], ["دابور", 0.0222], ["شبصیر", 0.0222]]
- Largest weight decreases (vs prev target): [["غشان", -0.0222], ["قاسم", -0.0222], ["پیزد", -0.0222], ["بهپاک", -0.0222], ["سشمال", -0.0222]]
- Largest score increases (eligible overlap, descriptive): [["شوینده", 19.62], ["حکشتی", 13.97], ["شستا", 10.96], ["غدام", 8.79], ["شبصیر", 7.93]]
- Largest score decreases (eligible overlap, descriptive): [["بهپاک", -17.81], ["بمپنا", -17.26], ["کهمدا", -14.36], ["سمازن", -14.26], ["تپمپی", -12.68]]
- Portfolio month: **4.52%** · Benchmark: 3.76% · Excess: **0.75%** · NAV 2.9209 (dd -0.84%) · Bench NAV 2.5365

### 2025-11

score 2025-11-30 (cutoff 2025-11-30T23:59:59+00:00) → exec 2025-12-01 · Eligible: **226** · Selected: **45** · Turnover (target): **20.0%** · Realized traded: 22.4% · Cost: 0.11%
Actions: BUY 7 · INCREASE 25 · DECREASE 13 · HOLD 0 · exits (SELL) 5 · carried-unselected 4 · cash-failed 0
- ENTERED (8): شیران,سآبیک,سهرمز,خراسان,عالیس,پیزد,خمحرکه,خودرو
- EXITED (8): غدیس,دابور,سمازن,سهگمت,سباقر,سغرب,شکام,دعبید
- Retained: 37 · Holdings: 49 · Cash: -0.0% · Top-5 weight: 11.6% · Top-10 weight: 22.7%
- Largest weight increases (vs prev target): [["شیران", 0.0222], ["سآبیک", 0.0222], ["سهرمز", 0.0222], ["خراسان", 0.0222], ["عالیس", 0.0222]]
- Largest weight decreases (vs prev target): [["دعبید", -0.0222], ["شکام", -0.0222], ["سغرب", -0.0222], ["سباقر", -0.0222], ["سهگمت", -0.0222]]
- Largest score increases (eligible overlap, descriptive): [["کاذر", 6.96], ["غشوکو", 6.39], ["شمس", 5.53], ["خمحرکه", 4.53], ["کیمیا", 4.14]]
- Largest score decreases (eligible overlap, descriptive): [["کاما", -4.76], ["کپرور", -4.64], ["ارفع", -4.58], ["غبشهر", -4.19], ["سبجنو", -3.89]]
- Portfolio month: **19.10%** · Benchmark: 16.17% · Excess: **2.93%** · NAV 3.0529 (dd 0.00%) · Bench NAV 2.6320

### 2025-12

score 2025-12-31 (cutoff 2025-12-31T23:59:59+00:00) → exec 2026-01-04 · Eligible: **224** · Selected: **44** · Turnover (target): **23.9%** · Realized traded: 37.9% · Cost: 0.19%
Actions: BUY 6 · INCREASE 26 · DECREASE 12 · HOLD 0 · exits (SELL) 9 · carried-unselected 2 · cash-failed 0
- ENTERED (10): شپارس,سهگمت,فملی,تپسی,قنیشا,سباقر,کیمیا,شپدیس,دعبید,دفرا
- EXITED (11): دزاگرس,پاسا,کپشیر,افق,شگل,عالیس,ساروم,فگستر,پیزد,سقاین,کپرور
- Retained: 34 · Holdings: 46 · Cash: -0.0% · Top-5 weight: 11.8% · Top-10 weight: 23.2%
- Largest weight increases (vs prev target): [["شپارس", 0.0227], ["سهگمت", 0.0227], ["فملی", 0.0227], ["تپسی", 0.0227], ["قنیشا", 0.0227]]
- Largest weight decreases (vs prev target): [["کپرور", -0.0222], ["سقاین", -0.0222], ["پیزد", -0.0222], ["فگستر", -0.0222], ["ساروم", -0.0222]]
- Largest score increases (eligible overlap, descriptive): [["شپدیس", 10.28], ["فملی", 7.43], ["قنیشا", 6.09], ["فایرا", 5.81], ["کنور", 5.75]]
- Largest score decreases (eligible overlap, descriptive): [["پاسا", -5.16], ["غکورش", -4.62], ["غمهرا", -4.5], ["شیران", -4.48], ["زاگرس", -3.53]]
- Portfolio month: **-5.71%** · Benchmark: -6.78% · Excess: **1.06%** · NAV 3.6360 (dd 0.00%) · Bench NAV 3.0577

### 2026-01

score 2026-01-31 (cutoff 2026-01-31T23:59:59+00:00) → exec 2026-02-01 · Eligible: **219** · Selected: **43** · Turnover (target): **41.4%** · Realized traded: 63.8% · Cost: 0.32%
Actions: BUY 15 · INCREASE 22 · DECREASE 6 · HOLD 0 · exits (SELL) 14 · carried-unselected 4 · cash-failed 0
- ENTERED (17): کمنگنز,دزاگرس,سشرق,فایرا,دابور,شگویا,کپشیر,افق,آردینه,زشگزا,سبجنو,زقیام,شکام,شبریز,تلیسه,سقاین,پارس
- EXITED (18): شرانل,شبصیر,کاسپین,پاکشو,شیران,سآبیک,سهرمز,نان,خراسان,تپسی,غویتا,ساربیل,خمحرکه,غبشهر,قرن,دعبید,خودرو,بپیوند
- Retained: 26 · Holdings: 47 · Cash: -0.0% · Top-5 weight: 12.1% · Top-10 weight: 23.8%
- Largest weight increases (vs prev target): [["کمنگنز", 0.0233], ["دزاگرس", 0.0233], ["سشرق", 0.0233], ["فایرا", 0.0233], ["دابور", 0.0233]]
- Largest weight decreases (vs prev target): [["بپیوند", -0.0227], ["خودرو", -0.0227], ["دعبید", -0.0227], ["قرن", -0.0227], ["غبشهر", -0.0227]]
- Largest score increases (eligible overlap, descriptive): [["شگویا", 9.94], ["شبریز", 8.69], ["سپید", 8.31], ["سبجنو", 8.31], ["سشرق", 8.21]]
- Largest score decreases (eligible overlap, descriptive): [["کاما", -11.11], ["خمحرکه", -9.22], ["تپسی", -8.78], ["شرانل", -8.42], ["خبهمن", -7.25]]
- Portfolio month: **20.82%** · Benchmark: 18.13% · Excess: **2.69%** · NAV 3.4283 (dd -5.71%) · Bench NAV 2.8504

### 2026-05

score 2026-05-31 (cutoff 2026-05-31T23:59:59+00:00) → exec 2026-06-01 · Eligible: **204** · Selected: **40** · Turnover (target): **54.4%** · Realized traded: 91.3% · Cost: 0.46%
Actions: BUY 19 · INCREASE 17 · DECREASE 4 · HOLD 0 · exits (SELL) 21 · carried-unselected 5 · cash-failed 0
- ENTERED (20): غشاذر,غشصفا,کهمدا,سمازن,شمواد,دجابر,پاکشو,غفارس,شگل,غویتا,ساربیل,بهپاک,داسوه,قاسم,غشان,سغرب,شمس,غبشهر,دعبید,مادیرا
- EXITED (23): شپارس,غدام,کمنگنز,دزاگرس,فایرا,شگویا,کپشیر,فملی,آردینه,زشگزا,قنیشا,زقیام,دسینا,شکام,کیمیا,شپدیس,تلیسه,فنوال,کالا,کطبس,پارس,قلرست,دفرا
- Retained: 20 · Holdings: 45 · Cash: 0.0% · Top-5 weight: 12.5% · Top-10 weight: 24.9%
- Largest weight increases (vs prev target): [["غشاذر", 0.025], ["غشصفا", 0.025], ["کهمدا", 0.025], ["سمازن", 0.025], ["شمواد", 0.025]]
- Largest weight decreases (vs prev target): [["دفرا", -0.0233], ["قلرست", -0.0233], ["پارس", -0.0233], ["کطبس", -0.0233], ["کالا", -0.0233]]
- Largest score increases (eligible overlap, descriptive): [["سهگمت", 29.73], ["کهمدا", 25.69], ["داسوه", 18.73], ["شگل", 18.42], ["غبشهر", 18.08]]
- Largest score decreases (eligible overlap, descriptive): [["غدام", -24.24], ["شستا", -17.9], ["قنیشا", -13.02], ["سهرمز", -10.37], ["تایرا", -8.67]]
- Portfolio month: **36.29%** · Benchmark: 26.97% · Excess: **9.32%** · NAV 4.1420 (dd 0.00%) · Bench NAV 3.3672

### 2026-06

score 2026-06-30 (cutoff 2026-06-30T23:59:59+00:00) → exec 2026-07-01 · Eligible: **209** · Selected: **41** · Turnover (target): **22.9%** · Realized traded: 37.6% · Cost: 0.19%
Actions: BUY 6 · INCREASE 21 · DECREASE 14 · HOLD 0 · exits (SELL) 8 · carried-unselected 2 · cash-failed 0
- ENTERED (9): شبهرن,دزاگرس,کپارس,ددانا,کرماشا,زقیام,دسینا,شپدیس,کالا
- EXITED (8): پاکشو,پخش,افق,ساربیل,سغرب,چکارن,سصوفی,کاما
- Retained: 32 · Holdings: 43 · Cash: -0.0% · Top-5 weight: 12.2% · Top-10 weight: 24.4%
- Largest weight increases (vs prev target): [["شبهرن", 0.0244], ["دزاگرس", 0.0244], ["کپارس", 0.0244], ["ددانا", 0.0244], ["کرماشا", 0.0244]]
- Largest weight decreases (vs prev target): [["کاما", -0.025], ["سصوفی", -0.025], ["چکارن", -0.025], ["سغرب", -0.025], ["ساربیل", -0.025]]
- Largest score increases (eligible overlap, descriptive): [["دلقما", 26.2], ["ددانا", 10.71], ["کفرا", 5.62], ["دسینا", 5.53], ["دارو", 4.45]]
- Largest score decreases (eligible overlap, descriptive): [["دبالک", -10.09], ["ساربیل", -9.71], ["غنوش", -6.63], ["سغرب", -6.1], ["چکارن", -4.37]]
- Portfolio month: **—** · Benchmark: — · Excess: **—** · NAV 5.6451 (dd 0.00%) · Bench NAV 4.2755

## 5. Holding duration (spells of continuous Top20 membership)

- Total spells: **583** across **171** unique securities
- Spell length: median **2 months** · p25 1 · p75 5 · p90 9 · mean 4.3 · max 56
- Longest spells: غمینو 56m (2021-07→2026-06, still held at replay end); غاذر 51m (2021-09→2026-06, still held at replay end); غکورش 49m (2021-12→2026-06, still held at replay end); غپینو 38m (2022-12→2026-06, still held at replay end); دلقما 35m (2021-07→2024-07); رمپنا 35m (2021-07→2024-06); دجابر 34m (2021-07→2024-04); سیستم 24m (2023-07→2025-06); سصوفی 23m (2024-04→2026-05); پکویر 23m (2023-11→2025-09)

Per-security detail: `security_holding_history.csv` (every security × month: score, rank, selected, target weight, action, holding age) — one row per security × decision month.

## 6. Top20 recurrence (descriptive only — no turnover buffers proposed)

- Most frequently in Top20: غمینو (56 mo, avg rank 2); غاذر (51 mo, avg rank 4); غکورش (50 mo, avg rank 8); دلقما (50 mo, avg rank 9); غپینو (50 mo, avg rank 13); رمپنا (45 mo, avg rank 9); کاما (41 mo, avg rank 11); ساربیل (41 mo, avg rank 13); دجابر (39 mo, avg rank 8); سمازن (39 mo, avg rank 15); شمواد (37 mo, avg rank 18); سصوفی (36 mo, avg rank 25); کهمدا (35 mo, avg rank 13); غبشهر (31 mo, avg rank 18); کاسپین (31 mo, avg rank 23)
- Longest uninterrupted streaks: غمینو (52 mo); دجابر (34 mo); سیستم (28 mo); دلقما (25 mo); پکویر (23 mo); سصوفی (22 mo); رمپنا (21 mo); دتماد (20 mo); سفانو (17 mo); پرداخت (17 mo)
- Entered only once: **12** securities
- Repeated enterers/exitors (≥4 spells): **80** — ارفع (5 spells), افق (4 spells), بهپاک (6 spells), بوعلی (4 spells), بپیوند (6 spells), تلیسه (5 spells), تپمپی (4 spells), حتاید (4 spells), خبهمن (5 spells), خزامیا (5 spells), خمحرکه (4 spells), خموتور (5 spells)

## 7. Operational comparison: 2021–2023 vs 2024–2026 (descriptive only — no tuning)

| Metric | 2021–2023 | 2024–2026 |
|---|---|---|
| Decision months | 36 | 27 |
| Median eligible universe | 209 | 216 |
| Median selected | 41 | 43 |
| Mean eligible DQ | 0.897 | 0.935 |
| Median score std-dev | 5.9108 | 7.7987 |
| Median score p90−p10 | 11.9550 | 17.8420 |
| Avg target turnover | 32.5% | 25.1% |
| Avg realized traded fraction | 54.4% | 38.8% |
| Avg holdings | 38.6 | 45.4 |
| Avg monthly retention | 71.8% | 76.6% |

The eligible universe ramped once, mid-2021 (79 names in January to ~210 by September), and is essentially flat across both eras (median 209 vs 216). What actually differs after 2023: higher data quality (mean DQ 0.897 → 0.935), wider score dispersion (median per-month score std 5.91 → 7.80; p90−p10 12.0 → 17.8), lower turnover (avg target 32.5% → 25.1%; realized traded fraction 54.4% → 38.8%), and higher monthly retention (71.8% → 76.6%). Per the frozen rules nothing was tuned in response; this comparison is descriptive only.

## 8. NON_SHADOW_CURRENT_PREVIEW (not a shadow decision)

**`NON_SHADOW_CURRENT_PREVIEW`** — built from the latest REAL production score run `0d2e5bc7-fde1-4af3-87fa-f292376beb79` (as_of 2026-10-01, completed 2026-10-01T12:50:54.842877+03:30 Tehran, code `canonical-v1-dev+report-chain-ttm+direct-valuation+fiscal-anchor-cell`; the 2026-10-02 run `e5998f6d…` is excluded — the state file marks it a test fixture). This is **not** a frozen month-end Shadow decision: no paper orders were generated, the shadow clock was NOT started, and nothing was written to the live state.

- Eligible universe: **271** · selected top-20%: **54** · equal target weight 1.85% each

| # | symbol | ui_score | rank | DQ | target weight |
|---|---|---|---|---|---|
| 1 | کیمیا | 68.6100 | 1 | 1.000 | 1.85% |
| 2 | شسپا | 67.2300 | 2 | 1.000 | 1.85% |
| 3 | غاذر | 65.9700 | 3 | 1.000 | 1.85% |
| 4 | کاما | 65.8800 | 4 | 1.000 | 1.85% |
| 5 | سباقر | 62.8700 | 5 | 1.000 | 1.85% |
| 6 | شتران | 62.6800 | 6 | 1.000 | 1.85% |
| 7 | خراسان | 62.3700 | 7 | 1.000 | 1.85% |
| 8 | دقاضی | 62.2900 | 8 | 1.000 | 1.85% |
| 9 | فایرا | 61.8100 | 9 | 1.000 | 1.85% |
| 10 | دارو | 61.1200 | 10 | 1.000 | 1.85% |
| 11 | دلقما | 61.0200 | 11 | 1.000 | 1.85% |
| 12 | شمواد | 60.9300 | 12 | 1.000 | 1.85% |
| 13 | کاسپین | 59.9900 | 13 | 1.000 | 1.85% |
| 14 | شبصیر | 59.3900 | 14 | 1.000 | 1.85% |
| 15 | سقاین | 59.3100 | 15 | 1.000 | 1.85% |
| 16 | کمنگنز | 59.2300 | 16 | 1.000 | 1.85% |
| 17 | شبندر | 58.9700 | 17 | 1.000 | 1.85% |
| 18 | شپنا | 58.7700 | 18 | 1.000 | 1.85% |
| 19 | آردینه | 57.7300 | 19 | 1.000 | 1.85% |
| 20 | کرماشا | 57.7100 | 20 | 1.000 | 1.85% |
| 21 | فملی | 57.3200 | 21 | 1.000 | 1.85% |
| 22 | ارفع | 56.9600 | 22 | 1.000 | 1.85% |
| 23 | دیران | 56.8600 | 23 | 1.000 | 1.85% |
| 24 | شاراک | 56.7600 | 24 | 1.000 | 1.85% |
| 25 | زکشت | 56.3700 | 25 | 1.000 | 1.85% |
| 26 | غکورش | 56.0300 | 26 | 1.000 | 1.85% |
| 27 | غبشهر | 55.5000 | 27 | 1.000 | 1.85% |
| 28 | بهپاک | 55.4800 | 28 | 1.000 | 1.85% |
| 29 | ساروم | 55.3100 | 29 | 1.000 | 1.85% |
| 30 | شبهرن | 54.8800 | 30 | 1.000 | 1.85% |
| 31 | غپینو | 54.1400 | 31 | 1.000 | 1.85% |
| 32 | سبجنو | 53.9500 | 32 | 1.000 | 1.85% |
| 33 | زبینا | 53.8000 | 33 | 1.000 | 1.85% |
| 34 | شغدیر | 53.7200 | 34 | 1.000 | 1.85% |
| 35 | غمینو | 53.4300 | 35 | 1.000 | 1.85% |
| 36 | فنوال | 53.3200 | 36 | 1.000 | 1.85% |
| 37 | دفرا | 53.2900 | 37 | 1.000 | 1.85% |
| 38 | غویتا | 53.2900 | 38 | 1.000 | 1.85% |
| 39 | عالیس | 52.8900 | 39 | 1.000 | 1.85% |
| 40 | کلر | 51.5100 | 40 | 1.000 | 1.85% |
| 41 | شرانل | 51.4200 | 41 | 1.000 | 1.85% |
| 42 | پیزد | 51.4200 | 42 | 1.000 | 1.85% |
| 43 | کسرا | 51.3200 | 43 | 1.000 | 1.85% |
| 44 | کپارس | 50.9100 | 44 | 1.000 | 1.85% |
| 45 | شپدیس | 50.8700 | 45 | 1.000 | 1.85% |
| 46 | کهمدا | 50.2200 | 46 | 1.000 | 1.85% |
| 47 | جم پیلن3 | 50.0700 | 47 | 1.000 | 1.85% |
| 48 | کالا | 49.9300 | 48 | 1.000 | 1.85% |
| 49 | سصوفی | 49.9000 | 49 | 1.000 | 1.85% |
| 50 | دعبید | 49.4500 | 50 | 1.000 | 1.85% |
| 51 | کخاک | 49.1800 | 51 | 1.000 | 1.85% |
| 52 | کطبس | 49.1100 | 52 | 1.000 | 1.85% |
| 53 | زگلدشت | 48.9200 | 53 | 1.000 | 1.85% |
| 54 | تلیسه | 48.3100 | 54 | 1.000 | 1.85% |

## 9. Reproducibility & audit

- Determinism probe (content hashes): monthly CSV `c00f22a9abdcc1b3…`, targets `056e80963e08b546…`, trades `adca7fc9d50f8aa7…` — a re-run under a different PYTHONHASHSEED must reproduce these exactly (result recorded below).
- Determinism re-run (PYTHONHASHSEED=7): **IDENTICAL — byte-level reproducibility across PYTHONHASHSEED runs**
- Live state `portfolio_shadow/shadow_v1_state.json` byte-identical before/after: **True** (`63493408c6796c13…`); decisions = 0; SHADOW_FORWARD_CLOCK_STARTED = **NO**; REAL_MONEY_ORDERS_ENABLED = NO; BROKER_CONNECTION_ENABLED = NO
- Full machine-readable audit: `replay_state.json`; monthly row data: `shadow_replay_monthly.csv`; row-level decisions: `shadow_replay_targets.parquet`; realized trades: `shadow_replay_trades.parquet`; parity: `shadow_replay_parity.json`; per-security history: `security_holding_history.csv`; yearly: `shadow_replay_yearly.csv`.

---

**HISTORICAL_REPLAY_ONLY** — this replay does not replace the forward 12-month shadow period, does not constitute new validation, and does not change any frozen artifact, threshold, or rule.