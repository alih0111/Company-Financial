# EVENT STREAM INTEGRITY AUDIT — FUNDAMENTAL EVENT V1 (final pre-registration gate)

Executed: 2026-10-03. Script: `audit_event_stream_v1.py` (independent re-implementation of
the deterministic matcher; no outcomes, no ICs, no returns touched). Machine-readable:
`event_stream_audit.json`. No threshold was changed; nothing was tuned to pass.

## Verdict

| gate | result |
|---|---|
| MONTHLY_EVENT_STREAM_INTEGRITY | **PASS** |
| MONTHLY_EVENT_TIMESTAMP_INTEGRITY | **PASS** (1 documented non-blocking tz defect in the OLD artifact, fixed in the canonical artifact) |
| MONTHLY_EVENT_COVERAGE | **PASS** (9,546 publication events; 8,270 eligible; 161 symbols; 2021–2026) |
| MONTHLY_FUNDAMENTAL_REVISION_FEATURES_READY | **YES** (re-built with correct same-company comparators) |
| FUNDAMENTAL_EVENT_PREREGISTRATION_READY | **YES** (design frozen 2026-10-02 unchanged; measured pre-outcome counts corrected by this audit; FE1/FE8 pre-checks PASS) |

**STOP after this audit. The event signal is NOT executed** (`FUNDAMENTAL_EVENT_EXECUTED = NO`).

## 1. Monthly reconciliation: 9,615 vs 11,743 — RESOLVED, legitimate one-to-many

Independent matcher reproduces the frozen stats exactly: 12,180 canonical monthly events =
**7,487 MATCH_STRONG + 2,128 MATCH_STRONG_CORRECTION + 6 AMBIGUOUS + 2,559 NOT_FOUND**.

- 9,615 = 7,487 + 2,128 canonical events with a real recovered publication time.
- The old stream's 11,743 monthly rows = 9,615 original-publication rows + 2,128 rows for
  the *latest* correction letter of each MATCH_STRONG_CORRECTION event
  (7,487 periods × 1 row; 2,128 periods × 2 rows; verified row-by-row).
- The canonical artifact now carries **12,183 publication rows = 9,615 originals + 2,568
  correction letters**: the audit found 440 additional correction letters the old stream
  had dropped (it kept only the latest correction per event). One row per actual Codal
  publication is now literally true.

## 2. Financial reconciliation: 3,410 vs 166 — RESOLVED as a construction DEFECT; financial stream QUARANTINED

Independent matcher reproduces: 8,157 = **595 MATCH_EXACT + 2,416 MATCH_STRONG +
399 MATCH_STRONG_CORRECTION + 2,665 AMBIGUOUS + 2,082 NOT_FOUND**; recovered = 3,410.

- By design MATCH_EXACT events keep their canonical `published_at` in the DB and are not
  duplicated into the stream → 2,815 events should have produced ~3,249 stream publication
  rows (2,416 originals + 833 correction letters).
- Actual old stream: **166 financial rows, all defective.** `match_pub_times.py` never
  emitted original rows for financial MATCH_STRONG events; the 166 rows exist only where
  loop state leaked from the monthly section: every one carries the SAME constant
  `published_at` (2026-08-29 15:33+03:30, the last monthly letter's stamp) and a canonical
  report UUID as `source_report_id`. They represent no actual publication.
- Disposition: the 166 rows are **quarantined** (documented, not deleted; the old parquet
  is preserved for lineage). Financial event research remains
  `FINANCIAL_REPORT_EVENT_TIMING_READY = PARTIAL`; a correct financial-stream rebuild is a
  separate future task. This does NOT affect the monthly-only frozen preregistration.

## 3–5. One row per publication · duplicates · corrections

- `event_id` (= Codal tracing_no) duplicates in monthly stream: **0** (12,183 unique).
- 12,183/12,183 rows resolve to a letter in the raw backfill cache
  (`historical_codal_backfill/output/pub_backfill`, 27,497 unique letters, 474 files);
  0 rows unresolvable. All 2,568 correction rows verified: title contains اصلاحیه, same
  (symbol, period), LetterType 58, own tracing_no and own PublishDateTime.
- Each canonical event maps to exactly 1 original letter (max per event = 1); canonical
  (company, period_end) duplicates in `fundamentals.monthly_activities`: **0**.
- No tracing_no appears under more than one symbol in the raw cache (0).
- `ingestion.reports.tracing_no` is NULL on all DB rows (ground truth; the identity keys
  live in the raw cache + stream artifact). DB `published_at` remains NULL for the 12,180
  legacy monthly rows — publication times exist ONLY in the event-stream artifacts; no DB
  write-back was performed (and none is needed for the monthly preregistration).
- Corrections: **0** cases of correction ≤ original publication time (69 same-day
  corrections exist and are kept separately); originals retain their own knowledge time;
  corrections never overwrite (E6 PASS structurally).
- Corrections carry `sales_current_rial = NULL` in the canonical artifact: corrected
  numeric values were never ingested, so a correction row cannot honestly claim "the
  values published at that time". Per frozen PART 1 items 4–5 they are therefore
  stream-rows-but-not-events (`ineligibility_reason = CORRECTION_VALUE_UNAVAILABLE`).
  This is a value-fidelity determination, not a threshold change.

## 6. Match-status audit

Re-run independently from the frozen hierarchy; both monthly and financial stats
reproduce exactly (tables above). Monthly AMBIGUOUS = 6 events excluded; NOT_FOUND =
2,559 excluded. The old stream's monthly `match_status` field matched the independent
matcher on every row.

## 7. Timestamp integrity (E1/E2) — PASS

- 12,183/12,183 raw jalali `PublishDateTime` strings parse; Tehran wall time and Tehran
  calendar date match the raw cache on every row; 0 parse failures; 0 fabricated stamps.
- Old-stream defect found: it stamped every row with a FIXED +03:30 offset. During Iran's
  DST windows (2021-03-22..2021-09-21, 2022-03-22..2022-09-21, true offset +04:30),
  **1,809 of 11,743 rows carry UTC instants 1h late** (histogram: 9,934 × 0h, 1,809 × +1h).
  Non-blocking: `SIGNAL_ENTRY_DATE` uses the Tehran calendar DATE of publication, which is
  unaffected by the offset error. The canonical artifact re-converts with the Asia/Tehran
  zone rules (`published_at` UTC + `published_at_tehran` local + raw jalali retained).
- E2: for all 9,615 originals, `signal_entry_date` is strictly AFTER the Tehran
  publication date AND equals the first canonical trading date after it (9,615/9,615).
- Sanity: 12,073/12,183 publications occur after period end. The 110 exceptions are
  genuine Codal letters filed 0–6 days BEFORE their Jalali Esfand month-end (early annual-
  close filings); matching verified by exact title period; entry rule unchanged.

## 8. Coverage & concentration (eligible events)

- **8,270 eligible events** (9,615 originals − 1,081 no prior-year comparator & no previous
  publication − 195 no previous-publication YoY − 69 invalid canonical sales), 161 symbols,
  2021–2026: 585 / 1,407 / 1,663 / 1,757 / 1,814 / 1,044.
- Max security share **0.77%** (شبصیر) ≤ 5% · max year share **21.93%** (2025) ≤ 30% → FE8 pre-check PASS.
- 428 distinct signal-entry dates; **230 qualifying dates (≥10 events); 7,662 events on
  qualifying dates** → FE1 pre-check PASS (≥24 dates, ≥500 events).
- E4: prior-year comparator publication time provably earlier for 7,458/8,270 eligible;
  812 not recoverable (comparator letter unmatched) — soft evidence: **0 period-order
  violations across 9,451 consecutive publication-sequence pairs**; 0 hard violations.
  Events with a proven leak would be excluded (`PRIOR_YEAR_NOT_KNOWN_AT_EVENT_TIME`): 0.
- Feature sanity: SALES_YOY_CURRENT median **+0.458** (p1 −0.76, p99 +5.94) — plausible for
  an inflationary market; SALES_GROWTH_ACCELERATION median **+0.002** centered (p1 −4.21,
  p99 +4.21). Contrast with the old defective panel (median +3.22, p99 +3,069 — invalid).

## 9–10. Canonical artifact & pre-outcome features

`fundamental_event_research/monthly_sales_events_pit.parquet` — 12,183 publication rows,
SHA-256 `15d39e5389dc47de82d89d62d18debfc272d88bcbda5ca95f05a886d6fadefdf`:

- one row per actual Codal publication (`event_id` = tracing_no; `publication_role`
  original/correction; `supersedes_tracing_no` links corrections);
- `published_at_raw_jalali`, `published_at_tehran`, `published_at` (UTC, zone-correct),
  `tehran_date`, `signal_entry_date` (frozen rule: first canonical trading date strictly
  AFTER the Tehran calendar date; no same-day entry);
- PRE-OUTCOME features only, frozen formulas, originals only:
  `sales_current_rial` · `sales_same_month_prior_year_rial` (same company, same Jalali
  month one year earlier, ±3-day month-end match) · `SALES_YOY_CURRENT` ·
  `SALES_YOY_PREVIOUS` (immediately preceding publication in the company's sequence,
  strict reading — no skipping back over invalid publications) ·
  `SALES_GROWTH_ACCELERATION` · 3-publication trajectory availability flag
  (`SALES_YOY_PREV2`, `TRAJECTORY_3PUB_AVAILABLE` — feasibility only, NOT a feature);
- `prior_year_pub_verified`, `eligible_base`, `ineligibility_reason`, `event_eligible`.
- No forward returns, no outcome join, no IC anywhere in the artifact or the script.

## Defect ledger (superseded artifacts; originals preserved for lineage)

| artifact | defect | disposition |
|---|---|---|
| `research_bundle/fundamental_event_pre_outcome_panel.parquet` (SHA-256 2d12f11b…) | prior-year lookup was NOT restricted to the event's company (first cross-company month match won, nondeterministic) → all YoY/acceleration values invalid | SUPERSEDED by the canonical artifact |
| `research_bundle/fundamental_event_feasibility.json` | counts derived from the defective panel | measured counts corrected by this audit; frozen gate THRESHOLDS unchanged |
| `research_bundle/event_stream_pit.parquet` (SHA-256 64792174…) | monthly section valid (proven); financial section corrupt (166 leaked-state rows); monthly correction letters incomplete (2,128 of 2,568); fixed-offset tz | monthly superseded by canonical artifact; financial QUARANTINED — rebuild is a separate future task |
| `historical_codal_backfill/match_pub_times.py` (2ebd2cb1…) | financial emission block + loop-state leak | superseded by `fundamental_event_research/audit_event_stream_v1.py` for any future rebuild |
| `historical_codal_backfill/fundamental_event_feasibility.py` (398c29de…) | cross-company YoY bug | superseded by this audit |

Note on the frozen preregistration: `FUNDAMENTAL_EVENT_V1_PREREGISTRATION.md`
(SHA-256 `5dff31d525a58b6474d06956eab5abff5a93ff898f3571358ac0d3b637c66fd1`) is
UNEDITED. Its PART 15 *measured* numbers were computed with the defective panel and are
corrected here: eligible 11,489 → **8,270** · qualifying dates 278 → **230** · events on
qualifying dates 9,810 → **7,662** · symbols 164 → **161**. FE1 and FE8 pre-checks PASS on
the corrected counts; the frozen design, formulas, entry rule, gates FE1–FE8, bootstrap
settings, and leakage tests E1–E8 are unchanged.

## Execution-relevant determinations recorded by this audit (for the record)

1. Correction publications are preserved as stream rows but are not feature events
   (`CORRECTION_VALUE_UNAVAILABLE`) — corrected values were never ingested.
2. "Immediately preceding publication" is the strict immediate predecessor in the
   company's publication sequence; if its YoY is undefined the event is ineligible
   (literal reading of frozen PART 3; no back-skipping).
3. Comparator-period letters that could not be matched (812 events) are kept eligible on
   sequence-monotonicity evidence (0/9,451 violations) and are flagged
   `prior_year_pub_verified = NULL` for execution-time transparency.
4. 110 early-filed Esfand letters (published before period end) are genuine publications;
   kept; entry rule unchanged.
