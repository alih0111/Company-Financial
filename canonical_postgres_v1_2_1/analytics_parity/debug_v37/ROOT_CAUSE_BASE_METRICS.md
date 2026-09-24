# Root Cause — Base Metric Parity Failures (v3.7 vs reduced compat)

Read-only extraction of v3.7 intermediate columns was performed against
`dbo.vw_AIStockMetrics` (SELECT only) and compared with canonical shadow facts.

## 1. Unit scaling — canonical `rial` vs v3.7 `million rial` (HIGH)

The reduced compat compared canonical `canonical_value` (stored in **rial**,
`reported_value × 1e6`) directly against v3.7 monetary columns, which are in
**million rial**. Verified 1:1 offset of exactly `1e6`:

| symbol | metric | v3.7 | canonical compat | ratio |
| --- | --- | --- | --- | --- |
| فولاد | SalesLast12M | 3,862,599,517 | 3,862,599,517,000,000 | 1e6 |
| فولاد | TTMNetProfit | 962,487,084 | 962,487,084,000,000 | 1e6 |
| خودرو | SalesLast12M | 5,430,579,681 | 5,430,579,681,000,000 | 1e6 |
| خودرو | TTMNetProfit | -126,273,117 | -126,273,117,000,000 | 1e6 |

After dividing canonical monetary facts by `1e6`, فولاد/خودرو sales and TTM match
v3.7 **exactly**:

- فولاد: `NetProfitAmount` p1+p3−p2 = 120,356,493 + 1,003,954,296 − 161,823,705
  = **962,487,084** = v3.7 `TTMNetProfit`.
- خودرو: −224,803,882 + 3,085,069 − (−95,445,696) = **−126,273,117** = v3.7.

The `compromise` compat divides nothing; the `tolerances.md` note
("after ×1e6 scaling") shows the scaling was known but never applied in comparison.

## 2. TTM semantics — compat over-populates vs v3.7 (HIGH)

`compute_and_compare.ttm()` returns `d[1]` whenever period 2/3 are missing:

```python
if d[2] is not None and d[3] is not None: return d[1] + d[3] - d[2]
return d[1]     # <-- v3.7 would return NULL and fall through to Product1 path
```

v3.7 requires (month=12 ∧ amount present) or all three of
`NetProfitAmount`, `NetProfitAmountFYPrev`, `NetProfitAmountLY`; otherwise it falls
to the Product1 path and only then to NULL. This produces the 155
`NULL_SEMANTICS` mismatches (compat has a value, v3.7 NULL) and the low exact count.

## 3. Product1 absent from canonical (MEDIUM, recoverable)

v3.7's second TTM path (and PE second branch, and `TTMNetProfitP1`) use the legacy
`Product1` column, which was intentionally **not** migrated as a canonical fact
(`LEGACY_DERIVED_DO_NOT_MIGRATE_AS_FACT`). Observed exactly in raw legacy rows:

```
Product1 = Num1_Value1 (EPS) × Num2_Value1 (share count)
```

Example فولاد 1405/03: `62 × 1,935,000,000 = 119,970,000,000` = `Product1`.
Canonical migrated `Num2_Value1` as `capital` with `million_rial` (×1e6), so
`shares = capital/1e6` and `Product1 = eps × capital/1e6` is recoverable **exactly**
inside the compat layer (allowed legacy heuristic), without touching canonical facts.

## 4. Share count / EPS path — PEApprox (HIGH)

Reduced compat used `shares = capital / 1000`, but canonical `capital` was already
scaled to `rial` (×1e6), so the correct share count is `capital / 1e6`
(= legacy `Num2_Value1`). Equivalent to v3.7 `ImpliedShares = Product1 / EPS`.

- فولاد v3.7: `TTMEPS = SR_TTM × EPS / NetProfitAmount = 962,487,084 × 62 / 120,356,493 = 495.8`;
  `PE = LatestPrice / TTMEPS = 3350 / 495.8 = 6.76` (compat gave 1.02).
- `LatestPrice` in v3.7 = `COALESCE(LastPrice, ClosingPrice)`; reduced compat used
  `closing_price_rial` only (e.g. شکربن last=10100 vs close=10020 → PE 5.54).

## 5. OperatingProfit per-share normalization (`OpK`) missing (HIGH)

Canonical `operating_profit` is legacy `OperatingProfitNew` (sometimes per-share,
sometimes absolute). v3.7 computes `OpK` per report and only uses `OpAmt = OpRaw×OpK`
in amount-based ratios. The reduced compat used `operating_profit` raw against
`revenue`, producing e.g. فولاد `OperatingMargin12M` −6.62 vs v3.7 **25.05**.
`OpK`, `OpAbs`, `OpAmt/OpLYAmt/OpFYPrevAmt` are all recoverable from canonical
`operating_profit`, `eps`, `net_profit`, `revenue`.

## 6. Latest statement selection nondeterminism (MEDIUM)

The reduced compat built `fact_index[(company, metric, period_order)]` by
overwriting while iterating **all** statements ordered only by
`(company_id, period_order)`. It did not select the **latest report**
(`max period_end_date`), which is what v3.7 `ProfitDedup rn=1` uses.

## Summary of required compat fixes (base metrics)

1. Scale all monetary canonical facts `/1e6` before comparison.
2. Select the latest report per company (`max period_end_date`) and read p1/p2/p3.
3. Reimplement TTM exactly (amount path → Product1 path → NULL).
4. Recover `shares = capital/1e6`; `Product1 = eps × shares`.
5. Implement `OpK/OpAbs/OpAmt` heuristics per report.
6. Use `LatestPrice = COALESCE(last_price, closing_price)`.
