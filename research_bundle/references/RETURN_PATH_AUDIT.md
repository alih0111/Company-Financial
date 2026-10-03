# RETURN PATH AUDIT (PHASES 1–3) — RETURN_SERIES_CORPORATE_ACTION_INTEGRITY

Frozen: 2026-10-02. Read-only audit; nothing modified. Companion to
`CORPORATE_ACTION_AUDIT.md` (which declared `RETURN_SERIES_NOT_PROMOTION_GRADE`).

## PHASE 1 — the exact historical return path (code trace)

**Chain** (factor IC, Model v2, Model v2.1, portfolio metrics all consume the same target):

1. `phase3_validation.py::build_signals` — per monthly rebalance date `T` (2021-01 … 2026-06,
   63 dates): snapshot via `build_snapshot(T)` (PIT, frozen), `exec_date = cal.next_trading_day(T)`,
   then `fwd = compute_forward_returns(price_store, cal.dates, sigs, [5, 21, 63])`
   (`phase3_validation.py:144-152`) → written to `output/phase3_signals.csv` as
   `ret_5 / ret_21 / ret_63` (+ `execution_date`, `entry_price`). The CSV is FROZEN
   (`phase3_signals.sig` hash sidecar) and is the single return source for every model run.
2. `forward_returns.py::forward_return` (lines 29-36): `ret = close(exit)/close(entry) − 1`
   where `close()` is an **exact-date** lookup — no carry-forward, no interpolation.
   Missing close on either date ⇒ `None` ⇒ row excluded (IC pairs need ≥5; portfolio
   selection filters `ret_21 is not None`).
3. `forward_returns.py::resolve_execution_date` (16-19): entry = **first trading day strictly
   after the signal date** (no same-close look-ahead). `exit_after` (22-26): exit = entry + H
   **trading days** (H ∈ {5,21,63}) on the union calendar of all trade dates.
4. `market_data.py::load_price_store` (73-84):
   `SELECT security_id, trade_date, closing_price_rial FROM market.price_observations`
   — **no `price_series` filter**; `PriceStore` keeps the LAST row per (security, date).
5. `config.py:29`: `return_convention = "raw_price_return"` — **label is a misnomer, see below**.
   `rebalance_freq="M"`, `execution_convention="next_trading_day_close"`, TOP_N=20 equal
   weight, cost 10 bps/side (model_v2.py:27-31).

**Rebalance-date semantics**: signal at close of month-end date T; entry at next trading day's
close; exit at entry+H trading days. **Horizons** are trading-day based, not calendar days.
**Delisting/suspension**: no explicit handling — a security without a close on the exact
entry/exit calendar date yields `None` and the row drops out of IC pairs and portfolio
selection (implicit survivor-within-horizon behavior; documented here, unchanged).

### What the price actually is

`market.price_observations` contains **ONLY `price_series='adjusted'` rows** (no unadjusted
series exists in canonical):

| price_series | adjustment_method | rows | securities | span |
|---|---|---|---|---|
| adjusted | vendor_adjusted | 705,812 | 273 | 1991-11-20 … 2026-09-24 |
| adjusted | **NULL** (later `brs_daily` backfill) | 5,546 | 320 | 2018-06-09 … 2026-09-30 |

**Audit finding A1 (pre-existing, bounded):** 1,163 duplicate `(security_id, trade_date)`
groups (2,612 rows) exist between the two variants; `PriceStore` last-row-wins is load-order
dependent. Affected symbols are mostly non-corporate instruments (عیار, ناب, نگین فارس) and
2026-08+ dates (زگلدشت, قاسم) — i.e. partly inside the Forward diagnostic window. Quantified
as a finding; NOT patched in this task (raw tables untouched).

**Audit finding A2 (label correction):** the series is **not raw** — it is the vendor
(TSETMC-style) *capital-adjusted* close migrated from legacy `MarketPriceHistory`
(`provenance = {"script": "brs_prices", "legacy_table": "MarketPriceHistory"}`). Empirical
proof: دارو ×19.92 capital event — stored series 1,199 (2025-07-23) → 1,163 (2025-08-31)
across the halt, i.e. **continuous**; raw closes are 25,420 → 1,280 (see Phase 3). The
vendor adjustment is a black box: no factor list, no event dates, no `market_ex_date`
anywhere. `RETURN_SERIES_NOT_PROMOTION_GRADE` remains correctly ACTIVE: the *level* is
adjusted, the *adjustment* is unauditable.

**Dividends**: initially hypothesized unadjusted (TSETMC adjusted-candle convention); the
Phase 6 pilot **refuted this** — see below and `historical_codal_backfill/
pilot_return_adjustment.json`. The vendor series adjusts BOTH capital events and cash
dividends. No dividend *evidence tables* exist in the DB (no columns/tables;
`vendor_snapshots` is empty) — the adjustment exists only inside the price levels.

### Phase 6 pilot results (correct the record; full data in pilot_return_adjustment.json)

Base-field identification: `closing_price_rial` tracks `pDrCotVal` (آخرین قیمت, last-trade
price) × a constant backward factor — NOT `pClosing` (قیمت پایانی, official weighted close).
Exact-constant check: دارو 2025-06-01..07-10 vendor/pDrCotVal = 0.04715 (5+ days identical).
**Audit finding A3: the entire model history was validated on last-trade-price levels, not
the official closing price.** Documented; not changed retroactively.

Event semantics (official gap rule on RAW series + cached share-change economics):
- دارو: 27 gaps = 9 capital increases (each matched to a share-change record; ×19.92 in
  2025 with funding tags bonus+rights from cached LT28 bodies) + 18 cash dividends.
- انرژی: 3 capital (matching the three resolved-EXACT share intervals) + 7 dividends.
- وبملت: 8 capital + 9 dividends; فولاد: 10 capital + 21 dividends; ثتران: 1 capital.
- Vendor F-step test (F = vendor/pDrCotVal, last row ≤ cum vs first row ≥ ex, span ≤ 20d):
  **capital ADJUSTED 20/20 verifiable (0 continuous); dividend ADJUSTED 39/51** — every
  "miss" explained: 10 measurement windows merged with an adjacent capital event (same
  vendor step), webmelt 2026-07-25 falls after the vendor's last migration (staleness),
  gap≈1.0003 noise. The vendor series ≡ Mode 1 (capital + dividends), backward-adjusted,
  sparse grid (e.g. دارو 2025-07-23 → 2025-08-31 with no rows across the ×19.92 halt).

**Phase 6 conclusion**: adjustment semantics are proven and reproducible from
(raw series + cached share economics + official gap rule). The promotion-grade deficit of
the current path is therefore NOT missing dividend/capital adjustment — it is
**auditability and completeness**: no factor list, no event dates, no provenance, sparse
grid, and post-migration staleness (وبملت 2026 dividend unadjusted in the vendor series).

## PHASE 2 — local corporate-action evidence inventory

| # | Source (local) | Content | Corporate-action value |
|---|---|---|---|
| 1 | `market.price_observations` | vendor capital-adjusted closes 1991-2026 | implied continuity; NOT auditable |
| 2 | `output/tsetmc_share/` (238 symbols) | `GetInstrumentShareChange` 1,227 events (dEven, old, new) + `GetInstrument` zTitad | capital/share-change economics; dEven = share-state date, **NOT ex-date** |
| 3 | `output/lt28_search.json` | 1,158 LT28 letters (TracingNo, Title, PublishDateTime) | announcement evidence + knowledge time |
| 4 | `output/lt28_bodies/` (708 cached) | parsed capital_before/after (rial), registration_date, meeting_date, nominal_value | capital event economics (reconciliation) |
| 5 | `output/lt28_bodies_index.json` | classification + parsed payloads for the above | same |
| 6 | `backtesting_v1/output/raw_return_discontinuities.csv` | 1,250 moves ≥25% on the ADJUSTED series (1998-2026) | dividend ex-date candidates (capital events are adjusted away) |
| 7 | `output/pilot_chain.json`, `darou_capital_chain.json` | Darou + pilot economics (8 transitions) | ground truth for the pilot |
| 8 | `market.corporate_actions` | 0 rows; schema ready (`action_type` CHECK ∈ capital_increase/cash_dividend/stock_dividend/split/reverse_split/rights_issue/merger/other; adjustment_factor; is_confirmed; detected_heuristically; metadata) | the target table |
| 9 | `market.vendor_snapshots` | **0 rows** | — |
| 10 | fundamentals/analytics schemas | **no dividend/DPS columns anywhere** | — |

Missing locally: raw (unadjusted) daily prices; any dividend evidence. ⇒ Phase 3.

## PHASE 3 — TSETMC adjustment-source evaluation (no semantics assumed)

Probed candidates (raw responses preserved under `historical_codal_backfill/output/
tsetmc_probe/`, paced ≥1.5 s):

- 11 guessed `cdn.tsetmc.com/api/Instrument/Get*Adjustment*/Get*Dividend*/Get*CapitalIncrease*`
  endpoints → **HTTP 404** (names do not exist).
- `service.tsetmc.com/tsev2/data/TseClient2.aspx` — `?t=LastPossibleDeven` → HTTP 200
  (`20260930`), but `?t=ClosingPrices&a=…` → **HTTP 500** (legacy client channel; retired for
  direct fetch). Documented (m-ahmadi/tse-client) as serving RAW prices + a per-instrument
  share feed, with the **official adjustment algorithm** implemented client-side.
- **VALIDATED: `GET https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{insCode}/0`**
  → HTTP 200 JSON `closingPriceDaily[]` = **RAW (unadjusted) daily history**:
  `{dEven, pClosing, priceYesterday, priceFirst, priceMin, priceMax, pDrCotVal, zTotTran,
  qTotTran5J, qTotCap, priceChange}`. Darou: 5,055 rows (2002→2026); انرژی: 1,507 rows
  (2020→2026). Raw-ness validated against the known ×19.92 event: pClosing 25,420
  (2025-07-23) → cliff → 1,280 (2025-07-29), while the vendor series stays continuous.

**Event semantics recovered from the official TSE adjustment algorithm** (verbatim port in
tse-client `adjust()`; the same logic TSETMC's own app uses):

- An **event** = price discontinuity between consecutive trading days:
  `prev_day.pClosing != this_day.priceYesterday` (TSETMC re-bases `priceYesterday` at events).
- Classification: a share-change record (`GetInstrumentShareChange`, already cached) whose
  date matches ⇒ **capital increase** with old/new shares; otherwise ⇒ **dividend** with
  amount = `priceBefore − priceAfter` (per share, from the gap).
- `event date` = last cum-trading date (the day BEFORE the gap); **ex-date** = the gap day.
- Two adjustment modes: Mode 1 coef *= priceBefore/priceAfter (capital + dividends);
  Mode 2 coef *= newShares/oldShares (capital only).

**Cross-validation on انرژی** (resolved-EXACT share events from §48): price gaps at
2021-07-04 (÷3.0), 2023-07-25 (÷1.5), 2025-07-27 (÷1.5) — exactly the three share-change
interval starts; 7 further small gaps (40-100 rial) classify as dividends.

**Critical two-axis evidence (Phase 5):** دارو's price re-bases at **2025-07-29** while its
share-change `dEven` is **2025-08-21** (23 days apart). dEven is NOT the ex-date. The frozen
distinction is not theoretical; it is measurable.

**Conclusion**: a promotion-grade, auditable adjustment series is constructible from
(a) RAW daily history (this endpoint), (b) cached share-change economics, (c) the official
gap-based event detection — with the vendor series as an independent cross-check
(hypothesis: vendor ≡ Mode 2, capital-only; tested in Phase 6).
