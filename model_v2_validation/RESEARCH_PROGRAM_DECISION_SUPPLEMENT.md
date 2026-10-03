# RESEARCH PROGRAM DECISION — SUPPLEMENT (independent verification + errata)

Frozen: 2026-10-02. Companion to `RESEARCH_PROGRAM_DECISION.md` (kept intact as the
pre-registered decision record). This supplement (a) records an independent reproduction
of that decision from the frozen inputs, (b) corrects two factual slips in the frozen
prose, and (c) adds the Part-2 panel columns that the frozen panel did not persist, plus a
hypergeometric significance test for the Part-3 regime question.

Scope discipline: Development 2021-2023 only; no candidate built; no factor removed or
reweighted; no threshold moved; no 2024/2025/2026 input; no external macro variable; no
data repair reopened. New artifact: `output/research_decision_panel_ext.json`
(script `research_decision_panel_ext.py`, diagnostic only).

---

## A. Independent reproduction (PASS)

Re-ran `research_decision_analysis.py` from the frozen inputs
(`phase3_signals_adjusted_v1.csv`, `pe_direct_universe_v2.jsonl`, raw pClosing caches,
`market.corporate_actions`, `research_symbols_238.txt`). Output reproduced every headline
in the frozen decision to ≤4 decimals. Cross-checked the negative-date set against the
independently-produced `output/model_v2_1_r2_diagnostics.json`:

- identical 10 negative dates out of 36;
- max |IC21 difference| between the two scripts = 4.8e-07 (float noise).

Confirms the decision is not fabricated and is reproducible from the frozen world.

## B. Errata (two factual slips in frozen prose — no mechanism impact)

1. **Mean Development composite IC.** `MODEL_V2_1_FINAL_CLOSEOUT.md` §R2 and
   `RESEARCH_PROGRAM_DECISION.md` Part 6 quote the composite's Dev mean IC21 as
   **+0.086**. The artifacts both compute **+0.0992**
   (`model_v2_1_r2_diagnostics.json → summary.mean_ic21 = 0.099164`; supplementary panel
   mean of the 36 per-date ICs = 0.0992). The number **0.086** is a stale value belonging
   to the older `canonical-v2-exp-b` row in `MODEL_V2_RESULTS.md`. Correct figure:
   **Dev mean composite IC21 = +0.0992, 26/36 positive dates**. This does not change any
   conclusion (it strengthens the "modest positive mean, one-date-short stability"
   reading).

2. **Panel contents.** `RESEARCH_PROGRAM_DECISION.md` Part 2 states the panel contains
   "mean pairwise factor rank correlations" and "LowVolatilityRank contribution". The
   persisted `output/research_decision_panel.json` did **not** contain per-date factor
   rank-correlation or LowVol-contribution columns (it stored per-date factor ICs and
   ex-ante state only). Those columns are now supplied in the supplementary panel (§C).

## C. Supplementary Part-2 columns (Development, 36 dates)

From `output/research_decision_panel_ext.json` (mean / min / max over dates):

| column | mean | min | max |
|---|---|---|---|
| mean pairwise factor rank corr | +0.129 | +0.010 | +0.262 |
| corr(LowVolatilityRank, PERank) | +0.177 | −0.359 | +0.368 |
| corr(LowVolatilityRank, growth family) | −0.017 | −0.210 | +0.275 |
| LowVolatilityRank composite weight share | **0.375** | 0.292 | 0.662 |
| composite cross-sectional dispersion (ex-ante) | 0.189 | 0.165 | 0.247 |
| factor-IC dispersion (descriptive) | 0.167 | 0.023 | 0.416 |
| eligible count | 212 | 190 | 225 |
| PERank availability | 0.578 | 0.333 | 0.647 |

**Structural finding (new, explanatory):** because missing values are renormalized
(`drop_unavailable_renormalize`), `LowVolatilityRank` — the *weakest* factor (mean IC
0.037, positive-fraction 0.556) — carries the *largest* average composite weight share
(**37.5%**), and up to 66% on sparse dates, because the other five factors are frequently
unavailable. LowVol's weight share is essentially identical on positive vs negative
composite dates (0.372 vs 0.381), so its negative contribution is **not** a coverage
artifact.

## D. Part 3 — regime test, extended with significance

Eight ex-ante, pre-observable state variables (all computed at the signal-date close from
information ≤ the signal date; none from the forward return): breadth, median trailing-21d
return, cross-sectional 21d dispersion, volatility level, negative-earnings prevalence, PE
dispersion, recent capital-adjustment fraction, and composite dispersion. Median split of
36 dates; observed negative-date concentration in the high half vs the 10 negatives
(chance = 5.0); hypergeometric p (P[count ≥ observed]):

| ex-ante variable | neg in high half | chance | p | corr vs IC |
|---|---|---|---|---|
| composite_disp | 7 | 5.0 | 0.132 | −0.047 |
| recent_capital_frac | 6 | 5.0 | 0.356 | −0.149 |
| breadth | 5 | 5.0 | 0.644 | +0.112 |
| mkt_ret21_med | 5 | 5.0 | 0.644 | +0.111 |
| xsec_disp21 | 5 | 5.0 | 0.644 | +0.058 |
| vol_level | 4 | 5.0 | 0.868 | −0.000 |
| pe_disp | 4 | 5.0 | 0.868 | −0.097 |
| neg_pe_frac | 3 | 5.0 | 0.970 | +0.145 |

- No variable is significant (min p = 0.132, and it is the best of eight → expected by
  chance). Max |corr(variable, IC)| over all eight = 0.149.
- Signs are mutually inconsistent: the composite did *better* in high-volatility and
  high-negative-earnings halves (opposite to the "turbulence hurts" intuition), and worse
  in high composite-dispersion and low-breadth halves.
- The two heaviest negative dates (2022-07-31 IC −0.332, 2023-10-31 IC −0.233) do share a
  low-breadth state (0.129 / 0.161), but the third-worst (2023-02-28, breadth 0.606) does
  not — no reproducible state.
- The pre-registered core variables graded **NONE**; the supplementary composite-dispersion
  variable reaches the rubric's low "WEAK" bar (c = 0.70 ≥ 0.60).

**REGIME_MECHANISM_EVIDENCE = WEAK (boundary).** Honest reading: a stable, significant,
pre-observable market state does **not** explain the R2 failures. One dispersion variable
sits at the boundary of the weakest band, non-significant and not direction-consistent with
the rest; the frozen core rubric returned NONE. Either label leaves the decision unchanged.

## E. Part 4 — LowVolatilityRank diagnosis (unchanged conclusion, more detail)

- IC by year: 2021 +0.027 (6/12 pos) · 2022 +0.026 (5/12) · 2023 +0.059 (9/12) —
  positive mean every year; overall positive-fraction 0.556.
- IC by quarter (mean / positive): 2021Q1 +0.117 (2/3) · 2021Q2 **−0.228** (0/3) ·
  2021Q3 +0.062 (2/3) · 2021Q4 +0.155 (2/3) · 2022Q1 −0.072 (0/3) · 2022Q2 +0.189 (2/3) ·
  2022Q3 +0.040 (2/3) · 2022Q4 −0.053 (1/3) · 2023Q1 −0.095 (1/3) · 2023Q2 +0.173 (3/3) ·
  2023Q3 +0.211 (3/3) · 2023Q4 −0.052 (2/3). Sign flips across quarters; annual mean stays
  positive.
- Contribution: mean IC **+0.128** on the 26 positive composite dates, **−0.200** on the
  10 negative dates; at ~0.375 weight share that is ≈ +0.048 / −0.075 of composite IC.
- Turnover: corr(LowVol IC, composite turnover) = −0.053 (none). Coverage:
  corr(LowVol IC, PERank availability) = +0.026 (none).
- Correlation with PERank: mean per-date rank corr **+0.177** (a consistent diversifier);
  with the growth family **−0.017** (near-orthogonal). corr(LowVol IC, ex-ante vol level)
  = −0.012.

**Verdict: RANDOM/NOISY** — positive mean in every year, no ex-ante state association, no
turnover/coverage driver. Not systematic; not regime-dependent by any tested state. Not
removed, not reweighted.

## F. Part 5 — PERank_DIRECT_V2 negative episodes (unchanged conclusion)

12 negative Dev dates. Associations with ex-ante states all weak: vol level −0.009 ·
market reversal −0.070 · negative-earnings prevalence +0.120 · recent capital adjustments
−0.172 · cross-section size −0.219. Mean state on PERank-negative dates vs all Dev dates is
essentially identical (neg-PE 3.6% vs 3.8%; PE dispersion 1.352 vs 1.342; recent-capital
7.4% vs 6.6%; market trailing return −1.5% vs +0.5%). One- or two-industry domination:
**NOT DERIVABLE** — `core.securities` has no industry/sector column (verified against the
live schema; columns are id, company_id, tsetmc_ins_code, codal_symbol, isin, brs_name,
security_type, is_primary, is_active, valid_from, valid_to, timestamps). No factor was
modified.

**Verdict:** PERank's negative months are ordinary sampling variation of a positive-mean
factor; no identifiable condition.

## G. Part 6/7 — hypotheses and stop rule

Criteria (from the task): materially new, ex-ante observable, economically interpretable,
Development-supported, not "drop the bad factor", testable small.

- *Regime-conditional factor reliability* — needs a stable ex-ante regime that separates
  good/bad months. The panel finds none (Part D). Fails criteria 2 + 4.
- *Cross-sectional confidence weighting* — needs an ex-ante confidence proxy (dispersion,
  availability, breadth) that tracks factor reliability. None does (Part D; LowVol/PERank
  state correlations ≈ 0; max |corr| 0.149). Fails criteria 2 + 4.
- Any "reweight LowVol / collapse growth / search weights" idea is unacceptable by
  construction (criteria 5, and the prohibited acts).

**Zero hypotheses survive.** The 26/36-vs-27/36 shortfall is a threshold artifact of
sampling noise around a modest positive mean IC (+0.0992): quarter-block bootstrap
P(pos-frac ≥ 0.75) = 0.432, nearest negative |IC| = 0.0022.

**NEW_MODEL_FAMILY_JUSTIFIED = NO.** The current systematic research program should STOP
rather than continue mining the same history. If research resumes, it must be driven by
genuinely new external evidence (new data source, new universe, or a reformulated
investment thesis), not by re-configuring this factor set on this history.

## H. Final returns

```
ROBUST_SIX_FAMILY_CLOSED      = YES
NEW_MODEL_FAMILY_JUSTIFIED    = NO
REGIME_MECHANISM_EVIDENCE     = WEAK (boundary; frozen core rubric = NONE)
SIGNAL_ENGINE_STARTED         = NO
DATA_INTEGRITY_BLOCKERS_CLOSED = YES
MODEL_V2_1_FINAL_STATUS       = VALIDATION_WEAK     (unchanged)
MODEL_V2_2_EXPLORATORY_GATE   = FAIL                (unchanged)
MODEL_V2_2_SHADOW_ELIGIBLE    = NO                  (unchanged)
```

Signal Engine remains NOT STARTED: no shadow-eligible candidate exists (v2.2 exploratory
FAIL), so no production recommendation logic may be built and nothing may be shadowed.
Technical note only: the infrastructure (frozen snapshots, scorer functions, adjusted
return target, shadow protocol §8B/§8C of `MODEL_V2_2_PREREGISTRATION.md`) is *capable* of
running a research-only shadow scorer, but with no eligible candidate it stays OFF.
