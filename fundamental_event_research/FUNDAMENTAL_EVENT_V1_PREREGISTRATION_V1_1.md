# FUNDAMENTAL EVENT V1 — PREREGISTRATION **V1.1** (SUPERSEDING, PRE-EXECUTION)

Frozen: 2026-10-03, BEFORE any outcome inspection. `FUNDAMENTAL_EVENT_EXECUTED = NO`.
**This document is the ONLY binding execution specification after freeze.** Its SHA-256 is
recorded in `SESSION_HANDOFF.md` §68 and in `event_universe_v1_1.json`. It may not be
edited after execution; further corrections require V1.2.

## SUPERSESSION

**SUPERSEDES PRE-EXECUTION SPEC:**
`FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md` (V1.0), SHA-256
`5dff31d525a58b6474d06956eab5abff5a93ff898f3571358ac0d3b637c66fd1`

The V1.0 file and its hash remain preserved, immutable, unreferenced for execution.

**Reason for pre-execution supersession** — external review found material
specification/sample inconsistencies:

1. an unauthorized UI-Q5 ("top-attractiveness universe") eligibility condition implied by
   the V1.0 FE4 rationale ("a narrower universe (top-attractiveness events)") — the UI
   score was never intended as an eligibility filter;
2. feasibility/spec universe mismatch: the reported feasibility counts (11,489 eligible
   events, 278 qualifying dates) were computed on a universe inconsistent with the written
   architecture and (as the integrity audit later proved) with a defective comparator
   construction;
3. ambiguous previous-publication semantics ("immediately previous publication event")
   that would let a same-period correction act as the economic predecessor;
4. unreconciled event-stream row counts (9,615 vs 11,743 monthly; 3,410 vs 166 financial).

**No outcomes, returns, ICs, or performance statistics had been inspected at any point
before this freeze.** This is a clean pre-execution correction.

## What changed V1.0 → V1.1 (and what did not)

| item | V1.0 | V1.1 |
|---|---|---|
| UI score as eligibility | ambiguous (FE4 rationale) | **REMOVED — forbidden** (Issue 1) |
| primary universe | ambiguous | ALL PIT-ready eligible monthly-sales publication events (Issue 1) |
| previous-period semantics | previous publication event | previous DISTINCT monthly period, latest version known by event time (Issue 4) |
| prior-year comparator | canonical value, availability check | must be **PIT-known by the current published_at** (Issue 5) |
| corrections | separate events "for the corrected values" | separate publication rows; corrected values not in the canonical store → rows preserved, not feature events (Issue 6) |
| corrected-period originals | eligible | excluded (EI5: current-value version unverifiable) |
| FE2–FE8 thresholds | frozen | **unchanged** (Issue 12) |
| outcome contract | frozen | **unchanged** (Issue 11) |
| feasibility counts | 11,489 / 278 (invalid) | recomputed on the corrected universe (Issue 2) |
| integrity gates | leakage tests E1–E8 | retained + new **EI1–EI8 pre-execution gates** (Issue 13) |

The V1.0 leakage tests E1–E8 remain in force verbatim, supplemented by EI1–EI8.

## PART 1 — Primary event universe (frozen, Issue 1)

The primary universe is **ALL PIT-ready eligible monthly-sales publication events**
satisfying ALL of:

1. real Codal `published_at` (raw jalali stamp from the metadata backfill, converted with
   Asia/Tehran zone rules);
2. deterministic security mapping (canonical `security_id` via `core.securities`
   is-primary);
3. deterministic `period_end` (matched by exact title period, company + LetterType 58);
4. non-ambiguous match (MATCH_STRONG; MATCH_STRONG_CORRECTION events are separate
   publication rows, see PART 6);
5. `CURRENT_PERIOD_SALES > 0` AND current-value version provably the one published at
   this event (`current_value_version_known`): periods with any correction letter fail —
   the canonical store holds one value per period and cannot prove which version it is
   (EI5);
6. prior-year comparator (same company, same Jalali month one year earlier, month-end
   ±3 days) exists with value > 0 AND is PIT-known by the current `published_at`
   (PART 5);
7. a previous DISTINCT monthly period exists (PART 4) whose value and its own prior-year
   comparator are PIT-known by the current `published_at`;
8. `SALES_YOY_CURRENT`, `SALES_YOY_PREVIOUS`, hence `SALES_GROWTH_ACCELERATION`,
   computable;
9. deterministic `SIGNAL_ENTRY_DATE` exists on the canonical trading calendar.

**The UI score is NOT an eligibility filter and must never be used as one.** The research
question is: *does newly published monthly-sales acceleration itself contain predictive
information?* Any UI-conditioned variant (e.g., UI-Q5 restriction) requires a separate
future preregistration and is FORBIDDEN in V1.1.

PIT-knownness of a period's canonical value (frozen rules, auditable per event):

- `PUB_VERIFIED` — the period has ≥1 recovered publication and its latest `published_at`
  ≤ the event's `published_at` (whichever version the canonical value is, it was public
  by then);
- `PRE_WINDOW` — the period has no recovered publication and its period_end precedes the
  backfill search-window start (1400/01/01 = 2021-03-21): every letter for it predates
  the window, hence predates every event;
- otherwise (`FUTURE_PUB`, `UNVERIFIED_IN_WINDOW`, `ABSENT`) the comparator is NOT
  PIT-known → the event is not eligible. Residual caveat, documented: a letter published
  inside the window but missed by title parsing could be misread as PRE_WINDOW; title
  formats in the recovered corpus are uniform, and no such case was found among eligible
  events (9 in-window unverified cases exist and are excluded).

## PART 2 — Signal entry timestamp (frozen; unchanged)

`SIGNAL_ENTRY_DATE` = first canonical trading date strictly AFTER the Tehran local
calendar date of `published_at`. No same-day entry. All features computable from
information available by `published_at`.

## PART 3 — Current YoY (frozen, Issue 5)

```
SALES_YOY_CURRENT = CURRENT_PERIOD_SALES / SAME_MONTH_PRIOR_YEAR_SALES_KNOWN_AT_EVENT_TIME - 1
```

The prior-year comparator must itself be PIT-known by the current `published_at`
(PART 1 rule). If unavailable or not provably known: the event is not eligible. No
future-corrected prior-year value may leak backward.

## PART 4 — Previous-period semantics (frozen, Issue 4)

`SALES_YOY_PREVIOUS` is **NOT** the YoY of the immediately previous publication event.

For current event E with period P:

- `PREVIOUS_PERIOD` = the immediately preceding DISTINCT monthly accounting/activity
  period for the same security (max canonical period_end strictly < P);
- its value = the latest version of that period's report whose `published_at` ≤ E's
  `published_at` (implemented as: the canonical value is usable iff
  `PUB_VERIFIED`/`PRE_WINDOW` holds for that period at E's knowledge time; the canonical
  store holds one value per period, so "latest version" is approximated by a value
  provably public by event time — fidelity note, not a leak);

```
SALES_YOY_PREVIOUS = PREVIOUS_PERIOD_SALES / SAME_MONTH_PRIOR_YEAR_SALES(PREVIOUS_PERIOD)_KNOWN_AT_EVENT_TIME - 1
```

This structurally prevents a correction of the SAME current period from ever acting as
the acceleration predecessor (EI6). A same-period correction with `published_at` ≤ E's
time does not affect eligibility of E's predecessor (both versions known); a previous
period whose latest publication (e.g., a late correction) postdates E fails PIT-knownness
and E is excluded.

## PART 5 — Prior-year comparator for the previous period

Computed identically to PART 3 at `PREVIOUS_PERIOD` (its own Jalali month one year
earlier), and it must also be PIT-known by the **current** event's `published_at`.

## PART 6 — Correction events (frozen, Issue 6)

Corrections remain separate publication rows, never overwriting originals:

- every correction is a stream row with its own `event_id` (tracing_no), its own real
  `published_at` (knowledge time), and `is_correction = true`,
  `supersedes_event_id = original_event_id` (the original letter's tracing_no);
- originals keep their own knowledge time (EI7);
- per the frozen semantic, for a correction of period P, `CURRENT_PERIOD_SALES` is the
  corrected value published in that correction. **Data limitation:** corrected numeric
  values are not present in the canonical store (only letter metadata was recovered), so
  correction rows carry `CURRENT_PERIOD_SALES = NULL` and are NOT eligible for the
  primary acceleration feature in V1.1 (`CORRECTED_VALUE_NOT_IN_CANONICAL_STORE`);
  recovering correction contents is future work and would not change this document.
- an original publication of a period that later received a correction is excluded from
  the primary universe (`CURRENT_VALUE_VERSION_UNVERIFIABLE`, EI5): the canonical value
  cannot be proven to be the version published at the original time.

## PART 7 — Primary signal (frozen, Issue 7)

Primary: `fundamental-event-v1-acceleration`.

```
SALES_GROWTH_ACCELERATION = SALES_YOY_CURRENT - SALES_YOY_PREVIOUS
```

On each `SIGNAL_ENTRY_DATE` with ≥10 eligible event rows: cross-sectional midrank
percentile of `SALES_GROWTH_ACCELERATION`; higher acceleration = higher rank.
No UI-score filtering. No weights. No price, valuation, momentum, or volatility variables.

## PART 8 — UI score baseline (frozen, Issue 8)

For the IDENTICAL event rows and IDENTICAL signal-entry dates:

`UI_EVENT_RANK` = cross-sectional midrank percentile of the frozen UI score
(`canonical-v1-dev`, PIT source: the validated monthly PIT panel whose frozen ICs are
IC21 +0.1103 / IC63 +0.1543 / IC126 +0.1806 / IC252 +0.1571; per event, the latest
`ui_score` with `signal_date` ≤ `SIGNAL_ENTRY_DATE` for the same security).

No universe mismatch: the baseline uses exactly the rows available to the event signal.
The event signal does not require a UI score; FE6 (incremental test) is computed on the
identical-row subset where both signals are defined. The UI score is a BASELINE only.

## PART 9 — Quintiles (frozen, Issue 9)

Within each qualifying event date: Q1 = lowest acceleration rank, Q5 = highest.
For the UI baseline, separately: UI-Q1 = lowest UI rank, UI-Q5 = highest UI rank.
**UI-Q5 is never an eligibility filter.** Pooled event portfolio Q1–Q5 ranked within each
event-date cross-section; primary spread Q5 − Q1; no cross-date raw ranking.

## PART 10 — Ablation (frozen, Issue 10; unchanged)

`fundamental-event-v1-level`: `SALES_YOY_CURRENT` on the exact same event universe.
Diagnostic only; if acceleration FAILS, level is NOT automatically promoted.

## PART 11 — Outcome contract (frozen, Issue 11; unchanged)

PRIMARY: 63-trading-day adjusted excess return = stock adjusted forward return minus the
same-entry-date equal-weight forward return of the PIT-eligible product universe.
SECONDARY: 126d. DIAGNOSTIC: 21d. 252d excluded from all gates. Entry at SIGNAL_ENTRY_DATE
close; exit entry + H canonical trading days; price basis TSETMC pClosing + validated
adjustment pipeline.

## PART 12 — Date-level analysis (frozen; unchanged from V1.0)

A. date-level cross-section (dates with ≥10 eligible events): Spearman IC between the
signal and 63d excess return; mean/median IC, positive-date fraction.
B. pooled event portfolio quintiles (PART 9); event count, positive-fraction, Q5 − Q1.

## PART 13 — Gates FE1–FE8 (frozen; thresholds unchanged per Issue 12)

- **FE1 sample adequacy**: ≥ 24 qualifying signal-entry dates (≥10 eligible events each)
  AND ≥ 500 total eligible primary events. Recomputed on the corrected universe: **PASS**
  (see PART 15).
- **FE2**: mean IC63 ≥ **+0.05** (unchanged).
- **FE3**: positive-IC63 fraction ≥ **0.60** (unchanged).
- **FE4**: Q5−Q1 63d excess spread ≥ **+2.0pp** (unchanged; materiality floor set in
  V1.0 and retained — no universe implication).
- **FE5**: dependence-aware block-bootstrap 95% CI lower bound > 0 for IC63 and for the
  Q5−Q1 spread (unchanged).
- **FE6**: vs identical-row UI baseline (PART 8): ΔIC63 ≥ **+0.02** AND ΔSpread63 ≥
  **+1.0pp** (unchanged).
- **FE7**: all PIT/leakage tests (E1–E8) PASS (unchanged).
- **FE8**: max security contribution ≤ **5%** AND max full-year contribution ≤ **30%**
  (unchanged; pre-measured PASS on the corrected universe, PART 15).

No near-miss override. Thresholds were NOT changed because the specification was
corrected.

## PART 14 — Bootstrap settings (frozen; unchanged)

Seed **20261003** · B **2000** · 63d block = 3 months of signal-entry dates · 126d block
= 6 months · resampling unit: date.

## PART 15 — Corrected pre-outcome feasibility (measured 2026-10-03; no outcomes touched)

From `event_universe_v1_1.json` / `monthly_sales_events_universe_v1_1.parquet`
(`build_event_universe_v1_1.py`):

| quantity | value |
|---|---|
| total event rows (all publications) | 12,183 |
| eligible acceleration events (primary universe) | **6,091** |
| distinct signal-entry dates | 390 |
| qualifying signal-entry dates (≥10 eligible events) | **203** |
| events on qualifying dates | **5,442** |
| symbols | **160** |
| events by year | 2021: 556 · 2022: 962 · 2023: 1,213 · 2024: 1,327 · 2025: 1,268 · 2026: 765 |
| max symbol concentration | **1.03%** (دفرا) — limit 5% → PASS |
| max year concentration | **21.79%** (2024) — limit 30% → PASS |
| correction publication rows | 2,568 (0 eligible — corrected values not in store) |

FE1 pre-outcome: **PASS** (203 ≥ 24 dates; 6,091 ≥ 500 events). FE8 pre-outcome: **PASS**.

Feature sanity: SALES_YOY_CURRENT median +0.466 (p1 −0.740, p99 +5.267);
SALES_GROWTH_ACCELERATION median 0.000 (p1 −4.067, p99 +3.801).

Only these corrected counts may be used for FE1/FE8.

## PART 16 — Event-stream reconciliation (Issue 3; exact, before freeze)

| counter | value |
|---|---|
| canonical_monthly_rows | 12,180 |
| canonical_rows_with_published_at (DB) | 0 (no DB write-back was ever performed) |
| canonical_rows_with_published_at (recovered via backfill matching) | 9,615 |
| matched_codal_publication_rows | 12,183 |
| unique_source_report_ids | 12,183 |
| unique_tracing_nos | 12,183 |
| unique_security_periods | 9,615 |
| original_publications | 9,615 |
| corrections | 2,568 |
| multiple_publications_same_period | 2,128 (all are original+correction(s) pairs) |
| duplicate_source_report_ids | **0** |
| one_source_report_matched_to_multiple_canonical_rows | **0** |
| ambiguous_excluded | 6 |
| not_found | 2,559 |
| final_event_stream_rows | **12,183** |

Reconciliation of the previously reported discrepancy: 11,743 old stream rows = 9,615
original publications + 2,128 latest-correction rows; the old stream dropped 440 earlier
correction letters and (in its financial section) contained 166 corrupt leaked-state rows
(quarantined; financial stream rebuild is a separate future task — the financial report
path remains out of scope for V1.1).

**Hard requirement met:** one actual Codal publication appears exactly once in the
canonical research event stream (12,183 rows = 12,183 unique tracing_nos, each verified
against the raw backfill cache; multi-publication periods are legitimate correction
semantics). `EVENT_STREAM_UNIQUENESS = PASS`.

## PART 17 — Pre-execution integrity gates EI1–EI8 (new, Issue 13; all must PASS before any return metric)

- **EI1** one row per actual Codal publication: stream rows == distinct source ids
  (12,183 == 12,183); 100% of rows resolve to a raw-cache letter. → PASS
- **EI2** no unexplained duplicate tracing_no/source_report_id: 0 duplicates; 0 letters
  mapped to multiple canonical rows; every multi-publication period is a documented
  correction semantic. → PASS
- **EI3** `published_at` is the real Codal publication time: 100% raw-jalali parse, wall
  time and Tehran date match the raw cache, zone-rule UTC conversion (DST-correct). → PASS
- **EI4** `signal_entry_date` strictly after the publication local date (all rows). → PASS
- **EI5** current period and prior-year comparable are PIT-known: enforced by eligibility
  (corrected-period originals excluded; comparator knownness PUB_VERIFIED/PRE_WINDOW
  only; mix among eligible: prior-year 5,346 PUB_VERIFIED + 745 PRE_WINDOW; previous
  period 6,090 PUB_VERIFIED + 1 PRE_WINDOW). → PASS
- **EI6** previous-period comparator is a DISTINCT earlier period: 0 violations;
  same-period corrections structurally excluded as predecessors. → PASS
- **EI7** corrections preserve historical knowledge and do not overwrite originals:
  0 order violations; originals retained with original knowledge time; correction rows
  carry no canonical value. → PASS
- **EI8** outcomes physically inaccessible to construction code: the construction script
  reads identity tables, canonical monthly sales history, the trade-date calendar, and
  the raw letter cache only — no adjusted prices, returns, or outcome artifacts. → PASS

## PART 18 — Decision rule (frozen; unchanged)

Primary: `fundamental-event-v1-acceleration`. The primary alone determines the gate. If it
FAILS: the level ablation is NOT promoted. Any different primary requires a new
preregistration.

## PART 19 — Future confirmation and product boundaries (frozen; unchanged)

All historical results are EXPLORATORY; 2021–2026 are not untouched holdouts. Passing
FE1–FE8 yields `FUNDAMENTAL_EVENT_SHADOW_ELIGIBLE = YES` but never
`SIGNAL_PROMOTION_READY = YES`. The UI score remains the sole product-level ranking
instrument. No BUY/SELL. Research labels never exposed to users. `SIGNAL_ENGINE_STARTED
= NO`.

## PART 20 — Artifacts

- Superseded (preserved, immutable): `FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md`
  (SHA-256 `5dff31d525a58b6474d06956eab5abff5a93ff898f3571358ac0d3b637c66fd1`)
- Binding spec: this file (SHA-256 recorded in `SESSION_HANDOFF.md` §68 and
  `event_universe_v1_1.json` after freeze)
- Universe/audit evidence: `build_event_universe_v1_1.py` ·
  `event_universe_v1_1.json` · `monthly_sales_events_universe_v1_1.parquet`
  (SHA-256 `bcd69f109fd1a3be…` — full hash in the JSON)
- Prior audit record: `audit_event_stream_v1.py` · `EVENT_STREAM_INTEGRITY_AUDIT.md` ·
  `event_stream_audit.json`
