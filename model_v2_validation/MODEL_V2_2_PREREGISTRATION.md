# MODEL V2.2 PREREGISTRATION

Frozen: 2026-10-02, BEFORE any v2.2 execution. `MODEL_V2_2_EXECUTED = NO` at freeze time.
This document may not be edited after the first v2.2 evaluation runs; corrections require a
new version id and a new file. Parent: `MODEL_V2_1_FINAL_CLOSEOUT.md` (immutable).

## 0. Data-snooping statement (binding)

- 2024 Validation has already been inspected (v2.1 and predecessors).
- 2025 Holdout has already been inspected descriptively.
- 2026 Forward (2026-01..06) has already been inspected descriptively.
- Therefore NONE of 2024/2025/2026 may be presented as an untouched confirmatory holdout
  for v2.2. They will not be relabeled as unseen. Historical results of v2.2 are
  EXPLORATORY by construction. A truly confirmatory v2.2 result requires future
  observations (shadow protocol, §8B) collected after this freeze.

## 1. Hypotheses (exactly three, Development-diagnostic only — see the closeout §R2)

- **H1 — missing-data interaction**: `RevenueGrowthRank` is available for only 5.2% of Dev
  rows (≈11 names per date). Under `drop_unavailable_renormalize` its sporadic presence
  renormalizes the composite on a small, non-random sub-universe while contributing ≈0
  marginal IC (LOO Δ −0.0009). Hypothesis: removing it stabilizes the composite without
  losing signal.
- **H2 — growth-family redundancy**: four of six factors (NetProfitGrowth, SalesGrowth,
  SalesGrowth3M, RevenueGrowth) are one correlated family (mean pairwise rank correlation
  up to 0.649; SalesGrowthRank LOO Δ +0.0005 = zero marginal). The 1/6-weight scheme makes
  the composite a de-facto 4/6 growth bet. Hypothesis: collapsing the family into a single
  deterministic composite reduces redundancy-driven instability.
- **H3 — unstable contribution of LowVolatilityRank**: lowest Dev positive-fraction (0.556)
  and mean IC (0.037), and the largest negative contributor on every one of the five worst
  Dev dates (−0.125…−0.530). Hypothesis: LowVol's regime-dependent sign, not missing data
  (99.99% available), drives the negative-date mass. H3 is DIAGNOSTIC CONTEXT ONLY —
  v2.2 does NOT remove LowVol (it is the availability anchor and the turnover stabilizer;
  R4 passes by 0.0005). Its behaviour is recorded by the ablation metrics.

No other hypothesis is pursued. No broad factor search. No new factors.

## 2-6. Frozen specification (identical harness discipline to v2.1)

1. **Hypothesis**: as above (H1+H2 primary; ablations isolate each).
2. **Factor sets** (ranks consumed from the same frozen Phase-3 snapshot; PERank always
   consumed as PERank_DIRECT_V2):
   - `canonical-v2.2-a` (PRIMARY): {PERank_DIRECT_V2, GrowthComposite, LowVolatilityRank},
     where `GrowthComposite(row) = mean(available of {NetProfitGrowthRank, SalesGrowthRank,
     SalesGrowth3MRank})` — RevenueGrowthRank EXCLUDED (H1); equal weights 1/3.
   - `canonical-v2.2-b` (ablation, isolates H1): the five factors {PERank_DIRECT_V2,
     NetProfitGrowthRank, SalesGrowthRank, SalesGrowth3MRank, LowVolatilityRank}, equal
     weights 1/5 (RevenueGrowthRank excluded, no family collapse).
   - `canonical-v2.2-c` (ablation, isolates H2): {PERank_DIRECT_V2, GrowthComposite₄,
     LowVolatilityRank} equal weights 1/3, where GrowthComposite₄ = mean(available of the
     FOUR growth ranks incl. RevenueGrowthRank) (family collapse only; H1 not applied).
3. **Transformations**: none beyond the frozen rank construction; GrowthComposite is the
   arithmetic mean of available member ranks (no re-ranking of the composite).
4. **Weights**: equal over the set (deterministic; identical to the v2.1-a weight rule).
   No fitted weights anywhere.
5. **Missing-data policy**: `drop_unavailable_renormalize` — unchanged. GrowthComposite is
   UNAVAILABLE for a row iff all its member ranks are unavailable.
6. **Eligibility**: unchanged frozen snapshot eligibility (PIT filters as in phase3;
   ≥5 IC-able rows per date for IC statistics).
7. **Rebalance frequency**: monthly month-end signals — unchanged.
8. **TOP_N / construction**: TOP_N = 20, equal weight — unchanged (reported, not primary).
9. **Turnover / costs**: reported per the frozen harness (10 bps/side, illustrative);
   R4 threshold unchanged at ≤ 0.65 on mean monthly turnover.
10. **Adjusted-return target**: `FORWARD_RETURN_ADJUSTED_V1` (`phase3_signals_adjusted_v1.csv`,
    sha256 `bf7cc191…`), canonical price basis `CANONICAL_RETURN_PRICE = TSETMC pClosing`.
11. **PERank version**: `PERank_DIRECT_V2`
    (`perank-direct-v2+tsetmc-shares+codal-knowledge+ambiguity-resolved`).
12. **Metrics**: per-period mean/median IC21 and positive-fraction (primary: IC21
    positive-fraction and mean), IC5/IC63 descriptive, turnover mean, coverage–score
    correlation, n per date. Periods frozen: Dev 2021-23, Validation 2024;
    Holdout 2025 / Forward 2026 descriptive only.
13. **Gates (exploratory historical, same thresholds as v2.1 — unchanged, not relaxed)**:
    - R1: Dev IC21 mean > baseline AND Val IC21 mean ≥ baseline (baseline = frozen
      `canonical-v1-dev` quant_score on the same adjusted target).
    - R2: IC21 positive-fraction ≥ 0.75 in BOTH Dev and Validation.
    - R3: |coverage–score correlation| ≤ 0.30 in both.
    - R4: turnover ≤ 0.65 in both.
    - Selection: among candidates passing R1-R4, highest (Dev IC21 + Val IC21)/2; if none
      passes ⇒ `MODEL_V2_2_VALIDATION_WEAK`. Selection uses a/b/c only (never the
      ablations to replace a failing primary post hoc).

## 8A. EXPLORATORY HISTORICAL EVALUATION (procedure frozen now)

One execution, deterministic, no post-hoc changes:
1. Load `phase3_signals_adjusted_v1.csv` via the frozen loader; substitute PERank_DIRECT_V2
   (same substitution code as the V2 rebaseline); build a/b/c scorers exactly as §2.
2. Evaluate with the frozen harness on Dev + Validation (+ Holdout/Forward descriptive
   rows, reported but excluded from every decision).
3. Apply §13 gates once; persist the full JSON; declare
   `MODEL_V2_2_EXPLORATORY = PASS | VALIDATION_WEAK` per the selection rule.
4. Whatever the outcome, no variant may be added, removed, reweighted, or re-gated. Any
   further idea becomes a NEW preregistration (v2.3) justified by NEW Dev-only evidence.

## 8B. CONFIRMATORY FUTURE EVALUATION (shadow protocol)

- Starts with the FIRST month-end signal date at least one full month after v2.2 execution
  and after its input data exist (expected 2026-11-30; if execution slips, the first
  month-end thereafter). No earlier date may be counted.
- Every month, on the frozen snapshot pipeline: compute IC21, positive-fraction, turnover
  for `canonical-v2.2-a` AND baseline `canonical-v1-dev` on the same adjusted target.
- No interim peeking for decisions; monthly values are appended to a log file.
- CONFIRMATORY PASS requires, over the first 12 shadow dates (all 12 must exist):
  (i) mean shadow IC21 of `canonical-v2.2-a` > 0;
  (ii) shadow IC21 positive-fraction of `canonical-v2.2-a` ≥ 0.75;
  (iii) mean shadow monthly turnover of `canonical-v2.2-a` ≤ 0.65;
  (iv) mean shadow IC21 of `canonical-v2.2-a` ≥ mean shadow IC21 of the frozen baseline
  `canonical-v1-dev` (the quant_score column of the same Phase-3 snapshot lineage),
  both means computed on the IDENTICAL shadow dates with the IDENTICAL
  `FORWARD_RETURN_ADJUSTED_V1` target. The baseline is `canonical-v1-dev` exactly as
  frozen; no new or additional baseline may be chosen after seeing v2.2 results.
  Fewer than 12 dates ⇒ NO verdict.

### 8C. Shadow execution boundary (clarified at acceptance)

A minimal research/shadow scorer MAY be operated to record frozen v2.2 scores for future
confirmation dates without starting the production Signal Engine. It may:
- compute the preregistered `canonical-v2.2-a` score exactly as specified in §2;
- record ranks/scores for each shadow date;
- freeze a timestamped monthly snapshot (inputs, scores, ranks, snapshot hash);
- later attach realized forward returns when they exist.
It may NOT:
- issue production recommendations of any kind;
- change model logic, factor definitions, or weights;
- tune anything against accumulated shadow results;
- alter any threshold or gate;
- become or embed the production Signal Engine.
Production Signal Engine work still requires PROMOTION_READY (§9).
- A single shadow window may be judged once. Extension/restart requires a new prereg.

## 9. Signal Engine boundary

- `RESEARCH_SIGNAL_READY`: v2.2 exploratory evaluation = PASS (all four rules on Dev+Val)
  AND the shadow protocol of §8B is running. Permits continued research and shadow
  logging only.
- `PROMOTION_READY`: confirmatory shadow PASS per §8B, plus the return-integrity and
  historical-share integrity gates still standing (`RETURN_SERIES_INTEGRITY = PASS`,
  `HISTORICAL_SHARE_REPAIR_COMPLETE = YES` — both currently hold).
- **Signal Engine work may begin only at PROMOTION_READY.** An exploratory v2.2
  improvement alone never implies promotion and never starts the Signal Engine.

## Stop rules

- If v2.2 exploratory = VALIDATION_WEAK: the robust-six family is closed; the next
  research cycle requires new Dev-only evidence and a new preregistration.
- If confirmatory shadow FAILS: v2.2 is dead; no third family may be derived from the
  same data without genuinely new external evidence.
- R2's threshold (0.75), all weights, and all factors are FROZEN everywhere in this
  document. Nothing here may be tuned against 2024/2025/2026.
