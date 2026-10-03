# BUNDLE INTEGRITY AUDIT (research bundle v2)

Frozen: 2026-10-02. Scope: repair of the external-review defects in
`research_bundle_for_review.zip` (v1) and re-export as
`research_bundle_v2_for_review.zip`. No research results were computed or optimized; the
UI score is untouched.

## Finding 1 — outcomes.parquet measured the corporate-action FACTOR RATIO, not returns
**Root cause (code defect):** the v1 bundle's forward-return helper divided the
cumulative corporate-action adjustment FACTOR chain (`adj[sym] = c` — the backward
coefficients) instead of adjusted PRICES: `a1/a0 − 1` where a0/a1 were chain values. The
chain is constant between events, so the "return" was **exactly 0.0 whenever no CONFIRMED
event fell inside the forward window** — 89% of 21d windows, ~two-thirds of 63d windows;
فولاد 2021-01-31 63d returned 0.0 (its next event, 2021-05-24, fell outside the window).
**Repair:** outcomes rebuilt as adjusted PRICE returns — `adjp[exit]/adjp[entry] − 1`
where adjp = pClosing × cumulative factor (identical to the validated
`ui_score_historical_v1` implementation). The factor chain is now used only for the daily
panel's `adjustment_factor`/`adjusted_close` columns.

**Parity (repaired outcomes, UI score):** IC21 **+0.1103** (pf 0.857) · IC63 **+0.1543**
(pf 0.935) · IC126 **+0.1806** (pf 1.000) · IC252 **+0.1571** (pf 0.982) — reproduces the
frozen UI validation (+0.110/+0.154/+0.181/+0.157) within tolerance. The external
reviewer's direct reconstruction (+0.1543) is confirmed.

## Finding 2 — 13,409 vs 13,481 rows
**Root cause:** the v1 monthly builder skipped rows whose raw TSETMC daily cache had **no
row on or before the signal date** (`raw_series_starts_after_signal_date`) — late-listed
names at early grid dates (the raw endpoint's per-symbol history depth differs from the
canonical price coverage, which reaches back further via the legacy migration).
**Classification: all 72 rows = raw-cache depth limitation (accidental inner-join loss —
repaired).** None were intentionally excluded, none were security-mapping failures, none
were missing-feature-only rows. Repaired monthly panel: **13,481 rows** = the full frozen
grid. The 72 repaired rows carry UI outputs with NULL price features
(`feature_availability = NO_PRICE_DATA_ON_OR_BEFORE_T`).

## Finding 3 — UI quintile semantics inverted in the bundle
**Root cause:** the v1 bundle assigned `ui_quintile` from a DESCENDING score sort
(Q1 = highest score), while the validated UI-score analysis used the ASCENDING convention
(Q1 = lowest, Q5 = highest — consistent with the positive IC and the validation ladder
Q1 +6.7% → Q5 +11.7%). The bundle's labels were inverted relative to the documentation.
**Repair:** canonical convention frozen — **ascending ui_score: Q1 = lowest score, Q5 =
HIGHEST score** (remainder-inclusive last quintile); `ui_rank` (higher = higher score)
retained so future research never depends on the Q label alone. DATA_DICTIONARY and README
aligned. The validated §54/§55 ladders were computed under the correct ascending
convention (verified: `ui_score_historical_analysis.py` sorts ascending) — only the bundle
was inconsistent.

## Finding 4 — daily panel security_id all NULL
**Root cause:** the daily builder read `security_id` from the TSETMC index entries, which
do not carry it. **Repair:** mapped from `core.securities` via the covered symbol list.
Result: **837,525/837,525 non-null (100%)**, 238 unique symbols, 238 unique security_ids,
0 duplicate identity conflicts. Symbol-only joins are no longer required.

## Finding 5 — event panel security_id all NULL + missing financial-statement events
**Root causes:** (a) monthly/LT28/corporate-action event rows hard-coded
`security_id = None`; (b) the financial-statement query contributed 0 rows (it never
reached the append loop due to a join/column defect). **Repair:** company → primary
security mapping applied to every event class; financial-statement events exported
(8,157 rows, 0 unmapped) with fiscal period and canonical revenue/net_profit/
operating_profit/eps where stored. Result: **28,508 rows** — financial_report 8,157
(mapped 8,157/unmapped 0) · monthly_sales_report 12,180 (mapped, 0 unmapped) ·
corporate_action_* 7,013 · capital_increase_announcement_LT28 1,158.

## Finding 6 — monthly_sales_report published_at coverage = 0%
**Root cause:** all 12,177 legacy-migrated monthly activity reports have
`published_at = NULL` in `ingestion.reports` (the legacy migration carried
`period_end_date` only). NOT fabricated; NOT substituted with period_end. **Per-class
event-timing audit:** financial_report — published_at 595/8,157 (7.3%; the Codal-ingested
subset carries real dates) · monthly_sales_report — 0/12,180 →
**EVENT_TIMING_PIT_READY = NO** (period_end proxy only) · LT28 — 1,158/1,158
(real Codal PublishDateTime, converted to UTC) → **YES** · corporate_actions —
published_at not captured; `action_date` is the market ex-date (market fact) →
announcement timing NOT READY. Monthly-report publication times would require a bounded
Codal re-crawl of report pages — out of scope.

## Finding 7 — daily trade-activity zero stretches
**Root cause classified:** the TSETMC daily-history endpoint emits rows for non-trading
dates with carried prices and zero trades. Flags added per row:
`security_traded` (zTotTran > 0) and `zero_trade_reason` ∈ {traded,
market_closed_no_covered_trades, no_trade_unknown} (suspension vs placeholder NOT further
classified — no synthesis). فولاد's 2026 zero stretches are rows of this kind (carried
price, zero trades), not source defects. Trade-value/trade-count shocks must respect
these flags in any future research.

## Finding 8 — reproduction test calendar defect (found and fixed during this audit)
The v1 integrity check's own reproduction test used the DAILY PANEL's date set as the
"trading calendar" — which includes non-trading placeholder rows — so "63 rows later"
diverged from "63 canonical trading days later" whenever a placeholder fell inside the
window (57/192 values). **Repair:** the reproduction test now uses the CANONICAL trading
calendar (`market.price_observations` trade dates). Result: **191/191 values reproduce
exactly** (50 samples; remaining rows = incomplete windows), and
فولاد 2021-01-31 63d = **+0.077447** from both paths (the reviewer's value).

## Finding 9 — independent review finding (recorded, not acted on)
The external review preregistered and tested one price-timing hypothesis (QUALITY PULLBACK
REVERSAL) before opening outcomes: Signal IC63 ≈ −0.019, identical-row UI baseline ≈
+0.042, ΔIC ≈ −0.061, positive fraction ≈ 0.429, Q5−Q1 excess ≈ −0.6pp — unfavorable.
Recorded as an independent finding; NOT merged into this project's candidates; no V2
built.

## Repaired bundle (research_bundle_v2_for_review.zip)

| file | rows |
|---|---|
| monthly_pit_panel.parquet | **13,481** × 102 cols |
| daily_market_panel.parquet | 837,525 (security_id 100%, trade flags) |
| event_panel.parquet | **28,508** (statements restored) |
| market_state_daily.parquet | 6,163 |
| outcomes.parquet | 13,481 |
| DATA_INVENTORY.md / DATA_DICTIONARY.md / README / COVERAGE_SUMMARY.csv / COVERAGE_BY_YEAR.csv / FEATURE_PROVENANCE.csv / reproduction_test.json | updated |

## Final gates

- `RESEARCH_BUNDLE_V2_READY = YES`
- `OUTCOME_PARITY = PASS` (IC21/63/126/252 reproduce the frozen validation; 191/191
  sample reproduction; فولاد exact)
- `MONTHLY_GRID_PARITY = PASS` (13,481 = full frozen grid)
- `UI_QUINTILE_SEMANTICS = PASS` (canonical ascending convention; ui_rank retained)
- `DAILY_IDENTITY_MAPPING = PASS` (100% non-null; 0 conflicts)
- `EVENT_IDENTITY_MAPPING = PASS` (statements/monthly 100% mapped; 0 ambiguous guesses)
- `EVENT_TIMING_PIT_READY = PARTIAL` (financial reports 7.3% published_at; monthly 0%;
  LT28 100%; corporate actions = ex-date only)
- `TRADE_ACTIVITY_SEMANTICS = VALIDATED` (classified with explicit flags; unknown left
  unknown)
