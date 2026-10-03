# FUNDAMENTAL EVENT V1 — PREREGISTRATION

Frozen: 2026-10-02, BEFORE any outcome inspection. `FUNDAMENTAL_EVENT_EXECUTED = NO` at
freeze time. SHA-256 recorded in SESSION_HANDOFF §66. This document may not be edited
after execution; corrections require V2.

Parent documents: `research_bundle/EVENT_TIMING_READINESS.md` (data readiness),
`research_bundle/BUNDLE_INTEGRITY_AUDIT.md` (repair record), `research_bundle/RESEARCH_BUNDLE_README.md`
(project state). This experiment is a SEPARATE research family from Signal V1 (timing
overlay) and from the UI score (cross-sectional quality ranking).

## Research question

Does newly published improvement in monthly sales fundamentals predict subsequent
relative performance because the market may under-react to the new information?

Primary mechanism: **POST-PUBLICATION FUNDAMENTAL DRIFT**.

This is intentionally different from: price momentum · pullback/reversal · volatility
timing · Signal V1 · the UI score.

## PART 1 — Event universe (frozen)

Eligible events are monthly-sales-report publications that satisfy ALL:

1. real Codal `published_at` (non-null, from the metadata backfill)
2. deterministic security mapping (canonical `security_id` via `core.securities`)
3. deterministic `period_end` date
4. valid current-period sales value (`sales_amount_rial > 0`)
5. valid same-month-prior-year comparable sales value (from `fundamentals.monthly_activities`)
6. deterministic next-trading-date signal entry (from the canonical trading calendar)
7. non-ambiguous event match (MATCH_STRONG or MATCH_STRONG_CORRECTION)

Excluded: AMBIGUOUS · NOT_FOUND · missing publication time · missing prior-year
comparable · events that cannot produce the frozen feature.

Corrections remain separate publication events. The original event's knowledge time is
the original `published_at`. A correction's `published_at` is the correction's own
knowledge time for the corrected values.

## PART 2 — Signal entry timestamp (frozen)

`SIGNAL_ENTRY_DATE` = first canonical trading date (from `market.price_observations`
trade dates) strictly AFTER the Tehran calendar date of `published_at`. No same-day
entry. All features must be computable from information available by `published_at`.

## PART 3 — Primary feature (frozen)

```
SALES_YOY_CURRENT = current_month_sales / same_month_prior_year_sales - 1
```

where "same_month_prior_year_sales" is the `sales_amount_rial` from
`fundamentals.monthly_activities` for the same company and the same Jalali calendar
month one year before the current `period_end`.

Define the **immediately preceding PIT-ready monthly publication** for the same security
(sorted by `published_at`; the previous event in the company's publication sequence).

```
SALES_YOY_PREVIOUS = same formula applied to that previous publication's period
```

```
SALES_GROWTH_ACCELERATION = SALES_YOY_CURRENT - SALES_YOY_PREVIOUS
```

This is the PRIMARY event information variable. Positive = newly published YoY sales
growth improved relative to the previous publication. Negative = deteriorated.

No alternative growth formulas searched. No level-vs-acceleration choice based on
outcomes.

## PART 4 — One ablation (frozen)

`fundamental-event-v1-level`: uses `SALES_YOY_CURRENT` instead of acceleration.
Purpose: determine whether the revision (change in YoY) matters beyond the absolute
level. Diagnostic only; cannot replace the primary.

## PART 5 — Excluded variables (frozen)

NOT used in the primary experiment: 3-publication trajectory · moving averages ·
z-scores · earnings growth · UI-score delta · valuation · momentum · volatility ·
trade value. These remain future research possibilities.

## PART 6 — Primary signal (frozen)

For each `signal_entry_date`: take all eligible events whose entry date is that date.
Cross-sectionally midrank `SALES_GROWTH_ACCELERATION` (higher = higher rank).

`FUNDAMENTAL_EVENT_SIGNAL` = the midrank percentile [0,1].

No weights. No composite. No thresholds.

## PART 7 — Sparse-date handling (frozen)

`MIN_EVENT_CROSS_SECTION = 10`. Dates with fewer than 10 eligible events are not used
for date-level IC. Events are NOT moved to another date. Individual events are
preserved in the raw signal artifact.

## PART 8 — Outcome (frozen)

PRIMARY: 63-trading-day adjusted excess return = stock adjusted forward return minus
the same-entry-date equal-weight forward return of the PIT-eligible product universe.

SECONDARY: 126-trading-day adjusted excess return.

DIAGNOSTIC: 21-trading-day adjusted excess return.

Entry: SIGNAL_ENTRY_DATE close. Exit: canonical trading-day convention (entry + H
trading days on the global calendar). Price basis: TSETMC pClosing + validated
adjustment pipeline. 252d excluded from all gates.

## PART 9 — Event-level analysis (frozen)

TWO complementary views:

A. **Date-level cross-section** (dates with ≥10 eligible events): Spearman IC between
SALES_GROWTH_ACCELERATION and 63d excess return. Report mean/median IC, positive-date
fraction.

B. **Pooled event portfolio**: events divided into quintiles based on acceleration rank
within their event-date cross-section. Report Q1–Q5 mean/median excess return, event
count, positive excess-return fraction. Primary economic spread: Q5 − Q1. Events are
NOT mixed across dates before ranking.

## PART 10 — Baseline (frozen)

On the IDENTICAL event rows: `UI_RANK_EVENT` = cross-sectional rank of the frozen UI
score among the same eligible event cohort/date. The fundamental event signal is
compared against this UI-score baseline on identical events/dates. Never a different
universe.

## PART 11 — Incremental test (frozen)

Delta IC63 = Event Signal IC63 − UI baseline IC63 (identical rows).
Delta Spread63 = Event Signal Q5−Q1 excess spread − UI baseline Q5−Q1 excess spread.
No residual regression, no multivariate optimization.

## PART 12 — Success gates FE1–FE8 (frozen; rationale per gate)

- **FE1 sample adequacy**: ≥ 24 qualifying signal dates (≥10 eligible events each) AND
  ≥ 500 total eligible events. *Rationale: a monthly event-driven signal needs at least
  2 years of monthly dates and enough events for a meaningful cross-section; 500 is
  ~3.7× the v2.1 TOP_N portfolio size.*

- **FE2 primary ranking**: mean date-level IC63 ≥ **+0.05**. *Rationale: matches the
  UI-score validation floor; below this the event signal has no standalone information.*

- **FE3 stability**: positive-IC63 fraction ≥ **0.60**. *Rationale: 0.5 is chance; the
  UI score achieved 0.935 on the full cross-section; 0.60 for a sparser event-driven
  signal is a meaningful stability floor.*

- **FE4 economic spread**: mean Q5−Q1 63d excess return ≥ **+2.0pp**. *Rationale: the
  UI score's full-universe spread was +4.9pp; a narrower universe (top-attractiveness
  events) should still produce ≥40% of that spread if the mechanism is real.*

- **FE5 dependence robustness**: block-bootstrap 95% CI lower bound for mean IC63 > 0
  AND for Q5−Q1 spread > 0. *Settings: seed 20261003, B=2000, 63d block = 3 months of
  signal-entry dates, 126d = 6 months; date-level resampling unit.*

- **FE6 incremental value**: ΔIC63 ≥ **+0.02** AND ΔSpread63 ≥ **+1.0pp** vs the UI
  baseline on identical rows. *Rationale: the effect size previously treated as
  material in this project; both required to prevent a "different but not better"
  result from passing.*

- **FE7 PIT integrity**: all event-time leakage tests E1–E8 PASS (see PART 14).

- **FE8 concentration**: no single security > **5%** of eligible events AND no single
  calendar year > **30%** of eligible events. *Rationale: prevents the result from
  being driven by a single company or a single period; pre-measured (max security
  share 0.9%, max year share 20.7% — both pass).*

All FE1–FE8 required for exploratory PASS. No near-miss override.

## PART 13 — Bootstrap settings (frozen)

Seed: **20261003** · B: **2000** · 63d block length: **3 months** of signal-entry dates ·
126d block length: **6 months** · resampling unit: date. Settings frozen before
execution; never chosen after seeing results.

## PART 14 — Leakage tests E1–E8 (frozen; implemented with the pipeline build)

- **E1**: published_at is the real Codal source publication time (jalali → UTC, never
  backdated, never inferred from period_end)
- **E2**: signal_entry_date strictly follows the publication calendar date
- **E3**: current monthly sales value belongs to the published report (matched by
  period_end + company, not by proximity)
- **E4**: the same-month-prior-year comparator was already historically available by
  event time (it comes from a monthly report with an earlier published_at)
- **E5**: the previous-publication YoY value comes only from an earlier published event
  (sorted by published_at per company; no future publication used)
- **E6**: corrections do not overwrite earlier historical knowledge (original
  published_at is the knowledge time; corrections are separate stream rows)
- **E7**: future report rows are inaccessible during feature construction (the pipeline
  is date-isolated per signal date)
- **E8**: outcome fields are physically separated from the signal-construction artifact
  (two scripts; the construction script contains no outcome-source references)

All must PASS before any performance calculation. If any fails: STOP.

## PART 15 — Pre-outcome feasibility (measured)

Pre-outcome counts from `fundamental_event_feasibility.json`:

- events with real published_at + valid sales: 11,743
- with valid YoY (same-month-prior-year found): 11,660
- with valid acceleration (eligible): **11,489**
- distinct signal-entry dates: 930
- qualifying dates (≥10 events): **278**
- events on qualifying dates: **9,810**
- symbols: **164**
- FE1: **PASS** (278 ≥ 24 dates; 9,810 ≥ 500 events)
- FE8 pre-check: **PASS** (max security share 0.9%; max year share 20.7%)

## PART 16 — Decision rule (frozen)

Primary: `fundamental-event-v1-acceleration`. Ablation: `fundamental-event-v1-level`.
The primary alone determines the gate. If acceleration FAILS: do NOT promote the level
ablation. Any different primary requires a new preregistration.

## PART 17 — Future confirmation boundary (frozen)

All historical results are EXPLORATORY. 2021–2026 are not untouched holdout periods.
If the primary passes FE1–FE8 historically:
`FUNDAMENTAL_EVENT_SHADOW_ELIGIBLE = YES` (but `SIGNAL_PROMOTION_READY = NO`).
Future confirmation requires ≥ 12 months of future event publications with frozen logic
and no redesign during the shadow period.

## PART 18 — Product boundary (unchanged)

The UI score remains the sole product-level ranking instrument. No BUY/SELL. Research
labels are never exposed to users. `SIGNAL_ENGINE_STARTED = NO`.
