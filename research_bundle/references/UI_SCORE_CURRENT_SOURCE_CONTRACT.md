# UI SCORE — CURRENT SHARE-SOURCE CONTRACT (frozen 2026-10-02)

score_version = `canonical-v1-dev` · production scorer = `compute_metrics.py` Engine.
Companion to `historical_codal_backfill/UI_SCORE_HISTORICAL_VALIDATION.md` (validation)
and `RETURN_PATH_AUDIT.md` / `CORPORATE_ACTION_TAXONOMY.md` (data architecture).

## The single canonical rule (PHASE 3 decision)

**PRIMARY current shares: TSETMC `zTitad`** — the live exchange instrument master.
**CROSS-CHECK: BRS/vendor `core.share_structure`** (monitoring only).
**Deterministic fallback: vendor `core.share_structure`** when zTitad is unavailable
(no insCode / fetch failure); **if both unavailable → the existing valuation penalty**
(PE/PS/PB None, val = 0, `VALUATION_INPUT_MISSING` flag). No opportunistic per-symbol
mixing: one primary, one deterministic fallback.

Decision against the stated criteria:
- *direct share count*: zTitad is the exchange's own outstanding-count field — not
  capital-derived, not inferred. ✓
- *source freshness*: zTitad is the live instrument master (updated by TSETMC
  continuously); vendor snapshots refresh daily (as_of 2026-09-29..10-01). ✓
- *consistency with the historical share chain*: zTitad equals the terminal state of the
  validated TSETMC share-change chain (215/216 open-ended chains match exactly; the single
  mismatch — خودکفا — is a freshness artifact of the CACHED chain snapshot vs the live
  master, with the vendor agreeing with zTitad). ✓
- *deterministic availability*: after the Phase-2 fill, zTitad covers 271/271 UI subjects. ✓
- *PIT/current-date semantics*: zTitad is a CURRENT value — exactly what current-date
  scoring needs; historical dates continue to use the validated chain + knowledge path. ✓
- *coverage*: 271/271 (vendor 266/271). ✓

## Evidence (Phases 1, 2, 4, 5)

- **Vendor source semantics (Phase 1)**: `core.share_structure`, single source
  `brs_all_symbols`, 588 rows / 325 securities, as_of 2026-09-29..10-01, collected
  2026-09-29..10-01 (daily refresh). Engine gate: `as_of_date <= as_of AND collected_at <=
  cutoff` (`pit_share_snapshot`). Fallback: none; missing → valuation penalty.
- **TSETMC sources (Phase 1)**: `zTitad` (GetInstrument) = live outstanding count;
  `GetInstrumentShareChange.numberOfShareNew` = last recorded transition (chain terminal
  state). Cached zTitad fetch dates: 2026-10-01/02 (documented per symbol).
- **Three-way reconciliation (Phase 2, 271 UI subjects,
  `share_source_reconciliation_ui271.json`)**: vendor vs zTitad — EXACT **266**,
  TSETMC_ONLY 5, **zero count disagreements**. vendor vs latest chain-new — EXACT 242,
  no-chain 23, DIFF_GT_5PCT 1 (خودکفا: cached chain stale vs live master).
- **Recompute under the contract (Phase 4, `ui_score_canonical_source_recompute.json`)**:
  vs the production scores — Spearman **0.9985**, 112 exact matches, mean |Δ| 0.116, max
  6.6, top-quintile overlap 0.964, **top-decile overlap 1.0**; 3 companies move >2 points —
  ALL are companies that GAIN valuation (vendor snapshot missing, zTitad covers them);
  nobody loses. The remaining micro-deltas are rank churn from 5 names entering the
  valuation cross-sections.
- **Historical-contract coherence (Phase 5)**: 216 companies have open-ended historical
  chains; **terminal chain == canonical current count for 215/216**; 55 no-chain companies
  are covered by the current-source rule. No unexplained current-vs-history contradiction.

## Phase 6 — parity statement under the contract

- Formula parity: EXACT (same Engine; only the share input swapped).
- Input parity: semantically consistent — current date uses zTitad (the chain's live
  terminal state), historical dates use the chain + Codal knowledge time. The historical
  reconstruction's interval path remains the historical rule; zTitad is its natural
  continuation.
- Score parity: near-exact (Spearman 0.9985; only 3 companies move >2 points, all gains).
- Valuation parity: the 5 previously-valuation-less companies gain PE/PS/PB; everyone else
  is unchanged beyond micro rank churn.
- Deployment: the next production refresh implements PRIMARY/CROSS-CHECK/FALLBACK in the
  Engine's share loader and re-stores `analytics.*` under it.
  **DEPLOYED 2026-10-02** (implementation + validation on a NEW production-style run):
  migration `sql/119_tsetmc_current_shares.sql` (snapshots with REAL collected_at, never
  backdated) · Engine `select_current_shares()` precedence + load gate (historical
  `market_pit='trade_date'` runs never read this table) · collector
  `historical_codal_backfill/collect_tsetmc_current_shares.py` (323/323 instruments,
  real acquired window 2026-10-02 14:55:53-15:01:18 Tehran) · 8 regression tests.
  New versioned analytics run: `e5998f6d-93ab-4577-b13a-7b2f89c39c02` (as_of 2026-10-02,
  cutoff 15:15+03:30 > real acquisition; all 271 subjects on TSETMC_ZTITAD_CURRENT,
  0 fallbacks, cross-check 266 AGREE + 5 TSETMC_ONLY).
  **PIT correction on record**: the earlier what-if recompute that stamped zTitad rows
  collected_at=2026-10-01 was a counterfactual sensitivity test only — zTitad was actually
  acquired 2026-10-02 and can never be assigned an artificial cutoff-era timestamp. The
  deployed run's cutoff (15:15) is strictly after the real acquisition (15:01).

## Phase 7 — frozen product meaning of the score

The 0–100 UI score is:
- a **cross-sectional ranking / company-quality score** computed within the covered
  product universe;
- historically associated with better medium/long-horizon subsequent returns **within the
  reconstructed available historical universe, with residual universe/survivorship
  uncertainty** (survivorship effect on the full market: `UNRESOLVED` — the absent issuers
  were never reconstructed/scored, and the three-month LetterType=58 filer union is not a
  definitive census of the entire listed-equity market).

It is NOT: a probability of profit · an expected-return percentage · a guarantee ·
calibrated over the full 0–100 range (observed historical range ≈ **2.1–71.9**; 80+
unobserved). No scale redesign in this task.

## Phase 8 — gates

- `UI_SCORE_HISTORICAL_VALIDATION = PASS_WITH_UNIVERSE_CAVEAT`
- `UI_SCORE_CURRENT_SHARE_SOURCE = VALIDATED` (three-way reconciliation + continuity +
  recompute demonstration)
- `UI_SCORE_CURRENT_PRODUCTION_CONTRACT = PASS` — pre-deployment status was PARTIAL (per the PIT correction: unvalidated until a run with cutoff after the real acquisition); with run `e5998f6d` the contract is **deployed and validated: PASS**.
- `UI_SCORE_READY_FOR_PRODUCT_USE = YES` — the current score is technically and
  semantically ready to remain in the UI. This authorizes NOTHING beyond the UI: no
  Signal Engine, no trading recommendations.
- `SURVIVORSHIP_EFFECT_ON_FULL_MARKET = UNRESOLVED`
