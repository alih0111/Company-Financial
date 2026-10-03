# RESEARCH PROGRAM DECISION — robust-six family (Development-only analysis)

Frozen: 2026-10-02. Input artifacts: `output/research_decision_panel.json` (script
`research_decision_analysis.py`), built ONLY from Development 2021–2023 and the frozen
world (v2.1-a composite, PERank_DIRECT_V2, FORWARD_RETURN_ADJUSTED_V1, pClosing basis).
This is a decision analysis, not a candidate search.

## PART 1 — CLOSED findings (must not be re-tested as if new)

1. Historical PE contamination was real and repaired (EPS-based PERank → PERank_DIRECT).
2. PERank_DIRECT quality is acceptable (share-state + knowledge-time contract; Stage-4
   ambiguity resolution; factor-level IC above legacy in Dev/Val).
3. Return-series integrity is promotion-grade (`RETURN_SERIES_INTEGRITY = PASS`,
   FORWARD_RETURN_ADJUSTED_V1, pClosing basis, auditable event factors).
4. RevenueGrowthRank sparse availability (5.2%) was real but NOT the R2 cause
   (v2.2-b removed it: Dev positive-fraction unchanged at 0.7222).
5. Growth-family redundancy exists (pairwise rank corr up to 0.649) but collapsing it
   WORSENED results (v2.2-a/c: Dev IC 0.1120 → 0.0705).
6. v2.1 and v2.2 both fail the same R2 stability condition (Dev positive-fraction).
7. The failure is 26/36 positive dates vs required 27/36; nearest negative |IC| = 0.0022;
   quarter-block bootstrap P(pos-frac ≥ 0.75) = 0.432.
8. 2024/2025/2026 are no longer untouched test periods (data-snooping statement binding).

## PART 2 — Diagnostic panel (Development, 36 monthly dates)

Per-date panel stored in the JSON: composite IC, all six factor ICs, ret_21
cross-sectional dispersion/median (outcome-side, descriptive), mean pairwise factor rank
correlations, PERank availability, LowVolatilityRank contribution, market breadth, median
return, return dispersion, volatility level, turnover, eligible count. No external macro
variables introduced. No regime label exists in the codebase (checked); year/quarter used.

## PART 3 — Can negative months be identified ex ante? → NO

Ex-ante state variables (computed at signal-date close; never from future returns):
market breadth, median trailing 21d return, cross-sectional 21d dispersion, volatility
level, negative-earnings prevalence, PE dispersion, recent capital-adjustment fraction.
Median-split of the 36 dates (mean IC low/high half, positive-fraction low/high, # of the
10 negative dates in the high half — 5 expected by chance):

| ex-ante variable | mean IC low/high | pos-frac low/high | neg in high | corr vs IC |
|---|---|---|---|---|
| breadth | +0.087 / +0.111 | 0.72 / 0.72 | 5/10 | +0.112 |
| mkt_ret21_med | +0.087 / +0.111 | 0.72 / 0.72 | 5/10 | +0.111 |
| xsec_disp21 | +0.096 / +0.102 | 0.72 / 0.72 | 5/10 | +0.058 |
| vol_level | +0.073 / +0.125 | 0.67 / 0.78 | 4/10 | −0.000 |
| neg_pe_frac | +0.059 / +0.139 | 0.61 / 0.83 | 3/10 | +0.145 |
| pe_disp | +0.073 / +0.125 | 0.67 / 0.78 | 4/10 | −0.097 |
| recent_capital_frac | +0.114 / +0.084 | 0.78 / 0.67 | 6/10 | −0.149 |

Negative dates sit at chance concentration (4–6 of 10) on every variable; several point
the "wrong" way (the composite did *better* in high-vol and high-negative-PE halves).
Rubric (pre-stated in the script) ⇒

**REGIME_MECHANISM_EVIDENCE = NONE.**

## PART 4 — LowVolatilityRank diagnosis (no candidate built, nothing removed/reweighted)

- IC by year: 2021 +0.027 (6/12 positive) · 2022 +0.026 (5/12) · 2023 +0.059 (9/12) —
  positive mean in EVERY year; overall positive-fraction 0.556.
- Mean IC on the 26 positive composite dates **+0.128**; on the 10 negative dates
  **−0.200** — it co-moves with the composite but has no identifiable state driver.
- Relationship to turnover: corr(LowVol IC, composite turnover) = −0.053 (none).
  Relationship to coverage: corr(LowVol IC, PERank availability) = +0.026 (none).
- Mean rank correlation with PERank +0.177 (a useful diversifier); with NetProfitGrowth
  −0.068 (near-orthogonal to growth).
- Correlation of LowVol IC with the ex-ante volatility level: **−0.012 — no regime
  structure**.

**Verdict: its negative episodes are RANDOM/NOISY** (positive mean in all years, no
ex-ante state association) — not systematic, not regime-dependent by any tested state.
Consistent with a weak-but-real effect whose monthly sign is close to a coin flip.

## PART 5 — PERank_DIRECT_V2 negative episodes

12 negative Dev dates. Associations with ex-ante states are all weak:
vol level −0.009 · market reversal −0.070 · negative-earnings prevalence +0.120 ·
recent capital adjustments −0.172 · cross-section size −0.219. Mean state on PERank-
negative dates vs all Dev dates is essentially identical (neg-PE 3.6% vs 3.8%; PE
dispersion 1.352 vs 1.342; recent-capital 7.4% vs 6.6%; market trailing return −1.5% vs
+0.5%). Industry domination: **not derivable** — no industry/sector columns exist in
`core.securities`. Verdict: PERank's negative months are ordinary sampling variation of a
positive-mean factor, not an identifiable condition.

## PART 6 — Is there a genuinely new hypothesis?

Pre-stated criteria: materially different AND ex-ante observable AND economically
interpretable AND Development-supported AND not "drop the bad factor" AND testable small.

- *Regime-conditional factor reliability* — requires a stable ex-ante regime variable that
  separates good from bad months. The panel found NONE (Part 3). Fails criteria 2+4.
- *Cross-sectional confidence weighting* — requires ex-ante confidence proxies (dispersion,
  availability, breadth) to associate with factor reliability. They do not (Part 3, and
  LowVol/PERank state correlations ≈ 0). Fails criteria 2+4.
- "Remove/reweight LowVolatilityRank" — unacceptable by definition (criterion 5), and H3
  was never an experiment.

**At most two hypotheses were allowed; ZERO survive the criteria.** The honest reading of
the panel: the composite's negative months are sampling noise around a modest positive
mean IC (+0.086), and the 26/36-vs-27/36 shortfall is a threshold artifact of that noise —
not a mechanism waiting to be modeled.

## PART 7 — Research stop rule

**NEW_MODEL_FAMILY_JUSTIFIED = NO.**

The current systematic research program should STOP rather than continue mining the same
history. Any "new family" built now would be fit to noise: there is no ex-ante state to
condition on, the closed findings leave no unexplained mechanism, and the remaining gap to
R2 is one near-zero date. If research resumes later, it must be driven by genuinely new
external evidence (new data sources, new universe, or a reformulated investment thesis) —
not by re-configuration of this factor set on this history.

## PART 8 — Signal Engine boundary

`SIGNAL_ENGINE_STARTED = NO`. No shadow-eligible candidate exists (v2.2 exploratory FAIL),
so nothing may be shadowed and no production recommendation logic may be built. Technical
note: the infrastructure (frozen snapshots, scorer functions, adjusted-return target,
shadow snapshot spec in MODEL_V2_2_PREREGISTRATION.md §8B/§8C) is technically capable of
running a research-only shadow scorer, but with no eligible candidate it remains OFF.
