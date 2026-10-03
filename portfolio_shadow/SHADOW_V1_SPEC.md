# SHADOW V1 — FORWARD-ONLY PAPER PORTFOLIO SPECIFICATION (`score-portfolio-v1-top20`)

Frozen: 2026-10-03, UTC 18:45:00 (`SPEC_FROZEN_AT_UTC`). Forward-only. No historical
dates are shadow observations. The historical SCORE_PORTFOLIO_V1 backtest remains
exploratory history; nothing in it is re-run, altered, or extended by this document.

Working rules: every step reproducible, PIT-safe, audit-friendly. Nothing is tuned to
look good; thresholds are frozen here and never altered after results are seen.

---

## 1. Shadow start boundary (frozen)

- The shadow start = the **first production score run of `canonical-v1-dev` COMPLETED
  AFTER `SPEC_FROZEN_AT_UTC = 2026-10-03T18:45:00Z`**, identified in the canonical DB
  as an `analytics.score_runs` row with `status='completed'` and
  `completed_at > SPEC_FROZEN_AT_UTC`.
- **Mid-session guard (data-quality rule, not strategy):** a run qualifies only if
  `as_of_date < date(completed_at)` OR `source_cutoff_at >= 12:45 Asia/Tehran` on its
  `as_of_date` — i.e. the snapshot is not taken while the session is still open. A run
  rejected by the guard is logged in `SHADOW_V1_ISSUES.md` and skipped; the next
  qualifying run starts the shadow.
- The last pre-freeze production run (as_of 2026-10-02, completed 2026-10-02 15:04
  Tehran, input hash `d75b8c5b7a13cdaaa70f54f428d6a9590f07a1c8475ff066a7f05d3bbf554d44`)
  is NOT a shadow observation and is used only as a test fixture.
- **Rebalance cadence after the start:** the decision run for each subsequent month is
  the earliest qualifying run (same definition as above) whose `as_of_date` falls in a
  strictly later calendar month than the previous decision's `as_of_date`. Additional
  completed runs within an already-decided month are recorded in the state file as
  `ignored_runs` and never used. This is MONTHLY, matching the frozen V1 schedule as
  closely as operationally possible.
- For every rebalance, decision timestamp, target securities, and target weights are
  frozen BEFORE any execution outcome is observed. Targets are never regenerated after
  seeing market conditions.

## 2. Score source (frozen)

The exact current production score **`canonical-v1-dev`** as published by the production
engine (code version `canonical-v1-dev+report-chain-ttm+direct-valuation+fiscal-anchor-cell`
or its documented production successor; no research rebuild). The historical PIT
reconstruction is NOT used to produce current scores.

Each shadow snapshot stores, for every scored security: `score_run_id`,
`score_as_of_date`, `knowledge_cutoff` (`source_cutoff_at`), `score_generated_at`
(`completed_at`), company identity (`company_id`, `security_id`, `ins_code`, `symbol`),
`ui_score` (= production `quant_score`), `ui_rank` (1 = highest score; tie-break below),
`data_quality_score` plus the DQ detail dict, the four category scores
(growth/profitability/valuation/market), and every stored factor percentile.

The decision input is read from the permanent DB tables (`analytics.score_runs`,
`analytics.company_scores`, `analytics.factor_scores`) so that a later overwrite of the
ephemeral `canonical_v1_metrics.json` file cannot alter a frozen decision. When the
snapshot file's digest (`canonical_v1_hash.txt`) equals the run's stored `input_hash`,
the binding is recorded; otherwise the DB remains authoritative.

## 3. Selection (frozen — identical to historical V1 rule)

From SCORE_PORTFOLIO_V1_PREREGISTRATION §3 (SHA-256
`10e6aa0e477b89eb73a5deacb72a4e337467fcfd2a06fd736a78e5954ecaf17c`, quoted):

> "PRIMARY `score-portfolio-v1-top20`: at each monthly score date, rank all eligible
> scored securities; select TOP 20% by score rank; equal weight among selected names
> BEFORE failed executions."
>
> "Selection arithmetic: `n = max(1, floor(pct × N_eligible))`; ties broken
> deterministically by `(ui_score DESC, symbol ASC)`."

Shadow implementation, exactly:

- Eligible universe = every `company_scores` row of the decision run (production
  cross-section; `quant_score` non-NULL). No pre-filtering by priceability, liquidity,
  or identity — unpriceable names are handled by the frozen failed-target rule (§5).
- `n_selected = max(1, floor(0.20 × N_eligible))`.
- Ranking order: `(quant_score DESC, symbol ASC)`; `ui_rank` assigned in this order.
- Selected = first `n_selected` rows. Equal target weight `1 / n_selected` each,
  BEFORE failed executions. No substitution, no judgment, no Top10 shadow portfolio
  (Top10 remains a historical diagnostic only).

## 4. Identity (frozen)

One stable portfolio-security identity per security: **`company_id:ins_code`** (the
certified canonical key). Resolution order per scored row:

1. `company_scores.company_id` + `primary_security_id` → `core.securities`
   (`codal_symbol`, `tsetmc_ins_code`, `is_primary`).
2. Cross-check against the certified `portfolio_research/portfolio_identity_map.parquet`
   (235 UNIQUE rows): if the company is present, `ins_code` must agree; agreement is
   recorded as `MAP_VERIFIED`, absence of the company as `DB_RESOLVED`, disagreement as
   `IDENTITY_ERROR`.

A selected name with `IDENTITY_ERROR` cannot be paper-executed; its target weight
remains CASH (frozen failed-target rule) and the failure is logged. Identity is never
re-mapped retroactively; a change of instrument for the same company_id is a new
identity row and an issue-log entry.

## 5. Execution reference (frozen — historical comparability path A)

Historical V1 (prereg §4, quoted): "`EXECUTION_DATE` = first canonical trading date
strictly AFTER the score date / its proven `knowledge_cutoff` … Execution price:
canonical `pClosing` on EXECUTION_DATE … Tradability: a selected security is executable
on EXECUTION_DATE iff the canonical daily panel has an observation AND
`security_traded == True` (zero-trade / unknown = NOT executable). If selected but not
executable: NO substitute, NO assumed execution — that target weight remains **CASH**
until the next rebalance … If the portfolio already holds a temporarily non-tradable
security: carry at the canonical carried-valuation convention but do not pretend it
could be sold."

`SHADOW_REFERENCE_EXECUTION` = canonical raw `pClosing` of the security's raw closing
cache (`raw_{symbol}_{ins_code}.json.gz`, field `pClosing`) on EXECUTION_DATE — the same
price object the certified historical engine consumed — expressed on the CONFIRMED
`tsetmc_gap_rule_v1` adjustment chain for valuation and returns. Valuation and fills are
performed in adjusted-chain units exactly like the certified backtest
(`price_at` semantics: last known adjusted close carried forward for missing days,
flagged as carried).

### 5a. Shadow trading calendar (frozen, evidence-based)

A date D is a **shadow trading date** iff:

- D is not Thursday and not Friday (Iranian market weekend), AND
- D has ≥ 30 distinct securities with `volume > 0` in `market.price_observations`.

Evidence recorded at freeze time: across the whole observation table only 2 Thursday
dates and 2 Friday dates exist (2026-07-30, 2026-09-24, 2026-09-25, 2026-10-02), all
collector artifacts of the recent live-feed era, and the 2026-10-02 Friday rows are
byte-identical carry-overs of the 2026-09-30 session (276 of 282 securities share both
close and volume) — phantom sessions. Real sessions since 2026-08 all have breadth ≥ 230
securities; token holiday sessions (e.g. 2026-09-27) have ≤ 6. The 30-securities
threshold separates these regimes; it is frozen here and never tuned after results.

`EXECUTION_DATE` = first shadow trading date strictly after the decision run's
`as_of_date`. Execution dates are never moved. Multiple intraday snapshots in
`market.price_observations` are never used for path A; the raw caches hold one final
record per session.

### 5b. Price contract (frozen)

- **Path A (frozen-comparable):** raw cache `pClosing` only × CONFIRMED
  `tsetmc_gap_rule_v1` factors. Corporate-action factors are read from
  `market.corporate_actions` (`source='tsetmc_gap_rule_v1'`,
  `adjustment_evidence_status='CONFIRMED'`) with the same backward-chaining algorithm as
  the certified engine. Later confirmations restate the chain exactly as the certified
  historical chain did; this is the frozen return semantics
  `PRICE_PLUS_MECHANICAL_ADJUSTMENTS` (cash dividends are NOT captured; the term "total
  shareholder return" is NOT permitted).
- **Path B (observed-practical diagnostic):** `market.price_observations` (vendor series
  `adjusted`, `adjustment_method='vendor_adjusted'`/`legacy_brs_adjusted`; duplicates
  deduplicated by max `collected_at` per `(security_id, trade_date)`) may be used for
  diagnostics only. Path B never rewrites path A and is never mixed into the
  frozen-comparable series.
- If the raw cache lacks EXECUTION_DATE data for a name at observation time, the order
  is **not** filled: `DATA_MISSING`, target stays cash/carry, issue logged. Missing
  execution fields are never synthesized.

## 6. Paper orders (frozen)

No brokerage transmission, ever. For every selected security one PAPER order is
recorded at decision freeze time with: `shadow_order_id` (`SHDW1-YYYYMM-###`, numbered
in `(symbol ASC)` order), security identity, symbol, side (`PAPER_BUY`,
`PAPER_SELL_REBAL`, `PAPER_HOLD` relative to prior holdings at decision valuation),
`decision_timestamp` (`score_runs.completed_at`), `target_weight`, `target_quantity_note`
(quantities are fixed at observation from the reference fill; the order freezes weight
and expected notional), `eligible_execution_date` (E, computed per §5a),
`reference_price` (raw pClosing of `as_of_date` — last known adjusted close at
decision), `expected_notional` (`target_weight × decision NAV`), `identity_status`.

## 7. Executability classification (frozen)

Each intended order is classified at observation time into exactly one primary flag:

| Flag | Path-A meaning |
|---|---|
| `EXECUTABLE_REFERENCE` | raw-cache record for (ins_code, E) exists with `qTotTran5J > 0` |
| `NO_TRADE` | record exists on E but `qTotTran5J == 0` (queued, no fill) |
| `SUSPENDED` | no record on E AND no trade evidence anywhere for the security on E while the market session existed (diagnostic cross-check vs DB; conservative — when suspension cannot be distinguished from a collection gap the flag is `DATA_MISSING`) |
| `PRICE_LIMIT_CONSTRAINED` | reserved for genuinely stored allowed-range evidence; no such field exists today, so it is currently unreachable |
| `INSUFFICIENT_LIQUIDITY_DATA` | record exists, traded, but volume/value fields missing |
| `IDENTITY_ERROR` | unresolved identity (§4) |
| `DATA_MISSING` | no path-A price evidence on E that survives §5a/§5b |
| `OTHER` | anything else, with mandatory issue-log entry |

An order is never silently marked executed without market evidence. Because no
allowed-price-range field is stored anywhere in the pipeline, price-limit constraint is
recorded only as a **diagnostic**: `price_limit_candidate = true` when the observed
session `closing_change_percent` (path-B deduplicated row) lies within ±0.1pp of ±7% or
±10%, with the raw change percent stored. This diagnostic never alters a fill.

## 8. Paper fill model (frozen)

- **A. Frozen-backtest-comparable execution:** reference fill at raw pClosing on E
  (adjusted-chain units), quantity = executed value ÷ reference price, through the
  certified accounting engine (§12).
- **B. Observed-practical diagnostic:** last-trade price (`pDrCotVal` of the E record)
  as the practical proxy where present. Path B never rewrites A.

## 9. Slippage (frozen diagnostic)

Where a path-B proxy exists and the order is `EXECUTABLE_REFERENCE`:

`slippage = (practical proxy − frozen pClosing reference) × side_sign`
(buys pay `+1`, sells `−1`; negative = worse than reference for the portfolio).

Reported in bps of reference price, rial per share, and % of order notional. Slippage is
observational only; no strategy or execution optimization is performed during the frozen
shadow period.

## 10. Transaction costs (frozen)

Research comparability convention: **50 bps one-way on absolute traded notional**
(BASE), identical to the frozen historical PRIMARY convention; GROSS/LOW/HIGH are not
recomputed in the shadow (they are historical scenarios). Actual applicable real-world
fee schedules are recorded verbatim in the issue log when canonically available; the
frozen-comparable series is never switched to a new fee assumption during the shadow
period.

## 11. Capital (frozen)

Normalized shadow NAV: **NAV = 1.0**, cash = 1.0 at inception. No real money, no
brokerage connection, no leverage, cash ≥ 0 at all times.

## 12. Portfolio accounting (frozen)

Only the certified repaired accounting engine may be used. The shadow runs
`deterministic_accounting.rebalance_accounts` — a byte-faithful port of
`portfolio_research/repair_accounting_v1.rebalance_accounts` (SHA-256 recorded in the
state file) with **sorted key iteration** replacing unordered set iteration (§13); the
port is parity-proven against the certified engine on randomized scenarios and unit
tests A–E before first use, with maximum elementwise divergence ≤ 1e-12 (observed ≤
5e-16, float-summation order only; economics identical).

Required invariants, asserted at every rebalance:

- `NAV_post = NAV_pre − cost` (exact);
- `cash ≥ 0` (financing by proportional buy-delta scaling, never target scaling);
- position continuity (held non-tradable names carried at the canonical convention);
- self-financing replay of the trade ledger;
- one stable identity per position (§4);
- cost ledger identity (`cost = 0.005 × |buys| + 0.005 × |sells|`).

Quarantined portfolio code (`execute_score_portfolio_v1.py` pre-repair artifacts) is
never imported.

## 13. Determinism (frozen engineering requirement)

The certification of SCORE_PORTFOLIO_V1 documented cross-process float differences from
unordered set iteration. Before the first shadow decision, the shadow build is made
deterministic:

- all security/order collections iterated in sorted order (`symbol`, then `ins_code`);
- deterministic summation order everywhere;
- JSON artifacts serialized with `sort_keys=True`, fixed indent;
- parquet artifacts written with fixed row order plus a canonical content hash
  (sorted-column CSV re-serialization) alongside the file hash;
- no reliance on `PYTHONHASHSEED`.

Proof: the same fixture snapshot built by 3 independent processes under different
`PYTHONHASHSEED` values (1, 2, 3) must produce byte-identical target/order/snapshot
artifacts (identical SHA-256). Result recorded as `SHADOW_BUILD_DETERMINISTIC` in the
state file. This is an engineering fix, not a strategy modification.

## 14. Monthly artifacts (frozen)

Per decision month `YYYY_MM` (month of `as_of_date`), written exactly once, never
overwritten:

- `shadow_snapshot_YYYY_MM.json` — full decision cross-section (§2 fields);
- `shadow_targets_YYYY_MM.parquet` — selected securities, weights, ranks;
- `shadow_orders_YYYY_MM.parquet` — paper orders (§6);
- `shadow_portfolio_state_YYYY_MM.json` — decision-time portfolio state (NAV, cash,
  holdings, targets) + SHA-256 of all sibling artifacts;
- `shadow_execution_observations_YYYY_MM.parquet` — per-order observation (§7/§8/§9),
  written once by the observer when the raw caches cover E (or the deadline rule in
  §15b fires);
- `shadow_execution_summary_YYYY_MM.json` — post-fill portfolio state, month returns
  (portfolio/benchmark/excess), monitoring metrics (§15), artifact hashes.

The build refuses to overwrite an existing artifact (hard error). Artifact hashes are
recorded in `shadow_v1_state.json` under the month's entry.

## 15. Monitoring metrics (frozen, reported monthly)

Per month: eligible universe size; selected holdings (with identity status); target
turnover vs prior holdings (frozen formula `0.5 × Σ|Δw|` incl. cash); paper-executed
holdings; failed/constrained orders by flag; cash %; estimated transaction costs at
50 bps; slippage diagnostic (§9); score distribution (mean/median/quartiles of
`ui_score`); DQ distribution; portfolio return; benchmark return; excess return.

Benchmark = equal-weight ALL eligible scored names of the same decision run with
identical schedule, execution reference, tradability treatment, cash treatment, return
semantics, and 50 bps costs (prereg §7), computed through the same engine; names without
computable returns are frozen failed targets and their coverage is reported.

No success/failure judgement is made from the first few observations.

### 15b. Observation deadline (frozen operational rule)

The observer writes the monthly observation artifacts on the first run where the raw
caches cover EXECUTION_DATE; names still missing are finalized `DATA_MISSING`. If the
caches do not cover E within **7 calendar days** after E, the observer finalizes the
month with `DATA_MISSING` for the uncovered names and logs the collection failure.
Before either condition holds, the observer runs in check mode only (no artifacts).

## 16. Live operational failure log (frozen)

`portfolio_shadow/SHADOW_V1_ISSUES.md` is append-only. Logged: data gaps, identity
issues, late data, collector failures, suspensions, unexpected corporate actions,
execution ambiguity, accounting exceptions, superseded/ignored score runs. Past shadow
decisions are never patched retrospectively; a discovered defect is fixed forward and
logged.

## 17. Frozen shadow period (frozen)

Minimum horizon: **12 future monthly rebalance cycles**. During the period none of the
following may change: selection percentile, score formula, rebalance schedule,
weighting, execution reference, cost convention, portfolio gates. Any material
modification creates a NEW shadow version (`SHADOW_V2...`) and resets prospective
confirmation.

## 18. Shadow performance is secondary to operational validation (frozen)

Primary questions: reproducible targets? executable selections? observed turnover vs
historical expectation? real slippage magnitude? suspension/constraint frequency? data
timeliness? accounting correctness? score/rank behavior vs the historical process?
Performance is recorded but not over-interpreted.

## 19. Future promotion boundary (frozen)

Real-money promotion is NOT automatic after 12 months. After ≥ 12 future monthly cycles,
a separately preregistered review assesses operational reliability, execution/slippage,
forward ranking and portfolio behavior, data quality, and universe/survivorship issues.
Only after that review can a real-money pilot design be considered.

## 20. No automatic trading (frozen, absolute)

Prohibited: broker API order transmission; real-money BUY; real-money SELL; automatic
account access; position changes in any brokerage account. The system may generate
`PAPER BUY` / `PAPER SELL` / `PAPER HOLD` records only. `REAL_MONEY_ORDERS_ENABLED =
NO`, `BROKER_CONNECTION_ENABLED = NO` permanently at this stage.

## 21. Initial files (frozen)

- `portfolio_shadow/SHADOW_V1_SPEC.md` (this document; SHA-256 recorded in
  `shadow_v1_state.json` before the first shadow rebalance);
- `portfolio_shadow/shadow_v1_state.json`;
- `portfolio_shadow/SHADOW_V1_ISSUES.md`;
- `portfolio_shadow/build_shadow_portfolio.py`;
- `portfolio_shadow/observe_shadow_execution.py`;
- `portfolio_shadow/deterministic_accounting.py` (engineering support, §12–§13);
- `portfolio_shadow/tests/` (fixture + parity/determinism/unit validation; clearly
  labeled TEST ONLY; never ingested as shadow observations).

No fake historical shadow observations exist. No shadow month is ingested by this
freeze; the state file starts with an empty decision list.
