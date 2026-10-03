# Point-in-Time Contract (Backtesting v1)

## 1. Signal snapshot

At evaluation date `T`, the signal snapshot is produced by
`analytics_canonical_v1.compute_metrics.Engine(as_of=T, cutoff=end_of_day_T)` and
frozen. Only data visible at `T` may enter.

| source | eligibility at `T` |
| --- | --- |
| `ingestion.reports` / `report_versions` / `parse_runs` | report with `published_at <= T`; legacy synthetic reports (no `published_at`) use `period_end_date <= T` |
| `fundamentals.financial_statements` / `financial_facts` | `period_end_date <= T` (or `published_at <= T`); superseded reports excluded |
| `fundamentals.monthly_activities` | `period_end_date <= T` |
| `market.price_observations` | **`trade_date <= T`** (historical mode) |
| `market.corporate_actions` | `action_date <= T` (currently empty) |
| report-chain TTM | all three legs drawn from the PIT-filtered report index; a later correction/future report cannot enter |

## 2. Documented market-PIT limitation (important)

Canonical `market.price_observations.collected_at` is **migration ingestion time**
(2026-07-30 … 2026-09-24), not historical availability. Using
`collected_at <= T` for a historical `T` returns nothing, so the engine's default
market-PIT mode cannot reconstruct history.

The backtester therefore uses an explicit, opt-in **`market_pit="trade_date"`** mode:
a price for `trade_date = d` is considered available at end of `d`. This prevents
future prices from leaking while remaining PIT-safe. The production/default engine
behavior (`collected_at`) is unchanged.

Impact: market factors are reconstructed from `trade_date`; the initial baseline is
valid on this convention. A future data fix could populate true per-row
availability timestamps.

## 3. Signal vs execution vs return

* **Signal date `T`**: snapshot uses data through end of `T` (close of `T` included
  in price-derived factors).
* **Execution date**: the **first trading date strictly after `T`**
  (`next_trading_day_close`) — never same-close, to avoid look-ahead.
* **Exit**: entry + H trading days (`exit_after`), H ∈ {5, 21, 63} for diagnostics;
  portfolio holding uses the next rebalance's execution date.
* Forward returns are computed **only after** all snapshots are frozen.

## 4. Anti-look-ahead tests

`tests/test_backtest_v1.py`: future report rejection, future correction rejection,
future price rejection (trade_date mode), report-chain missing-leg safety,
signal/execution separation, no survivorship from a static universe.

## 5. Source-class contract (architecture decision, 2026-10-01)

PIT is **source-class specific**. One temporal rule is not correct for every
source, because different sources have different notions of "when it existed"
and "when we could know it".

### 5.1 Archival (source-backed) disclosures

Codal financial reports, Codal LT28 capital-registration notices, and any other
historical disclosure that carries a trustworthy real `published_at`.

```
eligible(as_of, cutoff)  IFF  economic/effective_date <= as_of
                              AND published_at <= cutoff
```

* `published_at` = the source's own publication time. This is the **knowledge
  gate** for archival evidence.
* `collected_at` = the real acquisition/backfill timestamp. It is **lineage
  only**; it is never the knowledge gate, and it is never backdated.
* A backfilled archival document is therefore usable in historical research when
  its authentic `published_at` precedes the signal cutoff, *even though* it was
  acquired much later. Re-acquiring an old document does not change when the
  world could have known its contents.
* Historical fundamental evaluation in
  `analytics_canonical_v1/compute_metrics.py::Engine.load()` already implements
  exactly this rule (`published_at <= cutoff`, with `period_end_date <= as_of` as
  the legacy fallback when `published_at IS NULL`).

### 5.2 Observed snapshots

`core.share_structure` (BRS) and similar vendor observations are **bitemporal
observations**:

```
eligible(as_of, cutoff)  IFF  as_of_date <= as_of AND collected_at <= cutoff
```

An observation did not exist before it was observed, so today's snapshot can
never be projected backwards. This behavior is unchanged.

### 5.3 Valid time and knowledge time (two independent axes)

| axis | question | column |
| --- | --- | --- |
| valid time | when does the fact apply economically? | `valid_from` / `valid_to`, `effective_date`, `as_of_date` |
| knowledge time | when could it be known? | `published_at` (archival), `collected_at` (observation) |

A fact is usable in a historical simulation only when **both** axes pass. A
later-backfilled document may establish an older economic state for research
whose cutoff is on/after its publication; it must never make that state visible
to a signal whose cutoff precedes the publication.

### 5.4 Knowledge aggregation for derived values

When a derived value (for example a reconstructed historical share count)
depends on several facts:

```
knowledge_from = MAX(published_at of all REQUIRED evidence)
```

Optional cross-check sources are never part of the maximum — they would delay
availability without being necessary. Every contributing source id is retained
in the interval's lineage. An amendment whose economics are unchanged does not
move `knowledge_from`; an amendment that supplies a REQUIRED field absent from
the original does.

### 5.5 Superseded statement

`historical_codal_backfill/PIT_SAFETY_REPORT.md` states that recovered reports
are excluded from historical computations because their `collected_at` (2026) is
after the historical cutoff. **That statement is SUPERSEDED and inconsistent with
the canonical engine contract** as implemented since the archival rule above:
eligibility for archival disclosures is decided by `published_at`, not by
`collected_at`. Measured on the live database at `as_of = cutoff = 2022-06-30`,
1,468 Codal facts with `published_at <= cutoff` (and 0 with
`collected_at <= cutoff`) are eligible, and the engine returns
`net_profit_ttm` for کاسپین from them. The safety report's *intent* — never
invent or backdate an availability window — remains in force and is exactly what
`collected_at` being real and unmodified guarantees.

### 5.6 Share history

`core.share_events` / `core.share_intervals` follow the archival rule for the
knowledge axis. `share_history.interval_eligible()` implements
`valid_from <= as_of < valid_to AND knowledge_from <= cutoff`; the vendor anchor
interval takes its `knowledge_from` from the snapshot's own `collected_at`,
which is what keeps the current share count out of every historical cutoff.

## 6. Historical share counts — two-source design (2026-10-02)

Share counts and their knowledge time come from two independent sources, joined
per event. Neither is sufficient alone.

| role | source | field |
| --- | --- | --- |
| **historical share counts** (PRIMARY) | TSETMC `Instrument/GetInstrumentShareChange/{insCode}` | `numberOfShareOld`, `numberOfShareNew` |
| **exchange-side valid-time candidate** | same response | `dEven` — labelled **`EXCHANGE_SHARE_STATE_DATE`** |
| **knowledge time** (PRIMARY) | matched Codal LT28 disclosure | `published_at` |
| **current anchor** | TSETMC `Instrument/GetInstrument` `zTitad`, cross-checked with BRS `core.share_structure` | |

Frozen temporal rule for a matched event:

```
valid_from     = TSETMC.dEven
knowledge_from = Codal matched LT28 published_at
usable         IFF valid_from <= as_of AND knowledge_from <= cutoff
```

Consequences, all intentional:

* A change whose `dEven` precedes its Codal publication is **not** visible to
  signals between those dates. Measured on the pilot: 132 such cases.
* `dEven` is **never** used as knowledge and **never** written as
  `market_ex_date`; `market_ex_date` stays NULL and `market.corporate_actions`
  stays empty.
* TSETMC supplies no publication/revision history, so an unmatched TSETMC event
  (`NO_CODAL_MATCH`) carries `knowledge_from = NULL` and is never PIT-eligible.
* **Share counts are never derived from `capital / 1000`.** Codal capital is a
  reconciliation input only. Nominal value is no longer required for valuation.
* The state before the first TSETMC event has no source-stated start, so the
  frozen check (`KNOWN` requires `valid_from`) keeps it
  `HISTORICAL_SHARES_UNKNOWN`. Every pilot company's first event precedes the
  signal window, so this costs no coverage.

Precedence and disagreement handling: TSETMC is authoritative for the **count**;
Codal is authoritative for the **timing of public knowledge**. `zTitad` and BRS
must agree with the last event's `numberOfShareNew`; a disagreement is reported,
never silently overwritten. An event whose Codal capital ratio contradicts its
TSETMC ratio is graded `MATCH_AMBIGUOUS` rather than accepted.
