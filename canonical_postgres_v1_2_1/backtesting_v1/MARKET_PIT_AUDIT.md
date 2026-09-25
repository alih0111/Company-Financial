# Market PIT / Revision Audit

## 1. `collected_at` is not historical availability

Canonical `market.price_observations.collected_at` ranges only over
**2026-07-30 … 2026-09-24** (migration ingestion time), for all 705,812 rows.
It therefore cannot reconstruct historical availability. The production engine's
default market PIT (`collected_at <= cutoff`) is unchanged; the backtester uses an
opt-in `market_pit="trade_date"` proxy (a price for `trade_date = d` is available
at end of `d`). This prevents future-price leakage but is a proxy, documented here.

## 2. Revision diagnostics (`market_revision_diagnostics.csv`)

| metric | value |
| --- | --- |
| observations | 705,812 |
| distinct `(security_id, trade_date)` keys | 705,685 |
| keys with >1 observation | **126** |
| keys with conflicting `closing_price_rial` | **126** |
| conflicting share | **0.0179%** |
| distinct `price_series` | 1 (`adjusted`) |
| distinct `source` | 1 (`brs`) |
| distinct `adjustment_version` | 1 (`legacy_brs_adjusted`) |

99.982% of security-dates have exactly one immutable observation. 126 keys have
conflicting values; because all `collected_at` are migration-time, their historical
revision ordering **cannot be reconstructed** → flagged `pit_ambiguous=true`.

## 3. Decision

* For 99.982% of keys, `trade_date <= T` PIT is acceptable and immutable.
* The 126 ambiguous keys are a negligible share; the backtester does not silently
  pick a revision — they are flagged. Their contribution is not distinguishable
  historically; this is bounded and disclosed.
* No historical market value was altered.

## 4. Additional market-data limitation (found in Phase 2)

`trade_value_rial` is non-null for only **9,382 / 705,812** rows, all in **2026**.
Historical trade value is absent, so the **Liquidity factor is neutral (0.0) for all
historical signals** and cannot be measured. `volume` and `closing_price_rial` are
fully populated, so volatility/momentum are unaffected. This is a canonical data
limitation, not a model change.
