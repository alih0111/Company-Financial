# MARKET OBSERVATION HASH CONTRACT

## 1. Problem

`market.price_observations` is append-only and deduplicated by
`UNIQUE (security_id, trade_date, source, price_series, observation_hash)`.
The full-universe migration and the new live dual-write writer computed
`observation_hash` with different serializations, so the same logical
observation could be appended twice (once by each writer).

## 2. Decision (least invasive, no historical rewrite)

1. **Stable hash contract for new writes** — `canonical_ingest.writer._observation_hash`:
   `sha256("|".join([security_id, trade_date, source, price_series,
   first_price_rial, open_price_rial, high_price_rial, low_price_rial,
   closing_price_rial, last_price_rial, yesterday_price_rial,
   closing_change_rial, closing_change_percent, last_change_rial,
   last_change_percent, volume, trade_value_rial, trade_count]))`.
   It is deterministic, depends only on canonical payload fields, and never on
   wall-clock time.

2. **Natural-key compatibility lookup** — before inserting, the writer checks
   for an existing row with the same `(security_id, trade_date, source,
   price_series, closing_price_rial, volume, trade_value_rial)`. If present it
   returns that row id and **does not insert**, regardless of hash differences
   from historical writers.

This satisfies both goals: new ingestion is idempotent under its own hash, and
it does not duplicate observations already written by the migration under a
different hash serialization.

## 3. Why not canonicalise historical hashes

Rewriting ~705k historical `observation_hash` values would mutate append-only
lineage, risk collisions, and is unnecessary: the natural-key lookup prevents
duplicates and the historical rows remain valid. Per task guidance, historical
observations were **not** rewritten.

## 4. Compatibility check

Verified against the shadow DB: rerunning the market dual-write for the same
rows appends nothing (second run `inserted=0`, natural-key/hash skip). Existing
historical rows are matched by natural key where present.

## 5. Residual note

A small number of duplicate `(security, trade_date, brs)` rows existed in the
shadow DB from earlier Phase-1 experiments with a different hash; these are
pre-existing test artifacts, not produced by this contract, and were left
untouched (append-only). New writes follow the contract above.
