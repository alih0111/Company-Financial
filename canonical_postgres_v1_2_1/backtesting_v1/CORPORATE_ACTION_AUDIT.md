# Corporate-Action Audit (before trusting returns)

## Finding

`market.corporate_actions` is **empty** (0 rows; min/max `action_date` = NULL).
There is therefore **no canonical basis** to reconstruct adjusted or total returns.

## Required actions and coverage

| action type | canonical coverage |
| --- | --- |
| splits | none |
| capital increases | none |
| cash dividends | none |
| other | none |

## Decision (Phase 1)

The baseline runs a **clearly labeled raw price-return** backtest:
`return_convention = "raw_price_return"`, using canonical `closing_price_rial` only.
No adjustment factors are invented, and raw price returns are **not** asserted to
equal investor total returns. `summary_metrics.json` records
`corporate_actions_available = false`.

## Limitation

Raw price returns overstate/understate true returns around corporate actions
(especially capital increases and dividends common on the Tehran market). Any
subsequent interpretation must treat results as price-return association, not
realizable total return. A later phase may add a canonical corporate-action-driven
adjusted/total-return series once coverage exists.

## Phase-2 return-integrity diagnostic (`raw_return_discontinuities.csv`)

No corporate action is inferred from prices. Instead, extreme one-day raw-price
moves are flagged as **`POSSIBLE_CORPORATE_ACTION_OR_DATA_EVENT`** (threshold
|close-to-close return| ≥ 25%).

| item | value |
| --- | --- |
| flagged events | **1,250** |
| top-20 strategy exposure (event inside holding interval) | 6 (0.484%) |
| benchmark exposure | 21 (0.16%) |
| corporate_actions rows (fabricated for this) | **0** |

The strategy's exposure to extreme events is small and only modestly above the
benchmark; results are not driven by a handful of price jumps. Flagging is a
robustness diagnostic only and does **not** create a new return series; canonical
market data is untouched.
