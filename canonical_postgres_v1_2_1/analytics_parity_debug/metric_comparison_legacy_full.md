# Full v3.7 compat over 276 legacy subjects — metric comparison

| reference column | compared | exact | within tol | mismatch | max abs |
| --- | --- | --- | --- | --- | --- |
| SalesLast12M | 276 | 276 | 0 | 0 | 0 |
| SalesPrev12M | 276 | 276 | 0 | 0 | 0 |
| SalesGrowth12M | 276 | 91 | 185 | 0 | 0.00498249 |
| TTMNetProfit | 276 | 276 | 0 | 0 | 0 |
| PEApprox | 276 | 39 | 237 | 0 | 0.005 |
| QuantScore | 276 | 276 | 0 | 0 | 0 |
| OperatingMargin12M | 276 | 132 | 144 | 0 | 0.00494124 |
| NetProfitMargin12M | 276 | 172 | 104 | 0 | 0.00499958 |
| ROE | 276 | 174 | 102 | 0 | 0.00497438 |

## Rank factor parity

| factor rank | compared | exact | within 0.01 | mismatch | max abs |
| --- | --- | --- | --- | --- | --- |
| CashConversionRank | 276 | 196 | 80 | 0 | 5e-05 |
| CurrentRatioRank | 276 | 174 | 102 | 0 | 4.951e-05 |
| EarningsQualityRank | 276 | 142 | 134 | 0 | 4.962e-05 |
| InterestCoverageRank | 276 | 162 | 114 | 0 | 4.828e-05 |
| LeverageRank | 276 | 180 | 96 | 0 | 4.615e-05 |
| LiquidityRank | 276 | 16 | 260 | 0 | 4.815e-05 |
| LowVolatilityRank | 276 | 12 | 264 | 0 | 4.962e-05 |
| MarginTrendRank | 276 | 134 | 142 | 0 | 4.965e-05 |
| MomentumRank | 276 | 19 | 257 | 0 | 4.981e-05 |
| NetMarginRank | 276 | 173 | 103 | 0 | 4.951e-05 |
| NetProfitGrowthRank | 276 | 16 | 260 | 0 | 4.981e-05 |
| OperatingMarginRank | 276 | 133 | 143 | 0 | 4.965e-05 |
| OperatingProfitGrowthRank | 276 | 16 | 260 | 0 | 4.848e-05 |
| PBRank | 276 | 192 | 84 | 0 | 4.545e-05 |
| PERank | 276 | 58 | 218 | 0 | 4.545e-05 |
| PSRank | 276 | 188 | 88 | 0 | 4.545e-05 |
| ROERank | 276 | 175 | 101 | 0 | 4.95e-05 |
| RevenueGrowthRank | 276 | 151 | 125 | 0 | 4.921e-05 |
| SalesGrowth3MRank | 276 | 99 | 177 | 0 | 4.783e-05 |
| SalesGrowthRank | 276 | 99 | 177 | 0 | 4.783e-05 |
| StabilityRank | 276 | 99 | 177 | 0 | 5e-05 |

**Base metrics + 21 rank factors + QuantScore: 0 mismatch at tolerance.**
