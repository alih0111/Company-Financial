# UI SCORE — PRODUCT SPECIFICATION (explanation semantics, frozen 2026-10-02)

Scope: the 0–100 quantitative score (`canonical-v1-dev`) already shown in the UI. This
document freezes what the score MEANS, how it may be EXPLAINED, and what wording is
ALLOWED / PROHIBITED. Nothing here changes the score, its weights, its DQ multiplier, or
its scale. Validation basis: `historical_codal_backfill/UI_SCORE_HISTORICAL_VALIDATION.md`
(`PASS_WITH_UNIVERSE_CAVEAT`), share-source contract
(`canonical_postgres_v1_2_1/analytics_canonical_v1/UI_SCORE_CURRENT_SOURCE_CONTRACT.md`),
and the Signal V1 closeout (`signal_engine/SIGNAL_V1_CLOSEOUT.md`).

## 1. What the score measures

A **cross-sectional company-attractiveness / quality ranking** across the covered issuer
universe: each company's fundamentals (growth, profitability), valuation, and market/risk
standing are converted to percentiles among covered companies, weighted, summed by
category, penalized for specific weaknesses, and scaled by a data-quality multiplier.

It is computed from: canonical financial statements (PIT), monthly activity reports,
canonical market data (TSETMC pClosing basis), and the validated share-count source
(TSETMC zTitad current / TSETMC+ Codal knowledge-time historical).

## 2. How the four category scores contribute

- **GROWTH (max 36)**: 12-month sales growth (w10), 3-month sales growth (w6), revenue
  growth (w5), operating profit growth (w5), net profit / EPS growth (w10). Penalties:
  severe sales decline (−6), severe operating-profit decline (−5).
- **PROFITABILITY (max 26)**: operating margin (w4), net margin (w4), ROE (w6), margin
  trend (w3), interest coverage (w3), cash conversion (w2), earnings quality (w4,
  lower better). Penalties: net loss (−10), weak interest coverage (−4), falling margins
  (−3), low earnings quality (up to −8).
- **VALUATION (max 16)**: P/E TTM (w11), P/S (w3), P/B (w2) — lower cheaper is better
  within valid ranges; missing/invalid P/E penalty (−8).
- **MARKET & RISK (max 11)**: 30-day liquidity (w3), leverage (w2), current ratio (w2),
  sales stability (w1), 30-day volatility (w2, lower better), 30-day momentum (w1).

Each factor enters as its cross-sectional percentile among covered companies on that date.

## 3. Role of data quality

The four category sums are multiplied by a **data-quality multiplier (0–1)** built from
three availability components (financial statements 0.45 combined, monthly activity 0.20,
market price 0.35). The multiplier ensures a company with incomplete data cannot display
a very high score. It is a completeness gate — historically it neither added nor removed
predictive content (corr(DQ, future return) ≈ 0.02) — and it is the reason very high
displayed scores are rare.

## 4. What higher / lower means

- **Higher score** = the company ranks better **relative to other covered companies** on
  the weighted combination of growth, profitability, valuation and market/risk factors.
- **Lower score** = weaker relative standing and/or less complete underlying data.
- The score is **relative and cross-sectional**: it says nothing about the market's
  direction, and the same company's score can move when peers change.

## 5. Historical evidence supporting the ranking (frozen facts)

Within the available covered universe (2021–2026, 63 monthly evaluations, 238 symbols):
mean Spearman rank IC vs subsequent 63-trading-day adjusted returns **+0.154** (positive on
93.5% of dates), vs 126d **+0.181** (100%), vs 252d **+0.157** (98.2%); top-quintile minus
bottom-quintile mean excess return **+4.9pp (63d) / +11.0pp (126d) / +17.0pp (252d)**;
positive in every calendar year; dependence-aware bootstrap CIs exclude zero. Full record:
`historical_codal_backfill/UI_SCORE_HISTORICAL_VALIDATION.md`.

## 6. Important limitations

1. Ranking evidence, **not** action recommendations (no BUY/HOLD/SELL semantics).
2. Universe caveat: the validated universe is the covered/reconstructed available product
   universe; issuers that disappeared or were never covered are outside it
   (survivorship effect on the full market: UNRESOLVED).
3. Returns measured on the covered universe — **not** full-market validation.
4. Observed historical score range ≈ **2.1–71.9**; scores above ~72 have never been
   observed; the full 0–100 numeric range is **not** empirically calibrated.
5. The score is not a probability of profit, not an expected return, not a guarantee.
6. Past ranking performance does not guarantee future relationships.

## 7. Explanation contract (deterministic; no generated financial conclusions)

For every displayed company the UI can explain the final score **only** from the already
computed decomposition (`analytics.factor_scores` percentiles/weighted scores +
`metric_snapshots` raw values + DQ flags):

- Final Score = Growth + Profitability + Valuation + Market & Risk, each × data-quality
  multiplier.
- Per category: each factor's **contribution = weight × percentile** (already materialized
  as `weighted_score`).
- **Top 3 positive contributors**: the three highest factor contributions among factors
  whose percentile ≥ 0.5 (reported as "strong relative standing in <factor name>").
- **Top 3 weak/negative drivers**: the three lowest contributions among weighted factors
  (percentile < 0.5) plus any applied category penalty (loss, invalid P/E, severe declines)
  with its fixed point value.
- Data-quality state: which availability components are present/missing.

No LLM-generated financial conclusion is part of the canonical explanation.

## 8. Descriptive score bands (explanation ONLY; no deployment)

Derived from the frozen score DISTRIBUTIONS (never from future returns):
historical grid 2021–2026 (13,481 rows): p25 23.8 / p50 29.7 / p75 36.8 / p90 42.2 / max
71.9; current production run 2026-10-02 (271 companies): p20 24.5 / p40 30.7 / p60 38.0 /
p80 48.2 / p95 59.3 / max 68.6.

**Proposed descriptive bands (anchored to the current-run quintiles; users see current
scores):**

| band | range | descriptive meaning |
|---|---|---|
| LOW | < 24.5 (bottom quintile) | weak relative standing and/or incomplete data |
| BELOW AVERAGE | 24.5 – 30.7 (second quintile) | below-median relative standing |
| AVERAGE | 30.7 – 38.0 (middle quintile) | mid-range relative standing |
| ABOVE AVERAGE | 38.0 – 48.2 (fourth quintile) | above-median relative standing |
| HIGH | > 48.2 (top quintile) | strong relative standing across the factor set |

**Preferred alternative (cleaner):** percentile labels instead of absolute numbers —
"higher standing than X% of covered companies at this evaluation date" computed from the
same cross-section. Either option is description-only; **do not deploy yet**; do not label
any band BUY/SELL; the absolute 0–100 scale must not be presented as empirically calibrated
over its full range (80+ unobserved).

## 9. Historical context display (decision: allowed WITH mandatory caveats)

The product may surface a descriptive line such as:

"در داده‌های تاریخی موجود سیستم، نمادهای با امتیاز بالاتر در افق‌های میان‌مدت و بلندمدت
عموماً رتبه بازده بهتری داشته‌اند."

Mandatory accompanying caveats whenever that line is shown:
- محدود به همان جهان پوشش‌داده‌شده و داده‌های تاریخی در دسترس (available-universe caveat);
- عملکرد گذشته تضمینی برای آینده نیست (historical performance is not a guarantee);
- بدون هیچ تفسیر احتمالی (no probability interpretation).
Exact expected-return figures must not be shown as promises. If numeric historical spread
context is ever shown, it must be labeled as historical description of the covered universe,
not expectation.

## 10. Wording policy (binding for UI copy)

**ALLOWED:** relative-standing statements ("رتبه بهتر نسبت به سایر نمادهای تحت پوشش"),
factor-level explanations per §7, the historical-context sentence with §9 caveats, the
descriptive bands of §8.

**PROHIBITED:** "این سهم رشد خواهد کرد" · "احتمال سود ۷۰٪" (or any probability) ·
"سیگنال خرید" / "سیگنال فروش" / BUY / SELL · any entry-timing statement · any claim that
the score is calibrated over the full 0–100 range · any claim of full-market validation.
