# Metric Comparison (canonical v3.7-compat vs SQL Server v3.7)

| reference column | compared | exact | within tol | mismatches | max abs diff | median abs diff |
| --- | --- | --- | --- | --- | --- | --- |
| SalesLast12M | 273 | 83 | 0 | 190 | 1.34346e+16 | 4.56936e+13 |
| SalesPrev12M | 273 | 83 | 0 | 190 | 4.65846e+15 | 2.69377e+13 |
| SalesGrowth12M | 273 | 89 | 181 | 3 | 0.00498249 | 0.00250491 |
| TTMNetProfit | 273 | 16 | 0 | 257 | 2.03113e+15 | 1.79352e+13 |
| PEApprox | 273 | 28 | 4 | 241 | 51.912 | 5.28259 |
| QuantScore | 273 | 0 | 0 | 273 | 35.92 | 15.13 |
| OperatingMargin12M | 273 | 131 | 6 | 136 | 97.16 | 9.21331 |
| NetProfitMargin12M | 273 | 171 | 84 | 18 | 34.1691 | 0.00298206 |
| ROE | 273 | 171 | 86 | 16 | 2813.58 | 0.00281451 |

- canonical companies compared: 273; reference rows: 276
- output hash: `4d083cfcdf1d7f9e1cdf2984e5bf761a17cf9148995ae5adcd51842ae85a74cc`
