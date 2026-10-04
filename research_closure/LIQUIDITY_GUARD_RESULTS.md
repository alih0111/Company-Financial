# LIQUIDITY GUARD RESULTS — V3 failure anatomy → implementation risk (Parts 2, 4–11)

Task: determine whether the V3 2021–22 failure is better framed as a SCORING failure or a
PORTFOLIO-IMPLEMENTABILITY / LIQUIDITY-RISK failure, using existing evidence only, with a
maximum of 4 pre-registered rank-based liquidity guards tested descriptively on V1 and
frozen B-W1 V3. **No threshold search was performed: each guard ran exactly once.** No V4,
no V3.1, no weight change, no score change, no production/live-shadow change.

> **REVISION 3 — FINAL BOOKKEEPING / SEMANTIC AUDIT CORRECTION (operator-directed,
> 2026-10-04).** Changes ONLY decision bookkeeping and audit documentation: no performance
> number, guard threshold, score, ranking, portfolio rule, or frozen research definition was
> altered, and no backtest was rerun. (1) `L4_OFFICIAL_SCOPE` is corrected to
> **INCLUDED_PER_FROZEN_PROTOCOL** — the interim token
> `EXCLUDED_PER_OPERATOR_RULING_2026_10_04` mischaracterized the operator ruling; the
> official scope is now read strictly from the original frozen protocol, which includes L4
> (see "L4 STATUS" below, quoting the frozen clauses). (2) The official
> `PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING` token is corrected to **NO** — the mechanical
> frozen §6e output under Direction D; the already-written draft is recorded separately as
> `PROSPECTIVE_GUARD_SHADOW_PLAN_DRAFT_EXISTS = YES`,
> `PROSPECTIVE_GUARD_SHADOW_PLAN_STATUS = DORMANT_POST_HOC_DRAFT`,
> `PROSPECTIVE_GUARD_SHADOW_ACTIVATED = NO`. Revision-2 SHA-256
> `841edc6db36e146495bab05c3a204c7874d7cbf548a0e3df6604d7fb1d517df7`; the SHA of this
> revision is recorded in SESSION_HANDOFF §87.

> **REVISION 2 — AUDIT CORRECTION (operator-directed, 2026-10-04).** This revision changes
> ONLY decision bookkeeping and audit documentation. No L0/L1/L2/L3 result, no bug-fix
> documentation, no guard definition, no threshold, and no decision-mapping rule was
> altered. (1) The preregistered direction is RESTORED to the mechanical frozen §6d output
> **D**; the previously recorded "B" is demoted to an explicitly post-hoc recommendation
> that must never replace D. (2) L4 provenance audited (§ "L4 STATUS" below); per the
> operator ruling L4 is excluded from the official comparison and preserved as an
> exploratory diagnostic. (3) The liquidity-regime finding is qualified POST-HOC
> DESCRIPTIVE. (4) The prospective plan remains a DRAFT; L1's candidate selection labeled
> post-hoc. (5) Artifact audit table added. Revision-1 SHA-256
> `b156b0f097aa1cf65b174d98d8a765c74c80afb7fc0dbd705517ab289f2f0313`; the SHA of this
> revision is recorded in SESSION_HANDOFF §86.

Provenance
- Frozen definitions (written BEFORE any return was computed):
  `LIQUIDITY_GUARD_DEFS_FROZEN.md` SHA-256
  `5a3b454de6fa793fe61fdc9ed595fd7c8b704dcee89106f4e3f1cbe171e43bc4`.
- Closure document: `SCORE_RESEARCH_CLOSURE.md` SHA-256
  `44a867437e2894b1cfd1bde335ce9d7e040c6d4b436519a02a91deb2bc63f418`.
- Scripts: `guard_backtest.py` (Parts 2,4,5,6,7), `capacity_current_v1.py` (Parts 8,9).
  Certified engine imported UNMODIFIED; frozen panel SHA-checked; Postgres SELECT-only.

Verification gates (all passed before any guarded result was reported)
- L0 tracker NAV == `RA.simulate` to 1e-9 for both models; monthly returns == frozen
  `trackA_monthly.csv` BASE rows to 1e-10; V1 CAGR/MDD/turnover == frozen records
  (0.3979 / −0.2685 / 0.2931); V3 MDD == −0.3085; yearly == frozen M7/M10 table.
- Gross decomposition identity (Σ wᵢ·rᵢ == gross) to 1e-10 on every rebalance of every run.
- Cross-asserts: tracker substitution counts == independent fail-set intersections
  (L1: V1 225, V3 243; L4 recomputed from the recorded guarded `value_pre` path).
- Window/yearly identity (Π over yearly buckets == window cum) verified 0.00pp for all
  10 variants.

Bug log (both found and fixed BEFORE any reported result; intermediate buggy numbers were
never reported)
1. The guard pass-mask was computed in panel-row order but applied positionally to the
   score-sorted frame — wrong names were excluded. Fixed by attaching the mask to the
   rows before sorting. Detected by the diagnostic cross-assert (tracker 284 vs
   independent intersection 225/243).
2. Substitution-event liquidity deltas initially used the rank as if it were the panel row
   index. Fixed via a per-date symbol→panel-position map (fingerprint: impossible negative
   L4 deltas; identical medians across models).

---

## PART 2 — Alpha vs implementability (existing evidence + guard diagnostics)

Selected-name liquidity profiles (medians over the L0 selections; episode = the V3
drawdown rows 2021-03..2022-02; capacity ratio = position of a 1B-toman portfolio / 30d
ADV, toman):

| window | model | median pct_TV30 | share bottom-decile TV30 | median TV30 (rial) | median TD60 | zero-trade days/60 | capacity@1B |
|---|---|---|---|---|---|---|---|
| episode | V1 | 0.500 | 11.0% | 47.0e9 | 0.980 | 1.2 | 0.97% |
| episode | V3 | 0.408 | **22.3%** | 39.3e9 | 0.971 | 1.7 | **3.94%** |
| 2023–26 | V1 | 0.498 | 8.4% | 52.4e9 | 0.932 | 4.1 | 0.66% |
| 2023–26 | V3 | 0.413 | **14.2%** | 42.8e9 | 0.933 | 4.0 | 0.82% |

Guard-fail composition (L1): failing selected names sit at **median rank 17** of their own
model's frozen ranking (core holdings, not marginal), 99.1% have TD60 < 1.0 (they missed
trading sessions; median TD60 of failing names = **0.783** ≈ 13 of the last 60 sessions
without trades), 49.9% are also in the other model's Top-40 (mean Top-40 overlap between
V1 and V3 is only 18.7/40 — the illiquid names that rank top-40 tend to rank top-40 in
BOTH models: the low-vol / shallow-mdd tilt attracts semi-suspended names).

Per frozen rule 6a: SHORT = V1 2021–22 cum − V3-L0 2021–22 cum = 16.26% − (−5.30%) =
21.56pp. Best rank-based guard (L1) lifts guarded V3 2021–22 cum by **+13.56pp = 62.9% of
SHORT** (≥ 50%) with V3 avg turnover up **+1.82pp** (≤ +2pp).

- **WAS_V3_2021_FAILURE_PRIMARILY_ALPHA_SELECTION = NO**
- **WAS_V3_2021_FAILURE_PRIMARILY_LIQUIDITY_REGIME = YES**

Semantic qualification (operator correction #3, 2026-10-04) — this is a single-path,
post-hoc descriptive mechanism finding, NOT validation:
- **POST_HOC_DESCRIPTIVE_MECHANISM = YES**
- **FRESH_CAUSAL_VALIDATION = NO**
No untouched holdout exists; the historical guard experiment does not constitute untouched
validation in any sense, and nothing here may be read as causal proof.

Reading: in the BACKTEST, the drawdown was driven by the score systematically ranking
semi-suspended / thinly-traded "calm" names into the Top-20% (the low-risk block's
preference surface) — a pure liquidity SCREEN (no new alpha, no new weights) recovers
about two thirds of the shortfall. Liquidity is therefore not merely an execution detail;
it was the transmission channel through which the low-risk block failed in 2021–22. (The
2023–26 edge came from the same block via the same channel — see Part 7.)

## PART 4 — Semantics implemented

Frozen ranking (ui_score DESC, symbol ASC — identical engine sort); n_elig and
n_sel = max(1, floor(0.20·n_elig)) unchanged; selection = first n_sel guard-passing names;
no score recomputation; equal weight; certified engine tradability filter and
`rebalance_accounts` UNMODIFIED; missing guard metric → excluded (counted). Shortfall
rebalances (fewer passers than n_sel): **0 in all runs.** Execution-time engine behavior
identical to L0.

## PART 5 — Historical results (BASE cost 0.005; post-hoc DESCRIPTIVE, NOT validation)

| model | guard | CAGR | cum full | MDD | turnover | fees | 2021 | 2022 | 2023 | 2024 | 2025 | 2026p | 21–22 cum | 23–26 cum |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| V1 | L0 | 39.79% | +464.5% | −26.85% | 29.31% | 0.250 | −11.44% | +31.27% | +59.96% | +26.92% | +54.83% | +55.25% | **+16.26%** | +388.00% |
| V1 | L1 | 39.68% | +462.2% | −26.84% | 31.81% | 0.292 | −8.69% | +33.25% | +58.69% | +23.05% | +50.51% | +58.02% | **+21.67%** | +364.40% |
| V1 | L2 | 34.97% | +370.8% | −28.82% | 31.40% | 0.245 | −12.02% | +21.83% | +56.46% | +24.16% | +47.42% | +54.13% | **+7.19%** | +341.43% |
| V1 | L3 | 39.21% | +452.4% | −26.79% | 30.33% | 0.267 | −8.42% | +31.41% | +57.45% | +26.92% | +49.99% | +53.89% | **+20.35%** | +361.27% |
| V1 | L4 | 37.08% | +410.1% | −26.34% | 31.57% | 0.281 | −10.49% | +31.68% | +60.46% | +22.79% | +49.35% | +47.82% | **+17.86%** | +334.97% |
| V3 | L0 | 43.69% | +550.6% | −30.85% | 27.76% | 0.242 | −24.70% | +25.77% | +76.88% | +48.01% | +61.32% | +63.48% | **−5.30%** | +590.42% |
| V3 | L1 | 46.36% | +615.5% | −22.81% | 29.58% | 0.296 | −14.79% | +27.05% | +75.84% | +44.28% | +60.54% | +63.09% | **+8.26%** | +564.22% |
| V3 | L2 | 41.10% | +492.3% | −26.05% | 32.23% | 0.271 | −17.37% | +19.24% | +63.86% | +48.41% | +57.28% | +57.98% | **−1.47%** | +504.21% |
| V3 | L3 | 45.85% | +602.9% | −22.81% | 28.57% | 0.274 | −16.00% | +23.95% | +73.22% | +50.37% | +61.48% | +61.31% | **+4.12%** | +578.45% |
| V3 | L4 | 47.91% | +655.8% | −20.38% | 31.33% | 0.397 | +3.63% | +24.37% | +79.88% | +43.21% | +60.12% | +42.88% | **+28.88%** | +489.32% |

Benchmark (frozen 100% bench, BASE): 2021–22 cum +15.06%, 2023–26 cum +273.45%.
Benchmark excess (ratio, windows): V1-L0 +1.0% / +30.7%; V1-L1 +5.7% / +24.4%;
V3-L0 −17.7% / +84.9%; V3-L1 −5.9% / +77.9%; V3-L3 −9.5% / +81.7%; V3-L4 +12.0% / +57.8%.

IC: guards act only on portfolio selection; scores are untouched, so per-date
cross-sectional ICs are **unchanged by construction** (identical arrays; not recomputed).

Substitutions (vs L0 Top-20% slots):

| model | guard | subs | retention | avg/reb | median Δpct TV30 | median Δpct TD60 | median ΔTV30 (rial) |
|---|---|---|---|---|---|---|---|
| V1 | L1 | 225 | 91.0% | 3.57 | −6.2pp | **+61.3pp** | −4.6e9 |
| V1 | L2 | 241 | 90.3% | 3.83 | **+46.9pp** | 0.0 | +35.4e9 |
| V1 | L3 | 59 | 97.6% | 0.94 | +41.2pp | +59.1pp | +25.8e9 |
| V1 | L4 | 165 | 93.4% | 2.62 | +47.9pp | 0.0 | +28.3e9 |
| V3 | L1 | 243 | 90.3% | 3.86 | +2.9pp | **+61.3pp** | +3.0e9 |
| V3 | L2 | 412 | 83.5% | 6.54 | **+48.1pp** | 0.0 | +37.7e9 |
| V3 | L3 | 99 | 96.0% | 1.57 | +39.9pp | +56.2pp | +30.4e9 |
| V3 | L4 | 371 | 85.1% | 5.89 | +46.3pp | 0.0 | +29.7e9 |

(Universe bottom-decile lines for context: TV30 p10 ≈ 9.3–12.2e9 rial; TD60 p10 = 0.867 —
i.e., the L2 decile line sits ABOVE L4's initial 5e9-rial cutoff and L4's NAV-scaled cutoff
rises above it as wealth grows — reconciling the L2 vs L4 event counts by era.)

**Scope note (revised by Revision 3, final bookkeeping 2026-10-04):** per the original
frozen protocol, the OFFICIAL preregistered guard comparison is L0–L4 — `L4_OFFICIAL_SCOPE
= INCLUDED_PER_FROZEN_PROTOCOL` (see "L4 STATUS — PROVENANCE AUDIT" below). All L4 rows in
this table and in Parts 6–7 are official preregistered results, preserved unchanged.

## PART 6 — V3 2021–22 episode: which major negative contributors would each guard remove?

Top-20 negative contributors to the V3 drawdown (frozen certification audit) vs guard
membership at the same as-of dates:

| contributor | contrib (pp) | L0 dates held | L1 | L2 | L3 | L4 |
|---|---|---|---|---|---|---|
| سدور | −3.79 | 1 | **REMOVED** | retained | retained | retained |
| سبجنو | −2.77 | 7 | retained | partial | retained | partial |
| کپشیر | −2.67 | 4 | retained | partial | retained | partial |
| دارو | −2.61 | 8 | retained | partial | retained | partial |
| پرداخت | −2.47 | 2 | retained | partial | retained | **REMOVED** |
| سنیر | −2.12 | 3 | **REMOVED** | partial | partial | partial |
| دتوزیع | −2.01 | 2 | partial | retained | retained | partial |
| غویتا | −1.92 | 1 | retained | **REMOVED** | retained | **REMOVED** |
| قلرست | −1.22 | 9 | partial | partial | partial | partial |
| افق | −1.19 | 10 | retained | retained | retained | retained |
| ساربیل | −1.17 | 4 | retained | partial | partial | partial |
| شگل | −1.17 | 2 | retained | partial | retained | partial |
| سهگمت | −1.15 | 7 | retained | partial | retained | partial |
| غدام | −1.14 | 3 | **REMOVED** | **REMOVED** | **REMOVED** | **REMOVED** |
| قرن | −0.96 | 3 | partial | retained | retained | retained |
| کاسپین | −0.89 | 8 | retained | partial | partial | partial |
| زمگسا | −0.87 | 2 | partial | **REMOVED** | **REMOVED** | **REMOVED** |
| بگیلان | −0.77 | 2 | retained | **REMOVED** | retained | retained |
| شیران | −0.74 | 3 | retained | retained | retained | retained |
| شبهرن | −0.71 | 6 | retained | retained | retained | retained |

Guarded V3 2021–22 cumulative and replacement names entering the episode:
- L1: +8.26% (Δ +13.56pp) — replacements بموتو، حسینا، دالبر، سخوز، سپیدار، شپارس، هجرت، کحافظ
- L2: −1.47% (Δ +3.83pp) — replacements بموتو، حتاید، حسینا، سخوز، سپیدار، شپارس، شگویا، فاذر، قنیشا، هجرت، پاسا، پخش
- L3: +4.12% (Δ +9.42pp) — replacements بموتو، دالبر، سخوز، سپیدار، فاذر، هجرت، پخش
- L4: +28.88% (Δ +34.18pp) — replacements بموتو، حتاید، حسینا، دالبر، سخوز، سپیدار، فاذر، قاسم، وخارزم، کحافظ

The single worst contributor (سدور) fails L1 but passes the TV30-based floors; the TV30
floors instead remove mid-list contributors. **This is descriptive association, NOT causal
proof** — the guards reweight the whole basket; the deltas are whole-portfolio effects.

## PART 7 — Does the guard destroy the good era (2023–26)?

Deltas vs each model's L0 (percentage points):

| model | guard | Δ21–22 cum | Δ23–26 cum | Δ23–26 MDD | Δturnover | ΔCAGR full | ΔMDD full |
|---|---|---|---|---|---|---|---|
| V1 | L1 | **+5.41** | **−23.60** | +0.73 | +2.50 | −0.11 | +0.02 |
| V1 | L2 | −9.07 | −46.58 | −2.12 | +2.09 | −4.83 | −1.96 |
| V1 | L3 | +4.10 | −26.73 | −0.65 | +1.03 | −0.59 | +0.06 |
| V1 | L4 | +1.61 | −53.03 | −0.11 | +2.26 | −2.71 | +0.51 |
| V3 | L1 | **+13.56** | −26.19 | +0.31 | +1.82 | **+2.67** | **+8.04** |
| V3 | L2 | +3.83 | −86.21 | −1.02 | +4.47 | −2.58 | +4.79 |
| V3 | L3 | +9.42 | −11.97 | +0.09 | +0.81 | +2.17 | +8.04 |
| V3 | L4 | +34.18 | −101.09 | −0.98 | +3.57 | +4.23 | +10.46 |

**The guard does NOT destroy the 2023–26 edge, but it gives up a material slice of it.**
Per-date ranking ICs are unchanged by construction (scores untouched); the 2023–26
*portfolio* cost of L1 is −26.2pp (V3) / −23.6pp (V1) of cumulative return (≈ −4.4% /
−6.1% relative), L3's is −12.0pp (V3, −2.0% relative) / −26.7pp (V1). L4 preserves the
most 2021–22 (+34.2pp on V3; V3-L4 2021 is POSITIVE +3.6% in the worst year) but costs the
most later (−101pp on V3) plus +15.5pp of fees. State it plainly: on V1 — the only model
that remains — every guard costs more 2023–26 return than it adds 2021–22 in absolute
terms (L1: +5.4 vs −23.6pp), because V1's 2021–22 was not broken to begin with.

## PART 8 — Capacity / real-money relevance (diagnostic only; latest snapshot 2026-10-01)

Position = Size/54; capacity ratio = position / 30d ADV (toman). Fractions of selected
names exceeding thresholds:

| model | size | median ratio | >1% | >2% | >5% | >10% |
|---|---|---|---|---|---|---|
| V1 Top20% | 100M | 0.01% | 0 | 0 | 0 | 0 |
| V1 Top20% | 500M | 0.03% | 1 (1.9%) | 0 | 0 | 0 |
| V1 Top20% | 1B | 0.05% | 1 (1.9%) | 1 (1.9%) | **1 (1.9%)** | **1 (1.9%)** |
| V1 Top20% | 5B | 0.26% | 1 | 1 | 1 | 1 |
| V1 Top20% | 10B | 0.52% | 1 | 1 | 1 | 1 |

The binding name is **جم پیلن3** (30d ADV ≈ 110M toman; TD60 = 0.433): a 1B-toman
portfolio's position would be 16.8% of its ADV, a 10B-toman portfolio's 168%. No fills are
assumed; costs beyond the frozen BASE assumption are not modeled. V3's current preview
Top-20% shows the same single binding name and near-identical medians (median TV30
35.80e9 vs 35.56e9 toman).

## PART 9 — Current V1 portfolio liquidity check (diagnostic; production selection UNTOUCHED)

Snapshot = latest completed non-fixture production run `0d2e5bc7-fde1-4af3-87fa-f292376beb79`,
as_of **2026-10-01** (same run as the frozen V3 preview — consistency confirmed). Universe
271; V1 Top20% = 54 names; full per-name table in `part9_current_v1_liquidity.csv`.

- **7 of 54 names (13.0%) fail L1/L2/L3 today**: جم پیلن3، شبهرن، غاذر، غبشهر، فایرا، پیزد، کسرا
  (غاذر is also the largest negative incremental security of the V3 study; شبهرن appeared
  in V3's 2021–22 episode holdings).
- Max capacity ratio at 1B toman: **16.8%** (جم پیلن3); 1 name > 1% at 1B.
- V1 Top20% median TV30 = 35.6e9 toman; median TD60 = 0.95; missing TV30: 0.
- Per frozen rule 6b: **CURRENT_V1_HAS_LIQUIDITY_RISK = HIGH**.

## L4 STATUS — PROVENANCE AUDIT (operator correction #2, 2026-10-04)

Question: where and when was the L4 NAV-scaled capacity guard preregistered, and was its
definition frozen before any guarded return was observed?

Evidence trail (all timestamps local +0330, from the filesystem and the frozen session
transcript):

1. **Original task text, PART 3** — preserved verbatim in the frozen session transcript
   `~/.zcode/cli/rollout/model-io-sess_9da553ba-1315-4e3c-a0b9-291dec4fded7.jsonl` (first
   record containing the task text: request completed 2026-10-04T16:10:58Z = 19:40:58, i.e.
   the task text existed ≥ 5.5 minutes BEFORE the definition freeze). Verbatim excerpt:
   "Maximum 4 guards. … Required examples: L0 — NONE … L1 — TRADED-DAYS FLOOR …
   L2 — TRADE-VALUE FLOOR … L3 — DUAL FLOOR … **Optional L4 only if justified:
   portfolio-capacity rule based on target notional / recent average traded value.** …
   Freeze definitions before running returns." (L1–L4 = exactly 4 guards with L0 baseline —
   consistent with "Maximum 4 guards".)
2. **Frozen definition** — `LIQUIDITY_GUARD_DEFS_FROZEN.md` §2, file created
   **2026-10-04 19:46:28**, i.e. BEFORE the first guarded-return computation (first write of
   `guard_variants.csv`, file birth **2026-10-04 19:57:32**). §2 defines L4 exactly (C = 1B
   toman = midpoint of the operator's Part-8 capacity grid; 5% participation; NAV_pre =
   the portfolio's own pre-rebalance value; n_sel_target fixed against circularity) with an
   a-priori, conventional justification, labeled "(optional, included with justification)".
   SHA-256 at freeze and today (file never modified):
   `5a3b454de6fa793fe61fdc9ed595fd7c8b704dcee89106f4e3f1cbe171e43bc4`.

Finding: an explicit pre-return directive naming L4 as an OPTIONAL guard DOES exist in the
original task text, and its exact definition (constants included) was frozen before any
guarded return was computed. L4 was NOT invented post hoc and its parameters were not
fitted after seeing returns.

Classification (operator correction #2):

- **L4_STATUS = PREREGISTERED_OPTIONAL_FROZEN_BEFORE_RETURNS** — the operator's
  `EXPLORATORY_OUT_OF_ORIGINAL_SCOPE` token is conditioned on "if no explicit pre-return
  directive extending the guard set to L4 exists"; the directive exists and is quoted above.
  Note the operator's premise that "the original accepted liquidity task preregistered only
  L0–L3" is contradicted by the frozen transcript (PART 3 listed L0–L3 as REQUIRED examples
  and named L4 as OPTIONAL); both facts are recorded here.
- **L4_OFFICIAL_SCOPE = INCLUDED_PER_FROZEN_PROTOCOL** (final bookkeeping correction,
  2026-10-04; the interim token `EXCLUDED_PER_OPERATOR_RULING_2026_10_04` mischaracterized
  the operator ruling and is RETRACTED). The official scope is determined strictly from the
  original frozen protocol, which includes L4 in the preregistered comparison:
  - `LIQUIDITY_GUARD_DEFS_FROZEN.md` §2 lists L4 among the "Guards (maximum 4, definitions
    frozen)": "**L4 — PORTFOLIO CAPACITY** (optional, included with justification): exclude
    s at T iff (NAV_pre(T) × C / n_sel_target) / TV30_T(s,T) > 0.05 …" — and the frozen file
    itself supplies the required justification BEFORE any return: "**Justification of
    constants (a priori, conventional, not fitted):** 5% of average daily traded value is
    the standard institutional participation heuristic (a full exit at 5% ADV takes ≈ 20
    sessions); C = 1B toman is the midpoint of the user-specified diagnostic grid."
    "Optional" in the original task therefore meant optional-to-INCLUDE provided a
    justification was frozen — it was. No frozen clause states or implies
    computed-but-excluded-from-decisions.
  - §6c applies "per guard, using BOTH V1 and V3 results" — no guard is excluded; §6d's
    "BEST_LIQUIDITY_GUARD := best classification …; if no guard exceeds NO VALUE → NONE"
    considers every guard with no L4 carve-out.
  - L4 was accordingly computed as part of the preregistered comparison, classified by
    frozen §6c (**UNACCEPTABLE**), and entered §6d. All L4 results (Part 5/6/7 rows,
    substitution table, Part 10 row) are official preregistered results, preserved
    unchanged.
- **Include-vs-exclude invariance (verified from the frozen mapping applied to the recorded
  results — no rerun):** including vs excluding L4 changes NEITHER official token.
  BEST_LIQUIDITY_GUARD — frozen §6c on L1–L3 alone: all three UNACCEPTABLE → no guard
  exceeds NO VALUE → NONE; with L4 added, L4 is also UNACCEPTABLE (2023–26 cum −53.03pp V1
  / −101.09pp V3) → still NONE. NEXT_RESEARCH_DIRECTION — frozen §6d: best guard
  NO VALUE/UNACCEPTABLE while §6b risk is HIGH → D either way. Frozen rule 6a never used
  L4. **No change to either token.**

## PART 10 — Decision matrix (frozen §6c criteria; applied mechanically)

| guard | fixes early tail? | preserves 23–26? | turnover | substitutions | simple? | class (frozen) |
|---|---|---|---|---|---|---|
| L1 | yes (+5.4pp V1, +13.6pp V3) | NO (−23.6pp V1) | +2.5pp | 9.0% | yes | **UNACCEPTABLE** |
| L2 | no (−9.1pp V1 21–22) | NO (−46.6pp V1) | +2.1pp | 9.7–16.5% | yes | **UNACCEPTABLE** |
| L3 | yes (+4.1pp V1, +9.4pp V3) | NO (−26.7pp V1) | +1.0pp | 2.4–4.0% | yes | **UNACCEPTABLE** |
| L4 | yes on V3 only (+1.6pp V1) | NO (−53.0pp V1, −101pp V3) | +2.3–3.6pp | 7–15% | partly (NAV path) | **UNACCEPTABLE** |

Official comparison (ALL FOUR guards L0–L4 per the frozen protocol — Revision 3 correction;
frozen §6c applies "per guard" and excludes none): every guard trips the frozen UNACCEPTABLE
clause (2023–26 cum drop > 10pp on at least one model: L1 −23.60pp, L2 −46.58pp, L3 −26.73pp,
L4 −53.03pp, each on V1; L4 also −101.09pp on V3). **No guard is historically validated in
any sense.** `BEST_LIQUIDITY_GUARD = NONE` — identical with or without L4 (frozen-mapping
invariance, verified in "L4 STATUS"). For reference only (POST-HOC, not a decision output):
the strongest candidate by the frozen tie-break (largest V1 2021–22 improvement) is **L1** —
also the simplest and most interpretable (one metric: did the name trade on at least 90% of
the last 60 sessions).

## PART 11 — Should score research continue?

- Score-model research is CLOSED (Part 1 closure): V2 and V3 terminally rejected; no
  untouched holdout; the only live score hypothesis would be a new model, which the
  evidence does not support and the task forbids by default.
- The failure mechanism is diagnosed (liquidity-screening channel, Part 2 YES), and the
  SAME exposure is measurable in production V1 today (Part 9 HIGH).
- The guard prescription is NOT established historically (Part 10: all UNACCEPTABLE) and
  cannot be, because no holdout remains. The only clean test is prospective — and it is
  cheap (a parallel computation against the existing Shadow V1.1, no activation).

**NEXT_RESEARCH_DIRECTION = D** (INSUFFICIENT_EVIDENCE)
**NEXT_RESEARCH_DIRECTION_LABEL = INSUFFICIENT_EVIDENCE**

This is the official, preregistered, mechanical frozen §6d output: best guard is
NO VALUE/UNACCEPTABLE (L1–L3 all UNACCEPTABLE per frozen §6c) while current-V1 liquidity
risk (§6b) is HIGH. It is restored by operator correction #1 (2026-10-04).

POST_HOC_RESEARCH_RECOMMENDATION = B (KEEP_V1_PLUS_PROSPECTIVE_LIQUIDITY_GUARD_RESEARCH)
POST_HOC_RECOMMENDATION_IS_PREREG_RESULT = NO

Operator correction #1 (2026-10-04): Revision 1 of this report had recorded B as the
direction with a disclosed override of the frozen mapping. That override was NOT allowed
and is RETRACTED. D is the official preregistered result; B is retained ONLY as the
explicitly post-hoc judgment recorded immediately above, and must never replace the frozen
D result. The post-hoc rationale for B (unchanged in substance, kept for the audit trail):
frozen rule 6a returned YES — the mechanism is identified descriptively; a concrete,
fully-frozen candidate (L1) exists; B adopts nothing and defers every decision to
prospective data. Under D, frozen §6e mechanically returns
PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING = NO, and that NO is the OFFICIAL token (final
bookkeeping correction, 2026-10-04; the interim operator-set YES is retracted). The fact
that a draft document was already written is recorded separately, not through §6e:
PROSPECTIVE_GUARD_SHADOW_PLAN_DRAFT_EXISTS = YES;
PROSPECTIVE_GUARD_SHADOW_PLAN_STATUS = DORMANT_POST_HOC_DRAFT (NOT APPROVED, NOT
ACTIVATED). The draft is retained unchanged.

## PART 12 — Prospective plan

`PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md` (DRAFT — NOT APPROVED — NOT ACTIVATED):
tests L1 on V1 as a parallel research computation against untouched Shadow V1.1, start no
earlier than the first production run ≥ 2026-11-01 after explicit operator approval,
12-month minimum horizon, pre-registered metrics and stop criteria, no retrospective
changes, no real-money orders. The existing Message A wait-state is untouched and takes
precedence. L1's selection as the plan's candidate is labeled POST-HOC in the plan itself
(operator correction #4).

---

## ARTIFACT AUDIT TABLE (operator correction #5, 2026-10-04)

Reference event — **first guarded-return computation** := first write of
`guard_variants.csv`, file birth **2026-10-04 19:57:32 +0330**. (Note: the editing tools
replace files atomically, so a file's filesystem birth time equals its LAST write; ordering
below therefore also uses the unmodified-SHA fact and the transcript record for the code
file.)

| # | artifact | SHA-256 (prefix) | created/frozen (+0330) | order vs first guarded return | modified after? | nature of later modifications |
|---|---|---|---|---|---|---|
| 1 | score-research closure freeze `SCORE_RESEARCH_CLOSURE.md` | `44a86743…f418` | 19:45:38 (birth; single write) | BEFORE (−11m54s) | NO | — |
| 2 | guard-definition freeze `LIQUIDITY_GUARD_DEFS_FROZEN.md` | `5a3b454d…3bc4` | 19:46:28 (birth; single write) | BEFORE (−11m04s) | NO — SHA at freeze == SHA today, verified 2026-10-04 | — |
| 3 | backtest code `guard_backtest.py` (Parts 2, 4–7) | `973f34bc…2085` (final) | existed before 19:57:32 (its first run wrote the first output); last edit 20:16:56 | created BEFORE; modified AFTER | YES — 3 edits | implementation-only bug fixes: (i) guard pass-mask attached to rows BEFORE the score sort; (ii) set-union call; (iii) substitution-event deltas via per-date symbol→panel-row map. NO guard definition, threshold (0.10/0.15/0.05/C=1B toman), selection semantics, or decision-mapping change |
| 3b | capacity/diagnostic code `capacity_current_v1.py` (Parts 8–9; no guarded portfolio returns) | `f9eb6b39…edf3` | 20:23:07 | AFTER (diagnostic only) | NO | — |
| 4 | final results report `LIQUIDITY_GUARD_RESULTS.md` | rev1 `b156b0f0…f313`; rev2 = this file (SHA in SESSION_HANDOFF §86) | 20:35:02 | AFTER (report, not a definition) | YES — this revision | decision-bookkeeping + audit documentation only (operator corrections #1–#5); no computed number, definition, threshold, or bug-fix documentation changed |
| 5 | prospective-plan draft `PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md` | v1 `3cc26ce1…9ddf`; post-correction SHA in §86 | 20:33:12 | AFTER (draft) | YES — one labeling addition (correction #4) | post-hoc labeling of L1's candidate selection only; no rule, date, metric, stop criterion, or scope change |

Bug-fix confirmation (operator correction #5): the two fixes in the bug log — (1) the guard
pass-mask alignment (mask computed in panel-row order had been applied positionally to the
score-sorted frame) and (2) the substitution-event index fix (rank mistakenly used as a
panel-row index, replaced by a per-date symbol→panel-position map) — changed ONLY
implementation correctness of the tracker and reporting code. They did NOT change any frozen
guard definition, threshold, selection semantics, or decision mapping. Evidence: the
definitions file was never modified (item 2: identical SHA before and after every code
edit); the frozen verification machinery itself DETECTED the mask bug (tracker substitution
count 284 ≠ independent fail-set intersection 225/243 — the cross-assert worked as
designed); and the final code passes every frozen gate (L0 == frozen `trackA_monthly.csv`
BASE to 1e-10; V1 anchors 0.3979/−0.2685/0.2931; V3 MDD −0.3085; gross-decomposition
identity 1e-10 on every rebalance of every run).

## FINAL STATUS (corrected — operator-required block, final bookkeeping 2026-10-04)

SCORE_RESEARCH_CLOSED_FOR_NOW = YES
V1_REMAINS_PRIMARY = YES
V2_REMAINS_REJECTED = YES
V3_REMAINS_REJECTED = YES

V3_FAILURE_PRIMARILY_LIQUIDITY_REGIME = YES
V3_FAILURE_DIAGNOSIS_STATUS = POST_HOC_DESCRIPTIVE
FRESH_CAUSAL_VALIDATION = NO

BEST_LIQUIDITY_GUARD = NONE
CURRENT_V1_HAS_LIQUIDITY_RISK = HIGH

NEXT_RESEARCH_DIRECTION = D
NEXT_RESEARCH_DIRECTION_LABEL = INSUFFICIENT_EVIDENCE

POST_HOC_RESEARCH_RECOMMENDATION = B
POST_HOC_RECOMMENDATION_IS_PREREG_RESULT = NO

PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING = NO
PROSPECTIVE_GUARD_SHADOW_PLAN_DRAFT_EXISTS = YES
PROSPECTIVE_GUARD_SHADOW_PLAN_STATUS = DORMANT_POST_HOC_DRAFT
PROSPECTIVE_GUARD_SHADOW_ACTIVATED = NO

NEW_SCORE_MODEL_CREATED = NO
PRODUCTION_CHANGED = NO
LIVE_SHADOW_CHANGED = NO
BROKER_CONNECTED = NO
REAL_MONEY_ORDERS = NO
SQL_SERVER_USED = NO

L4 status (immediately after the block, original frozen-protocol semantics only):
L4_STATUS = PREREGISTERED_OPTIONAL_FROZEN_BEFORE_RETURNS
L4_OFFICIAL_SCOPE = INCLUDED_PER_FROZEN_PROTOCOL

Notes: (a) NEXT_RESEARCH_DIRECTION = D is the preregistered mechanical frozen §6d output;
B is a post-hoc recommendation only and never replaces D. (b)
PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING = NO is the mechanical frozen §6e output under D
and is the official token; the already-written draft exists independently as a
DORMANT_POST_HOC_DRAFT — NOT APPROVED, NOT ACTIVATED, retained unchanged. (c) L4 is a
preregistered guard per the original frozen protocol (§2 "optional, included with
justification", justification frozen a priori before any return); it classifies
UNACCEPTABLE under frozen §6c, and including vs excluding it changes neither
BEST_LIQUIDITY_GUARD nor NEXT_RESEARCH_DIRECTION (verified from the frozen mapping only).
