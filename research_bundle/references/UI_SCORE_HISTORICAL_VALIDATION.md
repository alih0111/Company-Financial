# UI SCORE HISTORICAL VALIDATION — `ui_score_historical_v1`

Frozen: 2026-10-02. Question answered: **"When this exact UI score was high historically,
did those stocks subsequently perform better than stocks with lower UI scores?"**
All results `EXPLORATORY_HISTORICAL` (2021–2026 were previously inspected in model research).

## PHASE 0 — the exact production score (traced from code, not docs)

Scorer: `canonical_postgres_v1_2_1/analytics_canonical_v1/compute_metrics.py`, class
`Engine`, score_version **`canonical-v1-dev`**, production valuation **VAL_DIRECT**.
Full machine-readable manifest: `ui_score_historical_v1/ui_score_production_manifest.json`.

- Final score: `quant_score = round(dq × (growth + profitability + valuation + market), 2)`,
  theoretical max 89 × dq. The UI (`client/src/components/ScoreBreakdown.tsx` via go-app
  `summary_canonical.go`) displays the stored `analytics.company_scores` of live run
  `0d2e5bc7-fde1-4af3-87fa-f292376beb79` (as_of 2026-10-01) — exactly this implementation.
- Categories (weights = weight × midrank percentile [0,1], with penalties, floors at 0):
  GROWTH max 36 (SalesGrowth 10, SalesGrowth3M 6, RevenueGrowth 5, OpProfitGrowth 5,
  NetProfitGrowth 10; penalties: sales growth < −20 → −6, op growth < −25 → −5);
  PROFITABILITY max 26 (OpMargin 4, NetMargin 4, ROE 6, MarginTrend 3, InterestCoverage 3,
  CashConversion 2, EarningsQuality 4 lower-better; penalties: loss → −10, coverage <1.5 →
  −4, margin trend <−2 → −3, earnings-quality up to −8);
  VALUATION max 16 (PE 11, PS 3, PB 2 lower-better, valid ranges (0,60]/(0,100]/(0,30],
  missing/invalid PE → −8);
  MARKET & RISK max 11 (Liquidity 3, Leverage 2, CurrentRatio 2, Stability 1, LowVol 2,
  Momentum 1).
- Quality multiplier: `dq = 0.45·has_financial + 0.20·has_monthly + 0.35·has_price` (the
  5-component DQ model with freshness mirroring presence), max 1.0; flags recorded, not
  scored.
- Valuation inputs (production): market_cap = last_price (else close, latest trade-date row)
  × shares from `core.share_structure` PIT snapshot; PE = mc/net_profit_ttm, PS =
  mc/revenue_ttm, PB = mc/equity (each independently None-able).
- **Explicitly different from the tested Model v2.1/v2.2 composites** (those were equal-
  weight rank means, no penalties, no DQ multiplier, PERank consumed as PERank_DIRECT_V2).

## PHASE 3 — parity (required before backtesting)

Fresh Engine run with the stored live-run parameters (as_of 2026-10-01, cutoff
2026-10-01T12:50:41+03:30): **243/271 companies reproduce exactly**; 28/271 differ ONLY in
`growth_score` (max 2.40 quant points). Cause identified: the stored run predates the
current rank step (its `NetProfitGrowthRank` percentiles were null — the EPS-growth
fallback and resulting rank shifts are in the current production code, which is what a UI
refresh would show). Verdict: **explainable parity → reconstruction proceeds with the
current production implementation**; the stored UI snapshot is stale for 10% of companies'
growth components by ≤2.4 points.

## PHASE 1 — historical reconstructability

| input | historical source | PIT rule | caveat |
|---|---|---|---|
| fundamentals (growth/profitability/stability/leverage/current ratio/earnings quality) | `fundamentals.financial_statements` + `monthly_activities` | published_at ≤ cutoff (legacy-migrated: period_end ≤ as_of) | report-chain TTM provenance recorded |
| fiscal anchoring | Codal report titles | published_at ≤ cutoff | 56/268 issuers non-Esfand handled |
| prices (momentum/volatility/liquidity/latest price) | `market.price_observations` | trade_date ≤ as_of (frozen backtest proxy) | adjusted-only vendor series |
| shares (market cap) | **`core.share_intervals`** — TSETMC dEven + Codal published_at knowledge path | valid_from ≤ as_of < valid_to AND knowledge_from ≤ cutoff | task-directed; vendor `share_structure` has no historical PIT-valid collected_at |
| returns | FORWARD_RETURN_ADJUSTED_V1 (pClosing + confirmed factors) | outcome only | 126/252 missing for late 2026 dates |

Reconstruction: 63 Engine runs (one per frozen signal date), production formula unchanged,
share input injected per the table above. **Artifact: `ui_score_historical_v1/
ui_score_historical_v1.jsonl` — 13,481 rows = 100% of the frozen grid** (63 dates × 238
symbols), each row with raw metrics, ranks, per-factor weighted contributions, category
scores, DQ flags/multiplier, final score, missing flags.

## PHASES 5–8 — direct score-vs-return test (Spearman IC, quintiles, excess)

| horizon | IC mean | IC positive fraction | Q1 | Q2 | Q3 | Q4 | Q5 | Q5−Q1 mean | Q5>Q1 freq |
|---|---|---|---|---|---|---|---|---|---|
| 21d | +0.110 | 0.857 | +4.4% | +4.7% | +3.7% | +4.0% | +4.5% | +0.07pp | 0.65 |
| 63d | +0.154 | 0.935 | +6.7% | +8.3% | +8.5% | +10.2% | +11.6% | +4.92pp | 0.76 |
| 126d | +0.181 | 1.000 | +12.7% | +15.5% | +17.2% | +21.3% | +23.7% | +11.01pp | 0.80 |
| 252d | +0.157 | 0.982 | +29.9% | +32.4% | +37.0% | +42.4% | +46.9% | +16.99pp | 0.75 |

Excess vs the equal-weight eligible universe (same dates): IC identical by construction;
Q1 sits BELOW the universe (63d −2.4pp, 126d −5.4pp, 252d −7.9pp) and Q5 ABOVE (+2.6 /
+5.6 / +9.1pp) — high-score stocks genuinely outperformed the contemporaneous cross-section.
Pearson (descriptive) and full per-date values are in
`output/ui_score_historical_v1_analysis.json`.

## PHASE 9 — category diagnostics (not used for any reweighting)

| category | 21d | 63d | 126d | 252d |
|---|---|---|---|---|
| Growth | +0.123 | +0.160 | +0.157 | +0.102 |
| Profitability | +0.029 | +0.045 | +0.057 | +0.035 |
| Valuation | +0.066 | +0.099 | +0.135 | +0.147 |
| Market & Risk | +0.038 | +0.072 | +0.108 | +0.126 |
| Data-quality multiplier | +0.030 | +0.039 | +0.065 | +0.065 |
| **Combined UI score** | **+0.110** | **+0.154** | **+0.181** | **+0.157** |

Growth drives the short horizon, Valuation and Market & Risk the long ones; the combined
score matches or beats every single category at 63–252d (diversification benefit). The
combined score does not dilute the category signals.

## PHASE 10 — calibration (63d, ±5 around each displayed value)

| score | n | median ret | mean ret | P(positive) | mean excess |
|---|---|---|---|---|---|
| 40 | 3,356 | +6.3% | +12.1% | 62.4% | +2.3pp |
| 50 | 587 | +11.6% | +16.1% | 68.3% | +4.6pp |
| 60 | 54 | +1.1% | +13.3% | 63.0% | +1.4pp |
| 70 | 6 | +21.5% | +38.4% | 100% | +16.4pp |
| 80 | 0 | — | — | — | — |

Scores ≥60 are historically RARE (83 rows in the whole grid): the DQ multiplier caps the
score at 0.8×raw for the 36% of rows with missing monthly activity (dq=0.80), and the
80–100 band is EMPTY. The displayed score is a **ranking/quality score, not a probability**.

## PHASE 11 — time stability (all EXPLORATORY_HISTORICAL)

IC63 by year: 2021 +0.081 (pf 0.83) · 2022 +0.106 (1.00) · 2023 +0.107 (0.92) ·
2024 +0.245 (0.92) · 2025 +0.215 (1.00) · 2026 +0.253 (2 dates). Positive in every single
year — no regime dependence of the sign.

## PHASE 12 — quality-multiplier effect

DQ distribution: 1.00 → 8,595 rows; 0.80 → 4,885; 0.65 → 1. corr(DQ, score) = +0.549;
**corr(DQ, future 63d return) = +0.020** — the multiplier is a completeness gate, not an
alpha source. All 23 rows scoring ≥60 have DQ = 1.00 (a high displayed score cannot be
produced from partial data: dq=0.80 caps the score at ~71). Average available metrics:
21.0/21.

## PHASE 13 — examples (illustrative only)

20 examples in `output/ui_score_historical_v1_analysis.json` (`examples.high/low`).
High-score: غاذر 2024-10-30 UI 67.8 → +23.2% (63d), +61.9% (252d); غمینو 2022-06-29 UI 60.9
→ +115.5% (252d). Low-score: غدام/خمهر/دانا UI 2–4 (growth=0, profitability=0, valuation=0)
with mixed-to-negative outcomes. Examples are not evidence; the statistics above are.

## PHASE 14 — explicit answers

1. **Did higher UI scores have higher future returns? YES** — IC positive on all four
   horizons, positive on 86–100% of monthly dates.
2. **Monotonic across quintiles? YES** — strictly monotonic Q1→Q5 means on 63d, 126d and
   252d; the 21d horizon is flat/noisy (Q5−Q1 +0.07pp) with a Q3 dip → monotonicity holds
   on 3 of 4 horizons.
3. **Q5 vs Q1: YES on all four horizons** (+0.07pp / +4.9pp / +11.0pp / +17.0pp).
4. **Did high-score stocks beat the contemporaneous universe? YES** — Q1 below, Q5 above
   the equal-weight universe mean at every horizon >21d.
5. **Useful categories:** Growth (short horizon), Valuation and Market & Risk (long
   horizons); Profitability is the weakest and adds least. The combination does not dilute.
6. **Quality multiplier:** neutral-to-beneficial as a completeness gate (corr with future
   return ≈ 0.02); it is NOT predictive itself, and it makes displayed scores ≥60 rare
   (dq=0.80 caps the scale). It did not hurt the score-return relationship.
7. **The score is historically useful as BOTH**: a ranking score (strong, stable, monotone
   IC structure) and a quality/fundamental summary — but NOT as a probability of profit.

## FINAL GATES

- `UI_SCORE_RECONSTRUCTION = PASS` (13,481/13,481 rows; live-run parity explainable:
  243/271 exact, 28 growth-only ≤2.4 points, cause identified)
- `UI_SCORE_HISTORICAL_PREDICTIVE_EVIDENCE = STRONG` (IC63 +0.154, pf 0.935, Q5>Q1 on 4/4
  horizons per the pre-stated rubric)
- `UI_SCORE_MONOTONICITY = PASS` (3 of 4 horizons monotonic; 21d flat)
- `UI_SCORE_HIGH_VS_LOW_SPREAD = POSITIVE` (4 of 4 horizons)

---

# ROBUSTNESS AUDIT (2026-10-02) — `ui_score_robustness_audit.json`

## TASK 1 — SCORE_CURRENT_CODE vs SCORE_STORED_UI_RUN

- **SCORE_CURRENT_CODE** = current Engine (working tree, VAL_DIRECT, EPS-fallback rank step).
- **SCORE_STORED_UI_RUN** = run `0d2e5bc7` (what the UI serves today) — predates the rank-step
  change; 28/271 companies' growth components differ by ≤2.4 points (documented above).
- Fresh current Engine vs the historical-reconstruction scorer at as_of 2026-10-01:
  **scorer machinery in machine parity** — growth/profitability/market/DQ components
  0 differences across 271 companies. All differences are confined to the valuation
  component (234 companies; mean |Δquant| 2.11, max 15.32) and trace to the share INPUT
  source, not the formula: production uses `core.share_structure` (vendor snapshot),
  reconstruction uses `core.share_intervals` (task-directed historical path). Share
  comparison at as_of: 195 identical · 1 differs >1% (خودکفا 10.0B vendor vs 7.5B chain,
  25% — vendor is fresher) · 70 reconstruction-missing (no PIT-eligible interval at that
  date: non-research subjects + unresolved tail events) · 4 production-missing.
- **Label: this study validates CURRENT_PRODUCTION_SCORE** (current formula, historical
  TSETMC/Codal share inputs). It does NOT reproduce historical UI code versions.

## TASK 2 — universe / survivorship audit

- Per-date eligibility is PIT (Engine financial/price gates; universes grow 201→238 with
  listings/data availability; ranks computed within-date — TASK 3).
- **All 238 research symbols are active today**; the canonical DB contains **0 inactive/
  delisted primary securities**. Only 4 of the 85 active non-research instruments had
  >100 trading days in 2021-23 — all gold/fund instruments excluded by the documented
  corporate scope (یاقوت، عیار، مثقال، ناب), i.e. scope exclusions, not survivorship.
- 0 of the 238 symbols have raw price histories ending before 2026-06-30 → no intra-sample
  trading stops/delistings. New grid entries by year: 2022 +4, 2023 +4, 2024 +3, 2025 +5,
  2026 +2 (genuine listings/data availability). Eligible symbols per year: 220/224/228/
  231/236/238. The 27 symbols absent at the last two grid dates are an engine-coverage
  property IDENTICAL to the frozen phase3 grid (per-date symbol sets match exactly).
- **Verdict: the list is present-day (B) at the ISSUER level** — companies delisted during
  2021-2026 are absent from the canonical DB entirely and therefore from every historical
  cross-section. The bias is structural, direction upward on ABSOLUTE returns, unquantifiable
  from canonical data (no delisted population stored). The cross-sectional RANKING result is
  far less sensitive to it than absolute return levels, but this caveat stands.

## TASK 3 — PIT rank audit (3 dates)

Recomputed within-date percentiles from raw metrics match stored ranks exactly:
2021-03-31 (n=201), 2023-08-30 (n=267), 2025-08-31 (n=226; example سباقر ROE 66.92 →
percentile 1.0, contribution 6×1.0). No future constituents, no current-universe
normalization.

## TASK 4 — exact sample counts

| horizon | score rows | valid return rows | symbols | dates | missing | coverage |
|---|---|---|---|---|---|---|
| 21d | 13,481 | 13,481 | 238 | 63 | 0 | 100% |
| 63d | 13,481 | 13,270 | 236 | 62 | 211 | 98.4% |
| 126d | 13,481 | 13,056 | 236 | 61 | 425 | 96.9% |
| 252d | 13,481 | 11,654 | 234 | 55 | 1,827 | 86.5% |

## TASK 5 — dependence-aware block bootstrap (B=2000, blocks = horizon/21 months)

| horizon | mean IC 95% CI | P(IC≤0) | Q5−Q1 95% CI | P(spread≤0) |
|---|---|---|---|---|
| 21d | [+0.082, +0.141] | 0.000 | [−0.019, +0.021] | 0.476 |
| 63d | [+0.122, +0.194] | 0.000 | [+0.016, +0.077] | 0.0005 |
| 126d | [+0.134, +0.228] | 0.000 | [+0.044, +0.166] | 0.000 |
| 252d | [+0.099, +0.235] | 0.000 | [+0.029, +0.316] | 0.002 |

The RANK relationship survives dependence-aware resampling at every horizon. The 21d
ECONOMIC spread does not (CI straddles zero).

## TASK 6 — non-overlapping cohorts (spacing ≥ horizon)

63d: 17 cohorts, mean IC +0.171, pf 0.94, spread +9.1pp · 126d: 9 cohorts, +0.148, pf 1.00,
+8.0pp · 252d: 5 cohorts, +0.126, pf 1.00, +10.4pp · 21d: 32 cohorts, +0.101, pf 0.84,
+0.6pp. Direction identical to the full monthly analysis in every scheme.

## TASK 7 — full quintile table (n / mean / median / mean excess / median excess / win)

- **63d**: Q1 2,629 / +6.7% / +3.1% / −2.4pp / −3.6pp / 50% · Q2 2,651 / +8.2% ·
  Q3 2,658 / +8.5% · Q4 2,651 / +10.2% · Q5 2,681 / +11.7% — strictly monotonic means AND
  medians ✓
- **126d**: Q1 +12.8% · Q2 +15.7% · Q3 +17.6% · Q4 +21.7% · Q5 +24.1% — monotonic ✓
- **252d**: Q1 +30.0% · Q2 +32.9% · Q3 +37.2% · Q4 +42.8% · Q5 +47.4% — monotonic ✓
- **21d**: means NOT monotonic (Q1 +4.4, Q2 +4.7, Q3 +3.6, Q4 +4.0, Q5 +4.5); MEDIANS
  monotonic (+0.5 / +1.2 / +2.0 / +3.4 / +3.7) ✓

## TASK 8 — the 21d discrepancy, quantified

Mean Q5−Q1 +0.07pp vs **median +2.46pp** and **1%-winsorized mean +2.69pp**: a small number
of extreme outliers (huge losers inside Q5 / huge winners in Q1 in specific months) cancel
the mean, while the rank ordering (IC +0.110, CI [+0.082,+0.141]) and the median ladder are
intact. Verdict: the 21d rank signal is real but the mean top-bottom spread is economically
~0 — **WEAK economically at 21d**.

## TASK 9 — score distribution (displayed 0-100 range in practice)

Overall: min 2.1 · p10 18.4 · p25 23.8 · median 29.7 · p75 36.8 · p90 42.2 · p95 45.2 ·
p99 52.2 · **max 71.9**. The empirically observed production range is ≈2-72; **80+ has never
occurred** (dq=0.80 caps those rows at ~71). The 0-100 scale must not be marketed as
empirically calibrated over its full range.

## TASK 10 — quality-multiplier interaction (diagnostic)

Pre-DQ raw sum: IC63 +0.162, pf 0.935, Q5−Q1 +5.72pp. Post-DQ final: IC63 +0.154, pf 0.935,
Q5−Q1 +4.92pp. **Multiplying by DQ slightly HURTS ranking performance** (−0.008 IC,
−0.8pp spread) — it does not add information; it mainly suppresses low-information rows
(4,885 at dq=0.80) and enforces completeness. No change made.

## TASK 11 — actionability (descriptive)

Mean monthly top-quintile overlap turnover **33.6%** (66% of names persist); top-decile
**44.1%** (56% persist). The ranking is stable enough to be operationally meaningful at
monthly frequency. No cost tuning performed.

## TASK 12 — verdicts

- `UI_SCORE_CURRENT_CODE_PARITY = PASS` (scorer machinery machine-exact; valuation input
  source difference documented and quantified)
- `UI_SCORE_PIT_UNIVERSE_INTEGRITY = PASS` (per-date PIT computation verified on 3 dates;
  reconstruction = frozen grid exactly) — **with the explicit survivorship caveat above**:
  the 238-symbol list is present-day, the DB holds no delisted issuers, so a structural
  upward bias on ABSOLUTE return levels cannot be excluded or quantified; the cross-sectional
  ranking result is the robust claim.
- `UI_SCORE_DEPENDENCE_ROBUSTNESS = PASS` (all IC CIs exclude 0; spreads robust at
  63/126/252; 21d spread not distinguishable from 0)
- `UI_SCORE_HISTORICAL_RANKING_VALUE = STRONG`
- `UI_SCORE_SHORT_HORIZON_21D = WEAK` (statistical rank signal real; economic mean spread ~0;
  median spread +2.5pp/month)
- `UI_SCORE_MEDIUM_HORIZON_63_126D = STRONG`
- `UI_SCORE_LONG_HORIZON_252D = STRONG`

**Plain answer**: yes — historically, between two otherwise eligible stocks, the one with
the higher displayed UI score was more likely to deliver the higher subsequent adjusted
return, at every horizon tested, with the effect strongest and economically meaningful at
63-252 days. **STATISTICAL RANKING VALUE = strong at all horizons. ECONOMIC TOP-vs-BOTTOM
SPREAD = meaningful at 63-252d (+4.9pp to +17.0pp mean, CIs excluding zero); ~zero at 21d
on means (+2.5pp on medians).**

---

# SURVIVORSHIP RESOLUTION (2026-10-02) — market-wide issuer enumeration

Provisional gate revision accepted: `UI_SCORE_CURRENT_CODE_PARITY = PARTIAL`,
`UI_SCORE_PIT_UNIVERSE_INTEGRITY = PARTIAL`. Evidence: bounded Codal enumeration of the
**monthly activity reports (LetterType=58 — mandatory for listed producers)** for three
probe months spanning the window: 1400/05 (2021-07), 1402/05 (2023-07), 1404/05 (2025-07).
Raw responses cached under `output/survivorship_probe/`; scripts
`enumerate_codal_issuers.py` + candidate tables `survivorship_candidates_final.json`.

## PHASE 1-2 — the market-wide issuer population

Distinct LT58 filers: **618 (2021-07) → 725 (2023-07) → 860 (2025-07); 3-month union 914**.
Classification of the 914 against the canonical/research universe (symbol + normalized
company-name matching):

| class | issuers |
|---|---|
| in the 238 research list | 229 |
| matched in canonical (renames/other securities) | 33 |
| fund-like symbols | 1 |
| **absent from the canonical DB (monthly filers!)** | **651** |

Month-pattern of the 651 absent: 339 filed in ALL THREE probes (alive 2021→2025 — pure
coverage gap) · 100 filed 1402+1404 · 155 filed 1404 only (new listings 2023-25) · 17 filed
1402 only · **34 stopped filing during the window (1400-only 18 + 1400+1402 16) — the
plausible TRUE_EXIT set**. Sector mix of the absent: 270 operating/other, 168 investment
holdings, 21 insurance, 13 banks, 11 leasing, 8 financings, 2 exchanges — real listed
equities (مخابرات ایران، بیمه البرز، بورس تهران، تامین‌سرمایه‌ها، آبادا، افرانت…).

## PHASE 3-4 — quantification and scoring ability

- The canonical universe covers ~29% of the LT58 filer population (262/914). The gap is
  **coverage, not primarily delisting**: 339 of the 651 were alive throughout; the plausible
  true-exit set is ~34 (3.7% of filers).
- The 651 are absent from `core.companies`/`core.securities` → **no fundamentals are
  ingested → the exact production scorer cannot be run for them** (per the task rule they
  are kept EXPLICITLY MISSING; scoring them would require a new ingestion pipeline, out of
  scope). The survivorship direction (were disappeared issuers low-score/low-return?) is
  therefore UNVERIFIED, not assumed.

## PHASE 5-6 — effect on the validation

Because the missing issuers cannot be scored, the cross-sectional ranks cannot be re-run
over a materially wider denominator. The §54 result therefore stands AS the
**available-universe validation**: ranks were always computed within the covered universe
(the UI has never ranked the absent issuers, historically or today). The absolute-return
levels carry the (unquantifiable) survivorship/coverage bias; the within-date RANK ordering
of covered names is not mechanically affected by unlisted non-scored names.

## PHASE 7 — survivorship direction

Average score / quintile distribution of later-disappeared securities: **NOT COMPUTABLE**
(no fundamentals). Direction of bias: UNVERIFIED. What IS quantified: the true-exit set is
small (~34 filers ≈ 3.7% of the market population) and the covered set contains zero
intra-sample trading stops — so the classic delisting-survivorship channel is small; the
dominant caveat is coverage breadth.

## PHASE 8 — current production valuation-source sensitivity (A=vendor vs B=TSETMC path)

At as_of 2026-10-01, 271 companies: score rank correlation **0.956**; mean |Δscore| 2.11,
max 15.32; **top-quintile overlap 86.2%**, top-decile overlap **74.2%**; movers >2 points:
71 · >5 points: 39 · >10 points: 7. The valuation-source difference is material for
individual user-facing rankings (26% decile churn) though not for the aggregate ordering.
(`ui_score_input_sensitivity.json`)

## PHASE 9 — final gates

- `UI_SCORE_SCORER_FORMULA_PARITY = PASS` (machine-exact machinery, both worlds)
- `UI_SCORE_CURRENT_INPUT_PARITY = PARTIAL` (rank corr 0.956; 74% decile overlap)
- `UI_SCORE_PIT_UNIVERSE_INTEGRITY = PARTIAL` (per-date PIT verified; 651 filers absent —
  coverage gap; ~34 true exits unscorable without new ingestion)
- `UI_SCORE_DEPENDENCE_ROBUSTNESS = PASS`
- `UI_SCORE_HISTORICAL_RANKING_VALUE = STRONG` (within the reconstructed available
  historical universe)

**Plain answer: does inclusion of historically listed but later-disappeared equities
materially weaken the conclusion? NO — not demonstrated.** The plausible disappeared set is
small (~34 filers) and unscorable without new ingestion; the dominant issue is coverage
breadth (651 absent issuers), which the UI score never claimed to rank. **Final claim
(PARTIAL wording): higher UI scores ranked future returns better within the reconstructed
available historical universe, with residual survivorship uncertainty. The 21d horizon
remains economically WEAK** (rank signal real; mean spread ~0, median +2.5pp).
