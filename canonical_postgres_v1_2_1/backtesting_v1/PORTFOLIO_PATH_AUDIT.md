# Portfolio Path Audit

## Phase-1 path inspection

Phase-1 built one return per rebalance `i` from entry `exec_i` to exit `exec_{i+1}`
(the next rebalance's execution date), then compounded. Intervals `[exec_i, exec_{i+1}]`
share only the boundary point — they do **not** overlap and no market interval is
counted twice. The fixed-horizon forward returns (`ret_5/21/63`) are used only for
cross-sectional diagnostics and are **never** compounded.

## Issues found and fixed (Phase 2)

1. **Dropped intervals.** Phase-1 `_mean` returned `None` when every member's exit
   price was missing, so those intervals were omitted from the wealth chain
   (n=61 of 65). Phase 2 introduces an explicit **cash** policy and keeps every
   interval.
2. **Contiguity check** was mis-specified; Phase 2 asserts `exit_i == entry_{i+1}`
   (result: **True**).

## Phase-2 policy (frozen)

| case | policy |
| --- | --- |
| zero tradable names | interval is **cash** (return 0.0), retained and flagged (`cash_interval=true`) |
| fewer than top-N | equal-weight the available members (no fabrication) |
| missing entry price | excluded at universe stage (`no_price_on_execution_date`) |
| missing exit / next-rebalance price | member excluded from that period; count recorded (`n_missing_exit`); member not forward-filled |

Both strategy and benchmark use the identical policy and the same dates.

## Results

| item | value |
| --- | --- |
| intervals | 65 |
| contiguous / non-overlapping | **True** |
| cash intervals | 4 (`2026-01-31`, `2026-02-25`, `2026-03-31`, `2026-04-29`) |
| zero-tradable dates | `2026-02-25`, `2026-03-31`, `2026-04-29` (calendar gaps in canonical prices) |
| missing exits excluded | 77 member-observations |
| portfolio cumulative (gross) | 7.214 (721%) — **identical** to Phase 1 |
| benchmark cumulative | 2.496 (250%) |

## Conclusion

The Phase-1 **+721% portfolio path was accounting-valid** (contiguous, non-overlapping,
single chronological wealth stream). The only defect was that 4 cash intervals were
dropped rather than retained; because they carry a 0% return, compounding them leaves
the cumulative unchanged. Phase-2 rebuild is the authoritative path.
