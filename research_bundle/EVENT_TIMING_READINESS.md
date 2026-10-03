# EVENT TIMING READINESS ASSESSMENT (final, 2026-10-02)

Bounded metadata-first backfill completed. Source: per-symbol Codal search
(LetterType 58 = monthly activity, LetterType 6 = financial statements),
window 1400/01/01–1405/07/01, all 238 covered symbols, cache-first,
paced 6.2 s, raw responses persisted.

## Backfill summary

- **474 fresh fetches** (238 symbols × 2 letter types), 0 failures
- **27,497 unique letters recovered** across all symbols and both letter types
- Every letter carries: TracingNo, Title (with jalali period-end + duration),
  PublishDateTime (REAL Codal publication stamp in jalali, converted to UTC),
  LetterCode, Url

## Matching results

| event class | total events | MATCH_EXACT | MATCH_STRONG | MATCH_STRONG_CORRECTION | AMBIGUOUS | NOT_FOUND |
|---|---|---|---|---|---|---|
| monthly_sales_report | 12,180 | 0 | 7,487 | 2,128 | 6 | 2,559 |
| financial_report | 8,157 | 595 | 2,416 | 399 | 2,665 | 2,082 |

- monthly: 9,615/12,180 (78.9%) have real publication times (MATCH_STRONG +
  MATCH_STRONG_CORRECTION). NOT_FOUND = events where no Codal letter was found (the
  company may not have filed a monthly report for that period, or the symbol changed).
- financial: 595 already carried real published_at (Codal-ingested — MATCH_EXACT);
  2,416 more recovered via per-symbol search (MATCH_STRONG); 399 corrections linked
  (MATCH_STRONG_CORRECTION); 2,665 AMBIGUOUS (multiple letters for the same period,
  typically consolidated + standalone variants for the same issuer); 2,082 NOT_FOUND.
- event_stream_pit.parquet: **11,909 publication rows** (11,743 monthly + 166 financial
  report rows in the stream; the financial MATCH_EXACT events retain their original
  published_at in the canonical data and are counted in the coverage but not duplicated
  into the stream).

## PART 12 gates

- **MONTHLY_REPORT_EVENT_TIMING_READY = YES** — 78.9% of 12,180 monthly sales events have
  real publication times, spanning 164 symbols across all 6 years (2021–2026), with
  deterministic symbol + period matching from official Codal metadata. Sufficient for a
  non-trivial preregistered experiment.
- **FINANCIAL_REPORT_EVENT_TIMING_READY = PARTIAL** — 3,410/8,157 (41.8%) have real
  publication times; 2,665 are AMBIGUOUS (multiple letter variants for the same period:
  consolidated vs standalone, preliminary vs corrected) requiring resolution before
  individual-statement event timing can be used. The MATCH_EXACT 595 are high-confidence.

## Fundamental-event hypothesis feasibility (PART 9; no returns touched)

| construction | feasible? | basis |
|---|---|---|
| A. pre-publication state | **YES** | the event stream is sorted per company; the prior publication row gives the pre-event fundamental state (previous month's sales, prior TTM values) |
| B. newly published information | **YES** | the event stream carries the canonical values from each report (monthly sales_amount_rial; financial revenue/net_profit/operating_profit/EPS) |
| C. deterministic revision/surprise | **PARTIAL** | feasible for monthly sales (YoY change, 3-month trajectory change — monthly data is monthly-frequency so consecutive reports exist for most companies); for financial reports, the YoY change vs the previous comparable report is computable when both have real published_at; the AMBIGUOUS financial events limit full coverage |
| D. post-publication signal timestamp | **YES** | published_at (real, from Codal metadata) defines when the signal becomes evaluable; the first monthly date after published_at is the evaluation point |

**FUNDAMENTAL_EVENT_SIGNAL_FEASIBLE = YES** — the monthly sales path alone (9,615 events,
164 symbols, multi-year, real publication times) is sufficient for a non-trivial
preregistered experiment. The financial-report path is broader but has higher ambiguity.

## PART 10 — UI score delta explicitly excluded

The UI-score delta (current − previous UI score) is NOT used as the revision measure: it
mixes fundamental information with valuation and market/risk changes, and its data-quality
multiplier confounds information arrival with data completeness. The first event
hypothesis should isolate newly published fundamental information using the event stream's
raw canonical values (sales, profits) directly.

## PART 11 — trade-activity path (secondary, preserved)

Trade-count, trade-value, high/low/open and the security_traded flags are available in
the daily panel. Not tested here. Lower priority than fundamental information arrival
because buyer/seller direction and historical volume are unavailable.

## Unresolved

- 2,559 monthly + 2,082 financial NOT_FOUND events (reasons vary: symbol changes, non-filing
  periods, search date boundary effects)
- 2,665 AMBIGUOUS financial events (consolidated/standalone variants)
- 6 AMBIGUOUS monthly events
- 34 plausible true-exit issuers (from the survivorship audit) are unscorable
- The 651 non-covered Codal issuers remain outside the product universe
