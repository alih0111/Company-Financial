# Faithful v3.7 compat — metric comparison

| reference column | compared | exact | within tol | mismatch | max abs |
| --- | --- | --- | --- | --- | --- |
| SalesLast12M | 273 | 273 | 0 | 0 | 0 |
| SalesPrev12M | 273 | 273 | 0 | 0 | 0 |
| SalesGrowth12M | 273 | 89 | 184 | 0 | 0.00498249 |
| TTMNetProfit | 273 | 265 | 0 | 8 | 7.3673e+10 |
| PEApprox | 273 | 36 | 230 | 7 | 106.013 |
| QuantScore | 273 | 11 | 12 | 250 | 11.68 |
| OperatingMargin12M | 273 | 132 | 141 | 0 | 0.00494124 |
| NetProfitMargin12M | 273 | 172 | 101 | 0 | 0.00499958 |
| ROE | 273 | 174 | 99 | 0 | 0.00497438 |

- canonical companies computed: 273; reference rows: 276

## Rank factor parity (v3.7 rank columns)

| factor rank | compared | exact | within 0.01 | mismatch | max abs |
| --- | --- | --- | --- | --- | --- |
| CashConversionRank | 273 | 179 | 75 | 19 | 0.01546 |
| CurrentRatioRank | 273 | 172 | 87 | 14 | 0.0122 |
| EarningsQualityRank | 273 | 140 | 125 | 8 | 0.01092 |
| InterestCoverageRank | 273 | 158 | 113 | 2 | 0.009415 |
| LeverageRank | 273 | 171 | 95 | 7 | 0.01114 |
| LiquidityRank | 273 | 1 | 270 | 2 | 0.007259 |
| LowVolatilityRank | 273 | 5 | 266 | 2 | 0.004591 |
| MarginTrendRank | 273 | 132 | 117 | 24 | 0.01161 |
| MomentumRank | 273 | 12 | 258 | 3 | 0.3 |
| NetMarginRank | 273 | 171 | 95 | 7 | 0.0114 |
| NetProfitGrowthRank | 273 | 13 | 149 | 111 | 0.5939 |
| OperatingMarginRank | 273 | 131 | 140 | 2 | 0.006986 |
| OperatingProfitGrowthRank | 273 | 8 | 261 | 4 | 0.4234 |
| PBRank | 273 | 180 | 91 | 2 | 0.003659 |
| PERank | 273 | 37 | 139 | 97 | 0.7855 |
| PSRank | 273 | 176 | 95 | 2 | 0.003788 |
| ROERank | 273 | 173 | 92 | 8 | 0.01159 |
| RevenueGrowthRank | 273 | 148 | 123 | 2 | 0.005049 |
| SalesGrowth3MRank | 273 | 88 | 183 | 2 | 0.005249 |
| SalesGrowthRank | 273 | 88 | 183 | 2 | 0.003135 |
| StabilityRank | 273 | 82 | 189 | 2 | 0.00959 |
