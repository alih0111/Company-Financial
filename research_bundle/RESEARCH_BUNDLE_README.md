# RESEARCH BUNDLE — README

Frozen: 2026-10-02. A self-contained review bundle answering: *"What PIT-safe data do we
actually have that could plausibly support a genuinely new timing or entry mechanism?"*
The reviewer inspects this bundle and decides what, if anything, is worth testing. This
bundle contains **NO research results** — no feature ICs, no return correlations, no
candidate signals, no optimized anything.

## Project state (where this bundle sits)

- **UI score `canonical-v1-dev`**: VALIDATED and in the product
  (`UI_SCORE_READY_FOR_PRODUCT_USE = YES`). Historically, higher scores ranked medium/long-
  horizon adjusted returns better **within the available covered universe**
  (`PASS_WITH_UNIVERSE_CAVEAT`). Product spec: `product/UI_SCORE_PRODUCT_SPEC.md`.
- **Model v2.1 / v2.2**: CLOSED, `VALIDATION_WEAK` (preregistered gates failed on the
  adjusted-return target; the robust-six factor family is retired).
- **Signal V1** (timing overlay: 60d momentum + 60d-high distance + inverse 30d vol inside
  the UI-Q5 universe): **EXECUTED ONCE, PRIMARY GATE = FAIL** — IC63(excess) +0.0548,
  ΔIC63 vs identical-row UI baseline **−0.0074**, Q5−Q1 excess −0.20pp, turnover 0.633.
  Preregistration hash `149ba4af…`, snapshot hash `4719eced…`. Closed as a failed
  experiment (`SIGNAL_V1_CLOSEOUT.md`); `SIGNAL_RESEARCH_PAUSED = YES`.
- **Data integrity**: closed (`DATA_INTEGRITY_BLOCKERS_CLOSED = YES`) — corporate-action
  pipeline + adjusted returns (pClosing basis) + current share-source contract all
  validated; survivorship effect on the FULL market remains `UNRESOLVED`.

## PIT rules (binding for any future use of this bundle)

1. Financial inputs: `published_at ≤ cutoff` (legacy-migrated reports: `period_end ≤ as_of`).
2. Market data: `trade_date ≤ signal_date` (frozen historical proxy).
3. Observed snapshots: `collected_at ≤ cutoff` — NEVER backdated (the TSETMC zTitad snapshot
   was acquired 2026-10-02 14:55–15:01 Tehran and is only valid for runs after that instant).
4. Historical shares: TSETMC share-change chain + Codal `published_at` knowledge time.
5. Outcomes are OUTCOMES: they must never be used in feature construction.
6. All feature columns in the monthly panel are ex-ante computable at the signal date
   (verified by construction and by the drop-later invariance tests of Signal V1).

## Already-inspected periods (do NOT treat as untouched)

Development 2021–2023 (design), Validation 2024 (inspected), Holdout 2025 and Forward 2026
(inspected descriptively). Every historical result in this project is
EXPLORATORY_HISTORICAL. A confirmatory result requires future dates after any new
preregistration's freeze.

## Available-universe caveat (applies to every file here)

The covered universe is the **present-day product coverage list** (238 research symbols /
271 scored subjects). The canonical DB contains **zero delisted issuers**, and a bounded
Codal enumeration found **651 market issuers that filed mandatory monthly reports during
2021–2025 but were never ingested** (339 of them alive in all three probe years — a
coverage gap, not primarily delisting; ~34 plausible true exits). The survivorship effect
on absolute-return levels is therefore structural and unquantified; cross-sectional
within-date rankings of covered names are the robust object.

## Files

| file | rows | contents |
|---|---|---|
| `monthly_pit_panel.parquet` | 13,481 | signal_date × security: identifiers, eligibility, frozen UI outputs, fundamental raw metrics + ranks, all price/timing features, market-state columns |
| `daily_market_panel.parquet` | 837,525 | raw TSETMC daily fields per security/date + adjustment factor + adjusted close |
| `event_panel.parquet` | 28,508 | financial reports, monthly sales reports, LT28 announcements, corporate actions (with publication/collected stamps) |
| `market_state_daily.parquet` | 6,163 | equal-weight covered-universe daily state (breadth, dispersion, drawdown, momentum, aggregates) |
| `outcomes.parquet` | 13,409 | forward adjusted + excess returns 21/63/126/252d (SEPARATE from features) |
| `DATA_INVENTORY.md` / `DATA_DICTIONARY.md` / `COVERAGE_SUMMARY.csv` / `COVERAGE_BY_YEAR.csv` / `FEATURE_PROVENANCE.csv` / `BUNDLE_INTEGRITY_AUDIT.md` / `reproduction_test.json` | — | inventory, definitions, coverage, provenance flags |

Known gaps (documented, not synthesized): share volume unavailable; official index series
not stored; liquidity_30 57.0% / liquidity_20 69.6% / liquidity_60 36.6% coverage (raw qTotCap ramp); sales-growth features ramp 0%→69% with the
monthly-activity backfill; PE/PS/PB ramp 52%→76% with the share path; ocf_ttm not
materialized in the frozen artifact; 252d outcomes missing for the last ~12 months.

## Provenance flags (which features were already used)

- `USED_UI_SCORE`: ui_score, 4 category scores, DQ, all 21 factor ranks and their raw
  metrics (sales/revenue/op/np growth, margins, roe, margin trend, interest coverage, cash
  conversion, earnings quality, pe/ps/pb, liquidity_30, sales stability, vol_30, mom_30,
  leverage, current ratio).
- `USED_MODEL_V2`: the robust-six ranks (PERank, NetProfitGrowthRank, SalesGrowthRank,
  SalesGrowth3MRank, RevenueGrowthRank, LowVolatilityRank) + the full 21-rank set (v2.1
  candidates), PERank consumed as PERank_DIRECT_V2.
- `USED_SIGNAL_V1`: mom_60, distance_from_60d_high, vol_30 (as inverse), ui_score
  (Q5 eligibility + 0.5 weight in Architecture B).
- `NEVER_USED`: return_5d/10d/120d (+adjusted), mom_20/mom_90, vol_10/20/60, downside
  volatility, drawdown_20/120, distance_from_120d_high, distance_from_20d/60d_low,
  liquidity_20/60, trade_count, trade_value (directly), volume (unavailable), daily
  high/low/open/priceYesterday/priceChange, market-state variables, ocf_ttm
  (not materialized), event_panel as features, official index (unavailable).

## Rules for the reviewer

The bundle is for inspection only. Do not compute feature-ICs against the outcomes file as
part of "review" — that is research and belongs to a new preregistration. Any future
experiment must be preregistered with its economic mechanism, candidates, universes,
missing-data rules, metrics, gates and shadow protocol BEFORE execution
(see `signal_engine/SIGNAL_ENGINE_PREREGISTRATION_V1.md` for the binding format and
`SIGNAL_V1_CLOSEOUT.md` for the pause rule).
