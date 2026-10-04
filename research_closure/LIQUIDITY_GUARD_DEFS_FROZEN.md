# LIQUIDITY GUARD DEFINITIONS — FROZEN BEFORE ANY RETURN COMPUTATION

Frozen: 2026-10-03, before running any guarded backtest. SHA-256 of this file is recorded
in `LIQUIDITY_GUARD_RESULTS.md` and SESSION_HANDOFF §85. Nothing below may be changed after
results are seen. **No threshold search is permitted or performed: each guard below runs
exactly once.**

Research-only. Modifies no certified artifact, no production table, no live shadow.

---

## 1. Guard metrics (certified chain, PIT-safe)

Computed with the frozen `score_v2_research/v2lib.py` machinery, raw PIT fields only:

- **TD60** := `t_traded_days_ratio_60` = fraction of the last 60 file-records with
  `qTotTran5J > 0` (rolling 60, min_periods 60). Range [0,1].
- **TV30** := `t_trade_value_30d` = mean raw `qTotCap` (RIAL traded value) over the last 30
  sessions (rolling 30, min_periods 30). **TV30_T** := TV30 / 10 (toman).
- Computed as-of each panel `as_of` date T via `md.idx_at(sym, T)` — uses only sessions
  ≤ T. No future data anywhere.
- **Cross-sectional percentile** of a metric at date T := `v2lib.midrank_pct` (midrank /
  (n−1), ties get the midrank) computed over **all rows of the frozen research panel with
  that as_of date** (the date's eligible universe, n ≈ 200). Denoted pct_TD60, pct_TV30 ∈ [0,1].
- Missing metric (window incomplete or symbol absent from raw files): the security
  **FAILS any guard that uses that metric** (cannot verify liquidity → excluded).
  These exclusions are counted separately and reported.

## 2. Guards (maximum 4, definitions frozen)

- **L0 — NONE.** Existing portfolio behavior (frozen score ranking, certified engine,
  no liquidity eligibility filter). Baseline.
- **L1 — TRADED-DAYS FLOOR.** Exclude security s at date T iff pct_TD60(s,T) < 0.10
  (bottom 10% by trailing traded-days ratio).
- **L2 — TRADE-VALUE FLOOR.** Exclude s at T iff pct_TV30(s,T) < 0.10 (bottom 10% by
  trailing 30d traded value).
- **L3 — DUAL FLOOR.** Exclude s at T iff pct_TD60(s,T) < 0.15 **AND** pct_TV30(s,T) < 0.15
  (both bottom-15%; a security is excluded only if it fails both dimensions).
- **L4 — PORTFOLIO CAPACITY** (optional, included with justification): exclude s at T iff
  (NAV_pre(T) × C / n_sel_target) / TV30_T(s,T) > 0.05, where
  C = 1,000,000,000 toman (midpoint of the preregistered capacity grid 100M / 500M / 1B /
  5B / 10B toman), NAV_pre(T) = portfolio NAV immediately before the rebalance
  (dimensionless, initial 1.0 — the portfolio's own known state), n_sel_target =
  max(1, floor(0.20 × n_elig)) at T (the ORIGINAL target count; fixed to avoid
  circularity), and 0.05 = 5% participation. **Justification of constants (a priori,
  conventional, not fitted):** 5% of average daily traded value is the standard
  institutional participation heuristic (a full exit at 5% ADV takes ≈ 20 sessions);
  C = 1B toman is the midpoint of the user-specified diagnostic grid.

## 3. Selection semantics (frozen)

For each rebalance date T (sorted panel dates), for each model (V1 = frozen `ui_score`
panel column; V3 = frozen B-W1 score, `score_panel` with frozen features/weights):

1. n_elig = row count at T (UNCHANGED by guards); n_sel = max(1, floor(0.20 × n_elig))
   (UNCHANGED).
2. Frozen ranking = sort by (ui_score DESC, symbol ASC) — the identical engine sort.
3. Selection = **the first n_sel names in that frozen ranking that PASS the guard.** No
   score recomputation, no rank improvement, no future information. If fewer than n_sel
   pass, select all passers (shortfall recorded; count reported).
4. n_sel_effective := number selected in step 3 (== n_sel unless shortfall). All engine
   formulas (equal weight 1/n_sel_effective, turnover, cash-for-failed) use
   n_sel_effective exactly as the engine uses n_sel. For L0, n_sel_effective == n_sel
   (asserted).
5. The certified engine's execution-time tradability filter (`traded_keys`) then applies
   UNCHANGED: selected names not tradable on the exec date are not funded and stay cash
   (no replacement) — identical to L0 behavior.
6. Execution via `rebalance_accounts` UNMODIFIED; NAV identity asserted each rebalance.

## 4. Verification gates (frozen, must pass before any guarded result is reported)

- L0 V1 and L0 V3 tracker NAV paths == `RA.simulate` to 1e-9.
- L0 monthly returns == frozen `trackA_monthly.csv` BASE rows (V1, B-W1) to 1e-10.
- L0 V3 MDD == −0.3084678411938703 to 1e-9; L0 yearly returns reproduce the frozen
  yearly table used by M7/M10.
- Gross decomposition identity Σᵢ wᵢ·rᵢ == NAV_pre[k+1]/NAV_post[k] − 1 to 1e-10 on every
  rebalance of every run.

## 5. Reporting conventions (frozen)

- Cost level: BASE (0.005) only. Monthly row k labeled by score_date, return
  NAV_post[k+1]/NAV_post[k]−1, grouped yearly by row k's exec_date[:4] (engine `yearly`
  convention).
- CAGR := terminal_wealth^(12/62) − 1 with terminal_wealth = entry × Π(1+r) (engine
  `metrics` convention, entry cost included). MDD := min over path [1.0] + [entry ×
  Π(1+r)] of path/cummax − 1.
- Benchmark excess: frozen `bench_return` column (100% portfolio, same cost);
  cumulative excess = Π(1+r_p)/Π(1+r_b) − 1.
- 2021–22 / 2023–26 cumulative: Π(1+r) − 1 over rows whose exec_date year is in the range.
- IC: scores are untouched by guards → per-date cross-sectional ICs are mathematically
  IDENTICAL to L0 (guards act only on portfolio selection). Reported once as
  "unchanged by construction"; not recomputed per variant.
- Substitution events: names in the L0 top-n_sel of date T that fail the guard and are
  replaced by lower-ranked passers. Retention = 1 − Σsubstitutions / Σ|L0 top-n_sel|.
  Liquidity improvement per event: paired by rank order, Δ pct_TV30, Δ pct_TD60,
  Δ TV30 (rial); medians reported.
- L0 selection used as the substitution reference is the tracker's own L0 selection
  (asserted identical to the engine's).

## 6. Decision mappings (frozen before results)

### 6a. Part 2 classification rule
- Let SHORT = V1(2021–22 cum) − V3_L0(2021–22 cum) (the V3 shortfall, > 0).
- WAS_V3_2021_FAILURE_PRIMARILY_LIQUIDITY_REGIME = YES iff the best rank-based guard
  (L1/L2/L3) lifts guarded V3 2021–22 cum by ≥ 50% of SHORT with avg turnover up ≤ +2pp
  vs L0 V3; NO iff the best lift is < 25% of SHORT; MIXED otherwise.
- WAS_V3_2021_FAILURE_PRIMARILY_ALPHA_SELECTION = YES iff the above is NO; NO iff the
  above is YES; MIXED otherwise. (Liquidity-regime causation and alpha-selection causation
  are treated as competing explanations of the SAME backtest drawdown; the descriptive
  cross-sectional liquidity evidence (Part 2 tables) is reported alongside either way.)

### 6b. Part 9 current-V1 liquidity risk class
Capacity ratio of a name := (PortfolioSize / n_sel_prod) / TV30_T, n_sel_prod =
floor(0.20 × production universe size), evaluated at the latest production snapshot.
- HIGH iff any current V1 Top20% name has capacity ratio > 5% at 1B toman, or fails
  L1, L2, or L3 at the snapshot date.
- else MODERATE iff any name has capacity ratio > 1% at 1B toman.
- else LOW.

### 6c. Part 10 guard classification (applied per guard, using BOTH V1 and V3 results)
- **UNACCEPTABLE** iff 2023–26 cum drops > 10pp vs that model's L0 for either model,
  OR avg turnover rises > +5pp for either model, OR mean substitution rate > 15% of slots.
- else **NO VALUE** iff 2021–22 cum improvement < 2pp for BOTH models.
- else **ROBUST DESCRIPTIVE** iff 2021–22 improvement ≥ 2pp for BOTH V1 and V3, AND
  2023–26 preserved within 5pp for both, AND turnover +≤ 3pp, AND substitutions ≤ 10%.
- else **PROMISING BUT POST-HOC.**
No guard may be called historically validated in any case; ROBUST DESCRIPTIVE means the
descriptive evidence is consistent across both models and both eras.

### 6d. Part 11 direction rule (frozen)
- BEST_LIQUIDITY_GUARD := best classification (ROBUST DESCRIPTIVE > PROMISING BUT
  POST-HOC > NO VALUE > UNACCEPTABLE), tie-break larger V1 2021–22 improvement; if no
  guard exceeds NO VALUE → NONE.
- NEXT_RESEARCH_DIRECTION:
  - **B** (KEEP_V1_PLUS_PROSPECTIVE_LIQUIDITY_GUARD_RESEARCH) iff best guard is
    ROBUST DESCRIPTIVE or PROMISING BUT POST-HOC.
  - **A** (KEEP_V1_AND_FOCUS_ON_FORWARD_SHADOW) iff best guard is NO VALUE/UNACCEPTABLE
    and current-V1 liquidity risk (6b) is LOW or MODERATE.
  - **D** (INSUFFICIENT_EVIDENCE) iff best guard is NO VALUE/UNACCEPTABLE while current-V1
    liquidity risk is HIGH, or the two models' guard evidence contradicts without
    classification resolution.
  - **C** is not reachable from this evidence: V2 and V3 are terminally rejected and no
    new score evidence exists (user constraint: default must not be C).

### 6e. PROSPECTIVE_GUARD_SHADOW_WORTH_DRAFTING
YES iff NEXT_RESEARCH_DIRECTION = B; then `PROSPECTIVE_LIQUIDITY_GUARD_SHADOW_PLAN.md`
is drafted (draft only — no shadow started). NO otherwise.
