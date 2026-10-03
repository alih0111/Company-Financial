# SIGNAL ENGINE — PREREGISTRATION V1

Frozen: 2026-10-02, BEFORE any signal execution. `SIGNAL_ENGINE_EXECUTED = NO` at freeze
time. This document may not be edited after the first signal evaluation runs; corrections
require `SIGNAL_ENGINE_PREREGISTRATION_V2`.

Separation from the UI score (PART 1, binding): the validated `canonical-v1-dev` UI score
remains EXACTLY as validated (`UI_SCORE_READY_FOR_PRODUCT_USE = YES`) — a company/fundamental
attractiveness ranking, historically useful at medium/long horizons within the available
product universe, not a probability, not an expected return, not a trading signal. The Signal
Engine may CONSUME it as one input / eligibility layer; it may NOT change its weights, DQ,
categories, calibration, or replace it. No v2.1/v2.2 research is reopened.

## 1. Objective (frozen)

The Signal Engine answers a question the UI score does not ask:

> Given an otherwise attractive stock, is the current market/price state favorable enough
> to consider acting now?

It is NOT a rename of the UI score and never produces BUY/SELL in research.

## 2. Targets (frozen)

- PRIMARY: **63-trading-day forward adjusted excess return** = stock adjusted forward return
  minus the same-date equal-weight mean adjusted forward return of the eligible universe.
- SECONDARY: 126-trading-day adjusted excess return.
- DIAGNOSTIC ONLY: 21-trading-day return (raw and excess).
- 252d is NOT a Signal Engine target (too slow for entry timing); it may be reported
  descriptively only.
- Price basis: canonical TSETMC `pClosing` + the validated adjustment pipeline
  (FORWARD_RETURN_ADJUSTED_V1 semantics extended to 126d; the 252d descriptive path
  identical). Cadence: MONTHLY (the frozen 63 signal dates).

## 3. Allowed inputs (inventory measured: `input_inventory.json`, 63 dates, 13,409 scored
rows of the 13,481-row grid; availability = computable ex ante at the signal date)

| input | source | PIT semantics | availability | validated? |
|---|---|---|---|---|
| mom_20 / mom_30 / mom_60 / mom_90 | raw pClosing series (canonical basis) | trade dates ≤ signal date | 100.0/99.9/99.8/99.7% | derivation only; validated pipeline for 30d |
| dist_high60, drawdown_60 | raw pClosing, trailing 60d window | trade dates ≤ signal date | 99.8% | no (new derivation) |
| vol_30 | raw pClosing, trailing 21 returns | trade dates ≤ signal date | 99.9% | yes (UI score field) |
| downside_vol_30 | raw pClosing, negative returns only | trade dates ≤ signal date | 97.5% | no (new derivation) |
| liq_30 (mean qTotCap, 30d) | raw TSETMC qTotCap | trade dates ≤ signal date | **57.3%** (canonical adjusted series lacks trade values; raw source has them) | no; DIAGNOSTIC ONLY — no eligibility cutoff may use it |
| mkt_breadth, mkt_disp21, mkt_vol_level | cross-sectional over the covered universe, ex ante | trade dates ≤ signal date | 99.9% | demonstrated ex ante in research_decision_panel.json |
| ui_score + 4 category scores | frozen canonical-v1-dev reconstruction (`ui_score_historical_v1`) | full PIT contract already validated | 100% | yes (validated 2026-10-02) |
| return targets ret_21/63/126 | FORWARD_RETURN_ADJUSTED_V1 semantics | outcome only | 100/98.4/96.9% | yes |

NOT allowed: external macro data, new datasets, future-defined regime labels, the 651
non-covered issuers (no ingested fundamentals), anything using future returns.

## 4. PIT contract and leakage tests (frozen; implemented with the pipeline build)

At signal date T every feature must be known by T: financial inputs `published_at ≤ cutoff`;
market data `trade_date ≤ T`; observed snapshots `collected_at ≤ cutoff`; shares per the
frozen historical contract (TSETMC chain + Codal knowledge_from); current zTitad is NEVER
used historically. Forbidden: future returns, future constituents, future corporate
actions, current-data-backward, retrospective regime labels.

Frozen leakage tests (must pass before any evaluation output is trusted):
L1 per-feature max(source timestamps) ≤ signal date for every row;
L2 leave-one-date-out: dropping date T's outcome must not change any feature row of T;
L3 feature values for a symbol at T identical whether or not later dates exist in the frame;
L4 market-state variables recomputed on the covered universe as of T only;
L5 UI-score inputs byte-identical to the frozen `ui_score_historical_v1` (no re-tuning);
L6 share inputs per the historical contract (no zTitad leakage — already test-enforced in
the Engine suite).

## 5. Eligible universe (frozen)

The SAME available product universe (238-symbol research grid; full-market claims are not
made — the survivorship/coverage caveat of the UI validation carries over verbatim).
Eligibility at T: UI-score eligible (present in `ui_score_historical_v1`) AND valid current
price AND sufficient price history for the chosen features' lookbacks. **Liquidity is
recorded as a FEATURE only** — no liquidity cutoff is created in this task (none was
previously frozen).

## 6. Architectures (exactly two; no others permitted)

**ARCHITECTURE A — SCORE + TIMING OVERLAY (preferred).** The validated UI score defines
company attractiveness (eligibility + attractiveness layer). The Signal Engine adds only a
timing/market-state layer computed from the allowed price/risk/market-state inputs.
Conceptually: Signal = fundamental attractiveness + entry-timing quality (e.g., the timing
layer scales or gates WITHIN attractiveness groups; it never overrides the attractiveness
ordering with unrelated factors). Interpretability high; overfitting risk low (few timing
inputs); product clarity high ("good company + good moment"); PIT safety inherited from the
UI reconstruction; expected turnover moderate (attractiveness layer is sticky: 33.6%
measured top-quintile turnover).

**ARCHITECTURE B — UNIFIED SIGNAL RANK.** UI score and timing variables enter one frozen
cross-sectional rank. Interpretability medium (weights blur the two questions); overfitting
risk medium (more free combination choices); product clarity medium; data availability same;
PIT safety same; expected turnover higher (timing ranks churn faster than the score).

Comparison is conceptual only. The first executed experiment uses **A as PRIMARY**; B is
preregistered as the single alternative — no third architecture, no hybrid.

## 7. Output semantics (research labels; no thresholds defined here)

Provisional research labels only, never exposed to users: FAVORABLE = company attractive
AND timing state favorable; NEUTRAL = no strong timing evidence; UNFAVORABLE = timing state
argues against entry despite company score. Numeric label thresholds are NOT defined in this
document (none exists in a frozen rule); they would be frozen in the execution spec and
never calibrated against future outcomes.

## 8. Evaluation design (frozen)

Development 2021–2023: may inform design within the PART 11 limits. Historical exploratory
evaluation: 2024–2026 available data — **EXPLORATORY, previously inspected, never a
holdout**. True confirmation requires the future shadow protocol (PART 12) on dates after
this preregistration. All historical outputs labeled EXPLORATORY_HISTORICAL.

## 9. Evaluation metrics (frozen before execution)

RANKING: mean/median date-level Spearman IC (63d excess primary; 126d secondary; 21d
diagnostic); positive-IC fraction. ECONOMIC: top-vs-bottom quintile excess-return mean and
median spread; block-bootstrap CI (blocks = horizon/21 months, B=2000). STABILITY: year-by-
year IC, quarter-level behavior, dependence-aware bootstrap. OPERATIONAL: monthly top-
quintile and top-decile Jaccard turnover, coverage, missingness. INCREMENTAL: the SAME
metrics computed for the UI score alone on IDENTICAL dates/universe, reported side by side.

## 10. Success gates (frozen; thresholds anchored to the measured UI-score baselines on the
same grid/target: IC63(excess) +0.154 with pf 0.935, Q5−Q1 excess +4.9pp, top-quintile
turnover 0.336, coverage 100%/86.5%)

- **SG1 ranking floor**: mean date-level Spearman IC63 (excess) ≥ **+0.05** — rationale:
  ~1/3 of the validated UI baseline; a materially positive standalone level; below it the
  timing layer is noise.
- **SG2 stability**: positive-IC fraction ≥ **0.60** AND IC63 positive in **≥5 of 6
  calendar years** — rationale: 0.5 is chance; the UI score showed 0.935/6-of-6, so a
  timing signal that flips sign in most years is not robust; 0.60 on 62 valid monthly dates
  is a meaningful stability floor, deliberately far below the UI's own level.
- **SG3 economic separation**: mean Q5−Q1 excess spread ≥ **+2pp** AND its block-bootstrap
  95% CI excludes 0 — rationale: 40% of the UI baseline spread; the CI requirement is the
  dependence-aware proof (monthly observations overlap at 63d).
- **G4 dependence robustness**: 95% CI of mean IC63 (blocks = 3 months) excludes 0.
- **SG5 incremental value (the decisive gate)**: on identical dates/universe,
  **ΔIC63 = IC_signal − IC_UI ≥ +0.02** AND **Δ(Q5−Q1 excess) ≥ +1.0pp** — rationale: +0.02
  is the effect size previously treated as a material factor-level improvement in this
  project; requiring BOTH prevents a "different but not better" signal from passing. If the
  Signal Engine does not beat the UI score, it has not justified its complexity.
- **SG6 operational**: mean monthly top-quintile turnover ≤ **0.50** — rationale: 1.5× the
  measured UI layer (0.336); a timing overlay will churn more, but beyond 0.50 it is not
  operationally meaningful at monthly cadence.
- **SG7 coverage**: ≥ **85%** of eligible rows with complete signal inputs — rationale:
  matches the observed long-horizon return coverage (86.5%); below it, exclusions
  distort the cross-section.
- **SG8 integrity**: all leakage tests L1–L6 pass; `PIT_BACKDATING_PRESENT = NO`; no
  data-integrity violation.

Gates apply on Development + full-window exploratory results as PRE-REGISTERED; thresholds
were frozen before execution and are not chosen to pass.

## 11. Research degrees of freedom (binding)

Exactly 2 architectures (A primary, B alternative). First executed experiment: **1 primary
candidate + at most 2 preregistered ablations**. Every candidate must state its economic
rationale BEFORE execution. Forbidden: weight search, feature mining, genetic/grid
optimization, post-hoc threshold changes, adding factors that lack an ex-ante economic
rationale. The candidate instantiation (which timing inputs from §3, and the A-overlay
combination rule) is frozen in an execution-time addendum under these limits — any input
outside §3 requires a new preregistration.

## 12. Future shadow protocol (frozen)

SIGNAL_RESEARCH_READY: this preregistration exists AND the historical exploratory gate
(SG1–SG8) is evaluated once and reported. SIGNAL_PROMOTION_READY: requires, in order,
(1) SG1–SG8 PASS on the historical exploratory evaluation, (2) a future shadow evaluation of
≥ **12 future monthly signal dates** (first date strictly after the execution freeze) with
frozen logic throughout, no failed-month replacement, no early promotion, no threshold
changes, and (3) the shadow meeting SG1/SG2/SG3/SG5 computed on shadow data against the UI
score on identical dates. Only SIGNAL_PROMOTION_READY authorizes production Signal Engine
recommendations. The UI score remains in the product throughout regardless.

## 13. Product boundary (frozen)

Current UI score: READY FOR PRODUCT USE — it stays visible and unchanged. Signal Engine:
NOT READY; research labels are never exposed to users; no BUY/SELL exists at any stage of
this track until SIGNAL_PROMOTION_READY and a separate product decision.

## 14. Unresolved blockers (recorded, not worked around)

- Survivorship/universe: the 651 non-covered Codal issuers remain un-ingested and
  unscorable; the effect on the ranking conclusion is UNRESOLVED (three-month LT58 filer
  union is not a definitive market census). The Signal Engine inherits this caveat.
- liq_30 coverage 57.3% — liquidity stays a feature, never an eligibility rule.
- 21d is diagnostic only: the UI-score evidence at 21d was economically WEAK (mean spread
  ~0); the Signal Engine makes no 21d claims.

## Execution boundary

`SIGNAL_ENGINE_EXECUTED = NO` at freeze time. Execution (input pipeline + leakage tests +
one primary candidate + ≤2 ablations + SG1–SG8 evaluation) is authorized as the NEXT task
under this preregistration and nothing more.

---

# EXACT EXPERIMENT SPECIFICATION (preregistration amendment, frozen 2026-10-02)

This amendment was written BEFORE any Signal Engine execution and WITHOUT inspecting any
Signal Engine return outcome. It freezes the exact candidates, universes, missing-data
behavior, baselines, gates, turnover convention and bootstrap settings. `SIGNAL_RESEARCH_READY`
returns to YES only once this section is hash-frozen (SHA-256 recorded in SESSION_HANDOFF
§60) and the L1-L7 leakage tests are implemented with the pipeline build.

## E1 — Primary candidate `signal-v1-A` (Architecture A, SCORE + TIMING OVERLAY)

Universe (two stages, both PIT):
1. **Base universe (per date)**: the frozen available product universe — the rows of
   `ui_score_historical_v1` for that signal date (63 dates; covered-universe survivorship
   caveat inherited verbatim).
2. **Attractiveness universe (UI-Q5)**: rank the base universe by the frozen UI score
   (descending, exact index convention from the completed UI-score validation: sorted list
   `rs`, Q5 = `rs[4*floor(n/5) : n]` with n = base-universe count). **Exactly the top
   index-quintile; no absolute score cutoff (no 50/60/70), no decile variant, no threshold
   search.** Rationale: reuses the established product quintile convention; not tuned on
   Signal Engine returns.
3. **Timing-eligible universe**: UI-Q5 names for which ALL THREE timing features are
   computable at that date.

Timing features (all from canonical raw pClosing, all lookbacks end at or before the signal
date):
- `Momentum60` = pClosing(T) / pClosing(60 trading rows earlier) − 1 — higher more favorable
- `DistanceFrom60DayHigh` = pClosing(T) / max(pClosing over the trailing 60 trading rows
  inclusive of T) − 1 (≤ 0) — closer to the high (less negative) more favorable
- `Volatility30` = stdev of the last 21 daily returns within the trailing 30-row window —
  lower more favorable; the RANK enters as InverseVolatility30

Each feature is converted to a cross-sectional **midrank percentile in [0,1] within the
timing-eligible UI-Q5 universe** (same midrank semantics as the production scorer).

**TIMING_CORE = (1/3)·Momentum60Rank + (1/3)·DistanceFrom60DayHighRank + (1/3)·InverseVolatility30Rank**

**FINAL_SIGNAL_RANK_A = cross-sectional rank(percentile) of TIMING_CORE inside the
timing-eligible UI-Q5 universe.** The UI score performs attractiveness selection ONLY; there
is no second weighting of the UI score anywhere in Architecture A.

Missing-data behavior (frozen): ALL THREE timing features required; if ANY is missing the
company is not timing-eligible for that date. No 2-of-3 renormalization. No imputation.
Coverage is reported against the UI-Q5 denominator (SG7 applies to this denominator).

## E2 — Ablation `signal-v1-A-momentum`

Same UI-Q5 attractiveness universe and same timing-eligibility rule.
**TIMING_MOMENTUM = (1/2)·Momentum60Rank + (1/2)·DistanceFrom60DayHighRank**
(volatility term removed). Purpose: isolate whether inverse volatility adds incremental
timing value. No further momentum variants.

## E3 — Alternative architecture `signal-v1-B`

Universe: the full base PIT-eligible universe restricted to names with ALL THREE timing
features (no UI-Q5 stage).
- UI_RANK = cross-sectional percentile of the frozen UI score within that universe
- TIMING_CORE as in E1 (computed within that same universe)
- **FINAL_SIGNAL_B = 0.50·UI_RANK + 0.50·TIMING_CORE** — weights frozen exactly; no weight
  search. All three timing inputs required; otherwise the security/date has no signal-v1-B.

## E4 — Candidate count (frozen)

Exactly three candidates may ever be executed under this preregistration: `signal-v1-A`
(primary), `signal-v1-A-momentum` (ablation), `signal-v1-B` (alternative architecture).
No fourth candidate, no alternative weights, no alternate windows, no threshold search.

## E5 — Baselines (frozen; identical-universe rule)

- `signal-v1-A` and `signal-v1-A-momentum`: baseline = **UI-score rank WITHIN the same
  timing-eligible UI-Q5 subset** (same rows, same dates).
- `signal-v1-B`: baseline = **UI-score rank within the same full timing-eligible universe**.
Never compare a Signal Engine metric on one universe against a UI-score metric computed on a
different universe.

## E6 — Q1/Q5 semantics (frozen)

Architecture A: Q1-Q5 are quintiles of TIMING_CORE inside the UI-Q5 attractiveness subset
(Signal Q5 = most favorable timing among already-attractive companies). Architecture B:
Q1-Q5 are quintiles of FINAL_SIGNAL_B inside the full signal-eligible universe. Never mixed.

## E7 — Outcome target (frozen)

Primary: 63-trading-day adjusted **excess** return = stock adjusted 63d return − equal-weight
adjusted 63d return of the SAME DATE'S full base PIT-eligible product universe (for
Architecture A the reference is the FULL universe, never the UI-Q5 subset mean). Secondary:
126d excess. Diagnostic: 21d excess. 252d excluded from all Signal V1 gates.

## E8 — Gates (final; SG2b amended before execution)

For the PRIMARY `signal-v1-A`, exploratory historical PASS requires ALL of:
- **SG1**: mean date-level Spearman IC63 (excess) ≥ +0.05
- **SG2a**: date-level positive IC63 fraction ≥ 0.60
- **SG2b (amended)**: positive mean IC63 in ≥ 4 of the 5 FULL calendar years 2021-2025;
  2026 reported descriptively only and excluded from this gate (2026 is incomplete — the
  original ≥5-of-6 rule was inappropriate). Amendment made before execution, without
  inspecting any Signal Engine result. The overall date-level positive-fraction gate (SG2a)
  remains frozen separately.
- **SG3**: mean Signal-Q5 − Signal-Q1 63d excess ≥ +2.0pp AND the dependence-aware
  block-bootstrap 95% CI lower bound > 0
- **SG4**: block-bootstrap 95% CI lower bound for mean IC63 > 0
- **SG5 (incremental, BOTH required)**: Δ mean IC63 (signal − UI baseline on IDENTICAL rows)
  ≥ +0.02 AND Δ Q5−Q1 63d excess spread ≥ +1.0pp
- **SG6**: mean monthly top-signal-quintile turnover ≤ 0.50 (Architecture A: top TIMING
  quintile inside UI-Q5)
- **SG7**: ≥ 85% of UI-Q5 attractiveness rows have all three timing inputs
- **SG8**: all leakage/PIT tests PASS and no known integrity violation
No near-miss override. No discretionary PASS.

## E9 — Secondary-candidate decision rule (frozen)

1. Evaluate `signal-v1-A` against SG1-SG8. 2. Evaluate `signal-v1-A-momentum` only to
isolate the inverse-volatility contribution. 3. Evaluate `signal-v1-B` only as an
architecture comparison. **If A fails: SIGNAL_V1_PRIMARY_GATE = FAIL; A-momentum and B are
NOT auto-promoted regardless of their historical IC.** Any future switch of primary
architecture requires a NEW preregistration. This prevents winner-picking after results.

## E10 — Turnover definition (frozen)

For every consecutive pair of monthly signal dates (both dates must exist in the grid):
top set = the top 20% of FINAL_SIGNAL_RANK within that candidate's signal universe;
turnover = 1 − |previous_top ∩ current_top| / |previous_top| (denominator = PREVIOUS set
size; changing universe sizes handled by evaluating the ratio on the previous set's size and
reporting the count of transitions alongside). Reported: mean, median, p90. **SG6 uses the
MEAN.**

## E11 — Block-bootstrap settings (frozen before execution)

- random seed: **20261002** (deterministic)
- replications: **B = 2000**
- block length 63d: **3 consecutive monthly signal dates**; block length 126d: **6
  consecutive monthly signal dates** (matches forward-window overlap); 21d diagnostic: 1
- resampling unit: the DATE (a block of consecutive signal dates drawn with replacement,
  start index uniform over valid positions, blocks concatenated then truncated to the
  original date count)
- statistics bootstrapped: mean IC, positive-IC fraction, Q5−Q1 spread (per E8)
Settings frozen now; never chosen after seeing results.

## E12 - Leakage tests L1-L7 (implemented with the pipeline build, before evaluation)

- **L1**: every price feature uses only trade dates <= signal date (asserted per row)
- **L2**: financial/UI inputs respect published_at <= cutoff (the frozen UI reconstruction is
  consumed byte-identically - UI-tuning is impossible by construction)
- **L3**: observed snapshots respect collected_at <= cutoff
- **L4**: no current zTitad in historical runs (already test-enforced in the Engine suite;
  re-asserted for the signal pipeline)
- **L5**: recomputing one signal date cannot access later signal dates (date-isolated pipeline)
- **L6**: feature generation is invariant to deleting all observations after T (drop-later
  invariance test per feature)
- **L7**: forward-return columns are structurally unavailable to candidate-construction code
  (separated artifacts; construction consumes only ex-ante inputs)
All must PASS before any performance metric is accepted.

## E13 - Liquidity status (frozen)

`liq_30` is NOT part of Signal V1 (historical coverage 57.3%). It remains research inventory
only. No liquidity coverage improvement or backfill in this task; no data ingestion reopened.

---

Amendment status: frozen BEFORE execution, without inspecting any Signal Engine return
outcome. The SHA-256 of this file (computed after this amendment) is recorded in
SESSION_HANDOFF section 60. No execution before the hash exists.
