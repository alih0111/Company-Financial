# SCORE RESEARCH CLOSURE — V1 / V2 / V3 (frozen 2026-10-03)

Status document. Nothing here changes any artifact; it records the accepted verdicts of the
completed score-model search and formally closes it. All numbers are copied from the frozen
research artifacts cited below — no recomputation, no reinterpretation.

Scope of this closure: **score-model research (V1 / V2 / V3) only.** Portfolio-level
liquidity-guard research is a separate, follow-on diagnostic task (see
`LIQUIDITY_GUARD_DEFS_FROZEN.md` and `LIQUIDITY_GUARD_RESULTS.md` in this directory); it
does not alter any verdict recorded here.

---

## V1 — certified baseline / current production / shadow-eligible

- Verdict: **certified baseline, current production score, shadow-eligible (it IS the
  production and shadow model).** REMAINS PRIMARY.
- Frozen evidence: full-period 2021-01..2026-06, certified engine
  (`portfolio_research/repair_accounting_v1.py`, SHA
  3c63b887632f5fb2f8216ada4fac5309f0478f3a87ef621d978ac59ad1efa2af), PIT panel
  `score_v2_research/pit_feature_panel.parquet`: Top20% BASE CAGR 39.79%, MDD −26.85%,
  avg turnover 29.31%, IC63 0.0853 / IC126 0.1096 (frozen anchors asserted in every
  Track A run).
- Live state: production scoring runs on V1; live Shadow V1.1 is IDLE under the standing
  Message A wait-state (no qualifying post-freeze production `canonical-v1-dev` run can
  exist before 2026-10-31; the pre-authorized 11-step Decision #1 procedure has NOT run).

## V2 — REJECTED (final)

- Verdict: **FAIL — optimizer overfit + turnover.** REMAINS REJECTED.
- The V2 optimizer-selected weights did not survive out-of-window validation and the
  resulting portfolio turnover was uneconomical. No artifact of V2 was promoted; the
  rejection stands as the frozen terminal verdict of the V2 research track.

## V3 Minimal — REJECTED (final)

- Verdict: **FAIL on gates M6 and M10. Research value MEDIUM. NOT a shadow candidate.**
  (`V3_FUTURE_SHADOW_CANDIDATE = NO`, `V3_RESULT_STILL_USABLE_FOR_RESEARCH = YES (evidence only)`.)
- M6: Top20% BASE MDD −0.30847 vs tolerance −0.29853 (V1 −0.26853 − 0.03) → FAIL.
- M10: excluding the strongest incremental year (2024), remaining cumulative incremental
  V3−V1 = −6.15% → FAIL (one-regime dependence).
- Nominal cap contract PASS; normalized effective cap contract NO (five single-feature
  effective weights 18.52% > 12.5%, tech/risk block 37.04% > 25%, low-coverage SGR 7.41% > 5%).
- Track B strict prereg compliance NO (fold 2022 only: 0/15 eligible → post-protocol
  fallback picked E-W1; folds 2023–26 fully compliant, all B-W1).
- Ichimoku overlay corrected verdict: INCONCLUSIVE (mechanical YES retracted; overlay
  bootstrap not available).
- Certification audit artifacts: `score_v3_minimal_research/audit/
  SCORE_V3_MINIMAL_CERTIFICATION_AUDIT.md` (Parts A–I, all tokens), summarized in
  SESSION_HANDOFF.md §84.

## Final accepted failure findings (certification audit, frozen)

1. **The V3 low-risk block (vol_60 + mdd_60, 25 nominal points) caused the 2021–22
   failure.** Removing it (B-W1 minus both = A-W1 exactly): 2021–22 cumulative −5.3% →
   +27.6%, episode MDD −30.85% → −25.94%; 2021–22 IC63 0.0134 → 0.0321 (vs V1 0.0242).
2. **The mechanism was lower trailing vol / shallower 60d drawdown names that were also
   far less liquid** — V3's selected median 30d trade value was ~10x below V1's in the
   worst months (May 2021), with closer distance-to-120d-high and higher 120d momentum:
   a less-liquid "calm" profile that was rotated out of in the 2021–22 bear. V3 lost
   precisely in the two broad UP months (Jun–Jul 2021) following the 2021-04-28 rebalance,
   in a +6.9%/+6.7% universe.
3. **The same block created much of the 2023–26 edge.** Full B-W1 IC63 0.1878 (strict
   folds) vs 0.1156 with the tech block removed (V1 0.1240); 2023–26 strict-fold
   cumulative +562% (V1 +367%); the incremental bootstrap on strict folds is strictly
   positive (mean +0.88%, CI [+0.39%, +1.43%]).
4. **Performance concentration HIGH.** Excluding the single best month (2023-01-31) the
   cumulative incremental ratio falls +15.25% → +9.18%; excluding the top-5 months it is
   −8.69%; excluding 2024, −1.18%; the top-20 securities carry 51.5% of positive mass.
   One regime (2023–24) plus a handful of months supply the entire edge.
5. **No untouched historical holdout remains.** Every window 2021–2026 participated in the
   search (development, validation, Track A headline, Track B nested folds). The only
   eras with clean OOF certification (Track B strict folds) are the eras that work.
6. **Therefore future genuine validation must be prospective** — a forward shadow with
   frozen rules observed in real time. No further historical re-fit, re-weight, or
   re-folding can produce fresh confirmation.

## Terminal decision

Score-model search is **CLOSED**:

- No V4, no V3.1, no weight optimization, no feature additions/removals, no threshold
  tuning around 2021–2022.
- V1 remains the primary score. V2 and V3 remain rejected.
- What may continue is NOT score research: (a) forward Shadow V1.1 evidence under the
  standing Message A wait-state, and (b) portfolio-level implementability / liquidity
  research (separate documents in this directory), which is descriptive and
  prospective-only.

---

Document SHA-256 (self): recorded in the delivery message and SESSION_HANDOFF §85.
